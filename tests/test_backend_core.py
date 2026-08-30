from __future__ import annotations

import json
import unittest
from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.analyzer import (
    SearchResultAnalyzer, _extract_json, _fallback_query_understanding, _fallback_themes,
    candidate_pairs,
)
from backend.config import get_settings
from backend.engine import MockSearchEngine
from backend.result_formatter import format_result
from backend.schemas import ModelSearchRequest, PaperAnalysis, SearchOptions
from types import SimpleNamespace


class ResultFormatterTest(unittest.TestCase):
    def test_extract_json_accepts_fenced_output_and_ignores_following_objects(self) -> None:
        value = _extract_json(
            '分析如下：```json\n{"direct_answer":"结论","themes":[]}\n```'
            ' 补充诊断：{"ignored":true}'
        )

        self.assertEqual("结论", value["direct_answer"])
        self.assertNotIn("ignored", value)

    def test_selector_batch_size_is_bounded_to_a_positive_value(self) -> None:
        self.assertGreaterEqual(get_settings().selector_batch_size, 1)
        self.assertGreaterEqual(get_settings().selector_threshold, 0)
        self.assertLessEqual(get_settings().selector_threshold, 1)

    def test_deduplicates_by_arxiv_id_and_keeps_highest_score(self) -> None:
        tree = {
            "child": {
                "query": [
                    {
                        "arxiv_id": "2501.00001",
                        "title": "Paper A",
                        "abstract": "first",
                        "select_score": 0.4,
                        "depth": 0,
                        "source": "Search",
                        "child": {
                            "section": [
                                {
                                    "arxiv_id": "2501.00001",
                                    "title": "Paper A",
                                    "abstract": "better",
                                    "select_score": 0.9,
                                    "depth": 1,
                                    "source": "Expand",
                                    "child": {},
                                }
                            ]
                        },
                    }
                ]
            }
        }

        result = format_result("request", "query", tree)

        self.assertEqual(result.summary.paper_count, 1)
        self.assertEqual(result.summary.selected_count, 1)
        self.assertEqual(result.papers[0].score, 0.9)
        self.assertEqual(result.papers[0].abstract, "better")

    def test_result_formatter_uses_the_search_run_selector_threshold(self) -> None:
        tree = {
            "extra": {"selector_threshold": 0.7},
            "child": {"query": [{
                "arxiv_id": "2501.00001", "title": "Borderline paper",
                "abstract": "abstract", "select_score": 0.65, "depth": 0,
                "source": "Search", "extra": {}, "child": {},
            }]},
        }

        result = format_result("request", "query", tree)

        self.assertFalse(result.papers[0].selected)

    def test_deduplicates_cross_provider_records_by_normalized_title(self) -> None:
        tree = {"child": {"query": [
            {
                "arxiv_id": "2012.02190", "title": "pixelNeRF: Neural Radiance Fields",
                "abstract": "arxiv", "select_score": 0.8, "depth": 0,
                "source": "Search arxiv", "extra": {}, "child": {},
            },
            {
                "arxiv_id": "", "title": "pixelNeRF: Neural Radiance Fields",
                "abstract": "openalex", "select_score": 0.7, "depth": 0,
                "source": "Search openalex", "extra": {"openalex_id": "W1"}, "child": {},
            },
        ]}}

        result = format_result("request", "query", tree)

        self.assertEqual(1, result.summary.paper_count)
        self.assertEqual("2012.02190", result.papers[0].arxiv_id)

    def test_theme_rules_cover_known_domains_and_dynamically_name_long_tail_topics(self) -> None:
        papers = [
            SimpleNamespace(
                paper_id="p1", title="Variational Quantum Circuit Optimization",
                abstract="A quantum machine learning method.",
            ),
            SimpleNamespace(
                paper_id="p2", title="Acoustic Levitation for Contactless Assembly",
                abstract="We study contactless assembly with acoustic levitation.",
            ),
        ]
        analyses = [PaperAnalysis(paper_id=paper.paper_id) for paper in papers]

        themes = _fallback_themes("compare emerging computing approaches", papers, analyses)

        names = [theme.name for theme in themes]
        self.assertIn("量子计算与量子机器学习", names)
        self.assertTrue(any("levitation" in name.lower() or "acoustic" in name.lower() for name in names))
        self.assertNotIn("Other relevant approaches", names)
        self.assertEqual({"p1", "p2"}, {paper_id for theme in themes for paper_id in theme.paper_ids})

    def test_theme_routing_prefers_title_specific_planning_over_generic_abstract_terms(self) -> None:
        paper = SimpleNamespace(
            paper_id="p1",
            title="Can LLM Reasoning Models Replace Classical Planning?",
            abstract="We evaluate generative language models on complex planning problems.",
        )
        themes = _fallback_themes(
            "AI Agent 在复杂任务规划中的能力边界",
            [paper],
            [PaperAnalysis(paper_id="p1", methodology=["planning evaluation"])],
        )

        self.assertEqual("推理、规划与问题求解", themes[0].name)

    def test_query_json_failure_does_not_disable_model_analysis_for_later_requests(self) -> None:
        class RecoveringAgent:
            def infer(self, prompt, **_kwargs):
                if "Query: first query" in prompt:
                    return "invalid"
                if "Query: second query" in prompt:
                    return '{"research_intent":"second","sub_questions":["second"]}'
                if "Synthesize" in prompt and "second query" in prompt:
                    return '{"direct_answer":"grounded second answer","overview":"summary"}'
                return "invalid"

            def batch_infer(self, prompts, **_kwargs):
                if prompts and "second query" in prompts[0]:
                    return [
                        '{"paper_id":"p1","relevance_level":"high",'
                        '"one_sentence_summary":"Second analysis","evidence":["Paper title"]}'
                    ]
                return ["invalid" for _ in prompts]

        settings = replace(get_settings(), analysis_top_n=1)
        analyzer = SearchResultAnalyzer(RecoveringAgent(), settings)
        paper = SimpleNamespace(
            paper_id="p1", title="Paper title", abstract="Paper abstract evidence.",
            selected=True, score=0.9, selector_score=0.9,
        )

        first = analyzer.analyze("first query", SimpleNamespace(papers=[paper], tree={}))
        second = analyzer.analyze("second query", SimpleNamespace(papers=[paper], tree={}))

        self.assertIn("grounded-fallback", first.model)
        self.assertEqual("pasa-7b-crawler", second.model)
        self.assertEqual("与查询最相关的优先阅读包括《Paper title》。", second.synthesis.direct_answer)

    def test_analysis_reuses_query_plan_from_retrieval(self) -> None:
        class PlanAwareAgent:
            def infer(self, prompt, **_kwargs):
                self.assert_not_query_prompt(prompt)
                if "Synthesize" in prompt:
                    return '{"direct_answer":"answer","overview":"overview"}'
                return "invalid"

            @staticmethod
            def assert_not_query_prompt(prompt):
                if "Analyze this scholarly search request" in prompt:
                    raise AssertionError("query should be reused from QueryPlan")

            @staticmethod
            def batch_infer(_prompts, **_kwargs):
                return [
                    '{"paper_id":"p1","relevance_level":"high",'
                    '"one_sentence_summary":"summary","evidence":["Paper title"]}'
                ]

        settings = replace(get_settings(), analysis_top_n=1)
        paper = SimpleNamespace(
            paper_id="p1", title="Paper title", abstract="Paper abstract.",
            selected=True, score=0.9, selector_score=0.9,
        )
        result = SimpleNamespace(
            papers=[paper],
            tree={"extra": {"query_plan": {
                "research_intent": "统一研究意图",
                "hard_constraints": ["复杂任务规划"],
                "sub_questions": ["能力边界是什么"],
            }}},
        )

        analysis = SearchResultAnalyzer(PlanAwareAgent(), settings).analyze("query", result)

        self.assertEqual("统一研究意图", analysis.query_understanding.research_intent)
        self.assertEqual(["复杂任务规划"], analysis.query_understanding.hard_constraints)

    def test_fallback_query_understanding_extracts_methods_constraints_and_exclusions(self) -> None:
        understanding = _fallback_query_understanding(
            "寻找2022-2024年使用diffusion进行视频生成的论文，排除综述，并比较性能和成本"
        )

        self.assertIn("diffusion", understanding.methods)
        self.assertTrue(any("生成式" in domain for domain in understanding.domains))
        self.assertIn("2022-2024", understanding.hard_constraints)
        self.assertTrue(any("综述" in item for item in understanding.exclusions))
        self.assertIn("性能", understanding.comparison_dimensions)
        self.assertIn("效率与成本", understanding.comparison_dimensions)

    def test_result_formatter_applies_explicit_survey_exclusion(self) -> None:
        tree = {"child": {"query": [{
            "arxiv_id": "2501.00001", "title": "A Survey of Graph Retrieval",
            "abstract": "Survey", "select_score": 0.99, "depth": 0,
            "source": "Search", "extra": {}, "child": {},
        }]}}

        result = format_result("request", "find graph retrieval papers, exclude surveys", tree)

        self.assertFalse(result.papers[0].selected)
        self.assertEqual(0.49, result.papers[0].score)

    def test_candidate_pairs_prefilters_by_title_and_abstract_overlap(self) -> None:
        papers = [
            SimpleNamespace(paper_id="p1", title="Graph neural retrieval", abstract="ranking with graph embeddings"),
            SimpleNamespace(paper_id="p2", title="Graph retrieval survey", abstract="graph ranking methods"),
            SimpleNamespace(paper_id="p3", title="Protein folding", abstract="molecular structure prediction"),
        ]

        pairs = candidate_pairs(papers, limit=10)

        self.assertEqual([("p1", "p2")], [(left.paper_id, right.paper_id) for left, right in pairs])

    def test_grounded_analyzer_batches_papers_and_validates_relation_quotes(self) -> None:
        class FakeAgent:
            def __init__(self) -> None:
                self.responses = iter([
                    '{"research_intent":"graph retrieval","comparison_dimensions":["method"]}',
                    '{"direct_answer":"Both papers study graph retrieval.","overview":"Two approaches.",'
                    '"themes":[{"theme_id":"T1","name":"Graph retrieval","paper_ids":["p1","p2"]}]}',
                    '{"relations":[{"from_paper_id":"p1","to_paper_id":"p2","type":"same_task",'
                    '"description":"Both address graph retrieval.","evidence_from":"Graph retrieval encoder",'
                    '"evidence_to":"Graph retrieval ranking","confidence":0.9}]}',
                ])

            def infer(self, _prompt, **_kwargs):
                return next(self.responses)

            def batch_infer(self, prompts, **_kwargs):
                return [
                    '{"paper_id":"p1","relevance_level":"high","one_sentence_summary":"Encoder.",'
                    '"methodology":["encoder"],"evidence":["Graph retrieval encoder"]}',
                    '{"paper_id":"p2","relevance_level":"high","one_sentence_summary":"Ranking.",'
                    '"methodology":["ranking"],"evidence":["Graph retrieval ranking"]}',
                ][:len(prompts)]

        papers = [
            SimpleNamespace(paper_id="p1", title="Graph retrieval encoder", abstract="Encoder for graph ranking.", selected=True),
            SimpleNamespace(paper_id="p2", title="Graph retrieval ranking", abstract="Ranking for graph search.", selected=True),
        ]
        settings = replace(get_settings(), analysis_top_n=2, analysis_pair_limit=2, analysis_batch_size=2)

        analyzer = SearchResultAnalyzer(FakeAgent(), settings)
        result = SimpleNamespace(papers=papers)
        analysis = analyzer.analyze("graph retrieval", result)
        cached = analyzer.analyze("graph retrieval", result)

        self.assertIsNotNone(analysis)
        self.assertEqual(2, analysis.analyzed_paper_count)
        self.assertEqual("same_task", analysis.semantic_relations[0].type)
        self.assertIn("检索", analysis.query_understanding.research_intent)
        self.assertEqual("方法", analysis.query_understanding.comparison_dimensions[0])
        self.assertIn("该论文围绕", analysis.paper_analyses[0].one_sentence_summary)
        self.assertIn("相近的研究任务", analysis.semantic_relations[0].description)
        self.assertIn("与查询最相关", analysis.synthesis.direct_answer)
        self.assertGreater(analysis.semantic_relations[0].confidence, 0)
        self.assertLess(analysis.semantic_relations[0].confidence, 0.9)
        self.assertIs(analysis, cached)

    def test_analyzer_returns_grounded_content_when_model_json_is_invalid(self) -> None:
        class InvalidJsonAgent:
            @staticmethod
            def infer(*_args, **_kwargs):
                return "not json"

            @staticmethod
            def batch_infer(prompts, **_kwargs):
                return ["not json" for _ in prompts]

        papers = [SimpleNamespace(
            paper_id="p1",
            title="Graph Retrieval with Dense Encoders",
            abstract="We introduce a dense encoder for graph retrieval. It improves ranking.",
            selected=True,
            score=0.91,
        )]
        settings = replace(get_settings(), analysis_top_n=1)

        analysis = SearchResultAnalyzer(InvalidJsonAgent(), settings).analyze(
            "graph retrieval", SimpleNamespace(papers=papers)
        )

        self.assertEqual(1, analysis.analyzed_paper_count)
        self.assertIn("Graph Retrieval", analysis.paper_analyses[0].one_sentence_summary)
        self.assertTrue(analysis.paper_analyses[0].methodology)
        self.assertTrue(analysis.paper_analyses[0].contributions)
        self.assertTrue(analysis.synthesis.direct_answer)
        self.assertNotIn("unavailable", analysis.synthesis.overview.lower())
        self.assertNotIn("start with the highest-scoring", analysis.synthesis.overview.lower())
        self.assertTrue(analysis.synthesis.themes)
        self.assertIn("grounded-fallback", analysis.model)


class MockEngineTest(unittest.TestCase):
    def test_competition_tuned_default_search_profile(self) -> None:
        options = SearchOptions()

        self.assertEqual(0, options.expand_layers)
        self.assertEqual(5, options.search_queries)
        self.assertEqual(10, options.search_papers)

    def test_mock_engine_exposes_result(self) -> None:
        request = ModelSearchRequest(request_id="request", query="find relevant papers")
        tree = MockSearchEngine(step_delay=0).run(request, lambda _stage, _progress: None)
        result = format_result(request.request_id, request.query, tree)
        self.assertEqual(result.summary.paper_count, 2)
        self.assertEqual(result.summary.selected_count, 1)
        self.assertGreater(result.papers[0].score, result.papers[1].score)

    def test_stream_endpoint_emits_progress_before_result(self) -> None:
        settings = replace(
            get_settings(),
            engine_mode="mock",
            mock_step_delay=0,
            internal_token="test-token",
        )
        client = TestClient(create_app(settings))

        with client.stream(
            "POST",
            "/internal/v1/search/stream",
            headers={"X-Internal-Token": "test-token"},
            json={
                "request_id": "stream-test",
                "query": "find relevant papers",
                "options": {"expand_layers": 2},
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line) for line in response.iter_lines() if line]

        self.assertEqual(events[-1]["type"], "result")
        progress = [event for event in events if event["type"] == "progress"]
        self.assertGreaterEqual(len(progress), 6)
        self.assertEqual(progress[-1]["progress"]["current_layer"], 2)
        self.assertGreater(progress[-1]["progress"]["papers_found"], 0)
        self.assertGreater(progress[-1]["progress"]["papers_selected"], 0)
        self.assertEqual(events[-1]["data"]["summary"]["paper_count"], 2)
        self.assertEqual(events[-1]["data"]["analysis"]["model"], "mock")
        self.assertEqual(events[-1]["data"]["analysis"]["analyzed_paper_count"], 1)


if __name__ == "__main__":
    unittest.main()

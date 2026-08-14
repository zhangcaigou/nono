from __future__ import annotations

import json
import unittest
from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.analyzer import SearchResultAnalyzer, candidate_pairs
from backend.config import get_settings
from backend.engine import MockSearchEngine
from backend.result_formatter import format_result
from backend.schemas import ModelSearchRequest
from types import SimpleNamespace


class ResultFormatterTest(unittest.TestCase):
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
        self.assertIs(analysis, cached)


class MockEngineTest(unittest.TestCase):
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

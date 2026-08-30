from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from paper_agent import PaperAgent
from paper_node import PaperNode


class _Crawler:
    def __init__(self, response: str):
        self.response = response

    def infer(self, _prompt: str) -> str:
        return self.response


class PaperAgentQueryTest(TestCase):
    def make_agent(self, response: str) -> PaperAgent:
        agent = PaperAgent.__new__(PaperAgent)
        agent.crawler = _Crawler(response)
        agent.user_query = "graph neural network retrieval"
        agent.original_user_query = agent.user_query
        agent.prompts = {"generate_query": "{user_query}"}
        agent.templates = {"search_template": r"Search\](.*?)\["}
        agent.search_queries = 3
        agent.root = SimpleNamespace(extra={})
        agent.progress_callback = None
        agent.query_planner = None
        return agent

    def test_search_deduplicates_and_limits_generated_queries(self):
        agent = self.make_agent(
            "[Search] graph retrieval [x] [Search] graph retrieval [x] "
            "[Search] GNN ranking [x] [Search] graph benchmark [x] [Search] ignored [x]"
        )
        with patch.object(PaperAgent, "do_parallel") as parallel:
            agent.search()

        self.assertEqual(3, len(agent.root.extra["generated_search_queries"]))
        self.assertEqual("graph retrieval", agent.root.extra["generated_search_queries"][0])
        self.assertIn("GNN ranking", agent.root.extra["generated_search_queries"])
        self.assertEqual(3, parallel.call_args.args[2])

    def test_search_falls_back_to_original_query_when_crawler_output_is_unparseable(self):
        agent = self.make_agent("no structured search query")
        with patch.object(PaperAgent, "do_parallel") as parallel:
            agent.search()

        self.assertEqual([agent.original_user_query], agent.root.extra["generated_search_queries"])
        self.assertEqual(1, parallel.call_args.args[2])

    def test_search_announces_searching_before_workers_start(self):
        agent = self.make_agent("[Search] graph retrieval [x]")
        updates = []
        agent.progress_callback = lambda found, selected: updates.append((found, selected))

        with patch.object(PaperAgent, "do_parallel"):
            agent.search()

        self.assertEqual([(0, 0)], updates)

    def test_search_prefers_optional_query_planner_and_records_metrics(self):
        agent = self.make_agent("crawler output must not be used")
        agent.query_planner = lambda _query, _count: {
            "queries": ["data pruning", "dataset deduplication"],
            "metrics": {"calls": 1, "input_tokens": 20},
        }

        with patch.object(PaperAgent, "do_parallel") as parallel:
            agent.search()

        self.assertEqual(
            ["data pruning", "dataset deduplication", agent.original_user_query],
            agent.root.extra["generated_search_queries"],
        )
        self.assertEqual(1, agent.root.extra["query_planning"]["calls"])
        self.assertEqual(3, parallel.call_args.args[2])

    def test_query_selection_prefers_complementary_terms_from_oversized_pool(self):
        queries = PaperAgent._select_diverse_queries(
            [
                "smaller datasets for language model pretraining",
                "benefits of small datasets in language model pretraining",
                "data pruning for pretraining LLMs",
                "training data deduplication language models",
                "influential subset selection for language model training",
                "limited data language model pretraining",
            ],
            "Do smaller pretraining datasets produce better language models?",
            4,
        )

        self.assertEqual(4, len(queries))
        self.assertEqual(
            "Do smaller pretraining datasets produce better language models?",
            queries[-1],
        )
        self.assertIn("data pruning for pretraining LLMs", queries)
        self.assertIn("training data deduplication language models", queries)

    def test_search_uses_one_reserve_query_when_initial_retrieval_is_sparse(self):
        agent = self.make_agent("crawler output must not be used")
        agent.root.child = {}
        agent.query_planner = lambda _query, _count: {
            "queries": ["q1", "q2", "q3", "q4", "q5", "q6"],
            "metrics": {"calls": 1},
        }

        def simulate(_func, args, _workers):
            query_list = args[0]
            if not agent.root.child:
                agent.root.child["initial"] = [SimpleNamespace(select_score=0.9)]
            query_list.clear()

        with patch.object(PaperAgent, "do_parallel", side_effect=simulate) as parallel:
            agent.search()

        self.assertEqual(2, parallel.call_count)
        self.assertTrue(agent.root.extra["adaptive_search"]["triggered"])
        self.assertEqual(1, len(agent.root.extra["adaptive_search"]["queries"]))

    def test_every_expansion_layer_is_bounded_and_prefers_selected_papers(self):
        candidates = [
            PaperNode({"title": f"p{i}", "select_score": score})
            for i, score in enumerate([0.98, 0.91, 0.83, 0.77, 0.61, 0.49, 0.3])
        ]

        selected = PaperAgent._bounded_expand_candidates(candidates, 4)

        self.assertEqual(4, len(selected))
        self.assertTrue(all(paper.select_score > 0.5 for paper in selected))

    def test_expansion_uses_small_fallback_when_few_candidates_are_approved(self):
        candidates = [
            PaperNode({"title": f"p{i}", "select_score": 0.9 if i == 0 else 0.4 - i / 100})
            for i in range(20)
        ]

        selected = PaperAgent._bounded_expand_candidates(candidates, 10)

        self.assertEqual(5, len(selected))
        self.assertEqual("p0", selected[0].title)

    def test_citation_candidates_are_round_robin_bounded_and_deduplicated(self):
        selected, total = PaperAgent._bounded_section_references(
            {"method": ["A", "B", "C"], "evaluation": ["A", "D", "E"]},
            ["method", "evaluation"],
            4,
        )

        self.assertEqual(6, total)
        self.assertEqual(
            [["method", "A"], ["evaluation", "D"], ["method", "B"], ["evaluation", "E"]],
            selected,
        )

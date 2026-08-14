from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from paper_agent import PaperAgent


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
        agent.prompts = {"generate_query": "{user_query}"}
        agent.templates = {"search_template": r"Search\](.*?)\["}
        agent.search_queries = 3
        agent.root = SimpleNamespace(extra={})
        agent.progress_callback = None
        return agent

    def test_search_deduplicates_and_limits_generated_queries(self):
        agent = self.make_agent(
            "[Search] graph retrieval [x] [Search] graph retrieval [x] "
            "[Search] GNN ranking [x] [Search] graph benchmark [x] [Search] ignored [x]"
        )
        with patch.object(PaperAgent, "do_parallel") as parallel:
            agent.search()

        self.assertEqual(
            ["graph retrieval", "GNN ranking", "graph benchmark"],
            agent.root.extra["generated_search_queries"],
        )
        self.assertEqual(3, parallel.call_args.args[2])

    def test_search_rejects_unparseable_crawler_output(self):
        agent = self.make_agent("no structured search query")
        with self.assertRaisesRegex(RuntimeError, "valid search query"):
            agent.search()

    def test_search_announces_searching_before_workers_start(self):
        agent = self.make_agent("[Search] graph retrieval [x]")
        updates = []
        agent.progress_callback = lambda found, selected: updates.append((found, selected))

        with patch.object(PaperAgent, "do_parallel"):
            agent.search()

        self.assertEqual([(0, 0)], updates)

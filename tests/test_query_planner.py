from unittest import TestCase

from backend.query_planner import DeepSeekQueryPlanner


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": (
                '{"research_intent":"比较小数据预训练策略",'
                '"methods":["data pruning"],"hard_constraints":["smaller pretraining data"],'
                '"sub_questions":["数据筛选如何影响模型"],'
                '"queries":["data pruning LLM","dataset deduplication"]}'
            )}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 8},
        }


class _Http:
    def __init__(self):
        self.calls = 0
        self.last_json = None

    def post(self, *_args, **kwargs):
        self.calls += 1
        self.last_json = kwargs.get("json")
        return _Response()


class QueryPlannerTest(TestCase):
    def test_plans_strict_queries_and_reuses_cache(self):
        http = _Http()
        planner = DeepSeekQueryPlanner(
            api_key="test", base_url="https://example.test", model="test-model", http=http
        )

        first = planner.plan("smaller pretraining data", 5)
        second = planner.plan("smaller pretraining data", 5)

        self.assertEqual(["data pruning LLM", "dataset deduplication"], first["queries"])
        self.assertEqual("比较小数据预训练策略", first["query_plan"]["research_intent"])
        self.assertEqual(["data pruning"], second["query_plan"]["methods"])
        self.assertEqual(1, first["metrics"]["calls"])
        self.assertEqual(30, first["metrics"]["input_tokens"])
        self.assertTrue(second["metrics"]["cache_hit"])
        self.assertEqual(0, second["metrics"]["calls"])
        self.assertEqual(1, http.calls)

        request_body = http.last_json
        self.assertEqual(0, request_body["temperature"])
        self.assertEqual(512, request_body["max_tokens"])
        self.assertEqual({"type": "disabled"}, request_body["thinking"])

    def test_degrades_without_raising_when_remote_call_fails(self):
        class BrokenHttp:
            @staticmethod
            def post(*_args, **_kwargs):
                raise TimeoutError("slow")

        planner = DeepSeekQueryPlanner(
            api_key="test", base_url="https://example.test", model="test-model", http=BrokenHttp()
        )

        result = planner.plan("query", 5)
        second = planner.plan("another query", 5)

        self.assertEqual([], result["queries"])
        self.assertEqual("TimeoutError", result["metrics"]["degraded"])
        self.assertEqual("circuit_open", second["metrics"]["degraded"])
        self.assertEqual(0, second["metrics"]["calls"])

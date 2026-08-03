from __future__ import annotations

import json
import unittest
from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import get_settings
from backend.engine import MockSearchEngine
from backend.result_formatter import format_result
from backend.schemas import ModelSearchRequest


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


if __name__ == "__main__":
    unittest.main()

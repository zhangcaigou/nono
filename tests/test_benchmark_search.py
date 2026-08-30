from unittest import TestCase

from scripts.benchmark_search import pasa_case, retrieval_quality, summarize


class BenchmarkSearchTest(TestCase):
    def test_converts_official_pasa_case_and_applies_publication_cutoff(self):
        case = pasa_case({
            "qid": "RealScholarQuery_0",
            "question": "Find papers",
            "answer_arxiv_id": ["2309.04564v2"],
            "source_meta": {"published_time": "20241001"},
        })

        self.assertEqual("RealScholarQuery_0", case["case_id"])
        self.assertEqual(["2309.04564v2"], case["relevant_ids"])
        self.assertEqual("2024-09-24", case["end_date"])

    def test_reports_selected_f1_and_ranked_recall(self):
        quality = retrieval_quality(
            ["a", "b", "c"],
            {"a", "x"},
            {"a", "b"},
        )

        self.assertEqual(0.5, quality["precision"])
        self.assertEqual(0.5, quality["recall"])
        self.assertEqual(0.5, quality["f1"])
        self.assertEqual(1.0, quality["recall_at_20"])

    def test_summary_contains_macro_micro_latency_and_cost(self):
        results = [{
            "elapsed_ms": 1000,
            "quality": {
                "true_positive": 1,
                "selected_total": 2,
                "relevant_total": 4,
                "precision": 0.5,
                "recall": 0.25,
                "f1": 0.3333,
                "crawler_recall": 0.5,
                "recall_at_20": 0.25,
                "recall_at_50": 0.5,
                "recall_at_100": 0.5,
            },
            "efficiency": {
                "total_ms": 900,
                "model_search_ms": 800,
                "traceability_ms": 50,
                "deepseek_ms": 50,
                "tracked_api_calls": 10,
                "input_tokens": 20,
                "output_tokens": 5,
            },
        }]

        summary = summarize(results, [])

        self.assertEqual(1000, summary["latency_ms"]["p95"])
        self.assertEqual(0.3333, summary["quality_macro"]["f1"])
        self.assertEqual(0.3333, summary["quality_micro"]["f1"])
        self.assertEqual(10, summary["efficiency_average"]["tracked_api_calls"])

from __future__ import annotations

import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import paper_agent
import utils
from backend.result_formatter import format_result
from paper_agent import PaperAgent


class OpenAlexNormalizationTest(unittest.TestCase):
    def test_local_title_index_returns_ranked_bundled_papers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "titles.sqlite3"
            connection = sqlite3.connect(index)
            connection.execute(
                "CREATE VIRTUAL TABLE paper_titles USING fts5(arxiv_id UNINDEXED, title)"
            )
            connection.executemany(
                "INSERT INTO paper_titles(arxiv_id, title) VALUES (?, ?)",
                [
                    ("2401.00001", "Data Pruning for Language Model Pretraining"),
                    ("2401.00002", "Unrelated Vision Paper"),
                ],
            )
            connection.commit()
            connection.close()

            def local(arxiv_id):
                return {
                    "arxiv_id": arxiv_id,
                    "title": "Data Pruning for Language Model Pretraining",
                    "abstract": "Abstract",
                    "sections": "",
                    "source": "SearchFrom:local_paper_db",
                }

            with patch.object(utils, "title_index_path", index), patch.object(
                utils, "_local_paper_by_arxiv_id", side_effect=local
            ):
                papers = utils._search_papers_by_title_index_uncached(
                    "data pruning language model", 5, "20240924"
                )

        self.assertEqual(["2401.00001"], [paper["arxiv_id"] for paper in papers])
        self.assertEqual(["local_title"], papers[0]["extra"]["retrieval_providers"])

    def test_local_title_index_respects_end_date_by_arxiv_month(self) -> None:
        self.assertTrue(utils._arxiv_not_after("2409.99999", "20240924"))
        self.assertFalse(utils._arxiv_not_after("2410.00001", "20240924"))
        self.assertTrue(utils._arxiv_not_after("not-arxiv", "20240924"))

    def test_normalizes_work_and_reconstructs_abstract(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/10.1/example",
                    "title": "Example Paper",
                    "publication_year": 2024,
                    "publication_date": "2024-02-03",
                    "primary_location": {
                        "landing_page_url": "https://example.org/paper",
                        "source": {"display_name": "Example Venue"},
                    },
                    "ids": {"arxiv": "https://arxiv.org/abs/2402.00001"},
                    "cited_by_count": 17,
                    "authorships": [{"author": {"display_name": "A. Author"}}],
                    "abstract_inverted_index": {"Hello": [0], "world": [1]},
                }
            ]
        }
        with patch.object(utils, "OPENALEX_API_KEY", "test-key"), patch.object(
            utils.requests, "get", return_value=response
        ):
            papers = utils.openalex_search_papers("query", num=3, end_date="20250101")

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["arxiv_id"], "2402.00001")
        self.assertEqual(papers[0]["abstract"], "Hello world")
        self.assertEqual(papers[0]["extra"]["venue"], "Example Venue")
        self.assertEqual(papers[0]["extra"]["cited_by_count"], 17)


class ParallelRetrievalTest(unittest.TestCase):
    def test_batches_missing_serper_arxiv_ids_through_openalex_doi(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"results": [{
            "id": "https://openalex.org/W1",
            "title": "Paper One",
            "ids": {"arxiv": "https://arxiv.org/abs/2402.00001"},
            "primary_location": {},
        }]}
        with patch.object(utils, "_local_paper_by_arxiv_id", return_value=None), patch.object(
            utils.requests, "get", return_value=response
        ) as get:
            papers = utils._search_papers_by_arxiv_ids_uncached(("2402.00001", "2402.00002"))

        self.assertEqual(["2402.00001"], [paper["arxiv_id"] for paper in papers])
        get.assert_called_once()
        self.assertIn("10.48550/arxiv.2402.00001", get.call_args.kwargs["params"]["filter"])

    def test_merges_serper_and_openalex_and_keeps_openalex_only_work(self) -> None:
        class Crawler:
            def infer(self, _prompt):
                return "[Search]test query[StopSearch]"

        class Selector:
            def infer_score(self, prompts):
                return [0.9 for _ in prompts]

        serper_paper = {
            "arxiv_id": "2402.00001",
            "title": "Shared Paper",
            "abstract": "short",
            "sections": "",
            "source": "SearchFrom:arxiv",
        }
        openalex_papers = [
            {
                "paper_id": "arxiv:2402.00001",
                "arxiv_id": "2402.00001",
                "title": "Shared Paper",
                "abstract": "a longer abstract from OpenAlex",
                "sections": "",
                "source": "SearchFrom:openalex",
                "extra": {"retrieval_providers": ["openalex"], "openalex_id": "W1"},
            },
            {
                "paper_id": "openalex:W2",
                "arxiv_id": "",
                "title": "OpenAlex Only Paper",
                "abstract": "OpenAlex abstract",
                "sections": "",
                "source": "SearchFrom:openalex",
                "extra": {"retrieval_providers": ["openalex"], "openalex_id": "W2"},
            },
        ]
        with patch.object(paper_agent, "google_search_arxiv_id", return_value=["2402.00001"]), patch.object(
            paper_agent, "openalex_search_papers", return_value=openalex_papers
        ), patch.object(
            paper_agent, "search_papers_by_arxiv_ids", return_value=[serper_paper]
        ), patch.object(paper_agent, "search_papers_by_title_index", return_value=[]):
            agent = PaperAgent(
                "find papers", Crawler(), Selector(), expand_layers=0, search_queries=1
            )
            agent.search()

        papers = agent.root.child["test query"]
        self.assertEqual(len(papers), 2)
        shared = next(paper for paper in papers if paper.arxiv_id)
        self.assertEqual(shared.abstract, "a longer abstract from OpenAlex")
        self.assertEqual(shared.extra["retrieval_providers"], ["openalex", "serper"])
        self.assertEqual(agent.root.extra["retrieval_stats"]["serper_calls"], 1)
        self.assertEqual(agent.root.extra["retrieval_stats"]["openalex_calls"], 1)

    def test_formats_openalex_metadata_for_web_response(self) -> None:
        tree = {
            "child": {
                "query": [{
                    "arxiv_id": "",
                    "title": "OpenAlex Paper",
                    "abstract": "Abstract",
                    "select_score": 0.8,
                    "depth": 0,
                    "source": "SearchFrom:openalex",
                    "child": {},
                    "extra": {
                        "openalex_id": "W123",
                        "openalex_url": "https://openalex.org/W123",
                        "doi": "https://doi.org/10.1/example",
                        "publication_year": 2024,
                        "publication_date": "2024-02-03",
                        "venue": "Example Venue",
                        "cited_by_count": 17,
                        "authors": ["A. Author"],
                        "retrieval_providers": ["openalex"],
                    },
                }]
            }
        }
        result = format_result("request", "query", tree)
        paper = result.papers[0]
        self.assertEqual(paper.paper_id, "openalex:W123")
        self.assertEqual(paper.url, "https://openalex.org/W123")
        self.assertEqual(paper.publication_year, 2024)
        self.assertEqual(paper.cited_by_count, 17)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import re
from typing import Any

from backend.schemas import ModelSearchResponse, PaperItem, ResultSummary


def _title_key(title: str) -> str:
    return re.sub(r"\W+", "", title, flags=re.UNICODE).lower()


def format_result(request_id: str, query: str, tree: dict[str, Any]) -> ModelSearchResponse:
    """Convert the recursive core result into a stable list plus the original tree."""
    queue: list[dict[str, Any]] = [tree]
    best_by_key: dict[str, PaperItem] = {}

    while queue:
        node = queue.pop(0)
        for children in (node.get("child") or {}).values():
            for child in children:
                queue.append(child)
                arxiv_id = str(child.get("arxiv_id") or "")
                title = str(child.get("title") or "")
                extra = child.get("extra") or {}
                openalex_id = str(extra.get("openalex_id") or "")
                paper_id = f"arxiv:{arxiv_id}" if arxiv_id else (
                    f"openalex:{openalex_id}" if openalex_id else f"title:{_title_key(title)}"
                )
                key = paper_id
                score = float(child.get("select_score") or 0.0)
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None
                url = arxiv_url or str(extra.get("landing_page_url") or extra.get("openalex_url") or "") or None
                item = PaperItem(
                    paper_id=paper_id,
                    arxiv_id=arxiv_id,
                    openalex_id=openalex_id or None,
                    doi=str(extra.get("doi") or "") or None,
                    title=title,
                    abstract=str(child.get("abstract") or ""),
                    score=score,
                    selected=score > 0.5,
                    depth=int(child.get("depth", -1)),
                    source=str(child.get("source") or ""),
                    arxiv_url=arxiv_url,
                    url=url,
                    publication_year=extra.get("publication_year"),
                    publication_date=str(extra.get("publication_date") or "") or None,
                    venue=str(extra.get("venue") or "") or None,
                    cited_by_count=int(extra.get("cited_by_count") or 0),
                    authors=list(extra.get("authors") or []),
                    retrieval_providers=list(extra.get("retrieval_providers") or []),
                )
                previous = best_by_key.get(key)
                if previous is None or item.score > previous.score:
                    best_by_key[key] = item

    papers = sorted(best_by_key.values(), key=lambda item: item.score, reverse=True)
    return ModelSearchResponse(
        request_id=request_id,
        query=query,
        papers=papers,
        tree=tree,
        summary=ResultSummary(
            paper_count=len(papers),
            selected_count=sum(item.selected for item in papers),
        ),
    )

#!/usr/bin/env python3
"""Benchmark the running PaSa web stack with PaSa or generic JSONL cases."""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request_json(method: str, url: str, payload=None, timeout: float = 1800):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with DIRECT_OPENER.open(request, timeout=timeout) as response:
        return json.load(response)


def normalize_paper_id(value: str) -> str:
    value = str(value or "").strip().lower().removeprefix("arxiv:")
    return value.split("v", 1)[0]


def unique_ranked_paper_ids(papers: list[dict]) -> list[str]:
    ranked = []
    seen = set()
    for paper in papers:
        paper_id = normalize_paper_id(paper.get("arxiv_id") or paper.get("paper_id"))
        if paper_id and paper_id not in seen:
            seen.add(paper_id)
            ranked.append(paper_id)
    return ranked


def retrieval_quality(ranked: list[str], selected: set[str], relevant: set[str]):
    if not relevant:
        return None
    true_positive = len(selected & relevant)
    precision = true_positive / len(selected) if selected else 0.0
    recall = true_positive / len(relevant)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    def recall_at(limit: int) -> float:
        return len(set(ranked[:limit]) & relevant) / len(relevant)

    return {
        "true_positive": true_positive,
        "selected_total": len(selected),
        "relevant_total": len(relevant),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "crawler_recall": round(len(set(ranked) & relevant) / len(relevant), 4),
        "recall_at_20": round(recall_at(20), 4),
        "recall_at_50": round(recall_at(50), 4),
        "recall_at_100": round(recall_at(100), 4),
    }


def run_search(base_url: str, case: dict, poll_interval: float, timeout: float):
    query = str(case["query"]).strip()
    payload = {"query": query}
    if case.get("end_date"):
        payload["end_date"] = case["end_date"]
    if case.get("options"):
        payload["options"] = case["options"]

    started = time.perf_counter()
    accepted = request_json("POST", f"{base_url}/api/v1/search-tasks", payload, timeout)
    task_id = accepted["task_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = request_json("GET", f"{base_url}/api/v1/search-tasks/{task_id}", timeout=timeout)
        if task["status"] == "succeeded":
            break
        if task["status"] in {"failed", "cancelled"}:
            raise RuntimeError(f"task {task_id} ended as {task['status']}: {task.get('error')}")
        time.sleep(poll_interval)
    else:
        raise TimeoutError(f"task {task_id} exceeded {timeout:.0f}s")

    result = request_json("GET", f"{base_url}/api/v1/search-tasks/{task_id}/result", timeout=timeout)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    papers = result.get("papers", [])
    ranked = unique_ranked_paper_ids(papers)
    selected = {
        normalize_paper_id(paper.get("arxiv_id") or paper.get("paper_id"))
        for paper in papers
        if paper.get("selected")
    }
    selected.discard("")
    relevant = {normalize_paper_id(item) for item in case.get("relevant_ids", [])}
    relevant.discard("")
    return {
        "case_id": case.get("case_id"),
        "task_id": task_id,
        "query": query,
        "end_date": case.get("end_date"),
        "options": payload.get("options"),
        "elapsed_ms": elapsed_ms,
        "paper_count": len(papers),
        "selected_count": len(selected),
        "quality": retrieval_quality(ranked, selected, relevant),
        "efficiency": result.get("efficiency"),
    }


def pasa_case(raw: dict) -> dict:
    query = raw.get("query") or raw.get("question")
    if not query:
        raise ValueError("dataset case has neither query nor question")
    case = {
        "case_id": raw.get("case_id") or raw.get("qid"),
        "query": query,
        "relevant_ids": raw.get("relevant_ids") or raw.get("answer_arxiv_id") or [],
    }
    if raw.get("end_date"):
        case["end_date"] = raw["end_date"]
    else:
        published = (raw.get("source_meta") or {}).get("published_time")
        if published:
            cutoff = datetime.strptime(published, "%Y%m%d") - timedelta(days=7)
            case["end_date"] = cutoff.date().isoformat()
    if raw.get("options"):
        case["options"] = raw["options"]
    return case


def load_cases(args):
    if not args.dataset:
        return [{"query": args.query}]
    with open(args.dataset, encoding="utf-8") as source:
        cases = [pasa_case(json.loads(line)) for line in source if line.strip()]
    start = max(0, args.offset)
    end = None if args.limit is None else start + max(0, args.limit)
    return cases[start:end]


def percentile(values: list[int], fraction: float):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def average(items, key):
    values = [item[key] for item in items if item.get(key) is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(results: list[dict], errors: list[dict]):
    qualities = [item["quality"] for item in results if item.get("quality")]
    efficiencies = [item["efficiency"] for item in results if item.get("efficiency")]
    latencies = [item["elapsed_ms"] for item in results]
    true_positive = sum(item["true_positive"] for item in qualities)
    selected_total = sum(item["selected_total"] for item in qualities)
    relevant_total = sum(item["relevant_total"] for item in qualities)
    micro_precision = true_positive / selected_total if selected_total else 0.0
    micro_recall = true_positive / relevant_total if relevant_total else 0.0
    return {
        "cases_succeeded": len(results),
        "cases_failed": len(errors),
        "latency_ms": {
            "average": round(sum(latencies) / len(latencies)) if latencies else None,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "quality_macro": {
            key: average(qualities, key)
            for key in (
                "precision", "recall", "f1", "crawler_recall",
                "recall_at_20", "recall_at_50", "recall_at_100",
            )
        } if qualities else None,
        "quality_micro": {
            "precision": round(micro_precision, 4),
            "recall": round(micro_recall, 4),
            "f1": round(
                2 * micro_precision * micro_recall / (micro_precision + micro_recall), 4
            ) if micro_precision + micro_recall else 0.0,
        } if qualities else None,
        "efficiency_average": {
            key: round(sum(item.get(key, 0) for item in efficiencies) / len(efficiencies))
            for key in (
                "total_ms", "model_search_ms", "traceability_ms", "deepseek_ms",
                "tracked_api_calls", "input_tokens", "output_tokens",
            )
        } if efficiencies else None,
    }


def requested_options(args):
    mapping = {
        "expand_layers": args.expand_layers,
        "search_queries": args.search_queries,
        "search_papers": args.search_papers,
        "expand_papers": args.expand_papers,
        "recommendation_analysis": args.recommendation_analysis,
    }
    return {key: value for key, value in mapping.items() if value is not None}


def write_record(target, record):
    if target is not None:
        target.write(json.dumps(record, ensure_ascii=False) + "\n")
        target.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="single query to benchmark")
    group.add_argument("--dataset", help="PaSa or generic JSONL benchmark cases")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", help="write per-case records and summary as JSONL")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--continue-on-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--expand-layers", type=int)
    parser.add_argument("--search-queries", type=int)
    parser.add_argument("--search-papers", type=int)
    parser.add_argument("--expand-papers", type=int)
    parser.add_argument(
        "--recommendation-analysis",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="enable one paid batch recommendation request per case (disabled by default for benchmarks)",
    )
    args = parser.parse_args()

    cases = load_cases(args)
    if not cases:
        raise ValueError("no benchmark cases selected")
    overrides = requested_options(args)
    if overrides:
        for case in cases:
            case["options"] = {**case.get("options", {}), **overrides}

    output_path = Path(args.output) if args.output else None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    with output_path.open("w", encoding="utf-8") if output_path else _NullContext() as target:
        for index, case in enumerate(cases, args.offset):
            try:
                result = run_search(args.base_url.rstrip("/"), case, args.poll_interval, args.timeout)
                results.append(result)
                record = {"type": "case", "index": index, **result}
            except Exception as error:
                record = {
                    "type": "error", "index": index, "case_id": case.get("case_id"),
                    "query": case.get("query"), "error": f"{type(error).__name__}: {error}",
                }
                errors.append(record)
                if not args.continue_on_error:
                    write_record(target, record)
                    raise
            print(json.dumps(record, ensure_ascii=False), flush=True)
            write_record(target, record)

        summary = {"type": "summary", **summarize(results, errors)}
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        write_record(target, summary)
    return 1 if errors else 0


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, urllib.error.HTTPError) as error:
        raise SystemExit(f"benchmark failed: {error}") from error

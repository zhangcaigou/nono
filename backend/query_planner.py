from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any

import requests


class DeepSeekQueryPlanner:
    """Generate complementary scholarly queries with bounded cost and safe fallback."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 30,
        cache_max_entries: int = 200,
        failure_cooldown_seconds: int = 60,
        http: Any = requests,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.cache_max_entries = cache_max_entries
        self.failure_cooldown_seconds = max(0, failure_cooldown_seconds)
        self.http = http
        self._cache: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._unavailable_until = 0.0

    def plan(self, query: str, count: int) -> dict[str, Any]:
        key = (" ".join(query.split()), count)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return {
                    "queries": list(cached["queries"]),
                    "query_plan": dict(cached["query_plan"]),
                    "metrics": {
                        "enabled": True, "calls": 0, "cache_hit": True,
                        "latency_ms": 0, "input_tokens": 0, "output_tokens": 0,
                        "model": self.model,
                    },
                }
            if time.monotonic() < self._unavailable_until:
                return {
                    "queries": [],
                    "metrics": {
                        "enabled": True, "calls": 0, "cache_hit": False,
                        "latency_ms": 0, "input_tokens": 0, "output_tokens": 0,
                        "model": self.model, "degraded": "circuit_open",
                    },
                }

        started = time.perf_counter()
        candidate_count = max(count + 3, count)
        prompt = (
            f"Generate exactly {candidate_count} complementary academic paper search queries "
            "and one reusable structured query plan for the user request. Return JSON only with "
            "this schema: {\"research_intent\":\"\",\"entities\":[],\"methods\":[],"
            "\"domains\":[],\"datasets\":[],\"hard_constraints\":[],"
            "\"soft_constraints\":[],\"exclusions\":[],\"sub_questions\":[],"
            "\"comparison_dimensions\":[],\"queries\":[\"...\"]}. "
            "Use compact English keyword queries. Each query must cover a distinct terminology, "
            "mechanism, method family, or empirical comparison rather than paraphrasing another. "
            "Infer field-standard terms likely used in paper titles and abstracts. Preserve dates, "
            "named entities, inclusions, and exclusions; do not invent named entities. "
            "Hard constraints must include independently testable topic, method, dataset, venue, "
            "date, or population requirements. Only include comparison dimensions explicitly "
            "requested by the user. All explanatory fields in the query plan must be written "
            "in natural Simplified Chinese, while generated search queries must remain compact English.\n"
            f"User request: {query}"
        )
        try:
            response = self.http.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 512,
                    "thinking": {"type": "disabled"},
                    "response_format": {"type": "json_object"},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"].strip()
            parsed = json.loads(content)
            queries = [
                item.strip() for item in parsed.get("queries", [])
                if isinstance(item, str) and item.strip()
            ][:candidate_count]
            if not queries:
                raise ValueError("query planner returned no queries")
            list_fields = (
                "entities", "methods", "domains", "datasets", "hard_constraints",
                "soft_constraints", "exclusions", "sub_questions", "comparison_dimensions",
            )
            query_plan = {
                "research_intent": str(parsed.get("research_intent") or query).strip(),
                **{
                    field: [
                        value.strip() for value in parsed.get(field, [])
                        if isinstance(value, str) and value.strip()
                    ][:12]
                    if isinstance(parsed.get(field, []), list) else []
                    for field in list_fields
                },
            }
            if not query_plan["sub_questions"]:
                query_plan["sub_questions"] = [query]
            with self._lock:
                self._cache[key] = {
                    "queries": list(queries),
                    "query_plan": dict(query_plan),
                }
                self._unavailable_until = 0.0
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_max_entries:
                    self._cache.popitem(last=False)
            usage = payload.get("usage") or {}
            return {
                "queries": queries,
                "query_plan": query_plan,
                "metrics": {
                    "enabled": True,
                    "calls": 1,
                    "cache_hit": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "input_tokens": int(usage.get("prompt_tokens") or 0),
                    "output_tokens": int(usage.get("completion_tokens") or 0),
                    "model": self.model,
                },
            }
        except Exception as error:
            with self._lock:
                self._unavailable_until = (
                    time.monotonic() + self.failure_cooldown_seconds
                )
            return {
                "queries": [],
                "metrics": {
                    "enabled": True,
                    "calls": 1,
                    "cache_hit": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "model": self.model,
                    "degraded": type(error).__name__,
                },
            }

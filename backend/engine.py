from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from backend.config import Settings
from backend.schemas import ModelSearchRequest, ModelSearchResponse, SearchAnalysis, TaskProgress, TaskStage


ProgressCallback = Callable[[TaskStage, TaskProgress], None]


class EngineError(RuntimeError):
    code = "SEARCH_FAILED"


class ModelUnavailableError(EngineError):
    code = "MODEL_UNAVAILABLE"


class TaskCancelledError(EngineError):
    code = "TASK_CANCELLED"


class SearchEngine(Protocol):
    def preload(self) -> None: ...
    def run(self, request: ModelSearchRequest, progress: ProgressCallback) -> dict[str, Any]: ...
    def analyze(self, request: ModelSearchRequest, result: ModelSearchResponse) -> SearchAnalysis | None: ...
    def metrics(self) -> dict[str, Any]: ...


def _tree_counts(tree: dict[str, Any]) -> tuple[int, int]:
    threshold = float((tree.get("extra") or {}).get("selector_threshold", 0.5))
    found = selected = 0
    queue = [tree]
    while queue:
        node = queue.pop(0)
        for children in (node.get("child") or {}).values():
            for child in children:
                queue.append(child)
                found += 1
                selected += float(child.get("select_score") or 0.0) > threshold
    return found, selected


class MockSearchEngine:
    """Deterministic local engine used for frontend integration and API tests."""

    def __init__(self, step_delay: float = 0.15) -> None:
        self.step_delay = step_delay

    def _step(self, stage: TaskStage, progress: ProgressCallback, state: TaskProgress) -> None:
        time.sleep(self.step_delay)
        progress(stage, state)

    def preload(self) -> None:
        return None

    def run(self, request: ModelSearchRequest, progress: ProgressCallback) -> dict[str, Any]:
        total = request.options.expand_layers
        self._step(TaskStage.LOADING, progress, TaskProgress(total_layers=total))
        self._step(TaskStage.GENERATING_QUERIES, progress, TaskProgress(total_layers=total))
        self._step(
            TaskStage.SEARCHING,
            progress,
            TaskProgress(total_layers=total, papers_found=2),
        )
        self._step(
            TaskStage.SELECTING,
            progress,
            TaskProgress(total_layers=total, papers_found=2, papers_selected=1),
        )
        for layer in range(1, total + 1):
            self._step(
                TaskStage.EXPANDING,
                progress,
                TaskProgress(
                    current_layer=layer,
                    total_layers=total,
                    papers_found=2 + layer,
                    papers_selected=1 + layer,
                ),
            )

        return {
            "title": request.query,
            "arxiv_id": "",
            "depth": -1,
            "child": {
                "mock generated query": [
                    {
                        "title": "Mock Highly Relevant Paper",
                        "arxiv_id": "2501.00001",
                        "depth": 0,
                        "child": {},
                        "abstract": "Mock result for frontend integration. Replace mock mode with the production engine for real papers.",
                        "sections": "",
                        "source": "SearchFrom:mock",
                        "select_score": 0.91,
                        "extra": {},
                    },
                    {
                        "title": "Mock Less Relevant Paper",
                        "arxiv_id": "2501.00002",
                        "depth": 0,
                        "child": {},
                        "abstract": "A second deterministic mock paper.",
                        "sections": "",
                        "source": "SearchFrom:mock",
                        "select_score": 0.31,
                        "extra": {},
                    },
                ]
            },
            "abstract": "",
            "sections": "",
            "source": "Root",
            "select_score": 0.0,
            "extra": {},
        }

    def analyze(self, request: ModelSearchRequest, result: ModelSearchResponse) -> SearchAnalysis:
        from backend.analyzer import mock_analysis

        return mock_analysis(result)

    def metrics(self) -> dict[str, Any]:
        return {
            "model_load_ms": 0,
            "initial_search_ms": 0,
            "expansion_ms": [],
            "analysis_ms": 0,
            "model_total_ms": 0,
            "retrieval_stats": {},
        }


class PasaSearchEngine:
    """Lazy adapter around the original synchronous PaSa implementation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._load_lock = threading.Lock()
        self._crawler: Any | None = None
        self._selector: Any | None = None
        self._analyzer: Any | None = None
        self._query_planner: Any | None = None
        self._metrics: dict[str, Any] = {}

    def _load_models(self) -> tuple[Any, Any]:
        with self._load_lock:
            if self._crawler is not None and self._selector is not None:
                return self._crawler, self._selector
            ready, reasons = self.settings.readiness()
            if not ready:
                raise ModelUnavailableError("；".join(reasons))
            try:
                from models import Agent

                if self._crawler is None:
                    self._crawler = Agent(
                        str(self.settings.crawler_path),
                        device_map=self.settings.crawler_device,
                    )
                if self._selector is None:
                    self._selector = Agent(
                        str(self.settings.selector_path),
                        device_map=self.settings.selector_device,
                        score_batch_size=self.settings.selector_batch_size,
                    )
            except Exception as exc:
                raise ModelUnavailableError(f"模型加载失败: {exc}") from exc
            return self._crawler, self._selector

    def preload(self) -> None:
        """Load both local models during service startup so the first search is not penalized."""
        started = time.perf_counter()
        self._load_models()
        self._metrics["preload_ms"] = round((time.perf_counter() - started) * 1000)

    def run(self, request: ModelSearchRequest, progress: ProgressCallback) -> dict[str, Any]:
        total_started = time.perf_counter()
        total = request.options.expand_layers
        progress(TaskStage.LOADING, TaskProgress(total_layers=total))
        load_started = time.perf_counter()
        crawler, selector = self._load_models()
        model_load_ms = round((time.perf_counter() - load_started) * 1000)

        try:
            from paper_agent import PaperAgent
            from utils import retrieval_cache_stats

            end_date = request.end_date.strftime("%Y%m%d") if request.end_date else None
            cache_before = retrieval_cache_stats()
            kwargs: dict[str, Any] = {
                "user_query": request.query,
                "crawler": crawler,
                "selector": selector,
                "prompts_path": str(self.settings.prompts_path),
                "expand_layers": request.options.expand_layers,
                "search_queries": request.options.search_queries,
                "search_papers": request.options.search_papers,
                "expand_papers": request.options.expand_papers,
                "expand_refs_per_paper": self.settings.expand_refs_per_paper,
                "local_search_papers": self.settings.local_search_papers,
                "selector_threshold": self.settings.selector_threshold,
                "threads_num": self.settings.threads_num,
            }
            if self.settings.query_planning_enabled and self.settings.deepseek_api_key:
                if self._query_planner is None:
                    from backend.query_planner import DeepSeekQueryPlanner

                    self._query_planner = DeepSeekQueryPlanner(
                        api_key=self.settings.deepseek_api_key,
                        base_url=self.settings.deepseek_base_url,
                        model=self.settings.deepseek_model,
                        timeout=self.settings.query_planning_timeout,
                        cache_max_entries=self.settings.query_planning_cache_max_entries,
                    )
                kwargs["query_planner"] = self._query_planner.plan
            if end_date is not None:
                kwargs["end_date"] = end_date

            def publish_search_progress(found: int, selected: int) -> None:
                progress(
                    TaskStage.SEARCHING,
                    TaskProgress(
                        total_layers=total,
                        papers_found=found,
                        papers_selected=selected,
                    ),
                )

            kwargs["progress_callback"] = publish_search_progress
            agent = PaperAgent(**kwargs)

            progress(TaskStage.GENERATING_QUERIES, TaskProgress(total_layers=total))
            search_started = time.perf_counter()
            agent.search()
            initial_search_ms = round((time.perf_counter() - search_started) * 1000)
            tree = agent.root.todic()
            found, selected = _tree_counts(tree)
            progress(
                TaskStage.SELECTING,
                TaskProgress(total_layers=total, papers_found=found, papers_selected=selected),
            )

            expansion_ms: list[int] = []
            for depth in range(total):
                expansion_started = time.perf_counter()
                agent.expand(depth)
                expansion_ms.append(round((time.perf_counter() - expansion_started) * 1000))
                tree = agent.root.todic()
                found, selected = _tree_counts(tree)
                progress(
                    TaskStage.EXPANDING,
                    TaskProgress(
                        current_layer=depth + 1,
                        total_layers=total,
                        papers_found=found,
                        papers_selected=selected,
                    ),
                )
            tree = agent.root.todic()
            cache_after = retrieval_cache_stats()
            cache_delta = {
                provider: {
                    "hits": values["hits"] - cache_before.get(provider, {}).get("hits", 0),
                    "misses": values["misses"] - cache_before.get(provider, {}).get("misses", 0),
                }
                for provider, values in cache_after.items()
            }
            query_planning = (tree.get("extra") or {}).get("query_planning") or {}
            self._metrics = {
                "model_load_ms": model_load_ms,
                "initial_search_ms": initial_search_ms,
                "expansion_ms": expansion_ms,
                "analysis_ms": 0,
                "model_total_ms": round((time.perf_counter() - total_started) * 1000),
                "retrieval_stats": (tree.get("extra") or {}).get("retrieval_stats") or {},
                "retrieval_cache": cache_delta,
                "query_planning": query_planning,
                "adaptive_search": (tree.get("extra") or {}).get("adaptive_search") or {},
                "provider_network_calls": (
                    sum(
                        item["misses"] for provider, item in cache_delta.items()
                        if provider != "title_index"
                    )
                    + int(query_planning.get("calls", 0))
                ),
            }
            return tree
        except TaskCancelledError:
            raise
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(str(exc)) from exc

    def analyze(self, request: ModelSearchRequest, result: ModelSearchResponse) -> SearchAnalysis | None:
        from backend.analyzer import SearchResultAnalyzer

        started = time.perf_counter()
        try:
            crawler, _ = self._load_models()
            if self._analyzer is None:
                self._analyzer = SearchResultAnalyzer(crawler, self.settings)
            return self._analyzer.analyze(request.query, result)
        finally:
            analysis_ms = round((time.perf_counter() - started) * 1000)
            self._metrics["analysis_ms"] = analysis_ms
            self._metrics["model_total_ms"] = int(self._metrics.get("model_total_ms", 0)) + analysis_ms

    def metrics(self) -> dict[str, Any]:
        return dict(self._metrics)


def create_engine(settings: Settings) -> SearchEngine:
    if settings.is_mock:
        return MockSearchEngine(settings.mock_step_delay)
    return PasaSearchEngine(settings)

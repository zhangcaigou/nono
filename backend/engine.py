from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from backend.config import Settings
from backend.schemas import ModelSearchRequest, TaskProgress, TaskStage


ProgressCallback = Callable[[TaskStage, TaskProgress], None]


class EngineError(RuntimeError):
    code = "SEARCH_FAILED"


class ModelUnavailableError(EngineError):
    code = "MODEL_UNAVAILABLE"


class TaskCancelledError(EngineError):
    code = "TASK_CANCELLED"


class SearchEngine(Protocol):
    def run(self, request: ModelSearchRequest, progress: ProgressCallback) -> dict[str, Any]: ...


def _tree_counts(tree: dict[str, Any]) -> tuple[int, int]:
    found = selected = 0
    queue = [tree]
    while queue:
        node = queue.pop(0)
        for children in (node.get("child") or {}).values():
            for child in children:
                queue.append(child)
                found += 1
                selected += float(child.get("select_score") or 0.0) > 0.5
    return found, selected


class MockSearchEngine:
    """Deterministic local engine used for frontend integration and API tests."""

    def __init__(self, step_delay: float = 0.15) -> None:
        self.step_delay = step_delay

    def _step(self, stage: TaskStage, progress: ProgressCallback, state: TaskProgress) -> None:
        time.sleep(self.step_delay)
        progress(stage, state)

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


class PasaSearchEngine:
    """Lazy adapter around the original synchronous PaSa implementation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._load_lock = threading.Lock()
        self._crawler: Any | None = None
        self._selector: Any | None = None

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
                    )
            except Exception as exc:
                raise ModelUnavailableError(f"模型加载失败: {exc}") from exc
            return self._crawler, self._selector

    def run(self, request: ModelSearchRequest, progress: ProgressCallback) -> dict[str, Any]:
        total = request.options.expand_layers
        progress(TaskStage.LOADING, TaskProgress(total_layers=total))
        crawler, selector = self._load_models()

        try:
            from paper_agent import PaperAgent

            end_date = request.end_date.strftime("%Y%m%d") if request.end_date else None
            kwargs: dict[str, Any] = {
                "user_query": request.query,
                "crawler": crawler,
                "selector": selector,
                "prompts_path": str(self.settings.prompts_path),
                "expand_layers": request.options.expand_layers,
                "search_queries": request.options.search_queries,
                "search_papers": request.options.search_papers,
                "expand_papers": request.options.expand_papers,
                "threads_num": self.settings.threads_num,
            }
            if end_date is not None:
                kwargs["end_date"] = end_date
            agent = PaperAgent(**kwargs)

            progress(TaskStage.GENERATING_QUERIES, TaskProgress(total_layers=total))
            agent.search()
            tree = agent.root.todic()
            found, selected = _tree_counts(tree)
            progress(
                TaskStage.SELECTING,
                TaskProgress(total_layers=total, papers_found=found, papers_selected=selected),
            )

            for depth in range(total):
                agent.expand(depth)
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
            return agent.root.todic()
        except TaskCancelledError:
            raise
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(str(exc)) from exc


def create_engine(settings: Settings) -> SearchEngine:
    if settings.is_mock:
        return MockSearchEngine(settings.mock_step_delay)
    return PasaSearchEngine(settings)

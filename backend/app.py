from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.config import Settings, get_settings
from backend.engine import EngineError, ModelUnavailableError, create_engine
from backend.errors import (
    ApiError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from backend.result_formatter import format_result
from backend.schemas import ErrorResponse, HealthResponse, ModelSearchRequest, ModelSearchResponse, TaskProgress, TaskStage


log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings)
    inference_slots = threading.BoundedSemaphore(settings.max_workers)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.preload_models:
            log.info("Preloading PaSa crawler and selector models")
            await asyncio.to_thread(engine.preload)
            log.info("PaSa model preload completed")
        yield

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Internal PaSa Python model service. Public task APIs are provided by java-backend.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Internal-Token", "X-Request-ID"],
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": settings.app_name, "docs": "/docs", "health": "/internal/v1/health"}

    @app.get("/internal/v1/health", response_model=HealthResponse, tags=["internal"])
    def health() -> HealthResponse:
        ready, reasons = settings.readiness()
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            environment=settings.app_env,
            engine_mode=settings.engine_mode,
            ready=ready,
            reasons=reasons,
        )

    @app.post(
        "/internal/v1/search",
        response_model=ModelSearchResponse,
        status_code=status.HTTP_200_OK,
        responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
        tags=["internal"],
    )
    def run_model_search(payload: ModelSearchRequest, request: Request) -> ModelSearchResponse:
        if settings.internal_token and request.headers.get("X-Internal-Token") != settings.internal_token:
            raise ApiError(401, "UNAUTHORIZED", "内部服务凭证无效")
        ready, reasons = settings.readiness()
        if not ready:
            raise ApiError(503, "MODEL_UNAVAILABLE", "PaSa 搜索引擎尚未就绪", reasons)
        if not inference_slots.acquire(blocking=False):
            raise ApiError(429, "MODEL_BUSY", "模型服务正在执行其他任务")
        try:
            try:
                tree = engine.run(payload, lambda _stage, _progress: None)
            except ModelUnavailableError as exc:
                raise ApiError(503, exc.code, "PaSa 模型不可用") from exc
            except EngineError as exc:
                raise ApiError(502, exc.code, "PaSa 论文检索执行失败") from exc
            result = format_result(payload.request_id, payload.query, tree)
            result = result.model_copy(update={"analysis": engine.analyze(payload, result)})
            return result.model_copy(update={"metrics": engine.metrics()})
        finally:
            inference_slots.release()

    @app.post(
        "/internal/v1/search/stream",
        status_code=status.HTTP_200_OK,
        responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
        tags=["internal"],
    )
    def stream_model_search(payload: ModelSearchRequest, request: Request) -> StreamingResponse:
        """Stream real engine progress followed by exactly one result or error event."""
        if settings.internal_token and request.headers.get("X-Internal-Token") != settings.internal_token:
            raise ApiError(401, "UNAUTHORIZED", "内部服务凭证无效")
        ready, reasons = settings.readiness()
        if not ready:
            raise ApiError(503, "MODEL_UNAVAILABLE", "PaSa 搜索引擎尚未就绪", reasons)
        if not inference_slots.acquire(blocking=False):
            raise ApiError(429, "MODEL_BUSY", "模型服务正在执行其他任务")

        events: queue.Queue[dict[str, object] | None] = queue.Queue()

        def publish_progress(stage, progress: TaskProgress) -> None:
            events.put({
                "type": "progress",
                "stage": stage.value,
                "progress": progress.model_dump(mode="json"),
            })

        def execute() -> None:
            try:
                tree = engine.run(payload, publish_progress)
                result = format_result(payload.request_id, payload.query, tree)
                publish_progress(TaskStage.ANALYZING, TaskProgress(
                    current_layer=payload.options.expand_layers,
                    total_layers=payload.options.expand_layers,
                    papers_found=result.summary.paper_count,
                    papers_selected=result.summary.selected_count,
                ))
                result = result.model_copy(update={"analysis": engine.analyze(payload, result)})
                result = result.model_copy(update={"metrics": engine.metrics()})
                events.put({"type": "result", "data": result.model_dump(mode="json")})
            except ModelUnavailableError as exc:
                events.put({"type": "error", "error": {
                    "code": exc.code,
                    "message": "PaSa 模型不可用",
                    "details": None,
                }})
            except EngineError as exc:
                log.exception("Search engine failed for request %s", payload.request_id)
                events.put({"type": "error", "error": {
                    "code": exc.code,
                    "message": "PaSa 论文检索执行失败",
                    "details": None,
                }})
            except Exception:
                log.exception("Unhandled model-service failure for request %s", payload.request_id)
                events.put({"type": "error", "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "模型服务内部错误",
                    "details": None,
                }})
            finally:
                inference_slots.release()
                events.put(None)

        def event_stream():
            threading.Thread(
                target=execute,
                name=f"pasa-search-stream-{payload.request_id}",
                daemon=True,
            ).start()
            while True:
                event = events.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"

        return StreamingResponse(event_stream(), media_type="application/x-ndjson")

    return app


app = create_app()

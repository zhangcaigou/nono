from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskStage(str, Enum):
    QUEUED = "queued"
    LOADING = "loading"
    GENERATING_QUERIES = "generating_queries"
    SEARCHING = "searching"
    SELECTING = "selecting"
    EXPANDING = "expanding"
    FINISHED = "finished"


class SearchOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expand_layers: int = Field(default=2, ge=0, le=4)
    search_queries: int = Field(default=5, ge=1, le=10)
    search_papers: int = Field(default=10, ge=1, le=30)
    expand_papers: int = Field(default=20, ge=1, le=50)


class ModelSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=3, max_length=2000)
    end_date: date | None = None
    options: SearchOptions = Field(default_factory=SearchOptions)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("query 去除空白后至少需要 3 个字符")
        return value


class TaskProgress(BaseModel):
    current_layer: int = 0
    total_layers: int = 0
    papers_found: int = 0
    papers_selected: int = 0


class PaperItem(BaseModel):
    paper_id: str = ""
    arxiv_id: str
    openalex_id: str | None = None
    doi: str | None = None
    title: str
    abstract: str
    score: float
    selected: bool
    depth: int
    source: str
    arxiv_url: str | None
    url: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    venue: str | None = None
    cited_by_count: int = 0
    authors: list[str] = Field(default_factory=list)
    retrieval_providers: list[str] = Field(default_factory=list)


class ResultSummary(BaseModel):
    paper_count: int
    selected_count: int


class ModelSearchResponse(BaseModel):
    request_id: str
    query: str
    papers: list[PaperItem]
    tree: dict[str, Any]
    summary: ResultSummary


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    engine_mode: str
    ready: bool
    reasons: list[str] = Field(default_factory=list)


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody

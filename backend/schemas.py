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
    ANALYZING = "analyzing"
    FINISHED = "finished"


class SearchOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expand_layers: int = Field(default=0, ge=0, le=4)
    search_queries: int = Field(default=5, ge=1, le=10)
    search_papers: int = Field(default=10, ge=1, le=30)
    expand_papers: int = Field(default=10, ge=1, le=50)


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


class QueryUnderstanding(BaseModel):
    research_intent: str = ""
    entities: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)
    soft_constraints: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    sub_questions: list[str] = Field(default_factory=list)
    comparison_dimensions: list[str] = Field(default_factory=list)


class PaperAnalysis(BaseModel):
    paper_id: str
    relevance_level: str = "partial"
    one_sentence_summary: str = ""
    research_problem: str = ""
    methodology: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    contributions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class AnalysisTheme(BaseModel):
    theme_id: str
    name: str
    summary: str = ""
    paper_ids: list[str] = Field(default_factory=list)


class SemanticRelation(BaseModel):
    relation_id: str
    from_paper_id: str
    to_paper_id: str
    relation_class: str = "inferred"
    type: str
    description: str
    evidence_from: str = ""
    evidence_to: str = ""
    confidence: float = Field(default=0.7, ge=0, le=1)


class SearchSynthesis(BaseModel):
    direct_answer: str = ""
    overview: str = ""
    themes: list[AnalysisTheme] = Field(default_factory=list)
    consensus: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    recommended_reading_order: list[str] = Field(default_factory=list)
    comparison_dimensions: list[str] = Field(default_factory=list)


class SearchAnalysis(BaseModel):
    query_understanding: QueryUnderstanding
    paper_analyses: list[PaperAnalysis] = Field(default_factory=list)
    synthesis: SearchSynthesis
    semantic_relations: list[SemanticRelation] = Field(default_factory=list)
    analyzed_paper_count: int = 0
    model: str = "pasa-7b-crawler"
    estimated_model_calls: int = 0
    candidate_pair_count: int = 0
    possible_pair_count: int = 0


class ModelSearchResponse(BaseModel):
    request_id: str
    query: str
    papers: list[PaperItem]
    tree: dict[str, Any]
    summary: ResultSummary
    analysis: SearchAnalysis | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


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

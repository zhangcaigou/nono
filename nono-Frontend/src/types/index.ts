// ===== 任务状态 =====
export type TaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type TaskStage =
  | 'queued'
  | 'loading'
  | 'searching'
  | 'enriching'
  | 'finished'

// ===== 健康检查 =====
export interface HealthResponse {
  status: string
  service: string
  ready: boolean
  model_service_ready?: boolean
  engine_mode?: string
  environment?: string
  reasons: string[]
}

// ===== 创建任务 =====
export interface CreateSearchTaskRequest {
  query: string
  end_date?: string | null
  options?: {
    expand_layers?: number
    search_queries?: number
    search_papers?: number
    expand_papers?: number
  }
}

export interface SearchTaskAccepted {
  task_id: string
  status: 'queued'
  created_at: string
}

// ===== 任务进度 =====
export interface TaskProgress {
  current_layer: number
  total_layers: number
  papers_found: number
  papers_selected: number
}

export interface TaskError {
  code: string
  message: string
  details: unknown | null
}

export interface SearchTask {
  task_id: string
  query: string
  status: TaskStatus
  stage: TaskStage
  progress: TaskProgress
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: TaskError | null
}

// ===== 查询约束 =====
export type ConstraintType = 'hard' | 'soft' | 'exclusion' | 'output'

export interface QueryConstraint {
  constraint_id: string
  type: ConstraintType
  text: string
}

// ===== 约束评估 =====
export type ConstraintStatus = 'satisfied' | 'partially_satisfied' | 'violated' | 'unknown'

export interface ConstraintAssessment {
  constraint_id: string
  status: ConstraintStatus
  explanation: string
  evidence_ids: string[]
}

// ===== 证据 =====
export type EvidenceSourceType =
  | 'title'
  | 'abstract'
  | 'fulltext'
  | 'metadata'
  | 'citation_database'

export interface Evidence {
  evidence_id: string
  source_type: EvidenceSourceType
  exact_text: string
  location: string
  constraint_ids: string[]
  confidence: number
  source: string
  source_url: string | null
}

// ===== 推荐理由 =====
export interface RecommendationReason {
  text: string
  constraint_ids: string[]
  evidence_ids: string[]
}

// ===== 推荐追溯 =====
export interface RecommendationTrace {
  reasons: RecommendationReason[]
  satisfied_constraints: ConstraintAssessment[]
  partially_satisfied_constraints: ConstraintAssessment[]
  violated_constraints: ConstraintAssessment[]
  unknown_constraints: ConstraintAssessment[]
  evidence: Evidence[]
  retrieval_sources: string[]
}

// ===== 论文关系 =====
export type RelationClass = 'confirmed' | 'inferred'
export type RelationType =
  | 'cites'
  | 'cited_by'
  | 'same_method'
  | 'extends_method'
  | 'same_task'
  | 'same_dataset'

export interface PaperRelation {
  relation_id: string
  from_paper_id: string
  to_paper_id: string
  relation_class: RelationClass
  type: RelationType
  description: string
  evidence_ids: string[]
  evidence: Evidence[]
  confidence: number
}

// ===== 结果 =====
export interface PaperItem {
  paper_id: string
  arxiv_id: string
  openalex_id: string | null
  doi: string | null
  title: string
  abstract: string
  score: number
  selected: boolean
  depth: number
  source: string
  arxiv_url: string | null
  url: string | null
  publication_year: number | null
  publication_date: string | null
  venue: string | null
  cited_by_count: number
  authors: string[]
  retrieval_providers: string[]
  abstract_status: 'provided' | 'enriched' | 'unavailable'
  abstract_source: string
  abstract_source_url: string | null
  recommendation_trace: RecommendationTrace | null
}

export interface SearchResult {
  task_id: string
  query: string
  constraints: QueryConstraint[]
  traceability_enabled: boolean
  papers: PaperItem[]
  relations: PaperRelation[]
  tree: Record<string, unknown>
  summary: {
    paper_count: number
    selected_count: number
    abstract_available_count: number
    abstract_enriched_count: number
    traceable_selected_count: number
    relation_count: number
  }
}

// ===== 统一错误响应 =====
export interface ApiErrorResponse {
  error: {
    code: string
    message: string
    request_id: string
    details: unknown | null
  }
}

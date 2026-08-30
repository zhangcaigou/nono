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
  model_service_ready: boolean
  engine_mode?: string
  environment?: string
  reasons: string[]
}

// ===== 创建任务 =====
export interface SearchOptions {
  expand_layers?: number
  search_queries?: number
  search_papers?: number
  expand_papers?: number
  recommendation_analysis?: boolean
}

export interface SearchFormOptions {
  end_date?: string | null
  options?: SearchOptions
}

export interface CreateSearchTaskRequest {
  query: string
  end_date?: string | null
  options?: SearchOptions
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
  importance: ConstraintType
  description: string
  original_text: string
}

export interface DeepSeekEvidenceLocation {
  field: string
  sentence_index: number | null
  section: string | null
  page: number | null
}

export interface DeepSeekEvidence {
  evidence_id: string
  source_type: 'title' | 'abstract' | 'fulltext' | 'metadata'
  exact_text: string
  location: DeepSeekEvidenceLocation
  supports_constraints: string[]
  confidence: number
}

export interface DeepSeekConstraintResult {
  constraint_id: string
  status: ConstraintStatus
  explanation: string
  evidence_ids: string[]
  confidence: number
}

export interface DeepSeekTrace {
  recommendation_reason: string
  relevance_level: 'high' | 'partial' | 'low'
  constraint_results: DeepSeekConstraintResult[]
  evidence: DeepSeekEvidence[]
  satisfied_constraints: string[]
  partially_satisfied_constraints: string[]
  violated_constraints: string[]
  unknown_constraints: string[]
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
  | 'compares_with'
  | 'contradicts'
  | 'survey_of'

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

export interface QueryUnderstanding {
  research_intent: string
  entities: string[]
  methods: string[]
  domains: string[]
  datasets: string[]
  hard_constraints: string[]
  soft_constraints: string[]
  exclusions: string[]
  sub_questions: string[]
  comparison_dimensions: string[]
}

export interface PaperSemanticAnalysis {
  paper_id: string
  relevance_level: 'high' | 'partial' | 'low'
  one_sentence_summary: string
  research_problem: string
  methodology: string[]
  datasets: string[]
  key_findings: string[]
  contributions: string[]
  limitations: string[]
  evidence: string[]
}

export interface AnalysisTheme {
  theme_id: string
  name: string
  summary: string
  paper_ids: string[]
}

export interface SemanticRelation {
  relation_id: string
  from_paper_id: string
  to_paper_id: string
  relation_class: 'inferred'
  type: RelationType
  description: string
  evidence_from: string
  evidence_to: string
  confidence: number
}

export interface SearchAnalysis {
  query_understanding: QueryUnderstanding
  paper_analyses: PaperSemanticAnalysis[]
  synthesis: {
    direct_answer: string
    overview: string
    themes: AnalysisTheme[]
    consensus: string[]
    disagreements: string[]
    research_gaps: string[]
    recommended_reading_order: string[]
    comparison_dimensions: string[]
  }
  semantic_relations: SemanticRelation[]
  analyzed_paper_count: number
  model: string
  estimated_model_calls: number
  candidate_pair_count: number
  possible_pair_count: number
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
  selector_score: number | null
  selector_reason: string | null
  trace_status: 'success' | 'degraded' | 'disabled'
  deepseek_trace: DeepSeekTrace | null
}

export interface SearchResult {
  task_id: string
  query: string
  constraints: QueryConstraint[]
  traceability_enabled: boolean
  papers: PaperItem[]
  relations: PaperRelation[]
  analysis: SearchAnalysis | null
  tree: Record<string, unknown>
  summary: {
    paper_count: number
    selected_count: number
    abstract_available_count: number
    abstract_enriched_count: number
    traceable_selected_count: number
    relation_count: number
  }
  deepseek_usage: {
    total_calls: number
    input_tokens: number
    output_tokens: number
    cache_hits: number
    degraded_papers: number
    model_name: string
  } | null
  efficiency: {
    total_ms: number
    model_search_ms: number
    traceability_ms: number
    deepseek_ms: number
    tracked_api_calls: number
    input_tokens: number
    output_tokens: number
    model_metrics: Record<string, unknown> | null
  } | null
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

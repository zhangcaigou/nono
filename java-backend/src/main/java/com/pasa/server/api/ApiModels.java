package com.pasa.server.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

public final class ApiModels {
    private ApiModels() {}

    public record SearchOptions(
            @JsonProperty("expand_layers") @Min(0) @Max(4) Integer expandLayers,
            @JsonProperty("search_queries") @Min(1) @Max(10) Integer searchQueries,
            @JsonProperty("search_papers") @Min(1) @Max(30) Integer searchPapers,
            @JsonProperty("expand_papers") @Min(1) @Max(50) Integer expandPapers
    ) {
        public SearchOptions normalized() {
            return new SearchOptions(
                    expandLayers == null ? 2 : expandLayers,
                    searchQueries == null ? 5 : searchQueries,
                    searchPapers == null ? 10 : searchPapers,
                    expandPapers == null ? 20 : expandPapers
            );
        }
    }

    public record CreateSearchTaskRequest(
            @NotBlank @Size(min = 3, max = 2000) String query,
            @JsonProperty("end_date") LocalDate endDate,
            @Valid SearchOptions options
    ) {}

    public record TaskAccepted(
            @JsonProperty("task_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String taskId,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String status,
            @JsonProperty("created_at") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) Instant createdAt
    ) {}
    public record TaskProgress(
            @JsonProperty("current_layer") int currentLayer,
            @JsonProperty("total_layers") int totalLayers,
            @JsonProperty("papers_found") int papersFound,
            @JsonProperty("papers_selected") int papersSelected
    ) {}
    public record TaskError(String code, String message, Object details) {}
    public record TaskView(
            @JsonProperty("task_id") String taskId,
            String query,
            String status,
            String stage,
            TaskProgress progress,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("started_at") Instant startedAt,
            @JsonProperty("finished_at") Instant finishedAt,
            TaskError error
    ) {}

    public record PaperItem(
            @JsonProperty("paper_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String paperId,
            @JsonProperty("arxiv_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String arxivId,
            @JsonProperty("openalex_id")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String openalexId,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String doi,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String title,
            @JsonProperty("abstract") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String abstractText,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) double score,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) boolean selected,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) int depth,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String source,
            @JsonProperty("arxiv_url")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String arxivUrl,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String url,
            @JsonProperty("publication_year")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"integer", "null"}) Integer publicationYear,
            @JsonProperty("publication_date")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String publicationDate,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String venue,
            @JsonProperty("cited_by_count") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) int citedByCount,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<String> authors,
            @JsonProperty("retrieval_providers") @Schema(requiredMode = Schema.RequiredMode.REQUIRED)
            List<String> retrievalProviders,
            @JsonProperty("abstract_status")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED,
                    allowableValues = {"provided", "enriched", "unavailable"}) String abstractStatus,
            @JsonProperty("abstract_source")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED,
                    allowableValues = {"openalex", "arxiv", "semantic_scholar", "crossref", "model_result", "unavailable"})
            String abstractSource,
            @JsonProperty("abstract_source_url")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String abstractSourceUrl,
            @JsonProperty("recommendation_trace")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"object", "null"})
            RecommendationTrace recommendationTrace
    ) {
        public PaperItem(
                String paperId, String arxivId, String openalexId, String doi, String title,
                String abstractText, double score, boolean selected, int depth, String source,
                String arxivUrl, String url, Integer publicationYear, String publicationDate,
                String venue, int citedByCount, List<String> authors, List<String> retrievalProviders
        ) {
            this(paperId, arxivId, openalexId, doi, title, abstractText, score, selected, depth,
                    source, arxivUrl, url, publicationYear, publicationDate, venue, citedByCount,
                    authors, retrievalProviders, null, null, null, null);
        }
    }

    public record Evidence(
            @JsonProperty("evidence_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String evidenceId,
            @JsonProperty("source_type") @Schema(requiredMode = Schema.RequiredMode.REQUIRED,
                    allowableValues = {"title", "abstract", "fulltext", "metadata", "citation_database"})
            String sourceType,
            @JsonProperty("exact_text") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String exactText,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String location,
            @JsonProperty("constraint_ids") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<String> constraintIds,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, minimum = "0", maximum = "1") double confidence,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String source,
            @JsonProperty("source_url")
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, types = {"string", "null"}) String sourceUrl
    ) {}

    public record QueryConstraint(
            @JsonProperty("constraint_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String constraintId,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED,
                    allowableValues = {"hard", "soft", "exclusion", "output"}) String type,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String text
    ) {}

    public record ConstraintAssessment(
            @JsonProperty("constraint_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String constraintId,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED,
                    allowableValues = {"satisfied", "partially_satisfied", "violated", "unknown"}) String status,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String explanation,
            @JsonProperty("evidence_ids") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<String> evidenceIds
    ) {}

    public record RecommendationReason(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String text,
            @JsonProperty("constraint_ids") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<String> constraintIds,
            @JsonProperty("evidence_ids") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<String> evidenceIds
    ) {}

    public record RecommendationTrace(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<RecommendationReason> reasons,
            @JsonProperty("satisfied_constraints") @Schema(requiredMode = Schema.RequiredMode.REQUIRED)
            List<ConstraintAssessment> satisfiedConstraints,
            @JsonProperty("partially_satisfied_constraints") @Schema(requiredMode = Schema.RequiredMode.REQUIRED)
            List<ConstraintAssessment> partiallySatisfiedConstraints,
            @JsonProperty("violated_constraints") @Schema(requiredMode = Schema.RequiredMode.REQUIRED)
            List<ConstraintAssessment> violatedConstraints,
            @JsonProperty("unknown_constraints") @Schema(requiredMode = Schema.RequiredMode.REQUIRED)
            List<ConstraintAssessment> unknownConstraints,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<Evidence> evidence,
            @JsonProperty("retrieval_sources") @Schema(requiredMode = Schema.RequiredMode.REQUIRED)
            List<String> retrievalSources
    ) {}

    public record PaperRelation(
            @JsonProperty("relation_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String relationId,
            @JsonProperty("from_paper_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String fromPaperId,
            @JsonProperty("to_paper_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String toPaperId,
            @JsonProperty("relation_class") @Schema(requiredMode = Schema.RequiredMode.REQUIRED,
                    allowableValues = {"confirmed", "inferred"}) String relationClass,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED,
                    allowableValues = {"cites", "cited_by", "same_method", "extends_method", "same_task", "same_dataset"})
            String type,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String description,
            @JsonProperty("evidence_ids") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<String> evidenceIds,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<Evidence> evidence,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, minimum = "0", maximum = "1") double confidence
    ) {}

    public record ResultSummary(
            @JsonProperty("paper_count") int paperCount,
            @JsonProperty("selected_count") int selectedCount,
            @JsonProperty("abstract_available_count") int abstractAvailableCount,
            @JsonProperty("abstract_enriched_count") int abstractEnrichedCount,
            @JsonProperty("traceable_selected_count") int traceableSelectedCount,
            @JsonProperty("relation_count") int relationCount
    ) {
        public ResultSummary(int paperCount, int selectedCount) {
            this(paperCount, selectedCount, 0, 0, 0, 0);
        }
    }
    public record TaskResult(
            @JsonProperty("task_id") @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String taskId,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) String query,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<QueryConstraint> constraints,
            @JsonProperty("traceability_enabled") @Schema(requiredMode = Schema.RequiredMode.REQUIRED)
            boolean traceabilityEnabled,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<PaperItem> papers,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<PaperRelation> relations,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) JsonNode tree,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) ResultSummary summary
    ) {
        public TaskResult(String taskId, String query, List<PaperItem> papers, JsonNode tree,
                          ResultSummary summary) {
            this(taskId, query, List.of(), false, papers, List.of(), tree, summary);
        }
    }

    public record HealthResponse(
            String status,
            String service,
            boolean ready,
            @JsonProperty("model_service_ready") boolean modelServiceReady,
            List<String> reasons
    ) {}

    public record ErrorBody(
            String code,
            String message,
            @JsonProperty("request_id") String requestId,
            Object details
    ) {}
    public record ErrorResponse(ErrorBody error) {}
}

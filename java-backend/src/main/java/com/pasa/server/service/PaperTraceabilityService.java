package com.pasa.server.service;

import com.pasa.server.api.ApiModels;

import java.time.LocalDate;
import java.util.List;

public interface PaperTraceabilityService {
    TraceablePapers enrich(String query, LocalDate endDate, List<ApiModels.PaperItem> papers);

    default ApiModels.RecommendationTrace enrichFullText(
            String query,
            LocalDate endDate,
            ApiModels.PaperItem paper
    ) {
        return paper.recommendationTrace();
    }

    static TraceablePapers degraded(List<ApiModels.PaperItem> papers) {
        return new TraceablePapers(papers.stream().map(PaperTraceabilityService::withoutTrace).toList(),
                List.of(), List.of(), false);
    }

    private static ApiModels.PaperItem withoutTrace(ApiModels.PaperItem paper) {
        boolean hasAbstract = paper.abstractText() != null && !paper.abstractText().isBlank();
        String abstractStatus = textOr(paper.abstractStatus(), hasAbstract ? "provided" : "unavailable");
        String abstractSource = textOr(paper.abstractSource(), hasAbstract ? inferSource(paper) : "unavailable");
        return new ApiModels.PaperItem(
                paper.paperId(), paper.arxivId(), paper.openalexId(), paper.doi(), paper.title(),
                hasAbstract ? paper.abstractText() : "", paper.score(), paper.selected(), paper.depth(), paper.source(),
                paper.arxivUrl(), paper.url(), paper.publicationYear(), paper.publicationDate(), paper.venue(),
                paper.citedByCount(), safeList(paper.authors()), safeList(paper.retrievalProviders()),
                abstractStatus, abstractSource, textOr(paper.abstractSourceUrl(), hasAbstract ? paper.url() : null), null,
                paper.selectorScore() == null ? paper.score() : paper.selectorScore(), paper.selectorReason(),
                paper.traceStatus() == null ? "disabled" : paper.traceStatus(), paper.deepseekTrace());
    }

    private static String inferSource(ApiModels.PaperItem paper) {
        if (paper.retrievalProviders() != null && paper.retrievalProviders().contains("openalex")) {
            return "openalex";
        }
        return paper.arxivId() != null && !paper.arxivId().isBlank() ? "arxiv" : "model_result";
    }

    private static String textOr(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    private static <T> List<T> safeList(List<T> value) {
        return value == null ? List.of() : List.copyOf(value);
    }

    record TraceablePapers(
            List<ApiModels.PaperItem> papers,
            List<ApiModels.PaperRelation> relations,
            List<ApiModels.QueryConstraint> constraints,
            boolean enabled
    ) {}
}

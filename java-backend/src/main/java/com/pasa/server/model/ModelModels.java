package com.pasa.server.model;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.pasa.server.api.ApiModels;

import java.time.LocalDate;
import java.util.List;

public final class ModelModels {
    private ModelModels() {}

    public record ModelSearchRequest(
            @JsonProperty("request_id") String requestId,
            String query,
            @JsonProperty("end_date") LocalDate endDate,
            ApiModels.SearchOptions options
    ) {}

    public record ModelSearchResponse(
            @JsonProperty("request_id") String requestId,
            String query,
            List<ApiModels.PaperItem> papers,
            JsonNode tree,
            ApiModels.ResultSummary summary
    ) {}

    public record ModelProgress(
            String stage,
            int currentLayer,
            int totalLayers,
            int papersFound,
            int papersSelected
    ) {}
}

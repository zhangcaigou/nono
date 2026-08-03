package com.pasa.server.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.pasa.server.config.PasaProperties;
import com.pasa.server.model.ModelModels.ModelSearchRequest;
import com.pasa.server.model.ModelModels.ModelSearchResponse;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

@Component
public class HttpModelGateway implements ModelGateway {
    private static final MediaType NDJSON = MediaType.parseMediaType("application/x-ndjson");
    private final RestClient client;
    private final PasaProperties properties;
    private final ObjectMapper objectMapper;

    public HttpModelGateway(@Qualifier("modelRestClient") RestClient modelRestClient,
                            PasaProperties properties, ObjectMapper objectMapper) {
        this.client = modelRestClient;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    @Override
    public ModelSearchResponse search(ModelSearchRequest request) {
        return legacySearch(request);
    }

    @Override
    public ModelSearchResponse search(ModelSearchRequest request, ProgressListener progressListener) {
        try {
            return streamSearch(request, progressListener);
        } catch (StreamNotSupportedException exception) {
            progressListener.onProgress(new ModelModels.ModelProgress(
                    "searching", 0, request.options().expandLayers(), 0, 0));
            return legacySearch(request);
        }
    }

    private ModelSearchResponse legacySearch(ModelSearchRequest request) {
        RestClient.RequestBodySpec spec = client.post()
                .uri("/internal/v1/search")
                .contentType(MediaType.APPLICATION_JSON);
        if (!properties.getInternalToken().isBlank()) {
            spec.header("X-Internal-Token", properties.getInternalToken());
        }
        ModelSearchResponse response;
        try {
            response = spec.body(payload(request)).retrieve().body(ModelSearchResponse.class);
        } catch (RestClientResponseException exception) {
            throw modelServiceException(exception);
        }
        if (response == null) {
            throw new IllegalStateException("Python 模型服务返回空响应");
        }
        return response;
    }

    private ModelSearchResponse streamSearch(ModelSearchRequest request, ProgressListener progressListener) {
        RestClient.RequestBodySpec spec = client.post()
                .uri("/internal/v1/search/stream")
                .contentType(MediaType.APPLICATION_JSON);
        spec.accept(NDJSON);
        if (!properties.getInternalToken().isBlank()) {
            spec.header("X-Internal-Token", properties.getInternalToken());
        }
        return spec.body(payload(request)).exchange((httpRequest, response) -> {
            int status = response.getStatusCode().value();
            if (status == 404 || status == 405) {
                throw new StreamNotSupportedException();
            }
            if (response.getStatusCode().isError()) {
                String body = new String(response.getBody().readAllBytes(), StandardCharsets.UTF_8);
                throw modelServiceException(body, null);
            }
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(response.getBody(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.isBlank()) {
                        continue;
                    }
                    JsonNode event = objectMapper.readTree(line);
                    switch (event.path("type").asText()) {
                        case "progress" -> progressListener.onProgress(progress(event));
                        case "result" -> {
                            return objectMapper.treeToValue(event.path("data"), ModelSearchResponse.class);
                        }
                        case "error" -> throw modelServiceException(event.path("error").toString(), null);
                        default -> throw new IllegalStateException("Python 模型服务返回未知流事件");
                    }
                }
            }
            throw new IllegalStateException("Python 模型服务流结束前未返回结果");
        });
    }

    private ModelModels.ModelProgress progress(JsonNode event) {
        JsonNode value = event.path("progress");
        return new ModelModels.ModelProgress(
                event.path("stage").asText("searching"),
                value.path("current_layer").asInt(0),
                value.path("total_layers").asInt(0),
                value.path("papers_found").asInt(0),
                value.path("papers_selected").asInt(0)
        );
    }

    private Map<String, Object> payload(ModelSearchRequest request) {
        Map<String, Object> options = new LinkedHashMap<>();
        options.put("expand_layers", request.options().expandLayers());
        options.put("search_queries", request.options().searchQueries());
        options.put("search_papers", request.options().searchPapers());
        options.put("expand_papers", request.options().expandPapers());

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("request_id", request.requestId());
        payload.put("query", request.query());
        if (request.endDate() != null) {
            payload.put("end_date", request.endDate().toString());
        }
        payload.put("options", options);

        return payload;
    }

    private ModelServiceException modelServiceException(RestClientResponseException exception) {
        return modelServiceException(exception.getResponseBodyAsString(), exception);
    }

    private ModelServiceException modelServiceException(String responseBody, Throwable cause) {
        try {
            JsonNode parsed = objectMapper.readTree(responseBody);
            JsonNode error = parsed.has("error") ? parsed.path("error") : parsed;
            String code = error.path("code").asText("MODEL_SERVICE_ERROR");
            String message = error.path("message").asText("Python 模型服务执行失败");
            Object details = error.hasNonNull("details") ? objectMapper.treeToValue(error.get("details"), Object.class) : null;
            return new ModelServiceException(code, message, details, cause);
        } catch (Exception parseException) {
            return new ModelServiceException(
                    "MODEL_SERVICE_ERROR",
                    "Python 模型服务返回错误响应",
                    null,
                    cause
            );
        }
    }

    @Override
    public Readiness readiness() {
        try {
            JsonNode body = client.get().uri("/internal/v1/health").retrieve().body(JsonNode.class);
            boolean ready = body != null && body.path("ready").asBoolean(false);
            return new Readiness(ready, ready ? null : "Python 模型服务尚未就绪");
        } catch (Exception exception) {
            return new Readiness(false, "无法连接 Python 模型服务");
        }
    }

    private static final class StreamNotSupportedException extends RuntimeException {}
}

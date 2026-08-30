package com.pasa.server.deepseek;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.pasa.server.api.ApiModels;
import com.pasa.server.config.PasaProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Semaphore;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class DeepSeekEvidenceGenerator {
    private static final Logger log = LoggerFactory.getLogger(DeepSeekEvidenceGenerator.class);
    private static final Set<String> STATUSES = Set.of(
            "satisfied", "partially_satisfied", "violated", "unknown");
    private static final Set<String> RELEVANCE = Set.of("high", "partial", "low");
    private static final Set<String> SOURCE_TYPES = Set.of("title", "abstract", "metadata", "fulltext");
    private static final Pattern UNHELPFUL_REASON_CLAUSE = Pattern.compile(
            "(?i)(无法确认|不能确认|尚无法确认|未能确认|无从确认|未提供|没有提供|"
                    + "缺少.{0,24}(?:信息|细节|内容|证据)|仅提供.{0,16}(?:标题|摘要)|"
                    + "cannot be confirmed|cannot confirm|could not be confirmed|"
                    + "not (?:provided|stated|available)|does not provide|"
                    + "lack(?:s|ing)? .{0,32}(?:information|details|evidence))");
    private static final Pattern CONTRAST_TRANSITION = Pattern.compile(
            "(?i)(?:[；;，,]\s*)?(?:然而|但是|但|不过|可是|although|however|but)\s*[，,]?");
    private static final Pattern GENERIC_RECOMMENDATION_CLAUSE = Pattern.compile(
            "(?i)(?:[；;，,]\\s*)?(?:(?:因此|从而|因而|所以|这(?:一结果|使其)?|该研究)?\\s*)?"
                    + "(?:(?:符合|满足|契合|回应)用户.{0,30}(?:需求|目的|关注)|"
                    + "(?:具有|具备).{0,12}参考价值|"
                    + "为.{0,30}(?:提供参考|提供思路|提供依据)|"
                    + "有助于(?:用户)?(?:了解|掌握|调研).{0,30}|"
                    + "研究(?:直接)?涉及(?:LLM|大语言模型).{0,40}(?:应用|模型|方法|评估|挑战|进展))");
    private static final Pattern STOCK_RECOMMENDATION_OPENING = Pattern.compile(
            "^(?:(?:该|这篇)论文|本文|本研究|该研究|该工作|这项工作)\\s*"
                    + "(?:提出|研究|探讨|介绍|设计|构建|开发|采用|评估|分析|基准测试|聚焦(?:于)?|关注)\\s*");
    private static final Pattern CHINESE_CHARACTER = Pattern.compile("[\\u3400-\\u9fff]");

    private final DeepSeekEvidenceClient client;
    private final PasaProperties properties;
    private final ObjectMapper objectMapper;
    private final String systemPrompt;
    private final Semaphore apiSlots;
    private final Map<String, ApiModels.DeepSeekTrace> cache = new ConcurrentHashMap<>();

    @Autowired
    public DeepSeekEvidenceGenerator(
            DeepSeekEvidenceClient client,
            PasaProperties properties,
            ObjectMapper objectMapper
    ) {
        this(client, properties, objectMapper, loadPrompt(properties.getDeepseekPromptVersion()));
    }

    DeepSeekEvidenceGenerator(
            DeepSeekEvidenceClient client,
            PasaProperties properties,
            ObjectMapper objectMapper,
            String systemPrompt
    ) {
        this.client = client;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.systemPrompt = systemPrompt;
        this.apiSlots = new Semaphore(properties.getDeepseekConcurrency());
    }

    public BatchResult enrich(
            String originalQuery,
            List<ApiModels.QueryConstraint> constraints,
            List<ApiModels.PaperItem> papers
    ) {
        if (!available()) {
            return new BatchResult(papers.stream().map(paper -> withTrace(paper, "disabled", null)).toList(),
                    new ApiModels.DeepSeekUsageStats(0, 0, 0, 0, 0, properties.getDeepseekModel()));
        }

        List<ApiModels.PaperItem> targets = papers.stream()
                .filter(ApiModels.PaperItem::selected)
                .limit(properties.getDeepseekMaxPapers())
                .toList();
        if (targets.isEmpty()) {
            return new BatchResult(papers.stream().map(paper -> withTrace(paper, "disabled", null)).toList(),
                    new ApiModels.DeepSeekUsageStats(0, 0, 0, 0, 0, properties.getDeepseekModel()));
        }

        Map<String, Outcome> outcomes = new HashMap<>();
        List<ApiModels.PaperItem> uncached = new ArrayList<>();
        for (ApiModels.PaperItem paper : targets) {
            ApiModels.DeepSeekTrace trace = cache.get(cacheKey(
                    originalQuery, paper.paperId(), properties.getDeepseekPromptVersion()));
            if (trace == null) {
                uncached.add(paper);
            } else {
                outcomes.put(paper.paperId(), new Outcome("success", trace,
                        0, 0, 0, 0, true, properties.getDeepseekModel()));
            }
        }

        long batchCalls = 0;
        long batchInputTokens = 0;
        long batchOutputTokens = 0;
        String batchModel = properties.getDeepseekModel();
        if (uncached.size() == 1) {
            ApiModels.PaperItem paper = uncached.getFirst();
            outcomes.put(paper.paperId(), analyze(originalQuery, constraints, paper));
        } else if (!uncached.isEmpty()) {
            BatchAnalysis analysis = analyzeBatch(originalQuery, constraints, uncached);
            outcomes.putAll(analysis.outcomes());
            batchCalls = analysis.calls();
            batchInputTokens = analysis.inputTokens();
            batchOutputTokens = analysis.outputTokens();
            batchModel = analysis.modelName();
        }

        List<ApiModels.PaperItem> result = papers.stream().map(paper -> {
            Outcome outcome = outcomes.get(paper.paperId());
            return outcome == null
                    ? withTrace(paper, "disabled", null)
                    : withTrace(paper, outcome.status(), outcome.trace());
        }).toList();
        long calls = batchCalls + outcomes.values().stream().mapToLong(Outcome::calls).sum();
        long inputTokens = batchInputTokens + outcomes.values().stream().mapToLong(Outcome::inputTokens).sum();
        long outputTokens = batchOutputTokens + outcomes.values().stream().mapToLong(Outcome::outputTokens).sum();
        long cacheHits = outcomes.values().stream().filter(Outcome::cacheHit).count();
        long degraded = outcomes.values().stream().filter(value -> "degraded".equals(value.status())).count();
        String modelName = outcomes.values().stream().map(Outcome::modelName)
                .filter(value -> value != null && !value.isBlank()).findFirst()
                .orElse(batchModel);
        return new BatchResult(result, new ApiModels.DeepSeekUsageStats(
                calls, inputTokens, outputTokens, cacheHits, degraded, modelName));
    }

    public BatchResult degraded(List<ApiModels.PaperItem> papers) {
        long degraded = papers.stream().filter(ApiModels.PaperItem::selected).count();
        List<ApiModels.PaperItem> result = papers.stream()
                .map(paper -> withTrace(paper, paper.selected() ? "degraded" : "disabled", null))
                .toList();
        return new BatchResult(result, new ApiModels.DeepSeekUsageStats(
                0, 0, 0, 0, degraded, properties.getDeepseekModel()));
    }

    public BatchResult disabled(List<ApiModels.PaperItem> papers) {
        List<ApiModels.PaperItem> result = papers.stream()
                .map(paper -> withTrace(paper, "disabled", null))
                .toList();
        return new BatchResult(result, new ApiModels.DeepSeekUsageStats(
                0, 0, 0, 0, 0, properties.getDeepseekModel()));
    }

    private boolean available() {
        return properties.isDeepseekEvidenceEnabled()
                && properties.getDeepseekMaxPapers() > 0
                && !properties.getDeepseekApiKey().isBlank();
    }

    public boolean isEnabled() {
        return available();
    }

    private Outcome analyze(
            String originalQuery,
            List<ApiModels.QueryConstraint> constraints,
            ApiModels.PaperItem paper
    ) {
        String key = cacheKey(originalQuery, paper.paperId(), properties.getDeepseekPromptVersion());
        ApiModels.DeepSeekTrace cached = cache.get(key);
        if (cached != null) {
            log.info("DeepSeek evidence paper={} model={} cache_hit=true", paper.paperId(),
                    properties.getDeepseekModel());
            return new Outcome("success", cached, 0, 0, 0, 0, true, properties.getDeepseekModel());
        }

        String userPrompt = buildUserPrompt(originalQuery, constraints, paper);
        int maxAttempts = properties.getDeepseekMaxRetries() + 1;
        long inputTokens = 0;
        long outputTokens = 0;
        int invalidResponseFailures = 0;
        Instant started = Instant.now();
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                DeepSeekEvidenceClient.Completion completion;
                apiSlots.acquire();
                try {
                    completion = client.complete(systemPrompt, userPrompt);
                } finally {
                    apiSlots.release();
                }
                inputTokens += completion.inputTokens();
                outputTokens += completion.outputTokens();
                ApiModels.DeepSeekTrace parsed = objectMapper.readValue(
                        completion.content(), ApiModels.DeepSeekTrace.class);
                ApiModels.DeepSeekTrace validated = validate(parsed, constraints, paper);
                putCache(key, validated);
                long latency = Duration.between(started, Instant.now()).toMillis();
                log.info("DeepSeek evidence paper={} model={} input_tokens={} output_tokens={} latency_ms={} retries={} cache_hit=false",
                        paper.paperId(), completion.modelName(), inputTokens, outputTokens, latency, attempt - 1);
                return new Outcome("success", validated, attempt, inputTokens, outputTokens,
                        attempt - 1, false, completion.modelName());
            } catch (Exception exception) {
                if (exception instanceof InterruptedException) {
                    Thread.currentThread().interrupt();
                }
                boolean invalidResponse = exception instanceof JsonProcessingException
                        || exception instanceof IllegalArgumentException;
                if (invalidResponse) {
                    invalidResponseFailures++;
                }
                // Malformed/schema-invalid JSON is retried once; transport/API errors use MAX_RETRIES.
                if ((invalidResponse && invalidResponseFailures >= 2) || attempt == maxAttempts) {
                    long latency = Duration.between(started, Instant.now()).toMillis();
                    log.warn("DeepSeek evidence degraded paper={} model={} latency_ms={} retries={} cause={}",
                            paper.paperId(), properties.getDeepseekModel(), latency, attempt - 1,
                            exception.getClass().getSimpleName());
                    return new Outcome("degraded", null, attempt, inputTokens, outputTokens,
                            attempt - 1, false, properties.getDeepseekModel());
                }
            }
        }
        return Outcome.degraded(properties.getDeepseekModel(), properties.getDeepseekMaxRetries());
    }

    /**
     * Audits all uncached recommendation papers in one API request. Besides reducing cost and
     * latency, paper_id keeps every response independently verifiable: one malformed trace is
     * degraded without discarding valid traces returned in the same batch.
     */
    private BatchAnalysis analyzeBatch(
            String originalQuery,
            List<ApiModels.QueryConstraint> constraints,
            List<ApiModels.PaperItem> papers
    ) {
        String userPrompt = buildBatchUserPrompt(originalQuery, constraints, papers);
        int maxAttempts = Math.min(2, properties.getDeepseekMaxRetries() + 1);
        long inputTokens = 0;
        long outputTokens = 0;
        Instant started = Instant.now();
        String modelName = properties.getDeepseekModel();
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                DeepSeekEvidenceClient.Completion completion;
                apiSlots.acquire();
                try {
                    String attemptPrompt = attempt == 1 ? userPrompt : buildCompactRetryPrompt(
                            originalQuery, constraints, papers);
                    completion = client.complete(systemPrompt, attemptPrompt);
                } finally {
                    apiSlots.release();
                }
                inputTokens += completion.inputTokens();
                outputTokens += completion.outputTokens();
                modelName = completion.modelName();
                JsonNode root = objectMapper.readTree(completion.content());
                JsonNode analyses = root.path("analyses");
                if (!analyses.isArray()) {
                    throw new IllegalArgumentException("batch response must contain analyses array");
                }
                Map<String, JsonNode> returned = new HashMap<>();
                for (JsonNode item : analyses) {
                    String paperId = item.path("paper_id").asText("");
                    if (!paperId.isBlank() && !returned.containsKey(paperId)) {
                        returned.put(paperId, item.path("trace"));
                    }
                }
                Map<String, Outcome> outcomes = new LinkedHashMap<>();
                Set<String> seenRecommendations = new HashSet<>();
                for (ApiModels.PaperItem paper : papers) {
                    try {
                        JsonNode traceNode = returned.get(paper.paperId());
                        if (traceNode == null || traceNode.isMissingNode() || traceNode.isNull()) {
                            throw new IllegalArgumentException("missing trace for paper " + paper.paperId());
                        }
                        ApiModels.DeepSeekTrace raw = objectMapper.treeToValue(
                                traceNode, ApiModels.DeepSeekTrace.class);
                        ApiModels.DeepSeekTrace validated = validate(raw, constraints, paper);
                        String recommendationKey = validated.recommendationReason()
                                .replaceAll("[\\p{Punct}\\p{IsPunctuation}\\s]+", "")
                                .toLowerCase();
                        if (!seenRecommendations.add(recommendationKey)) {
                            throw new IllegalArgumentException(
                                    "duplicate recommendation_reason across papers");
                        }
                        putCache(cacheKey(originalQuery, paper.paperId(),
                                properties.getDeepseekPromptVersion()), validated);
                        outcomes.put(paper.paperId(), new Outcome("success", validated,
                                0, 0, 0, attempt - 1, false, modelName));
                    } catch (Exception exception) {
                        log.warn("DeepSeek batch trace degraded paper={} cause={}", paper.paperId(),
                                exception.getClass().getSimpleName());
                        outcomes.put(paper.paperId(), new Outcome("degraded", null,
                                0, 0, 0, attempt - 1, false, modelName));
                    }
                }
                long latency = Duration.between(started, Instant.now()).toMillis();
                log.info("DeepSeek evidence batch papers={} model={} input_tokens={} output_tokens={} latency_ms={} retries={}",
                        papers.size(), modelName, inputTokens, outputTokens, latency, attempt - 1);
                return new BatchAnalysis(outcomes, attempt, inputTokens, outputTokens, modelName);
            } catch (Exception exception) {
                if (exception instanceof InterruptedException) {
                    Thread.currentThread().interrupt();
                }
                if (attempt == maxAttempts) {
                    log.warn("DeepSeek evidence batch degraded papers={} retries={} cause={}",
                            papers.size(), attempt - 1, exception.getClass().getSimpleName());
                    Map<String, Outcome> degraded = new LinkedHashMap<>();
                    for (ApiModels.PaperItem paper : papers) {
                        degraded.put(paper.paperId(), new Outcome("degraded", null,
                                0, 0, 0, attempt - 1, false, modelName));
                    }
                    return new BatchAnalysis(degraded, attempt, inputTokens, outputTokens, modelName);
                }
            }
        }
        throw new IllegalStateException("unreachable DeepSeek batch state");
    }

    private String buildUserPrompt(
            String originalQuery,
            List<ApiModels.QueryConstraint> constraints,
            ApiModels.PaperItem paper
    ) {
        try {
            List<Map<String, Object>> constraintPayload = constraints.stream().map(constraint -> {
                Map<String, Object> value = new LinkedHashMap<>();
                value.put("constraint_id", constraint.constraintId());
                value.put("type", constraint.type());
                value.put("description", constraint.description());
                value.put("importance", constraint.importance());
                value.put("original_text", constraint.originalText());
                return value;
            }).toList();
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("publication_year", paper.publicationYear());
            metadata.put("publication_date", paper.publicationDate());
            metadata.put("authors", safe(paper.authors()));
            metadata.put("venue", paper.venue());
            metadata.put("cited_by_count", paper.citedByCount());
            metadata.put("doi", paper.doi());
            Map<String, Object> selector = new LinkedHashMap<>();
            selector.put("decision", paper.selected() ? "selected" : "dropped");
            selector.put("score", paper.selectorScore() == null ? paper.score() : paper.selectorScore());
            selector.put("reason", paper.selectorReason());
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("original_query", originalQuery);
            payload.put("constraints", constraintPayload);
            payload.put("paper_id", paper.paperId());
            payload.put("title", text(paper.title()));
            payload.put("abstract", text(paper.abstractText()));
            payload.put("metadata", metadata);
            payload.put("selector", selector);
            // Phase 1/2 deliberately send no full text or citation graph.
            payload.put("fulltext_excerpts", List.of());
            payload.put("citations", List.of());
            return "Audit the following input and return JSON matching the example schema:\n"
                    + objectMapper.writeValueAsString(payload);
        } catch (Exception exception) {
            throw new IllegalStateException("Cannot serialize DeepSeek evidence prompt", exception);
        }
    }

    private String buildBatchUserPrompt(
            String originalQuery,
            List<ApiModels.QueryConstraint> constraints,
            List<ApiModels.PaperItem> papers
    ) {
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("original_query", originalQuery);
            payload.put("constraints", constraintPayload(constraints));
            payload.put("papers", papers.stream().map(this::paperPayload).toList());
            return "Audit every paper independently. Return one compact JSON object exactly in the form "
                    + "{\"analyses\":[{\"paper_id\":\"input paper_id\",\"trace\":{"
                    + "\"recommendation_reason\":\"2 concise paper-specific Chinese sentences\","
                    + "\"relevance_level\":\"high|partial|low\",\"constraint_results\":[],\"evidence\":[]}}]}。"
                    + "Return exactly one analyses entry per input paper and never mix evidence between papers. "
                    + "Every recommendation_reason must describe that paper's own task, concrete method or "
                    + "finding, and its specific value for the query in natural Simplified Chinese; do not reuse "
                    + "sentence templates across papers. Keep it to 70-140 Chinese characters, each constraint "
                    + "explanation to one sentence, and at most 3 strongest evidence quotes per paper. Omit the "
                    + "four derived *_constraints arrays. Do not output Markdown or any text outside JSON.\n"
                    + objectMapper.writeValueAsString(payload);
        } catch (Exception exception) {
            throw new IllegalStateException("Cannot serialize DeepSeek batch prompt", exception);
        }
    }

    private String buildCompactRetryPrompt(
            String originalQuery,
            List<ApiModels.QueryConstraint> constraints,
            List<ApiModels.PaperItem> papers
    ) {
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("original_query", originalQuery);
            payload.put("constraints", constraintPayload(constraints));
            payload.put("papers", papers.stream().map(this::paperPayload).toList());
            return "The previous response was not complete JSON. Return JSON only, with no Markdown. "
                    + "Use this minimal schema: {\"analyses\":[{\"paper_id\":\"\",\"trace\":{"
                    + "\"recommendation_reason\":\"70-140 Chinese characters specific to this paper\","
                    + "\"relevance_level\":\"high|partial|low\",\"constraint_results\":[{"
                    + "\"constraint_id\":\"\",\"status\":\"satisfied|partially_satisfied|violated|unknown\","
                    + "\"explanation\":\"one Chinese sentence\",\"evidence_ids\":[],\"confidence\":0.0}],"
                    + "\"evidence\":[{\"evidence_id\":\"\",\"source_type\":\"title|abstract|metadata\","
                    + "\"exact_text\":\"exact quote\",\"supports_constraints\":[],\"confidence\":0.0}]}}]}. "
                    + "Return every input paper once, at most 3 evidence items per paper, and omit all other "
                    + "fields. Every recommendation must name the paper's concrete method, design or finding "
                    + "and explain its value for the query. INPUT:\n"
                    + objectMapper.writeValueAsString(payload);
        } catch (Exception exception) {
            throw new IllegalStateException("Cannot serialize compact DeepSeek retry prompt", exception);
        }
    }

    private List<Map<String, Object>> constraintPayload(List<ApiModels.QueryConstraint> constraints) {
        return constraints.stream().map(constraint -> {
            Map<String, Object> value = new LinkedHashMap<>();
            value.put("constraint_id", constraint.constraintId());
            value.put("type", constraint.type());
            value.put("description", constraint.description());
            value.put("importance", constraint.importance());
            value.put("original_text", constraint.originalText());
            return value;
        }).toList();
    }

    private Map<String, Object> paperPayload(ApiModels.PaperItem paper) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("publication_year", paper.publicationYear());
        metadata.put("publication_date", paper.publicationDate());
        metadata.put("authors", safe(paper.authors()));
        metadata.put("venue", paper.venue());
        metadata.put("cited_by_count", paper.citedByCount());
        metadata.put("doi", paper.doi());
        Map<String, Object> selector = new LinkedHashMap<>();
        selector.put("decision", paper.selected() ? "selected" : "dropped");
        selector.put("score", paper.selectorScore() == null ? paper.score() : paper.selectorScore());
        selector.put("reason", paper.selectorReason());
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("paper_id", paper.paperId());
        value.put("title", text(paper.title()));
        value.put("abstract", compactAbstract(paper.abstractText()));
        value.put("metadata", metadata);
        value.put("selector", selector);
        value.put("fulltext_excerpts", List.of());
        value.put("citations", List.of());
        return value;
    }

    ApiModels.DeepSeekTrace validate(
            ApiModels.DeepSeekTrace raw,
            List<ApiModels.QueryConstraint> constraints,
            ApiModels.PaperItem paper
    ) {
        if (raw == null) {
            throw new IllegalArgumentException("DeepSeek trace is null");
        }
        if (text(raw.recommendationReason()).isBlank()
                || !RELEVANCE.contains(raw.relevanceLevel())
                || raw.constraintResults() == null || raw.evidence() == null) {
            throw new IllegalArgumentException("DeepSeek trace does not conform to evidence-v1 schema");
        }
        Set<String> allowedConstraints = constraints.stream()
                .map(ApiModels.QueryConstraint::constraintId)
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));

        List<ApiModels.DeepSeekEvidence> evidence = new ArrayList<>();
        Set<String> seenEvidence = new HashSet<>();
        for (ApiModels.DeepSeekEvidence item : safe(raw.evidence())) {
            if (validEvidence(item, paper, allowedConstraints) && seenEvidence.add(item.evidenceId())) {
                List<String> supports = safe(item.supportsConstraints()).stream()
                        .filter(allowedConstraints::contains).distinct().toList();
                evidence.add(new ApiModels.DeepSeekEvidence(item.evidenceId(), item.sourceType(),
                        item.exactText(), normalizedLocation(item), supports, clamp(item.confidence())));
            }
        }
        Set<String> validEvidenceIds = evidence.stream().map(ApiModels.DeepSeekEvidence::evidenceId)
                .collect(java.util.stream.Collectors.toSet());

        Map<String, ApiModels.DeepSeekConstraintResult> byConstraint = new LinkedHashMap<>();
        for (ApiModels.DeepSeekConstraintResult result : safe(raw.constraintResults())) {
            if (result == null || text(result.constraintId()).isBlank() || !STATUSES.contains(result.status())
                    || result.explanation() == null || result.evidenceIds() == null) {
                throw new IllegalArgumentException("constraint_results violates evidence-v1 schema");
            }
            if (!allowedConstraints.contains(result.constraintId())
                    || byConstraint.containsKey(result.constraintId())) {
                continue;
            }
            String status = result.status();
            String explanation = text(result.explanation());
            List<String> ids = safe(result.evidenceIds()).stream()
                    .filter(validEvidenceIds::contains).distinct().toList();
            if (!"unknown".equals(status) && ids.isEmpty()) {
                status = "unknown";
                explanation = "未找到可验证的原文证据，无法确认该条件。";
            }
            if ("unknown".equals(status)) {
                ids = List.of();
            }
            if (!hasSubstantialChinese(explanation)) {
                explanation = "unknown".equals(status)
                        ? "现有标题与摘要证据不足，暂不判断该条件。"
                        : "该条件判断由下方可核验的论文原文证据支持。";
            }
            byConstraint.put(result.constraintId(), new ApiModels.DeepSeekConstraintResult(
                    result.constraintId(), status, explanation, ids, clamp(result.confidence())));
        }
        for (String constraintId : allowedConstraints) {
            byConstraint.putIfAbsent(constraintId, new ApiModels.DeepSeekConstraintResult(
                    constraintId, "unknown", "模型未返回可验证判断。", List.of(), 0));
        }
        List<ApiModels.DeepSeekConstraintResult> results = List.copyOf(byConstraint.values());
        String relevance = raw.relevanceLevel();
        // Unknown constraints remain available below as structured results, but repetitive absence
        // disclaimers add no value to the natural recommendation paragraph.
        String reason = usefulRecommendationReason(raw.recommendationReason(), paper);
        if (!isPersonalizedRecommendation(reason)) {
            throw new IllegalArgumentException("recommendation_reason is not personalized Chinese analysis");
        }
        return new ApiModels.DeepSeekTrace(
                reason,
                relevance,
                results,
                List.copyOf(evidence),
                idsByStatus(results, "satisfied"),
                idsByStatus(results, "partially_satisfied"),
                idsByStatus(results, "violated"),
                idsByStatus(results, "unknown")
        );
    }

    static String usefulRecommendationReason(String rawReason, ApiModels.PaperItem paper) {
        List<String> usefulSentences = new ArrayList<>();
        for (String rawSentence : text(rawReason).strip().split("(?<=[。！？.!?])")) {
            String sentence = STOCK_RECOMMENDATION_OPENING.matcher(rawSentence.strip())
                    .replaceFirst("").strip();
            if (sentence.isBlank()) continue;
            Matcher unhelpful = UNHELPFUL_REASON_CLAUSE.matcher(sentence);
            if (!unhelpful.find()) {
                usefulSentences.add(sentence);
                continue;
            }

            int cutoff = -1;
            Matcher transition = CONTRAST_TRANSITION.matcher(sentence.substring(0, unhelpful.start()));
            while (transition.find()) cutoff = transition.start();
            if (cutoff > 0) {
                String supportedPart = sentence.substring(0, cutoff)
                        .replaceFirst("[；;，,\\s]+$", "").strip();
                if (!supportedPart.isBlank()) {
                    usefulSentences.add(supportedPart.matches(".*[。！？.!?]$")
                            ? supportedPart : supportedPart + "。");
                }
            }
        }
        List<String> specificSentences = new ArrayList<>();
        for (String sentence : usefulSentences) {
            Matcher generic = GENERIC_RECOMMENDATION_CLAUSE.matcher(sentence);
            if (!generic.find()) {
                specificSentences.add(sentence);
                continue;
            }
            if (generic.start() > 0) {
                String supportedPart = sentence.substring(0, generic.start())
                        .replaceFirst("[；;，,。.!?！？\\s]+$", "").strip();
                if (!supportedPart.isBlank()) {
                    specificSentences.add(supportedPart + "。");
                }
            }
        }
        if (!specificSentences.isEmpty()) {
            String result = String.join("", specificSentences);
            if (hasSubstantialChinese(result)) {
                return result;
            }
        }
        return "";
    }

    private static boolean isPersonalizedRecommendation(String value) {
        String reason = text(value).strip();
        if (!hasSubstantialChinese(reason) || chineseCharacterCount(reason) < 18) return false;
        return !reason.contains("与本次检索主题的具体关联，见下方原文证据")
                && !reason.matches(".*该论文围绕《.*》所指向的研究任务展开.*")
                && !reason.matches(".*研究《.*》所涉及的核心问题.*")
                && !reason.contains("具体表述见原文证据")
                && !reason.contains("具体结论见原文证据")
                && !GENERIC_RECOMMENDATION_CLAUSE.matcher(reason).find()
                && !STOCK_RECOMMENDATION_OPENING.matcher(reason).find()
                && !Set.of("与检索主题相关。", "具有参考价值。", "值得关注。")
                .contains(reason);
    }

    private static String compactAbstract(String value) {
        String abstractText = text(value).strip();
        return abstractText.length() <= 1800 ? abstractText : abstractText.substring(0, 1800);
    }

    private static boolean hasSubstantialChinese(String value) {
        return chineseCharacterCount(value) >= 4;
    }

    private static int chineseCharacterCount(String value) {
        Matcher matcher = CHINESE_CHARACTER.matcher(text(value));
        int count = 0;
        while (matcher.find()) count++;
        return count;
    }

    private boolean validEvidence(
            ApiModels.DeepSeekEvidence evidence,
            ApiModels.PaperItem paper,
            Set<String> allowedConstraints
    ) {
        if (evidence == null || text(evidence.evidenceId()).isBlank()
                || !SOURCE_TYPES.contains(evidence.sourceType()) || text(evidence.exactText()).isBlank()) {
            return false;
        }
        if (safe(evidence.supportsConstraints()).stream().noneMatch(allowedConstraints::contains)) {
            return false;
        }
        String quote = evidence.exactText().strip();
        return switch (evidence.sourceType()) {
            case "title" -> text(paper.title()).contains(quote);
            case "abstract" -> text(paper.abstractText()).contains(quote);
            case "metadata" -> metadataValues(paper).stream()
                    .anyMatch(value -> value.equals(quote) || value.contains(quote));
            // Phase 1/2 never supplies full-text excerpts, so full-text evidence cannot validate.
            case "fulltext" -> false;
            default -> false;
        };
    }

    private static ApiModels.DeepSeekEvidenceLocation normalizedLocation(ApiModels.DeepSeekEvidence evidence) {
        ApiModels.DeepSeekEvidenceLocation location = evidence.location();
        if (location == null) {
            return new ApiModels.DeepSeekEvidenceLocation(evidence.sourceType(), null, null, null);
        }
        return new ApiModels.DeepSeekEvidenceLocation(
                text(location.field()).isBlank() ? evidence.sourceType() : location.field(),
                location.sentenceIndex(), location.section(), location.page());
    }

    private static List<String> idsByStatus(
            List<ApiModels.DeepSeekConstraintResult> results,
            String status
    ) {
        return results.stream().filter(result -> status.equals(result.status()))
                .map(ApiModels.DeepSeekConstraintResult::constraintId).toList();
    }

    private static List<String> metadataValues(ApiModels.PaperItem paper) {
        List<String> values = new ArrayList<>();
        if (paper.publicationYear() != null) values.add(Integer.toString(paper.publicationYear()));
        if (paper.publicationDate() != null) values.add(paper.publicationDate());
        if (paper.venue() != null) values.add(paper.venue());
        if (paper.doi() != null) values.add(paper.doi());
        values.addAll(safe(paper.authors()));
        return values;
    }

    private void putCache(String key, ApiModels.DeepSeekTrace value) {
        if (cache.size() >= properties.getDeepseekCacheMaxEntries()) {
            cache.keySet().stream().findFirst().ifPresent(cache::remove);
        }
        cache.put(key, value);
    }

    private static ApiModels.PaperItem withTrace(
            ApiModels.PaperItem paper,
            String status,
            ApiModels.DeepSeekTrace trace
    ) {
        return new ApiModels.PaperItem(
                paper.paperId(), paper.arxivId(), paper.openalexId(), paper.doi(), paper.title(),
                paper.abstractText(), paper.score(), paper.selected(), paper.depth(), paper.source(),
                paper.arxivUrl(), paper.url(), paper.publicationYear(), paper.publicationDate(),
                paper.venue(), paper.citedByCount(), safe(paper.authors()), safe(paper.retrievalProviders()),
                paper.abstractStatus(), paper.abstractSource(), paper.abstractSourceUrl(), paper.recommendationTrace(),
                paper.selectorScore() == null ? paper.score() : paper.selectorScore(), paper.selectorReason(),
                status, trace);
    }

    private static String cacheKey(String query, String paperId, String promptVersion) {
        try {
            String value = text(query) + "\n" + text(paperId) + "\n" + text(promptVersion);
            return java.util.HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
    }

    private static String loadPrompt(String promptVersion) {
        try {
            String version = text(promptVersion).matches("[A-Za-z0-9._-]+")
                    ? promptVersion : "evidence-v2";
            return new ClassPathResource("prompts/deepseek-" + version + ".txt")
                    .getContentAsString(StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot load DeepSeek evidence prompt", exception);
        }
    }

    private static double clamp(double value) {
        if (!Double.isFinite(value)) return 0;
        return Math.max(0, Math.min(1, value));
    }

    private static String text(String value) {
        return value == null ? "" : value;
    }

    private static <T> List<T> safe(List<T> value) {
        return value == null ? List.of() : value;
    }

    public record BatchResult(List<ApiModels.PaperItem> papers, ApiModels.DeepSeekUsageStats usage) {}

    private record BatchAnalysis(
            Map<String, Outcome> outcomes,
            long calls,
            long inputTokens,
            long outputTokens,
            String modelName
    ) {}

    private record Outcome(
            String status,
            ApiModels.DeepSeekTrace trace,
            long calls,
            long inputTokens,
            long outputTokens,
            int retries,
            boolean cacheHit,
            String modelName
    ) {
        private static Outcome degraded(String model, int retries) {
            return new Outcome("degraded", null, retries + 1L, 0, 0, retries, false, model);
        }
    }
}

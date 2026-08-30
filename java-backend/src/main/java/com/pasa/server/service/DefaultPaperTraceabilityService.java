package com.pasa.server.service;

import com.pasa.server.api.ApiModels;
import com.pasa.server.config.PasaProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

@Service
public class DefaultPaperTraceabilityService implements PaperTraceabilityService {
    private static final Logger log = LoggerFactory.getLogger(DefaultPaperTraceabilityService.class);
    private static final Pattern TOKEN = Pattern.compile("[A-Za-z][A-Za-z0-9+.#-]{2,}");
    private static final Pattern HAN_RUN = Pattern.compile("[\\p{IsHan}]{2,}");
    private static final Pattern NEGATIVE_CUE = Pattern.compile(
            "(?i)(排除|不包括|不包含|不能|不得|不要|避免|除外|exclude|excluding|without|must not|do not)");
    private static final Pattern STRICT_REQUIREMENT_CUE = Pattern.compile(
            "(?i)(必须|务必|限定|只能|要求|must|require|required|only)");
    private static final Set<String> STOP_WORDS = Set.of(
            "the", "and", "for", "with", "from", "that", "this", "using", "based", "into",
            "paper", "papers", "study", "studies", "method", "methods", "approach", "approaches",
            "find", "search", "recommend", "about", "research", "related", "recent", "their", "these",
            "must", "require", "required", "only", "prefer", "preferably", "compare", "comparison",
            "use", "uses", "used", "采用", "使用", "必须", "要求", "需要", "优先", "论文", "相关",
            "寻找", "检索", "推荐", "排除", "比较", "分析", "内容");
    private static final Set<String> METHOD_TERMS = Set.of(
            "attention", "clustering", "contrastive", "diffusion", "embedding", "encoder", "gan",
            "graph neural network", "lstm", "multimodal", "prompting", "rag", "reinforcement learning",
            "retrieval augmented generation", "transformer", "vision transformer");
    private static final Set<String> TASK_TERMS = Set.of(
            "classification", "detection", "diagnosis", "diagnostic", "generation", "information retrieval",
            "machine translation", "object detection", "question answering", "ranking", "recommendation",
            "segmentation", "summarization");
    private static final Set<String> DATASET_TERMS = Set.of(
            "cifar-10", "cifar-100", "coco", "glue", "imagenet", "mnist", "ms marco", "squad", "superglue",
            "wikitext");
    private static final List<QueryConcept> QUERY_CONCEPTS = List.of(
            new QueryConcept("大语言模型", List.of("large language model", "language models", "llm", "llms")),
            new QueryConcept("诊断", List.of("diagnosis", "diagnostic", "diagnose", "diagnosing")),
            new QueryConcept("症状", List.of("symptom", "symptoms")),
            new QueryConcept("疾病", List.of("disease", "diseases", "illness", "illnesses")),
            new QueryConcept("医疗", List.of("medical", "medicine", "healthcare", "clinical")),
            new QueryConcept("医学影像", List.of("medical image", "radiology", "radiological")),
            new QueryConcept("问答", List.of("question answering", "questions")),
            new QueryConcept("检索", List.of("retrieval", "retrieve", "search")),
            new QueryConcept("多模态", List.of("multimodal", "multi-modal")),
            new QueryConcept("数据集", List.of("dataset", "benchmark")));

    private final ScholarlyMetadataClient metadataClient;
    private final PasaProperties properties;
    private final QueryConstraintParser constraintParser;
    private final FullTextClient fullTextClient;
    private final Map<String, CacheEntry> cache = new ConcurrentHashMap<>();

    public DefaultPaperTraceabilityService(
            ScholarlyMetadataClient metadataClient,
            PasaProperties properties,
            QueryConstraintParser constraintParser,
            FullTextClient fullTextClient
    ) {
        this.metadataClient = metadataClient;
        this.properties = properties;
        this.constraintParser = constraintParser;
        this.fullTextClient = fullTextClient;
    }

    @Override
    public TraceablePapers enrich(String query, LocalDate endDate, List<ApiModels.PaperItem> papers) {
        return enrich(query, endDate, papers, constraintParser.parse(query, endDate));
    }

    @Override
    public TraceablePapers enrich(
            String query,
            LocalDate endDate,
            List<ApiModels.PaperItem> papers,
            List<ApiModels.QueryConstraint> plannedConstraints
    ) {
        if (!properties.isTraceabilityEnabled()) {
            return new TraceablePapers(papers.stream().map(DefaultPaperTraceabilityService::normalizeWithoutTrace).toList(),
                    List.of(), List.of(), false);
        }
        String cacheKey = cacheKey(query, endDate, papers);
        CacheEntry hit = cache.get(cacheKey);
        if (hit != null && hit.createdAt().plus(properties.getTraceCacheTtl()).isAfter(Instant.now())) {
            return hit.result();
        }

        List<ApiModels.QueryConstraint> constraints = plannedConstraints == null || plannedConstraints.isEmpty()
                ? constraintParser.parse(query, endDate)
                : List.copyOf(plannedConstraints);
        List<ApiModels.PaperItem> selectedTopN = papers.stream()
                .filter(ApiModels.PaperItem::selected)
                .limit(properties.getTraceTopN())
                .toList();
        Set<String> tracedPaperIds = selectedTopN.stream().map(ApiModels.PaperItem::paperId)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Map<String, ScholarlyMetadataClient.PaperMetadata> metadata = fetchMetadata(selectedTopN);

        List<ApiModels.PaperItem> resultPapers = papers.stream().map(paper -> {
            if (!tracedPaperIds.contains(paper.paperId())) {
                return normalizeWithoutTrace(paper);
            }
            return enrichSelectedPaper(paper, metadata.getOrDefault(
                    paper.paperId(), ScholarlyMetadataClient.PaperMetadata.empty()), constraints);
        }).toList();
        List<ApiModels.PaperRelation> relations = buildRelations(
                resultPapers.stream().filter(paper -> tracedPaperIds.contains(paper.paperId())).toList(),
                metadata, constraints);
        TraceablePapers result = new TraceablePapers(resultPapers, relations, constraints, true);
        putCache(cacheKey, result);
        return result;
    }

    @Override
    public ApiModels.RecommendationTrace enrichFullText(
            String query,
            LocalDate endDate,
            ApiModels.PaperItem paper
    ) {
        if (!properties.isTraceabilityEnabled() || paper.recommendationTrace() == null) {
            return paper.recommendationTrace();
        }
        return buildTrace(paper, constraintParser.parse(query, endDate), fullTextClient.load(paper));
    }

    private Map<String, ScholarlyMetadataClient.PaperMetadata> fetchMetadata(List<ApiModels.PaperItem> papers) {
        int limit = Math.min(Math.min(properties.getEnrichmentMaxPapers(), properties.getTraceTopN()), papers.size());
        if (!properties.isEnrichmentEnabled() || limit == 0) {
            return Map.of();
        }
        Map<String, ScholarlyMetadataClient.PaperMetadata> result = new HashMap<>();
        int concurrency = Math.min(properties.getEnrichmentConcurrency(), limit);
        try (var executor = Executors.newFixedThreadPool(concurrency,
                Thread.ofVirtual().name("pasa-trace-metadata-", 0).factory())) {
            Map<String, Future<ScholarlyMetadataClient.PaperMetadata>> futures = new LinkedHashMap<>();
            papers.stream().limit(limit).forEach(paper ->
                    futures.put(paper.paperId(), executor.submit(() -> metadataClient.lookup(paper))));
            futures.forEach((paperId, future) -> {
                try {
                    result.put(paperId, future.get());
                } catch (Exception exception) {
                    log.debug("Trace metadata lookup failed for {}: {}", paperId, exception.getMessage());
                    result.put(paperId, ScholarlyMetadataClient.PaperMetadata.empty());
                }
            });
        }
        return result;
    }

    private ApiModels.PaperItem enrichSelectedPaper(
            ApiModels.PaperItem paper,
            ScholarlyMetadataClient.PaperMetadata metadata,
            List<ApiModels.QueryConstraint> constraints
    ) {
        String abstractText = hasText(paper.abstractText()) ? clean(paper.abstractText()) : clean(metadata.abstractText());
        String abstractStatus = hasText(paper.abstractText()) ? "provided"
                : hasText(metadata.abstractText()) ? "enriched" : "unavailable";
        String abstractSource = hasText(paper.abstractText()) ? inferExistingAbstractSource(paper)
                : hasText(metadata.abstractText()) ? metadata.abstractSource() : "unavailable";
        String abstractSourceUrl = hasText(paper.abstractText()) ? textOr(paper.abstractSourceUrl(), paper.url())
                : metadata.abstractSourceUrl();
        String openAlexId = hasText(paper.openalexId()) ? paper.openalexId() : metadata.openAlexId();
        String arxivId = hasText(paper.arxivId()) ? paper.arxivId() : metadata.arxivId();
        String doi = hasText(paper.doi()) ? paper.doi() : metadata.doi();
        ApiModels.PaperItem hydrated = copy(paper, arxivId, openAlexId, doi, abstractText, abstractStatus,
                abstractSource, abstractSourceUrl, null);
        return copy(hydrated, hydrated.arxivId(), hydrated.openalexId(), hydrated.doi(),
                hydrated.abstractText(), hydrated.abstractStatus(),
                hydrated.abstractSource(), hydrated.abstractSourceUrl(), buildTrace(hydrated, constraints));
    }

    private ApiModels.RecommendationTrace buildTrace(
            ApiModels.PaperItem paper,
            List<ApiModels.QueryConstraint> constraints
    ) {
        return buildTrace(paper, constraints, List.of());
    }

    private ApiModels.RecommendationTrace buildTrace(
            ApiModels.PaperItem paper,
            List<ApiModels.QueryConstraint> constraints,
            List<FullTextClient.FullTextPassage> fullText
    ) {
        EvidenceCollector evidence = new EvidenceCollector(paper.paperId());
        List<ApiModels.ConstraintAssessment> assessments = constraints.stream()
                .map(constraint -> assess(constraint, paper, fullText, evidence))
                .toList();
        List<ApiModels.Evidence> collectedEvidence = evidence.values();
        List<ApiModels.RecommendationReason> reasons = assessments.stream()
                .filter(item -> !item.evidenceIds().isEmpty())
                .map(item -> new ApiModels.RecommendationReason(
                        recommendationReason(paper, item, collectedEvidence),
                        List.of(item.constraintId()), item.evidenceIds()))
                .toList();
        return new ApiModels.RecommendationTrace(
                reasons,
                byStatus(assessments, "satisfied"),
                byStatus(assessments, "partially_satisfied"),
                byStatus(assessments, "violated"),
                byStatus(assessments, "unknown"),
                collectedEvidence,
                retrievalSources(paper));
    }

    private ApiModels.ConstraintAssessment assess(
            ApiModels.QueryConstraint constraint,
            ApiModels.PaperItem paper,
            List<FullTextClient.FullTextPassage> fullText,
            EvidenceCollector evidence
    ) {
        if (constraint.text().startsWith("发表日期不晚于 ")) {
            return assessEndDate(constraint, paper, evidence);
        }
        List<QuerySignal> terms = querySignals(constraint.text());
        List<SignalMatch> matches = terms.stream()
                .map(term -> findMatch(paper, fullText, term))
                .filter(java.util.Objects::nonNull).toList();
        List<String> evidenceIds = new ArrayList<>();
        for (SignalMatch signalMatch : matches.stream().limit(5).toList()) {
            String term = signalMatch.matchedText();
            if (paper.title().toLowerCase(Locale.ROOT).contains(term.toLowerCase(Locale.ROOT))) {
                evidenceIds.add(evidence.add("title", paper.title(), "title", constraint.constraintId(), 1.0,
                        "model_result", paper.url()));
            } else if (contains(paper, term)) {
                Sentence sentence = abstractSentence(paper.abstractText(), term);
                if (sentence != null) {
                    evidenceIds.add(evidence.add("abstract", sentence.text(),
                            "abstract sentence " + sentence.number(), constraint.constraintId(), 0.92,
                            paper.abstractSource(), paper.abstractSourceUrl()));
                }
            } else {
                FullTextMatch match = fullTextMatch(fullText, term);
                if (match != null) {
                    evidenceIds.add(evidence.add("fulltext", match.sentence(),
                            "section: " + match.section(), constraint.constraintId(), 0.88,
                            "ar5iv", match.sourceUrl()));
                }
            }
        }

        if (constraint.type().equals("exclusion") || NEGATIVE_CUE.matcher(constraint.text()).find()) {
            if (!evidenceIds.isEmpty()) {
                return new ApiModels.ConstraintAssessment(constraint.constraintId(), "violated",
                        "标题或摘要中存在排除条件的直接文本证据。", List.copyOf(evidenceIds));
            }
            return unknown(constraint.constraintId(), "没有证据能够确认排除条件成立；缺少证据不能视为违反。"
            );
        }
        if (terms.isEmpty() || evidenceIds.isEmpty()) {
            List<String> candidateEvidence = addCandidateEvidence(paper, constraint.constraintId(), evidence);
            if (!candidateEvidence.isEmpty() && !STRICT_REQUIREMENT_CUE.matcher(constraint.text()).find()) {
                return new ApiModels.ConstraintAssessment(constraint.constraintId(), "partially_satisfied",
                        "标题与摘要提供了主题相关性依据，论文可作为该检索主题的候选；"
                                + "该判断基于当前已有内容，不依赖全文证据。",
                        candidateEvidence);
            }
            return new ApiModels.ConstraintAssessment(constraint.constraintId(), "unknown",
                    candidateEvidence.isEmpty()
                            ? "当前可用来源中没有足够证据，不能据此判定违反。"
                            : "已根据标题与摘要核验，但其中没有直接支持该项严格要求的表述，暂不作满足或违反判断。",
                    candidateEvidence);
        }
        if (matches.size() == terms.size()) {
            return new ApiModels.ConstraintAssessment(constraint.constraintId(), "satisfied",
                    "标题、摘要或全文覆盖了该约束的全部可检索要点："
                            + matchedLabels(matches) + "。", List.copyOf(evidenceIds));
        }
        return new ApiModels.ConstraintAssessment(constraint.constraintId(), "partially_satisfied",
                "已核验部分要点：" + matchedLabels(matches) + "；其余要点仍需人工核验。",
                List.copyOf(evidenceIds));
    }

    private ApiModels.ConstraintAssessment assessEndDate(
            ApiModels.QueryConstraint constraint,
            ApiModels.PaperItem paper,
            EvidenceCollector evidence
    ) {
        LocalDate endDate;
        try {
            endDate = LocalDate.parse(constraint.text().substring(constraint.text().lastIndexOf(' ') + 1));
        } catch (RuntimeException exception) {
            return unknown(constraint.constraintId(), "无法解析截止日期。"
            );
        }
        if (hasText(paper.publicationDate())) {
            try {
                LocalDate publicationDate = LocalDate.parse(paper.publicationDate());
                String evidenceId = evidence.add("metadata", paper.publicationDate(), "metadata.publication_date",
                        constraint.constraintId(), 1.0, "model_result", paper.url());
                return new ApiModels.ConstraintAssessment(constraint.constraintId(),
                        publicationDate.isAfter(endDate) ? "violated" : "satisfied",
                        publicationDate.isAfter(endDate) ? "发表日期晚于用户截止日期。" : "发表日期不晚于用户截止日期。",
                        List.of(evidenceId));
            } catch (RuntimeException ignored) {
                // A year-only check below is still evidence-backed, but cannot prove a same-year day constraint.
            }
        }
        if (paper.publicationYear() != null) {
            String evidenceId = evidence.add("metadata", Integer.toString(paper.publicationYear()),
                    "metadata.publication_year", constraint.constraintId(), 1.0, "model_result", paper.url());
            if (paper.publicationYear() > endDate.getYear()) {
                return new ApiModels.ConstraintAssessment(constraint.constraintId(), "violated",
                        "发表年份晚于用户截止年份。", List.of(evidenceId));
            }
            if (paper.publicationYear() < endDate.getYear()) {
                return new ApiModels.ConstraintAssessment(constraint.constraintId(), "satisfied",
                        "发表年份早于用户截止年份。", List.of(evidenceId));
            }
            return new ApiModels.ConstraintAssessment(constraint.constraintId(), "partially_satisfied",
                    "年份符合，但缺少月日，无法完全确认截止日。", List.of(evidenceId));
        }
        return unknown(constraint.constraintId(), "缺少可核验的发表日期或年份。"
        );
    }

    private List<ApiModels.PaperRelation> buildRelations(
            List<ApiModels.PaperItem> papers,
            Map<String, ScholarlyMetadataClient.PaperMetadata> metadata,
            List<ApiModels.QueryConstraint> constraints
    ) {
        Map<String, ApiModels.PaperItem> byOpenAlexId = papers.stream()
                .filter(paper -> hasText(paper.openalexId()))
                .collect(Collectors.toMap(paper -> normalizeOpenAlexId(paper.openalexId()), paper -> paper,
                        (left, right) -> left, LinkedHashMap::new));
        List<String> outputConstraintIds = constraints.stream().filter(item -> item.type().equals("output"))
                .map(ApiModels.QueryConstraint::constraintId).toList();
        Map<String, ApiModels.PaperRelation> relations = new LinkedHashMap<>();
        int relationIndex = 1;
        for (ApiModels.PaperItem citing : papers) {
            for (String referenceId : metadata.getOrDefault(citing.paperId(),
                    ScholarlyMetadataClient.PaperMetadata.empty()).referencedOpenAlexIds()) {
                ApiModels.PaperItem cited = byOpenAlexId.get(normalizeOpenAlexId(referenceId));
                if (cited == null || cited.paperId().equals(citing.paperId())) {
                    continue;
                }
                String relationId = "R" + relationIndex++;
                ApiModels.Evidence relationEvidence = new ApiModels.Evidence(
                        relationId + "-E1", "citation_database",
                        normalizeOpenAlexId(citing.openalexId()) + " referenced_works contains "
                                + normalizeOpenAlexId(referenceId),
                        "OpenAlex referenced_works", outputConstraintIds, 1.0, "openalex",
                        "https://openalex.org/" + normalizeOpenAlexId(citing.openalexId()));
                relations.put(relationId, new ApiModels.PaperRelation(
                        relationId, citing.paperId(), cited.paperId(), "confirmed", "cites",
                        "OpenAlex 确认前一篇论文引用后一篇论文。", List.of(relationEvidence.evidenceId()),
                        List.of(relationEvidence), 1.0));
            }
        }
        relationIndex = addInferredRelations(relations, relationIndex, papers, outputConstraintIds,
                "same_dataset", DATASET_TERMS, 0.63);
        relationIndex = addInferredRelations(relations, relationIndex, papers, outputConstraintIds,
                "same_task", TASK_TERMS, 0.55);
        addInferredRelations(relations, relationIndex, papers, outputConstraintIds,
                "same_method", METHOD_TERMS, 0.55);
        return List.copyOf(relations.values());
    }

    private int addInferredRelations(
            Map<String, ApiModels.PaperRelation> relations,
            int startIndex,
            List<ApiModels.PaperItem> papers,
            List<String> constraintIds,
            String type,
            Set<String> vocabulary,
            double relationPrior
    ) {
        int index = startIndex;
        for (int left = 0; left < papers.size(); left++) {
            for (int right = left + 1; right < papers.size(); right++) {
                ApiModels.PaperItem first = papers.get(left);
                ApiModels.PaperItem second = papers.get(right);
                if (hasRelationBetween(relations, first.paperId(), second.paperId())) {
                    continue;
                }
                Set<String> firstSignals = signals(first, vocabulary);
                Set<String> secondSignals = signals(second, vocabulary);
                Set<String> shared = new LinkedHashSet<>(firstSignals);
                shared.retainAll(secondSignals);
                if (shared.isEmpty()) {
                    continue;
                }
                String signal = shared.iterator().next();
                String relationId = "R" + index++;
                Sentence firstSentence = bestSentence(first, signal);
                Sentence secondSentence = bestSentence(second, signal);
                double confidence = inferredRelationConfidence(
                        first, second, firstSignals, secondSignals, shared,
                        firstSentence != null, secondSentence != null, relationPrior);
                ApiModels.Evidence firstEvidence = relationEvidence(relationId + "-E1", first,
                        firstSentence, signal, constraintIds, confidence);
                ApiModels.Evidence secondEvidence = relationEvidence(relationId + "-E2", second,
                        secondSentence, signal, constraintIds, confidence);
                relations.put(relationId, new ApiModels.PaperRelation(
                        relationId, first.paperId(), second.paperId(), "inferred", type,
                        "《" + first.title() + "》与《" + second.title()
                                + "》的标题或摘要都明确出现“" + signal + "”，据此推断该关系。",
                        List.of(firstEvidence.evidenceId(), secondEvidence.evidenceId()),
                        List.of(firstEvidence, secondEvidence), confidence));
            }
        }
        return index;
    }

    /**
     * Scores each inferred relation from its own support instead of assigning one constant value.
     * Exact dataset matches start with a stronger prior; shared-signal coverage, evidence in both
     * abstracts, and the two selector scores then contribute bounded, independently varying support.
     */
    private static double inferredRelationConfidence(
            ApiModels.PaperItem first,
            ApiModels.PaperItem second,
            Set<String> firstSignals,
            Set<String> secondSignals,
            Set<String> shared,
            boolean firstHasAbstractEvidence,
            boolean secondHasAbstractEvidence,
            double relationPrior
    ) {
        double coverage = (double) shared.size() / Math.max(firstSignals.size(), secondSignals.size());
        double breadth = Math.min(1.0, shared.size() / 3.0);
        double evidenceSupport = (double) ((firstHasAbstractEvidence ? 1 : 0)
                + (secondHasAbstractEvidence ? 1 : 0)) / 2.0;
        double firstScore = normalizedPaperScore(first);
        double secondScore = normalizedPaperScore(second);
        double pairRelevance = (firstScore + secondScore) / 2.0;
        double scoreAgreement = 1.0 - Math.abs(firstScore - secondScore);
        double textSimilarity = jaccardSimilarity(contentTokens(first), contentTokens(second));
        double titleSimilarity = jaccardSimilarity(tokens(first.title()), tokens(second.title()));
        double confidence = relationPrior
                + 0.10 * coverage
                + 0.05 * breadth
                + 0.03 * evidenceSupport
                + 0.08 * pairRelevance
                + 0.02 * scoreAgreement
                + 0.12 * textSimilarity
                + 0.05 * titleSimilarity;
        return Math.max(0.0, Math.min(0.99, confidence));
    }

    private static double normalizedPaperScore(ApiModels.PaperItem paper) {
        double score = paper.selectorScore() == null ? paper.score() : paper.selectorScore();
        return Math.max(0.0, Math.min(1.0, score));
    }

    private static Set<String> contentTokens(ApiModels.PaperItem paper) {
        return tokens(textOr(paper.title(), "") + " " + textOr(paper.abstractText(), ""));
    }

    private static double jaccardSimilarity(Set<String> first, Set<String> second) {
        if (first.isEmpty() || second.isEmpty()) return 0.0;
        Set<String> intersection = new LinkedHashSet<>(first);
        intersection.retainAll(second);
        Set<String> union = new LinkedHashSet<>(first);
        union.addAll(second);
        return (double) intersection.size() / union.size();
    }

    private static ApiModels.Evidence relationEvidence(
            String id,
            ApiModels.PaperItem paper,
            Sentence sentence,
            String signal,
            List<String> constraintIds,
            double confidence
    ) {
        if (sentence != null) {
            return new ApiModels.Evidence(id, "abstract", sentence.text(),
                    "abstract sentence " + sentence.number(), constraintIds, confidence,
                    paper.abstractSource(), paper.abstractSourceUrl());
        }
        return new ApiModels.Evidence(id, "title", paper.title(), "title", constraintIds,
                confidence, "model_result", paper.url());
    }

    private static Set<String> signals(ApiModels.PaperItem paper, Set<String> vocabulary) {
        String content = (textOr(paper.title(), "") + " " + textOr(paper.abstractText(), ""))
                .toLowerCase(Locale.ROOT);
        return vocabulary.stream().filter(content::contains)
                .sorted((left, right) -> Integer.compare(right.length(), left.length()))
                .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    private static boolean hasRelationBetween(
            Map<String, ApiModels.PaperRelation> relations,
            String firstPaperId,
            String secondPaperId
    ) {
        return relations.values().stream().anyMatch(relation ->
                relation.relationClass().equals("inferred") && (
                        relation.fromPaperId().equals(firstPaperId) && relation.toPaperId().equals(secondPaperId)
                                || relation.fromPaperId().equals(secondPaperId)
                                && relation.toPaperId().equals(firstPaperId)));
    }

    private static Sentence bestSentence(ApiModels.PaperItem paper, String signal) {
        if (!paper.title().toLowerCase(Locale.ROOT).contains(signal.toLowerCase(Locale.ROOT))) {
            return abstractSentence(paper.abstractText(), signal);
        }
        return null;
    }

    private void putCache(String key, TraceablePapers result) {
        if (cache.size() >= properties.getTraceCacheMaxEntries()) {
            cache.entrySet().stream().min((left, right) ->
                    left.getValue().createdAt().compareTo(right.getValue().createdAt()))
                    .ifPresent(oldest -> cache.remove(oldest.getKey(), oldest.getValue()));
        }
        cache.put(key, new CacheEntry(Instant.now(), result));
    }

    private static String cacheKey(String query, LocalDate endDate, List<ApiModels.PaperItem> papers) {
        StringBuilder value = new StringBuilder(textOr(query, "")).append('|').append(endDate).append('|');
        papers.forEach(paper -> value.append(paper.paperId()).append(':').append(paper.selected()).append(':')
                .append(paper.score()).append(':').append(paper.title()).append(':').append(paper.abstractText())
                .append(':').append(paper.publicationDate()).append(';'));
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.toString().getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (Exception exception) {
            return Integer.toHexString(value.toString().hashCode());
        }
    }

    private static ApiModels.PaperItem normalizeWithoutTrace(ApiModels.PaperItem paper) {
        boolean hasAbstract = hasText(paper.abstractText());
        return copy(paper, paper.arxivId(), paper.openalexId(), paper.doi(),
                hasAbstract ? clean(paper.abstractText()) : "",
                textOr(paper.abstractStatus(), hasAbstract ? "provided" : "unavailable"),
                textOr(paper.abstractSource(), hasAbstract ? inferExistingAbstractSource(paper) : "unavailable"),
                textOr(paper.abstractSourceUrl(), hasAbstract ? paper.url() : null), null);
    }

    private static ApiModels.PaperItem copy(
            ApiModels.PaperItem paper,
            String arxivId,
            String openAlexId,
            String doi,
            String abstractText,
            String abstractStatus,
            String abstractSource,
            String abstractSourceUrl,
            ApiModels.RecommendationTrace trace
    ) {
        return new ApiModels.PaperItem(
                paper.paperId(), textOr(arxivId, ""), openAlexId, doi, textOr(paper.title(), ""),
                textOr(abstractText, ""), paper.score(), paper.selected(), paper.depth(), textOr(paper.source(), ""),
                paper.arxivUrl(), paper.url(), paper.publicationYear(), paper.publicationDate(), paper.venue(),
                paper.citedByCount(), safeList(paper.authors()), safeList(paper.retrievalProviders()),
                abstractStatus, abstractSource, abstractSourceUrl, trace,
                paper.selectorScore() == null ? paper.score() : paper.selectorScore(), paper.selectorReason(),
                paper.traceStatus() == null ? "disabled" : paper.traceStatus(), paper.deepseekTrace());
    }

    private static Set<String> tokens(String value) {
        Set<String> result = new LinkedHashSet<>();
        Matcher matcher = TOKEN.matcher(value.toLowerCase(Locale.ROOT));
        while (matcher.find()) {
            String token = matcher.group();
            if (!STOP_WORDS.contains(token) && !NEGATIVE_CUE.matcher(token).matches()
                    && !token.matches("\\d{4}-\\d{2}-\\d{2}")) {
                result.add(token);
            }
        }
        Matcher hanMatcher = HAN_RUN.matcher(value);
        while (hanMatcher.find()) {
            String run = hanMatcher.group();
            for (String stopWord : STOP_WORDS) {
                if (stopWord.matches("[\\p{IsHan}]+")) {
                    run = run.replace(stopWord, " ");
                }
            }
            for (String fragment : run.split("\\s+")) {
                for (int size : List.of(4, 3, 2)) {
                    for (int start = 0; start + size <= fragment.length(); start++) {
                        result.add(fragment.substring(start, start + size));
                    }
                }
            }
        }
        return result;
    }

    private static boolean contains(ApiModels.PaperItem paper, String term) {
        String lower = term.toLowerCase(Locale.ROOT);
        return textOr(paper.title(), "").toLowerCase(Locale.ROOT).contains(lower)
                || textOr(paper.abstractText(), "").toLowerCase(Locale.ROOT).contains(lower);
    }

    private static boolean fullTextContains(List<FullTextClient.FullTextPassage> passages, String term) {
        return fullTextMatch(passages, term) != null;
    }

    private static List<QuerySignal> querySignals(String value) {
        String lower = textOr(value, "").toLowerCase(Locale.ROOT);
        Map<String, QuerySignal> result = new LinkedHashMap<>();
        for (QueryConcept concept : QUERY_CONCEPTS) {
            boolean requested = lower.contains(concept.label())
                    || concept.aliases().stream().anyMatch(lower::contains);
            if (requested) {
                result.put(concept.label(), new QuerySignal(concept.label(), concept.aliases()));
            }
        }
        for (String token : tokens(value)) {
            if (token.chars().noneMatch(character -> Character.UnicodeScript.of(character)
                    == Character.UnicodeScript.HAN)) {
                result.putIfAbsent(token, new QuerySignal(token, List.of(token)));
            }
        }
        return List.copyOf(result.values());
    }

    private static SignalMatch findMatch(
            ApiModels.PaperItem paper,
            List<FullTextClient.FullTextPassage> fullText,
            QuerySignal signal
    ) {
        for (String alias : signal.aliases().stream()
                .sorted((left, right) -> Integer.compare(right.length(), left.length())).toList()) {
            if (contains(paper, alias) || fullTextContains(fullText, alias)) {
                return new SignalMatch(signal.label(), alias);
            }
        }
        return null;
    }

    private static List<String> addCandidateEvidence(
            ApiModels.PaperItem paper,
            String constraintId,
            EvidenceCollector evidence
    ) {
        List<String> ids = new ArrayList<>();
        if (hasText(paper.title())) {
            ids.add(evidence.add("title", paper.title(), "title", constraintId, 1.0,
                    "model_result", paper.url()));
        }
        if (hasText(paper.abstractText())) {
            String firstSentence = clean(paper.abstractText()).split("(?<=[.!?。！？])\\s+", 2)[0];
            ids.add(evidence.add("abstract", firstSentence, "abstract sentence 1", constraintId, 0.75,
                    paper.abstractSource(), paper.abstractSourceUrl()));
        }
        return List.copyOf(ids);
    }

    private static String matchedLabels(List<SignalMatch> matches) {
        return matches.stream().map(SignalMatch::label).distinct().collect(Collectors.joining("、"));
    }

    private static String recommendationReason(
            ApiModels.PaperItem paper,
            ApiModels.ConstraintAssessment assessment,
            List<ApiModels.Evidence> evidence
    ) {
        ApiModels.Evidence supportingEvidence = evidence.stream()
                .filter(item -> assessment.evidenceIds().contains(item.evidenceId()))
                .findFirst().orElse(null);
        Set<String> sourceTypes = evidence.stream()
                .filter(item -> assessment.evidenceIds().contains(item.evidenceId()))
                .map(ApiModels.Evidence::sourceType)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        List<String> sourceLabels = new ArrayList<>();
        if (sourceTypes.contains("title")) sourceLabels.add("标题");
        if (sourceTypes.contains("abstract")) sourceLabels.add("摘要");
        if (sourceTypes.contains("fulltext")) sourceLabels.add("全文");
        if (sourceTypes.contains("metadata") || sourceTypes.contains("citation_database")) {
            sourceLabels.add("元数据");
        }
        String sourceDescription = sourceLabels.isEmpty()
                ? "当前可用"
                : String.join("与", sourceLabels);
        String quote = supportingEvidence == null ? ""
                : clean(supportingEvidence.exactText());
        if (quote.length() > 100) {
            quote = quote.substring(0, 100) + "…";
        }
        return "《" + paper.title() + "》的" + sourceDescription + "证据"
                + (quote.isBlank() ? "" : "“" + quote + "”")
                + "支持以下判断，" + assessment.constraintId() + "：" + assessment.explanation();
    }

    private static FullTextMatch fullTextMatch(List<FullTextClient.FullTextPassage> passages, String term) {
        for (FullTextClient.FullTextPassage passage : passages) {
            Sentence sentence = abstractSentence(passage.exactText(), term);
            if (sentence != null) {
                return new FullTextMatch(passage.section(), sentence.text(), passage.sourceUrl());
            }
        }
        return null;
    }

    private static Sentence abstractSentence(String abstractText, String term) {
        if (!hasText(abstractText)) {
            return null;
        }
        String[] sentences = clean(abstractText).split("(?<=[.!?。！？])\\s+");
        for (int index = 0; index < sentences.length; index++) {
            if (sentences[index].toLowerCase(Locale.ROOT).contains(term.toLowerCase(Locale.ROOT))) {
                return new Sentence(index + 1, sentences[index].strip());
            }
        }
        return null;
    }

    private static List<ApiModels.ConstraintAssessment> byStatus(
            List<ApiModels.ConstraintAssessment> assessments,
            String status
    ) {
        return assessments.stream().filter(item -> item.status().equals(status)).toList();
    }

    private static ApiModels.ConstraintAssessment unknown(String constraintId, String explanation) {
        return new ApiModels.ConstraintAssessment(constraintId, "unknown", explanation, List.of());
    }

    private static List<String> retrievalSources(ApiModels.PaperItem paper) {
        Set<String> sources = new LinkedHashSet<>(safeList(paper.retrievalProviders()));
        if (hasText(paper.abstractSource()) && !paper.abstractSource().equals("unavailable")) {
            sources.add(paper.abstractSource());
        }
        if (hasText(paper.source())) {
            sources.add(paper.source());
        }
        return List.copyOf(sources);
    }

    private static String inferExistingAbstractSource(ApiModels.PaperItem paper) {
        if (hasText(paper.abstractSource())) {
            return paper.abstractSource();
        }
        if (safeList(paper.retrievalProviders()).contains("openalex")) {
            return "openalex";
        }
        return hasText(paper.arxivId()) ? "arxiv" : "model_result";
    }

    private static String normalizeOpenAlexId(String value) {
        if (!hasText(value)) {
            return "";
        }
        String normalized = value.strip();
        int slash = normalized.lastIndexOf('/');
        return (slash >= 0 ? normalized.substring(slash + 1) : normalized).toUpperCase(Locale.ROOT);
    }

    private static String clean(String value) {
        return value == null ? null : value.replaceAll("\\s+", " ").strip();
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private static String textOr(String value, String fallback) {
        return hasText(value) ? value : fallback;
    }

    private static <T> List<T> safeList(List<T> value) {
        return value == null ? List.of() : List.copyOf(value);
    }

    private record Sentence(int number, String text) {}
    private record FullTextMatch(String section, String sentence, String sourceUrl) {}
    private record QueryConcept(String label, List<String> aliases) {}
    private record QuerySignal(String label, List<String> aliases) {}
    private record SignalMatch(String label, String matchedText) {}
    private record CacheEntry(Instant createdAt, TraceablePapers result) {}

    private static final class EvidenceCollector {
        private final String prefix;
        private final List<ApiModels.Evidence> evidence = new ArrayList<>();
        private final Map<String, Integer> indexes = new LinkedHashMap<>();

        private EvidenceCollector(String paperId) {
            this.prefix = "E-" + paperId.replaceAll("[^A-Za-z0-9]+", "-") + "-";
        }

        private String add(
                String sourceType,
                String exactText,
                String location,
                String constraintId,
                double confidence,
                String source,
                String sourceUrl
        ) {
            String key = sourceType + '\u0000' + location + '\u0000' + exactText;
            Integer existingIndex = indexes.get(key);
            if (existingIndex != null) {
                ApiModels.Evidence existing = evidence.get(existingIndex);
                if (!existing.constraintIds().contains(constraintId)) {
                    List<String> constraintIds = new ArrayList<>(existing.constraintIds());
                    constraintIds.add(constraintId);
                    evidence.set(existingIndex, new ApiModels.Evidence(existing.evidenceId(),
                            existing.sourceType(), existing.exactText(), existing.location(),
                            List.copyOf(constraintIds), Math.max(existing.confidence(), confidence),
                            existing.source(), existing.sourceUrl()));
                }
                return existing.evidenceId();
            }
            String id = prefix + (evidence.size() + 1);
            evidence.add(new ApiModels.Evidence(id, sourceType, exactText, location,
                    List.of(constraintId), confidence, textOr(source, "model_result"), sourceUrl));
            indexes.put(key, evidence.size() - 1);
            return id;
        }

        private List<ApiModels.Evidence> values() {
            return List.copyOf(evidence);
        }
    }
}

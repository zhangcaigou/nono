package com.pasa.server.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.pasa.server.api.ApiModels;
import com.pasa.server.config.PasaProperties;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class DefaultPaperTraceabilityServiceTest {
    @Test
    void parsesNumberedConstraintsAndBuildsEvidenceBackedTrace() {
        PasaProperties properties = new PasaProperties();
        ScholarlyMetadataClient metadata = paper -> new ScholarlyMetadataClient.PaperMetadata(
                "We propose a transformer retrieval framework for grounded question answering.",
                "semantic_scholar", "https://example.test/evidence", "W1", List.of());
        DefaultPaperTraceabilityService service = service(metadata, properties);

        PaperTraceabilityService.TraceablePapers result = service.enrich(
                "find retrieval papers; must use transformer; prefer question answering",
                LocalDate.of(2025, 12, 31),
                List.of(paper("openalex:W1", "W1", "", 2024, true,
                        "Transformer Retrieval for QA")));

        ApiModels.PaperItem paper = result.papers().getFirst();
        assertThat(result.constraints()).extracting(ApiModels.QueryConstraint::constraintId)
                .containsExactly("C1", "C2", "C3", "C4");
        assertThat(result.constraints()).extracting(ApiModels.QueryConstraint::type)
                .containsExactly("hard", "hard", "soft", "hard");
        assertThat(paper.abstractText()).contains("transformer retrieval");
        assertThat(paper.recommendationTrace().satisfiedConstraints()).isNotEmpty();
        assertThat(paper.recommendationTrace().evidence())
                .allMatch(item -> item.evidenceId().startsWith("E-")
                        && item.exactText() != null && !item.exactText().isBlank()
                        && item.confidence() > 0 && !item.constraintIds().isEmpty());
        assertThat(paper.recommendationTrace().reasons())
                .allMatch(reason -> !reason.constraintIds().isEmpty() && !reason.evidenceIds().isEmpty());
    }

    @Test
    void usesOnlyFourStatusesAndTreatsMissingExclusionEvidenceAsUnknown() {
        PasaProperties properties = new PasaProperties();
        properties.setEnrichmentEnabled(false);
        DefaultPaperTraceabilityService service = service(
                paper -> ScholarlyMetadataClient.PaperMetadata.empty(), properties);

        PaperTraceabilityService.TraceablePapers result = service.enrich(
                "must use transformer and multimodal retrieval; exclude proprietary datasets", null,
                List.of(paper("openalex:W1", "W1", "A transformer retrieval framework.",
                        2024, true, "Transformer Retrieval")));

        ApiModels.RecommendationTrace trace = result.papers().getFirst().recommendationTrace();
        assertThat(trace.partiallySatisfiedConstraints()).isNotEmpty();
        assertThat(trace.unknownConstraints()).extracting(ApiModels.ConstraintAssessment::constraintId)
                .contains("C2");
        assertThat(trace.violatedConstraints()).isEmpty();
    }

    @Test
    void tracesOnlySelectedTopNWithoutChangingOrderOrSelection() {
        PasaProperties properties = new PasaProperties();
        properties.setTraceTopN(1);
        properties.setEnrichmentEnabled(false);
        DefaultPaperTraceabilityService service = service(
                paper -> ScholarlyMetadataClient.PaperMetadata.empty(), properties);
        List<ApiModels.PaperItem> input = List.of(
                paper("openalex:W1", "W1", "Transformer retrieval.", 2024, true, "First"),
                paper("openalex:W2", "W2", "Transformer retrieval.", 2024, true, "Second"),
                paper("openalex:W3", "W3", "Transformer retrieval.", 2024, false, "Third"));

        List<ApiModels.PaperItem> output = service.enrich("transformer retrieval", null, input).papers();

        assertThat(output).extracting(ApiModels.PaperItem::paperId)
                .containsExactly("openalex:W1", "openalex:W2", "openalex:W3");
        assertThat(output).extracting(ApiModels.PaperItem::selected)
                .containsExactly(true, true, false);
        assertThat(output.get(0).recommendationTrace()).isNotNull();
        assertThat(output.get(1).recommendationTrace()).isNull();
        assertThat(output.get(2).recommendationTrace()).isNull();
    }

    @Test
    void buildsConfirmedCitationAndEvidenceBackedInferredRelations() {
        PasaProperties properties = new PasaProperties();
        ScholarlyMetadataClient metadata = paper -> paper.paperId().equals("openalex:W2")
                ? new ScholarlyMetadataClient.PaperMetadata(null, null, null, "W2", List.of("W1"))
                : new ScholarlyMetadataClient.PaperMetadata(null, null, null, "W1", List.of());
        DefaultPaperTraceabilityService service = service(metadata, properties);
        List<ApiModels.PaperItem> papers = List.of(
                paper("openalex:W1", "W1", "Transformer retrieval architecture.", 2024, true, "First"),
                paper("openalex:W2", "W2", "A transformer retrieval model.", 2024, true, "Second"));

        List<ApiModels.PaperRelation> relations = service.enrich(
                "compare transformer retrieval methods", null, papers).relations();

        assertThat(relations).anyMatch(relation -> relation.relationClass().equals("confirmed")
                && relation.type().equals("cites") && relation.confidence() == 1.0);
        assertThat(relations).anyMatch(relation -> relation.relationClass().equals("inferred")
                && relation.type().equals("same_method") && relation.evidence().size() == 2
                && !relation.evidenceIds().isEmpty());
    }

    @Test
    void computesRelationSpecificConfidenceInsteadOfUsingOneFixedPercentage() {
        PasaProperties properties = new PasaProperties();
        properties.setEnrichmentEnabled(false);
        DefaultPaperTraceabilityService service = service(
                paper -> ScholarlyMetadataClient.PaperMetadata.empty(), properties);
        List<ApiModels.PaperItem> papers = List.of(
                paperWithScore("local:1", "Transformer and attention for classification.",
                        "First", 0.95),
                paperWithScore("local:2", "Transformer classification.",
                        "Second", 0.82),
                paperWithScore("local:3", "Transformer generation.",
                        "Third", 0.61));

        List<Double> confidences = service.enrich("transformer research", null, papers).relations().stream()
                .filter(relation -> relation.type().equals("same_method"))
                .map(ApiModels.PaperRelation::confidence)
                .distinct()
                .toList();

        assertThat(confidences).hasSizeGreaterThan(1).allMatch(value -> value > 0.0 && value < 1.0);
    }

    @Test
    void cachesTraceResults() {
        PasaProperties properties = new PasaProperties();
        AtomicInteger calls = new AtomicInteger();
        DefaultPaperTraceabilityService service = service(paper -> {
            calls.incrementAndGet();
            return ScholarlyMetadataClient.PaperMetadata.empty();
        }, properties);
        List<ApiModels.PaperItem> papers = List.of(
                paper("openalex:W1", "W1", "Transformer retrieval.", 2024, true, "First"));

        service.enrich("transformer retrieval", null, papers);
        service.enrich("transformer retrieval", null, papers);

        assertThat(calls).hasValue(1);
    }

    @Test
    void featureFlagBypassesTraceAndExternalMetadata() {
        PasaProperties properties = new PasaProperties();
        properties.setTraceabilityEnabled(false);
        AtomicInteger calls = new AtomicInteger();
        DefaultPaperTraceabilityService service = service(paper -> {
            calls.incrementAndGet();
            return ScholarlyMetadataClient.PaperMetadata.empty();
        }, properties);

        PaperTraceabilityService.TraceablePapers result = service.enrich(
                "must use transformer", null,
                List.of(paper("openalex:W1", "W1", "Transformer retrieval.", 2024, true, "First")));

        assertThat(result.enabled()).isFalse();
        assertThat(result.constraints()).isEmpty();
        assertThat(result.papers().getFirst().recommendationTrace()).isNull();
        assertThat(calls).hasValue(0);
    }

    @Test
    void canLoadFullTextOnlyOnExplicitRequest() {
        PasaProperties properties = new PasaProperties();
        FullTextClient fullText = paper -> List.of(new FullTextClient.FullTextPassage(
                "Experiments", "We evaluate on the SQuAD benchmark.", "https://example.test/fulltext"));
        DefaultPaperTraceabilityService service = new DefaultPaperTraceabilityService(
                paper -> ScholarlyMetadataClient.PaperMetadata.empty(), properties,
                new QueryConstraintParser(), fullText);
        ApiModels.PaperItem initial = service.enrich("must use SQuAD", null,
                List.of(paper("openalex:W1", "W1", "", 2024, true, "QA Paper")))
                .papers().getFirst();

        assertThat(initial.recommendationTrace().unknownConstraints()).isNotEmpty();
        ApiModels.RecommendationTrace expanded = service.enrichFullText("must use SQuAD", null, initial);
        assertThat(expanded.satisfiedConstraints()).isNotEmpty();
        assertThat(expanded.evidence()).anyMatch(item -> item.sourceType().equals("fulltext")
                && item.location().equals("section: Experiments"));
    }

    @Test
    void mapsChineseConstraintsToEnglishEvidenceInsteadOfReturningAnEmptyUnknownPanel() {
        PasaProperties properties = new PasaProperties();
        properties.setEnrichmentEnabled(false);
        DefaultPaperTraceabilityService service = service(
                paper -> ScholarlyMetadataClient.PaperMetadata.empty(), properties);

        ApiModels.PaperItem traced = service.enrich(
                "寻找使用大语言模型根据症状进行疾病诊断的论文", null,
                List.of(paper("local:1", null,
                        "We evaluate large language models for interpreting symptoms and diagnostic decisions.",
                        2024, true, "Digital Diagnostics with Large Language Models")))
                .papers().getFirst();

        assertThat(traced.recommendationTrace().reasons()).isNotEmpty();
        assertThat(traced.recommendationTrace().evidence())
                .anyMatch(item -> item.sourceType().equals("abstract")
                        && item.exactText().contains("symptoms"));
        assertThat(traced.recommendationTrace().partiallySatisfiedConstraints()).isNotEmpty();
    }

    @Test
    void usesTitleAndAbstractForTopicalRecommendationWithoutRequestingFullText() {
        PasaProperties properties = new PasaProperties();
        properties.setEnrichmentEnabled(false);
        AtomicInteger fullTextCalls = new AtomicInteger();
        DefaultPaperTraceabilityService service = new DefaultPaperTraceabilityService(
                paper -> ScholarlyMetadataClient.PaperMetadata.empty(), properties,
                new QueryConstraintParser(), paper -> {
                    fullTextCalls.incrementAndGet();
                    return List.of();
                });

        ApiModels.PaperItem traced = service.enrich(
                "寻找端到端自动驾驶中的轨迹规划论文", null,
                List.of(paper("arxiv:1", null,
                        "We model trajectory planning and scene evolution for end-to-end autonomous driving.",
                        2025, true,
                        "Future-Aware End-to-End Driving: Trajectory Planning and Scene Evolution")))
                .papers().getFirst();

        ApiModels.RecommendationTrace trace = traced.recommendationTrace();
        assertThat(fullTextCalls).hasValue(0);
        assertThat(trace.partiallySatisfiedConstraints()).hasSize(1);
        assertThat(trace.unknownConstraints()).isEmpty();
        assertThat(trace.reasons()).singleElement().satisfies(reason -> {
            assertThat(reason.text()).startsWith("《").contains("的标题与摘要证据").contains("C1：");
            assertThat(reason.text()).contains("不依赖全文证据");
            assertThat(reason.text()).doesNotContain("保留候选原文");
        });
        assertThat(trace.evidence()).extracting(ApiModels.Evidence::sourceType)
                .containsExactly("title", "abstract");
    }

    @Test
    void keepsStrictRequirementUnknownButExplainsTheTitleAndAbstractAssessment() {
        PasaProperties properties = new PasaProperties();
        properties.setEnrichmentEnabled(false);
        DefaultPaperTraceabilityService service = service(
                paper -> ScholarlyMetadataClient.PaperMetadata.empty(), properties);

        ApiModels.RecommendationTrace trace = service.enrich(
                "必须在 CARLA 数据集上评测", null,
                List.of(paper("arxiv:1", null,
                        "We study trajectory planning for autonomous driving.", 2025, true,
                        "End-to-End Driving")))
                .papers().getFirst().recommendationTrace();

        assertThat(trace.unknownConstraints()).hasSize(1);
        assertThat(trace.reasons()).singleElement().satisfies(reason -> {
            assertThat(reason.text()).startsWith("《").contains("的标题与摘要证据").contains("C1：");
            assertThat(reason.text()).contains("没有直接支持该项严格要求的表述");
            assertThat(reason.text()).doesNotContain("现有证据不足以作确定判断");
        });
    }

    @Test
    void hydratesMissingIdentifiersSoFullTextCanBeRequested() {
        PasaProperties properties = new PasaProperties();
        ScholarlyMetadataClient metadata = paper -> new ScholarlyMetadataClient.PaperMetadata(
                null, null, null, "W4417175683", List.of(), "2506.22405",
                "10.48550/arxiv.2506.22405");
        DefaultPaperTraceabilityService service = service(metadata, properties);

        ApiModels.PaperItem traced = service.enrich("诊断", null,
                List.of(paper("local:1", null, "A diagnostic benchmark.", 2025, true,
                        "Sequential Diagnosis with Language Models"))).papers().getFirst();

        assertThat(traced.openalexId()).isEqualTo("W4417175683");
        assertThat(traced.arxivId()).isEqualTo("2506.22405");
        assertThat(traced.doi()).isEqualTo("10.48550/arxiv.2506.22405");
    }

    @Test
    void reconstructsOpenAlexInvertedAbstractInWordOrder() throws Exception {
        var index = new ObjectMapper().readTree("{\"world\":[1],\"Hello\":[0]}");
        assertThat(ExternalScholarlyMetadataClient.reconstructAbstract(index)).isEqualTo("Hello world");
    }

    private static DefaultPaperTraceabilityService service(
            ScholarlyMetadataClient metadata,
            PasaProperties properties
    ) {
        return new DefaultPaperTraceabilityService(metadata, properties, new QueryConstraintParser(), paper -> List.of());
    }

    private static ApiModels.PaperItem paper(String id, String openAlexId, String abstractText,
                                             Integer year, boolean selected, String title) {
        return new ApiModels.PaperItem(id, "", openAlexId, null, title, abstractText, 0.9,
                selected, 0, "SearchFrom:openalex", null, "https://openalex.org/" + openAlexId,
                year, null, "Test Venue", 0, List.of("Author"), List.of("openalex"));
    }

    private static ApiModels.PaperItem paperWithScore(
            String id,
            String abstractText,
            String title,
            double score
    ) {
        return new ApiModels.PaperItem(id, "", null, null, title, abstractText, score,
                true, 0, "SearchFrom:test", null, null, 2025, null,
                "Test Venue", 0, List.of("Author"), List.of("test"));
    }
}

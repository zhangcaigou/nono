package com.pasa.server.deepseek;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.pasa.server.api.ApiModels;
import com.pasa.server.config.PasaProperties;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class DeepSeekEvidenceGeneratorTest {
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void parsesAndValidatesLegalJsonForFullySatisfiedPaper() {
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(traceJson(
                "high", "Directly matches the query.",
                result("C1", "satisfied", "E1"),
                evidence("E1", "abstract", "uses knowledge distillation", "C1"))));

        var batch = generator.enrich("knowledge distillation", constraints("hard"),
                List.of(paper("p1", "Paper", "This paper uses knowledge distillation on real data.")));

        assertThat(batch.papers().getFirst().traceStatus()).isEqualTo("success");
        assertThat(batch.papers().getFirst().deepseekTrace().recommendationReason())
                .isEqualTo("Directly matches the query.");
        assertThat(batch.papers().getFirst().deepseekTrace().satisfiedConstraints()).containsExactly("C1");
        assertThat(batch.usage().totalCalls()).isEqualTo(1);
    }

    @Test
    void retriesMalformedJsonThenSucceeds() {
        AtomicInteger calls = new AtomicInteger();
        DeepSeekEvidenceGenerator generator = generator((system, user) -> calls.incrementAndGet() == 1
                ? completion("not-json")
                : completion(traceJson("partial", "Evidence found.",
                    result("C1", "satisfied", "E1"),
                    evidence("E1", "title", "Paper", "C1"))));

        var batch = generator.enrich("query", constraints("hard"),
                List.of(paper("retry", "Paper", "Abstract")));

        assertThat(calls).hasValue(2);
        assertThat(batch.papers().getFirst().traceStatus()).isEqualTo("success");
    }

    @Test
    void degradesAfterMalformedJsonRetriesAndPreservesSelectorFields() {
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion("{"));

        ApiModels.PaperItem original = paper("bad-json", "Paper", "Abstract");
        var batch = generator.enrich("query", constraints("hard"), List.of(original));
        ApiModels.PaperItem result = batch.papers().getFirst();

        assertThat(result.traceStatus()).isEqualTo("degraded");
        assertThat(result.deepseekTrace()).isNull();
        assertThat(result.selected()).isTrue();
        assertThat(result.score()).isEqualTo(original.score());
    }

    @Test
    void distinguishesUnknownFromExplicitViolation() {
        String json = traceJson("partial", "One exclusion is explicit; code is unknown.",
                result("C1", "violated", "E1") + "," + result("C2", "unknown", null),
                evidence("E1", "abstract", "includes synthetic data", "C1"));
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(json));

        var batch = generator.enrich("exclude synthetic data; prefer open code",
                List.of(constraint("C1", "exclusion"), constraint("C2", "soft")),
                List.of(paper("states", "Paper", "The evaluation includes synthetic data.")));
        ApiModels.DeepSeekTrace trace = batch.papers().getFirst().deepseekTrace();

        assertThat(trace.violatedConstraints()).containsExactly("C1");
        assertThat(trace.unknownConstraints()).containsExactly("C2");
    }

    @Test
    void keepsCodeAndDatasetUnknownWhenTopicIsRelevantButTheyAreNotStated() {
        String json = traceJson("partial", "The topic matches, while code and dataset are not stated.",
                result("C1", "satisfied", "E1") + "," + result("C2", "unknown", null)
                        + "," + result("C3", "unknown", null),
                evidence("E1", "title", "UAV Localization", "C1"));
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(json));

        var trace = generator.enrich("UAV localization with open code and a named dataset",
                List.of(constraint("C1", "hard"), constraint("C2", "soft"), constraint("C3", "hard")),
                List.of(paper("unknown-details", "UAV Localization", "A localization method.")))
                .papers().getFirst().deepseekTrace();

        assertThat(trace.satisfiedConstraints()).containsExactly("C1");
        assertThat(trace.unknownConstraints()).containsExactly("C2", "C3");
        assertThat(trace.violatedConstraints()).isEmpty();
    }

    @Test
    void removesUnhelpfulMissingInformationCaveatsFromRecommendationParagraph() {
        String reason = "该论文提出面向无人机定位的知识蒸馏方法，与检索主题直接相关。"
                + "实验使用真实飞行数据；然而，摘要未提供代码或数据集可用性信息，因此无法确认。";
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(traceJson(
                "high", reason, result("C1", "satisfied", "E1") + ","
                        + result("C2", "unknown", null),
                evidence("E1", "title", "UAV Localization", "C1"))));

        ApiModels.DeepSeekTrace trace = generator.enrich(
                "UAV localization with open code",
                List.of(constraint("C1", "hard"), constraint("C2", "soft")),
                List.of(paper("useful-reason", "UAV Localization", "A localization method.")))
                .papers().getFirst().deepseekTrace();

        assertThat(trace.recommendationReason())
                .contains("知识蒸馏方法", "实验使用真实飞行数据")
                .doesNotContain("未提供", "无法确认");
        assertThat(trace.unknownConstraints()).containsExactly("C2");
    }

    @Test
    void removesHallucinatedExactTextAndChangesJudgmentToUnknown() {
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(traceJson(
                "high", "Claims open source code.", result("C1", "satisfied", "E1"),
                evidence("E1", "abstract", "Code is available on GitHub", "C1"))));

        var trace = generator.enrich("open source code", constraints("soft"),
                List.of(paper("fake", "Paper", "The method improves localization.")))
                .papers().getFirst().deepseekTrace();

        assertThat(trace.evidence()).isEmpty();
        assertThat(trace.unknownConstraints()).containsExactly("C1");
        assertThat(trace.satisfiedConstraints()).isEmpty();
    }

    @Test
    void changesNonUnknownWithoutEvidenceToUnknown() {
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(traceJson(
                "partial", "No cited evidence.", result("C1", "partially_satisfied", null), "")));

        var result = generator.enrich("query", constraints("hard"),
                List.of(paper("no-evidence", "Paper", "Abstract")))
                .papers().getFirst().deepseekTrace().constraintResults().getFirst();

        assertThat(result.status()).isEqualTo("unknown");
        assertThat(result.evidenceIds()).isEmpty();
    }

    @Test
    void onePaperFailureDoesNotAffectOtherPaper() {
        DeepSeekEvidenceGenerator generator = generator((system, user) -> {
            if (user.contains("Slow Paper")) throw new IllegalStateException("timeout");
            return completion(traceJson("high", "Matched.", result("C1", "satisfied", "E1"),
                    evidence("E1", "title", "Good Paper", "C1")));
        });

        var papers = generator.enrich("query", constraints("hard"), List.of(
                paper("slow", "Slow Paper", "Abstract"),
                paper("good", "Good Paper", "Abstract"))).papers();

        assertThat(papers).extracting(ApiModels.PaperItem::traceStatus)
                .containsExactly("degraded", "success");
    }

    @Test
    void disabledModeDoesNotCallApiAndLeavesSelectorBehaviorIntact() {
        AtomicInteger calls = new AtomicInteger();
        PasaProperties properties = properties();
        properties.setDeepseekEvidenceEnabled(false);
        DeepSeekEvidenceGenerator generator = new DeepSeekEvidenceGenerator(
                (system, user) -> { calls.incrementAndGet(); return completion("{}"); },
                properties, objectMapper, "prompt");

        ApiModels.PaperItem original = paper("disabled", "Paper", "Abstract");
        ApiModels.PaperItem result = generator.enrich("query", constraints("hard"), List.of(original))
                .papers().getFirst();

        assertThat(calls).hasValue(0);
        assertThat(result.traceStatus()).isEqualTo("disabled");
        assertThat(result.selected()).isEqualTo(original.selected());
        assertThat(result.score()).isEqualTo(original.score());
    }

    @Test
    void cachesByQueryPaperAndPromptVersion() {
        AtomicInteger calls = new AtomicInteger();
        DeepSeekEvidenceGenerator generator = generator((system, user) -> {
            calls.incrementAndGet();
            return completion(traceJson("high", "Matched.", result("C1", "satisfied", "E1"),
                    evidence("E1", "title", "Paper", "C1")));
        });
        ApiModels.PaperItem paper = paper("cached", "Paper", "Abstract");

        generator.enrich("same query", constraints("hard"), List.of(paper));
        var second = generator.enrich("same query", constraints("hard"), List.of(paper));

        assertThat(calls).hasValue(1);
        assertThat(second.usage().cacheHits()).isEqualTo(1);
        assertThat(second.usage().totalCalls()).isZero();
    }

    private DeepSeekEvidenceGenerator generator(DeepSeekEvidenceClient client) {
        return new DeepSeekEvidenceGenerator(client, properties(), objectMapper, "Return JSON. Example: {}");
    }

    private static PasaProperties properties() {
        PasaProperties properties = new PasaProperties();
        properties.setDeepseekApiKey("test-only-key");
        properties.setDeepseekEvidenceEnabled(true);
        properties.setDeepseekMaxRetries(1);
        properties.setDeepseekConcurrency(2);
        properties.setDeepseekMaxPapers(20);
        return properties;
    }

    private static List<ApiModels.QueryConstraint> constraints(String type) {
        return List.of(constraint("C1", type));
    }

    private static ApiModels.QueryConstraint constraint(String id, String type) {
        return new ApiModels.QueryConstraint(id, type, "requested condition");
    }

    private static ApiModels.PaperItem paper(String id, String title, String abstractText) {
        return new ApiModels.PaperItem(id, "", null, null, title, abstractText, 0.91, true, 0,
                "mock", null, null, 2024, "2024-01-01", "Venue", 0,
                List.of("Author"), List.of("mock"));
    }

    private static DeepSeekEvidenceClient.Completion completion(String content) {
        return new DeepSeekEvidenceClient.Completion(content, 100, 50, "deepseek-v4-flash");
    }

    private static String result(String constraintId, String status, String evidenceId) {
        String evidenceIds = evidenceId == null ? "[]" : "[\"" + evidenceId + "\"]";
        return "{\"constraint_id\":\"" + constraintId + "\",\"status\":\"" + status
                + "\",\"explanation\":\"checked\",\"evidence_ids\":" + evidenceIds
                + ",\"confidence\":0.9}";
    }

    private static String evidence(String evidenceId, String sourceType, String exactText, String constraintId) {
        return "{\"evidence_id\":\"" + evidenceId + "\",\"source_type\":\"" + sourceType
                + "\",\"exact_text\":\"" + exactText + "\",\"location\":{\"field\":\""
                + sourceType + "\",\"sentence_index\":1,\"section\":null,\"page\":null},"
                + "\"supports_constraints\":[\"" + constraintId + "\"],\"confidence\":0.9}";
    }

    private static String traceJson(String relevance, String reason, String results, String evidence) {
        return "{\"recommendation_reason\":\"" + reason + "\",\"relevance_level\":\"" + relevance
                + "\",\"constraint_results\":[" + results + "],\"evidence\":[" + evidence + "],"
                + "\"satisfied_constraints\":[],\"partially_satisfied_constraints\":[],"
                + "\"violated_constraints\":[],\"unknown_constraints\":[]}";
    }
}

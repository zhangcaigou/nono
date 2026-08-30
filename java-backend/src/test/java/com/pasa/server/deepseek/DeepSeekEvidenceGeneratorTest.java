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
                "high", "该论文采用知识蒸馏处理目标任务，并在真实数据上验证方法，直接对应查询关注的技术路线。",
                result("C1", "satisfied", "E1"),
                evidence("E1", "abstract", "uses knowledge distillation", "C1"))));

        var batch = generator.enrich("knowledge distillation", constraints("hard"),
                List.of(paper("p1", "Paper", "This paper uses knowledge distillation on real data.")));

        assertThat(batch.papers().getFirst().traceStatus()).isEqualTo("success");
        assertThat(batch.papers().getFirst().deepseekTrace().recommendationReason())
                .contains("知识蒸馏", "真实数据");
        assertThat(batch.papers().getFirst().deepseekTrace().constraintResults().getFirst().explanation())
                .isEqualTo("该条件判断由下方可核验的论文原文证据支持。");
        assertThat(batch.papers().getFirst().deepseekTrace().satisfiedConstraints()).containsExactly("C1");
        assertThat(batch.usage().totalCalls()).isEqualTo(1);
    }

    @Test
    void retriesMalformedJsonThenSucceeds() {
        AtomicInteger calls = new AtomicInteger();
        DeepSeekEvidenceGenerator generator = generator((system, user) -> calls.incrementAndGet() == 1
                ? completion("not-json")
                : completion(traceJson("partial", "该论文围绕查询任务给出具体技术方案，标题为相关性判断提供了直接依据。",
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
        String json = traceJson("partial", "该论文明确评估了合成数据设置，可用于判断查询中的数据排除条件。",
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
        String json = traceJson("partial", "该论文研究无人机定位方法，标题直接对应用户关注的定位任务。",
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
    void removesStockOpeningsAndGenericResearchNeedSentences() {
        String reason = "该论文提出面向鉴别诊断的LLM，并在NEJM真实病例上由20名临床医生评估，"
                + "显示其辅助诊断准确率显著提升。研究直接涉及LLM在医疗诊断中的模型、评估与挑战，"
                + "符合用户对最新进展的调研需求。";

        String cleaned = DeepSeekEvidenceGenerator.usefulRecommendationReason(
                reason, paper("medical", "Differential Diagnosis with LLMs", "Abstract"));

        assertThat(cleaned)
                .startsWith("面向鉴别诊断的LLM")
                .contains("NEJM真实病例", "20名临床医生", "准确率显著提升")
                .doesNotContain("该论文提出", "研究直接涉及", "符合用户", "调研需求");
    }

    @Test
    void trimsGenericValueClaimWithoutDiscardingSpecificFinding() {
        String reason = "OrthoDoc结合RAG模块减少幻觉，并在骨科疾病诊断中超越GPT-4，"
                + "从而符合用户对最新进展的调研需求。";

        String cleaned = DeepSeekEvidenceGenerator.usefulRecommendationReason(
                reason, paper("orthodoc", "OrthoDoc", "Abstract"));

        assertThat(cleaned)
                .isEqualTo("OrthoDoc结合RAG模块减少幻觉，并在骨科疾病诊断中超越GPT-4。")
                .doesNotContain("符合用户", "调研需求");
    }

    @Test
    void removesHallucinatedExactTextAndChangesJudgmentToUnknown() {
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(traceJson(
                "high", "该论文讨论定位方法，并声称提供开源代码以回应用户对实现可用性的关注。", result("C1", "satisfied", "E1"),
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
                "partial", "该论文围绕查询问题展开方法研究，可作为相关技术路线的候选工作。", result("C1", "partially_satisfied", null), "")));

        var result = generator.enrich("query", constraints("hard"),
                List.of(paper("no-evidence", "Paper", "Abstract")))
                .papers().getFirst().deepseekTrace().constraintResults().getFirst();

        assertThat(result.status()).isEqualTo("unknown");
        assertThat(result.evidenceIds()).isEmpty();
    }

    @Test
    void onePaperFailureDoesNotAffectOtherPaper() {
        AtomicInteger calls = new AtomicInteger();
        DeepSeekEvidenceGenerator generator = generator((system, user) -> {
            calls.incrementAndGet();
            return completion(batchJson(
                    batchItem("slow", "{}"),
                    batchItem("good", traceJson("high", "该论文从标题所示任务出发提出具体方法，与查询关注的研究问题直接对应。",
                            result("C1", "satisfied", "E1"),
                            evidence("E1", "title", "Good Paper", "C1")))));
        });

        var papers = generator.enrich("query", constraints("hard"), List.of(
                paper("slow", "Slow Paper", "Abstract"),
                paper("good", "Good Paper", "Abstract"))).papers();

        assertThat(papers).extracting(ApiModels.PaperItem::traceStatus)
                .containsExactly("degraded", "success");
        assertThat(calls).hasValue(1);
    }

    @Test
    void batchesMultipleUncachedPapersIntoOneApiCall() {
        AtomicInteger calls = new AtomicInteger();
        DeepSeekEvidenceGenerator generator = generator((system, user) -> {
            calls.incrementAndGet();
            return completion(batchJson(
                    batchItem("p1", traceJson("high", "第一篇论文针对编码器设计展开研究，其标题明确对应查询关注的第一类方法。",
                            result("C1", "satisfied", "E1"),
                            evidence("E1", "title", "First Paper", "C1"))),
                    batchItem("p2", traceJson("partial", "第二篇论文重点研究排序策略，其标题体现了不同于第一篇的具体技术方向。",
                            result("C1", "satisfied", "E2"),
                            evidence("E2", "title", "Second Paper", "C1")))));
        });

        var batch = generator.enrich("query", constraints("hard"), List.of(
                paper("p1", "First Paper", "Abstract"),
                paper("p2", "Second Paper", "Abstract")));

        assertThat(calls).hasValue(1);
        assertThat(batch.usage().totalCalls()).isEqualTo(1);
        assertThat(batch.usage().inputTokens()).isEqualTo(100);
        assertThat(batch.usage().outputTokens()).isEqualTo(50);
        assertThat(batch.papers()).extracting(ApiModels.PaperItem::traceStatus)
                .containsExactly("success", "success");
        assertThat(batch.papers()).extracting(
                paper -> paper.deepseekTrace().recommendationReason())
                .doesNotHaveDuplicates();
    }

    @Test
    void acceptsCompactBatchTraceAndDerivesStatusLists() {
        String compactTrace = "{\"recommendation_reason\":\"该论文提出面向图检索的稠密编码器，并通过联合表示学习改善候选排序，能够直接支撑查询对检索方法的比较。\","
                + "\"relevance_level\":\"high\",\"constraint_results\":["
                + result("C1", "satisfied", "E1") + "],\"evidence\":["
                + evidence("E1", "title", "First Paper", "C1") + "]}";
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(batchJson(
                batchItem("p1", compactTrace),
                batchItem("p2", compactTrace.replace("图检索", "排序学习")
                        .replace("First Paper", "Second Paper")))));

        var papers = generator.enrich("query", constraints("hard"), List.of(
                paper("p1", "First Paper", "Abstract"),
                paper("p2", "Second Paper", "Abstract"))).papers();

        assertThat(papers).allSatisfy(paper -> {
            assertThat(paper.traceStatus()).isEqualTo("success");
            assertThat(paper.deepseekTrace().satisfiedConstraints()).containsExactly("C1");
        });
    }

    @Test
    void malformedBatchRetryUsesCompactCorrectionPrompt() {
        AtomicInteger calls = new AtomicInteger();
        DeepSeekEvidenceGenerator generator = generator((system, user) -> {
            if (calls.incrementAndGet() == 1) return completion("{");
            assertThat(user).contains("previous response was not complete JSON", "minimal schema");
            return completion(batchJson(
                    batchItem("p1", traceJson("high", "第一篇论文针对编码器结构提出具体改进，能够回应查询对表示学习方法的关注。",
                            result("C1", "satisfied", "E1"), evidence("E1", "title", "First Paper", "C1"))),
                    batchItem("p2", traceJson("high", "第二篇论文针对排序目标设计训练策略，能够回应查询对候选排序方法的关注。",
                            result("C1", "satisfied", "E2"), evidence("E2", "title", "Second Paper", "C1")))));
        });

        var batch = generator.enrich("query", constraints("hard"), List.of(
                paper("p1", "First Paper", "Abstract"),
                paper("p2", "Second Paper", "Abstract")));

        assertThat(calls).hasValue(2);
        assertThat(batch.papers()).extracting(ApiModels.PaperItem::traceStatus)
                .containsExactly("success", "success");
    }

    @Test
    void rejectsGenericNonChineseRecommendationInsteadOfShowingTemplateAsSuccess() {
        DeepSeekEvidenceGenerator generator = generator((system, user) -> completion(traceJson(
                "high", "This paper is relevant and worth reading.",
                result("C1", "satisfied", "E1"),
                evidence("E1", "title", "Paper", "C1"))));

        ApiModels.PaperItem result = generator.enrich(
                "query", constraints("hard"), List.of(paper("generic", "Paper", "Abstract")))
                .papers().getFirst();

        assertThat(result.traceStatus()).isEqualTo("degraded");
        assertThat(result.deepseekTrace()).isNull();
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
            return completion(traceJson("high", "该论文围绕目标任务提出明确方法，标题内容能够支持其与查询条件的具体关联。", result("C1", "satisfied", "E1"),
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

    private static String batchItem(String paperId, String trace) {
        return "{\"paper_id\":\"" + paperId + "\",\"trace\":" + trace + "}";
    }

    private static String batchJson(String... items) {
        return "{\"analyses\":[" + String.join(",", items) + "]}";
    }
}

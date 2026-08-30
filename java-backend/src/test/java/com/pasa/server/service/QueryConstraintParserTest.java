package com.pasa.server.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class QueryConstraintParserTest {
    @Test
    void splitsCompoundQueryWithoutAddingUnstatedConditions() {
        var constraints = new QueryConstraintParser().parse(
                "查找2022年以来使用知识蒸馏进行无人机定位的论文，要求真实数据，优先开源代码。", null);

        assertThat(constraints).extracting(value -> value.description()).containsExactly(
                "研究无人机定位", "使用知识蒸馏", "2022年以来", "要求真实数据", "优先开源代码");
        assertThat(constraints).extracting(value -> value.importance()).containsExactly(
                "hard", "hard", "hard", "hard", "soft");
        assertThat(constraints).extracting(value -> value.constraintId()).containsExactly(
                "C1", "C2", "C3", "C4", "C5");
        assertThat(constraints).allMatch(value -> !value.originalText().isBlank());
    }

    @Test
    void reusesStructuredModelUnderstandingInsteadOfReparsingPunctuation() throws Exception {
        var analysis = new ObjectMapper().readTree("""
                {"query_understanding":{
                  "research_intent":"研究 AI Agent 在复杂任务规划中的能力边界",
                  "hard_constraints":["长时程规划","约束遵循"],
                  "soft_constraints":["优先实证研究"],
                  "exclusions":["排除综述"],
                  "comparison_dimensions":["性能"]
                }}
                """);

        var constraints = new QueryConstraintParser().parseAnalysis(
                analysis, "比较 AI Agent 的复杂规划能力，排除综述", null);

        assertThat(constraints).extracting(value -> value.description()).containsExactly(
                "研究 AI Agent 在复杂任务规划中的能力边界",
                "长时程规划", "约束遵循", "排除综述", "性能");
        assertThat(constraints).extracting(value -> value.type()).containsExactly(
                "hard", "hard", "hard", "exclusion", "output");
    }

    @Test
    void doesNotExposePlannerInventedPreferencesOrExclusions() throws Exception {
        var analysis = new ObjectMapper().readTree("""
                {"query_understanding":{
                  "research_intent":"研究隐私保护联邦学习",
                  "hard_constraints":["必须涉及联邦学习","必须涉及隐私保护"],
                  "soft_constraints":["优先近五年","优先顶级会议"],
                  "exclusions":["排除非联邦学习","排除无隐私保护方法"]
                }}
                """);

        var constraints = new QueryConstraintParser().parseAnalysis(
                analysis, "联邦学习在隐私保护下的分布式训练", null);

        assertThat(constraints).extracting(value -> value.description()).containsExactly(
                "研究隐私保护联邦学习", "必须涉及联邦学习", "必须涉及隐私保护");
        assertThat(constraints).allMatch(value -> value.type().equals("hard"));
    }
}

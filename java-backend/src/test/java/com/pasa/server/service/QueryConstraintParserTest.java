package com.pasa.server.service;

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
}

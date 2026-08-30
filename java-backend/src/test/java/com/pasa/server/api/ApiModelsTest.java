package com.pasa.server.api;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ApiModelsTest {
    @Test
    void recommendationAnalysisDefaultsToEnabledWhenOptionIsOmitted() {
        ApiModels.SearchOptions options = new ApiModels.SearchOptions(null, null, null, null, null)
                .normalized();

        assertThat(options.recommendationAnalysis()).isTrue();
    }

    @Test
    void recommendationAnalysisCanStillBeExplicitlyEnabled() {
        ApiModels.SearchOptions options = new ApiModels.SearchOptions(null, null, null, null, true)
                .normalized();

        assertThat(options.recommendationAnalysis()).isTrue();
    }
}

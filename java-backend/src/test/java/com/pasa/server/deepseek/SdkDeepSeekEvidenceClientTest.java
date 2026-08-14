package com.pasa.server.deepseek;

import com.pasa.server.config.PasaProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SdkDeepSeekEvidenceClientTest {
    @Test
    void acceptsEnvironmentBackedConfigurationWithoutEmbeddingAKey() {
        PasaProperties properties = new PasaProperties();
        properties.setDeepseekApiKey("");
        properties.setDeepseekBaseUrl("https://api.deepseek.com");
        properties.setDeepseekModel("deepseek-v4-flash");
        properties.setDeepseekTimeout(60);
        properties.setDeepseekMaxRetries(2);

        SdkDeepSeekEvidenceClient client = new SdkDeepSeekEvidenceClient(properties);

        assertThat(properties.getDeepseekBaseUrl()).isEqualTo("https://api.deepseek.com");
        assertThat(properties.getDeepseekModel()).isEqualTo("deepseek-v4-flash");
        assertThat(properties.getDeepseekTimeout()).isEqualTo(60);
        assertThat(properties.getDeepseekMaxRetries()).isEqualTo(2);
        assertThatThrownBy(() -> client.complete("system", "user"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("DEEPSEEK_API_KEY");
    }
}

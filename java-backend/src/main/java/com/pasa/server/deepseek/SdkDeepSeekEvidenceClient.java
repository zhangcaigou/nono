package com.pasa.server.deepseek;

import com.openai.client.OpenAIClient;
import com.openai.client.okhttp.OpenAIOkHttpClient;
import com.openai.core.JsonValue;
import com.openai.core.RequestOptions;
import com.openai.models.chat.completions.ChatCompletion;
import com.openai.models.chat.completions.ChatCompletionCreateParams;
import com.pasa.server.config.PasaProperties;
import org.springframework.stereotype.Component;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URI;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;

@Component
public class SdkDeepSeekEvidenceClient implements DeepSeekEvidenceClient {
    private final PasaProperties properties;
    private final OpenAIClient client;

    public SdkDeepSeekEvidenceClient(PasaProperties properties) {
        this.properties = properties;
        if (properties.getDeepseekApiKey().isBlank()) {
            this.client = null;
            return;
        }
        OpenAIOkHttpClient.Builder builder = OpenAIOkHttpClient.builder()
            .apiKey(properties.getDeepseekApiKey())
            .baseUrl(properties.getDeepseekBaseUrl())
            // Application retries include malformed JSON; keep retry accounting in one place.
            .maxRetries(0);
        configuredProxy().ifPresent(builder::proxy);
        this.client = builder.build();
    }

    /**
     * OkHttp does not automatically consume the conventional proxy environment
     * variables. Use the deployment's existing HTTPS/HTTP proxy when present so
     * the evidence service can reach DeepSeek without embedding network settings
     * or credentials in source code.
     */
    static Optional<Proxy> configuredProxy() {
        String proxyUrl = firstNonBlank(
                System.getenv("DEEPSEEK_PROXY_URL"),
                System.getenv("HTTPS_PROXY"),
                System.getenv("https_proxy"),
                System.getenv("HTTP_PROXY"),
                System.getenv("http_proxy")
        );
        if (proxyUrl == null) {
            return Optional.empty();
        }
        try {
            URI uri = URI.create(proxyUrl);
            if (uri.getHost() == null) {
                return Optional.empty();
            }
            int port = uri.getPort();
            if (port < 0) {
                port = "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
            }
            return Optional.of(new Proxy(Proxy.Type.HTTP, new InetSocketAddress(uri.getHost(), port)));
        } catch (IllegalArgumentException ignored) {
            return Optional.empty();
        }
    }

    private static String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value.strip();
            }
        }
        return null;
    }

    @Override
    public Completion complete(String systemPrompt, String userPrompt) {
        if (client == null) {
            throw new IllegalStateException("DEEPSEEK_API_KEY is not configured");
        }
        ChatCompletionCreateParams params = ChatCompletionCreateParams.builder()
                .model(properties.getDeepseekModel())
                .addSystemMessage(systemPrompt)
                .addUserMessage(userPrompt)
                .temperature(0.0)
                .putAdditionalBodyProperty("stream", JsonValue.from(false))
                // Six evidence traces can legitimately exceed 4K tokens. The provider bills
                // actual output rather than this ceiling; extra headroom avoids paying for a
                // response cut in the middle of its JSON and then paying again for a retry.
                .putAdditionalBodyProperty("max_tokens", JsonValue.from(6144))
                .putAdditionalBodyProperty("response_format",
                        JsonValue.from(Map.of("type", "json_object")))
                .putAdditionalBodyProperty("thinking",
                        JsonValue.from(Map.of("type", "disabled")))
                .build();
        ChatCompletion completion = client.chat().completions().create(params,
                RequestOptions.builder()
                        .timeout(Duration.ofSeconds(properties.getDeepseekTimeout()))
                        .build());
        if (completion.choices().isEmpty()) {
            throw new IllegalStateException("DeepSeek returned no choices");
        }
        String content = completion.choices().getFirst().message().content().orElse("");
        long inputTokens = completion.usage().map(usage -> usage.promptTokens()).orElse(0L);
        long outputTokens = completion.usage().map(usage -> usage.completionTokens()).orElse(0L);
        return new Completion(content, inputTokens, outputTokens, completion.model());
    }
}

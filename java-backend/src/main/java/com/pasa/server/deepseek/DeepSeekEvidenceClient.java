package com.pasa.server.deepseek;

public interface DeepSeekEvidenceClient {
    Completion complete(String systemPrompt, String userPrompt);

    record Completion(String content, long inputTokens, long outputTokens, String modelName) {}
}

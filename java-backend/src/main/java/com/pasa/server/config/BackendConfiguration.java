package com.pasa.server.config;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.web.client.RestClient;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.concurrent.Executor;

@Configuration
public class BackendConfiguration {
    @Bean
    RestClient modelRestClient(RestClient.Builder builder, PasaProperties properties) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(java.time.Duration.ofSeconds(10));
        requestFactory.setReadTimeout(properties.getModelReadTimeout());
        return builder
                .baseUrl(properties.getModelServiceBaseUrl())
                .requestFactory(requestFactory)
                .build();
    }

    @Bean
    @Qualifier("scholarlyRestClient")
    RestClient scholarlyRestClient(RestClient.Builder builder, PasaProperties properties) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(properties.getScholarlyApiTimeout());
        requestFactory.setReadTimeout(properties.getScholarlyApiTimeout());
        return builder
                .requestFactory(requestFactory)
                .defaultHeader("User-Agent", "PaSa-paper-search/0.1 (metadata enrichment)")
                .build();
    }

    @Bean
    @Qualifier("searchTaskExecutor")
    Executor searchTaskExecutor(PasaProperties properties) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(properties.getTaskWorkers());
        executor.setMaxPoolSize(properties.getTaskWorkers());
        executor.setQueueCapacity(100);
        executor.setThreadNamePrefix("pasa-search-");
        executor.initialize();
        return executor;
    }

    @Bean
    WebMvcConfigurer corsConfigurer(PasaProperties properties) {
        return new WebMvcConfigurer() {
            @Override
            public void addCorsMappings(CorsRegistry registry) {
                registry.addMapping("/api/**")
                        .allowedOrigins(properties.getCorsOrigins().toArray(String[]::new))
                        .allowedMethods("GET", "POST", "DELETE", "OPTIONS")
                        .allowedHeaders("Content-Type", "Authorization", "X-Request-ID")
                        .allowCredentials(true);
            }
        };
    }
}

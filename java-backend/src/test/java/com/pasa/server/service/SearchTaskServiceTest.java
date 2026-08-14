package com.pasa.server.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.pasa.server.api.ApiModels;
import com.pasa.server.model.ModelGateway;
import com.pasa.server.model.ModelModels;
import com.pasa.server.model.ModelServiceException;
import com.pasa.server.config.PasaProperties;
import com.pasa.server.deepseek.DeepSeekEvidenceClient;
import com.pasa.server.deepseek.DeepSeekEvidenceGenerator;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

class SearchTaskServiceTest {
    @Test
    void createsTaskAndStoresModelResult() {
        ModelGateway gateway = new ModelGateway() {
            @Override
            public ModelModels.ModelSearchResponse search(ModelModels.ModelSearchRequest request) {
                ApiModels.PaperItem paper = new ApiModels.PaperItem(
                        "arxiv:2501.00001", "2501.00001", null, null,
                        "Paper", "Abstract", 0.9, true, 0,
                        "SearchFrom:mock", "https://arxiv.org/abs/2501.00001",
                        "https://arxiv.org/abs/2501.00001", 2025, "2025-01-01",
                        null, 0, List.of(), List.of("mock"));
                var analysis = new ObjectMapper().createObjectNode().put("model", "mock-analysis");
                return new ModelModels.ModelSearchResponse(
                        request.requestId(), request.query(), List.of(paper),
                        new ObjectMapper().createObjectNode(), new ApiModels.ResultSummary(1, 1), analysis);
            }

            @Override
            public Readiness readiness() {
                return new Readiness(true, null);
            }
        };
        Executor directExecutor = Runnable::run;
        SearchTaskService service = new SearchTaskService(gateway, directExecutor, passThroughTraceability(), disabledDeepSeek());

        ApiModels.TaskAccepted accepted = service.create(new ApiModels.CreateSearchTaskRequest(
                "find papers", null, null));

        assertThat(service.get(accepted.taskId()).status()).isEqualTo("succeeded");
        assertThat(service.result(accepted.taskId()).summary().paperCount()).isEqualTo(1);
        assertThat(service.result(accepted.taskId()).analysis().path("model").asText()).isEqualTo("mock-analysis");
        ApiModels.PaperItem resultPaper = service.result(accepted.taskId()).papers().getFirst();
        assertThat(resultPaper.score()).isEqualTo(0.9);
        assertThat(resultPaper.selected()).isTrue();
        assertThat(resultPaper.selectorScore()).isEqualTo(0.9);
        assertThat(resultPaper.selectorReason()).isNull();
        assertThat(resultPaper.traceStatus()).isEqualTo("disabled");
    }

    @Test
    void preservesStructuredModelServiceErrorOnTask() {
        ModelGateway gateway = new ModelGateway() {
            @Override
            public ModelModels.ModelSearchResponse search(ModelModels.ModelSearchRequest request) {
                throw new ModelServiceException(
                        "MODEL_UNAVAILABLE",
                        "PaSa 模型不可用",
                        List.of("SERPER_API_KEY 未设置"),
                        null
                );
            }

            @Override
            public Readiness readiness() {
                return new Readiness(false, "Python 模型服务尚未就绪");
            }
        };
        SearchTaskService service = new SearchTaskService(gateway, Runnable::run, passThroughTraceability(), disabledDeepSeek());

        ApiModels.TaskAccepted accepted = service.create(new ApiModels.CreateSearchTaskRequest(
                "find papers", null, null));
        ApiModels.TaskView task = service.get(accepted.taskId());

        assertThat(task.status()).isEqualTo("failed");
        assertThat(task.error().code()).isEqualTo("MODEL_UNAVAILABLE");
        assertThat(task.error().message()).isEqualTo("PaSa 模型不可用");
    }

    @Test
    void infersPublicationYearForArxivPaperWhenModelOmitsIt() {
        ModelGateway gateway = new ModelGateway() {
            @Override
            public ModelModels.ModelSearchResponse search(ModelModels.ModelSearchRequest request) {
                ApiModels.PaperItem paper = new ApiModels.PaperItem(
                        "arxiv:2312.10997", "2312.10997", null, null,
                        "Paper", "Abstract", 0.9, true, 0,
                        "SearchFrom:arxiv", "https://arxiv.org/abs/2312.10997",
                        "https://arxiv.org/abs/2312.10997", null, null,
                        null, 0, List.of(), List.of("arxiv"));
                return new ModelModels.ModelSearchResponse(
                        request.requestId(), request.query(), List.of(paper),
                        new ObjectMapper().createObjectNode(), new ApiModels.ResultSummary(1, 1));
            }

            @Override
            public Readiness readiness() {
                return new Readiness(true, null);
            }
        };
        SearchTaskService service = new SearchTaskService(gateway, Runnable::run, passThroughTraceability(), disabledDeepSeek());

        ApiModels.TaskAccepted accepted = service.create(new ApiModels.CreateSearchTaskRequest(
                "find papers", null, null));
        ApiModels.PaperItem paper = service.result(accepted.taskId()).papers().getFirst();

        assertThat(paper.publicationYear()).isEqualTo(2023);
        assertThat(paper.publicationDate()).isNull();
    }

    @Test
    void returnsCompleteTraceabilityFieldsWhenEnrichmentFails() {
        ModelGateway gateway = successfulGateway(new ApiModels.PaperItem(
                "arxiv:2501.00001", "2501.00001", null, null,
                "Fallback Paper", "Verified abstract", 0.8, true, 0,
                "SearchFrom:arxiv", "https://arxiv.org/abs/2501.00001",
                "https://arxiv.org/abs/2501.00001", 2025, null,
                null, 0, null, null));
        PaperTraceabilityService failingTraceability = (query, endDate, papers) -> {
            throw new IllegalStateException("simulated enrichment failure");
        };
        SearchTaskService service = new SearchTaskService(gateway, Runnable::run, failingTraceability, disabledDeepSeek());

        ApiModels.TaskAccepted accepted = service.create(new ApiModels.CreateSearchTaskRequest(
                "find papers", null, null));
        ApiModels.TaskResult result = service.result(accepted.taskId());
        ApiModels.PaperItem paper = result.papers().getFirst();

        assertThat(paper.abstractStatus()).isEqualTo("provided");
        assertThat(paper.abstractSource()).isEqualTo("arxiv");
        assertThat(paper.recommendationTrace()).isNull();
        assertThat(result.traceabilityEnabled()).isFalse();
        assertThat(paper.authors()).isEmpty();
        assertThat(result.relations()).isEmpty();
    }

    @Test
    void exposesModelProgressWhileSearchIsRunning() throws Exception {
        CountDownLatch progressSent = new CountDownLatch(1);
        CountDownLatch allowResult = new CountDownLatch(1);
        ApiModels.PaperItem resultPaper = new ApiModels.PaperItem(
                "arxiv:2501.00001", "2501.00001", null, null,
                "Paper", "Abstract", 0.9, true, 1,
                "SearchFrom:mock", "https://arxiv.org/abs/2501.00001",
                "https://arxiv.org/abs/2501.00001", 2025, null,
                null, 0, List.of(), List.of("mock"));
        ModelGateway gateway = new ModelGateway() {
            @Override
            public ModelModels.ModelSearchResponse search(ModelModels.ModelSearchRequest request) {
                return response(request, resultPaper);
            }

            @Override
            public ModelModels.ModelSearchResponse search(
                    ModelModels.ModelSearchRequest request,
                    ProgressListener progressListener
            ) {
                progressListener.onProgress(new ModelModels.ModelProgress("selecting", 0, 2, 7, 3));
                progressListener.onProgress(new ModelModels.ModelProgress("expanding", 1, 2, 11, 5));
                progressListener.onProgress(new ModelModels.ModelProgress("analyzing", 2, 2, 11, 5));
                progressSent.countDown();
                try {
                    if (!allowResult.await(5, TimeUnit.SECONDS)) {
                        throw new IllegalStateException("test result release timed out");
                    }
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException(exception);
                }
                return response(request, resultPaper);
            }

            @Override
            public Readiness readiness() {
                return new Readiness(true, null);
            }
        };

        try (ExecutorService executor = Executors.newSingleThreadExecutor()) {
            SearchTaskService service = new SearchTaskService(gateway, executor, passThroughTraceability(), disabledDeepSeek());
            ApiModels.TaskAccepted accepted = service.create(new ApiModels.CreateSearchTaskRequest(
                    "find papers", null, new ApiModels.SearchOptions(2, 5, 10, 20)));

            assertThat(progressSent.await(5, TimeUnit.SECONDS)).isTrue();
            ApiModels.TaskView running = service.get(accepted.taskId());
            assertThat(running.status()).isEqualTo("running");
            assertThat(running.stage()).isEqualTo("enriching");
            assertThat(running.progress()).isEqualTo(new ApiModels.TaskProgress(2, 2, 11, 5));

            allowResult.countDown();
        }
    }

    private static ModelGateway successfulGateway(ApiModels.PaperItem paper) {
        return new ModelGateway() {
            @Override
            public ModelModels.ModelSearchResponse search(ModelModels.ModelSearchRequest request) {
                return new ModelModels.ModelSearchResponse(
                        request.requestId(), request.query(), List.of(paper),
                        new ObjectMapper().createObjectNode(), new ApiModels.ResultSummary(1, 1));
            }

            @Override
            public Readiness readiness() {
                return new Readiness(true, null);
            }
        };
    }

    private static DeepSeekEvidenceGenerator disabledDeepSeek() {
        PasaProperties properties = new PasaProperties();
        properties.setDeepseekEvidenceEnabled(false);
        DeepSeekEvidenceClient client = (system, user) -> {
            throw new AssertionError("disabled DeepSeek client must not be called");
        };
        return new DeepSeekEvidenceGenerator(client, properties, new ObjectMapper());
    }

    private static ModelModels.ModelSearchResponse response(
            ModelModels.ModelSearchRequest request,
            ApiModels.PaperItem paper
    ) {
        return new ModelModels.ModelSearchResponse(
                request.requestId(), request.query(), List.of(paper),
                new ObjectMapper().createObjectNode(), new ApiModels.ResultSummary(1, 1));
    }

    private static PaperTraceabilityService passThroughTraceability() {
        return (query, endDate, papers) ->
                new PaperTraceabilityService.TraceablePapers(papers, List.of(), List.of(), false);
    }
}

package com.pasa.server.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.pasa.server.api.ApiModels;
import com.pasa.server.error.ApiException;
import com.pasa.server.model.ModelGateway;
import com.pasa.server.model.ModelModels;
import com.pasa.server.model.ModelServiceException;
import com.pasa.server.deepseek.DeepSeekEvidenceGenerator;
import org.springframework.beans.factory.annotation.Qualifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.Year;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class SearchTaskService {
    private static final Logger log = LoggerFactory.getLogger(SearchTaskService.class);
    private static final Pattern NEW_STYLE_ARXIV_ID =
            Pattern.compile("^(\\d{2})(\\d{2})\\.\\d+(?:v\\d+)?$");
    private final Map<String, TaskState> tasks = new ConcurrentHashMap<>();
    private final ModelGateway modelGateway;
    private final Executor executor;
    private final PaperTraceabilityService traceabilityService;
    private final DeepSeekEvidenceGenerator deepSeekEvidenceGenerator;

    public SearchTaskService(ModelGateway modelGateway,
                             @Qualifier("searchTaskExecutor") Executor executor,
                             PaperTraceabilityService traceabilityService,
                             DeepSeekEvidenceGenerator deepSeekEvidenceGenerator) {
        this.modelGateway = modelGateway;
        this.executor = executor;
        this.traceabilityService = traceabilityService;
        this.deepSeekEvidenceGenerator = deepSeekEvidenceGenerator;
    }

    public ApiModels.TaskAccepted create(ApiModels.CreateSearchTaskRequest request) {
        String taskId = UUID.randomUUID().toString().replace("-", "");
        ApiModels.SearchOptions options = request.options() == null
                ? new ApiModels.SearchOptions(null, null, null, null, null).normalized()
                : request.options().normalized();
        ApiModels.CreateSearchTaskRequest normalized = new ApiModels.CreateSearchTaskRequest(
                request.query().strip(), request.endDate(), options);
        TaskState task = new TaskState(taskId, normalized, options);
        tasks.put(taskId, task);
        try {
            executor.execute(() -> execute(taskId));
        } catch (RejectedExecutionException exception) {
            tasks.remove(taskId);
            throw new ApiException(429, "TOO_MANY_REQUESTS", "搜索任务队列已满");
        }
        return new ApiModels.TaskAccepted(taskId, "queued", task.createdAt);
    }

    private void execute(String taskId) {
        long totalStarted = System.nanoTime();
        TaskState task = require(taskId);
        synchronized (task) {
            if (task.cancelRequested) {
                markCancelled(task);
                return;
            }
            task.status = TaskState.Status.RUNNING;
            task.stage = TaskState.Stage.LOADING;
            task.startedAt = Instant.now();
        }

        try {
            long modelStarted = System.nanoTime();
            ModelModels.ModelSearchResponse response = modelGateway.search(new ModelModels.ModelSearchRequest(
                    task.taskId,
                    task.request.query(),
                    task.request.endDate(),
                    task.request.options()
            ), progress -> updateModelProgress(taskId, progress));
            long modelSearchMs = elapsedMs(modelStarted);
            List<ApiModels.PaperItem> papers = response.papers().stream()
                    .map(SearchTaskService::withPublicationYearFallback)
                    .toList();
            synchronized (task) {
                task.stage = TaskState.Stage.ENRICHING;
                task.progress = completedProgress(task, response);
            }
            List<ApiModels.QueryConstraint> plannedConstraints = new QueryConstraintParser()
                    .parseAnalysis(response.analysis(), task.request.query(), task.request.endDate());
            PaperTraceabilityService.TraceablePapers traceable;
            long traceabilityStarted = System.nanoTime();
            try {
                traceable = traceabilityService.enrich(
                        task.request.query(), task.request.endDate(), papers, plannedConstraints);
            } catch (Exception exception) {
                log.warn("Paper traceability enrichment failed for task {}; returning result without traces", taskId,
                        exception);
                traceable = PaperTraceabilityService.degraded(papers);
            }
            long traceabilityMs = elapsedMs(traceabilityStarted);
            List<ApiModels.QueryConstraint> constraints = traceable.constraints().isEmpty()
                    ? plannedConstraints
                    : traceable.constraints();
            DeepSeekEvidenceGenerator.BatchResult deepSeek;
            long deepSeekStarted = System.nanoTime();
            if (Boolean.TRUE.equals(task.request.options().recommendationAnalysis())) {
                try {
                    deepSeek = deepSeekEvidenceGenerator.enrich(
                            task.request.query(), constraints, traceable.papers());
                } catch (Exception exception) {
                    log.warn("DeepSeek evidence enrichment failed for task {}; preserving Selector results", taskId,
                            exception);
                    deepSeek = deepSeekEvidenceGenerator.degraded(traceable.papers());
                }
            } else {
                deepSeek = deepSeekEvidenceGenerator.disabled(traceable.papers());
            }
            long deepSeekMs = elapsedMs(deepSeekStarted);
            ApiModels.EfficiencyMetrics efficiency = new ApiModels.EfficiencyMetrics(
                    elapsedMs(totalStarted), modelSearchMs, traceabilityMs, deepSeekMs,
                    trackedModelApiCalls(response.metrics()) + deepSeek.usage().totalCalls(),
                    trackedModelTokens(response.metrics(), "input_tokens") + deepSeek.usage().inputTokens(),
                    trackedModelTokens(response.metrics(), "output_tokens") + deepSeek.usage().outputTokens(),
                    response.metrics());
            synchronized (task) {
                if (task.cancelRequested) {
                    markCancelled(task);
                    return;
                }
                task.result = new ApiModels.TaskResult(
                        task.taskId,
                        task.request.query(),
                        constraints,
                        traceable.enabled(),
                        deepSeek.papers(),
                        traceable.relations(),
                        response.tree(),
                        resultSummary(traceable),
                        response.analysis(),
                        deepSeek.usage(),
                        efficiency
                );
                task.progress = completedProgress(task, response);
                task.status = TaskState.Status.SUCCEEDED;
                task.stage = TaskState.Stage.FINISHED;
                task.finishedAt = Instant.now();
            }
            log.info("Search task {} completed total_ms={} model_ms={} trace_ms={} deepseek_ms={} api_calls={}",
                    taskId, efficiency.totalMs(), efficiency.modelSearchMs(), efficiency.traceabilityMs(),
                    efficiency.deepSeekMs(), efficiency.trackedApiCalls());
        } catch (ModelServiceException exception) {
            log.error("Python model service rejected task {} with code {}", taskId, exception.getCode(), exception);
            synchronized (task) {
                if (task.cancelRequested) {
                    markCancelled(task);
                    return;
                }
                task.status = TaskState.Status.FAILED;
                task.error = new ApiModels.TaskError(
                        exception.getCode(),
                        exception.getMessage(),
                        exception.getDetails()
                );
                task.finishedAt = Instant.now();
            }
        } catch (Exception exception) {
            log.error("Python model service failed for task {}", taskId, exception);
            synchronized (task) {
                if (task.cancelRequested) {
                    markCancelled(task);
                    return;
                }
                task.status = TaskState.Status.FAILED;
                task.error = new ApiModels.TaskError(
                        "MODEL_SERVICE_ERROR",
                        "Python 模型服务执行失败",
                        null
                );
                task.finishedAt = Instant.now();
            }
        }
    }

    private static long elapsedMs(long started) {
        return Math.max(0, (System.nanoTime() - started) / 1_000_000);
    }

    private static long trackedModelApiCalls(JsonNode metrics) {
        if (metrics == null) return 0;
        if (metrics.has("provider_network_calls")) {
            return metrics.path("provider_network_calls").asLong(0);
        }
        JsonNode retrieval = metrics.path("retrieval_stats");
        return retrieval.path("serper_calls").asLong(0) + retrieval.path("openalex_calls").asLong(0);
    }

    private static long trackedModelTokens(JsonNode metrics, String field) {
        if (metrics == null) return 0;
        return metrics.path("query_planning").path(field).asLong(0);
    }

    public ApiModels.TaskView get(String taskId) {
        TaskState task = require(taskId);
        synchronized (task) {
            return task.view();
        }
    }

    public ApiModels.TaskResult result(String taskId) {
        TaskState task = require(taskId);
        synchronized (task) {
            if (task.status != TaskState.Status.SUCCEEDED || task.result == null) {
                throw new ApiException(409, "TASK_NOT_FINISHED", "搜索任务尚未成功完成");
            }
            return task.result;
        }
    }

    public ApiModels.RecommendationTrace paperTrace(String taskId, String paperId, boolean includeFulltext) {
        TaskState task = require(taskId);
        ApiModels.PaperItem paper;
        String query;
        java.time.LocalDate endDate;
        synchronized (task) {
            if (task.status != TaskState.Status.SUCCEEDED || task.result == null) {
                throw new ApiException(409, "TASK_NOT_FINISHED", "搜索任务尚未成功完成");
            }
            paper = task.result.papers().stream()
                    .filter(item -> item.paperId().equals(paperId))
                    .findFirst()
                    .orElseThrow(() -> new ApiException(404, "PAPER_NOT_FOUND", "结果中不存在该论文"));
            if (paper.recommendationTrace() == null) {
                throw new ApiException(409, "TRACE_NOT_AVAILABLE", "该论文不在可追溯 Top-N 范围内");
            }
            query = task.request.query();
            endDate = task.request.endDate();
        }
        return includeFulltext
                ? traceabilityService.enrichFullText(query, endDate, paper)
                : paper.recommendationTrace();
    }

    public ApiModels.TaskView cancel(String taskId) {
        TaskState task = require(taskId);
        synchronized (task) {
            if (task.terminal()) {
                throw new ApiException(409, "TASK_STATE_CONFLICT", "任务已经进入终态");
            }
            task.cancelRequested = true;
            if (task.status == TaskState.Status.QUEUED) {
                markCancelled(task);
            }
            return task.view();
        }
    }

    private TaskState require(String taskId) {
        TaskState task = tasks.get(taskId);
        if (task == null) {
            throw new ApiException(404, "TASK_NOT_FOUND", "搜索任务不存在");
        }
        return task;
    }

    private static void markCancelled(TaskState task) {
        task.status = TaskState.Status.CANCELLED;
        task.finishedAt = Instant.now();
    }

    private void updateModelProgress(String taskId, ModelModels.ModelProgress progress) {
        TaskState task = tasks.get(taskId);
        if (task == null) {
            return;
        }
        synchronized (task) {
            if (task.status != TaskState.Status.RUNNING || task.cancelRequested) {
                return;
            }
            task.stage = switch (progress.stage()) {
                case "loading" -> TaskState.Stage.LOADING;
                case "analyzing" -> TaskState.Stage.ENRICHING;
                default -> TaskState.Stage.SEARCHING;
            };
            int totalLayers = progress.totalLayers() > 0
                    ? progress.totalLayers()
                    : task.progress.totalLayers();
            int currentLayer = Math.max(task.progress.currentLayer(), progress.currentLayer());
            if (totalLayers > 0) {
                currentLayer = Math.min(currentLayer, totalLayers);
            }
            task.progress = new ApiModels.TaskProgress(
                    Math.max(0, currentLayer),
                    Math.max(0, totalLayers),
                    Math.max(task.progress.papersFound(), progress.papersFound()),
                    Math.max(task.progress.papersSelected(), progress.papersSelected())
            );
        }
    }

    private static ApiModels.TaskProgress completedProgress(
            TaskState task,
            ModelModels.ModelSearchResponse response
    ) {
        int totalLayers = Math.max(task.progress.totalLayers(), task.request.options().expandLayers());
        return new ApiModels.TaskProgress(
                Math.max(task.progress.currentLayer(), totalLayers),
                totalLayers,
                Math.max(task.progress.papersFound(), response.summary().paperCount()),
                Math.max(task.progress.papersSelected(), response.summary().selectedCount())
        );
    }

    private static ApiModels.PaperItem withPublicationYearFallback(ApiModels.PaperItem paper) {
        Integer inferredYear = paper.publicationYear() != null
                ? paper.publicationYear() : inferPublicationYear(paper.arxivId());
        return new ApiModels.PaperItem(
                paper.paperId(), paper.arxivId(), paper.openalexId(), paper.doi(),
                paper.title(), paper.abstractText(), paper.score(), paper.selected(), paper.depth(),
                paper.source(), paper.arxivUrl(), paper.url(), inferredYear, paper.publicationDate(),
                paper.venue(), paper.citedByCount(), paper.authors(), paper.retrievalProviders(),
                paper.abstractStatus(), paper.abstractSource(), paper.abstractSourceUrl(), paper.recommendationTrace(),
                paper.selectorScore() == null ? paper.score() : paper.selectorScore(), paper.selectorReason(),
                paper.traceStatus() == null ? "disabled" : paper.traceStatus(), paper.deepseekTrace()
        );
    }

    private static ApiModels.ResultSummary resultSummary(PaperTraceabilityService.TraceablePapers result) {
        int abstractAvailable = (int) result.papers().stream()
                .filter(paper -> paper.abstractText() != null && !paper.abstractText().isBlank()).count();
        int abstractEnriched = (int) result.papers().stream()
                .filter(paper -> "enriched".equals(paper.abstractStatus())).count();
        int selected = (int) result.papers().stream().filter(ApiModels.PaperItem::selected).count();
        int traceable = (int) result.papers().stream()
                .filter(ApiModels.PaperItem::selected)
                .filter(paper -> paper.recommendationTrace() != null).count();
        return new ApiModels.ResultSummary(result.papers().size(), selected, abstractAvailable,
                abstractEnriched, traceable, result.relations().size());
    }

    private static Integer inferPublicationYear(String arxivId) {
        if (arxivId == null || arxivId.isBlank()) {
            return null;
        }
        Matcher matcher = NEW_STYLE_ARXIV_ID.matcher(arxivId.strip());
        if (!matcher.matches()) {
            return null;
        }
        int year = 2000 + Integer.parseInt(matcher.group(1));
        int month = Integer.parseInt(matcher.group(2));
        if (year < 2007 || year > Year.now().getValue() + 1 || month < 1 || month > 12) {
            return null;
        }
        return year;
    }
}

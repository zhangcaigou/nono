package com.pasa.server.service;

import com.pasa.server.api.ApiModels;

import java.time.Instant;

final class TaskState {
    enum Status { QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED }
    enum Stage { QUEUED, LOADING, SEARCHING, ENRICHING, FINISHED }

    final String taskId;
    final ApiModels.CreateSearchTaskRequest request;
    final Instant createdAt = Instant.now();
    Status status = Status.QUEUED;
    Stage stage = Stage.QUEUED;
    ApiModels.TaskProgress progress;
    Instant startedAt;
    Instant finishedAt;
    ApiModels.TaskError error;
    ApiModels.TaskResult result;
    boolean cancelRequested;

    TaskState(String taskId, ApiModels.CreateSearchTaskRequest request, ApiModels.SearchOptions options) {
        this.taskId = taskId;
        this.request = request;
        this.progress = new ApiModels.TaskProgress(0, options.expandLayers(), 0, 0);
    }

    boolean terminal() {
        return status == Status.SUCCEEDED || status == Status.FAILED || status == Status.CANCELLED;
    }

    ApiModels.TaskView view() {
        return new ApiModels.TaskView(
                taskId,
                request.query(),
                status.name().toLowerCase(),
                stage.name().toLowerCase(),
                progress,
                createdAt,
                startedAt,
                finishedAt,
                error
        );
    }
}

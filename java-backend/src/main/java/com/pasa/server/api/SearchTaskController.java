package com.pasa.server.api;

import com.pasa.server.service.SearchTaskService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/search-tasks")
public class SearchTaskController {
    private final SearchTaskService service;

    public SearchTaskController(SearchTaskService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ApiModels.TaskAccepted create(@Valid @RequestBody ApiModels.CreateSearchTaskRequest request) {
        return service.create(request);
    }

    @GetMapping("/{taskId}")
    public ApiModels.TaskView get(@PathVariable String taskId) {
        return service.get(taskId);
    }

    @GetMapping("/{taskId}/result")
    public ApiModels.TaskResult result(@PathVariable String taskId) {
        return service.result(taskId);
    }

    @GetMapping("/{taskId}/papers/{paperId}/trace")
    public ApiModels.RecommendationTrace paperTrace(
            @PathVariable String taskId,
            @PathVariable String paperId,
            @RequestParam(name = "include_fulltext", defaultValue = "false") boolean includeFulltext
    ) {
        return service.paperTrace(taskId, paperId, includeFulltext);
    }

    @DeleteMapping("/{taskId}")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ApiModels.TaskView cancel(@PathVariable String taskId) {
        return service.cancel(taskId);
    }
}

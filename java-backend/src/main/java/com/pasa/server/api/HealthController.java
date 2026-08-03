package com.pasa.server.api;

import com.pasa.server.model.ModelGateway;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/v1/health")
public class HealthController {
    private final ModelGateway modelGateway;

    public HealthController(ModelGateway modelGateway) {
        this.modelGateway = modelGateway;
    }

    @GetMapping
    public ApiModels.HealthResponse health() {
        ModelGateway.Readiness readiness = modelGateway.readiness();
        return new ApiModels.HealthResponse(
                "ok",
                "PaSa Java Backend",
                readiness.ready(),
                readiness.ready(),
                readiness.reason() == null ? List.of() : List.of(readiness.reason())
        );
    }
}


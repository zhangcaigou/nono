package com.pasa.server.model;

import com.pasa.server.model.ModelModels.ModelSearchRequest;
import com.pasa.server.model.ModelModels.ModelSearchResponse;

public interface ModelGateway {
    ModelSearchResponse search(ModelSearchRequest request);

    default ModelSearchResponse search(ModelSearchRequest request, ProgressListener progressListener) {
        return search(request);
    }

    Readiness readiness();

    @FunctionalInterface
    interface ProgressListener {
        void onProgress(ModelModels.ModelProgress progress);
    }

    record Readiness(boolean ready, String reason) {}
}

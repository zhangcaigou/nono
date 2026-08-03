package com.pasa.server.service;

import com.pasa.server.api.ApiModels;

import java.util.List;

public interface ScholarlyMetadataClient {
    PaperMetadata lookup(ApiModels.PaperItem paper);

    record PaperMetadata(
            String abstractText,
            String abstractSource,
            String abstractSourceUrl,
            String openAlexId,
            List<String> referencedOpenAlexIds,
            String arxivId,
            String doi
    ) {
        public PaperMetadata(String abstractText, String abstractSource, String abstractSourceUrl,
                             String openAlexId, List<String> referencedOpenAlexIds) {
            this(abstractText, abstractSource, abstractSourceUrl, openAlexId,
                    referencedOpenAlexIds, null, null);
        }

        public static PaperMetadata empty() {
            return new PaperMetadata(null, null, null, null, List.of(), null, null);
        }
    }
}

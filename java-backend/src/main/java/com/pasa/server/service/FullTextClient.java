package com.pasa.server.service;

import com.pasa.server.api.ApiModels;

import java.util.List;

public interface FullTextClient {
    List<FullTextPassage> load(ApiModels.PaperItem paper);

    record FullTextPassage(String section, String exactText, String sourceUrl) {}
}

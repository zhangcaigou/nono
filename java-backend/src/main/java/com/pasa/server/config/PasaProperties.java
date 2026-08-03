package com.pasa.server.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

@ConfigurationProperties(prefix = "pasa")
public class PasaProperties {
    private String modelServiceBaseUrl = "http://127.0.0.1:8000";
    private String internalToken = "";
    private Duration modelReadTimeout = Duration.ofMinutes(30);
    private Duration scholarlyApiTimeout = Duration.ofSeconds(6);
    private int taskWorkers = 1;
    private int enrichmentMaxPapers = 40;
    private int enrichmentConcurrency = 6;
    private boolean enrichmentEnabled = true;
    private boolean traceabilityEnabled = true;
    private int traceTopN = 10;
    private Duration traceCacheTtl = Duration.ofHours(6);
    private int traceCacheMaxEntries = 200;
    private boolean traceFulltextEnabled = true;
    private int traceFulltextMaxPassages = 120;
    private String semanticScholarApiKey = "";
    private String openAlexApiKey = "";
    private String openAlexEmail = "";
    private List<String> corsOrigins = new ArrayList<>(List.of("http://localhost:3000", "http://localhost:5173"));

    public String getModelServiceBaseUrl() { return modelServiceBaseUrl; }
    public void setModelServiceBaseUrl(String value) { this.modelServiceBaseUrl = value; }
    public String getInternalToken() { return internalToken; }
    public void setInternalToken(String value) { this.internalToken = value; }
    public Duration getModelReadTimeout() { return modelReadTimeout; }
    public void setModelReadTimeout(Duration value) { this.modelReadTimeout = value; }
    public Duration getScholarlyApiTimeout() { return scholarlyApiTimeout; }
    public void setScholarlyApiTimeout(Duration value) { this.scholarlyApiTimeout = value; }
    public int getTaskWorkers() { return taskWorkers; }
    public void setTaskWorkers(int value) { this.taskWorkers = Math.max(1, value); }
    public int getEnrichmentMaxPapers() { return enrichmentMaxPapers; }
    public void setEnrichmentMaxPapers(int value) { this.enrichmentMaxPapers = Math.max(0, value); }
    public int getEnrichmentConcurrency() { return enrichmentConcurrency; }
    public void setEnrichmentConcurrency(int value) { this.enrichmentConcurrency = Math.max(1, value); }
    public boolean isEnrichmentEnabled() { return enrichmentEnabled; }
    public void setEnrichmentEnabled(boolean value) { this.enrichmentEnabled = value; }
    public boolean isTraceabilityEnabled() { return traceabilityEnabled; }
    public void setTraceabilityEnabled(boolean value) { this.traceabilityEnabled = value; }
    public int getTraceTopN() { return traceTopN; }
    public void setTraceTopN(int value) { this.traceTopN = Math.max(0, value); }
    public Duration getTraceCacheTtl() { return traceCacheTtl; }
    public void setTraceCacheTtl(Duration value) { this.traceCacheTtl = value == null ? Duration.ofHours(6) : value; }
    public int getTraceCacheMaxEntries() { return traceCacheMaxEntries; }
    public void setTraceCacheMaxEntries(int value) { this.traceCacheMaxEntries = Math.max(1, value); }
    public boolean isTraceFulltextEnabled() { return traceFulltextEnabled; }
    public void setTraceFulltextEnabled(boolean value) { this.traceFulltextEnabled = value; }
    public int getTraceFulltextMaxPassages() { return traceFulltextMaxPassages; }
    public void setTraceFulltextMaxPassages(int value) { this.traceFulltextMaxPassages = Math.max(1, value); }
    public String getSemanticScholarApiKey() { return semanticScholarApiKey; }
    public void setSemanticScholarApiKey(String value) { this.semanticScholarApiKey = value == null ? "" : value; }
    public String getOpenAlexApiKey() { return openAlexApiKey; }
    public void setOpenAlexApiKey(String value) { this.openAlexApiKey = value == null ? "" : value; }
    public String getOpenAlexEmail() { return openAlexEmail; }
    public void setOpenAlexEmail(String value) { this.openAlexEmail = value == null ? "" : value; }
    public List<String> getCorsOrigins() { return corsOrigins; }
    public void setCorsOrigins(List<String> value) { this.corsOrigins = value; }
}

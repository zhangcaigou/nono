package com.pasa.server.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.pasa.server.api.ApiModels;
import com.pasa.server.config.PasaProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.HtmlUtils;
import org.springframework.web.util.UriComponentsBuilder;
import org.w3c.dom.Document;
import org.w3c.dom.NodeList;
import org.xml.sax.InputSource;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.StringReader;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

@Component
public class ExternalScholarlyMetadataClient implements ScholarlyMetadataClient {
    private static final Logger log = LoggerFactory.getLogger(ExternalScholarlyMetadataClient.class);
    private final RestClient client;
    private final PasaProperties properties;

    public ExternalScholarlyMetadataClient(
            @Qualifier("scholarlyRestClient") RestClient client,
            PasaProperties properties
    ) {
        this.client = client;
        this.properties = properties;
    }

    @Override
    public PaperMetadata lookup(ApiModels.PaperItem paper) {
        if (!properties.isEnrichmentEnabled()) {
            return PaperMetadata.empty();
        }

        PaperMetadata openAlex = lookupOpenAlex(paper);
        if (hasText(paper.abstractText()) || hasText(openAlex.abstractText())) {
            return openAlex;
        }

        AbstractCandidate candidate = lookupArxiv(hasText(paper.arxivId()) ? paper.arxivId() : openAlex.arxivId());
        if (candidate == null) {
            candidate = lookupSemanticScholar(paper);
        }
        if (candidate == null) {
            candidate = lookupCrossref(paper.doi());
        }
        if (candidate == null) {
            return openAlex;
        }
        return new PaperMetadata(candidate.text(), candidate.source(), candidate.url(),
                openAlex.openAlexId(), openAlex.referencedOpenAlexIds(),
                openAlex.arxivId(), openAlex.doi());
    }

    private PaperMetadata lookupOpenAlex(ApiModels.PaperItem paper) {
        String openAlexId = normalizeOpenAlexId(paper.openalexId());
        if (!hasText(openAlexId)) {
            return lookupOpenAlexByTitle(paper);
        }
        try {
            UriComponentsBuilder builder = UriComponentsBuilder
                    .fromUriString("https://api.openalex.org/works/{id}")
                    .queryParam("select", "id,title,ids,abstract_inverted_index,referenced_works");
            addOpenAlexCredentials(builder);
            URI uri = builder.buildAndExpand(openAlexId).encode().toUri();
            JsonNode work = client.get().uri(uri).retrieve().body(JsonNode.class);
            if (work == null) {
                return PaperMetadata.empty();
            }
            return openAlexMetadata(work);
        } catch (Exception exception) {
            log.debug("OpenAlex enrichment failed for {}: {}", paper.paperId(), exception.getMessage());
            return new PaperMetadata(null, null, null, openAlexId, List.of());
        }
    }

    private PaperMetadata lookupOpenAlexByTitle(ApiModels.PaperItem paper) {
        if (!hasText(paper.title())) {
            return PaperMetadata.empty();
        }
        try {
            UriComponentsBuilder builder = UriComponentsBuilder
                    .fromUriString("https://api.openalex.org/works")
                    .queryParam("filter", "title.search:" + paper.title())
                    .queryParam("per-page", 3)
                    .queryParam("select", "id,title,ids,abstract_inverted_index,referenced_works");
            addOpenAlexCredentials(builder);
            JsonNode response = client.get().uri(builder.build().encode().toUri())
                    .retrieve().body(JsonNode.class);
            if (response == null) {
                return PaperMetadata.empty();
            }
            for (JsonNode candidate : response.path("results")) {
                if (titleSimilarity(paper.title(), candidate.path("title").asText()) >= 0.9) {
                    return openAlexMetadata(candidate);
                }
            }
        } catch (Exception exception) {
            log.debug("OpenAlex title lookup failed for {}: {}", paper.paperId(), exception.getMessage());
        }
        return PaperMetadata.empty();
    }

    private PaperMetadata openAlexMetadata(JsonNode work) {
        String openAlexId = normalizeOpenAlexId(work.path("id").asText());
        List<String> references = new ArrayList<>();
        work.path("referenced_works").forEach(node -> references.add(normalizeOpenAlexId(node.asText())));
        String abstractText = reconstructAbstract(work.path("abstract_inverted_index"));
        String doi = normalizeNullableDoi(work.path("ids").path("doi").asText(null));
        String arxivId = extractArxivId(work.path("ids").path("arxiv").asText(null), doi);
        return new PaperMetadata(abstractText, hasText(abstractText) ? "openalex" : null,
                hasText(openAlexId) ? "https://openalex.org/" + openAlexId : null,
                openAlexId, List.copyOf(references), arxivId, doi);
    }

    private void addOpenAlexCredentials(UriComponentsBuilder builder) {
        if (hasText(properties.getOpenAlexApiKey())) {
            builder.queryParam("api_key", properties.getOpenAlexApiKey());
        }
        if (hasText(properties.getOpenAlexEmail())) {
            builder.queryParam("mailto", properties.getOpenAlexEmail());
        }
    }

    private AbstractCandidate lookupArxiv(String arxivId) {
        if (!hasText(arxivId)) {
            return null;
        }
        try {
            URI uri = UriComponentsBuilder.fromUriString("https://export.arxiv.org/api/query")
                    .queryParam("id_list", arxivId).build().encode().toUri();
            String xml = client.get().uri(uri).retrieve().body(String.class);
            if (!hasText(xml)) {
                return null;
            }
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
            factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
            factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
            factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
            factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
            Document document = factory.newDocumentBuilder().parse(new InputSource(new StringReader(xml)));
            NodeList summaries = document.getElementsByTagName("summary");
            if (summaries.getLength() == 0) {
                return null;
            }
            String text = cleanText(summaries.item(0).getTextContent());
            return hasText(text) ? new AbstractCandidate(text, "arxiv",
                    "https://arxiv.org/abs/" + arxivId) : null;
        } catch (Exception exception) {
            log.debug("arXiv enrichment failed for {}: {}", arxivId, exception.getMessage());
            return null;
        }
    }

    private AbstractCandidate lookupSemanticScholar(ApiModels.PaperItem paper) {
        String identifier = hasText(paper.doi()) ? "DOI:" + normalizeDoi(paper.doi())
                : hasText(paper.arxivId()) ? "ARXIV:" + paper.arxivId() : null;
        if (hasText(identifier)) {
            try {
                String encodedId = URLEncoder.encode(identifier, StandardCharsets.UTF_8).replace("+", "%20");
                URI uri = URI.create("https://api.semanticscholar.org/graph/v1/paper/" + encodedId
                        + "?fields=abstract,url");
                JsonNode result = semanticScholarRequest(uri);
                if (result != null && hasText(result.path("abstract").asText())) {
                    return new AbstractCandidate(cleanText(result.path("abstract").asText()), "semantic_scholar",
                            result.path("url").asText("https://www.semanticscholar.org/"));
                }
            } catch (Exception exception) {
                log.debug("Semantic Scholar identifier lookup failed for {}: {}",
                        paper.paperId(), exception.getMessage());
            }
        }

        if (!hasText(paper.title())) {
            return null;
        }
        try {
            URI uri = UriComponentsBuilder
                    .fromUriString("https://api.semanticscholar.org/graph/v1/paper/search")
                    .queryParam("query", paper.title().replace('-', ' '))
                    .queryParam("limit", 3)
                    .queryParam("fields", "title,abstract,url")
                    .build().encode().toUri();
            JsonNode result = semanticScholarRequest(uri);
            if (result == null) {
                return null;
            }
            for (JsonNode candidate : result.path("data")) {
                if (hasText(candidate.path("abstract").asText())
                        && titleSimilarity(paper.title(), candidate.path("title").asText()) >= 0.8) {
                    return new AbstractCandidate(cleanText(candidate.path("abstract").asText()),
                            "semantic_scholar", candidate.path("url").asText("https://www.semanticscholar.org/"));
                }
            }
            return null;
        } catch (Exception exception) {
            log.debug("Semantic Scholar title lookup failed for {}: {}", paper.paperId(), exception.getMessage());
            return null;
        }
    }

    private JsonNode semanticScholarRequest(URI uri) {
        RestClient.RequestHeadersSpec<?> request = client.get().uri(uri);
        if (hasText(properties.getSemanticScholarApiKey())) {
            request = request.header("x-api-key", properties.getSemanticScholarApiKey());
        }
        return request.retrieve().body(JsonNode.class);
    }

    private AbstractCandidate lookupCrossref(String doi) {
        if (!hasText(doi)) {
            return null;
        }
        try {
            String encodedDoi = URLEncoder.encode(normalizeDoi(doi), StandardCharsets.UTF_8).replace("+", "%20");
            JsonNode result = client.get().uri(URI.create("https://api.crossref.org/works/" + encodedDoi))
                    .header(HttpHeaders.ACCEPT, "application/json")
                    .retrieve().body(JsonNode.class);
            String abstractText = result == null ? "" : result.path("message").path("abstract").asText();
            abstractText = cleanText(HtmlUtils.htmlUnescape(abstractText.replaceAll("<[^>]+>", " ")));
            return hasText(abstractText) ? new AbstractCandidate(abstractText, "crossref",
                    "https://doi.org/" + normalizeDoi(doi)) : null;
        } catch (Exception exception) {
            log.debug("Crossref enrichment failed for {}: {}", doi, exception.getMessage());
            return null;
        }
    }

    static String reconstructAbstract(JsonNode invertedIndex) {
        if (invertedIndex == null || !invertedIndex.isObject() || invertedIndex.isEmpty()) {
            return null;
        }
        List<PositionedWord> words = new ArrayList<>();
        invertedIndex.properties().forEach(entry -> entry.getValue().forEach(
                position -> words.add(new PositionedWord(position.asInt(), entry.getKey()))));
        words.sort((left, right) -> Integer.compare(left.position(), right.position()));
        return cleanText(words.stream().map(PositionedWord::word).reduce("", (a, b) -> a + " " + b));
    }

    private static String normalizeOpenAlexId(String value) {
        if (!hasText(value)) {
            return null;
        }
        String normalized = value.strip();
        int slash = normalized.lastIndexOf('/');
        return (slash >= 0 ? normalized.substring(slash + 1) : normalized).toUpperCase(Locale.ROOT);
    }

    private static String normalizeDoi(String value) {
        return value.strip().replaceFirst("(?i)^https?://(?:dx\\.)?doi\\.org/", "");
    }

    private static String normalizeNullableDoi(String value) {
        return hasText(value) ? normalizeDoi(value) : null;
    }

    private static String extractArxivId(String arxivUrl, String doi) {
        if (hasText(arxivUrl)) {
            return arxivUrl.strip().replaceFirst("(?i)^https?://arxiv\\.org/abs/", "");
        }
        if (hasText(doi) && doi.toLowerCase(Locale.ROOT).startsWith("10.48550/arxiv.")) {
            return doi.substring("10.48550/arxiv.".length());
        }
        return null;
    }

    private static String cleanText(String value) {
        return value == null ? null : value.replaceAll("\\s+", " ").strip();
    }

    private static double titleSimilarity(String left, String right) {
        String normalizedLeft = left.toLowerCase(Locale.ROOT).replaceAll("[^\\p{L}\\p{N}]+", " ").strip();
        String normalizedRight = right.toLowerCase(Locale.ROOT).replaceAll("[^\\p{L}\\p{N}]+", " ").strip();
        if (normalizedLeft.equals(normalizedRight)) {
            return 1.0;
        }
        List<String> leftTokens = List.of(normalizedLeft.split("\\s+"));
        List<String> rightTokens = List.of(normalizedRight.split("\\s+"));
        long overlap = leftTokens.stream().distinct().filter(rightTokens::contains).count();
        return overlap / (double) Math.max(1, Math.max(leftTokens.size(), rightTokens.size()));
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private record AbstractCandidate(String text, String source, String url) {}
    private record PositionedWord(int position, String word) {}
}

package com.pasa.server.service;

import com.pasa.server.api.ApiModels;
import com.pasa.server.config.PasaProperties;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.net.URI;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class Ar5ivFullTextClient implements FullTextClient {
    private final RestClient client;
    private final PasaProperties properties;
    private final Map<String, CacheEntry> cache = new ConcurrentHashMap<>();

    public Ar5ivFullTextClient(
            @Qualifier("scholarlyRestClient") RestClient client,
            PasaProperties properties
    ) {
        this.client = client;
        this.properties = properties;
    }

    @Override
    public List<FullTextPassage> load(ApiModels.PaperItem paper) {
        if (!properties.isTraceFulltextEnabled() || paper.arxivId() == null || paper.arxivId().isBlank()) {
            return List.of();
        }
        CacheEntry hit = cache.get(paper.arxivId());
        if (hit != null && hit.createdAt().plus(properties.getTraceCacheTtl()).isAfter(Instant.now())) {
            return hit.passages();
        }
        String url = "https://ar5iv.labs.arxiv.org/html/" + paper.arxivId();
        try {
            String html = client.get().uri(URI.create(url)).retrieve().body(String.class);
            if (html == null || html.isBlank()) {
                return List.of();
            }
            Document document = Jsoup.parse(html, url);
            List<FullTextPassage> passages = new ArrayList<>();
            for (Element section : document.select("section")) {
                Element heading = section.selectFirst("h1, h2, h3, h4, h5, h6");
                if (heading == null || heading.text().isBlank()) {
                    continue;
                }
                String sectionName = heading.text().strip();
                for (Element paragraph : section.select("p")) {
                    String exactText = paragraph.text().replaceAll("\\s+", " ").strip();
                    if (exactText.length() >= 40) {
                        passages.add(new FullTextPassage(sectionName, exactText, url));
                    }
                    if (passages.size() >= properties.getTraceFulltextMaxPassages()) {
                        break;
                    }
                }
                if (passages.size() >= properties.getTraceFulltextMaxPassages()) {
                    break;
                }
            }
            List<FullTextPassage> result = List.copyOf(passages);
            cache.put(paper.arxivId(), new CacheEntry(Instant.now(), result));
            return result;
        } catch (Exception exception) {
            return List.of();
        }
    }

    private record CacheEntry(Instant createdAt, List<FullTextPassage> passages) {}
}

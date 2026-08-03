package com.pasa.server.service;

import com.pasa.server.api.ApiModels;
import com.pasa.server.config.PasaProperties;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class ExternalScholarlyMetadataClientTest {
    @Test
    void findsMissingIdentifiersByExactTitleAndExtractsArxivIdFromDoi() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo(containsString("title.search")))
                .andRespond(withSuccess("""
                        {
                          "results": [{
                            "id": "https://openalex.org/W4417175683",
                            "title": "Sequential Diagnosis with Language Models",
                            "ids": {"doi": "https://doi.org/10.48550/arxiv.2506.22405"},
                            "abstract_inverted_index": {"Diagnostic": [0], "evidence": [1]},
                            "referenced_works": ["https://openalex.org/W1"]
                          }]
                        }
                        """, MediaType.APPLICATION_JSON));
        ExternalScholarlyMetadataClient client = new ExternalScholarlyMetadataClient(
                builder.build(), new PasaProperties());
        ApiModels.PaperItem paper = new ApiModels.PaperItem(
                "local:1", "", null, null, "Sequential Diagnosis with Language Models",
                "", 0.9, true, 0, "SearchFrom:local_paper_db", null, null,
                2025, null, null, 0, List.of(), List.of("local_paper_db"));

        ScholarlyMetadataClient.PaperMetadata metadata = client.lookup(paper);

        assertThat(metadata.openAlexId()).isEqualTo("W4417175683");
        assertThat(metadata.arxivId()).isEqualTo("2506.22405");
        assertThat(metadata.doi()).isEqualTo("10.48550/arxiv.2506.22405");
        assertThat(metadata.abstractText()).isEqualTo("Diagnostic evidence");
        assertThat(metadata.referencedOpenAlexIds()).containsExactly("W1");
        server.verify();
    }
}

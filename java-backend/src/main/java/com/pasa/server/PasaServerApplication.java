package com.pasa.server;

import com.pasa.server.config.PasaProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(PasaProperties.class)
public class PasaServerApplication {
    public static void main(String[] args) {
        SpringApplication.run(PasaServerApplication.class, args);
    }
}


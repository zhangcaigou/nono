package com.pasa.server.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.pasa.server.api.ApiModels;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.regex.Matcher;

@Component
public class QueryConstraintParser {
    private static final Pattern EXCLUSION = Pattern.compile(
            "(?i)(排除|不包括|不包含|不能|不得|不要|避免|除外|exclude|excluding|without|must not|do not)");
    private static final Pattern SOFT = Pattern.compile(
            "(?i)(优先|最好|尽量|偏好|prefer|preferably|ideally|nice to have)");
    private static final Pattern OUTPUT = Pattern.compile(
            "(?i)(比较|对比|区别|差异|联系|关系|总结|列出|分析|compare|comparison|contrast|difference|relationship|summarize|list)");
    private static final Pattern LEADING_REQUEST = Pattern.compile(
            "(?i)^(请|请帮我|帮我|寻找|查找|检索|推荐|找出|find|search for|recommend|show me)\\s*");
    private static final Pattern SINCE_YEAR = Pattern.compile("((?:19|20)\\d{2})\\s*年?\\s*(以来|以后|之后|起|至今)");
    private static final Pattern USE_FOR = Pattern.compile("(?:使用|采用|运用)\\s*([^，,。；;]{2,40}?)\\s*(?:进行|用于|实现)\\s*([^，,。；;]{2,50}?)(?:的?论文|研究)?$");

    public List<ApiModels.QueryConstraint> parse(String query, LocalDate endDate) {
        List<String> clauses = split(query);
        List<ApiModels.QueryConstraint> constraints = new ArrayList<>();
        int index = 1;
        for (String clause : clauses) {
            String cleaned = LEADING_REQUEST.matcher(clause.strip()).replaceFirst("").strip();
            if (cleaned.isBlank()) {
                continue;
            }
            Matcher useFor = USE_FOR.matcher(cleaned);
            if (useFor.find()) {
                String method = useFor.group(1).replaceAll("^.*?((?:19|20)\\d{2}年?(?:以来|以后|之后|起|至今))", "").strip();
                String task = useFor.group(2).replaceAll("的?论文$", "").strip();
                if (!task.isBlank()) {
                    constraints.add(constraint(index++, "hard", "研究" + task, clause));
                }
                if (!method.isBlank()) {
                    constraints.add(constraint(index++, "hard", "使用" + method, clause));
                }
            } else {
                constraints.add(constraint(index++, classify(cleaned), cleaned, clause));
            }
            Matcher year = SINCE_YEAR.matcher(cleaned);
            if (year.find()) {
                constraints.add(constraint(index++, "hard", year.group(), year.group()));
            }
        }
        if (endDate != null && constraints.stream().noneMatch(item -> containsDate(item.text(), endDate))) {
            String text = "发表日期不晚于 " + endDate;
            constraints.add(constraint(index, "hard", text, text));
        }
        return List.copyOf(constraints);
    }

    public List<ApiModels.QueryConstraint> parseAnalysis(
            JsonNode analysis,
            String query,
            LocalDate endDate
    ) {
        JsonNode understanding = analysis == null ? null : analysis.path("query_understanding");
        if (understanding == null || !understanding.isObject() || understanding.isEmpty()) {
            return parse(query, endDate);
        }

        List<ConstraintValue> values = new ArrayList<>();
        addValue(values, "hard", understanding.path("research_intent").asText(""), query);
        addArray(values, "hard", understanding.path("hard_constraints"), query);
        addArray(values, "soft", understanding.path("soft_constraints"), query);
        addArray(values, "exclusion", understanding.path("exclusions"), query);
        if (OUTPUT.matcher(query).find()) {
            addArray(values, "output", understanding.path("comparison_dimensions"), query);
        }

        Set<String> seen = new LinkedHashSet<>();
        List<ApiModels.QueryConstraint> constraints = new ArrayList<>();
        int index = 1;
        for (ConstraintValue value : values) {
            String key = value.type() + ":" + value.description().toLowerCase(Locale.ROOT)
                    .replaceAll("[\\s，。；;,.]+", "");
            if (!value.description().isBlank() && seen.add(key)) {
                constraints.add(constraint(index++, value.type(), value.description(), value.originalText()));
            }
        }
        if (constraints.isEmpty()) {
            return parse(query, endDate);
        }
        if (endDate != null && constraints.stream().noneMatch(item -> containsDate(item.text(), endDate))) {
            String text = "发表日期不晚于 " + endDate;
            constraints.add(constraint(index, "hard", text, text));
        }
        return List.copyOf(constraints);
    }

    private static void addArray(
            List<ConstraintValue> target,
            String type,
            JsonNode values,
            String originalText
    ) {
        if (values == null || !values.isArray()) {
            return;
        }
        values.forEach(value -> addValue(target, type, value.asText(""), originalText));
    }

    private static void addValue(
            List<ConstraintValue> target,
            String type,
            String description,
            String originalText
    ) {
        String cleaned = description == null ? "" : description.strip();
        if (!cleaned.isBlank()) {
            target.add(new ConstraintValue(type, cleaned, originalText));
        }
    }

    private static ApiModels.QueryConstraint constraint(int index, String importance, String description,
                                                         String originalText) {
        return new ApiModels.QueryConstraint("C" + index, importance, description,
                importance, description, originalText);
    }

    private static List<String> split(String query) {
        if (query == null || query.isBlank()) {
            return List.of();
        }
        Set<String> clauses = new LinkedHashSet<>();
        for (String part : query.replace('\r', '\n').split("[\\n。；;!?！？，,]+")) {
            String cleaned = part.replaceAll("\\s+", " ").strip();
            if (!cleaned.isBlank()) {
                clauses.add(cleaned);
            }
        }
        return clauses.stream().limit(12).toList();
    }

    private static String classify(String clause) {
        if (EXCLUSION.matcher(clause).find()) {
            return "exclusion";
        }
        if (SOFT.matcher(clause).find()) {
            return "soft";
        }
        if (OUTPUT.matcher(clause).find()) {
            return "output";
        }
        return "hard";
    }

    private static boolean containsDate(String text, LocalDate date) {
        String lower = text.toLowerCase(Locale.ROOT);
        return lower.contains(date.toString()) || lower.contains(Integer.toString(date.getYear()));
    }

    private record ConstraintValue(String type, String description, String originalText) {}
}

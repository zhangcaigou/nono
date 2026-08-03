package com.pasa.server.service;

import com.pasa.server.api.ApiModels;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

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

    public List<ApiModels.QueryConstraint> parse(String query, LocalDate endDate) {
        List<String> clauses = split(query);
        List<ApiModels.QueryConstraint> constraints = new ArrayList<>();
        int index = 1;
        for (String clause : clauses) {
            String cleaned = LEADING_REQUEST.matcher(clause.strip()).replaceFirst("").strip();
            if (cleaned.isBlank()) {
                continue;
            }
            constraints.add(new ApiModels.QueryConstraint("C" + index++, classify(cleaned), cleaned));
        }
        if (endDate != null && constraints.stream().noneMatch(item -> containsDate(item.text(), endDate))) {
            constraints.add(new ApiModels.QueryConstraint("C" + index, "hard", "发表日期不晚于 " + endDate));
        }
        return List.copyOf(constraints);
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
}

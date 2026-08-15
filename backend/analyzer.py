from __future__ import annotations

import json
import logging
import re
import math
import hashlib
from collections import OrderedDict
from itertools import combinations
from typing import Any

from backend.config import Settings
from backend.schemas import (
    AnalysisTheme,
    ModelSearchResponse,
    PaperAnalysis,
    QueryUnderstanding,
    SearchAnalysis,
    SearchSynthesis,
    SemanticRelation,
)


_WORD = re.compile(r"[a-z0-9][a-z0-9+.#-]{1,}|[\u3400-\u9fff]{2,}", re.IGNORECASE)
_RELATION_TYPES = {
    "same_method", "extends_method", "same_task", "same_dataset",
    "compares_with", "contradicts", "survey_of",
}
_STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "using", "based", "into",
    "paper", "study", "method", "methods", "results", "approach", "model", "models",
    "研究", "论文", "方法", "结果", "模型", "基于", "使用", "提出",
}
log = logging.getLogger(__name__)


def _extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response does not contain a JSON object")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response JSON must be an object")
    return value


def _tokens(text: str) -> set[str]:
    result: set[str] = set()
    for match in _WORD.findall(text.lower()):
        if match in _STOP_WORDS:
            continue
        if re.fullmatch(r"[\u3400-\u9fff]+", match):
            result.update(match[index:index + 2] for index in range(len(match) - 1))
        elif len(match) > 2:
            result.add(match)
    return result


def candidate_pairs(papers: list[Any], limit: int) -> list[tuple[Any, Any]]:
    """Select likely-related pairs before asking the LLM; avoids an O(N²) model workload."""
    scored: list[tuple[float, Any, Any]] = []
    token_sets = {
        paper.paper_id: _tokens(f"{paper.title} {paper.abstract}")
        for paper in papers
    }
    for left, right in combinations(papers, 2):
        left_tokens, right_tokens = token_sets[left.paper_id], token_sets[right.paper_id]
        shared = left_tokens & right_tokens
        if not shared:
            continue
        score = len(shared) / max(1, len(left_tokens | right_tokens))
        scored.append((score, left, right))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [(left, right) for _, left, right in scored[:limit]]


def _valid_quote(quote: str, paper: Any) -> bool:
    normalized_quote = " ".join(quote.split()).lower()
    source = " ".join(f"{paper.title} {paper.abstract}".split()).lower()
    return bool(normalized_quote) and normalized_quote in source


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _paper_score(paper: Any) -> float:
    value = getattr(paper, "selector_score", None)
    if value is None:
        value = getattr(paper, "score", 0.5)
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _calibrated_relation_confidence(
    model_confidence: float,
    left: Any,
    right: Any,
    evidence_from: str,
    evidence_to: str,
) -> float:
    """Blend the model judgment with pair-specific continuous evidence features."""
    content_similarity = _jaccard(
        _tokens(f"{left.title} {left.abstract}"),
        _tokens(f"{right.title} {right.abstract}"),
    )
    evidence_similarity = _jaccard(_tokens(evidence_from), _tokens(evidence_to))
    pair_relevance = (_paper_score(left) + _paper_score(right)) / 2
    calibrated = (
        0.25
        + 0.40 * model_confidence
        + 0.15 * content_similarity
        + 0.10 * evidence_similarity
        + 0.10 * pair_relevance
    )
    return min(0.99, max(0.0, calibrated))


class SearchResultAnalyzer:
    def __init__(self, agent: Any, settings: Settings) -> None:
        self.agent = agent
        self.settings = settings
        self.cache: OrderedDict[str, SearchAnalysis] = OrderedDict()

    def analyze(self, query: str, result: ModelSearchResponse) -> SearchAnalysis | None:
        if not self.settings.analysis_enabled:
            return None
        papers = [paper for paper in result.papers if paper.selected][:self.settings.analysis_top_n]
        if not papers:
            return None
        cache_value = query + "|" + "|".join(
            f"{paper.paper_id}:{paper.title}:{paper.abstract}" for paper in papers
        )
        cache_key = hashlib.sha256(cache_value.encode("utf-8")).hexdigest()
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.cache.move_to_end(cache_key)
            return cached
        try:
            try:
                query_understanding = self._analyze_query(query)
            except Exception as exc:
                log.warning("Query analysis failed; using original intent: %s", type(exc).__name__)
                query_understanding = QueryUnderstanding(
                    research_intent=query,
                    sub_questions=[query],
                    comparison_dimensions=["方法", "主要发现", "贡献", "局限性"],
                )
            try:
                paper_analyses = self._analyze_papers(query, papers)
            except Exception as exc:
                log.warning("Paper batch analysis failed: %s", type(exc).__name__)
                paper_analyses = []
            try:
                synthesis = self._synthesize(query, query_understanding, paper_analyses, papers)
            except Exception as exc:
                log.warning("Search synthesis failed: %s", type(exc).__name__)
                synthesis = SearchSynthesis(
                    overview="综合生成暂不可用；论文检索与原始证据仍可正常查看。",
                    comparison_dimensions=query_understanding.comparison_dimensions,
                )
            try:
                relations = self._analyze_relations(query, papers)
            except Exception as exc:
                log.warning("Semantic relation analysis failed: %s", type(exc).__name__)
                relations = []
            pair_count = len(candidate_pairs(papers, self.settings.analysis_pair_limit))
            analysis = SearchAnalysis(
                query_understanding=query_understanding,
                paper_analyses=paper_analyses,
                synthesis=synthesis,
                semantic_relations=relations,
                analyzed_paper_count=len(paper_analyses),
                estimated_model_calls=2 + math.ceil(len(papers) / self.settings.analysis_batch_size)
                    + (1 if pair_count else 0),
                candidate_pair_count=pair_count,
                possible_pair_count=len(papers) * (len(papers) - 1) // 2,
            )
            self.cache[cache_key] = analysis
            self.cache.move_to_end(cache_key)
            while len(self.cache) > self.settings.analysis_cache_max_entries:
                self.cache.popitem(last=False)
            return analysis
        except Exception as exc:
            # Analysis is optional enrichment: retrieval results must remain available on any LLM/JSON failure.
            log.warning("Search result analysis failed: %s", type(exc).__name__)
            return None

    def _analyze_query(self, query: str) -> QueryUnderstanding:
        prompt = f"""Analyze this scholarly search request. Return JSON only, in the user's language.
Query: {query}
Schema: {{"research_intent":"", "entities":[], "methods":[], "domains":[], "datasets":[],
"hard_constraints":[], "soft_constraints":[], "exclusions":[], "sub_questions":[],
"comparison_dimensions":[]}}
Identify meaning, not merely punctuation. Do not invent constraints."""
        value = _extract_json(self.agent.infer(prompt))
        return QueryUnderstanding.model_validate(value)

    def _analyze_papers(self, query: str, papers: list[Any]) -> list[PaperAnalysis]:
        prompts = []
        for paper in papers:
            abstract = paper.abstract[:self.settings.analysis_abstract_chars]
            prompts.append(f"""Analyze one paper against the user query. Return JSON only, in the user's language.
User query: {query}
paper_id: {paper.paper_id}
Title: {paper.title}
Abstract: {abstract}
Schema: {{"paper_id":"{paper.paper_id}", "relevance_level":"high|partial|low",
"one_sentence_summary":"", "research_problem":"", "methodology":[], "datasets":[],
"key_findings":[], "contributions":[], "limitations":[], "evidence":[]}}
Every evidence item must be an exact quote from the title or abstract. If information is absent, use an empty list;
never infer experimental findings or limitations that are not stated.""")
        responses = self.agent.batch_infer(
            prompts,
            batch_size=self.settings.analysis_batch_size,
            max_new_tokens=512,
        )
        analyses: list[PaperAnalysis] = []
        by_id = {paper.paper_id: paper for paper in papers}
        for expected, response in zip(papers, responses):
            try:
                value = _extract_json(response)
                value["paper_id"] = expected.paper_id
                analysis = PaperAnalysis.model_validate(value)
                analysis.evidence = [
                    quote for quote in analysis.evidence
                    if _valid_quote(quote, by_id[analysis.paper_id])
                ][:5]
                analyses.append(analysis)
            except Exception:
                continue
        return analyses

    def _synthesize(
        self,
        query: str,
        understanding: QueryUnderstanding,
        analyses: list[PaperAnalysis],
        papers: list[Any],
    ) -> SearchSynthesis:
        compact = [analysis.model_dump() for analysis in analyses]
        prompt = f"""Synthesize a set of retrieved papers into a grounded answer. Return JSON only in the user's language.
User query: {query}
Query understanding: {understanding.model_dump_json()}
Paper analyses: {json.dumps(compact, ensure_ascii=False)}
Schema: {{"direct_answer":"", "overview":"", "themes":[{{"theme_id":"T1","name":"","summary":"","paper_ids":[]}}],
"consensus":[], "disagreements":[], "research_gaps":[], "recommended_reading_order":[],
"comparison_dimensions":[]}}
Only use supplied analyses. State uncertainty when evidence is insufficient. Do not claim consensus from one paper."""
        synthesis = SearchSynthesis.model_validate(_extract_json(self.agent.infer(prompt, max_new_tokens=768)))
        allowed = {paper.paper_id for paper in papers}
        synthesis.themes = [
            AnalysisTheme(
                theme_id=theme.theme_id,
                name=theme.name,
                summary=theme.summary,
                paper_ids=[paper_id for paper_id in theme.paper_ids if paper_id in allowed],
            )
            for theme in synthesis.themes
            if theme.name
        ]
        synthesis.recommended_reading_order = [
            paper_id for paper_id in synthesis.recommended_reading_order if paper_id in allowed
        ]
        return synthesis

    def _analyze_relations(self, query: str, papers: list[Any]) -> list[SemanticRelation]:
        pairs = candidate_pairs(papers, self.settings.analysis_pair_limit)
        if not pairs:
            return []
        pair_payload = []
        for left, right in pairs:
            pair_payload.append({
                "from_paper_id": left.paper_id,
                "from_title": left.title,
                "from_abstract": left.abstract[:900],
                "to_paper_id": right.paper_id,
                "to_title": right.title,
                "to_abstract": right.abstract[:900],
            })
        prompt = f"""Judge semantic relationships only for these prefiltered paper pairs. Return JSON only.
User query: {query}
Candidate pairs: {json.dumps(pair_payload, ensure_ascii=False)}
Schema: {{"relations":[{{"from_paper_id":"", "to_paper_id":"", "type":"same_method|extends_method|same_task|same_dataset|compares_with|contradicts|survey_of", "description":"", "evidence_from":"", "evidence_to":"", "confidence":0.0}}]}}
Evidence must be exact title/abstract quotes from both papers. Omit a pair if the relation cannot be supported.
Do not infer citation relationships."""
        raw = _extract_json(self.agent.infer(prompt, max_new_tokens=768)).get("relations", [])
        allowed_pairs = {(left.paper_id, right.paper_id): (left, right) for left, right in pairs}
        relations: list[SemanticRelation] = []
        for value in raw if isinstance(raw, list) else []:
            if not isinstance(value, dict):
                continue
            key = (str(value.get("from_paper_id", "")), str(value.get("to_paper_id", "")))
            pair = allowed_pairs.get(key)
            relation_type = str(value.get("type", ""))
            if pair is None or relation_type not in _RELATION_TYPES:
                continue
            left, right = pair
            evidence_from, evidence_to = str(value.get("evidence_from", "")), str(value.get("evidence_to", ""))
            if not _valid_quote(evidence_from, left) or not _valid_quote(evidence_to, right):
                continue
            try:
                model_confidence = min(1.0, max(0.0, float(value.get("confidence", 0.7))))
            except (TypeError, ValueError):
                model_confidence = 0.7
            confidence = _calibrated_relation_confidence(
                model_confidence, left, right, evidence_from, evidence_to
            )
            relations.append(SemanticRelation(
                relation_id=f"MLR{len(relations) + 1}",
                from_paper_id=left.paper_id,
                to_paper_id=right.paper_id,
                type=relation_type,
                description=str(value.get("description", "")),
                evidence_from=evidence_from,
                evidence_to=evidence_to,
                confidence=confidence,
            ))
        return relations


def mock_analysis(result: ModelSearchResponse) -> SearchAnalysis:
    selected = [paper for paper in result.papers if paper.selected]
    paper_analyses = [PaperAnalysis(
        paper_id=paper.paper_id,
        relevance_level="high",
        one_sentence_summary="该论文是用于接口联调的确定性高相关结果。",
        research_problem="验证学术检索结果的结构化分析展示。",
        methodology=["deterministic mock"],
        evidence=[paper.title],
    ) for paper in selected]
    return SearchAnalysis(
        query_understanding=QueryUnderstanding(
            research_intent=result.query,
            sub_questions=[result.query],
            comparison_dimensions=["方法", "主要贡献", "局限性"],
        ),
        paper_analyses=paper_analyses,
        synthesis=SearchSynthesis(
            direct_answer="已完成结构化检索与证据分析。",
            overview="这是 mock 模式的确定性综合结果。",
            themes=[AnalysisTheme(theme_id="T1", name="接口联调", paper_ids=[p.paper_id for p in selected])],
            recommended_reading_order=[p.paper_id for p in selected],
            comparison_dimensions=["方法", "主要贡献", "局限性"],
        ),
        analyzed_paper_count=len(paper_analyses),
        model="mock",
        estimated_model_calls=0,
        candidate_pair_count=0,
        possible_pair_count=len(selected) * (len(selected) - 1) // 2,
    )

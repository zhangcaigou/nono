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
_CHINESE = re.compile(r"[\u3400-\u9fff]")
_RELATION_TYPES = {
    "same_method", "extends_method", "same_task", "same_dataset",
    "compares_with", "contradicts", "survey_of",
}
_STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "using", "based", "into",
    "paper", "study", "method", "methods", "results", "approach", "model", "models",
    "abstract", "also", "are", "between", "both", "can", "demonstrate", "has", "have",
    "introduce", "its", "may", "our", "present", "propose", "show", "such", "their",
    "these", "those", "through", "various", "was", "were", "which", "within",
    "研究", "论文", "方法", "结果", "模型", "基于", "使用", "提出",
}
_METHOD_MARKERS = (
    "we propose", "we present", "we introduce", "we develop", "we design", "our method",
    "our approach", "our framework", "framework", "architecture", "pipeline", "algorithm",
    "using", "based on", "leverag", "通过", "采用", "提出", "设计", "构建", "框架",
)
_FINDING_MARKERS = (
    "outperform", "achieve", "improve", "results show", "experiments show", "demonstrate",
    "effective", "superior", "state-of-the-art", "sota", "提升", "优于", "实验表明", "结果表明",
)
_CONTRIBUTION_MARKERS = (
    "we propose", "we present", "we introduce", "we develop", "novel", "first", "contribution",
    "enable", "提出", "首次", "创新", "贡献", "实现",
)
_LIMITATION_MARKERS = (
    "limitation", "however", "remain challenging", "fails to", "restricted to", "requires",
    "expensive", "局限", "然而", "仍然困难", "依赖", "仅适用",
)
_THEME_RULES = (
    ("生成式建模与扩散方法", "Generative and diffusion methods", ("diffusion", "generative", "autoregressive", "text-to-image")),
    ("几何、深度与视觉先验", "Geometry, depth, and visual priors", ("depth", "geometry", "monocular", "camera pose", "geometric")),
    ("弱监督与数据高效学习", "Weakly supervised and data-efficient learning", ("unsupervised", "self-supervised", "few-shot", "single image", "sparse view")),
    ("多模态表示与预训练", "Multimodal representation and pre-training", ("multimodal", "audio-visual", "vision-language", "pre-training", "foundation model")),
    ("强化学习与智能体训练", "Reinforcement learning and agent training", ("reinforcement learning", "rlhf", "agent", "policy optimization")),
    ("大语言模型训练与扩展", "Large language model training and scaling", ("large language model", "llm", "language model pretraining", "scaling law", "instruction tuning")),
    ("对齐、安全与价值学习", "Alignment, safety, and preference learning", ("alignment", "preference optimization", "dpo", "reward model", "constitutional ai", "ai safety")),
    ("推理、规划与问题求解", "Reasoning, planning, and problem solving", ("chain-of-thought", "reasoning", "planning", "problem solving", "tree of thoughts")),
    ("工具使用与智能体协作", "Tool use and multi-agent collaboration", ("tool use", "multi-agent", "agentic", "function calling", "web agent")),
    ("代码生成与软件工程", "Code generation and software engineering", ("code generation", "program synthesis", "software engineering", "code repair", "repository-level")),
    ("检索、排序与知识增强", "Retrieval, ranking, and knowledge augmentation", ("retrieval", "ranking", "knowledge graph", "rag", "search")),
    ("自然语言理解与生成", "Natural language understanding and generation", ("natural language processing", "text generation", "machine translation", "question answering", "summarization")),
    ("信息抽取与文本挖掘", "Information extraction and text mining", ("named entity recognition", "relation extraction", "information extraction", "text mining", "sentiment analysis")),
    ("知识图谱与图推理", "Knowledge graphs and graph reasoning", ("knowledge graph", "graph reasoning", "link prediction", "graph embedding")),
    ("图神经网络与图学习", "Graph neural networks and graph learning", ("graph neural network", "graph convolution", "graph attention", "gnn", "graph learning")),
    ("图像识别与视觉理解", "Image recognition and visual understanding", ("image classification", "object detection", "semantic segmentation", "visual recognition", "computer vision")),
    ("视频理解与视频生成", "Video understanding and generation", ("video generation", "video understanding", "action recognition", "video prediction", "text-to-video")),
    ("语音、音频与音乐智能", "Speech, audio, and music intelligence", ("speech recognition", "speech synthesis", "audio generation", "music generation", "speaker recognition")),
    ("三维重建与神经表示", "3D reconstruction and neural representations", ("nerf", "radiance field", "3d reconstruction", "novel view", "neural field")),
    ("点云与三维视觉", "Point clouds and 3D vision", ("point cloud", "3d detection", "3d segmentation", "mesh reconstruction", "lidar")),
    ("机器人学习与具身智能", "Robot learning and embodied intelligence", ("robot learning", "embodied ai", "robot manipulation", "navigation", "vision-language-action")),
    ("自动驾驶与智能交通", "Autonomous driving and intelligent transportation", ("autonomous driving", "self-driving", "traffic prediction", "vehicle trajectory", "driving policy")),
    ("推荐系统与用户建模", "Recommender systems and user modeling", ("recommender system", "recommendation", "collaborative filtering", "user modeling", "click-through rate")),
    ("时间序列与时空预测", "Time-series and spatiotemporal forecasting", ("time series", "forecasting", "temporal prediction", "spatiotemporal", "anomaly detection")),
    ("因果推断与反事实学习", "Causal inference and counterfactual learning", ("causal inference", "causal discovery", "counterfactual", "treatment effect", "causality")),
    ("迁移学习与领域泛化", "Transfer learning and domain generalization", ("transfer learning", "domain adaptation", "domain generalization", "distribution shift", "out-of-domain")),
    ("持续学习、元学习与适应", "Continual, meta, and adaptive learning", ("continual learning", "lifelong learning", "meta-learning", "online learning", "catastrophic forgetting")),
    ("模型压缩与高效推理", "Model compression and efficient inference", ("quantization", "knowledge distillation", "model pruning", "efficient inference", "low-rank adaptation", "lora")),
    ("分布式与联邦学习", "Distributed and federated learning", ("federated learning", "distributed training", "decentralized learning", "split learning")),
    ("隐私保护与可信学习", "Privacy-preserving and trustworthy learning", ("differential privacy", "privacy-preserving", "machine unlearning", "robustness", "adversarial attack")),
    ("可解释性与模型分析", "Interpretability and model analysis", ("interpretability", "explainable ai", "mechanistic interpretability", "feature attribution", "model analysis")),
    ("数据质量与合成数据", "Data quality and synthetic data", ("data quality", "data pruning", "dataset distillation", "synthetic data", "data augmentation", "deduplication")),
    ("评测基准与能力测量", "Benchmarks and capability evaluation", ("benchmark", "evaluation framework", "capability evaluation", "leaderboard", "evaluation metric")),
    ("量子计算与量子机器学习", "Quantum computing and quantum machine learning", ("quantum computing", "quantum circuit", "quantum machine learning", "variational quantum")),
    ("优化算法与搜索策略", "Optimization algorithms and search strategies", ("optimization", "gradient descent", "bayesian optimization", "evolutionary algorithm", "hyperparameter")),
    ("概率建模与不确定性", "Probabilistic modeling and uncertainty", ("probabilistic model", "bayesian", "uncertainty estimation", "calibration", "gaussian process")),
    ("数据库与数据管理", "Databases and data management", ("database", "query optimization", "data management", "transaction processing", "data system")),
    ("计算机系统与云边协同", "Computer systems and cloud-edge computing", ("distributed system", "cloud computing", "edge computing", "operating system", "resource scheduling")),
    ("网络通信与物联网", "Networking, communications, and IoT", ("computer network", "wireless network", "internet of things", "iot", "network protocol")),
    ("网络安全与恶意行为检测", "Cybersecurity and malicious-behavior detection", ("cybersecurity", "malware", "intrusion detection", "vulnerability", "phishing")),
    ("人机交互与用户体验", "Human-computer interaction and user experience", ("human-computer interaction", "user experience", "human-ai interaction", "usability", "interactive system")),
    ("计算生物学与医疗智能", "Computational biology and medical AI", ("medical imaging", "clinical", "drug discovery", "protein", "genomics", "healthcare")),
    ("遥感、地理空间与环境智能", "Remote sensing, geospatial, and environmental AI", ("remote sensing", "satellite", "geospatial", "earth observation", "climate", "weather")),
    ("金融智能与风险建模", "Financial intelligence and risk modeling", ("financial", "stock prediction", "credit risk", "portfolio", "fraud detection")),
    ("教育智能与个性化学习", "AI in education and personalized learning", ("education", "student modeling", "personalized learning", "intelligent tutoring", "knowledge tracing")),
    ("理论计算与算法分析", "Theoretical computing and algorithm analysis", ("computational complexity", "approximation algorithm", "online algorithm", "theoretical analysis", "algorithmic")),
    ("Transformer 与注意力架构", "Transformer and attention architectures", ("transformer", "self-attention", "attention mechanism", "vision transformer")),
)
_DYNAMIC_THEME_STOP_WORDS = _STOP_WORDS | {
    "learning", "neural", "network", "networks", "large", "language", "towards", "via",
    "new", "novel", "analysis", "system", "systems", "framework", "task", "tasks",
}


def _has_chinese(value: str) -> bool:
    return bool(_CHINESE.search(str(value or "")))


def _zh_text(value: str, fallback: str) -> str:
    value = str(value or "").strip()
    return value if _has_chinese(value) else fallback


def _zh_list(values: list[str], fallback: str) -> list[str]:
    values = [str(value).strip() for value in values if str(value).strip()]
    chinese_values = [value for value in values if _has_chinese(value)]
    return chinese_values or ([fallback] if values else [])


def _fallback_query_understanding(query: str) -> QueryUnderstanding:
    lowered = query.lower()
    matched_methods = list(dict.fromkeys(
        marker
        for _chinese_name, _english_name, markers in _THEME_RULES
        for marker in markers
        if marker in lowered
    ))[:12]
    matched_domains = list(dict.fromkeys(
        chinese_name
        for chinese_name, english_name, markers in _THEME_RULES
        if any(marker in lowered for marker in markers)
    ))[:8]
    exclusions = []
    exclusion_patterns = (
        r"(?:exclude|excluding|without|not include)\s+([^.;,]+)",
        r"(?:排除|不包括|不包含|不要)\s*([^，。；]+)",
    )
    for pattern in exclusion_patterns:
        exclusions.extend(match.strip() for match in re.findall(pattern, query, re.IGNORECASE))
    if re.search(r"(?:非|不是)(?:综述|survey|review)", lowered):
        exclusions.append("综述论文")
    exclusions = list(dict.fromkeys(item for item in exclusions if item))[:8]

    hard_constraints = []
    hard_constraints.extend(re.findall(
        r"(?<!\d)(?:19|20)\d{2}(?:\s*[-–—]\s*(?:19|20)\d{2})?(?!\d)", query
    ))
    venue_match = re.findall(
        r"\b(?:NeurIPS|ICML|ICLR|ACL|EMNLP|CVPR|ICCV|ECCV|AAAI|IJCAI|KDD|SIGIR|WWW)\b",
        query, re.IGNORECASE,
    )
    hard_constraints.extend(venue_match)
    hard_constraints = list(dict.fromkeys(hard_constraints))

    datasets = list(dict.fromkeys(
        match.strip()
        for match in re.findall(r"\b([A-Za-z0-9_-]+\s+(?:dataset|benchmark|corpus))\b", query, re.IGNORECASE)
    ))[:8]
    quoted = [value.strip() for value in re.findall(r"[\"“”']([^\"“”']{2,80})[\"“”']", query)]

    clauses = [
        clause.strip(" ,，。；;")
        for clause in re.split(r"[。；;]|\b(?:and|while|but)\b|并且|同时|以及|但", query, flags=re.IGNORECASE)
        if len(clause.strip(" ,，。；;")) >= 6
    ]
    sub_questions = list(dict.fromkeys(clauses))[:5] or [query]
    dimensions = []
    dimension_rules = (
        (("method", "approach", "方法", "技术"), "方法"),
        (("performance", "accuracy", "效果", "性能", "精度"), "性能"),
        (("efficien", "latency", "cost", "效率", "延迟", "成本"), "效率与成本"),
        (("dataset", "data", "数据集", "数据"), "数据"),
        (("contribution", "贡献", "创新"), "贡献"),
    )
    for markers, label in dimension_rules:
        if any(marker in lowered for marker in markers):
            dimensions.append(label)
    dimensions.extend(["主要发现", "局限性"])

    return QueryUnderstanding(
        research_intent=query if _has_chinese(query) else f"检索与“{query}”相关的学术论文",
        entities=list(dict.fromkeys(quoted))[:8],
        methods=matched_methods,
        domains=matched_domains,
        datasets=datasets,
        hard_constraints=hard_constraints,
        exclusions=exclusions,
        sub_questions=sub_questions,
        comparison_dimensions=list(dict.fromkeys(dimensions)),
    )


def _normalize_query_understanding_zh(
    understanding: QueryUnderstanding, query: str
) -> QueryUnderstanding:
    understanding.research_intent = _zh_text(
        understanding.research_intent,
        query if _has_chinese(query) else f"检索与“{query}”相关的学术论文",
    )
    domain_names = {
        english: chinese for chinese, english, _markers in _THEME_RULES
    }
    understanding.domains = [domain_names.get(value, value) for value in understanding.domains]
    dimension_names = {
        "method": "方法", "methodology": "方法", "performance": "性能",
        "accuracy": "精度", "efficiency": "效率", "cost": "成本",
        "data": "数据", "dataset": "数据集", "contribution": "贡献",
        "main findings": "主要发现", "limitations": "局限性",
    }
    understanding.comparison_dimensions = [
        dimension_names.get(value.lower(), value)
        for value in understanding.comparison_dimensions
    ]
    understanding.sub_questions = [
        value if _has_chinese(value) else f"检索子问题：{value}"
        for value in understanding.sub_questions
    ]
    return understanding
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


def _first_evidence_sentence(paper: Any, limit: int = 240) -> str:
    abstract = " ".join(str(getattr(paper, "abstract", "") or "").split())
    abstract = re.sub(r"^abstract\s*[:.-]?\s*", "", abstract, flags=re.IGNORECASE)
    if not abstract:
        return str(getattr(paper, "title", "") or "")
    match = re.search(r"^.{1,%d}?(?:[.!?。！？](?:\s|$)|$)" % limit, abstract)
    return match.group(0).strip() if match else abstract[:limit].strip()


def _abstract_sentences(paper: Any, limit: int = 260) -> list[str]:
    abstract = " ".join(str(getattr(paper, "abstract", "") or "").split())
    abstract = re.sub(r"^abstract\s*[:.-]?\s*", "", abstract, flags=re.IGNORECASE)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。！？])\s+", abstract)
        if len(sentence.strip()) >= 24
    ]
    shortened = []
    for sentence in sentences:
        if len(sentence) <= limit:
            shortened.append(sentence)
            continue
        boundary = sentence.rfind(" ", 0, limit - 1)
        shortened.append(sentence[:boundary if boundary > limit // 2 else limit].rstrip() + "…")
    return shortened


def _sentences_with_markers(sentences: list[str], markers: tuple[str, ...], limit: int = 2) -> list[str]:
    selected = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(marker in lowered for marker in markers):
            selected.append(sentence)
        if len(selected) >= limit:
            break
    return selected


def _fallback_paper_analysis(paper: Any) -> PaperAnalysis:
    evidence = _first_evidence_sentence(paper)
    sentences = _abstract_sentences(paper)
    title = str(getattr(paper, "title", "") or "")
    score = _paper_score(paper)
    methodology = _sentences_with_markers(sentences, _METHOD_MARKERS)
    findings = _sentences_with_markers(sentences, _FINDING_MARKERS)
    contributions = _sentences_with_markers(sentences, _CONTRIBUTION_MARKERS)
    limitations = _sentences_with_markers(sentences, _LIMITATION_MARKERS, 1)
    return PaperAnalysis(
        paper_id=paper.paper_id,
        relevance_level="high" if score >= 0.8 else "partial",
        one_sentence_summary=f"该论文围绕《{title}》所指向的研究任务展开，具体依据见标题与摘要原文。",
        research_problem=f"研究《{title}》所涉及的核心问题。",
        methodology=["摘要介绍了论文采用的方法或技术路线，具体表述见原文证据。"] if methodology else [],
        # Dataset names may stay in their original language, but an extracted English
        # abstract sentence is evidence rather than Chinese-facing analysis.
        datasets=[],
        key_findings=["摘要报告了该方法的实验结果或性能表现，具体结论见原文证据。"] if findings else [],
        contributions=["摘要陈述了论文的方法贡献或创新点，具体内容见原文证据。"] if contributions else [],
        limitations=["摘要提及了适用条件或局限，具体表述见原文证据。"] if limitations else [],
        evidence=list(dict.fromkeys(
            item for item in [evidence, *methodology, *findings, *contributions] if item
        ))[:5],
    )


def _normalize_paper_analysis_zh(analysis: PaperAnalysis, paper: Any) -> PaperAnalysis:
    """Keep paper entities/evidence verbatim while guaranteeing Chinese-facing analysis."""
    title = str(getattr(paper, "title", "") or "")
    analysis.one_sentence_summary = _zh_text(
        analysis.one_sentence_summary,
        f"该论文围绕《{title}》所指向的研究任务展开。",
    )
    analysis.research_problem = _zh_text(
        analysis.research_problem,
        f"研究《{title}》所涉及的核心问题。",
    )
    analysis.methodology = _zh_list(
        analysis.methodology, "摘要介绍了论文采用的方法或技术路线。"
    )
    analysis.key_findings = _zh_list(
        analysis.key_findings, "摘要报告了相应的实验结果或性能表现。"
    )
    analysis.contributions = _zh_list(
        analysis.contributions, "摘要陈述了论文的方法贡献或创新点。"
    )
    analysis.limitations = _zh_list(
        analysis.limitations, "摘要提及了方法的适用条件或局限。"
    )
    analysis.datasets = [
        value for value in analysis.datasets
        if len(str(value).split()) <= 8 and len(str(value)) <= 80
    ]
    return analysis


def _fallback_themes(
    query: str, papers: list[Any], analyses: list[PaperAnalysis]
) -> list[AnalysisTheme]:
    rule_members: dict[int, list[Any]] = {}
    remaining = []
    for paper in papers:
        title = str(paper.title).lower()
        abstract = str(paper.abstract).lower()
        scored_rules = []
        for rule_index, (_chinese_name, _english_name, markers) in enumerate(_THEME_RULES):
            score = sum(
                (4 * title.count(marker) + min(3, abstract.count(marker)))
                * (1 + 0.15 * max(0, len(marker.split()) - 1))
                for marker in markers
            )
            if score > 0:
                scored_rules.append((score, rule_index))
        if not scored_rules:
            remaining.append(paper)
            continue
        _, rule_index = max(scored_rules, key=lambda item: (item[0], -item[1]))
        rule_members.setdefault(rule_index, []).append(paper)

    grouped: list[tuple[str, list[Any]]] = []
    for rule_index, members in rule_members.items():
        chinese_name, _english_name, _markers = _THEME_RULES[rule_index]
        grouped.append((chinese_name, members))

    dynamic_clusters: list[list[Any]] = []
    dynamic_terms: list[set[str]] = []
    for paper in remaining:
        terms = {
            token for token in _tokens(str(paper.title))
            if token not in _DYNAMIC_THEME_STOP_WORDS
        }
        best_index, best_similarity = -1, 0.0
        for index, existing in enumerate(dynamic_terms):
            similarity = _jaccard(terms, existing)
            if similarity > best_similarity:
                best_index, best_similarity = index, similarity
        if best_index >= 0 and best_similarity >= 0.15:
            dynamic_clusters[best_index].append(paper)
            dynamic_terms[best_index].update(terms)
        else:
            dynamic_clusters.append([paper])
            dynamic_terms.append(set(terms))

    for members, terms in zip(dynamic_clusters, dynamic_terms):
        frequencies: dict[str, int] = {}
        for paper in members:
            for token in _tokens(str(paper.title)):
                if token not in _DYNAMIC_THEME_STOP_WORDS:
                    frequencies[token] = frequencies.get(token, 0) + 1
        salient = sorted(
            frequencies or {token: 1 for token in terms},
            key=lambda token: (-frequencies.get(token, 1), -len(token), token),
        )[:3]
        name = "、".join(salient) + "相关研究" if salient else "专题研究路线"
        grouped.append((name, members))

    themes = []
    grouped.sort(key=lambda item: (-len(item[1]), item[0]))
    for index, (name, members) in enumerate(grouped[:6], 1):
        represented = "、".join(f"《{paper.title}》" for paper in members[:2])
        summary = f"该路线的代表工作包括{represented}，共同关注相近的研究任务或技术方向。"
        themes.append(AnalysisTheme(
            theme_id=f"T{index}", name=name, summary=summary,
            paper_ids=[paper.paper_id for paper in members],
        ))
    return themes


def _fallback_synthesis(
    query: str,
    understanding: QueryUnderstanding,
    analyses: list[PaperAnalysis],
    papers: list[Any],
) -> SearchSynthesis:
    titles = [f"《{paper.title}》" for paper in papers[:3]]
    direct_answer = "与查询最相关的优先阅读包括" + "、".join(titles) + "。"
    overview = ""
    return SearchSynthesis(
        direct_answer=direct_answer,
        overview=overview,
        themes=_fallback_themes(query, papers, analyses),
        recommended_reading_order=[paper.paper_id for paper in papers],
        comparison_dimensions=understanding.comparison_dimensions,
    )


def _fallback_relations(query: str, papers: list[Any], limit: int) -> list[SemanticRelation]:
    relations: list[SemanticRelation] = []
    query_tokens = _tokens(query)
    for left, right in candidate_pairs(papers, limit):
        left_tokens = _tokens(f"{left.title} {left.abstract}")
        right_tokens = _tokens(f"{right.title} {right.abstract}")
        shared = sorted(
            left_tokens & right_tokens,
            key=lambda token: (token not in query_tokens, -len(token), token),
        )
        similarity = _jaccard(left_tokens, right_tokens)
        if len(shared) < 2 or similarity < 0.03:
            continue
        evidence_from = str(left.title)
        evidence_to = str(right.title)
        confidence = _calibrated_relation_confidence(
            min(0.9, 0.55 + similarity), left, right, evidence_from, evidence_to
        )
        relations.append(SemanticRelation(
            relation_id=f"LXR{len(relations) + 1}",
            from_paper_id=left.paper_id,
            to_paper_id=right.paper_id,
            type="same_task",
            description="共同研究主题：" + "、".join(shared[:4]),
            evidence_from=evidence_from,
            evidence_to=evidence_to,
            confidence=confidence,
        ))
    return relations


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
        result_tree = getattr(result, "tree", {}) or {}
        raw_query_plan = ((result_tree.get("extra") or {}).get("query_plan") or {})
        try:
            planned_understanding = (
                QueryUnderstanding.model_validate(raw_query_plan) if raw_query_plan else None
            )
        except Exception:
            planned_understanding = None
        cache_value = query + "|" + json.dumps(raw_query_plan, ensure_ascii=False, sort_keys=True) + "|" + "|".join(
            f"{paper.paper_id}:{paper.title}:{paper.abstract}" for paper in papers
        )
        cache_key = hashlib.sha256(cache_value.encode("utf-8")).hexdigest()
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.cache.move_to_end(cache_key)
            return cached
        try:
            degraded = False
            if planned_understanding is not None:
                query_understanding = planned_understanding
            else:
                try:
                    query_understanding = self._analyze_query(query)
                except Exception as exc:
                    degraded = True
                    log.warning("Query analysis failed; using grounded fallback: %s", type(exc).__name__)
                    query_understanding = _fallback_query_understanding(query)
            query_understanding = _normalize_query_understanding_zh(
                query_understanding, query
            )
            try:
                paper_analyses = self._analyze_papers(query, papers)
            except Exception as exc:
                degraded = True
                log.warning("Paper batch analysis failed: %s", type(exc).__name__)
                paper_analyses = []
            analyses_by_id = {analysis.paper_id: analysis for analysis in paper_analyses}
            if len(analyses_by_id) < len(papers):
                degraded = True
                paper_analyses = [
                    analyses_by_id.get(paper.paper_id) or _fallback_paper_analysis(paper)
                    for paper in papers
                ]
            try:
                synthesis = self._synthesize(query, query_understanding, paper_analyses, papers)
            except Exception as exc:
                degraded = True
                log.warning("Search synthesis failed: %s", type(exc).__name__)
                synthesis = _fallback_synthesis(
                    query, query_understanding, paper_analyses, papers
                )
            try:
                relations = self._analyze_relations(query, papers)
            except Exception as exc:
                degraded = True
                log.warning("Semantic relation analysis failed: %s", type(exc).__name__)
                relations = _fallback_relations(query, papers, self.settings.analysis_pair_limit)
            pair_count = len(candidate_pairs(papers, self.settings.analysis_pair_limit))
            analysis = SearchAnalysis(
                query_understanding=query_understanding,
                paper_analyses=paper_analyses,
                synthesis=synthesis,
                semantic_relations=relations,
                analyzed_paper_count=len(paper_analyses),
                model=(
                    "pasa-7b-crawler+grounded-fallback"
                    if degraded else "pasa-7b-crawler"
                ),
                estimated_model_calls=(1 if planned_understanding is not None else 2)
                    + math.ceil(len(papers) / self.settings.analysis_batch_size)
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
        prompt = f"""Analyze this scholarly search request. Return JSON only.
All user-facing explanatory text MUST be written in natural Simplified Chinese, even when the query is English.
Keep named methods, datasets, venues, and paper titles in their original form when needed.
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
            prompts.append(f"""Analyze one paper against the user query. Return JSON only.
Write every analytical field in natural Simplified Chinese, including summary, research problem, methodology,
findings, contributions, and limitations. Keep paper_id, named methods/datasets and evidence quotes in their
original form. Evidence MUST remain an exact quote and must not be translated.
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
                analyses.append(_normalize_paper_analysis_zh(analysis, expected))
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
        prompt = f"""Synthesize a set of retrieved papers into a grounded answer. Return JSON only.
All summaries, route names, comparisons, consensus, disagreements, and research gaps MUST be written in
natural Simplified Chinese. Paper titles and named technical terms may remain in their original form.
User query: {query}
Query understanding: {understanding.model_dump_json()}
Paper analyses: {json.dumps(compact, ensure_ascii=False)}
Schema: {{"direct_answer":"", "overview":"", "themes":[{{"theme_id":"T1","name":"","summary":"","paper_ids":[]}}],
"consensus":[], "disagreements":[], "research_gaps":[], "recommended_reading_order":[],
"comparison_dimensions":[]}}
Only use supplied analyses. State uncertainty when evidence is insufficient. Do not claim consensus from one paper."""
        synthesis = SearchSynthesis.model_validate(_extract_json(self.agent.infer(prompt, max_new_tokens=768)))
        fallback = _fallback_synthesis(query, understanding, analyses, papers)
        synthesis.direct_answer = _zh_text(synthesis.direct_answer, fallback.direct_answer)
        synthesis.overview = _zh_text(synthesis.overview, fallback.overview)
        synthesis.consensus = [value for value in synthesis.consensus if _has_chinese(value)]
        synthesis.disagreements = [value for value in synthesis.disagreements if _has_chinese(value)]
        synthesis.research_gaps = [value for value in synthesis.research_gaps if _has_chinese(value)]
        allowed = {paper.paper_id for paper in papers}
        synthesis.themes = [
            AnalysisTheme(
                theme_id=theme.theme_id,
                name=_zh_text(theme.name, "专题研究路线"),
                summary=_zh_text(theme.summary, "该路线汇集了研究任务或技术方向相近的论文。"),
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
Write every relationship description in natural Simplified Chinese. Keep paper IDs and exact evidence quotes
in their original form; never translate evidence_from or evidence_to.
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
            relation_labels = {
                "same_method": "两篇论文采用了相近的方法或技术路线。",
                "extends_method": "后一项工作在相关方法方向上进行了扩展。",
                "same_task": "两篇论文面向相同或相近的研究任务。",
                "same_dataset": "两篇论文使用或讨论了相同的数据集。",
                "compares_with": "两篇论文的方法或结果可以进行横向比较。",
                "contradicts": "两篇论文在相关结论或观察上存在差异。",
                "survey_of": "其中一篇论文对相关研究方向进行了综述。",
            }
            relations.append(SemanticRelation(
                relation_id=f"MLR{len(relations) + 1}",
                from_paper_id=left.paper_id,
                to_paper_id=right.paper_id,
                type=relation_type,
                description=_zh_text(
                    str(value.get("description", "")), relation_labels[relation_type]
                ),
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

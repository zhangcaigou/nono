# Copyright (c) 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from paper_node import PaperNode
from models     import Agent
from datetime   import datetime
from utils      import (
    search_paper_by_title,
    google_search_arxiv_id,
    openalex_search_papers,
    search_paper_by_arxiv_id,
    search_papers_by_arxiv_ids,
    search_papers_by_title_index,
    search_section_by_arxiv_id
)

class PaperAgent:
    _chinese_pattern = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
    _query_stop_words = {
        "a", "an", "and", "are", "about", "for", "give", "in", "is", "list",
        "me", "of", "on", "paper", "papers", "provide", "research", "show", "some",
        "study", "studies", "that", "the", "to", "using", "which", "with",
    }

    @classmethod
    def contains_chinese(cls, text):
        return bool(cls._chinese_pattern.search(text))

    def __init__(
        self,
        user_query:     str,
        crawler:        Agent, # prompt(s) -> response(s)
        selector:       Agent, # prompt(s) -> score(s)
        end_date:       str = datetime.now().strftime("%Y%m%d"),
        prompts_path:   str = "agent_prompt.json",
        expand_layers:  int = 0,
        search_queries: int = 5,
        search_papers:  int = 10, # per query
        expand_papers:  int = 10, # per layer
        expand_refs_per_paper: int = 12, # citation candidates per expanded paper
        local_search_papers: int = 20, # per query from bundled title index
        selector_threshold: float = 0.5,
        threads_num:    int = 20, # number of threads in parallel at the same time
        progress_callback = None, # optional (papers_found, papers_selected) callback
        query_planner = None,     # optional query -> {queries, metrics}
    ) -> None:
        self.crawler    = crawler
        self.selector   = selector
        self.original_user_query = user_query.strip()
        self.user_query = self.original_user_query
        self.input_language = "zh" if self.contains_chinese(self.user_query) else "en"
        self.end_date   = end_date
        with open(prompts_path, encoding="utf-8") as prompts_file:
            self.prompts = json.load(prompts_file)
        self.root       = PaperNode({
            "title": self.original_user_query,
            "extra": {
                "original_user_query": self.original_user_query,
                "input_language": self.input_language,
                "generated_search_queries": [],
                "query_plan": {},
                "selector_threshold": min(1.0, max(0.0, float(selector_threshold))),
                "query_planning": {},
                "adaptive_search": {
                    "triggered": False,
                    "reason": "initial_retrieval_sufficient",
                    "queries": [],
                },
                "retrieval_stats": {
                    "serper_calls": 0,
                    "openalex_calls": 0,
                    "serper_candidates": 0,
                    "openalex_candidates": 0,
                    "local_calls": 0,
                    "local_candidates": 0,
                    "expansion_layers": [],
                    "citation_candidates": 0,
                    "citation_candidates_bounded": 0,
                    "provider_errors": [],
                },
                "touch_ids": [],
                "crawler_recall_papers": [],
                "recall_papers": [],
            }
        })

        # hyperparameters
        self.expand_layers   = expand_layers
        self.search_queries  = search_queries
        self.search_papers   = search_papers
        self.expand_papers   = expand_papers
        self.expand_refs_per_paper = expand_refs_per_paper
        self.local_search_papers = local_search_papers
        self.selector_threshold = min(1.0, max(0.0, float(selector_threshold)))
        self.threads_num     = threads_num
        self.progress_callback = progress_callback
        self.query_planner = query_planner
        self.papers_queue    = []
        self.expand_start    = 0
        self.lock            = threading.Lock()
        self.templates       = {
            "cite_template":   r"~\\cite\{(.*?)\}",
            "search_template": r"Search\](.*?)\[",
            "expand_template": r"Expand\](.*?)\["
        }
    
    @staticmethod
    def do_parallel(func, args, num):
        threads = []
        errors = []
        errors_lock = threading.Lock()

        def run_worker():
            try:
                func(*args)
            except BaseException as exc:
                with errors_lock:
                    errors.append(exc)

        for _ in range(num):
            thread = threading.Thread(target=run_worker)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        if errors:
            raise RuntimeError(f"parallel worker failed: {errors[0]}") from errors[0]

    @staticmethod
    def _candidate_key(paper):
        if paper.get("arxiv_id"):
            return f"arxiv:{paper['arxiv_id']}"
        if paper.get("paper_id"):
            return paper["paper_id"]
        normalized_title = re.sub(r"\W+", "", paper.get("title", "")).lower()
        return f"title:{normalized_title}"

    @classmethod
    def _query_terms(cls, query):
        return {
            token
            for token in re.findall(r"[a-z0-9]+", query.lower())
            if len(token) > 1 and token not in cls._query_stop_words
        }

    @classmethod
    def _select_diverse_queries(cls, parsed, original_query, limit):
        """Greedily maximize lexical coverage across an oversized query pool."""
        original = original_query.strip()
        candidates = list(dict.fromkeys(query.strip() for query in parsed if query.strip()))
        if original and original not in candidates:
            candidates.append(original)
        if len(candidates) <= limit:
            return candidates[:limit]

        selected = [candidates.pop(0)]
        selected_terms = [cls._query_terms(selected[0])]
        reserve_original = original and original not in selected
        if reserve_original:
            candidates.remove(original)
        diversity_limit = limit - int(bool(reserve_original))
        while candidates and len(selected) < diversity_limit:
            best_index = 0
            best_similarity = float("inf")
            for index, candidate in enumerate(candidates):
                terms = cls._query_terms(candidate)
                maximum_similarity = max(
                    len(terms & existing) / len(terms | existing)
                    if terms | existing else 1.0
                    for existing in selected_terms
                )
                if maximum_similarity < best_similarity:
                    best_index = index
                    best_similarity = maximum_similarity
            chosen = candidates.pop(best_index)
            selected.append(chosen)
            selected_terms.append(cls._query_terms(chosen))
        if reserve_original and len(selected) < limit:
            selected.append(original)
        return selected

    @staticmethod
    def _bounded_expand_candidates(candidates, budget, threshold=0.5):
        """Bound every expansion layer while prioritizing Selector-approved papers.

        Keep a small top-score fallback when too few papers cross the 0.5 threshold so
        an imperfect Selector does not completely suppress citation recall.
        """
        if budget <= 0:
            return []
        candidates = list(candidates)
        approved = [paper for paper in candidates if paper.select_score > threshold]
        minimum_coverage = min(len(candidates), max(3, budget // 2))
        target = min(budget, max(minimum_coverage, len(approved)))
        return candidates[:target]

    @staticmethod
    def _bounded_section_references(sections, selected_sections, budget):
        """Round-robin references across Crawler-selected sections under a hard cap."""
        queues = []
        seen_sections = set()
        total = 0
        for raw_section in selected_sections:
            section = raw_section.strip()
            if section in seen_sections or section not in sections:
                continue
            seen_sections.add(section)
            references = list(dict.fromkeys(sections[section]))
            total += len(references)
            queues.append([section, references])

        bounded = []
        seen_titles = set()
        while queues and len(bounded) < budget:
            next_queues = []
            for section, references in queues:
                while references:
                    title = references.pop(0)
                    key = re.sub(r"\W+", "", title).lower()
                    if key and key not in seen_titles:
                        seen_titles.add(key)
                        bounded.append([section, title])
                        break
                if references:
                    next_queues.append([section, references])
                if len(bounded) >= budget:
                    break
            queues = next_queues
        return bounded, total

    @staticmethod
    def _merge_candidate(existing, incoming):
        if len(incoming.get("abstract", "")) > len(existing.get("abstract", "")):
            existing["abstract"] = incoming["abstract"]
        if not existing.get("sections") and incoming.get("sections"):
            existing["sections"] = incoming["sections"]
        if not existing.get("arxiv_id") and incoming.get("arxiv_id"):
            existing["arxiv_id"] = incoming["arxiv_id"]
        existing_extra = existing.setdefault("extra", {})
        incoming_extra = incoming.get("extra") or {}
        providers = set(existing_extra.get("retrieval_providers") or [])
        providers.update(incoming_extra.get("retrieval_providers") or [])
        existing_extra.update({
            key: value
            for key, value in incoming_extra.items()
            if key != "retrieval_providers" and value not in (None, "", [])
        })
        existing_extra["retrieval_providers"] = sorted(providers)
        sources = {item for item in (existing.get("source"), incoming.get("source")) if item}
        existing["source"] = "+".join(sorted(sources))
        return existing

    def _record_retrieval(self, provider, candidates=None, error=None):
        with self.lock:
            stats = self.root.extra["retrieval_stats"]
            stats[f"{provider}_calls"] += 1
            if candidates is not None:
                stats[f"{provider}_candidates"] += len(candidates)
            if error is not None:
                stats["provider_errors"].append({
                    "provider": provider,
                    "error": type(error).__name__,
                })

    def search_paper(self, queries):
        while True:
            with self.lock:
                if not queries:
                    return
                query = queries.pop()
                self.root.child[query] = []

            serper_ids, openalex_papers, local_papers = [], [], []
            with ThreadPoolExecutor(max_workers=3) as executor:
                serper_future = executor.submit(
                    google_search_arxiv_id, query, self.search_papers, self.end_date
                )
                openalex_future = executor.submit(
                    openalex_search_papers, query, self.search_papers, self.end_date
                )
                local_future = executor.submit(
                    search_papers_by_title_index, query, self.local_search_papers, self.end_date
                )
                try:
                    serper_ids = serper_future.result()
                    self._record_retrieval("serper", serper_ids)
                except Exception as exc:
                    self._record_retrieval("serper", error=exc)
                try:
                    openalex_papers = openalex_future.result()
                    self._record_retrieval("openalex", openalex_papers)
                except Exception as exc:
                    self._record_retrieval("openalex", error=exc)
                try:
                    local_papers = local_future.result()
                    self._record_retrieval("local", local_papers)
                except Exception as exc:
                    self._record_retrieval("local", error=exc)

            searched_papers = search_papers_by_arxiv_ids(serper_ids)
            for paper in searched_papers:
                paper["paper_id"] = f"arxiv:{paper['arxiv_id']}"
                paper["extra"] = {"retrieval_providers": ["serper"]}

            searched_papers.extend(openalex_papers)
            searched_papers.extend(local_papers)
            merged_papers = {}
            for paper in searched_papers:
                key = self._candidate_key(paper)
                if key in merged_papers:
                    self._merge_candidate(merged_papers[key], paper)
                else:
                    merged_papers[key] = paper

            searched_papers = []
            for key, paper in merged_papers.items():
                with self.lock:
                    if key in self.root.extra["touch_ids"]:
                        continue
                    self.root.extra["touch_ids"].append(key)
                searched_papers.append(paper)

            select_prompts  = [self.prompts["get_selected"].format(title=paper["title"], abstract=paper["abstract"], user_query=self.user_query) for paper in searched_papers]
            scores = self.selector.infer_score(select_prompts)
            with self.lock:
                for score, paper in zip(scores, searched_papers):
                    self.root.extra["crawler_recall_papers"].append(paper["title"])
                    if score > self.selector_threshold:
                        self.root.extra["recall_papers"].append(paper["title"])
                    paper_node = PaperNode({
                        "title":        paper["title"],
                        "arxiv_id":     paper["arxiv_id"],
                        "depth":        0,
                        "abstract" :    paper["abstract"],
                        "sections" :    paper["sections"],
                        "source":       "Search " + paper["source"],
                        "select_score": score,
                        "extra":        paper.get("extra", {})
                    })
                    self.root.child[query].append(paper_node)
                    self.papers_queue.append(paper_node)

                if self.progress_callback is not None:
                    papers = [
                        paper
                        for query_papers in self.root.child.values()
                        for paper in query_papers
                    ]
                    self.progress_callback(
                        len(papers),
                        sum(paper.select_score > self.selector_threshold for paper in papers),
                    )

    def search(self):
        parsed = []
        if self.query_planner is not None:
            planned = self.query_planner(self.original_user_query, self.search_queries)
            if isinstance(planned, dict):
                parsed = list(planned.get("queries") or [])
                self.root.extra["query_plan"] = dict(planned.get("query_plan") or {})
                self.root.extra["query_planning"] = dict(planned.get("metrics") or {})
        if not parsed:
            prompt = self.prompts["generate_query"].format(user_query=self.user_query).strip()
            response = self.crawler.infer(prompt)
            parsed = [
                query.strip()
                for query in re.findall(self.templates["search_template"], response, flags=re.DOTALL)
                if query.strip()
            ]
        initial_queries = self._select_diverse_queries(
            parsed, self.original_user_query, self.search_queries
        )
        if not initial_queries:
            raise RuntimeError("Crawler did not generate any valid search query")
        self.root.extra["generated_search_queries"] = list(initial_queries)
        if self.progress_callback is not None:
            self.progress_callback(0, 0)
        PaperAgent.do_parallel(
            self.search_paper, (list(initial_queries),), len(initial_queries)
        )

        children = getattr(self.root, "child", None)
        if isinstance(children, dict) and children:
            selector_threshold = getattr(self, "selector_threshold", 0.5)
            selected_count = sum(
                paper.select_score > selector_threshold
                for papers in children.values()
                for paper in papers
            )
            reserve_queries = list(dict.fromkeys(
                query.strip() for query in parsed
                if query.strip() and query.strip() not in initial_queries
            ))
            if selected_count < 3 and reserve_queries:
                adaptive_query = reserve_queries[0]
                self.root.extra["adaptive_search"] = {
                    "triggered": True,
                    "reason": "fewer_than_3_selector_approved_papers",
                    "initial_selected_count": selected_count,
                    "queries": [adaptive_query],
                }
                self.root.extra["generated_search_queries"].append(adaptive_query)
                PaperAgent.do_parallel(self.search_paper, ([adaptive_query],), 1)

    def get_paper_content(self, new_expand, crawl_prompts, have_full_paper):
        while True:
            with self.lock:
                if not new_expand:
                    return
                paper = new_expand.pop(0)
            
            if paper.sections == "":
                if not paper.arxiv_id:
                    paper.extra["expand"] = "unsupported: no arXiv ID"
                    continue
                paper.sections = search_section_by_arxiv_id(paper.arxiv_id, self.templates["cite_template"])
                if not paper.sections:
                    paper.extra["expand"] = "get full paper error"
                    continue
            
            paper.extra["expand"] = "not expand"
            prompt = self.prompts["select_section"].format(user_query=self.user_query, title=paper.title, abstract=paper.abstract, sections=paper.sections.keys()).strip()
            with self.lock:
                have_full_paper.append(paper)
                crawl_prompts.append(prompt)

    def search_ref(self, section_sources_ori, select_prompts, section_sources, lock):
        while True:
            with lock:
                if not section_sources_ori:
                    return
                section, title = section_sources_ori.pop(0)
            
            searched_paper = search_paper_by_title(title)
            if searched_paper is None:
                continue
            
            arxiv_id = searched_paper["arxiv_id"]
            paper_key = f"arxiv:{arxiv_id}"
            with lock:
                if paper_key not in self.root.extra["touch_ids"]:
                    self.root.extra["touch_ids"].append(paper_key)
                else:
                    continue
            prompt = self.prompts["get_selected"].format(title=title, abstract=searched_paper["abstract"], user_query=self.user_query)
            with lock:
                select_prompts.append(prompt)
                section_sources.append([section, searched_paper])

    def do_expand(self, depth, have_full_paper, crawl_results):
        while True:
            with self.lock:
                if not have_full_paper:
                    return
                if not crawl_results:
                    raise RuntimeError("Crawler expansion results do not match loaded papers")
                paper = have_full_paper.pop(0)
                crawl_result = crawl_results.pop(0)
            crawl_result = re.findall(self.templates["expand_template"], crawl_result, flags=re.DOTALL)
            section_sources_ori, original_candidate_count = self._bounded_section_references(
                paper.sections, crawl_result, self.expand_refs_per_paper
            )
            with self.lock:
                stats = self.root.extra["retrieval_stats"]
                stats["citation_candidates"] += original_candidate_count
                stats["citation_candidates_bounded"] += len(section_sources_ori)
            select_prompts, section_sources, lock = [], [], threading.Lock()
            PaperAgent.do_parallel(self.search_ref, (section_sources_ori, select_prompts, section_sources, lock), self.threads_num * 3)
            scores = self.selector.infer_score(select_prompts)
            for score, (section, ref_paper) in zip(scores, section_sources):
                self.root.extra["crawler_recall_papers"].append(ref_paper["title"])
                if score > self.selector_threshold:
                    self.root.extra["recall_papers"].append(ref_paper["title"])
                paper_node = PaperNode({
                    "title":        ref_paper["title"],
                    "depth":        depth + 1,
                    "arxiv_id":     ref_paper["arxiv_id"],
                    "abstract" :    ref_paper["abstract"],
                    "sections" :    ref_paper["sections"],
                    "source":       "Expand " + ref_paper["source"],
                    "select_score": score,
                    "extra":        {}
                })

                with self.lock:
                    if section not in paper.child:
                        paper.child[section] = []
                    paper.child[section].append(paper_node)
                    paper.extra["expand"] = "success"
                    self.papers_queue.append(paper_node)

    def expand(self, depth):
        candidates = sorted(self.papers_queue[self.expand_start:], key=PaperNode.sort_paper, reverse=True)
        self.papers_queue = self.papers_queue[:self.expand_start] + candidates
        expand_papers = self._bounded_expand_candidates(
            candidates, self.expand_papers, self.selector_threshold
        )
        with self.lock:
            self.root.extra["retrieval_stats"]["expansion_layers"].append({
                "depth": depth,
                "candidates": len(candidates),
                "expanded": len(expand_papers),
                "approved_candidates": sum(
                    paper.select_score > self.selector_threshold for paper in candidates
                ),
            })
        self.expand_start = len(self.papers_queue)
        crawl_prompts, have_full_paper = [], []
        PaperAgent.do_parallel(self.get_paper_content, (expand_papers, crawl_prompts, have_full_paper), self.threads_num)
        crawl_results = self.crawler.batch_infer(crawl_prompts)
        PaperAgent.do_parallel(self.do_expand, (depth, have_full_paper, crawl_results), self.threads_num)

    def run(self):
        self.search()
        for depth in range(self.expand_layers):
            self.expand(depth)

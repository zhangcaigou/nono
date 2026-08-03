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
    search_section_by_arxiv_id
)

class PaperAgent:
    _chinese_pattern = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

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
        expand_layers:  int = 2,
        search_queries: int = 5,
        search_papers:  int = 10, # per query
        expand_papers:  int = 20, # per layer
        threads_num:    int = 20, # number of threads in parallel at the same time
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
                "retrieval_stats": {
                    "serper_calls": 0,
                    "openalex_calls": 0,
                    "serper_candidates": 0,
                    "openalex_candidates": 0,
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
        self.threads_num     = threads_num
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
        while queries:
            with self.lock:
                query, self.root.child[query] = queries.pop(), []

            serper_ids, openalex_papers = [], []
            with ThreadPoolExecutor(max_workers=2) as executor:
                serper_future = executor.submit(
                    google_search_arxiv_id, query, self.search_papers, self.end_date
                )
                openalex_future = executor.submit(
                    openalex_search_papers, query, self.search_papers, self.end_date
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

            searched_papers = []
            for arxiv_id in serper_ids:
                arxiv_id = arxiv_id.split('v')[0]
                paper = search_paper_by_arxiv_id(arxiv_id)
                if paper is not None:
                    paper["paper_id"] = f"arxiv:{arxiv_id}"
                    paper["extra"] = {"retrieval_providers": ["serper"]}
                    searched_papers.append(paper)

            searched_papers.extend(openalex_papers)
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
                    if score > 0.5:
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

    def search(self):
        prompt = self.prompts["generate_query"].format(user_query=self.user_query).strip()
        queries = self.crawler.infer(prompt)
        queries = [q.strip() for q in re.findall(self.templates["search_template"], queries, flags=re.DOTALL)][:self.search_queries]
        self.root.extra["generated_search_queries"] = list(queries)
        PaperAgent.do_parallel(self.search_paper, (queries,), len(queries))

    def get_paper_content(self, new_expand, crawl_prompts, have_full_paper):
        while new_expand:
            with self.lock:
                if new_expand:
                    paper = new_expand.pop(0)
                else:
                    break
            
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
        while section_sources_ori:
            with lock:
                if section_sources_ori:
                    section, title = section_sources_ori.pop(0)
                else:
                    break
            
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
        while have_full_paper:
            with self.lock:
                if have_full_paper:
                    paper = have_full_paper.pop(0)
                    crawl_result = crawl_results.pop(0)
                else:
                    break
            crawl_result = re.findall(self.templates["expand_template"], crawl_result, flags=re.DOTALL)
            section_sources_ori = []
            for section in crawl_result:
                section = section.strip()
                if section not in paper.sections:
                    continue
                for ref in paper.sections[section]:
                    section_sources_ori.append([section, ref])
            select_prompts, section_sources, lock = [], [], threading.Lock()
            PaperAgent.do_parallel(self.search_ref, (section_sources_ori, select_prompts, section_sources, lock), self.threads_num * 3)
            scores = self.selector.infer_score(select_prompts)
            for score, (section, ref_paper) in zip(scores, section_sources):
                self.root.extra["crawler_recall_papers"].append(ref_paper["title"])
                if score > 0.5:
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
        expand_papers = sorted(self.papers_queue[self.expand_start:], key=PaperNode.sort_paper, reverse=True)
        self.papers_queue = self.papers_queue[:self.expand_start] + expand_papers
        if depth > 0:
            expand_papers = expand_papers[:self.expand_papers]
        self.expand_start = len(self.papers_queue)
        crawl_prompts, have_full_paper = [], []
        PaperAgent.do_parallel(self.get_paper_content, (expand_papers, crawl_prompts, have_full_paper), self.threads_num)
        crawl_results = self.crawler.batch_infer(crawl_prompts)
        PaperAgent.do_parallel(self.do_expand, (depth, have_full_paper, crawl_results), self.threads_num)

    def run(self):
        self.search()
        for depth in range(self.expand_layers):
            self.expand(depth)

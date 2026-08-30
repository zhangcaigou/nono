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
"""
Please note that:
1. You need to first apply for a Google Search API key at https://serper.dev/
   and provide it through the SERPER_API_KEY environment variable.
2. The service for searching arxiv and obtaining paper contents is relatively simple. 
   If there are any bugs or improvement suggestions, you can submit pull requests.
   We would greatly appreciate and look forward to your contributions!!
"""
import re
import bs4
import copy
import json
import os
import arxiv
import sqlite3
import urllib
import zipfile
import warnings
import requests
import time
import threading
from functools import lru_cache
from pathlib import Path
from datetime   import datetime
warnings.simplefilter("always")

PROJECT_ROOT = Path(__file__).resolve().parent
GOOGLE_KEY   = os.getenv("SERPER_API_KEY", "").strip()
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "").strip()
OPENALEX_API_URL = "https://api.openalex.org/works"
arxiv_client = arxiv.Client(delay_seconds = 0.05)
paper_id_path = Path(os.getenv("PASA_PAPER_ID_PATH", PROJECT_ROOT / "data/paper_database/id2paper.json"))
paper_db_path = Path(os.getenv("PASA_PAPER_DB_PATH", PROJECT_ROOT / "data/paper_database/cs_paper_2nd.zip"))
title_index_path = Path(os.getenv(
    "PASA_TITLE_INDEX_PATH", PROJECT_ROOT / "data/paper_database/title_index.sqlite3"
))
with paper_id_path.open(encoding="utf-8") as paper_id_file:
    id2paper = json.load(paper_id_file)
paper_db     = zipfile.ZipFile(paper_db_path, "r")
paper_db_names = set(paper_db.namelist())
serper_concurrency = max(1, int(os.getenv("PASA_SERPER_CONCURRENCY", "2")))
serper_semaphore = threading.BoundedSemaphore(serper_concurrency)
TITLE_QUERY_STOP_WORDS = {
    "a", "all", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "give", "in", "is", "list", "me", "of", "on", "or", "paper", "papers",
    "provide", "research", "show", "some", "study", "studies", "that", "the",
    "to", "use", "using", "which", "with", "about",
}

def _google_search_arxiv_id_uncached(query, num=10, end_date=None):
    if not GOOGLE_KEY:
        raise RuntimeError("SERPER_API_KEY is not configured")

    url = "https://google.serper.dev/search"

    search_query = f"{query} site:arxiv.org"
    if end_date:
        try:
            end_date = datetime.strptime(end_date, '%Y%m%d').strftime('%Y-%m-%d')
            search_query = f"{query} before:{end_date} site:arxiv.org"
        except:
            search_query = f"{query} site:arxiv.org"
    
    payload = json.dumps({
        "q": search_query, 
        "num": num, 
        "page": 1, 
    })

    headers = {
        'X-API-KEY': GOOGLE_KEY,
        'Content-Type': 'application/json'
    }
    last_error = None
    for attempt in range(3):
        try:
            with serper_semaphore:
                response = requests.request("POST", url, headers=headers, data=payload, timeout=30)
            if response.status_code == 200:
                results = json.loads(response.text)
                arxiv_id_list = []
                for paper in results.get('organic', []):
                    match = re.search(r'arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d+)', paper.get("link", ""))
                    if match:
                        arxiv_id = match.group(1)
                        arxiv_id_list.append(arxiv_id)
                return list(dict.fromkeys(arxiv_id_list))
            last_error = RuntimeError(f"Serper returned HTTP {response.status_code}")
        except (requests.RequestException, ValueError, TypeError) as exc:
            last_error = exc
        warnings.warn(f"google search failed, query: {query}: {last_error}")
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Serper search failed after 3 attempts: {last_error}")


@lru_cache(maxsize=256)
def _cached_google_search_arxiv_id(query, num, end_date):
    return tuple(_google_search_arxiv_id_uncached(query, num, end_date))


def google_search_arxiv_id(query, num=10, end_date=None):
    """Search Serper with a process-local cache for repeated query plans."""
    return list(_cached_google_search_arxiv_id(query, int(num), end_date))


def _openalex_abstract(inverted_index):
    """Reconstruct an abstract from OpenAlex's inverted-index representation."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positions = []
    for word, indexes in inverted_index.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int) and index >= 0:
                positions.append((index, word))
    positions.sort(key=lambda item: item[0])
    return " ".join(str(word) for _, word in positions)


def _openalex_arxiv_id(ids, *fallback_values):
    values = list(ids.values()) if isinstance(ids, dict) else []
    values.extend(fallback_values)
    for value in values:
        value = str(value or "")
        if "arxiv" not in value.lower():
            continue
        match = re.search(r"(\d{4}\.\d+)", value)
        if match:
            return match.group(1)
    return ""


OPENALEX_WORK_SELECT = (
    "id,doi,title,display_name,publication_year,publication_date,"
    "primary_location,ids,cited_by_count,authorships,abstract_inverted_index"
)


def _normalize_openalex_work(work):
    title = str(work.get("title") or work.get("display_name") or "").strip()
    if not title:
        return None
    openalex_url = str(work.get("id") or "")
    openalex_id = openalex_url.rstrip("/").split("/")[-1]
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = str(author.get("display_name") or "").strip()
        if name:
            authors.append(name)
    landing_url = str(primary_location.get("landing_page_url") or "")
    arxiv_id = _openalex_arxiv_id(work.get("ids"), work.get("doi"), landing_url)
    return {
        "paper_id": f"arxiv:{arxiv_id}" if arxiv_id else f"openalex:{openalex_id}",
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": _openalex_abstract(work.get("abstract_inverted_index")),
        "sections": "",
        "source": "SearchFrom:openalex",
        "extra": {
            "retrieval_providers": ["openalex"],
            "openalex_id": openalex_id,
            "openalex_url": openalex_url,
            "doi": str(work.get("doi") or ""),
            "publication_year": work.get("publication_year"),
            "publication_date": str(work.get("publication_date") or ""),
            "venue": str(source.get("display_name") or ""),
            "cited_by_count": int(work.get("cited_by_count") or 0),
            "authors": authors,
            "landing_page_url": landing_url or openalex_url,
        },
    }


def _openalex_search_papers_uncached(query, num=10, end_date=None):
    """Search OpenAlex and normalize works into PaSa's internal paper format."""
    if not OPENALEX_API_KEY:
        raise RuntimeError("OPENALEX_API_KEY is not configured")

    params = {
        "api_key": OPENALEX_API_KEY,
        "search": query,
        "per-page": max(1, min(int(num), 100)),
        "select": OPENALEX_WORK_SELECT,
    }
    if end_date:
        try:
            formatted_date = datetime.strptime(end_date, "%Y%m%d").strftime("%Y-%m-%d")
            params["filter"] = f"to_publication_date:{formatted_date}"
        except (TypeError, ValueError):
            pass

    for attempt in range(3):
        try:
            response = requests.get(OPENALEX_API_URL, params=params, timeout=30)
            if response.status_code == 200:
                payload = response.json()
                papers = []
                for work in payload.get("results", []):
                    paper = _normalize_openalex_work(work)
                    if paper is not None:
                        papers.append(paper)
                return papers
        except (requests.RequestException, ValueError, TypeError):
            pass
        if attempt < 2:
            time.sleep(attempt + 1)
    raise RuntimeError("OpenAlex search failed after 3 attempts")


@lru_cache(maxsize=256)
def _cached_openalex_search_papers(query, num, end_date):
    return tuple(_openalex_search_papers_uncached(query, num, end_date))


def openalex_search_papers(query, num=10, end_date=None):
    """Search OpenAlex while protecting cached values from caller mutation."""
    return copy.deepcopy(list(_cached_openalex_search_papers(query, int(num), end_date)))

def parse_metadata(metas):
    """
    Parse concatenated metadata string into authors, title, and journal.
    """
    # Get and clean metas
    metas = [item.replace('\n', ' ') for item in metas]
    meta_string = ' '.join(metas)
    
    authors, title, journal = "", "", ""
        
    if len(metas) == 3: # author / title / journal
        authors, title, journal = metas
    else:
        # Remove the year suffix (e.g., 2022a) from the metadata string
        meta_string = re.sub(r'\.\s\d{4}[a-z]?\.', '.', meta_string)
        # Regular expression to match the pattern
        regex = r"^(.*?\.\s)(.*?)(\.\s.*|$)"
        match = re.match(regex, meta_string, re.DOTALL)
        if match:
            authors = match.group(1).strip() if match.group(1) else ""
            title = match.group(2).strip() if match.group(2) else ""
            journal = match.group(3).strip() if match.group(3) else ""

            if journal.startswith('. '):
                journal = journal[2:]

    return {
        "meta_list": metas, 
        "meta_string": meta_string, 
        "authors": authors,
        "title": title,
        "journal": journal
    }

def create_dict_for_citation(ul_element):
    citation_dict, futures, id_attrs = {}, [], []
    for li in ul_element.find_all("li", recursive=False):
        id_attr = li['id']
        metas = [x.text.strip() for x in li.find_all('span', class_='ltx_bibblock')]
        id_attrs.append(id_attr)
        futures.append(parse_metadata(metas))
    results = list(zip(id_attrs, futures))
    citation_dict = dict(results)
    return citation_dict

def generate_full_toc(soup):
    toc = []
    stack = [(0, toc)]
    
    # Mapping of heading tags to their levels
    heading_tags = {'h1': 1, 'h2': 2, 'h3': 3, 'h4': 4, 'h5': 5}
    
    for tag in soup.find_all(heading_tags.keys()):
        level = heading_tags[tag.name]
        title = tag.get_text()
        
        # Ensure the stack has the correct level
        while stack and stack[-1][0] >= level:
            stack.pop()
        
        current_level = stack[-1][1]

        # Find the nearest enclosing section with an id
        section = tag.find_parent('section', id=True)
        section_id = section.get('id') if section else None
        
        # Create the new entry
        new_entry = {'title': title, 'id': section_id, 'subsections': []}
        
        current_level.append(new_entry)
        stack.append((level, new_entry['subsections']))
    
    return toc

def parse_text(local_text, tag):
    ignore_tags = ['a', 'figure', 'center', 'caption', 'td', 'h1', 'h2', 'h3', 'h4']
    # latexmlc
    ignore_tags += ['sup']
    max_math_length = 300000

    for child in tag.children:
        child_type = type(child)
        if child_type == bs4.element.NavigableString:
                txt = child.get_text()
                local_text.append(txt)

        elif child_type == bs4.element.Comment:
            continue
        elif child_type == bs4.element.Tag:

                if child.name in ignore_tags or (child.has_attr('class') and child['class'][0] == 'navigation'):
                    continue
                elif child.name == 'cite':
                    # add hrefs
                    hrefs = [a.get('href').strip('#') for a in child.find_all('a', class_='ltx_ref')]
                    local_text.append('~\\cite{' + ', '.join(hrefs) + '}')
                elif child.name == 'img' and child.has_attr('alt'):
                    math_txt = child.get('alt')
                    if len(math_txt) < max_math_length:
                        local_text.append(math_txt)

                elif child.has_attr('class') and (child['class'][0] == 'ltx_Math' or child['class'][0] == 'ltx_equation'):
                    math_txt = child.get_text()
                    if len(math_txt) < max_math_length:
                        local_text.append(math_txt)

                elif child.name == 'section':
                    return
                else:
                    parse_text(local_text, child)
        else:
            raise RuntimeError('Unhandled type')

def clean_text(text):
    delete_items = ['=-1', '\t', u'\xa0', '[]', '()', 'mathbb', 'mathcal', 'bm', 'mathrm', 'mathit', 'mathbf', 'mathbfcal', 'textbf', 'textsc', 'langle', 'rangle', 'mathbin']
    for item in delete_items:
        text = text.replace(item, '')
    text = re.sub(' +', ' ', text)
    text = re.sub(r'[[,]+]', '', text)
    text = re.sub(r'\.(?!\d)', '. ', text)
    text = re.sub('bib. bib', 'bib.bib', text)
    return text

def remove_stop_word_sections_and_extract_text(toc, soup, stop_words=['references', 'acknowledgments', 'about this document', 'apopendix']):
    def has_stop_word(title, stop_words):
        return any(stop_word.lower() in title.lower() for stop_word in stop_words)
    
    def extract_text(entry, soup):
        section_id = entry['id']
        if section_id: # section_id
            section = soup.find(id=section_id)
            if section is not None:
                local_text = []
                parse_text(local_text, section)
                if local_text:
                    processed_text = clean_text(''.join(local_text))
                    entry['text'] = processed_text
        return 0 
    
    def filter_and_update_toc(entries):
        filtered_entries = []
        for entry in entries:
            if not has_stop_word(entry['title'], stop_words):
                # Get clean text
                extract_text(entry, soup)                
                entry['subsections'] = filter_and_update_toc(entry['subsections'])
                filtered_entries.append(entry)
        return filtered_entries
    
    return filter_and_update_toc(toc)

def parse_html(html_file):
    soup = bs4.BeautifulSoup(html_file, "lxml")
    # parse title
    title = soup.head.title.get_text().replace("\n", " ")
    # parse abstract
    abstract = soup.find(class_='ltx_abstract').get_text()
    # parse citation
    citation = soup.find(class_='ltx_biblist')
    citation_dict = create_dict_for_citation(citation)
    # generate the full toc without text
    sections = generate_full_toc(soup)
    # remove the sections need to skip and extract the text of the rest sections
    sections = remove_stop_word_sections_and_extract_text(sections, soup)
    document = {
        "title": title, 
        "abstract": abstract, 
        "sections": sections, 
        "references": citation_dict,
    }
    return document 

def _search_section_by_arxiv_id_uncached(entry_id, cite):
    warnings.warn("Using search_section_by_arxiv_id function may return wrong title because ar5iv parsing citation error. To solve this, You can prompt any LLM to extract the paper title from the reference string")
    assert re.match(r'^\d+\.\d+$', entry_id)
    url = f'https://ar5iv.labs.arxiv.org/html/{entry_id}'
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            html_content = response.text
            if not 'https://ar5iv.labs.arxiv.org/html' in html_content:
                warnings.warn(f'Invalid ar5iv HTML document: {url}')
                return None
            else:
                try:
                    document = parse_html(html_content)
                except:
                    warnings.warn(f'Wrong format HTML document: {url}')
                    return None
                try:
                    sections = get_2nd_section(document["sections"][0]["subsections"])
                except:
                    warnings.warn(f'Get subsections error')
                    return None
                sections2title = {}
                for k, v in sections.items():
                    k = " ".join(k.split("\n"))
                    sections2title[k] = set()
                    bibs = re.findall(cite, v, re.DOTALL)
                    for bib in bibs:
                        bib = bib.split(",")
                        for b in bib:
                            if b not in document["references"]:
                                continue
                            sections2title[k].add(document["references"][b]["title"]) # !!! The title here may be incorrect, you can use an LLM to parse the write title from document["references"][b]["meta_string"] !!!
                    if len(sections2title[k]) == 0:
                        del sections2title[k]
                    else:
                        sections2title[k] = list(sections2title[k])
                return sections2title
        else:
            warnings.warn(f"Failed to retrieve content. Status code: {response.status_code}")
            return None
    except requests.RequestException as e:
        warnings.warn(f"An error occurred: {e}")
        return None


@lru_cache(maxsize=512)
def _cached_search_section_by_arxiv_id(entry_id, cite):
    return _search_section_by_arxiv_id_uncached(entry_id, cite)


def search_section_by_arxiv_id(entry_id, cite):
    return copy.deepcopy(_cached_search_section_by_arxiv_id(entry_id, cite))

def keep_letters(s):
    letters = [c for c in s if c.isalpha()]
    result = ''.join(letters)
    return result.lower()

def _local_paper_by_arxiv_id(arxiv_id):
    """Resolve an arXiv paper from the bundled database without network access."""
    if arxiv_id not in id2paper:
        return None
    title_key = keep_letters(id2paper[arxiv_id])
    if title_key not in paper_db_names:
        return None
    with paper_db.open(title_key) as source:
        data = json.loads(source.read().decode("utf-8"))
    return {
        "arxiv_id": arxiv_id,
        "title": data["title"].replace("\n", " "),
        "abstract": data["abstract"],
        "sections": data["sections"],
        "source": "SearchFrom:local_paper_db",
    }


def _arxiv_result_to_paper(result, expected_ids=None):
    entry_id = result.entry_id.split("/")[-1].split("v")[0]
    if expected_ids is not None and entry_id not in expected_ids:
        return None
    return {
        "arxiv_id": entry_id,
        "title": result.title.replace("\n", " "),
        "abstract": result.summary.replace("\n", " "),
        "sections": "",
        "source": "SearchFrom:arxiv",
    }


def _search_paper_by_arxiv_id_uncached(arxiv_id):
    """
    Search paper by arxiv id.
    :param arxiv_id: arxiv id of the paper
    :return: paper list
    """
    local = _local_paper_by_arxiv_id(arxiv_id)
    if local is not None:
        return local

    search = arxiv.Search(
        query = "",
        id_list = [arxiv_id],
        max_results = 10,
        sort_by = arxiv.SortCriterion.Relevance,
        sort_order = arxiv.SortOrder.Descending,
    )

    try:
        results = list(arxiv_client.results(search, offset=0))
    except:
        warnings.warn(f"Failed to search arxiv id: {arxiv_id}")
        return None

    for arxiv_result in results:
        paper = _arxiv_result_to_paper(arxiv_result, {arxiv_id})
        if paper is not None:
            return paper
    return None


@lru_cache(maxsize=4096)
def _cached_search_paper_by_arxiv_id(arxiv_id):
    return _search_paper_by_arxiv_id_uncached(arxiv_id)


def search_paper_by_arxiv_id(arxiv_id):
    """Resolve paper metadata once per model-service process."""
    return copy.deepcopy(_cached_search_paper_by_arxiv_id(arxiv_id))


def _search_papers_by_arxiv_ids_uncached(arxiv_ids):
    """Resolve a Serper page locally, then batch missing IDs through OpenAlex DOI."""
    normalized = list(dict.fromkeys(str(item).split("v")[0] for item in arxiv_ids if item))
    resolved = {}
    missing = []
    for arxiv_id in normalized:
        local = _local_paper_by_arxiv_id(arxiv_id)
        if local is not None:
            resolved[arxiv_id] = local
        else:
            missing.append(arxiv_id)

    if missing:
        try:
            dois = "|".join(f"10.48550/arxiv.{arxiv_id}" for arxiv_id in missing)
            response = requests.get(
                OPENALEX_API_URL,
                params={
                    "api_key": OPENALEX_API_KEY,
                    "filter": f"doi:{dois}",
                    "per-page": min(len(missing), 100),
                    "select": OPENALEX_WORK_SELECT,
                },
                timeout=15,
            )
            if response.status_code == 200:
                for work in response.json().get("results", []):
                    paper = _normalize_openalex_work(work)
                    if paper is not None and paper["arxiv_id"] in missing:
                        paper["extra"]["retrieval_providers"] = ["serper", "openalex_metadata"]
                        resolved[paper["arxiv_id"]] = paper
            else:
                warnings.warn(f"OpenAlex DOI batch returned HTTP {response.status_code}")
        except Exception as error:
            warnings.warn(f"Failed to resolve {len(missing)} arxiv ids via OpenAlex DOI: {error}")
    return [resolved[arxiv_id] for arxiv_id in normalized if arxiv_id in resolved]


@lru_cache(maxsize=512)
def _cached_search_papers_by_arxiv_ids(arxiv_ids):
    return tuple(_search_papers_by_arxiv_ids_uncached(arxiv_ids))


def search_papers_by_arxiv_ids(arxiv_ids):
    return copy.deepcopy(list(_cached_search_papers_by_arxiv_ids(tuple(arxiv_ids))))


def _title_index_match(query):
    terms = list(dict.fromkeys(
        token for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 1 and token not in TITLE_QUERY_STOP_WORDS
    ))
    return " OR ".join(f'"{term}"' for term in terms)


def _arxiv_not_after(arxiv_id, end_date):
    """Apply a conservative month-level cutoff when the bundled DB has no date field."""
    if not end_date:
        return True
    match = re.fullmatch(r"(\d{2})(\d{2})\.\d+", str(arxiv_id or ""))
    if not match:
        return True
    try:
        cutoff = datetime.strptime(str(end_date), "%Y%m%d")
    except (TypeError, ValueError):
        return True
    paper_year = 2000 + int(match.group(1))
    paper_month = int(match.group(2))
    return (paper_year, paper_month) <= (cutoff.year, cutoff.month)


def _search_papers_by_title_index_uncached(query, num, end_date=None):
    if num <= 0 or not title_index_path.exists():
        return []
    match = _title_index_match(query)
    if not match:
        return []
    uri = f"file:{title_index_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        rows = connection.execute(
            "SELECT arxiv_id, title, bm25(paper_titles) AS score "
            "FROM paper_titles WHERE paper_titles MATCH ? "
            "ORDER BY score LIMIT ?",
            (match, max(int(num), int(num) * 3)),
        ).fetchall()
    finally:
        connection.close()

    papers = []
    for rank, (arxiv_id, title, bm25_score) in enumerate(rows, 1):
        if not _arxiv_not_after(arxiv_id, end_date):
            continue
        paper = _local_paper_by_arxiv_id(arxiv_id)
        if paper is None:
            continue
        paper["paper_id"] = f"arxiv:{arxiv_id}"
        paper["extra"] = {
            "retrieval_providers": ["local_title"],
            "local_title_rank": rank,
            "local_title_bm25": float(bm25_score),
        }
        papers.append(paper)
        if len(papers) >= num:
            break
    return papers


@lru_cache(maxsize=512)
def _cached_search_papers_by_title_index(query, num, end_date):
    return tuple(_search_papers_by_title_index_uncached(query, num, end_date))


def search_papers_by_title_index(query, num=20, end_date=None):
    return copy.deepcopy(list(_cached_search_papers_by_title_index(query, int(num), end_date)))
    
@lru_cache(maxsize=2048)
def search_arxiv_id_by_title(title):
    """
    Search arxiv id by title.
    :param title: title of the paper
    :return: arxiv id of the paper
    """
    url = "https://arxiv.org/search/?" + urllib.parse.urlencode({
        'query': title,
        'searchtype': 'title', 
        'abstracts': 'hide', 
        'size': 200, 
    })
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            html_content = response.text
            soup = bs4.BeautifulSoup(html_content, 'html.parser')
            results = []

            if soup.find('meta', charset=True): # paper list
                if soup.find('p', class_="is-size-4 has-text-warning") and "Sorry" in soup.find('p', class_="is-size-4 has-text-warning").text.strip():
                    warnings.warn(f"Failed to find results by Arxiv Advanced Search: {title}")
                    return None
                
                p_tags = soup.find_all("li", class_="arxiv-result")
                for p_tag in p_tags:
                    title = p_tag.find("p", class_="title is-5 mathjax").text.strip()
                    id = p_tag.find('p', class_='list-title is-inline-block').find('a').text.strip('arXiv:')
                    if title and id:
                        results.append((title, id))
            if soup.find('html', xmlns=True): # a single paper
                p_tag = soup.find("head").find("title")
                match = re.match(r'\[(.*?)\]\s*(.*)', soup.title.string)
                if match:
                    id = match.group(1)
                    title = match.group(2)
                    if title and id:
                        results = [(title, id)]

            if results:
                for (result, id) in results:
                    title_find = result.lower().strip('.').replace(' ', '').replace('\n', '')
                    title_search = title.lower().strip('.').replace(' ', '').replace('\n', '')
                    if title_find == title_search:
                        return id
                return None
        
            warnings.warn(f"Failed to parse the html: {url}")
            return None
        else:
            warnings.warn(f"Failed to retrieve content. Status code: {response.status_code}")
            return None
    except requests.RequestException as e:
        warnings.warn(f"An error occurred while search_arxiv_id_by_title: {e}")
        return None

def _search_paper_by_title_uncached(title):
    """
    Search paper by title.
    :param title: title of the paper
    :return: paper list
    """
    title_id = search_arxiv_id_by_title(title)
    if title_id is None:
        return None
    title_id = title_id.split('v')[0]
    return search_paper_by_arxiv_id(title_id)


@lru_cache(maxsize=2048)
def _cached_search_paper_by_title(title):
    return _search_paper_by_title_uncached(title)


def search_paper_by_title(title):
    return copy.deepcopy(_cached_search_paper_by_title(title))


def retrieval_cache_stats():
    """Expose cache effectiveness for benchmark and operations diagnostics."""
    return {
        "serper": _cached_google_search_arxiv_id.cache_info()._asdict(),
        "openalex": _cached_openalex_search_papers.cache_info()._asdict(),
        "sections": _cached_search_section_by_arxiv_id.cache_info()._asdict(),
        "paper_by_id": _cached_search_paper_by_arxiv_id.cache_info()._asdict(),
        "paper_batch": _cached_search_papers_by_arxiv_ids.cache_info()._asdict(),
        "title_index": _cached_search_papers_by_title_index.cache_info()._asdict(),
        "id_by_title": search_arxiv_id_by_title.cache_info()._asdict(),
        "paper_by_title": _cached_search_paper_by_title.cache_info()._asdict(),
    }

def get_subsection(sections):
    res = {}
    for section in sections:
        if "text" in section and section["text"].strip() != "":
            res[section["title"].strip()] = section["text"].strip()
        subsections = get_subsection(section["subsections"])
        for k, v in subsections.items():
            res[k] = v
    return res

def get_1st_section(sections):
    res = {}
    for section in sections:
        subsections = get_subsection(section["subsections"])
        if "text" in section and section["text"].strip() != "" or len(subsections) > 0:
            if "text" in section and section["text"].strip() != "":
                res[section["title"].strip()] = section["text"].strip()
            else:
                res[section["title"].strip()] = ""
            for k, v in subsections.items():
                res[section["title"].strip()] += v.strip()
    res_new = {}
    for k, v in res.items():
        if "appendix" not in k.lower():
            res_new[" ".join(k.split("\n")).strip()] = v
    return res_new

def get_2nd_section(sections):
    res = {}
    for section in sections:
        subsections = get_1st_section(section["subsections"])
        if "text" in section and section["text"].strip() != "":
            if "text" in section and section["text"].strip() != "":
                res[section["title"].strip()] = section["text"].strip()
        for k, v in subsections.items():
            res[section["title"].strip() + " " + k.strip()] = v.strip()
    res_new = {}
    for k, v in res.items():
        if "appendix" not in k.lower():
            res_new[" ".join(k.split("\n")).strip()] = v
    return res_new

def cal_micro(pred_set, label_set):
    if len(label_set) == 0:
        return 0, 0, 0

    if len(pred_set) == 0:
        return 0, 0, len(label_set)

    tp = len(pred_set & label_set)
    fp = len(pred_set - label_set)
    fn = len(label_set - pred_set)

    assert tp + fn == len(label_set)
    assert len(label_set) != 0
    return tp, fp, fn

if __name__ == "__main__":
    print(search_section_by_arxiv_id("2307.00235", r"~\\cite\{(.*?)\}"))
    # print(search_paper_by_arxiv_id("2307.00235"))
    # print(search_paper_by_title("A hybrid approach to CMB lensing reconstruction on all-sky intensity maps"))

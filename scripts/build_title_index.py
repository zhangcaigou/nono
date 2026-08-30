#!/usr/bin/env python3
"""Build a deterministic SQLite FTS5 index for the bundled PaSa paper titles."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path


def build(source: Path, target: Path) -> None:
    started = time.perf_counter()
    with source.open(encoding="utf-8") as input_file:
        papers = json.load(input_file)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".building")
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=MEMORY;
            CREATE VIRTUAL TABLE paper_titles USING fts5(
                arxiv_id UNINDEXED,
                title,
                tokenize='porter unicode61 remove_diacritics 2'
            );
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        rows = ((paper_id, title) for paper_id, title in papers.items())
        connection.executemany(
            "INSERT INTO paper_titles(arxiv_id, title) VALUES (?, ?)", rows
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('paper_count', ?)",
            (str(len(papers)),),
        )
        connection.execute("INSERT INTO paper_titles(paper_titles) VALUES ('optimize')")
        connection.commit()
    finally:
        connection.close()
    os.replace(temporary, target)
    print(
        json.dumps({
            "index": str(target),
            "papers": len(papers),
            "size_bytes": target.stat().st_size,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }, ensure_ascii=False)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", default="data/paper_database/id2paper.json", type=Path
    )
    parser.add_argument(
        "--output", default="data/paper_database/title_index.sqlite3", type=Path
    )
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()

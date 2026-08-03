"""Interactive command-line entry point for PaSa paper search."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from models import Agent
from paper_agent import PaperAgent


def parse_args():
    parser = argparse.ArgumentParser(description="Interactively search papers with PaSa")
    parser.add_argument("--crawler_path", default="checkpoints/pasa-7b-crawler")
    parser.add_argument("--selector_path", default="checkpoints/pasa-7b-selector")
    parser.add_argument("--output_folder", default="results/interactive")
    parser.add_argument("--expand_layers", type=int, default=0)
    parser.add_argument("--search_queries", type=int, default=3)
    parser.add_argument("--search_papers", type=int, default=5)
    parser.add_argument("--expand_papers", type=int, default=10)
    parser.add_argument("--threads_num", type=int, default=10)
    return parser.parse_args()


def print_results(tree):
    papers = []
    queue = [tree]
    while queue:
        node = queue.pop(0)
        for children in (node.get("child") or {}).values():
            for child in children:
                queue.append(child)
                if child.get("arxiv_id"):
                    papers.append(child)

    unique = {}
    for paper in papers:
        key = paper.get("arxiv_id") or paper.get("title")
        if key not in unique or paper.get("select_score", 0) > unique[key].get("select_score", 0):
            unique[key] = paper

    ranked = sorted(unique.values(), key=lambda item: item.get("select_score", 0), reverse=True)
    if not ranked:
        print("\n没有检索到论文。\n")
        return

    print(f"\n检索到 {len(ranked)} 篇论文：")
    for index, paper in enumerate(ranked, 1):
        score = paper.get("select_score", 0)
        arxiv_id = paper.get("arxiv_id", "")
        print(f"{index}. [{score:.4f}] {paper.get('title', '')}")
        print(f"   https://arxiv.org/abs/{arxiv_id}")
    print()


def main():
    args = parse_args()
    if not os.getenv("SERPER_API_KEY"):
        print("提示：建议先设置 SERPER_API_KEY 环境变量。")

    output_folder = Path(args.output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    print("正在加载 Crawler 模型……")
    crawler = Agent(args.crawler_path)
    print("正在加载 Selector 模型……")
    selector = Agent(args.selector_path)
    print("模型加载完成。请输入论文检索需求；输入 quit 或 exit 退出。\n")

    request_number = 0
    while True:
        try:
            query = input("PaSa> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break

        if query.lower() in {"quit", "exit", "q"}:
            print("已退出。")
            break
        if not query:
            continue

        try:
            request_number += 1
            agent = PaperAgent(
                user_query=query,
                crawler=crawler,
                selector=selector,
                expand_layers=args.expand_layers,
                search_queries=args.search_queries,
                search_papers=args.search_papers,
                expand_papers=args.expand_papers,
                threads_num=args.threads_num,
            )
            agent.run()
            if agent.input_language == "zh":
                generated_queries = agent.root.extra.get("generated_search_queries", [])
                if generated_queries:
                    print("\n生成的英文检索词：")
                    for generated_query in generated_queries:
                        print(f"- {generated_query}")
        except Exception as exc:
            print(f"\n检索失败：{exc}\n")
            continue

        tree = agent.root.todic()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = output_folder / f"{timestamp}-{request_number}.json"
        with output_path.open("w", encoding="utf-8") as output_file:
            json.dump(tree, output_file, ensure_ascii=False, indent=2)

        print_results(tree)
        print(f"完整结果已保存到：{output_path}\n")


if __name__ == "__main__":
    main()

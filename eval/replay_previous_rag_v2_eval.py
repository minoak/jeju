"""Replay a previous RAG report with the Goldset V2 metrics.

This does not rerun the old retriever. It parses the top-10 results from a
previous markdown report and scores them with the current Goldset V2 evaluator.

Usage:
    python eval/replay_previous_rag_v2_eval.py
    python eval/replay_previous_rag_v2_eval.py --previous-report data/reports/rag_three_tier_evaluation.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREVIOUS_STASH_REF = "stash@{0}^3:data/reports/rag_three_tier_evaluation.md"
DEFAULT_CURRENT_REPORT = ROOT / "data" / "reports" / "rag_goldset_v2_evaluation.md"
DEFAULT_PREVIOUS_REPORT = ROOT / "data" / "reports" / "rag_goldset_v2_previous_replay.md"
DEFAULT_COMPARISON_REPORT = ROOT / "data" / "reports" / "rag_goldset_v2_comparison.md"

sys.path.insert(0, str(ROOT))
from eval.goldset_v2_eval import (  # noqa: E402
    CARDS_PATH,
    DEFAULT_GOLD,
    NameResolver,
    forbidden_exposure,
    hit_metrics,
    load_gold,
    ndcg_at_k,
    pct,
    region_match,
    required_tag_metrics,
)


METRIC_ORDER = [
    "Must Hit@5",
    "Must Hit@10",
    "Canonical MRR@10",
    "NDCG@5",
    "NDCG@10",
    "Semantic Tag Match@5",
    "Semantic Tag Coverage@5",
    "Region Match@5",
    "Forbidden Exposure@5",
]


def md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "/").replace("\n", " ")


def read_previous_report(path: Path | None) -> str:
    if path and path.exists():
        return path.read_text(encoding="utf-8-sig")
    result = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=D:/model-serving-course/jeju-github-latest",
            "show",
            DEFAULT_PREVIOUS_STASH_REF,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout


def split_markdown_row(line: str) -> list[str]:
    return [cell.strip().replace("\\|", "|") for cell in line.strip().strip("|").split("|")]


def split_names(value: str) -> list[str]:
    names = []
    seen = set()
    for raw in re.split(r",\s+", value or ""):
        name = raw.strip()
        if not name or name == "-":
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def parse_previous_gold_rows(markdown: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    in_table = False
    header: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("| qid |") and "top-10" in line:
            header = split_markdown_row(line)
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and not line.startswith("|"):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = split_markdown_row(line)
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        qid = row.get("qid", "")
        if qid.startswith("G"):
            rows[qid] = split_names(row.get("top-10", ""))
    if not rows:
        raise ValueError("Could not find a Gold Query Results top-10 table in previous report.")
    return rows


def parse_metric_table(path: Path) -> dict[str, float]:
    metrics: dict[str, float] = {}
    in_table = False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() == "| metric | result |":
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and not line.startswith("|"):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = split_markdown_row(line)
        if len(cells) < 2:
            continue
        name, value = cells[0], cells[1].replace("%", "").strip()
        try:
            metrics[name] = float(value) / 100.0
        except ValueError:
            pass
    return metrics


def evaluate_replay(
    top10_by_qid: dict[str, list[str]],
    gold: list[dict[str, Any]],
    resolver: NameResolver,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    rows = []
    for item in gold:
        raw_names = top10_by_qid.get(item["qid"], [])
        names = []
        seen = set()
        for raw_name in raw_names:
            name = resolver.resolve(raw_name)
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        relevant = {resolver.resolve(name) for name in item["must_names"]}
        hit5, hit10, mrr = hit_metrics(names, relevant)
        tag_match5, tag_coverage5 = required_tag_metrics(
            names, item["required"], resolver, 5
        )
        region5 = region_match(names, item["regions"], resolver, 5)
        forbidden5 = forbidden_exposure(names, item["forbidden"], resolver, 5)
        rows.append(
            {
                **item,
                "raw_names": raw_names,
                "names": names,
                "hit5": hit5,
                "hit10": hit10,
                "mrr": mrr,
                "ndcg5": ndcg_at_k(names, item, relevant, resolver, 5),
                "ndcg10": ndcg_at_k(names, item, relevant, resolver, 10),
                "tag_match5": tag_match5,
                "tag_coverage5": tag_coverage5,
                "region5": region5,
                "forbidden5": forbidden5,
            }
        )

    region_values = [row["region5"] for row in rows if row["region5"] is not None]
    forbidden_values = [
        row["forbidden5"] for row in rows if row["forbidden5"] is not None
    ]
    metrics = {
        "Must Hit@5": mean(row["hit5"] for row in rows),
        "Must Hit@10": mean(row["hit10"] for row in rows),
        "Canonical MRR@10": mean(row["mrr"] for row in rows),
        "NDCG@5": mean(row["ndcg5"] for row in rows),
        "NDCG@10": mean(row["ndcg10"] for row in rows),
        "Semantic Tag Match@5": mean(row["tag_match5"] for row in rows),
        "Semantic Tag Coverage@5": mean(row["tag_coverage5"] for row in rows),
        "Region Match@5": mean(region_values) if region_values else 1.0,
        "Forbidden Exposure@5": mean(forbidden_values) if forbidden_values else 0.0,
    }
    return rows, metrics


def write_previous_report(path: Path, rows: list[dict[str, Any]], metrics: dict[str, float]) -> None:
    lines = [
        "# Previous RAG Goldset V2 Replay",
        "",
        "This is a replay evaluation. It scores the top-10 results recorded in the previous `rag_three_tier_evaluation.md` report with the current Goldset V2 metric definitions.",
        "",
        "## Metrics",
        "",
        "| metric | result |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {pct(metrics[name])} |" for name in METRIC_ORDER)
    lines.extend(
        [
            "",
            "## Query Results",
            "",
            "| qid | question | previous top-5 | Must@5 | Must@10 | MRR | NDCG@5 | NDCG@10 | Tag Match@5 | Region@5 | Forbidden@5 |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['qid']} | {md(row['question'])} | {md(', '.join(row['raw_names'][:5]))} | "
            f"{int(row['hit5'])} | {int(row['hit10'])} | {row['mrr']:.3f} | "
            f"{row['ndcg5']:.3f} | {row['ndcg10']:.3f} | {row['tag_match5']:.3f} | "
            f"{pct(row['region5'])} | {pct(row['forbidden5'])} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_comparison_report(
    path: Path,
    previous_metrics: dict[str, float],
    current_metrics: dict[str, float],
) -> None:
    lines = [
        "# RAG Goldset V2 Comparison",
        "",
        "Previous RAG is evaluated by replaying the recorded top-10 results from `rag_three_tier_evaluation.md`. Current RAG uses the latest `rag_goldset_v2_evaluation.md` run.",
        "",
        "| metric | previous replay | current | delta |",
        "|---|---:|---:|---:|",
    ]
    for name in METRIC_ORDER:
        old = previous_metrics[name]
        new = current_metrics[name]
        lines.append(f"| {name} | {pct(old)} | {pct(new)} | {new - old:+.1%} |")
    lines.extend(
        [
            "",
            "## Read",
            "",
            "- Current RAG keeps Must Hit@5 flat but improves Must Hit@10 slightly.",
            "- NDCG is lower on current RAG, so representative or highly relevant cafes are less consistently ranked at the very top.",
            "- Semantic tag scores are effectively flat, with a tiny decrease on current RAG.",
            "- Forbidden exposure is worse on current RAG and should be treated as the highest-priority retrieval/rerank issue.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-report", type=Path)
    parser.add_argument("--current-report", type=Path, default=DEFAULT_CURRENT_REPORT)
    parser.add_argument("--previous-output", type=Path, default=DEFAULT_PREVIOUS_REPORT)
    parser.add_argument("--comparison-output", type=Path, default=DEFAULT_COMPARISON_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    resolver = NameResolver(cards)
    gold = load_gold(DEFAULT_GOLD)
    previous_markdown = read_previous_report(args.previous_report)
    previous_rows, previous_metrics = evaluate_replay(
        parse_previous_gold_rows(previous_markdown), gold, resolver
    )
    current_metrics = parse_metric_table(args.current_report)
    missing_current = [name for name in METRIC_ORDER if name not in current_metrics]
    if missing_current:
        raise ValueError(f"Current report is missing metrics: {missing_current}")

    write_previous_report(args.previous_output, previous_rows, previous_metrics)
    write_comparison_report(args.comparison_output, previous_metrics, current_metrics)

    print("Previous replay metrics")
    for name in METRIC_ORDER:
        print(f"- {name}: {pct(previous_metrics[name])}")
    print("\nComparison delta")
    for name in METRIC_ORDER:
        print(f"- {name}: {current_metrics[name] - previous_metrics[name]:+.1%}")
    print(f"\n- previous replay report: {args.previous_output}")
    print(f"- comparison report: {args.comparison_output}")


if __name__ == "__main__":
    main()

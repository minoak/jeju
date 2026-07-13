"""Evaluate the latest V4 /agent path with the existing Gold 50 contract.

The existing V1-V3 reports evaluate retrieval paths. This evaluator calls the
actual frontend path (`app.server.agent`) so judge, soft relaxation, optional
Kakao fallback, and synthesis are included in the run.

Usage:
    python eval/v4_agent_goldset_eval.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from goldset_v2_eval import (  # noqa: E402
    CARDS_PATH,
    NameResolver,
    forbidden_exposure,
    hit_metrics,
    load_gold,
    ndcg_at_k,
    pct,
    region_match,
    required_tag_metrics,
    result_names,
)


DEFAULT_GOLD = ROOT / "data" / "golden" / "golden_set.csv"
DEFAULT_REPORT = ROOT / "data" / "reports" / "rag_goldset_v4_agent_evaluation.md"

HISTORY = [
    {
        "version": "V1 Hybrid seed",
        "mode": "live seed adapter",
        "hit5": 0.420,
        "hit10": 0.500,
        "mrr": 0.241,
        "ndcg5": 0.297,
        "ndcg10": 0.377,
        "tag": 0.748,
        "region": 0.385,
        "forbidden": 0.243,
    },
    {
        "version": "V2 Three-tier",
        "mode": "previous replay",
        "hit5": 0.620,
        "hit10": 0.740,
        "mrr": 0.424,
        "ndcg5": 0.369,
        "ndcg10": 0.431,
        "tag": 0.675,
        "region": 0.600,
        "forbidden": 0.186,
    },
    {
        "version": "V3 Deterministic",
        "mode": "live /search",
        "hit5": 0.620,
        "hit10": 0.760,
        "mrr": 0.383,
        "ndcg5": 0.350,
        "ndcg10": 0.429,
        "tag": 0.672,
        "region": 0.708,
        "forbidden": 0.200,
    },
]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - pos) + ordered[high] * (pos - low)


def trace_has(response: dict[str, Any], step: str) -> bool:
    return any(row.get("step") == step for row in response.get("agent_trace") or [])


def evaluate(
    server: Any,
    gold: list[dict[str, Any]],
    resolver: NameResolver,
    top_k: int,
    determinism_sample: int,
) -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, Any]]]:
    rows = []
    cached = []
    for index, item in enumerate(gold, start=1):
        print(f"[v4] {index:02d}/{len(gold)} {item['qid']} {item['question']}", flush=True)
        started = time.perf_counter()
        error = ""
        try:
            response = server.agent(q=item["question"], k=top_k)
        except Exception as exc:  # Preserve the failed query in the report.
            error = f"{type(exc).__name__}: {exc}"
            response = {"cards": [], "agent_trace": [], "external": False}
        latency = time.perf_counter() - started

        names = result_names(response, resolver)
        relevant = {resolver.resolve(name) for name in item["must_names"]}
        hit5, hit10, mrr = hit_metrics(names, relevant)
        tag_match5, tag_coverage5 = required_tag_metrics(
            names, item["required"], resolver, 5
        )
        region5 = region_match(names, item["regions"], resolver, 5)
        forbidden5 = forbidden_exposure(names, item["forbidden"], resolver, 5)
        ndcg5 = ndcg_at_k(names, item, relevant, resolver, 5)
        ndcg10 = ndcg_at_k(names, item, relevant, resolver, 10)

        row = {
            **item,
            "names": names,
            "hit5": hit5,
            "hit10": hit10,
            "mrr": mrr,
            "ndcg5": ndcg5,
            "ndcg10": ndcg10,
            "tag_match5": tag_match5,
            "tag_coverage5": tag_coverage5,
            "region5": region5,
            "forbidden5": forbidden5,
            "latency": latency,
            "relaxed": trace_has(response, "완화"),
            "external": bool(response.get("external")),
            "empty": not names,
            "translation": response.get("translation") or [],
            "unresolved": response.get("unresolved") or [],
            "trace": response.get("agent_trace") or [],
            "error": error,
        }
        rows.append(row)
        cached.append(response)

    repeats = []
    for index, (item, first) in enumerate(
        zip(gold[:determinism_sample], cached[:determinism_sample]), start=1
    ):
        print(f"[repeat] {index:02d}/{determinism_sample} {item['qid']}", flush=True)
        try:
            second = server.agent(q=item["question"], k=top_k)
            first_names = result_names(first, resolver)[:top_k]
            second_names = result_names(second, resolver)[:top_k]
            repeats.append(
                {
                    "qid": item["qid"],
                    "same": first_names == second_names,
                    "first": first_names,
                    "second": second_names,
                }
            )
        except Exception as exc:
            repeats.append(
                {
                    "qid": item["qid"],
                    "same": False,
                    "first": result_names(first, resolver)[:top_k],
                    "second": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    region_values = [row["region5"] for row in rows if row["region5"] is not None]
    forbidden_values = [
        row["forbidden5"] for row in rows if row["forbidden5"] is not None
    ]
    latencies = [row["latency"] for row in rows]
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
        "Repeated Determinism@10": mean(float(row["same"]) for row in repeats)
        if repeats
        else 1.0,
        "Relaxation Query Rate": mean(float(row["relaxed"]) for row in rows),
        "External Fallback Query Rate": mean(float(row["external"]) for row in rows),
        "Empty Result Query Rate": mean(float(row["empty"]) for row in rows),
        "Error Query Rate": mean(float(bool(row["error"])) for row in rows),
        "Latency Mean Seconds": mean(latencies),
        "Latency P95 Seconds": percentile(latencies, 0.95),
    }
    return rows, metrics, repeats


def md(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def decimal3(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def write_report(
    path: Path,
    rows: list[dict[str, Any]],
    metrics: dict[str, float],
    repeats: list[dict[str, Any]],
    kakao_ready: bool,
) -> None:
    v4 = {
        "version": "V4 Agentic guarded",
        "mode": "live /agent" + ("" if kakao_ready else " (Kakao fallback unavailable)"),
        "hit5": metrics["Must Hit@5"],
        "hit10": metrics["Must Hit@10"],
        "mrr": metrics["Canonical MRR@10"],
        "ndcg5": metrics["NDCG@5"],
        "ndcg10": metrics["NDCG@10"],
        "tag": metrics["Semantic Tag Match@5"],
        "region": metrics["Region Match@5"],
        "forbidden": metrics["Forbidden Exposure@5"],
    }
    lines = [
        "# RAG Goldset V4 Agent Evaluation",
        "",
        "V4 frontend production path (`/agent`) was evaluated with the existing Gold 50 contract.",
        "The path includes internal retrieval, LLM judgment, optional soft relaxation, optional Kakao fallback, and LLM synthesis.",
        "",
        "## Environment",
        "",
        f"- Git commit: `91ac005`",
        f"- Gold questions: {len(rows)}",
        f"- Kakao fallback configured: **{'yes' if kakao_ready else 'no'}**",
        "- OpenAI embeddings and gpt-5-mini: live calls",
        "- Warning: V1/V2 are adapter or replay evaluations; V3/V4 are live paths.",
        "",
        "## V4 Metrics",
        "",
        "| metric | result |",
        "|---|---:|",
    ]
    percent_metrics = {
        "Must Hit@5",
        "Must Hit@10",
        "Canonical MRR@10",
        "NDCG@5",
        "NDCG@10",
        "Semantic Tag Match@5",
        "Semantic Tag Coverage@5",
        "Region Match@5",
        "Forbidden Exposure@5",
        "Repeated Determinism@10",
        "Relaxation Query Rate",
        "External Fallback Query Rate",
        "Empty Result Query Rate",
        "Error Query Rate",
    }
    for name, value in metrics.items():
        rendered = pct(value) if name in percent_metrics else f"{value:.2f}"
        lines.append(f"| {name} | {rendered} |")

    lines.extend(
        [
            "",
            "## Version Comparison",
            "",
            "| version | mode | Must@5 | Must@10 | MRR@10 | NDCG@5 | NDCG@10 | Tag Match@5 | Region@5 | Forbidden@5 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in [*HISTORY, v4]:
        lines.append(
            f"| {row['version']} | {row['mode']} | {pct(row['hit5'])} | "
            f"{pct(row['hit10'])} | {pct(row['mrr'])} | {pct(row['ndcg5'])} | "
            f"{pct(row['ndcg10'])} | {pct(row['tag'])} | {pct(row['region'])} | "
            f"{pct(row['forbidden'])} |"
        )

    lines.extend(
        [
            "",
            "## Agent Behavior",
            "",
            f"- Relaxed queries: {sum(row['relaxed'] for row in rows)} / {len(rows)}",
            f"- External fallback queries: {sum(row['external'] for row in rows)} / {len(rows)}",
            f"- Empty-result queries: {sum(row['empty'] for row in rows)} / {len(rows)}",
            f"- Failed queries: {sum(bool(row['error']) for row in rows)} / {len(rows)}",
            f"- Queries with unresolved terms: {sum(bool(row['unresolved']) for row in rows)} / {len(rows)}",
            "",
            "## Query Results",
            "",
            "| qid | question | top-5 | Must@5 | NDCG@5 | Tag Match@5 | Region@5 | Forbidden@5 | relax | external | latency(s) | unresolved |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['qid']} | {md(row['question'])} | {md(', '.join(row['names'][:5]))} | "
            f"{int(row['hit5'])} | {row['ndcg5']:.3f} | {row['tag_match5']:.3f} | "
            f"{decimal3(row['region5'])} | {decimal3(row['forbidden5'])} | "
            f"{int(row['relaxed'])} | {int(row['external'])} | {row['latency']:.2f} | "
            f"{md(', '.join(row['unresolved']))} |"
        )

    failed_repeats = [row for row in repeats if not row["same"]]
    lines.extend(["", "## Determinism Differences", ""])
    if not failed_repeats:
        lines.append("- None.")
    else:
        for row in failed_repeats:
            lines.append(
                f"- {row['qid']}: first={md(row['first'])}; second={md(row['second'])}"
            )

    suspicious = []
    for row in rows:
        for item in row["translation"]:
            if item.get("method") == "embedding" and item.get("score", 1.0) < 0.70:
                suspicious.append((row["qid"], item))
    lines.extend(["", "## Low-confidence Embedding Translations", ""])
    if not suspicious:
        lines.append("- None under 0.70.")
    else:
        for qid, item in suspicious[:50]:
            lines.append(
                f"- {qid}: `{item.get('input')}` -> `{item.get('tag')}` "
                f"({item.get('score')})"
            )

    errors = [row for row in rows if row["error"]]
    if errors:
        lines.extend(["", "## Errors", ""])
        for row in errors:
            lines.append(f"- {row['qid']}: {md(row['error'])}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--determinism-sample", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from app import server

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    resolver = NameResolver(cards)
    gold = load_gold(args.gold)
    rows, metrics, repeats = evaluate(
        server, gold, resolver, args.top_k, args.determinism_sample
    )
    kakao_ready = bool(server.env.get("KAKAO_KEY"))
    write_report(args.report, rows, metrics, repeats, kakao_ready)

    print("\nV4 agent metrics")
    for name, value in metrics.items():
        if "Seconds" in name:
            print(f"- {name}: {value:.2f}")
        else:
            print(f"- {name}: {pct(value)}")
    print(f"- report: {args.report}")


if __name__ == "__main__":
    main()

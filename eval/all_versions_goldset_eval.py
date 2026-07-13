"""Evaluate five RAG versions with the Goldset V2 metric rubric.

Version scope:
- V0: youtube-only reconstruction from chroma_smoke/smoke source=youtube.
- V1: blog/hybrid seed RAG from chroma_seed_test/seed_v2.
- V2: previous three-tier RAG replay from saved top-10 report.
- V3: current production metrics from rag_goldset_v2_evaluation.md.
- W2-W4: PPT architecture retrieval path route -> retrieve -> relax.

This evaluator keeps metric definitions identical to goldset_v2_eval.py. Some
versions are reconstructions or replays, so the report labels comparability.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import mean
from typing import Any

import chromadb
from openai import OpenAI


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "data" / "reports" / "rag_goldset_v2_all_versions.md"
DETAIL_DIR = ROOT / "data" / "reports"
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
from eval.replay_previous_rag_v2_eval import (  # noqa: E402
    parse_metric_table,
    parse_previous_gold_rows,
    read_previous_report,
)


def md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "/").replace("\n", " ")


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in (".env", ".github/.env"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def extract_name(meta: dict[str, Any], document: str | None) -> str:
    for key in ("spot_name", "cafe_name", "name"):
        value = meta.get(key)
        if value:
            return str(value)
    first = (document or "").splitlines()[0] if document else ""
    for prefix in ("카페명:", "카페명"):
        if first.startswith(prefix):
            return first.replace(prefix, "", 1).strip()
    return first.strip()


def score_top10_by_qid(
    top10_by_qid: dict[str, list[str]],
    gold: list[dict[str, Any]],
    resolver: NameResolver,
    version: str,
    mode: str,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    rows = []
    for item in gold:
        raw_names = top10_by_qid.get(item["qid"], [])
        names = []
        seen = set()
        for raw_name in raw_names:
            canon = resolver.resolve(raw_name)
            if canon and canon not in seen:
                seen.add(canon)
                names.append(canon)
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
                "version": version,
                "mode": mode,
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


def query_chroma_version(
    *,
    gold: list[dict[str, Any]],
    resolver: NameResolver,
    client: OpenAI,
    collection_path: Path,
    collection_name: str,
    version: str,
    mode: str,
    where: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    collection = chromadb.PersistentClient(path=str(collection_path)).get_collection(collection_name)
    questions = [item["question"] for item in gold]
    embeddings = client.embeddings.create(
        model="text-embedding-3-large",
        input=questions,
    ).data
    top10_by_qid: dict[str, list[str]] = {}
    for item, embedding in zip(gold, embeddings):
        query = {"query_embeddings": [embedding.embedding], "n_results": 80}
        if where:
            query["where"] = where
        result = collection.query(**query)
        raw_names = []
        seen = set()
        for meta, doc in zip(result["metadatas"][0], result["documents"][0]):
            name = extract_name(meta or {}, doc)
            canon = resolver.resolve(name)
            key = canon or name
            if key and key not in seen:
                seen.add(key)
                raw_names.append(name)
            if len(raw_names) >= 10:
                break
        top10_by_qid[item["qid"]] = raw_names
    return score_top10_by_qid(top10_by_qid, gold, resolver, version, mode)


def previous_replay_version(
    gold: list[dict[str, Any]], resolver: NameResolver
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    top10 = parse_previous_gold_rows(read_previous_report(None))
    return score_top10_by_qid(top10, gold, resolver, "V2 Three-tier RAG", "replay")


def w234_version(
    gold: list[dict[str, Any]], resolver: NameResolver, k: int
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    from app.router import route_query
    from app.retrieve import retrieve
    from app.relax import relax

    top10_by_qid: dict[str, list[str]] = {}
    for index, item in enumerate(gold, start=1):
        print(f"[w234-gold] {index:02d}/{len(gold)} {item['qid']} {item['question']}", flush=True)
        trace = route_query(item["question"])
        trace = retrieve(trace, k=k)
        if not trace.get("results") and (trace.get("intent") or {}).get("유형") != "조회":
            trace = relax(trace, k=k)
        top10_by_qid[item["qid"]] = [
            str(row.get("spot_name") or row.get("name") or "")
            for row in trace.get("results") or []
        ][:10]
    return score_top10_by_qid(
        top10_by_qid, gold, resolver, "W2-W4 PPT architecture", "live adapter"
    )


def write_detail(path: Path, rows: list[dict[str, Any]], metrics: dict[str, float]) -> None:
    lines = [
        f"# {rows[0]['version']} Goldset V2 Evaluation" if rows else "# Goldset V2 Evaluation",
        "",
        f"- mode: {rows[0]['mode'] if rows else '-'}",
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
            "| qid | question | top-5 | Must@5 | Must@10 | MRR | NDCG@5 | NDCG@10 | Tag Match@5 | Region@5 | Forbidden@5 |",
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


def write_summary(
    path: Path,
    all_metrics: dict[str, dict[str, float]],
    notes: dict[str, str],
) -> None:
    lines = [
        "# Goldset V2 All-version Evaluation",
        "",
        "Same Gold 50 rubric, different comparability modes. V0 is a runnability check because surviving youtube-only Chroma docs are missing, V2 is a replay, V3 and W2-W4 are live paths.",
        "",
        "| version | mode | " + " | ".join(METRIC_ORDER) + " |",
        "|---|---|" + "|".join("---:" for _ in METRIC_ORDER) + "|",
    ]
    for version, metrics in all_metrics.items():
        lines.append(
            f"| {version} | {notes[version]} | "
            + " | ".join(pct(metrics[name]) for name in METRIC_ORDER)
            + " |"
        )

    lines.extend(
        [
            "",
            "## Read",
            "",
            "- V0 is not strictly comparable: the surviving Chroma collection has 0 `source=youtube` documents, so the row is a coverage/runnability check, not a performance score.",
            "- V1 measures the hybrid seed corpus directly, so it tests seed quality more than the later production search stack.",
            "- V2 and V3 are the cleanest historical comparison: previous replay vs current production.",
            "- W2-W4 is the PPT architecture candidate path. It should be compared against V3 before promotion.",
            "- Use NDCG@5 and Forbidden Exposure@5 as the main go/no-go metrics for architecture changes.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--skip-live-w234", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    resolver = NameResolver(cards)
    gold = load_gold(DEFAULT_GOLD)
    env = load_env()
    client = OpenAI(api_key=env["OPENAI_KEY"])

    results: dict[str, tuple[list[dict[str, Any]], dict[str, float]]] = {}
    notes = {
        "V0 YouTube-only prototype": "not runnable: source=youtube docs missing",
        "V1 Hybrid seed RAG": "live seed adapter",
        "V2 Three-tier RAG": "previous replay",
        "V3 Current production": "current report",
        "W2-W4 PPT architecture": "live adapter",
    }

    print("[version] V0 YouTube-only reconstruction", flush=True)
    results["V0 YouTube-only prototype"] = query_chroma_version(
        gold=gold,
        resolver=resolver,
        client=client,
        collection_path=ROOT / "chroma_smoke",
        collection_name="smoke",
        version="V0 YouTube-only prototype",
        mode=notes["V0 YouTube-only prototype"],
        where={"source": "youtube"},
    )

    print("[version] V1 Hybrid seed", flush=True)
    results["V1 Hybrid seed RAG"] = query_chroma_version(
        gold=gold,
        resolver=resolver,
        client=client,
        collection_path=ROOT / "chroma_seed_test",
        collection_name="seed_v2",
        version="V1 Hybrid seed RAG",
        mode=notes["V1 Hybrid seed RAG"],
    )

    print("[version] V2 previous replay", flush=True)
    results["V2 Three-tier RAG"] = previous_replay_version(gold, resolver)

    print("[version] V3 current report", flush=True)
    current_metrics = parse_metric_table(ROOT / "data" / "reports" / "rag_goldset_v2_evaluation.md")
    results["V3 Current production"] = ([], current_metrics)

    if not args.skip_live_w234:
        print("[version] W2-W4 live adapter", flush=True)
        results["W2-W4 PPT architecture"] = w234_version(gold, resolver, 10)

    for version, (rows, metrics) in results.items():
        if rows:
            slug = (
                version.lower()
                .replace(" ", "_")
                .replace("-", "_")
                .replace("/", "_")
            )
            write_detail(DETAIL_DIR / f"rag_goldset_v2_{slug}.md", rows, metrics)

    all_metrics = {version: metrics for version, (_, metrics) in results.items()}
    write_summary(args.report, all_metrics, notes)

    print("\nAll-version Goldset V2")
    for version, metrics in all_metrics.items():
        print(f"\n[{version}] {notes[version]}")
        for name in METRIC_ORDER:
            print(f"- {name}: {pct(metrics[name])}")
    print(f"\n- report: {args.report}")


if __name__ == "__main__":
    main()

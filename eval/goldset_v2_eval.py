"""Evaluate the current Jeju cafe search with the 50-question gold set.

This evaluator is intentionally external to app/ and pipeline/. It does not
rewrite cards, tags, Chroma, or runtime search behavior.

Checks:
- Gold 50: Must Hit@5/@10, Canonical MRR, NDCG@5/@10,
  semantic tag/region match, forbidden exposure.
- W2-W4: the existing eight routing/relaxation/honest-zero scenarios.
- Invariants: closed/non-serving leakage, place_id duplicates, alias lookup,
  and repeated-query determinism.

Usage:
    python eval/goldset_v2_eval.py
    python eval/goldset_v2_eval.py --skip-w234
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLD = ROOT / "data" / "golden" / "golden_set.csv"
DEFAULT_REPORT = ROOT / "data" / "reports" / "rag_goldset_v2_evaluation.md"
CARDS_PATH = ROOT / "data" / "processed" / "cards.json"

# Evaluation-only semantic normalization. Source data and runtime tags stay intact.
TAG_CANON = {
    "조용": "조용함",
    "애견": "애견동반",
    "테라스": "야외석",
    "사진": "포토존",
    "인생샷": "포토존",
    "로스터리": "핸드드립",
    "원두": "핸드드립",
    "바다": "오션뷰",
    "해변": "오션뷰",
}
REGION_CANON = {"서귀포": "서귀포시내"}


def split_pipe(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def norm_name(value: str | None) -> str:
    return re.sub(r"[^\w가-힣]", "", (value or "").lower())


def canon_tag(tag: str) -> str:
    return TAG_CANON.get(tag.strip(), tag.strip())


def canon_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(canon_tag(tag) for tag in tags if tag.strip()))


def load_gold(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["must_names"] = split_pipe(row.get("must_include"))
        row["regions"] = [
            REGION_CANON.get(region, region)
            for region in split_pipe(row.get("required_region"))
        ]
        row["required"] = canon_tags(split_pipe(row.get("required_tags")))
        row["optional"] = canon_tags(split_pipe(row.get("optional_tags")))
        row["forbidden"] = canon_tags(split_pipe(row.get("forbidden_tags")))

        # G012 is impossible as authored: "활기" is absent from cards and the
        # active runtime tag dictionary. Apply the agreed evaluator-only rubric.
        if row.get("qid") == "G012":
            row["required"] = ["핫플"]
            row["optional"] = canon_tags(["웨이팅", "사진"])
            row["evaluation_override"] = (
                "required=핫플; optional=웨이팅|사진; unsupported 활기 removed"
            )
        else:
            row["evaluation_override"] = ""
    return rows


class NameResolver:
    def __init__(self, cards: list[dict[str, Any]]) -> None:
        self.cards = {card["name"]: card for card in cards}
        self.index: dict[str, str] = {}
        for card in cards:
            canon = card["name"]
            for label in [canon, *(card.get("aliases") or [])]:
                key = norm_name(label)
                if key:
                    self.index.setdefault(key, canon)

    def resolve(self, value: str | None) -> str:
        key = norm_name(value)
        return self.index.get(key, value or "")

    def card(self, value: str | None) -> dict[str, Any]:
        return self.cards.get(self.resolve(value), {})


def result_names(response: dict[str, Any], resolver: NameResolver) -> list[str]:
    names = []
    seen = set()
    for card in response.get("cards") or []:
        canon = resolver.resolve(card.get("spot_name") or card.get("name"))
        if canon and canon not in seen:
            seen.add(canon)
            names.append(canon)
    return names


def card_tag_set(card: dict[str, Any]) -> set[str]:
    return set(canon_tags([str(tag) for tag in card.get("tags") or []]))


def required_tag_metrics(
    names: list[str], required: list[str], resolver: NameResolver, k: int
) -> tuple[float, float]:
    if not required:
        return 1.0, 1.0
    selected = names[:k]
    if not selected:
        return 0.0, 0.0
    matched_pairs = 0
    covered = set()
    for name in selected:
        tags = card_tag_set(resolver.card(name))
        for tag in required:
            if tag in tags:
                matched_pairs += 1
                covered.add(tag)
    return matched_pairs / (len(selected) * len(required)), len(covered) / len(required)


def region_match(
    names: list[str], regions: list[str], resolver: NameResolver, k: int
) -> float | None:
    if not regions:
        return None
    selected = names[:k]
    if not selected:
        return 0.0
    matches = 0
    wanted = set(regions)
    for name in selected:
        card = resolver.card(name)
        candidates = {
            REGION_CANON.get(str(card.get("region_bucket") or ""), str(card.get("region_bucket") or "")),
            REGION_CANON.get(str(card.get("region_fine") or ""), str(card.get("region_fine") or "")),
        }
        if wanted & candidates:
            matches += 1
    return matches / len(selected)


def has_forbidden(card: dict[str, Any], forbidden: list[str]) -> bool:
    if not forbidden:
        return False
    tags = card_tag_set(card)
    caution_text = " ".join(str(item) for item in card.get("caution") or [])
    for tag in forbidden:
        if tag in tags or tag in caution_text:
            return True
    return False


def forbidden_exposure(
    names: list[str], forbidden: list[str], resolver: NameResolver, k: int
) -> float | None:
    if not forbidden:
        return None
    selected = names[:k]
    if not selected:
        return 0.0
    return sum(has_forbidden(resolver.card(name), forbidden) for name in selected) / len(selected)


def card_region_matches(card: dict[str, Any], regions: list[str]) -> bool:
    if not regions:
        return True
    wanted = set(regions)
    candidates = {
        REGION_CANON.get(str(card.get("region_bucket") or ""), str(card.get("region_bucket") or "")),
        REGION_CANON.get(str(card.get("region_fine") or ""), str(card.get("region_fine") or "")),
    }
    return bool(wanted & candidates)


def relevance_grade(
    name: str,
    item: dict[str, Any],
    relevant: set[str],
    resolver: NameResolver,
) -> float:
    """Gold-informed graded relevance for NDCG.

    The gold set is not exhaustive, so this combines representative cafe hits
    with intent evidence from required tags, optional tags, region, and
    forbidden tags. Scores are capped to the common 0-3 relevance scale.
    """
    card = resolver.card(name)
    if not card:
        return 0.0
    if has_forbidden(card, item["forbidden"]):
        return 0.0

    tags = card_tag_set(card)
    required = item["required"]
    optional = item["optional"]
    required_score = (
        sum(1 for tag in required if tag in tags) / len(required)
        if required
        else 1.0
    )
    optional_score = (
        sum(1 for tag in optional if tag in tags) / len(optional)
        if optional
        else 0.0
    )

    score = 0.0
    if name in relevant:
        score += 1.4
    score += required_score
    score += 0.4 if card_region_matches(card, item["regions"]) else -0.4
    score += min(0.2, 0.2 * optional_score)

    if score <= 0.4:
        return 0.0
    return min(3.0, score)


def dcg(grades: list[float]) -> float:
    from math import log2

    return sum(
        ((2**grade) - 1) / log2(rank + 1)
        for rank, grade in enumerate(grades, start=1)
    )


def ndcg_at_k(
    names: list[str],
    item: dict[str, Any],
    relevant: set[str],
    resolver: NameResolver,
    k: int,
) -> float:
    ranked_grades = [
        relevance_grade(name, item, relevant, resolver) for name in names[:k]
    ]
    candidate_names = list(dict.fromkeys([*names[:k], *relevant]))
    ideal_grades = sorted(
        (relevance_grade(name, item, relevant, resolver) for name in candidate_names),
        reverse=True,
    )[:k]
    ideal = dcg(ideal_grades)
    return dcg(ranked_grades) / ideal if ideal > 0 else 0.0


def hit_metrics(names: list[str], relevant: set[str]) -> tuple[float, float, float]:
    rank = next((idx + 1 for idx, name in enumerate(names[:10]) if name in relevant), None)
    return (
        float(rank is not None and rank <= 5),
        float(rank is not None and rank <= 10),
        1.0 / rank if rank else 0.0,
    )


def run_gold(
    server: Any,
    gold: list[dict[str, Any]],
    resolver: NameResolver,
    top_k: int,
    determinism_sample: int,
) -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, Any]]]:
    rows = []
    cached: list[dict[str, Any]] = []
    for index, item in enumerate(gold, start=1):
        print(f"[gold] {index:02d}/{len(gold)} {item['qid']} {item['question']}", flush=True)
        response = server.search(q=item["question"], k=top_k, explain=0)
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
        }
        rows.append(row)
        cached.append(response)

    repeat_rows = []
    for item, first in zip(gold[:determinism_sample], cached[:determinism_sample]):
        second = server.search(q=item["question"], k=top_k, explain=0)
        first_names = result_names(first, resolver)[:top_k]
        second_names = result_names(second, resolver)[:top_k]
        repeat_rows.append(
            {
                "qid": item["qid"],
                "same": first_names == second_names,
                "first": first_names,
                "second": second_names,
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
        f"Repeated Determinism@{top_k} ({len(repeat_rows)} queries)": mean(
            float(row["same"]) for row in repeat_rows
        )
        if repeat_rows
        else 1.0,
    }
    return rows, metrics, repeat_rows


def run_w234() -> tuple[list[dict[str, Any]], float]:
    path = ROOT / "eval" / "w234_검증.py"
    spec = importlib.util.spec_from_file_location("w234_eval", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rows = []
    for num, slug, query, expected, check in module.SCENARIOS:
        print(f"[w234] {num}/8 {slug}: {query}", flush=True)
        try:
            trace = module.run_pipeline(query)
            checks = check(trace)
            ok = all(result for _, result in checks)
            rows.append(
                {
                    "number": num,
                    "slug": slug,
                    "query": query,
                    "expected": expected,
                    "ok": ok,
                    "checks": checks,
                    "results": len(trace.get("results") or []),
                    "relaxations": len(trace.get("relaxation") or []),
                    "router": trace.get("router_method"),
                    "honest_zero": bool((trace.get("answer") or {}).get("honest_zero")),
                    "quote_violations": len(trace.get("quote_violations") or []),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "number": num,
                    "slug": slug,
                    "query": query,
                    "expected": expected,
                    "ok": False,
                    "checks": [(f"{type(exc).__name__}: {exc}", False)],
                    "results": 0,
                    "relaxations": 0,
                    "router": "exception",
                    "honest_zero": False,
                    "quote_violations": 0,
                }
            )
    return rows, mean(float(row["ok"]) for row in rows)


def invariant_metrics(
    server: Any,
    cards: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
    resolver: NameResolver,
) -> dict[str, Any]:
    pid_counts = Counter(
        str(card.get("place_id"))
        for card in cards
        if card.get("place_id") not in (None, "")
    )
    duplicate_pids = {pid: count for pid, count in pid_counts.items() if count > 1}

    # Test the aliases that the runtime deliberately admitted to its lookup
    # index. Raw aliases can be excluded by design when they are non-serving or
    # consist only of regional/category stopwords such as "애월 카페".
    aliases = list(server.NAME_IDX.items())
    alias_ok = 0
    alias_fail = []
    for normalized_alias, expected in aliases:
        found = server.name_lookup(normalized_alias, limit=8)
        ok = expected in found
        alias_ok += int(ok)
        if not ok and len(alias_fail) < 20:
            alias_fail.append(
                {
                    "alias": normalized_alias,
                    "expected": expected,
                    "found": found,
                }
            )

    returned = [name for row in gold_rows for name in row["names"][:10]]
    closed_leaks = [name for name in returned if resolver.card(name).get("closed")]
    nonserving_leaks = [
        name
        for name in returned
        if not resolver.card(name).get("closed")
        and resolver.card(name).get("판정") != "유지"
    ]
    return {
        "cards": len(cards),
        "place_ids": len(pid_counts),
        "duplicate_place_ids": len(duplicate_pids),
        "duplicate_place_id_detail": duplicate_pids,
        "alias_checks": len(aliases),
        "alias_success_rate": alias_ok / len(aliases) if aliases else 1.0,
        "alias_failures": alias_fail,
        "closed_leakage_count": len(closed_leaks),
        "nonserving_leakage_count": len(nonserving_leaks),
        "returned_top10_count": len(returned),
    }


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def md(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def write_report(
    path: Path,
    gold_rows: list[dict[str, Any]],
    gold_metrics: dict[str, float],
    repeats: list[dict[str, Any]],
    w234_rows: list[dict[str, Any]],
    w234_rate: float | None,
    invariants: dict[str, Any],
) -> None:
    lines = [
        "# RAG Goldset V2 Evaluation",
        "",
        "현재 `cards.json` + `app.server.search`를 대상으로 평가했다. "
        "태그 정규화와 G012 보정은 평가기에서만 적용했으며 원본 데이터와 검색 코드는 수정하지 않았다.",
        "",
        "## Evaluation Contract",
        "",
        "- Gold: 50 human-authored recommendation queries",
        "- Retrieval: current production path (`app.server.search`, top-10)",
        "- NDCG relevance grade: representative cafe + required tags + region + optional tags; forbidden tags force zero relevance.",
        "- Semantic normalization: 조용→조용함, 애견→애견동반, 테라스→야외석, "
        "사진/인생샷→포토존, 로스터리/원두→핸드드립, 바다/해변→오션뷰",
        "- G012 override: required=핫플, optional=웨이팅/사진, unsupported `활기` excluded",
        "- W2-W4 is reported separately because it is not wired into `server.py` yet.",
        "",
        "## Gold Metrics",
        "",
        "| metric | result |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {pct(value)} |" for name, value in gold_metrics.items())
    lines.extend(
        [
            "",
            "## Invariants",
            "",
            "| check | result |",
            "|---|---:|",
            f"| Canonical cards | {invariants['cards']} |",
            f"| Cards with place_id | {invariants['place_ids']} |",
            f"| Duplicate place_id groups | {invariants['duplicate_place_ids']} |",
            f"| Registered alias lookup success | {pct(invariants['alias_success_rate'])} "
            f"({invariants['alias_checks']} checks) |",
            f"| Closed leakage in Gold top-10 | {invariants['closed_leakage_count']} |",
            f"| Non-serving leakage in Gold top-10 | {invariants['nonserving_leakage_count']} |",
            "",
            "## W2-W4 Scenarios",
            "",
        ]
    )
    if w234_rate is None:
        lines.append("- Skipped by command option.")
    else:
        lines.extend(
            [
                f"- Scenario pass rate: **{pct(w234_rate)}**",
                "",
                "| # | scenario | query | router | results | relax | honest zero | quote removals | pass |",
                "|---:|---|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in w234_rows:
            lines.append(
                f"| {row['number']} | {md(row['slug'])} | {md(row['query'])} | "
                f"{row['router']} | {row['results']} | {row['relaxations']} | "
                f"{int(row['honest_zero'])} | {row['quote_violations']} | "
                f"{'PASS' if row['ok'] else 'FAIL'} |"
            )
        failed_w234 = [row for row in w234_rows if not row["ok"]]
        if failed_w234:
            lines.extend(["", "### W2-W4 Failed Checks", ""])
            for row in failed_w234:
                failed_checks = [label for label, ok in row["checks"] if not ok]
                lines.append(
                    f"- Scenario {row['number']} `{row['slug']}`: "
                    f"{md('; '.join(failed_checks))}"
                )

    lines.extend(
        [
            "",
            "## Gold Query Results",
            "",
            "| qid | type | question | top-5 | Must@5 | Must@10 | MRR | NDCG@5 | "
            "NDCG@10 | Tag Match@5 | Tag Coverage@5 | Region@5 | Forbidden@5 |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in gold_rows:
        lines.append(
            f"| {row['qid']} | {md(row['type'])} | {md(row['question'])} | "
            f"{md(', '.join(row['names'][:5]))} | {int(row['hit5'])} | "
            f"{int(row['hit10'])} | {row['mrr']:.3f} | {row['ndcg5']:.3f} | "
            f"{row['ndcg10']:.3f} | {row['tag_match5']:.3f} | "
            f"{row['tag_coverage5']:.3f} | {pct(row['region5'])} | "
            f"{pct(row['forbidden5'])} |"
        )

    failed_repeats = [row for row in repeats if not row["same"]]
    lines.extend(
        [
            "",
            "## Determinism Differences",
            "",
        ]
    )
    if not failed_repeats:
        lines.append("- None.")
    else:
        for row in failed_repeats:
            lines.append(
                f"- {row['qid']}: first={md(row['first'])}; second={md(row['second'])}"
            )

    lines.extend(["", "## Evaluator-only Overrides", ""])
    overrides = [row for row in gold_rows if row["evaluation_override"]]
    lines.extend(
        [
            f"- {row['qid']}: {row['evaluation_override']}"
            for row in overrides
        ]
        or ["- None."]
    )

    if invariants["alias_failures"]:
        lines.extend(["", "## Alias Lookup Failures", ""])
        for row in invariants["alias_failures"]:
            lines.append(
                f"- `{row['alias']}` → expected `{row['expected']}`, got `{row['found']}`"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--determinism-sample", type=int, default=10)
    parser.add_argument("--skip-w234", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.gold.exists():
        raise FileNotFoundError(f"Gold set not found: {args.gold}")
    if not CARDS_PATH.exists():
        raise FileNotFoundError(f"Canonical cards not found: {CARDS_PATH}")

    sys.path.insert(0, str(ROOT))
    from app import server  # Import after ROOT is on sys.path.

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    resolver = NameResolver(cards)
    gold = load_gold(args.gold)

    gold_rows, gold_metrics, repeats = run_gold(
        server, gold, resolver, args.top_k, args.determinism_sample
    )
    if args.skip_w234:
        w234_rows, w234_rate = [], None
    else:
        w234_rows, w234_rate = run_w234()
    invariants = invariant_metrics(server, cards, gold_rows, resolver)

    write_report(
        args.report,
        gold_rows,
        gold_metrics,
        repeats,
        w234_rows,
        w234_rate,
        invariants,
    )
    print("\nGold metrics")
    for name, value in gold_metrics.items():
        print(f"- {name}: {pct(value)}")
    if w234_rate is not None:
        print(f"- W2-W4 scenario pass: {pct(w234_rate)}")
    print(f"- duplicate place_id groups: {invariants['duplicate_place_ids']}")
    print(f"- alias lookup success: {pct(invariants['alias_success_rate'])}")
    print(f"- closed leakage: {invariants['closed_leakage_count']}")
    print(f"- non-serving leakage: {invariants['nonserving_leakage_count']}")
    print(f"- report: {args.report}")


if __name__ == "__main__":
    main()

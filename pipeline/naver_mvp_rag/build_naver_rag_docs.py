# -*- coding: utf-8 -*-
"""Build minimal Naver Blog based RAG docs for the Jeju cafe MVP.

Only user-query style tags are embedded. Operational hints such as parking,
waiting, holidays, and closure hints are kept in ``caution``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "processed" / "\ub124\uc774\ubc84 \uc815\uc81c.jsonl"
DOCS_OUT = ROOT / "data" / "processed" / "naver_rag_docs.jsonl"
ALIASES_OUT = ROOT / "data" / "processed" / "naver_tag_aliases.json"
REPORT_OUT = ROOT / "data" / "reports" / "naver_rag_report.md"

TAG_ALIASES: dict[str, list[str]] = {
    "\uc870\uc6a9": ["\uc870\uc6a9", "\uc870\uc6a9\ud55c", "\ud55c\uc801", "\ucc28\ubd84", "\uace0\uc988\ub109", "\uc5ec\uc720\ub85c\uc6b4"],
    "\ub178\uc744": ["\ub178\uc744", "\uc11d\uc591", "\uc120\uc14b", "\uc77c\ubab0"],
    "\ud578\ub4dc\ub4dc\ub9bd": ["\ud578\ub4dc\ub4dc\ub9bd", "\ub4dc\ub9bd\ucee4\ud53c", "\ub4dc\ub9bd \ucee4\ud53c", "\ud544\ud130\ucee4\ud53c", "\ube0c\ub8e8\uc789"],
    "\ub85c\uc2a4\ud130\ub9ac": ["\ub85c\uc2a4\ud130\ub9ac", "\ub85c\uc2a4\ud305", "\uc9c1\uc811 \ub85c\uc2a4\ud305"],
    "\uc624\uc158\ubdf0": ["\uc624\uc158\ubdf0", "\ubc14\ub2e4\ubdf0", "\ud574\uc548\ubdf0", "\ubc14\ub2e4 \ubcf4\uc774", "\ubc14\ub2e4\uac00 \ubcf4\uc774"],
    "\uc0b0\ubdf0": ["\uc0b0\ubdf0", "\uc232\ubdf0", "\uc624\ub984\ubdf0", "\ud55c\ub77c\uc0b0"],
    "\uac10\uc131": ["\uac10\uc131", "\ubd84\uc704\uae30", "\ubb34\ub4dc", "\uc81c\uc8fc\uac10\uc131", "\uc608\uc05c", "\uc778\ud14c\ub9ac\uc5b4"],
    "\ub85c\uceec": ["\ub85c\uceec", "\ud604\uc9c0\uc778", "\ub3d9\ub124", "\uc81c\uc8fc\uc2a4\ub7ec\uc6b4", "\uc81c\uc8fc\ub85c\uceec"],
    "\ub300\ud615": ["\ub300\ud615", "\ub113\uc740", "\uc88c\uc11d \ub9ce", "\uaddc\ubaa8", "\ub300\ud615\uce74\ud398"],
    "\uac00\uc871": ["\uac00\uc871", "\ud0a4\uc988\uce5c\ud654", "\uc544\uc774\uc640", "\uc544\uae30\uc640", "\uac00\uc871\ub07c\ub9ac"],
    "\ud63c\uc790": ["\ud63c\uc790", "\ud63c\uce74\ud398", "\uc791\uc5c5", "\ucc45 \uc77d", "\ub3c5\uc11c"],
    "\uc228\uc740": ["\uc228\uc740", "\ub35c \uc54c\ub824\uc9c4", "\ud55c\uc801\ud55c", "\uace8\ubaa9"],
    "\uc0ac\uc9c4": ["\uc0ac\uc9c4", "\ud3ec\ud1a0", "\ud3ec\ud1a0\uc874", "\uc0ac\uc9c4\ub9db\uc9d1", "\uc0ac\uc9c4 \ucc0d\uae30"],
    "\ub514\uc800\ud2b8": ["\ub514\uc800\ud2b8", "\ucf00\uc774\ud06c", "\ud0c0\ub974\ud2b8", "\ud478\ub529", "\uae4c\ub204\ub808"],
    "\ud574\ubcc0": ["\ud574\ubcc0", "\ud574\uc218\uc695\uc7a5", "\ubc14\ub2f7\uac00", "\ud574\uc548"],
    "\ube0c\ub7f0\uce58": ["\ube0c\ub7f0\uce58", "\uc0cc\ub4dc\uc704\uce58", "\ud50c\ub808\uc774\ud2b8", "\uc2dd\uc0ac \uac00\ub2a5"],
    "\ubca0\uc774\ucee4\ub9ac": ["\ubca0\uc774\ucee4\ub9ac", "\ube75", "\uc18c\uae08\ube75", "\ud06c\ub8e8\uc544\uc0c1", "\ud398\uc774\uc2a4\ud2b8\ub9ac"],
    "\ubc14\ub2e4": ["\ubc14\ub2e4", "\ud574\uc548", "\ubc14\ub2f7\uac00", "\ubc14\ub2e4 \uadfc\ucc98"],
    "\uc6d0\ub450": ["\uc6d0\ub450", "\uc2a4\ud398\uc15c\ud2f0", "\ucee4\ud53c\ub9db", "\uc0b0\ubbf8", "\uace0\uc18c\ud55c"],
    "\ub8e8\ud504\ud0d1": ["\ub8e8\ud504\ud0d1", "\uc625\uc0c1", "\uc625\uc0c1\uc815\uc6d0"],
    "\uc560\uacac": ["\uc560\uacac\ub3d9\ubc18", "\ubc18\ub824\uacac", "\ubc18\ub824\ub3d9\ubb3c", "\uac15\uc544\uc9c0"],
    "\uc2dc\uadf8\ub2c8\ucc98": ["\uc2dc\uadf8\ub2c8\ucc98", "\ub300\ud45c\uba54\ub274", "\ub300\ud45c \uba54\ub274", "\uc778\uae30\uba54\ub274", "\uc778\uae30 \uba54\ub274"],
    "\uc778\uc0dd\uc0f7": ["\uc778\uc0dd\uc0f7", "sns \uc0ac\uc9c4", "SNS \uc0ac\uc9c4", "\ubdf0\ub9db\uc9d1"],
    "\ud14c\ub77c\uc2a4": ["\ud14c\ub77c\uc2a4", "\uc57c\uc678\uc11d", "\uc57c\uc678 \uc88c\uc11d", "\ub9c8\ub2f9", "\uc815\uc6d0"],
    "\ud3b8\uc548": ["\ud3b8\uc548", "\uc26c\uae30 \uc88b", "\uc624\ub798 \uba38\ubb3c", "\uc544\ub291", "\ud3b8\ud55c"],
    "\ud65c\uae30": ["\ud65c\uae30", "\ubd90\ube44", "\uc0ac\ub78c \ub9ce", "\ubd81\uc801", "\ud65c\uae30\ucc2c"],
    "\ud56b\ud50c": ["\ud56b\ud50c", "\uc778\uae30", "\uc720\uba85", "\uc2e0\uc0c1", "\uc694\uc998 \ub728\ub294"],
}

CAUTION_ALIASES: dict[str, list[str]] = {
    "\uc8fc\ucc28": ["\uc8fc\ucc28"],
    "\uc6e8\uc774\ud305": ["\uc6e8\uc774\ud305", "\ub300\uae30", "\uc904\uc11c\uae30", "\uc904\uc11c\uc11c"],
    "\ub178\ud0a4\uc988\uc874": ["\ub178\ud0a4\uc988\uc874"],
    "\uc601\uc5c5\uc885\ub8cc": ["\ud3d0\uc5c5", "\uc601\uc5c5\uc885\ub8cc", "\ubb38 \ub2eb"],
    "\ud734\ubb34\uc8fc\uc758": ["\ud734\ubb34", "\ud734\ubb34\uc77c \ud655\uc778"],
    "\ud63c\uc7a1\uac00\ub2a5": ["\ud63c\uc7a1", "\ubd90\ube54", "\ub9cc\uc11d", "\uc6e8\uc774\ud305"],
}

GENERIC_NAMES = {
    "",
    "\uc81c\uc8fc",
    "\uce74\ud398",
    "\uc81c\uc8fc\uce74\ud398",
    "\uac10\uc131\uce74\ud398",
    "\uc624\uc158\ubdf0\uce74\ud398",
    "\uc81c\uc8fc\ub3c4",
}

NON_RECOMMENDATION_TAGS = set(CAUTION_ALIASES)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value: Any) -> str:
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]", "", clean_text(value).lower())


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if isinstance(value, str):
        return [clean_text(item) for item in re.split(r"[,|/]", value) if clean_text(item)]
    return [clean_text(value)]


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def parse_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def stable_doc_id(name: str) -> str:
    digest = hashlib.sha1(normalize_name(name).encode("utf-8")).hexdigest()[:10]
    return f"naver_{digest}"


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows = []
    bad_rows = 0
    with path.open(encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                bad_rows += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad_rows += 1
    return rows, bad_rows


def source_text(row: dict[str, Any]) -> str:
    fields = as_list(row.get("tags_blog")) + as_list(row.get("tags_extra")) + [clean_text(row.get("summary_blog"))]
    return " ".join(fields)


def has_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def extract_tags(row: dict[str, Any]) -> list[str]:
    text = source_text(row)
    tags = [tag for tag, terms in TAG_ALIASES.items() if has_any(text, terms)]

    # Waiting/parking/holiday signals are caution only. Also, waiting alone
    # must not become a "hot place" recommendation tag.
    return [tag for tag in tags if tag not in NON_RECOMMENDATION_TAGS]


def extract_caution(row: dict[str, Any]) -> list[str]:
    text = source_text(row)
    caution = [tag for tag, terms in CAUTION_ALIASES.items() if has_any(text, terms)]
    if parse_bool(row.get("closed_hint")) and "\uc601\uc5c5\uc885\ub8cc" not in caution:
        caution.append("\uc601\uc5c5\uc885\ub8cc")
    return caution


def mood_phrases(tags: list[str]) -> list[str]:
    tagset = set(tags)
    combos = [
        ({"\uc624\uc158\ubdf0", "\uac10\uc131"}, "\ubc14\ub2e4 \ubcf4\uc774\ub294 \uac10\uc131 \uce74\ud398"),
        ({"\uc624\uc158\ubdf0", "\uc0ac\uc9c4"}, "\uc0ac\uc9c4 \ucc0d\uae30 \uc88b\uc740 \uc624\uc158\ubdf0 \uce74\ud398"),
        ({"\ub178\uc744", "\uc624\uc158\ubdf0"}, "\ub178\uc744 \ubcf4\uae30 \uc88b\uc740 \ubc14\ub2e4 \uc804\ub9dd \uce74\ud398"),
        ({"\uc870\uc6a9", "\ud63c\uc790"}, "\ud63c\uc790 \uc870\uc6a9\ud788 \uc26c\uae30 \uc88b\uc740 \uce74\ud398"),
        ({"\uac00\uc871", "\ub300\ud615"}, "\uac00\uc871\uacfc \uac00\uae30 \uc88b\uc740 \ub113\uc740 \uce74\ud398"),
        ({"\uc560\uacac", "\ud14c\ub77c\uc2a4"}, "\ubc18\ub824\uacac\uacfc \ud568\uaed8 \uac00\uae30 \uc88b\uc740 \ud14c\ub77c\uc2a4 \uce74\ud398"),
        ({"\ube0c\ub7f0\uce58", "\ubc14\ub2e4"}, "\ubc14\ub2e4 \uadfc\ucc98 \ube0c\ub7f0\uce58 \uce74\ud398"),
        ({"\ubca0\uc774\ucee4\ub9ac", "\ub514\uc800\ud2b8"}, "\ubca0\uc774\ucee4\ub9ac\uc640 \ub514\uc800\ud2b8\uac00 \uc5b8\uae09\ub418\ub294 \uce74\ud398"),
        ({"\ud578\ub4dc\ub4dc\ub9bd", "\ub85c\uc2a4\ud130\ub9ac"}, "\ud578\ub4dc\ub4dc\ub9bd\uacfc \ub85c\uc2a4\ud130\ub9ac \ucee4\ud53c\uac00 \uc5b8\uae09\ub418\ub294 \uce74\ud398"),
        ({"\uc0b0\ubdf0", "\uc870\uc6a9"}, "\uc0b0\ubdf0 \ubcf4\uba70 \uc870\uc6a9\ud788 \uc26c\uae30 \uc88b\uc740 \uce74\ud398"),
        ({"\uac10\uc131", "\uc0ac\uc9c4"}, "\uc0ac\uc9c4 \ucc0d\uae30 \uc88b\uc740 \uac10\uc131 \uce74\ud398"),
        ({"\ub85c\uceec", "\uc228\uc740"}, "\uc228\uc740 \ub85c\uceec \uac10\uc131 \uce74\ud398"),
        ({"\ub8e8\ud504\ud0d1", "\ubc14\ub2e4"}, "\ubc14\ub2e4\ub97c \ub290\ub07c\uae30 \uc88b\uc740 \ub8e8\ud504\ud0d1 \uce74\ud398"),
    ]
    phrases = [phrase for required, phrase in combos if required <= tagset]
    if not phrases:
        fallback = [
            ("\uc624\uc158\ubdf0", "\ubc14\ub2e4 \uc804\ub9dd\uc774 \uc5b8\uae09\ub418\ub294 \uce74\ud398"),
            ("\ub514\uc800\ud2b8", "\ub514\uc800\ud2b8\uac00 \uc5b8\uae09\ub418\ub294 \uce74\ud398"),
            ("\ubca0\uc774\ucee4\ub9ac", "\ubca0\uc774\ucee4\ub9ac\uac00 \uc5b8\uae09\ub418\ub294 \uce74\ud398"),
            ("\uc870\uc6a9", "\uc870\uc6a9\ud55c \ubd84\uc704\uae30\uac00 \uc5b8\uae09\ub418\ub294 \uce74\ud398"),
            ("\uac10\uc131", "\uac10\uc131\uc801\uc778 \ubd84\uc704\uae30\uac00 \uc5b8\uae09\ub418\ub294 \uce74\ud398"),
        ]
        phrases.extend(phrase for tag, phrase in fallback if tag in tagset)
    return phrases[:5]


def answer_text(tags: list[str], phrases: list[str]) -> str:
    tag_text = ", ".join(tags[:5])
    if tag_text:
        first = f"\ube14\ub85c\uadf8 \uc694\uc57d \uae30\uc900\uc73c\ub85c {tag_text} \uad00\ub828 \uc5b8\uae09\uc774 \ud655\uc778\ub429\ub2c8\ub2e4."
    else:
        first = "\ube14\ub85c\uadf8 \uc694\uc57d \uae30\uc900\uc73c\ub85c \uce74\ud398 \uad00\ub828 \uc5b8\uae09\uc774 \ud655\uc778\ub429\ub2c8\ub2e4."
    if phrases:
        return f"{first} {phrases[0]}\ub97c \ucc3e\ub294 \uc9c8\ubb38\uc5d0 \ucc38\uace0\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
    return first


def search_text(cafe_name: str, category: str, tags: list[str], phrases: list[str], summary: str) -> str:
    category_label = category or "\uce74\ud398"
    parts = [
        f"\uce74\ud398\uba85: {cafe_name}",
        f"\uce74\ud14c\uace0\ub9ac: {category_label}",
        f"\ucd94\ucc9c \ud0dc\uadf8: {', '.join(tags)}",
    ]
    if phrases:
        parts.append(f"\uc9c8\ubb38 \ud45c\ud604: {', '.join(phrases)}")
    parts.append(f"\ube14\ub85c\uadf8 \uc694\uc57d \uae30\uc900: {summary}")
    return "\n".join(parts)


def exclusion_reason(row: dict[str, Any], cafe_name: str, tags: list[str]) -> str:
    if parse_bool(row.get("closed_hint")):
        return "closed"
    if not cafe_name or normalize_name(cafe_name) in GENERIC_NAMES:
        return "missing_name"
    if not clean_text(row.get("summary_blog")):
        return "missing_summary"
    if not tags:
        return "no_tags"
    return ""


def build_doc(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    cafe_name = clean_text(row.get("spot_name"))
    category = clean_text(row.get("category_hint")) or "\uce74\ud398"
    summary = clean_text(row.get("summary_blog"))
    tags = extract_tags(row)

    reason = exclusion_reason(row, cafe_name, tags)
    if reason:
        return None, reason

    phrases = mood_phrases(tags)
    return {
        "doc_id": stable_doc_id(cafe_name),
        "cafe_name": cafe_name,
        "category": category,
        "tags": tags,
        "mood_phrases": phrases,
        "search_text": search_text(cafe_name, category, tags, phrases, summary),
        "answer_text": answer_text(tags, phrases),
        "caution": extract_caution(row),
        "source_meta": {
            "n_snippets_used": parse_int(row.get("n_snippets_used")),
            "bloggers_used": parse_int(row.get("bloggers_used")),
        },
    }, ""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_report(path: Path, total: int, docs: list[dict[str, Any]], excluded: Counter[str], bad_rows: int) -> None:
    tag_counts = Counter(tag for doc in docs for tag in doc["tags"])
    caution_counts = Counter(tag for doc in docs for tag in doc["caution"])
    avg_search = round(sum(len(doc["search_text"]) for doc in docs) / len(docs), 1) if docs else 0
    avg_answer = round(sum(len(doc["answer_text"]) for doc in docs) / len(docs), 1) if docs else 0

    lines = [
        "# Naver MVP RAG Report",
        "",
        f"- total_records: {total}",
        f"- bad_jsonl_rows: {bad_rows}",
        f"- included_rag_docs: {len(docs)}",
        f"- excluded_records: {sum(excluded.values())}",
        f"- excluded_by_closed: {excluded['closed']}",
        f"- excluded_by_missing_name: {excluded['missing_name']}",
        f"- excluded_by_missing_summary: {excluded['missing_summary']}",
        f"- excluded_by_no_tags: {excluded['no_tags']}",
        f"- average_search_text_length: {avg_search}",
        f"- average_answer_text_length: {avg_answer}",
        "",
        "## Tag Distribution",
        "",
    ]
    lines.extend(f"- {tag}: {count}" for tag, count in tag_counts.most_common())
    lines.extend(["", "## Caution Distribution", ""])
    lines.extend(f"- {tag}: {count}" for tag, count in caution_counts.most_common())
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build minimal Naver RAG docs for MVP")
    parser.add_argument("--input", default=str(DEFAULT_INPUT.relative_to(ROOT)))
    parser.add_argument("--out", default=str(DOCS_OUT.relative_to(ROOT)))
    parser.add_argument("--aliases-out", default=str(ALIASES_OUT.relative_to(ROOT)))
    parser.add_argument("--report", default=str(REPORT_OUT.relative_to(ROOT)))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows, bad_rows = load_jsonl(ROOT / args.input)
    docs = []
    excluded: Counter[str] = Counter()
    seen_doc_ids: Counter[str] = Counter()

    for row in rows:
        doc, reason = build_doc(row)
        if doc is None:
            excluded[reason] += 1
            continue
        seen_doc_ids[doc["doc_id"]] += 1
        if seen_doc_ids[doc["doc_id"]] > 1:
            doc["doc_id"] = f"{doc['doc_id']}_{seen_doc_ids[doc['doc_id']]}"
        docs.append(doc)

    write_jsonl(ROOT / args.out, docs)
    write_json(ROOT / args.aliases_out, TAG_ALIASES)
    write_report(ROOT / args.report, len(rows), docs, excluded, bad_rows)
    print(
        json.dumps(
            {
                "input_records": len(rows),
                "rag_docs": len(docs),
                "excluded_records": sum(excluded.values()),
                "out": args.out,
                "aliases_out": args.aliases_out,
                "report": args.report,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

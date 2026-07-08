# -*- coding: utf-8 -*-
"""Build YouTube support docs for the existing Naver RAG docs.

The source data is not modified. This script groups ``유튜브 정제.json`` by
spot name and writes a compact support document per cafe. The output is meant
to sit beside Naver RAG docs as weak corroborating evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
YOUTUBE_INPUT = ROOT / "data" / "processed" / "유튜브 정제.json"
NAVER_RAG_INPUT = ROOT / "data" / "processed" / "naver_rag_docs.jsonl"
DOCS_OUT = ROOT / "data" / "processed" / "youtube_rag_support_docs.jsonl"
REPORT_OUT = ROOT / "data" / "reports" / "youtube_rag_support_report.md"

TAG_MAP = {
    "감성": {"감성"},
    "오션뷰": {"오션뷰", "바다", "뷰", "통창"},
    "산뷰": {"산뷰", "숲뷰", "산방산뷰"},
    "노을": {"노을"},
    "베이커리": {"베이커리"},
    "디저트": {"디저트", "전통찻집"},
    "브런치": {"브런치"},
    "대형": {"대형", "대형카페"},
    "애견": {"애견동반"},
    "테라스": {"야외석", "테라스"},
    "루프탑": {"루프탑"},
    "사진": {"포토존", "사진맛집"},
    "로컬": {"로컬", "조용한 로컬감성"},
    "조용": {"조용함", "조용한 로컬감성"},
    "핸드드립": {"핸드드립", "핸드드립 커피맛집"},
    "로스터리": {"로스터리", "로스터리 카페"},
    "원두": {"스페셜티", "커피맛집"},
    "가족": {"키즈친화"},
    "핫플": {"신상", "라이브공연"},
}

CAUTION_MAP = {
    "주차": {"주차편함", "주차"},
    "노키즈존": {"노키즈존"},
}


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", clean_text(value).lower())


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if isinstance(value, str):
        return [clean_text(item) for item in re.split(r"[,|/]", value) if clean_text(item)]
    return [clean_text(value)]


def parse_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def stable_id(name: str) -> str:
    digest = hashlib.sha1(normalize_name(name).encode("utf-8")).hexdigest()[:10]
    return f"youtube_support_{digest}"


def read_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"Expected list JSON: {path}")
    return [row for row in data if isinstance(row, dict)]


def read_naver_index(path: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return index
    with path.open(encoding="utf-8-sig") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            key = normalize_name(row.get("cafe_name"))
            if key:
                index[key] = {
                    "doc_id": row.get("doc_id"),
                    "cafe_name": row.get("cafe_name"),
                    "tags": as_list(row.get("tags")),
                }
    return index


def map_support_tags(tags: list[str], summary_text: str) -> list[str]:
    # source_keywords are collection queries, so they are useful for recall but
    # too noisy to become evidence tags.
    source = " ".join(tags + [summary_text])
    mapped = []
    for support_tag, aliases in TAG_MAP.items():
        if any(alias in source for alias in aliases):
            mapped.append(support_tag)
    return mapped


def map_caution(tags: list[str], summary_text: str) -> list[str]:
    source = " ".join(tags + [summary_text])
    caution = []
    for caution_tag, aliases in CAUTION_MAP.items():
        if any(alias in source for alias in aliases):
            caution.append(caution_tag)
    return caution


def representative(values: list[str]) -> str:
    values = [value for value in values if value]
    if not values:
        return ""
    return Counter(values).most_common(1)[0][0]


def build_doc(name: str, rows: list[dict[str, Any]], naver_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = normalize_name(name)
    if not key:
        return None

    summaries = [clean_text(row.get("summary")) for row in rows if clean_text(row.get("summary"))]
    tags = sorted({tag for row in rows for tag in as_list(row.get("tags"))})
    keywords = sorted({keyword for row in rows for keyword in as_list(row.get("source_keywords"))})
    video_ids = sorted({clean_text(row.get("video_id")) for row in rows if clean_text(row.get("video_id"))})
    regions = [clean_text(row.get("region")) for row in rows]
    addresses = [clean_text(row.get("address")) for row in rows]
    info_counts = Counter(clean_text(row.get("info_richness")) or "unknown" for row in rows)
    total_view_count = sum(parse_int(row.get("view_count")) for row in rows)

    summary_text = " ".join(summaries[:4])
    support_tags = map_support_tags(tags, summary_text)
    caution = map_caution(tags, summary_text)
    naver_match = naver_index.get(key)

    support_text_parts = [
        f"카페명: {name}",
        f"지역: {representative(regions)}",
        f"유튜브 원본 태그: {', '.join(tags)}",
        f"검색 보조 태그: {', '.join(support_tags)}",
        f"요약: {summary_text}",
        f"소스 키워드: {', '.join(keywords[:12])}",
    ]

    return {
        "doc_id": stable_id(name),
        "cafe_name": name,
        "normalized_name": key,
        "matched_naver": bool(naver_match),
        "naver_doc_id": naver_match.get("doc_id") if naver_match else "",
        "naver_cafe_name": naver_match.get("cafe_name") if naver_match else "",
        "region": representative(regions),
        "address": representative(addresses),
        "youtube_tags_original": tags,
        "support_tags": support_tags,
        "caution": caution,
        "support_text": "\n".join(support_text_parts),
        "youtube_summary": summary_text,
        "source_keywords": keywords[:30],
        "source_meta": {
            "record_count": len(rows),
            "unique_video_count": len(video_ids),
            "total_view_count": total_view_count,
            "info_richness_counts": dict(sorted(info_counts.items())),
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_report(path: Path, input_count: int, docs: list[dict[str, Any]], excluded_missing_name: int) -> None:
    matched = [doc for doc in docs if doc["matched_naver"]]
    unmatched = [doc for doc in docs if not doc["matched_naver"]]
    support_tag_counts = Counter(tag for doc in docs for tag in doc["support_tags"])
    original_tag_counts = Counter(tag for doc in docs for tag in doc["youtube_tags_original"])

    lines = [
        "# YouTube RAG Support Report",
        "",
        f"- input_youtube_records: {input_count}",
        f"- support_docs: {len(docs)}",
        f"- matched_with_naver_rag: {len(matched)}",
        f"- unmatched_with_naver_rag: {len(unmatched)}",
        f"- excluded_missing_spot_name: {excluded_missing_name}",
        f"- output: {DOCS_OUT.relative_to(ROOT)}",
        "",
        "## Top Support Tags",
        "",
    ]
    lines.extend(f"- {tag}: {count}" for tag, count in support_tag_counts.most_common(20))
    lines.extend(["", "## Top Original YouTube Tags", ""])
    lines.extend(f"- {tag}: {count}" for tag, count in original_tag_counts.most_common(20))
    lines.extend(["", "## Matched Samples", ""])
    for doc in matched[:10]:
        lines.append(
            f"- {doc['cafe_name']} -> {doc['naver_cafe_name']} / support_tags={', '.join(doc['support_tags'][:6])}"
        )
    lines.extend(["", "## Unmatched Samples", ""])
    for doc in unmatched[:10]:
        lines.append(f"- {doc['cafe_name']} / region={doc['region']} / support_tags={', '.join(doc['support_tags'][:6])}")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build YouTube support docs for Naver RAG")
    parser.add_argument("--youtube-input", default=str(YOUTUBE_INPUT.relative_to(ROOT)))
    parser.add_argument("--naver-input", default=str(NAVER_RAG_INPUT.relative_to(ROOT)))
    parser.add_argument("--out", default=str(DOCS_OUT.relative_to(ROOT)))
    parser.add_argument("--report", default=str(REPORT_OUT.relative_to(ROOT)))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    youtube_rows = read_json(ROOT / args.youtube_input)
    naver_index = read_naver_index(ROOT / args.naver_input)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded_missing_name = 0
    for row in youtube_rows:
        name = clean_text(row.get("spot_name"))
        if not normalize_name(name):
            excluded_missing_name += 1
            continue
        grouped[name].append(row)

    docs = []
    for name, rows in grouped.items():
        doc = build_doc(name, rows, naver_index)
        if doc:
            docs.append(doc)

    docs.sort(key=lambda doc: (not doc["matched_naver"], doc["cafe_name"]))
    write_jsonl(ROOT / args.out, docs)
    write_report(ROOT / args.report, len(youtube_rows), docs, excluded_missing_name)

    print(
        json.dumps(
            {
                "input_youtube_records": len(youtube_rows),
                "support_docs": len(docs),
                "matched_with_naver_rag": sum(1 for doc in docs if doc["matched_naver"]),
                "unmatched_with_naver_rag": sum(1 for doc in docs if not doc["matched_naver"]),
                "out": args.out,
                "report": args.report,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Build a team-shareable hybrid embedding seed.

Inputs are existing generated docs:
- data/processed/naver_rag_docs.jsonl
- data/processed/youtube_rag_support_docs.jsonl

Output:
- data/rag/hybrid_embedding_seed.jsonl
- data/rag/hybrid_manifest.json

The seed keeps Naver Blog evidence as the primary recommendation text and adds
YouTube support text as weak corroborating evidence when names match.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NAVER_PATH = ROOT / "data" / "processed" / "naver_rag_docs.jsonl"
YOUTUBE_PATH = ROOT / "data" / "processed" / "youtube_rag_support_docs.jsonl"
SEED_OUT = ROOT / "data" / "rag" / "hybrid_embedding_seed.jsonl"
MANIFEST_OUT = ROOT / "data" / "rag" / "hybrid_manifest.json"
COLLECTION = "jeju_cafe_hybrid"


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^0-9a-z가-힣]", "", text)
    if len(text) > 4 and text.startswith("카페"):
        text = text[2:]
    if len(text) > 4 and text.endswith("카페"):
        text = text[:-2]
    return text


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if isinstance(value, str):
        return [clean_text(item) for item in re.split(r"[,|/]", value) if clean_text(item)]
    return [clean_text(value)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def index_naver(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = normalize_name(row.get("cafe_name"))
        if key and key not in index:
            index[key] = row
    return index


def index_youtube(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = normalize_name(row.get("cafe_name"))
        if not key:
            continue
        if key not in index:
            index[key] = row
            continue
        current = index[key]
        current["support_tags"] = sorted(set(as_list(current.get("support_tags"))) | set(as_list(row.get("support_tags"))))
        current["caution"] = sorted(set(as_list(current.get("caution"))) | set(as_list(row.get("caution"))))
        current["support_text"] = "\n".join(
            part for part in [clean_text(current.get("support_text")), clean_text(row.get("support_text"))] if part
        )
        current_meta = current.get("source_meta") if isinstance(current.get("source_meta"), dict) else {}
        row_meta = row.get("source_meta") if isinstance(row.get("source_meta"), dict) else {}
        current_meta["record_count"] = int(current_meta.get("record_count") or 0) + int(row_meta.get("record_count") or 0)
        current_meta["unique_video_count"] = int(current_meta.get("unique_video_count") or 0) + int(
            row_meta.get("unique_video_count") or 0
        )
        current_meta["total_view_count"] = int(current_meta.get("total_view_count") or 0) + int(row_meta.get("total_view_count") or 0)
        current["source_meta"] = current_meta
    return index


def seed_id(key: str, naver: dict[str, Any] | None, youtube: dict[str, Any] | None) -> str:
    if naver and clean_text(naver.get("doc_id")):
        return f"hybrid_{clean_text(naver['doc_id']).replace('naver_', '')}"
    if youtube and clean_text(youtube.get("doc_id")):
        return f"hybrid_{clean_text(youtube['doc_id']).replace('youtube_support_', '')}"
    return f"hybrid_{key}"


def choose_name(key: str, naver: dict[str, Any] | None, youtube: dict[str, Any] | None) -> str:
    names = [clean_text((naver or {}).get("cafe_name")), clean_text((youtube or {}).get("cafe_name"))]
    names = [name for name in names if name]
    return max(names, key=len) if names else key


def merge_tags(naver: dict[str, Any] | None, youtube: dict[str, Any] | None) -> list[str]:
    tags = set(as_list((naver or {}).get("tags")))
    tags.update(as_list((youtube or {}).get("support_tags")))
    return sorted(tags)


def merge_caution(naver: dict[str, Any] | None, youtube: dict[str, Any] | None) -> list[str]:
    caution = set(as_list((naver or {}).get("caution")))
    caution.update(as_list((youtube or {}).get("caution")))
    return sorted(caution)


def build_text(name: str, naver: dict[str, Any] | None, youtube: dict[str, Any] | None, tags: list[str], caution: list[str]) -> str:
    parts = [f"카페명: {name}", f"추천 태그: {', '.join(tags)}"]
    if caution:
        parts.append(f"주의 신호: {', '.join(caution)}")
    if naver:
        parts.extend(
            [
                "[네이버 블로그 근거]",
                clean_text(naver.get("search_text")),
                f"답변 보조문: {clean_text(naver.get('answer_text'))}",
            ]
        )
    if youtube:
        parts.extend(
            [
                "[유튜브 보조 근거]",
                clean_text(youtube.get("support_text")),
                f"유튜브 요약: {clean_text(youtube.get('youtube_summary'))}",
            ]
        )
    return "\n".join(part for part in parts if part)


def build_seed_doc(key: str, naver: dict[str, Any] | None, youtube: dict[str, Any] | None) -> dict[str, Any]:
    name = choose_name(key, naver, youtube)
    tags = merge_tags(naver, youtube)
    caution = merge_caution(naver, youtube)
    youtube_meta = youtube.get("source_meta") if youtube and isinstance(youtube.get("source_meta"), dict) else {}
    naver_meta = naver.get("source_meta") if naver and isinstance(naver.get("source_meta"), dict) else {}
    source_types = []
    if naver:
        source_types.append("naver_blog")
    if youtube:
        source_types.append("youtube")

    return {
        "id": seed_id(key, naver, youtube),
        "text": build_text(name, naver, youtube, tags, caution),
        "metadata": {
            "cafe_name": name,
            "normalized_name": key,
            "collection": COLLECTION,
            "source_types": source_types,
            "has_naver": bool(naver),
            "has_youtube": bool(youtube),
            "naver_doc_id": clean_text((naver or {}).get("doc_id")),
            "youtube_doc_id": clean_text((youtube or {}).get("doc_id")),
            "category": clean_text((naver or {}).get("category")),
            "region": clean_text((youtube or {}).get("region")),
            "address": clean_text((youtube or {}).get("address")),
            "tags": tags,
            "caution": caution,
            "bloggers_used": naver_meta.get("bloggers_used", 0),
            "n_snippets_used": naver_meta.get("n_snippets_used", 0),
            "youtube_record_count": youtube_meta.get("record_count", 0),
            "youtube_unique_video_count": youtube_meta.get("unique_video_count", 0),
            "youtube_total_view_count": youtube_meta.get("total_view_count", 0),
        },
        "collection": COLLECTION,
        "source": "data/processed/naver_rag_docs.jsonl + data/processed/youtube_rag_support_docs.jsonl",
    }


def write_jsonl(path: Path, docs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for doc in docs:
            file.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")


def write_manifest(path: Path, naver_count: int, youtube_count: int, docs: list[dict[str, Any]]) -> None:
    source_mix = Counter(
        "both" if doc["metadata"]["has_naver"] and doc["metadata"]["has_youtube"] else "naver_only" if doc["metadata"]["has_naver"] else "youtube_only"
        for doc in docs
    )
    tag_counts = Counter(tag for doc in docs for tag in doc["metadata"]["tags"])
    manifest = {
        "collection": COLLECTION,
        "embedding_seed": str(SEED_OUT.relative_to(ROOT)),
        "input_naver_docs": naver_count,
        "input_youtube_support_docs": youtube_count,
        "seed_docs": len(docs),
        "source_mix": dict(source_mix),
        "top_tags": dict(tag_counts.most_common(20)),
        "inputs": [
            str(NAVER_PATH.relative_to(ROOT)),
            str(YOUTUBE_PATH.relative_to(ROOT)),
        ],
        "notes": [
            "Naver Blog text is primary recommendation evidence.",
            "YouTube support text is weak corroborating evidence.",
            "Use metadata.has_naver=true for public recommendation filtering if needed.",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build hybrid embedding seed JSONL")
    parser.add_argument("--naver", default=str(NAVER_PATH.relative_to(ROOT)))
    parser.add_argument("--youtube", default=str(YOUTUBE_PATH.relative_to(ROOT)))
    parser.add_argument("--out", default=str(SEED_OUT.relative_to(ROOT)))
    parser.add_argument("--manifest", default=str(MANIFEST_OUT.relative_to(ROOT)))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    naver_rows = read_jsonl(ROOT / args.naver)
    youtube_rows = read_jsonl(ROOT / args.youtube)
    naver_index = index_naver(naver_rows)
    youtube_index = index_youtube(youtube_rows)
    keys = sorted(set(naver_index) | set(youtube_index))
    docs = [build_seed_doc(key, naver_index.get(key), youtube_index.get(key)) for key in keys]
    docs.sort(key=lambda doc: (not doc["metadata"]["has_naver"], doc["metadata"]["cafe_name"]))

    write_jsonl(ROOT / args.out, docs)
    write_manifest(ROOT / args.manifest, len(naver_rows), len(youtube_rows), docs)
    print(
        json.dumps(
            {
                "seed_docs": len(docs),
                "both": sum(1 for doc in docs if doc["metadata"]["has_naver"] and doc["metadata"]["has_youtube"]),
                "naver_only": sum(1 for doc in docs if doc["metadata"]["has_naver"] and not doc["metadata"]["has_youtube"]),
                "youtube_only": sum(1 for doc in docs if doc["metadata"]["has_youtube"] and not doc["metadata"]["has_naver"]),
                "out": args.out,
                "manifest": args.manifest,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

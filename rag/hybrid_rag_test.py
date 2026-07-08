# -*- coding: utf-8 -*-
"""String-baseline hybrid RAG test for Jeju cafe recommendations.

This script reads existing Naver RAG docs and existing YouTube cafe data,
merges candidates by normalized cafe name, and writes a markdown test report.
It does not modify source data, regenerate tags, or call external APIs.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NAVER_PATH = ROOT / "data" / "processed" / "naver_rag_docs.jsonl"
ALIASES_PATH = ROOT / "data" / "processed" / "naver_tag_aliases.json"
REPORT_PATH = ROOT / "data" / "reports" / "hybrid_rag_test_report.md"

YOUTUBE_CANDIDATES = [
    ROOT / "data" / "processed" / "youtube_rag_support_docs.jsonl",
    ROOT / "data" / "processed" / "cafes_scored.json",
    ROOT / "data" / "processed" / "jeju_serving_ready_cafes.csv",
    ROOT / "data" / "processed" / "jeju-serving-ready.repaired.json",
    ROOT / "data" / "processed" / "rag_docs.jsonl",
    ROOT / "data" / "processed" / "\uc720\ud29c\ube0c \uc815\uc81c.json",
]

DEFAULT_QUESTIONS = [
    "\uc0ac\uc9c4 \ucc0d\uae30 \uc88b\uc740 \uac10\uc131 \uce74\ud398 \ucd94\ucc9c\ud574\uc918",
    "\ud63c\uc790 \uc870\uc6a9\ud788 \uc26c\uae30 \uc88b\uc740 \uce74\ud398 \uc788\uc5b4?",
    "\ub178\uc744 \ubcf4\uae30 \uc88b\uc740 \uc624\uc158\ubdf0 \uce74\ud398 \ucd94\ucc9c",
    "\uac00\uc871\uc774\ub791 \uac00\uae30 \uc88b\uc740 \ub300\ud615 \uce74\ud398",
    "\ud578\ub4dc\ub4dc\ub9bd \uc798\ud558\ub294 \ub85c\uc2a4\ud130\ub9ac \uce74\ud398",
    "\ubc14\ub2e4 \ubcf4\uc774\ub294 \ube0c\ub7f0\uce58 \uce74\ud398",
    "\uc560\uacac\ub3d9\ubc18 \uac00\ub2a5\ud55c \ud14c\ub77c\uc2a4 \uce74\ud398",
    "\ub514\uc800\ud2b8 \ub9db\uc788\ub294 \uc624\uc158\ubdf0 \uce74\ud398",
    "\uc228\uc740 \ub85c\uceec \uac10\uc131 \uce74\ud398 \ucd94\ucc9c",
    "\ud56b\ud50c \ub290\ub08c \ub098\ub294 \ud65c\uae30 \uc788\ub294 \uce74\ud398",
]

FALLBACK_ALIASES = {
    "\uc870\uc6a9": ["\uc870\uc6a9", "\ud55c\uc801", "\ucc28\ubd84"],
    "\ub178\uc744": ["\ub178\uc744", "\uc11d\uc591", "\uc120\uc14b"],
    "\ud578\ub4dc\ub4dc\ub9bd": ["\ud578\ub4dc\ub4dc\ub9bd", "\ub4dc\ub9bd\ucee4\ud53c", "\ud544\ud130\ucee4\ud53c"],
    "\ub85c\uc2a4\ud130\ub9ac": ["\ub85c\uc2a4\ud130\ub9ac", "\ub85c\uc2a4\ud305"],
    "\uc624\uc158\ubdf0": ["\uc624\uc158\ubdf0", "\ubc14\ub2e4\ubdf0", "\ubc14\ub2e4 \ubcf4\uc774"],
    "\uc0b0\ubdf0": ["\uc0b0\ubdf0", "\uc232\ubdf0", "\ud55c\ub77c\uc0b0"],
    "\uac10\uc131": ["\uac10\uc131", "\ubd84\uc704\uae30", "\ubb34\ub4dc"],
    "\ub85c\uceec": ["\ub85c\uceec", "\ud604\uc9c0\uc778", "\ub3d9\ub124"],
    "\ub300\ud615": ["\ub300\ud615", "\ub113\uc740"],
    "\uac00\uc871": ["\uac00\uc871", "\ud0a4\uc988", "\uc544\uc774"],
    "\ud63c\uc790": ["\ud63c\uc790", "\ud63c\uce74\ud398"],
    "\uc228\uc740": ["\uc228\uc740", "\ud55c\uc801\ud55c"],
    "\uc0ac\uc9c4": ["\uc0ac\uc9c4", "\ud3ec\ud1a0", "\ud3ec\ud1a0\uc874"],
    "\ub514\uc800\ud2b8": ["\ub514\uc800\ud2b8", "\ucf00\uc774\ud06c"],
    "\ud574\ubcc0": ["\ud574\ubcc0", "\ud574\uc218\uc695\uc7a5"],
    "\ube0c\ub7f0\uce58": ["\ube0c\ub7f0\uce58", "\uc0cc\ub4dc\uc704\uce58"],
    "\ubca0\uc774\ucee4\ub9ac": ["\ubca0\uc774\ucee4\ub9ac", "\ube75"],
    "\ubc14\ub2e4": ["\ubc14\ub2e4", "\ud574\uc548"],
    "\uc6d0\ub450": ["\uc6d0\ub450", "\uc2a4\ud398\uc15c\ud2f0"],
    "\ub8e8\ud504\ud0d1": ["\ub8e8\ud504\ud0d1", "\uc625\uc0c1"],
    "\uc560\uacac": ["\uc560\uacac", "\ubc18\ub824\uacac", "\ubc18\ub824\ub3d9\ubb3c"],
    "\uc2dc\uadf8\ub2c8\ucc98": ["\uc2dc\uadf8\ub2c8\ucc98", "\ub300\ud45c\uba54\ub274"],
    "\uc778\uc0dd\uc0f7": ["\uc778\uc0dd\uc0f7", "sns"],
    "\ud14c\ub77c\uc2a4": ["\ud14c\ub77c\uc2a4", "\uc57c\uc678\uc11d"],
    "\ud3b8\uc548": ["\ud3b8\uc548", "\uc544\ub291"],
    "\ud65c\uae30": ["\ud65c\uae30", "\ubd81\uc801"],
    "\ud56b\ud50c": ["\ud56b\ud50c", "\uc778\uae30", "\uc720\uba85"],
}

CAUTION_TERMS = {
    "\uc870\uc6a9": {"\uc6e8\uc774\ud305", "\ud63c\uc7a1\uac00\ub2a5"},
    "\ud63c\uc790": {"\uc6e8\uc774\ud305", "\ud63c\uc7a1\uac00\ub2a5"},
    "\ud3b8\uc548": {"\uc6e8\uc774\ud305", "\ud63c\uc7a1\uac00\ub2a5"},
    "\uac00\uc871": {"\ub178\ud0a4\uc988\uc874"},
}


@dataclass
class SourceBundle:
    source: str
    name: str
    tags: set[str] = field(default_factory=set)
    caution: set[str] = field(default_factory=set)
    body: str = ""
    answer_text: str = ""
    support_text: str = ""
    recommendation_reason: str = ""
    source_count: int = 0
    unique_video_count: int = 0


@dataclass
class Candidate:
    key: str
    cafe_name: str
    naver: SourceBundle | None = None
    youtube: SourceBundle | None = None


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^0-9a-z\uac00-\ud7a3]", "", text)
    if len(text) > 4 and text.startswith("\uce74\ud398"):
        text = text[2:]
    if len(text) > 4 and text.endswith("\uce74\ud398"):
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


def parse_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_aliases() -> dict[str, list[str]]:
    if not ALIASES_PATH.exists():
        return FALLBACK_ALIASES
    aliases = json.loads(ALIASES_PATH.read_text(encoding="utf-8-sig"))
    merged = dict(FALLBACK_ALIASES)
    for tag, terms in aliases.items():
        merged[tag] = sorted(set([tag] + as_list(terms) + merged.get(tag, [])))
    return merged


def load_naver_docs() -> list[SourceBundle]:
    rows = read_jsonl(NAVER_PATH)
    docs = []
    for row in rows:
        name = clean_text(row.get("cafe_name"))
        body = " ".join(
            [
                clean_text(row.get("search_text")),
                " ".join(as_list(row.get("tags"))),
                " ".join(as_list(row.get("mood_phrases"))),
                clean_text(row.get("answer_text")),
            ]
        )
        docs.append(
            SourceBundle(
                source="naver_blog",
                name=name,
                tags=set(as_list(row.get("tags"))),
                caution=set(as_list(row.get("caution"))),
                body=body,
                answer_text=clean_text(row.get("answer_text")),
                support_text=clean_text(row.get("search_text")),
            )
        )
    return docs


def load_json_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("serving_ready_cafes", "cafes", "scored_cafes", "records"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def choose_youtube_path() -> Path:
    for path in YOUTUBE_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("No YouTube cafe dataset found in data/processed")


def load_youtube_docs() -> tuple[list[SourceBundle], Path]:
    path = choose_youtube_path()
    if path.suffix.lower() == ".jsonl":
        rows = read_jsonl(path)
    elif path.suffix.lower() == ".csv":
        rows = load_csv_rows(path)
    else:
        rows = load_json_rows(path)

    docs = []
    for row in rows:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        source_meta = row.get("source_meta") if isinstance(row.get("source_meta"), dict) else {}
        name = clean_text(
            row.get("canonical_name")
            or row.get("cafe_name")
            or row.get("spot_name")
            or meta.get("canonical_name")
        )
        if not name:
            continue

        tags = set(as_list(row.get("support_tags") or row.get("tags")))
        category_tags = as_list(row.get("category_tags") or meta.get("category_tags"))
        source_keywords = as_list(row.get("source_keywords"))
        recommendation_reason = clean_text(row.get("recommendation_reason"))
        summary = clean_text(row.get("youtube_summary") or row.get("summary"))
        text = clean_text(row.get("support_text") or row.get("text"))
        caution = set(as_list(row.get("caution")))
        body = " ".join(
            [
                summary,
                " ".join(tags),
                " ".join(category_tags),
                recommendation_reason,
                " ".join(source_keywords),
                text,
            ]
        )

        docs.append(
            SourceBundle(
                source="youtube",
                name=name,
                tags=tags | set(category_tags),
                caution=caution,
                body=body,
                support_text=summary or text,
                recommendation_reason=recommendation_reason,
                source_count=parse_int(row.get("source_count") or meta.get("source_count") or source_meta.get("record_count")),
                unique_video_count=parse_int(row.get("unique_video_count") or source_meta.get("unique_video_count")),
            )
        )
    return docs, path


def merge_candidates(naver_docs: list[SourceBundle], youtube_docs: list[SourceBundle]) -> dict[str, Candidate]:
    candidates: dict[str, Candidate] = {}
    for doc in naver_docs + youtube_docs:
        key = normalize_name(doc.name)
        if not key:
            continue
        candidate = candidates.setdefault(key, Candidate(key=key, cafe_name=doc.name))
        if doc.source == "naver_blog":
            candidate.naver = merge_source(candidate.naver, doc)
        else:
            candidate.youtube = merge_source(candidate.youtube, doc)
        if len(doc.name) > len(candidate.cafe_name):
            candidate.cafe_name = doc.name
    return candidates


def merge_source(current: SourceBundle | None, doc: SourceBundle) -> SourceBundle:
    if current is None:
        return doc
    current.tags.update(doc.tags)
    current.caution.update(doc.caution)
    current.body = " ".join(part for part in [current.body, doc.body] if part)
    current.answer_text = current.answer_text or doc.answer_text
    current.support_text = current.support_text or doc.support_text
    current.recommendation_reason = current.recommendation_reason or doc.recommendation_reason
    current.source_count += doc.source_count
    current.unique_video_count += doc.unique_video_count
    return current


def infer_required_tags(question: str, aliases: dict[str, list[str]]) -> set[str]:
    q = question.lower()
    tags = set()
    for tag, terms in aliases.items():
        if tag.lower() in q or any(term.lower() in q for term in terms):
            tags.add(tag)
    return tags


def query_terms(question: str, required_tags: set[str], aliases: dict[str, list[str]]) -> set[str]:
    terms = set(re.findall(r"[0-9a-zA-Z\uac00-\ud7a3]+", question.lower()))
    for tag in required_tags:
        terms.add(tag.lower())
        terms.update(term.lower() for term in aliases.get(tag, [])[:8])
    return {term for term in terms if len(term) >= 2 and term not in {"카페", "추천", "있어", "좋은", "가능한"}}


def bundle_score(bundle: SourceBundle | None, terms: set[str], required_tags: set[str], aliases: dict[str, list[str]], source: str) -> float:
    if bundle is None:
        return 0.0
    score = 0.0
    body = bundle.body.lower()
    tag_text = " ".join(bundle.tags).lower()

    for term in terms:
        if term in body:
            score += 0.8 if source == "naver_blog" else 0.6
        if term in tag_text:
            score += 0.6

    for tag in required_tags:
        tag_aliases = [tag] + aliases.get(tag, [])
        if tag in bundle.tags:
            score += 3.0 if source == "naver_blog" else 2.5
        elif any(alias in body for alias in tag_aliases):
            score += 1.4 if source == "naver_blog" else 1.0

    if source == "naver_blog" and bundle.answer_text:
        score += 0.4
    if source == "youtube":
        source_count = max(bundle.source_count, bundle.unique_video_count)
        if source_count:
            score += min(0.8, math.log1p(source_count) * 0.25)
    return score


def caution_penalty(candidate: Candidate, required_tags: set[str]) -> float:
    caution = set()
    if candidate.naver:
        caution.update(candidate.naver.caution)
    penalty = 0.0
    for tag in required_tags:
        conflicts = CAUTION_TERMS.get(tag, set())
        penalty += 2.5 * len(caution & conflicts)
    if "\uc601\uc5c5\uc885\ub8cc" in caution:
        penalty += 5.0
    return penalty


def score_candidate(candidate: Candidate, question: str, aliases: dict[str, list[str]]) -> tuple[float, dict[str, Any]]:
    required_tags = infer_required_tags(question, aliases)
    terms = query_terms(question, required_tags, aliases)
    naver_score = bundle_score(candidate.naver, terms, required_tags, aliases, "naver_blog")
    youtube_score = bundle_score(candidate.youtube, terms, required_tags, aliases, "youtube")
    both_bonus = 2.0 if candidate.naver and candidate.youtube and (naver_score > 0 or youtube_score > 0) else 0.0
    penalty = caution_penalty(candidate, required_tags)
    score = max(0.0, naver_score + youtube_score + both_bonus - penalty)
    return score, {
        "required_tags": sorted(required_tags),
        "terms": sorted(terms),
        "naver_score": round(naver_score, 2),
        "youtube_score": round(youtube_score, 2),
        "both_bonus": both_bonus,
        "penalty": penalty,
    }


def search(question: str, candidates: dict[str, Candidate], aliases: dict[str, list[str]], top_k: int = 5) -> list[dict[str, Any]]:
    rows = []
    for candidate in candidates.values():
        score, debug = score_candidate(candidate, question, aliases)
        if score <= 0:
            continue
        matched_sources = []
        if candidate.naver and debug["naver_score"] > 0:
            matched_sources.append("naver_blog")
        if candidate.youtube and debug["youtube_score"] > 0:
            matched_sources.append("youtube")
        tags = set()
        caution = set()
        if candidate.naver:
            tags.update(candidate.naver.tags)
            caution.update(candidate.naver.caution)
        if candidate.youtube:
            tags.update(candidate.youtube.tags)
            caution.update(candidate.youtube.caution)
        rows.append(
            {
                "cafe_name": candidate.cafe_name,
                "matched_sources": matched_sources,
                "tags": sorted(tags),
                "caution": sorted(caution),
                "score": round(score, 2),
                "naver_answer_text": candidate.naver.answer_text if candidate.naver else "",
                "youtube_support_text": candidate.youtube.support_text if candidate.youtube else "",
                "recommendation_reason": candidate.youtube.recommendation_reason if candidate.youtube else "",
                "debug": debug,
            }
        )
    rows.sort(key=lambda row: (-row["score"], -len(row["matched_sources"]), row["cafe_name"]))
    return rows[:top_k]


def md_escape(value: Any) -> str:
    text = clean_text(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def shorten(value: Any, limit: int = 90) -> str:
    text = clean_text(value)
    return text if len(text) <= limit else text[: limit - 1] + "..."


def result_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| rank | cafe_name | matched_sources | tags | caution | score | naver_answer_text | youtube_support_text | recommendation_reason |",
        "|---:|---|---|---|---|---:|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    md_escape(row["cafe_name"]),
                    md_escape(", ".join(row["matched_sources"])),
                    md_escape(", ".join(row["tags"][:8])),
                    md_escape(", ".join(row["caution"])),
                    str(row["score"]),
                    md_escape(shorten(row["naver_answer_text"])),
                    md_escape(shorten(row["youtube_support_text"])),
                    md_escape(shorten(row["recommendation_reason"])),
                ]
            )
            + " |"
        )
    return lines


def source_mix(rows: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    naver_only, youtube_only, both = [], [], []
    for row in rows:
        sources = set(row["matched_sources"])
        if sources == {"naver_blog"}:
            naver_only.append(row["cafe_name"])
        elif sources == {"youtube"}:
            youtube_only.append(row["cafe_name"])
        elif sources == {"naver_blog", "youtube"}:
            both.append(row["cafe_name"])
    return naver_only, youtube_only, both


def improvement_patterns(all_results: dict[str, list[dict[str, Any]]], aliases: dict[str, list[str]]) -> list[str]:
    patterns = []
    failed = [question for question, rows in all_results.items() if not rows]
    if failed:
        patterns.append(f"- 검색 실패 질문 {len(failed)}개: alias 확장 또는 원문 필드 확인 필요")
    low_conf = [question for question, rows in all_results.items() if rows and rows[0]["score"] < 5]
    if low_conf:
        patterns.append(f"- top-1 점수 5 미만 질문 {len(low_conf)}개: 질문 태그와 데이터 태그 표현 차이 점검 필요")
    naver_only_count = sum(1 for rows in all_results.values() for row in rows if set(row["matched_sources"]) == {"naver_blog"})
    youtube_only_count = sum(1 for rows in all_results.values() for row in rows if set(row["matched_sources"]) == {"youtube"})
    both_count = sum(1 for rows in all_results.values() for row in rows if set(row["matched_sources"]) == {"naver_blog", "youtube"})
    patterns.append(f"- top-5 기준 naver_only={naver_only_count}, youtube_only={youtube_only_count}, both={both_count}")
    allowed_tags = set(aliases)
    outside_vocab = Counter(
        tag
        for rows in all_results.values()
        for row in rows
        for tag in row["tags"]
        if tag not in allowed_tags
    )
    if outside_vocab:
        examples = ", ".join(f"{tag}({count})" for tag, count in outside_vocab.most_common(8))
        patterns.append(f"- 유튜브 기존 태그와 네이버 MVP 태그 어휘가 다름: {examples}")
    patterns.append("- 문자열 baseline이라 어미 변화와 의미 유사어에는 약함. 다음 단계에서 임베딩 rerank를 붙이면 좋음")
    patterns.append("- caution 감점은 조용/혼자/가족 intent에만 최소 적용했으므로 운영 질문이 늘면 충돌 규칙 확장 필요")
    return patterns


def write_report(
    candidates: dict[str, Candidate],
    naver_docs: list[SourceBundle],
    youtube_docs: list[SourceBundle],
    youtube_path: Path,
    all_results: dict[str, list[dict[str, Any]]],
    aliases: dict[str, list[str]],
) -> None:
    matched_count = sum(1 for candidate in candidates.values() if candidate.naver and candidate.youtube)
    failed_questions = [question for question, rows in all_results.items() if not rows]

    lines = [
        "# Hybrid RAG Test Report",
        "",
        f"- total_naver_docs: {len(naver_docs)}",
        f"- total_youtube_docs: {len(youtube_docs)}",
        f"- youtube_source_file: {youtube_path.relative_to(ROOT)}",
        f"- matched_cafe_count_between_naver_and_youtube: {matched_count}",
        f"- candidate_count_after_name_merge: {len(candidates)}",
        "",
        "## Query Results",
        "",
    ]

    source_counter: Counter[str] = Counter()
    for question, rows in all_results.items():
        lines.extend([f"### {question}", ""])
        lines.extend(result_table(rows) if rows else ["검색 결과 없음"])
        naver_only, youtube_only, both = source_mix(rows)
        source_counter["naver_only"] += len(naver_only)
        source_counter["youtube_only"] += len(youtube_only)
        source_counter["both"] += len(both)
        lines.extend(
            [
                "",
                f"- 네이버만 잡힌 후보: {', '.join(naver_only) if naver_only else '-'}",
                f"- 유튜브만 잡힌 후보: {', '.join(youtube_only) if youtube_only else '-'}",
                f"- 양쪽 모두 잡힌 후보: {', '.join(both) if both else '-'}",
                "",
            ]
        )

    lines.extend(
        [
            "## Source Mix Summary",
            "",
            f"- 네이버만 잡힌 후보: {source_counter['naver_only']}",
            f"- 유튜브만 잡힌 후보: {source_counter['youtube_only']}",
            f"- 양쪽 모두 잡힌 후보: {source_counter['both']}",
            "",
            "## 검색 실패 질문",
            "",
        ]
    )
    lines.extend([f"- {question}" for question in failed_questions] or ["- 없음"])
    lines.extend(["", "## 개선이 필요한 패턴", ""])
    lines.extend(improvement_patterns(all_results, aliases))
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    aliases = load_aliases()
    naver_docs = load_naver_docs()
    youtube_docs, youtube_path = load_youtube_docs()
    candidates = merge_candidates(naver_docs, youtube_docs)
    all_results = {question: search(question, candidates, aliases, top_k=5) for question in DEFAULT_QUESTIONS}
    write_report(candidates, naver_docs, youtube_docs, youtube_path, all_results, aliases)
    print(
        json.dumps(
            {
                "total_naver_docs": len(naver_docs),
                "total_youtube_docs": len(youtube_docs),
                "matched_cafe_count_between_naver_and_youtube": sum(
                    1 for candidate in candidates.values() if candidate.naver and candidate.youtube
                ),
                "report": str(REPORT_PATH.relative_to(ROOT)),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

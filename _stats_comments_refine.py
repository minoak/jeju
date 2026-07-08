# -*- coding: utf-8 -*-
"""댓글 정제 결과 수율 (읽기 전용)."""
import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
recs = []
for line in open(os.path.join(ROOT, "data", "processed", "댓글 정제.jsonl"), encoding="utf-8"):
    line = line.strip()
    if line:
        recs.append(json.loads(line))

print(f"총 {len(recs)}편")
print("트랙:", dict(Counter(r["track"] for r in recs)))
print("카페 무관 영상:", sum(1 for r in recs if not r["is_cafe_related"]))

found = [r for r in recs if r["track"] == "B발굴" and r.get("cafe_identified")]
print(f"\nB발굴 — 카페 특정 성공: {len(found)}편")
for r in found[:10]:
    print(f"  {r['cafe_identified']}")

def has_slot(r):
    return any(v for v in (r.get("info_slots") or {}).values())
info = [r for r in recs if has_slot(r)]
print(f"\ninfo_slots 보유: {len(info)}편")
addr = [r for r in recs if (r.get('info_slots') or {}).get('address')]
print(f"  주소 확보: {len(addr)}편")
for r in addr[:5]:
    print(f"  [{r.get('spot_name') or r.get('cafe_identified') or '?'}] {r['info_slots']['address'][:60]}")

react = [r for r in recs if r.get("reaction_summary")]
print(f"\n반응 요약 보유: {len(react)}편 | 톤 분포:", dict(Counter(r["reaction_tone"] for r in react)))
tips = [t for r in recs for t in r.get("local_tips", [])]
print(f"로컬 팁: {len(tips)}개 | 예시: {tips[:5]}")
closed = [r.get('spot_name') or r.get('cafe_identified') for r in recs if r.get("closed_hint")]
print(f"폐업 제보: {len(closed)}편 → {closed[:10]}")

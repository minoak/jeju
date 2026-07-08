# -*- coding: utf-8 -*-
"""네이버 크롤링 결과 1차 확인 (읽기 전용 — 아무것도 수정 안 함)."""
import json
import os
import re
import statistics as st
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))

recs = []
for line in open(os.path.join(ROOT, "data", "raw", "naver_20260708.jsonl"), encoding="utf-8"):
    line = line.strip()
    if line:
        recs.append(json.loads(line))

print(f"■ 레코드: {len(recs)}건")
errs = [r for r in recs if "error" in r]
print(f"■ 오류 레코드: {len(errs)}건")

ok = [r for r in recs if "blog" in r]
by_rich = {"high": [], "mid": [], "low": [], None: []}
for r in ok:
    by_rich.setdefault(r.get("info_richness"), []).append(r)

print("\n■ 블로그 검색 수율 (richness별)")
for k in ["high", "mid", "low"]:
    rows = by_rich.get(k, [])
    if not rows:
        continue
    totals = [r["blog"].get("total", 0) for r in rows]
    n_items = [len(r["blog"].get("items", [])) for r in rows]
    print(f"  {k:４} {len(rows):>4}곳 | total 중앙값 {st.median(totals):>7,.0f} | "
          f"0건 {sum(1 for t in totals if t == 0)}곳 | 10건미만 {sum(1 for t in totals if t < 10)}곳 | "
          f"스니펫 평균 {st.mean(n_items):.0f}개")

# 텍스트량: 카페당 스니펫 텍스트 합계
TAG = re.compile(r"<[^>]+>")
def textlen(r):
    return sum(len(TAG.sub("", it.get("title", "") + it.get("description", "")))
               for it in r["blog"].get("items", []))
tl = [textlen(r) for r in ok]
print(f"\n■ 카페당 스니펫 텍스트: 중앙값 {st.median(tl):,.0f}자 / 평균 {st.mean(tl):,.0f}자")

# 지역검색
loc_hit = [r for r in ok if r.get("local", {}).get("items")]
print(f"\n■ 지역검색 히트: {len(loc_hit)}/{len(ok)} ({len(loc_hit)/len(ok):.0%})")

# 주소 보강 잠재력: 원본에 주소 없던 카페 중 지역검색이 주소를 준 곳
spots = json.load(open(os.path.join(ROOT, "data", "processed", "카페-변환.json"), encoding="utf-8"))
had_addr = {}
for s in spots:
    if s["spot_name"] not in had_addr:
        had_addr[s["spot_name"]] = bool(s.get("address"))
gain = sum(1 for r in loc_hit
           if not had_addr.get(r["spot_name"])
           and any(it.get("roadAddress") or it.get("address") for it in r["local"]["items"]))
no_addr_total = sum(1 for v in had_addr.values() if not v)
print(f"■ 주소 보강 잠재력: 주소 없던 {no_addr_total}곳 중 {gain}곳 신규 주소 후보 확보")

# 실존 의심 후보: 블로그도 거의 없고 지역검색도 0건
ghost = [r["spot_name"] for r in ok
         if r["blog"].get("total", 0) < 5 and not r.get("local", {}).get("items")]
print(f"\n■ 실존 의심(블로그<5 & 지역검색 0): {len(ghost)}곳")
print("  예시:", ghost[:10])

# 동명이인 위험 신호: 지역검색 1위 이름에 spot_name 핵심 토큰이 안 들어감
def norm(s):
    return re.sub(r"[^\w가-힣]", "", TAG.sub("", s or "").lower())
mismatch = sum(1 for r in loc_hit
               if norm(r["spot_name"])[:6] not in norm(r["local"]["items"][0].get("title", "")))
print(f"\n■ 지역검색 1위 이름 불일치(동명이인/오매칭 위험): {mismatch}/{len(loc_hit)}")

print("\n[확인 완료 — 파일 수정 없음]")

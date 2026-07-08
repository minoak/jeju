# -*- coding: utf-8 -*-
"""네이버 크롤 결과 → 엑셀 검수용 CSV (utf-8-sig). 원본은 건드리지 않음."""
import csv
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "data", "raw", "naver_20260708.jsonl")
OUT = os.path.join(ROOT, "data", "processed", "review_naver.csv")

TAG = re.compile(r"<[^>]+>")
def clean(s):
    return TAG.sub("", s or "").replace("&quot;", '"').replace("&amp;", "&").strip()

rows = []
for line in open(SRC, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    r = json.loads(line)
    items = r.get("blog", {}).get("items", [])
    loc = (r.get("local", {}).get("items") or [{}])[0]
    bloggers = {it.get("bloggername") for it in items}
    dates = sorted(it.get("postdate", "") for it in items if it.get("postdate"))
    # 카페명 토큰이 스니펫에 실제 등장하는 비율 (관련성 프록시)
    key = clean(r["spot_name"]).split("(")[0].strip().replace(" ", "")
    rel = sum(1 for it in items
              if key and key in clean(it.get("title", "") + it.get("description", "")).replace(" ", ""))
    rows.append({
        "카페명": r["spot_name"],
        "지역": r.get("region"),
        "정보등급": r.get("info_richness"),
        "블로그총량": r.get("blog", {}).get("total", 0),
        "스니펫수": len(items),
        "카페명포함스니펫": rel,
        "블로거수": len(bloggers),
        "최신포스트": dates[-1] if dates else "",
        "지역검색_상호": clean(loc.get("title", "")),
        "지역검색_업종": loc.get("category", ""),
        "지역검색_주소": loc.get("roadAddress") or loc.get("address", ""),
        "스니펫예시": clean(items[0].get("description", ""))[:100] if items else "",
    })

rows.sort(key=lambda x: (-{"low": 2, "mid": 1, "high": 0}.get(x["정보등급"] or "", 0), -x["블로그총량"]))
with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"저장: {OUT} ({len(rows)}행)")

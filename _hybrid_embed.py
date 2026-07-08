# -*- coding: utf-8 -*-
"""
하이브리드 코퍼스 — 팀원 병합 풀(뼈대) + 우리 자연어 요약(살).

① 조인율 측정: seed 410곳 이름 ↔ 우리 정제본 spot_name (정규화 매칭)
② 매칭된 카페만 임베딩: text = 블로그 요약 > 유튜브 요약
   → chroma_smoke/smoke 컬렉션에 source="hybrid"로 추가 (기존 문서 무손상)

사용: python _hybrid_embed.py          # 측정 + 등록
      python _hybrid_embed.py dry     # 측정만
"""
import json
import os
import re
import sys

import chromadb
from openai import OpenAI

ROOT = os.path.dirname(os.path.abspath(__file__))
RICH_ORDER = {"high": 0, "mid": 1, "low": 2}

env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
client = OpenAI(api_key=env["OPENAI_KEY"])

def norm(s):
    s = (s or "").split("(")[0]
    return re.sub(r"[^\w가-힣]", "", s.lower())

# ---- 폐업 명단 (closed_hint) — 모든 소스에 전역 적용 ----
closed = set()
for line in open(os.path.join(ROOT, "data", "processed", "네이버 정제.jsonl"), encoding="utf-8"):
    line = line.strip()
    if line:
        r = json.loads(line)
        if r.get("closed_hint"):
            closed.add(norm(r["spot_name"]))
print(f"폐업 제외 명단: {len(closed)}곳")

# ---- 우리 요약 인덱스 (정규화 이름 → 요약/지역) ----
ours = {}
spots = json.load(open(os.path.join(ROOT, "data", "processed", "유튜브 정제.json"), encoding="utf-8"))
best = {}
for s in spots:
    n = s["spot_name"]
    if n not in best or RICH_ORDER.get(s.get("info_richness"), 9) < RICH_ORDER.get(best[n].get("info_richness"), 9):
        best[n] = s
for n, s in best.items():
    k = norm(n)
    if k in closed:
        continue   # 폐업은 유튜브 요약 경로로도 못 들어옴
    if k and (s.get("summary") or "").strip() and s.get("info_richness") in ("high", "mid"):
        ours.setdefault(k, {})["yt"] = s["summary"]
        ours[k]["region"] = s.get("region")
        ours[k]["spot_name"] = n
for line in open(os.path.join(ROOT, "data", "processed", "네이버 정제.jsonl"), encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    r = json.loads(line)
    if r.get("closed_hint") or not (r.get("summary_blog") or "").strip():
        continue
    k = norm(r["spot_name"])
    if k:
        ours.setdefault(k, {})["blog"] = r["summary_blog"]
        ours[k].setdefault("spot_name", r["spot_name"])

# ---- seed 풀과 조인 ----
seed_docs = []
for line in open(os.path.join(ROOT, "data", "rag", "jeju_cafe_public.jsonl"), encoding="utf-8-sig"):
    line = line.strip()
    if line:
        seed_docs.append(json.loads(line))

matched, miss = [], []
for d in seed_docs:
    name = (d.get("text") or "").split("\n")[0].replace("카페명:", "").strip()
    k = norm(name)
    o = ours.get(k)
    if o and (o.get("blog") or o.get("yt")):
        matched.append((d, name, o))
    else:
        miss.append(name)

print(f"seed 풀 {len(seed_docs)}곳 중 우리 요약과 조인: {len(matched)}곳 ({len(matched)/len(seed_docs):.0%})")
print(f"미조인 예시: {miss[:10]}")

if len(sys.argv) > 1 and sys.argv[1] == "dry":
    sys.exit(0)

# ---- 하이브리드 문서 등록 ----
docs = []
for d, name, o in matched:
    text = o.get("blog") or o.get("yt")
    meta = d.get("metadata") or {}
    docs.append((f"hy::{meta.get('cafe_id', name)}", text,
                 {"source": "hybrid", "spot_name": o.get("spot_name") or name,
                  "region": o.get("region") or meta.get("region") or "기타",
                  "tier": meta.get("quality_tier", ""),
                  "text_from": "blog" if o.get("blog") else "youtube"}))

col = chromadb.PersistentClient(path=os.path.join(ROOT, "chroma_smoke")).get_collection("smoke")
col.delete(where={"source": "hybrid"})   # 기존 hybrid 전부 삭제 후 재등록 (폐업 누수 정화)
new = docs
print(f"등록 대상 {len(new)} (기존 hybrid 삭제 후 재등록)")
if new:
    embs = []
    texts = [d[1] for d in new]
    for i in range(0, len(texts), 100):
        resp = client.embeddings.create(model="text-embedding-3-large", input=texts[i:i+100])
        embs.extend(e.embedding for e in resp.data)
        print(f"  임베딩 {min(i+100, len(texts))}/{len(texts)}", flush=True)
    col.add(ids=[d[0] for d in new], documents=[d[1] for d in new],
            metadatas=[d[2] for d in new], embeddings=embs)
print(f"완료 — 컬렉션 총 {col.count()}문서")

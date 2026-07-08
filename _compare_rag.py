# -*- coding: utf-8 -*-
"""
3자 RAG 비교 — 같은 질문을 세 코퍼스에 던져 top-5 비교 (읽기 전용).

  youtube : chroma_smoke/smoke (source=youtube) — 유튜브 요약 1~2문장
  blog    : chroma_smoke/smoke (source=blog)    — 네이버 블로그 정제 1~2문장
  seed    : chroma_db/jeju_cafe_public          — 팀원 구조화 프로필 (410곳)

임베딩 모델 동일(text-embedding-3-large) → 점수 비교 가능.
"""
import io
import os
import sys

import chromadb
from openai import OpenAI

ROOT = os.path.dirname(os.path.abspath(__file__))
# 콘솔 인코딩 문제 회피: 결과를 utf-8 파일로도 남김
sys.stdout = io.TextIOWrapper(open(os.path.join(ROOT, "_compare_out.txt"), "wb"), encoding="utf-8")

env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
client = OpenAI(api_key=env["OPENAI_KEY"])

smoke = chromadb.PersistentClient(path=os.path.join(ROOT, "chroma_smoke")).get_collection("smoke")
seed = chromadb.PersistentClient(path=os.path.join(ROOT, "chroma_db")).get_collection("jeju_cafe_public")

QUERIES = [
    "성산에서 오션뷰 보면서 커피 마시고 싶어",
    "조용히 책 읽기 좋은 카페",
    "노을 맛집인 카페 알려줘",
    "애월에서 강아지랑 같이 갈 수 있는 브런치 카페",
    "주차 편하고 자리 넓은 대형 카페",
    "웨이팅 없이 여유롭게 있을 수 있는 로컬 카페",
    "소품샵 구경도 할 수 있는 감성 카페",
    "비 오는 날 가기 좋은 분위기 있는 카페",
]

def name_of(meta, doc):
    if "spot_name" in meta:
        return meta["spot_name"]
    # seed 문서는 text 첫 줄이 "카페명: XXX"
    first = (doc or "").split("\n")[0]
    return first.replace("카페명:", "").strip() or meta.get("cafe_id", "?")

for q in QUERIES:
    q_emb = client.embeddings.create(model="text-embedding-3-large", input=[q]).data[0].embedding
    print(f"\n{'='*72}\n❓ {q}")
    for label, col, where in (("youtube", smoke, {"source": "youtube"}),
                              ("blog   ", smoke, {"source": "blog"}),
                              ("seed   ", seed, None),
                              ("hybrid ", smoke, {"source": "hybrid"})):
        kw = {"query_embeddings": [q_emb], "n_results": 5}
        if where:
            kw["where"] = where
        res = col.query(**kw)
        print(f"  [{label}]")
        for m, d, doc in zip(res["metadatas"][0], res["distances"][0], res["documents"][0]):
            print(f"    {1-d:.3f} {name_of(m, doc)} ({m.get('region','?')})")

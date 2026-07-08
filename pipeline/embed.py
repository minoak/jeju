# -*- coding: utf-8 -*-
"""
[파이프라인 계약] 임베딩 — 유튜브/블로그 정제본 → Chroma 적재 (+스모크 검증).

입력:  data/processed/네이버 정제.jsonl    summary_blog (빈 값·closed 제외) → source=blog
       data/processed/review_master.csv   판정=유지 카페만 편입 (보류/제외 차단)
출력:  chroma_smoke/ 컬렉션 "smoke" (text-embedding-3-large, cosine)
       ※ 서빙 코퍼스 결정(7/8): 팀원 병합 풀(hybrid, _hybrid_embed.py) + blog(유지).
         우리 유튜브 문서는 은퇴 — 팀원 풀이 더 정확(검증됨)하다는 민옥 결정.
         유튜브 요약은 hybrid의 텍스트 폴백으로만 사용.
       ※ 병합(merge.py) 완성 후 카드 단위 chroma_db/로 승격 예정 — 지금은 MVP용
키:    .env OPENAI_KEY
소비자: app/server.py (/search)

사용:
  python pipeline/embed.py           # 적재(있으면 스킵) + 스모크 8문항
  python pipeline/embed.py rebuild   # 재적재

원칙: 검색은 유사도만 — 인기 수치(mention/블로거수)는 임베딩에 안 넣음 (원칙 8)
"""
import json
import os
import sys

import chromadb
from openai import OpenAI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RICH_ORDER = {"high": 0, "mid": 1, "low": 2}

env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
client = OpenAI(api_key=env["OPENAI_KEY"])

def build_docs():
    import csv
    docs = []
    # 지역 참조용 (문서로는 안 만듦 — 유튜브 문서 은퇴)
    spots = json.load(open(os.path.join(ROOT, "data", "processed", "유튜브 정제.json"), encoding="utf-8"))
    best = {}
    for s in spots:
        n = s["spot_name"]
        if n not in best or RICH_ORDER.get(s.get("info_richness"), 9) < RICH_ORDER.get(best[n].get("info_richness"), 9):
            best[n] = s
    # 판정=유지 화이트리스트
    keep = set()
    review = os.path.join(ROOT, "data", "processed", "review_master.csv")
    for r in csv.DictReader(open(review, encoding="utf-8-sig")):
        if r.get("판정") == "유지":
            keep.add(r["카페명"])
    path = os.path.join(ROOT, "data", "processed", "네이버 정제.jsonl")
    n_hold = 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if not (r.get("summary_blog") or "").strip() or r.get("closed_hint"):
            continue
        n = r["spot_name"]
        if n not in keep:
            n_hold += 1
            continue   # 보류/제외 판정 카페는 서빙 편입 안 함
        docs.append((f"blog::{n}", r["summary_blog"],
                     {"source": "blog", "spot_name": n,
                      "region": (best.get(n) or {}).get("region") or "기타",
                      "richness": r.get("info_richness_blog") or ""}))
    print(f"판정 비유지로 차단: {n_hold}곳")
    return docs

def embed_texts(texts, batch=100):
    out = []
    for i in range(0, len(texts), batch):
        resp = client.embeddings.create(model="text-embedding-3-large", input=texts[i:i+batch])
        out.extend(d.embedding for d in resp.data)
        print(f"  임베딩 {min(i+batch, len(texts))}/{len(texts)}", flush=True)
    return out

SMOKE_QUERIES = [
    "성산에서 오션뷰 보면서 커피 마시고 싶어",
    "조용히 책 읽기 좋은 카페",
    "노을 맛집인 카페 알려줘",
    "애월에서 강아지랑 같이 갈 수 있는 브런치 카페",
    "주차 편하고 자리 넓은 대형 카페",
    "웨이팅 없이 여유롭게 있을 수 있는 로컬 카페",
    "소품샵 구경도 할 수 있는 감성 카페",
    "비 오는 날 가기 좋은 분위기 있는 카페",
]

if __name__ == "__main__":
    cdb = chromadb.PersistentClient(path=os.path.join(ROOT, "chroma_smoke"))
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        try:
            cdb.delete_collection("smoke")
        except Exception:
            pass
    col = cdb.get_or_create_collection("smoke", metadata={"hnsw:space": "cosine"})

    if col.count() == 0:
        docs = build_docs()
        n_yt = sum(1 for d in docs if d[2]["source"] == "youtube")
        print(f"적재: 총 {len(docs)}문서 (유튜브 {n_yt} / 블로그 {len(docs)-n_yt})")
        embs = embed_texts([d[1] for d in docs])
        for i in range(0, len(docs), 500):
            chunk = docs[i:i+500]
            col.add(ids=[d[0] for d in chunk],
                    documents=[d[1] for d in chunk],
                    metadatas=[d[2] for d in chunk],
                    embeddings=embs[i:i+500])
        print(f"적재 완료: {col.count()}건")
    else:
        print(f"[스킵] 기존 컬렉션 {col.count()}건 (재적재는 'rebuild')")

    print("\n" + "=" * 70)
    for q in SMOKE_QUERIES:
        q_emb = client.embeddings.create(model="text-embedding-3-large", input=[q]).data[0].embedding
        print(f"\n❓ {q}")
        for src in ("youtube", "blog"):
            res = col.query(query_embeddings=[q_emb], n_results=5, where={"source": src})
            print(f"  [{src}]")
            for m, d, doc in zip(res["metadatas"][0], res["distances"][0], res["documents"][0]):
                print(f"    {1-d:.3f} {m['spot_name']} ({m['region']}) — {doc[:50]}")

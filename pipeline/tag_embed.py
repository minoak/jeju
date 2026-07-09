# -*- coding: utf-8 -*-
"""
태그 사전 임베딩 생성 — "임베딩은 찾지 않고 번역한다"의 앵커 구축 (W1 본판 산출물).

무엇을:
  활성 태그(tagdict.active_tags())의 표현들 — tag 자신 + 모든 synonym — 을
  각각 임베딩해서 "앵커"로 저장한다. 런타임 번역기(app/tagtrans.py)가 사전 밖
  조건어("석양빛", "물멍")를 받으면 이 앵커들과 코사인 비교해 가장 가까운 태그로
  번역한다. 앵커는 카페가 아니라 어휘다 — 임베딩 공간에 카페 831장이 아니라
  태그 표현 수십 개만 들어간다 (설계: 임베딩=사전).

입력:  app/tagdict.py (활성 태그 + synonym). 태그사전v2.json 있으면 그것, 없으면 픽스처.
출력:  data/rag/태그사전_임베딩.npz  {vectors(N,D) 정규화됨, tags(N), exprs(N)}
모델:  text-embedding-3-large (server.py·chroma 코퍼스와 동일 — 같은 공간이어야 비교 가능)
키:    .env OPENAI_KEY

실행 (로컬, 태그 사전 바뀔 때마다 1회):
  python pipeline/tag_embed.py
  → 앵커 수십 개, 몇 초, 비용 무시할 수준. 산출 후 서버 재기동하면 번역기가 자동 승격.

원칙:
  - 벡터는 저장 시 L2 정규화 → 런타임 코사인이 내적 한 번으로 끝 (빠름)
  - except 삼킴 금지: 실패 표현은 경고 출력
  - 표현이 태그별로 여럿이라 한 앵커가 한 태그를 가리킨다 (최근접 앵커 → 그 태그)
"""
import json
import os
import sys

import numpy as np
from openai import OpenAI

try:
    from app import tagdict
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import tagdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "rag", "태그사전_임베딩.npz")
MODEL = "text-embedding-3-large"

env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
client = OpenAI(api_key=env["OPENAI_KEY"])


def build_anchors():
    """활성 태그의 (tag + synonyms) 표현들을 (표현, 태그) 앵커 목록으로."""
    exprs, tags = [], []
    seen = set()
    for tg in tagdict.active_tags():
        for expr in [tg] + tagdict.synonyms_of(tg):
            key = expr.strip().lower()
            if not expr.strip() or key in seen:
                continue
            seen.add(key)
            exprs.append(expr)
            tags.append(tg)
    return exprs, tags


def main():
    exprs, tags = build_anchors()
    print(f"[tag_embed] 앵커 {len(exprs)}개 (활성 태그 {len(set(tags))}종)")
    resp = client.embeddings.create(model=MODEL, input=exprs)
    vecs = np.array([d.embedding for d in resp.data], dtype=np.float32)
    # L2 정규화 — 런타임 코사인 = 내적
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = vecs / np.clip(norms, 1e-9, None)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez(OUT, vectors=vecs, tags=np.array(tags), exprs=np.array(exprs))
    print(f"[tag_embed] 저장 → {OUT}  (vectors {vecs.shape})")

    # 육안 검증: 사전 밖 표현 몇 개가 어디로 번역되는지 (앵커끼리 최근접은 자기 자신이라 무의미,
    # 실제 검증은 tagtrans.py 스모크에서). 여기선 앵커 무결성만.
    assert vecs.shape[0] == len(exprs) == len(tags)
    print("[tag_embed] 앵커 무결성 OK — 번역 검증은 `python -m app.tagtrans` 스모크로")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
태그 임베딩 번역기 본판 — 사용자 언어 → 통제 태그 어휘 (translate_stub.py 승계).

역할 (설계의 핵심: "임베딩은 찾지 않고 번역한다"):
  조건어 하나(term)를 받아 태그로 번역한다. 3단 —
    1. exact      : tag/synonym 문자열 정확 매칭 (tagdict). "강아지"→애견동반
    2. embedding  : 태그사전 임베딩 앵커와 코사인 최근접 (threshold 이상). "석양빛"→노을
    3. unresolved : 둘 다 실패. 강제 번역 금지 — 정직한 실패의 재료 (조건부 grade 트리거)

  이 3단이 stub과 다른 점은 2단(embedding)의 유무다. 앵커 npz(pipeline/tag_embed.py 산출)가
  있고 embed_fn이 주입되면 2단이 살아나고, 없으면 exact만 하는 stub과 동일하게 동작한다
  (graceful degradation — 앵커 생성 전에도 서버는 죽지 않고 exact로 돈다).

계약 (stub과 동일 시그니처):
  translate(term) -> {"input": term, "tag": str|None,
                      "method": "exact|embedding|unresolved", "score": float}

주입:
  TagTranslator(embed_fn) — embed_fn(text)->list[float]. server.py가 자기 OpenAI
  client로 만들어 주입한다 (client 중복 생성 회피, 같은 모델 보장). 미주입 시 exact만.
"""
import os
import re

import numpy as np

try:
    from app import tagdict
except ImportError:
    import tagdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NPZ = os.path.join(ROOT, "data", "rag", "태그사전_임베딩.npz")

# 임베딩 번역 채택 최소 코사인. exact 밖 표현을 태그로 "붙일" 최소 확신도.
# 초기값 0.55 — 실측 튜닝 대상 (너무 낮으면 만능 자석, 너무 높으면 unresolved 남발).
# 튜닝 근거: tagtrans 스모크 + 골드셋 무드형(G002/G011) Tag Coverage 변화로 정한다.
THRESHOLD = 0.55

_TAG = re.compile(r"<[^>]+>")


def _norm(s):
    s = _TAG.sub("", s or "").split("(")[0]
    return re.sub(r"[^\w가-힣]", "", s.lower())


class TagTranslator:
    def __init__(self, embed_fn=None):
        self.embed_fn = embed_fn
        # 1단: exact 맵 (정규화 표현 → 태그). tag 자신 + synonym.
        self.exact = {}
        for tg in tagdict.active_tags():
            self.exact.setdefault(_norm(tg), tg)
            for sy in tagdict.synonyms_of(tg):
                self.exact.setdefault(_norm(sy), tg)
        # 2단: 앵커 (있으면). 없으면 embedding 단계 자동 비활성.
        self.vecs = self.anchor_tags = None
        if os.path.exists(NPZ):
            d = np.load(NPZ, allow_pickle=True)
            self.vecs = d["vectors"].astype(np.float32)        # (N,D) 정규화됨
            self.anchor_tags = [str(t) for t in d["tags"]]
        self._cache = {}
        self._embed_active = self.vecs is not None and self.embed_fn is not None

    @property
    def embedding_ready(self):
        return self._embed_active

    def translate(self, term):
        key = _norm(term)
        if not key:
            return {"input": term, "tag": None, "method": "unresolved", "score": 0.0}
        # 1단 exact
        if key in self.exact:
            return {"input": term, "tag": self.exact[key], "method": "exact", "score": 1.0}
        # 2단 embedding (앵커+embed_fn 있을 때만)
        if not self._embed_active:
            return {"input": term, "tag": None, "method": "unresolved", "score": 0.0}
        if term in self._cache:
            return dict(self._cache[term])
        try:
            v = np.asarray(self.embed_fn(term), dtype=np.float32)
        except Exception as e:
            print(f"[tagtrans] embed 실패 [{term}] {type(e).__name__}: {e}")
            return {"input": term, "tag": None, "method": "unresolved", "score": 0.0}
        v /= (np.linalg.norm(v) + 1e-9)
        sims = self.vecs @ v
        i = int(sims.argmax())
        s = float(sims[i])
        if s >= THRESHOLD:
            r = {"input": term, "tag": self.anchor_tags[i], "method": "embedding", "score": round(s, 3)}
        else:
            # 최근접이 threshold 미달 — 해석 불가 (강제 번역 금지). 근접 태그는 참고로만 남긴다.
            r = {"input": term, "tag": None, "method": "unresolved", "score": round(s, 3),
                 "nearest": self.anchor_tags[i]}
        self._cache[term] = r
        return dict(r)


# ---- stub 호환: 모듈 레벨 translate (embed 없이 exact만 — 기존 import 지점 무해 대체) ----
_DEFAULT = TagTranslator(embed_fn=None)


def translate(term):
    """embed_fn 없는 기본 번역 (exact/unresolved만). 임베딩 번역은 TagTranslator(embed_fn) 인스턴스로."""
    return _DEFAULT.translate(term)


if __name__ == "__main__":
    # 스모크: 앵커 npz가 있으면 임베딩 번역까지, 없으면 exact만 확인.
    # 임베딩 검증은 .env OPENAI_KEY 필요 (embed_fn 주입).
    import sys

    print(f"[tagtrans] 앵커 npz: {'있음' if os.path.exists(NPZ) else '없음 (exact만)'}")

    # exact 단독 (embed 없이)
    for t in ["강아지", "선셋", "조용한", "노키즈", "물멍"]:
        print(f"  exact-only  {t:6} → {translate(t)}")

    if os.path.exists(NPZ):
        try:
            from openai import OpenAI
            env = {}
            for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            cli = OpenAI(api_key=env["OPENAI_KEY"])
            embed = lambda s: cli.embeddings.create(model="text-embedding-3-large", input=[s]).data[0].embedding
            tr = TagTranslator(embed_fn=embed)
            print(f"[tagtrans] 임베딩 번역 활성={tr.embedding_ready}, threshold={THRESHOLD}")
            # 사전 밖 표현 — 여기가 stub과 갈리는 지점
            for t in ["석양빛", "해질녘", "물멍", "인스타 감성", "빵이 맛있는", "뷰 맛집", "노래방"]:
                print(f"  embed  {t:8} → {tr.translate(t)}")
        except Exception as e:
            print(f"[tagtrans] 임베딩 스모크 건너뜀 ({type(e).__name__}: {e})")
    else:
        print("[tagtrans] 앵커 없음 — `python pipeline/tag_embed.py` 먼저 실행하면 임베딩 번역 활성화")

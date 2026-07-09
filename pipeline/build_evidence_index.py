# -*- coding: utf-8 -*-
"""
[파이프라인 계약] 근거 스니펫 pre-index — /evidence 의 57MB 런타임 로드를 오프라인으로 옮김.

배경:  app/server.py 의 _load_snippets() 가 매 첫 호출마다 data/raw/네이버 크롤링.jsonl(57MB)을
       통째로 파싱했다 → Render 무료 티어에서 첫 /evidence 가 ~17.6초, 프론트 20초 timeout 에 걸려
       "근거 서버에 연결하지 못했어요" 발생 (2026-07-10 실측). 무거운 일은 오프라인에서 한 번만.

입력:  data/processed/cards.json            정본명·aliases (ALIAS2CANON 구성)
       data/raw/네이버 크롤링.jsonl          블로그 스니펫 원천 (57MB)
       data/raw/네이버 재검색 크롤링.jsonl   재검색 보강분

출력:  data/processed/evidence_snippets.json  { 정본명: [ {t, date, blogger, link}, ... ] }
소비자: app/server.py _load_snippets() — 이 파일이 있으면 57MB 대신 이것만 로드 (< 0.5초)

원칙: 서버의 _SNIPPETS 생성 규칙과 100% 동일해야 함 (한쪽만 바꾸면 근거가 어긋남).
      ⚠️ 아래 매칭 규칙(_norm/키 포함/postdate>=20240101)을 고치면 server.py 폴백도 같이 고칠 것.
사용:  python pipeline/build_evidence_index.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
TAG_RE = re.compile(r"<[^>]+>")

def _clean(s):
    return TAG_RE.sub("", s or "").strip()

def _norm(s):
    s = _clean(s).split("(")[0]
    return re.sub(r"[^\w가-힣]", "", s.lower())

# ---- cards.json 으로 이름 변형 -> 정본 매핑 (server.py 와 동일 규칙) ----
ALIAS2CANON = {}
for c in json.load(open(P("data", "processed", "cards.json"), encoding="utf-8")):
    ALIAS2CANON[c["name"]] = c["name"]
    for a in c.get("aliases", []):
        ALIAS2CANON[a] = c["name"]

# ---- 스니펫 접기 (server.py _load_snippets 의 _SNIPPETS 블록과 동일) ----
snip = {}
n_lines = 0
for idx, raw_name in enumerate(("네이버 크롤링.jsonl", "네이버 재검색 크롤링.jsonl")):
    p = P("data", "raw", raw_name)
    if not os.path.exists(p):
        print("[build_evidence] WARN missing raw file #%d" % idx)
        continue
    for line in open(p, encoding="utf-8", errors="replace"):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        n_lines += 1
        key = _norm(rec.get("cleaned_name") or rec["spot_name"])
        canon = ALIAS2CANON.get(rec["spot_name"], rec["spot_name"])
        rows = []
        for it in rec.get("blog", {}).get("items", []):
            txt = _clean(it.get("title", "") + " " + it.get("description", ""))
            if key and key in _norm(txt) and it.get("postdate", "") >= "20240101":
                rows.append({"t": txt, "date": it.get("postdate", ""),
                             "blogger": it.get("bloggername", ""), "link": it.get("link", "")})
        if rows:
            snip.setdefault(canon, []).extend(rows)

out_p = P("data", "processed", "evidence_snippets.json")
json.dump(snip, open(out_p, "w", encoding="utf-8"), ensure_ascii=False)
total = sum(len(v) for v in snip.values())
size_kb = os.path.getsize(out_p) // 1024
print("[build_evidence] %d lines -> %d snippets / %d cafes" % (n_lines, total, len(snip)))
print("[build_evidence] saved: data/processed/evidence_snippets.json (%d KB)" % size_kb)

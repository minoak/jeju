# -*- coding: utf-8 -*-
"""LLM 필터 검증 (작업용): 무관 결과 제거 + 이름 매치 보존 + 브라우즈 무제거"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.server import search

for q in ("조용한 카페 혼자 책읽기", "성산 오션뷰 카페", "해지개", "애월 카페"):
    r = search(q, k=10)
    print(f"--- {q!r}: 카드 {len(r['cards'])} / 제거 {r['filtered']} / browse={r['browse']}")
    for c in r["cards"][:10]:
        pin = "PIN" if c.get("name_match") else "   "
        print(f"  {pin} {c['score']:.2f} {c['spot_name'][:16]:16} | {(c.get('reason') or '')[:52]}")

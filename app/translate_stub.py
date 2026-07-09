# -*- coding: utf-8 -*-
"""
번역기 스텁 -- 자연어 조건 조각 -> 태그 (W2-4 지침 (0)-3)

⚠ 임시 파일: W1 본판(app/translate.py) 완료 시 이 파일 대신 그걸 임포트하도록 교체.
   반환 계약은 W1 본판과 동일 시그니처 --
     translate(term) -> {"input": term, "tag": str|None,
                         "method": "exact|unresolved", "score": 1.0|0.0}
   본판은 exact|embedding|unresolved 3단이지만, 스텁은 임베딩 없이 exact만.
   (임베딩 폴백은 W5 통합 시 server.py 기존 경로가 담당)

원칙:
  - 완전 일치만. 부분 포함 매칭 금지 -- "승마클럽"에 "마"가 들어있다고
    엉뚱한 태그로 붙던 사건 재발 방지 (HANDOFF 결정 6).
  - 보류 태그(status="보류")는 매칭 대상에서 제외 -> unresolved.
  - 강제 번역 금지 -- 못 찾으면 unresolved가 정답이다. 정직한 실패가 컨셉.
"""
import re

try:
    from app import tagdict  # 패키지 경로 실행 (python -m app.translate_stub, W5 배선)
except ImportError:
    import tagdict  # app/ 폴더 안에서 직접 실행 (python translate_stub.py)

# ---- server.py:63~67 _norm 미러 -- 정본은 server.py ----
# 질의 조각과 사전 항목을 같은 잣대로 정규화해야 완전 일치가 성립한다.
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(s):
    return _TAG_RE.sub("", s or "").strip()


def _norm(s):
    s = _clean(s).split("(")[0]
    return re.sub(r"[^\w가-힣]", "", s.lower())


# ---- 정규화 룩업 구축: norm(태그명|synonym) -> 태그명 (활성 태그만) ----
_NORM2TAG = {}
for _t in tagdict.TAGDICT["tags"]:
    if _t.get("status") == "보류":
        continue  # 보류 태그는 매칭 대상 제외 (unresolved 처리)
    for _v in [_t["tag"]] + list(_t.get("synonyms", [])):
        _key = _norm(_v)
        if not _key:
            continue
        _prev = _NORM2TAG.get(_key)
        if _prev and _prev != _t["tag"]:
            # except 삼킴 금지 정신 -- 사전 충돌은 조용히 덮지 않고 경고
            print(f"[translate_stub] 경고: 동의어 충돌 '{_v}' ({_prev} vs {_t['tag']}), "
                  f"먼저 등록된 {_prev} 유지")
            continue
        _NORM2TAG[_key] = _t["tag"]


def translate(term):
    """자연어 조건 조각 1개 -> 태그 번역 시도 (완전 일치만).

    반환 dict는 그대로 TraceState.translation[] 원소가 된다.
    """
    tag = _NORM2TAG.get(_norm(term))
    if tag:
        return {"input": term, "tag": tag, "method": "exact", "score": 1.0}
    return {"input": term, "tag": None, "method": "unresolved", "score": 0.0}


if __name__ == "__main__":
    # ---- 스모크: W3 지침 명시 케이스 + 보강 케이스 ----
    cases = [
        # (입력, 기대 tag, 기대 method)
        ("노을 맛집", "노을", "exact"),
        ("반려견동반", "애견동반", "exact"),
        ("조용한", "조용함", "exact"),
        ("물멍하기 좋은", None, "unresolved"),   # 사전 밖 -> 강제 번역 금지
        ("테이크아웃", None, "unresolved"),      # 보류 태그(포장) -> 매칭 제외
        ("오션뷰", "오션뷰", "exact"),           # 태그명 자기 자신
        ("포토스팟", "포토존", "exact"),         # 승격 태그 확인
        ("옥상", "루프탑", "exact"),
        ("한라산 전망", "한라산뷰", "exact"),    # 승격 태그 + 공백 정규화
        ("레트로", None, "unresolved"),          # 보류 태그(빈티지)
        ("승마클럽", None, "unresolved"),        # 부분 포함 매칭 금지 회귀 케이스
        ("바다", None, "unresolved"),            # "바다뷰"의 부분 문자열 -- 완전 일치 아님
    ]
    fails = []
    for term, want_tag, want_method in cases:
        r = translate(term)
        ok = (r["tag"] == want_tag and r["method"] == want_method
              and r["score"] == (1.0 if want_method == "exact" else 0.0))
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] translate({term!r}) -> tag={r['tag']} method={r['method']} score={r['score']}")
        if not ok:
            fails.append(term)

    # ---- tagdict 헬퍼 스모크 ----
    checks = [
        ("is_hard(애견동반)=True", tagdict.is_hard("애견동반") is True),
        ("is_hard(주차편함)=False", tagdict.is_hard("주차편함") is False),
        ("is_hard(노키즈존)=True", tagdict.is_hard("노키즈존") is True),
        ("active_tags()=23개", len(tagdict.active_tags()) == 23),
        ("보류 태그 활성 제외", "포장" not in tagdict.active_tags()),
        ("exclude_map에 노키즈존", "노키즈존" in tagdict.exclude_map()),
        ("synonyms_of(노을)에 선셋", "선셋" in tagdict.synonyms_of("노을")),
    ]
    for label, ok in checks:
        print(f"  [{'OK  ' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    total = len(cases) + len(checks)
    if fails:
        print(f"[translate_stub] 스모크 실패 {len(fails)}/{total}: {fails}")
        raise SystemExit(1)
    print(f"[translate_stub] 스모크 전부 통과 ({total}/{total})")

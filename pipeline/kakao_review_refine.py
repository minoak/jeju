# -*- coding: utf-8 -*-
"""
[파이프라인 계약] 카카오맵 리뷰 1차 정제 — 경량 모델로 "믿음직하냐" 신호 추리기.

입력:  data/processed/카카오리뷰.jsonl     카페당 1줄 {place_id, spot_name, reviews:[{text,star}], rating_avg, rating_count}
출력:  data/processed/카카오리뷰정제.jsonl   카페당 1줄 (JSONL append + 이어달리기 체크포인트)
키:    .env OPENAI_KEY

설계 (2026-07-09 민옥·코워크 합의):
  - 카카오 리뷰는 별점 긍정 편향(5★ 67%). 평균 별점은 변별력 낮음 → 진짜 신뢰 신호는 소수의 부정·혼합에 있다.
  - 그래서 LLM의 직업은 "평균 요약"이 아니라 "소수의 경고를 건져 올리기".
  - 별점 tone은 코드가 계산(원칙 8: 수치는 LLM 우회). LLM은 텍스트로 무엇/왜만.
  - quote는 원문 부분문자열만(코드 검증). 지어내면 버린다.
  - 산출물은 표시·근거·반응 층 전용 — 임베딩 편입 금지(결정 20, 만능 자석 방지).

사용 (같은 리포 어디서 실행하든 ROOT 자동):
  python pipeline/kakao_review_refine.py            # 이어달리기 (이미 정제된 카페 스킵)
  python pipeline/kakao_review_refine.py rebuild    # 처음부터
  (윈도우 한글 안전: py -3.13 -X utf8 pipeline/kakao_review_refine.py)

소비자: pipeline/merge.py — caution→신호층, quotes→근거층, tone/summary→반응 (유튜브 댓글과 같은 층)
"""
import json
import os
import sys
import time
from collections import Counter

from openai import OpenAI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, "data", "processed", "카카오리뷰.jsonl")
OUT = os.path.join(ROOT, "data", "processed", "카카오리뷰정제.jsonl")

# ---- .env ----
env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
client = OpenAI(api_key=env["OPENAI_KEY"])

# ---- 별점 tone: 코드가 계산 (원칙 8) ----
# 기준선: 전체 1~2★ 비율 ~9%. 그 위로 얼마나 쏠렸나로 tone 판정.
def star_tone(reviews):
    stars = [r.get("star") for r in reviews if isinstance(r, dict) and r.get("star") is not None]
    if not stars:
        return "", 0.0
    neg = sum(1 for s in stars if s <= 2)
    ratio = neg / len(stars)
    if ratio >= 0.30:
        return "부정", round(ratio, 3)
    if ratio >= 0.12:
        return "혼합", round(ratio, 3)
    return "긍정", round(ratio, 3)

_SYS = (
    "너는 카페 리뷰 정제가다. 한 카페의 카카오맵 방문자 리뷰들(별점 포함)과, 코드가 계산한 여론 톤을 받는다.\n"
    "이 데이터의 목적은 '이 카페가 믿을 만한가'를 돕는 것. 카카오 별점은 긍정으로 쏠려 있으니, "
    "칭찬을 나열하기보다 **여러 방문자가 공통으로 지적한 아쉬운 점을 정확히 건지는 것**이 더 중요하다.\n"
    "JSON으로만 답하라:\n"
    '{"summary": "방문자 여론 1~2문장 — 좋은 점과 아쉬운 점의 균형. 미화 금지.",\n'
    ' "praise": ["반복 언급된 강점 키워드 2~4개 (분위기, 특정 메뉴, 뷰 등)"],\n'
    ' "caution": ["여러 명(대략 3명 이상)이 공통으로 지적한 아쉬운 점만. 1명의 불평은 넣지 말 것. 없으면 빈 배열."],\n'
    ' "quotes": ["리뷰 원문에서 그대로 발췌한 짧은 인용 2~3개. 부정·혼합 의견이 있으면 반드시 1개 포함, 없으면 긍정만."]}\n'
    "규칙: quotes는 반드시 입력 리뷰의 부분 문자열. 없는 내용·과장 광고체 금지. caution은 보수적으로."
)

def refine(spot_name, reviews, tone, ratio, retries=3):
    """LLM 정제. 실패 시 None 반환(기록 안 함 → 재실행 때 재시도)."""
    # 부정·혼합이 잘리지 않게 낮은 별점 먼저 배치. 텍스트는 220자로 절단(원문 검증은 전체로).
    ordered = sorted(reviews, key=lambda r: r.get("star") or 5)
    items = [{"star": r.get("star"), "text": (r.get("text") or "")[:220]} for r in ordered[:30]]
    payload = {"카페": spot_name, "코드계산_여론톤": tone, "부정비율": ratio, "리뷰": items}
    for i in range(retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-5-mini",
                response_format={"type": "json_object"},
                max_completion_tokens=4000,
                reasoning_effort="minimal",
                timeout=30,
                messages=[{"role": "system", "content": _SYS},
                          {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
            d = json.loads(resp.choices[0].message.content or "{}")
            # quote 원문 검증: 전체 리뷰 텍스트의 부분문자열만 통과 (지어내기 차단)
            src = " ".join((r.get("text") or "") for r in reviews)
            quotes = [str(x) for x in (d.get("quotes") or []) if str(x) and str(x) in src][:3]
            praise = [str(x) for x in (d.get("praise") or []) if str(x)][:4]
            caution = [str(x) for x in (d.get("caution") or []) if str(x)][:4]
            return {"review_summary": str(d.get("summary") or ""),
                    "praise": praise, "caution": caution, "quotes": quotes}
        except Exception as e:
            if i == retries - 1:
                print(f"  !! LLM 실패 {spot_name!r}: {type(e).__name__}: {e}")
                return None
            time.sleep(2 ** i)

def main():
    rebuild = len(sys.argv) > 1 and sys.argv[1] == "rebuild"
    if rebuild and os.path.exists(OUT):
        os.remove(OUT)
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["spot_name"])
            except Exception:
                pass

    rows = [json.loads(l) for l in open(IN, encoding="utf-8") if l.strip()]
    todo = [r for r in rows if r.get("spot_name") not in done]
    print(f"대상 {len(todo)} (전체 {len(rows)}, 기존 체크포인트 {len(done)})")

    stats = Counter()
    n_caution = 0
    f = open(OUT, "a", encoding="utf-8")
    for i, r in enumerate(todo):
        name = r.get("spot_name")
        reviews = r.get("reviews") or []
        tone, ratio = star_tone(reviews)
        rec = {"place_id": r.get("place_id"), "spot_name": name,
               "source": "kakao_review_hackathon",
               "review_tone": tone, "neg_ratio": ratio,
               "rating_avg": r.get("rating_avg"), "rating_count": r.get("rating_count"),
               "n_reviews": len(reviews),
               "review_summary": "", "praise": [], "caution": [], "quotes": [],
               "refined_ok": True}
        if reviews:
            out = refine(name, reviews, tone, ratio)
            if out is None:
                continue  # 기록 안 함 — 재실행 이어달리기로 재시도
            rec.update(out)
        # 리뷰 0개 카페(29곳): tone "" + 빈 필드로 기록 (재시도 대상 아님)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        stats[tone or "리뷰없음"] += 1
        if rec["caution"]:
            n_caution += 1
        if (i + 1) % 25 == 0:
            f.flush()
            print(f"  체크포인트 {i+1}/{len(todo)} ... tone={dict(stats)} caution={n_caution}")
        time.sleep(0.05)
    f.close()
    print(f"\n완료: {sum(stats.values())}곳 처리")
    print(f"  여론 톤 분포: {dict(stats)}")
    print(f"  caution(주의점) 붙은 카페: {n_caution}")
    print(f"  → {OUT}")

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
[파이프라인 계약] 댓글 정제 — 쇼츠 댓글 → 의미 정보 추출 (gpt-5-mini).

입력:  data/raw/유튜브 댓글 크롤링.jsonl   (video_id, comments)
       data/raw/유튜브 크롤링.json         (video_id → 제목·태그)
       data/processed/유튜브 정제.json     (video_id → spot_name 귀속)
출력:  data/processed/댓글 정제.jsonl
       { video_id, spot_name(단일 귀속 시), track, is_cafe_related,
         cafe_identified(발굴), info_slots{address,hours,menu_price,etc},
         reaction_summary, reaction_tone, local_tips[], closed_hint,
         n_comments, sum_likes }                    ← 숫자는 코드가 운반

트랙 (7/8 밤 수율 실측 기반):
  A 귀속: 단일 카페 영상 → 댓글을 카페에 붙임 (정보/반응/팁/폐업 분류)
  B 발굴: Pass 1이 카페를 못 뽑은 영상 → 댓글·제목에서 카페 특정 시도
  복수 카페 영상은 귀속 모호 → skip 기록만

용도 제약 (결정 20): 반응은 임베딩 금지 (카피·정렬용). info_slots는 검증 후 텍스트 보강 가능.

사용:
  python pipeline/comments_refine.py 20   # 관통 (random 20)
  python pipeline/comments_refine.py      # 전량 (재실행 시 이어달리기)

규모: 댓글 있는 영상 ~780편 × 1콜 ≈ $1.5, ~30분
"""
import json
import os
import random
import sys
import time
from collections import Counter

from openai import OpenAI, RateLimitError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_COMMENTS = os.path.join(ROOT, "data", "raw", "유튜브 댓글 크롤링.jsonl")
SRC_VIDEOS = os.path.join(ROOT, "data", "raw", "유튜브 크롤링.json")
SRC_SPOTS = os.path.join(ROOT, "data", "processed", "유튜브 정제.json")
OUT = os.path.join(ROOT, "data", "processed", "댓글 정제.jsonl")
MAX_COMMENTS = 40   # 영상당 입력 상한 (좋아요순)

env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
client = OpenAI(api_key=env["OPENAI_KEY"])

SYSTEM = """제주 카페 쇼츠 영상의 댓글 묶음을 읽고 json으로만 답해.

## 규칙 (지어내기 절대 금지 — 댓글에 실제 있는 내용만)
- is_cafe_related: 영상이 카페/디저트 가게와 무관한 바이럴이면 false (그 경우 나머지는 비움)
- cafe_identified: [카페 특정 요청]이 있을 때만 — 댓글이나 제목에 상호명이 명시적으로
  등장하면 그 이름을, 아니면 "". 추측 금지. 지역명·수식어는 상호명이 아님
- info_slots: 댓글에 명시된 것만 그대로 복사 (창작 금지, 없으면 null)
  - address: 주소·위치 (📍 고정댓글 등)
  - hours: 영업시간·휴무
  - menu_price: 메뉴·가격
  - etc: 주차·웨이팅·예약 등 실용 정보
- reaction_summary: 방문자·시청자 반응의 대표 정서 1문장 (팬 인사·잡담·이모지 제외).
  의미 있는 반응이 없으면 ""
- reaction_tone: 긍정|중립|부정|혼합|없음
- local_tips: 댓글 속 근처 가게·명소 추천 (["꽁순이네 고기국수 (도민맛집)"] 형식, 없으면 [])
- closed_hint: 폐업·영업종료·이전 제보가 명시적으로 있으면 true

## 출력 (json만)
{"is_cafe_related": true, "cafe_identified": "", "info_slots": {"address": null,
"hours": null, "menu_price": null, "etc": null}, "reaction_summary": "",
"reaction_tone": "없음", "local_tips": [], "closed_hint": false}"""

def load_jsonl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out

# ---- 조인 준비 ----
videos = json.load(open(SRC_VIDEOS, encoding="utf-8"))
vmeta = videos if isinstance(videos, dict) else {v.get("video_id"): v for v in videos}
spots = json.load(open(SRC_SPOTS, encoding="utf-8"))
spots_per_video = Counter(s["video_id"] for s in spots)
spot_name_of = {}
for s in spots:
    spot_name_of.setdefault(s["video_id"], s["spot_name"])

targets = []
for r in load_jsonl(SRC_COMMENTS):
    if r.get("n_comments", 0) == 0:
        continue
    vid = r["video_id"]
    n_spots = spots_per_video.get(vid, 0)
    if n_spots == 1:
        track = "A귀속"
    elif n_spots == 0:
        track = "B발굴"
    else:
        track = "skip복수"
    targets.append((vid, r, track))
print(f"대상: {len(targets)}편 (A귀속 {sum(1 for t in targets if t[2]=='A귀속')} / "
      f"B발굴 {sum(1 for t in targets if t[2]=='B발굴')} / "
      f"복수skip {sum(1 for t in targets if t[2]=='skip복수')})")

def build_input(vid, rec, track):
    meta = vmeta.get(vid, {})
    title = meta.get("title", "")
    head = f"영상 제목: {title}"
    if track == "A귀속":
        head += f"\n이 영상의 카페: {spot_name_of[vid]}"
    elif track == "B발굴":
        head += "\n[카페 특정 요청] 이 영상은 어느 카페인지 미확인 — 댓글·제목에서 상호명을 찾아줘"
    cs = sorted(rec["comments"], key=lambda c: -c.get("like_count", 0))[:MAX_COMMENTS]
    lines = [f"- ({c.get('like_count',0)}👍) {c.get('text','')[:300]}" for c in cs]
    return head + "\n\n## 댓글 (좋아요순)\n" + "\n".join(lines)

def refine(vid, rec, track, max_retry=5):
    for i in range(max_retry):
        try:
            resp = client.chat.completions.create(
                model="gpt-5-mini",
                response_format={"type": "json_object"},
                max_completion_tokens=4000,
                reasoning_effort="minimal",
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": build_input(vid, rec, track)}],
            )
            content = resp.choices[0].message.content or ""
            if not content.strip():
                print(f"  ⚠ 빈 응답 [{vid}] finish={resp.choices[0].finish_reason}", flush=True)
                return None
            d = json.loads(content)
            slots = d.get("info_slots") or {}
            return {"video_id": vid,
                    "spot_name": spot_name_of.get(vid) if track == "A귀속" else None,
                    "track": track,
                    "is_cafe_related": bool(d.get("is_cafe_related")),
                    "cafe_identified": d.get("cafe_identified", ""),
                    "info_slots": {k: slots.get(k) for k in ("address", "hours", "menu_price", "etc")},
                    "reaction_summary": d.get("reaction_summary", ""),
                    "reaction_tone": d.get("reaction_tone", "없음"),
                    "local_tips": d.get("local_tips", []) or [],
                    "closed_hint": bool(d.get("closed_hint")),
                    "n_comments": rec.get("n_comments", 0),
                    "sum_likes": sum(c.get("like_count", 0) for c in rec["comments"])}
        except RateLimitError:
            time.sleep(2 ** i)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ⚠ 파싱 실패 [{vid}]: {e}", flush=True)
            return None
    print(f"  ⚠ 재시도 초과 [{vid}]", flush=True)
    return None

if __name__ == "__main__":
    work = [(v, r, t) for v, r, t in targets if t != "skip복수"]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if limit:
        random.seed(42)
        work = random.sample(work, min(limit, len(work)))
        print(f"[관통 모드] random {len(work)}건")
    done = {r["video_id"] for r in load_jsonl(OUT)}
    if done:
        print(f"[재개] 기존 {len(done)}건 스킵")
    fout = open(OUT, "a", encoding="utf-8")
    t0 = time.time()
    n_new = n_fail = n_found = 0
    for vid, rec, track in work:
        if vid in done:
            continue
        out = refine(vid, rec, track)
        if out is None:
            n_fail += 1
            continue
        fout.write(json.dumps(out, ensure_ascii=False) + "\n")
        fout.flush()
        n_new += 1
        if track == "B발굴" and out["cafe_identified"]:
            n_found += 1
        if n_new % 20 == 0:
            el = time.time() - t0
            print(f"  {n_new}/{len(work)} | 발굴 {n_found} | {el:.0f}s | 실패 {n_fail}", flush=True)
    fout.close()
    print(f"[완료] 신규 {n_new} / B트랙 카페 발굴 {n_found} / 실패 {n_fail} / {time.time()-t0:.0f}s")
    print(f"저장: {OUT}")

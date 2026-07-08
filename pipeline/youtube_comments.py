# -*- coding: utf-8 -*-
"""
[파이프라인 계약] 유튜브 쇼츠 댓글 수집 — 반응 데이터 (B트랙 보완).

입력:  data/raw/유튜브 크롤링.json         (video_id → 메타. duration으로 쇼츠 판별)
출력:  data/raw/유튜브 댓글 크롤링.jsonl   (video_id가 조인 키 — 기존 raw 불변, 별도 파일)
       {"video_id", "fetched_at", "n_comments", "comments":[
         {"text", "like_count", "published_at", "author", "reply_count"}]}
키:    .env API_KEY (유튜브)

대상 (7/8 밤 결정): **쇼츠만** — 긴 영상 댓글은 영상 자체에 수렴해 카페 신호가 약함.
  기본 필터: duration ≤ 65초. (설명란 풍부한 A트랙은 애초에 댓글 불필요)
용도 제약 (설계 결정 20): 반응 텍스트는 **임베딩 금지** — 카드 카피·정렬·화제성·폐업 제보용.

사용:
  python pipeline/youtube_comments.py         # 쇼츠 전량 (재실행 시 이어달리기)
  python pipeline/youtube_comments.py 30      # random 30건 관통

쿼터: 영상당 1콜(상위 100개, 관련성순). 쇼츠 ~1,300건 예상 → 일 한도 10,000의 ~13%.
"""
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "raw", "유튜브 크롤링.json")
OUT = os.path.join(ROOT, "data", "raw", "유튜브 댓글 크롤링.jsonl")
MAX_SEC = 65          # 쇼츠 판별 기준 (초)
SLEEP = 0.1

env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
KEY = env.get("API_KEY", "")
if not KEY:
    sys.exit("[중단] .env에 API_KEY(유튜브) 없음")

DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
def dur_seconds(iso):
    m = DUR.fullmatch(iso or "")
    if not m:
        return 10 ** 9
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s

def fetch_comments(vid, retries=3):
    """반환: (comments 리스트, 상태) — 상태: ok | disabled | error"""
    url = "https://www.googleapis.com/youtube/v3/commentThreads?" + urllib.parse.urlencode({
        "part": "snippet", "videoId": vid, "maxResults": 100,
        "order": "relevance", "textFormat": "plainText", "key": KEY})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8"))
            out = []
            for it in d.get("items", []):
                s = it["snippet"]["topLevelComment"]["snippet"]
                out.append({"text": s.get("textDisplay", ""),
                            "like_count": s.get("likeCount", 0),
                            "published_at": s.get("publishedAt", ""),
                            "author": s.get("authorDisplayName", ""),
                            "reply_count": it["snippet"].get("totalReplyCount", 0)})
            return out, "ok"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if "commentsDisabled" in body:
                return [], "disabled"
            if e.code == 403 and "quota" in body.lower():
                sys.exit("[중단] 유튜브 API 일일 쿼터 소진 — 내일 이어서 실행하면 재개됨")
            if attempt == retries - 1:
                return [], f"error:{e.code}"
            time.sleep(2 ** (attempt + 1))
        except Exception as e:
            if attempt == retries - 1:
                return [], f"error:{e!r}"
            time.sleep(1)
    return [], "error"

# ---- 대상: 쇼츠만 ----
raw = json.load(open(SRC, encoding="utf-8"))
vids = list(raw.items()) if isinstance(raw, dict) else [(v.get("video_id"), v) for v in raw]
targets = [(vid, m) for vid, m in vids if vid and dur_seconds(m.get("duration")) <= MAX_SEC]
print(f"전체 {len(vids)}편 중 쇼츠(≤{MAX_SEC}s) {len(targets)}편 대상")

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if limit:
    random.seed(42)
    targets = random.sample(targets, min(limit, len(targets)))
    print(f"[관통 모드] random {len(targets)}건")

done = set()
if os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8", errors="replace"):
        try:
            done.add(json.loads(line)["video_id"])
        except Exception:
            pass
    print(f"[재개] 기존 {len(done)}건 스킵")

fout = open(OUT, "a", encoding="utf-8")
t0 = time.time()
new = with_comments = disabled = errors = 0
for vid, meta in targets:
    if vid in done:
        continue
    comments, status = fetch_comments(vid)
    rec = {"video_id": vid,
           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "status": status, "n_comments": len(comments), "comments": comments}
    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fout.flush()
    new += 1
    if comments:
        with_comments += 1
    elif status == "disabled":
        disabled += 1
    elif status.startswith("error"):
        errors += 1
        print(f"  [오류] {vid}: {status}", flush=True)
    if new % 50 == 0:
        el = time.time() - t0
        print(f"  {new}/{len(targets)} | 댓글 있음 {with_comments} | {el:.0f}s", flush=True)
    time.sleep(SLEEP)
fout.close()
print(f"[완료] 신규 {new} / 댓글 있음 {with_comments} / 비활성 {disabled} / 오류 {errors} / {time.time()-t0:.0f}s")
print(f"저장: {OUT}")

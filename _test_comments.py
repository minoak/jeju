# -*- coding: utf-8 -*-
"""유튜브 댓글 API 실증 — 우리 raw 영상 표본에서 댓글을 실제로 받을 수 있는가 (읽기 전용)."""
import json
import os
import random
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))

env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
KEY = env["API_KEY"]

raw = json.load(open(os.path.join(ROOT, "data", "raw", "유튜브 크롤링.json"), encoding="utf-8"))
# raw 구조: dict(video_id → 메타) 또는 list — 둘 다 대응
if isinstance(raw, dict):
    vids = list(raw.items())
else:
    vids = [(v.get("video_id"), v) for v in raw]
print(f"raw 영상 수: {len(vids)}")

random.seed(7)
sample = random.sample(vids, 8)

ok = disabled = zero = 0
for vid, meta in sample:
    title = (meta.get("title") or "")[:40]
    dur = meta.get("duration", "")
    url = "https://www.googleapis.com/youtube/v3/commentThreads?" + urllib.parse.urlencode({
        "part": "snippet", "videoId": vid, "maxResults": 5,
        "order": "relevance", "key": KEY})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        items = d.get("items", [])
        total_hint = d.get("pageInfo", {}).get("totalResults", 0)
        if items:
            ok += 1
            print(f"\n■ [{dur}] {title} — 댓글 수신 {len(items)}개")
            for it in items[:3]:
                s = it["snippet"]["topLevelComment"]["snippet"]
                txt = s["textDisplay"].replace("\n", " ")[:70]
                print(f"   ({s['likeCount']}👍) {txt}")
        else:
            zero += 1
            print(f"\n■ [{dur}] {title} — 댓글 0개")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:120]
        if "commentsDisabled" in body:
            disabled += 1
            print(f"\n■ [{dur}] {title} — 댓글 비활성화")
        else:
            print(f"\n■ [{dur}] {title} — HTTP {e.code}: {body}")

print(f"\n결과: 수신 성공 {ok} / 0개 {zero} / 비활성 {disabled} (표본 8)")
print("스키마 필드: textDisplay, likeCount, publishedAt, authorDisplayName, totalReplyCount")

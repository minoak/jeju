# -*- coding: utf-8 -*-
"""댓글 크롤 수율 확인 (읽기 전용)."""
import json
import os
import statistics as st

ROOT = os.path.dirname(os.path.abspath(__file__))
recs = []
for line in open(os.path.join(ROOT, "data", "raw", "유튜브 댓글 크롤링.jsonl"), encoding="utf-8", errors="replace"):
    line = line.strip()
    if line:
        try:
            recs.append(json.loads(line))
        except Exception:
            pass

print(f"수집 영상: {len(recs)}편")
withc = [r for r in recs if r.get("n_comments", 0) > 0]
counts = [r["n_comments"] for r in withc]
print(f"댓글 있는 영상: {len(withc)}편 ({len(withc)/len(recs):.0%})")
if counts:
    print(f"댓글 수: 중앙값 {st.median(counts):.0f} / 평균 {st.mean(counts):.0f} / 최대 {max(counts)}")
    print(f"총 댓글: {sum(counts):,}개")

# 정보성 신호 프록시: 주소·시간·가격 패턴 포함 댓글
import re
info_pat = re.compile(r"(제주.*?[시읍면동로길]\s?\d|영업시간|웨이팅|주차|메뉴|\d{1,2}:\d{2}|📍|원\b)")
info_comments = 0
top_liked = []
for r in withc:
    for c in r["comments"]:
        if info_pat.search(c.get("text", "")):
            info_comments += 1
        top_liked.append((c.get("like_count", 0), c.get("text", "")[:60]))
print(f"정보 패턴 포함 댓글: {info_comments:,}개")
top_liked.sort(reverse=True)
print("\n좋아요 상위 댓글 5:")
for lk, t in top_liked[:5]:
    print(f"  ({lk}👍) {t}")

# 단일 카페 영상 비율 (귀속 가능성)
spots = json.load(open(os.path.join(ROOT, "data", "processed", "유튜브 정제.json"), encoding="utf-8"))
from collections import Counter
per_video = Counter(s["video_id"] for s in spots)
vids_with_c = {r["video_id"] for r in withc}
single = sum(1 for v in vids_with_c if per_video.get(v, 0) == 1)
multi = sum(1 for v in vids_with_c if per_video.get(v, 0) > 1)
print(f"\n댓글 있는 영상 중 단일 카페 영상: {single} / 복수 {multi} / 카페 미추출 {len(vids_with_c)-single-multi}")

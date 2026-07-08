# -*- coding: utf-8 -*-
import json, os, collections
base = r"C:\Users\akals\Documents\GitHub\jeju\data"
conv = json.load(open(os.path.join(base, "processed/카페-변환.json"), encoding="utf-8"))

# spots-per-video distribution: how often does one video map to multiple cafes?
by_vid = collections.Counter(c["video_id"] for c in conv)
dist = collections.Counter(by_vid.values())
print("총 추출 카드:", len(conv), "| 고유 video_id:", len(by_vid))
print("영상당 카페 수 분포 (카페수: 영상개수):")
for k in sorted(dist):
    print(f"  {k}개 카페 <- {dist[k]}개 영상")

n1 = sum(1 for v in by_vid.values() if v == 1)
nmulti = sum(1 for v in by_vid.values() if v > 1)
cards_clean = n1
cards_ambig = sum(v for v in by_vid.values() if v > 1)
print()
print(f"1:1 영상(귀속 깔끔): {n1}개 -> 카드 {cards_clean}장")
print(f"1:다 영상(귀속 모호): {nmulti}개 -> 카드 {cards_ambig}장")

# sample one multi-spot video
multi_vid = [vid for vid, n in by_vid.items() if n >= 4]
if multi_vid:
    vid = multi_vid[0]
    print("\n[예시] 한 영상이 여러 카페로 쪼개진 경우:", vid)
    for c in conv:
        if c["video_id"] == vid:
            print("   -", c["spot_name"], "|", c["region"])

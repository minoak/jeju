# -*- coding: utf-8 -*-
"""
MISS/HOLD 카페 재매칭 파일럿 — 원이름 한 쿼리로 실패한 카페를
aliases + 지역 힌트를 붙여 카카오에 다시 물어본다.

- 입력:  카카오플레이스.jsonl (status=MISS/HOLD 대상), cards.json(aliases·region), 카페부가v2.json(네이버 좌표)
- 출력:  카카오_재매칭_리포트.jsonl (리포트만 — 원본 카카오플레이스.jsonl 불변, 반영은 사람 확인 후)
- 목적:  ① place_id 커버리지 향상(진짜 카페 살리기)  ② 계속 MISS = 노이즈/폐업 후보 확정
- 키:    kakao_place.py의 kakao()/pick() 재사용 (.env KAKAO_KEY)
"""
import os, sys, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import kakao_place as kp   # kakao(), pick(), name_ok() 재사용 (import 시 KEY 로드)

PLACES = os.path.join(ROOT, "data", "processed", "카카오플레이스.jsonl")
CARDS  = os.path.join(ROOT, "data", "processed", "cards.json")
EXTRA  = os.path.join(ROOT, "data", "processed", "카페부가v2.json")
REPORT = os.path.join(ROOT, "data", "processed", "카카오_재매칭_리포트.jsonl")

rows = [json.loads(l) for l in open(PLACES, encoding="utf-8")]
targets = [r for r in rows if r.get("status") in ("MISS", "HOLD")]

cards = json.load(open(CARDS, encoding="utf-8"))
by_name = {}
for c in cards:
    by_name.setdefault(c["name"], c)
    for a in (c.get("aliases") or []):
        by_name.setdefault(a, c)
extra = json.load(open(EXTRA, encoding="utf-8"))

RANK = {"MATCH": 4, "MATCH_NOCOORD": 3, "HOLD": 2, "MISS": 0}
revived, still = [], []
fout = open(REPORT, "w", encoding="utf-8")
print(f"재매칭 대상 {len(targets)}곳 (MISS/HOLD)", flush=True)

for i, r in enumerate(targets, 1):
    name = r["spot_name"]
    card = by_name.get(name, {})
    aliases = [a for a in (card.get("aliases") or []) if a != name]
    region = card.get("region_fine") or card.get("region_bucket") or ""
    e = extra.get(name) or {}
    nlat, nlng = e.get("lat"), e.get("lng")

    # 여러 각도로 물어본다: 원이름 / 각 alias / 이름+지역
    queries = [name + " 제주"] + [a + " 제주" for a in aliases]
    if region:
        queries.append(f"{name} {region}")

    best_status, best, best_q = "MISS", None, None
    for q in queries:
        docs = kp.kakao(q)
        time.sleep(0.08)
        if not docs:
            continue
        st, b = kp.pick(name, nlat, nlng, docs)
        if RANK[st] > RANK[best_status]:
            best_status, best, best_q = st, b, q
        if best_status == "MATCH":
            break

    rec = {"spot_name": name, "prev": r.get("status"), "new": best_status, "query": best_q}
    if best and best_status in ("MATCH", "MATCH_NOCOORD"):
        d, dd = best
        rec.update({"place_id": d["id"], "kakao_name": d["place_name"],
                    "address": d.get("road_address_name") or d.get("address_name") or "",
                    "dist_m": round(dd) if dd is not None else None})
        revived.append(rec)
    else:
        still.append(rec)
    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if i % 30 == 0:
        print(f"  {i}/{len(targets)} … 살아남 {len(revived)}", flush=True)

fout.close()
print(f"\n== 결과 ==")
print(f"살아남(place_id 확보): {len(revived)} / {len(targets)}")
print(f"여전히 실패(노이즈·폐업 후보): {len(still)}")
print(f"\n[살아난 것 최대 20]")
for r in revived[:20]:
    print(f"  {r['spot_name']}  →  {r['kakao_name']}  ({r['new']}, {r.get('dist_m')}m)")
print(f"\n[여전히 실패 최대 30]")
for r in still[:30]:
    print(f"  {r['spot_name']}")
print(f"\n리포트 → {REPORT}")

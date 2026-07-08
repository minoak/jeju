# -*- coding: utf-8 -*-
"""
네이버 검색 API 배치 크롤러 — 고유 카페 전량 대상.

카페마다:
  1) 블로그 검색 (display=100, sort=sim)  → 텍스트 보강 원료
  2) 지역 검색   (display=5)              → 주소/좌표 보강 + 실존 신호

원칙 (HANDOFF 계승):
  - raw 불변: 타임스탬프 파일로 동결, 원본 응답 무손실 저장
  - 체크포인트: 25건마다 중간 저장, 중단돼도 재실행 시 이어서 (--resume 기본)
  - 관통 먼저: LIMIT 지정 시 random.sample (머리 표본 편향 금지)

사용:
  python _crawl_naver.py            # 전량
  python _crawl_naver.py 30         # 랜덤 30건 관통
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

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "data", "processed", "카페-변환.json")
OUT = os.path.join(ROOT, "data", "raw", "naver_20260708.jsonl")
# 작업 파일: NAVER_WORK 지정 시 그 경로(예: /tmp — 마운트 쓰기 회피), 아니면 OUT 직접
WORK = os.environ.get("NAVER_WORK", OUT)
SLEEP = 0.15          # ~6 QPS (여유)

# ---- .env 로드: repo 루트 우선, 폴백 경로 허용 (샌드박스 캐시 이슈 대응) ----
def load_env():
    candidates = [
        os.path.join(ROOT, ".env"),
        os.environ.get("NAVER_ENV_FILE", ""),
        "/sessions/intelligent-upbeat-albattani/mnt/outputs/_naver_keys.env",
    ]
    env = {}
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env

ENV = load_env()
CID, CSECRET = ENV.get("NAVER_CLIENT_ID", ""), ENV.get("NAVER_CLIENT_SECRET", "")
if not CID or not CSECRET:
    sys.exit("[중단] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음")

def naver_get(endpoint, query, display, sort=None, retries=3):
    params = {"query": query, "display": display}
    if sort:
        params["sort"] = sort
    url = f"https://openapi.naver.com/v1/search/{endpoint}.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": CID, "X-Naver-Client-Secret": CSECRET})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limit → 지수 백오프
                wait = 2 ** (attempt + 1)
                print(f"    429 rate limit — {wait}s 대기", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(1)
    raise RuntimeError("retries exhausted")

# ---- 대상: 고유 카페명 (첫 등장 레코드의 메타 유지) ----
spots = json.load(open(SRC, encoding="utf-8"))
uniq = {}
for s in spots:
    uniq.setdefault(s["spot_name"], s)
targets = list(uniq.items())

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if limit:
    random.seed(42)
    targets = random.sample(targets, min(limit, len(targets)))
    print(f"[관통 모드] random {len(targets)}건")

# ---- 재개: 기존 결과 로드 ----
# ---- 재개: JSONL 줄 단위 로드 (깨진 줄은 개별 스킵) ----
def load_jsonl(path):
    recs = {}
    if not os.path.exists(path):
        return recs
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if "�" not in line:
                recs[r["spot_name"]] = r
        except Exception:
            pass  # 마지막 잘린 줄 등 — 그 카페만 다시 긁으면 됨
    return recs

done = load_jsonl(WORK)
if WORK != OUT:
    for k, v in load_jsonl(OUT).items():
        done.setdefault(k, v)
if done:
    print(f"[재개] 기존 {len(done)}건 스킵")

fout = open(WORK, "a", encoding="utf-8")
# WORK가 비어있는데 done이 있으면(OUT에서 복원) WORK에 시딩
if os.path.getsize(WORK) == 0 and done:
    for r in done.values():
        fout.write(json.dumps(r, ensure_ascii=False) + "\n")
    fout.flush()

def emit(rec):
    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fout.flush()
    os.fsync(fout.fileno())

t0 = time.time()
new = fails = 0
for i, (name, meta) in enumerate(targets):
    if name in done:
        continue
    q = f"제주 {name}"
    rec = {"spot_name": name, "region": meta.get("region"),
           "info_richness": meta.get("info_richness"), "query": q}
    try:
        rec["blog"] = naver_get("blog", q, display=100, sort="sim")
        time.sleep(SLEEP)
        rec["local"] = naver_get("local", q, display=5)
        time.sleep(SLEEP)
    except Exception as e:
        rec["error"] = repr(e)
        fails += 1
        print(f"  [실패] {name}: {e!r}", flush=True)  # 삼키지 않기 — 경고 출력 필수
    done[name] = rec
    emit(rec)
    new += 1
    if new % 10 == 0:
        el = time.time() - t0
        print(f"  {new}건 (전체 {len(done)}/{len(uniq)}) | {el:.0f}s | 실패 {fails}", flush=True)

fout.close()
print(f"[완료] 신규 {new}건 / 누적 {len(done)}건 / 실패 {fails}건 / {time.time()-t0:.0f}s")
print(f"저장: {WORK}")

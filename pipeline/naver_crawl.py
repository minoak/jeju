# -*- coding: utf-8 -*-
"""
[파이프라인 계약] 네이버 크롤링 — 카페별 블로그 검색 + 지역검색 수집.

입력:  data/processed/유튜브 정제.json   (Pass 1 산출 — 카페명 목록)
출력:  data/raw/네이버 크롤링.jsonl      (crawl — raw 불변, append)
       data/raw/네이버 재검색 크롤링.jsonl (rescue — 이름 정리 후 재크롤)
키:    .env NAVER_CLIENT_ID / NAVER_CLIENT_SECRET

사용:
  python pipeline/naver_crawl.py crawl [N]   # 전량 or 랜덤 N건 관통
  python pipeline/naver_crawl.py rescue      # review_master.csv의 제외후보/실존의심 재검색

원칙: raw 불변(타임스탬프/append) · JSONL 줄 단위(중단 안전) · 재실행 시 이어달리기
"""
import csv
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "processed", "유튜브 정제.json")
OUT_CRAWL = os.path.join(ROOT, "data", "raw", "네이버 크롤링.jsonl")
OUT_RESCUE = os.path.join(ROOT, "data", "raw", "네이버 재검색 크롤링.jsonl")
REVIEW = os.path.join(ROOT, "data", "processed", "review_master.csv")
SLEEP = 0.15

def load_env():
    env = {}
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env

ENV = load_env()
CID, CSECRET = ENV.get("NAVER_CLIENT_ID", ""), ENV.get("NAVER_CLIENT_SECRET", "")
if not CID or not CSECRET:
    sys.exit("[중단] .env에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음")

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
            if e.code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1)
    raise RuntimeError("retries exhausted")

TAG = re.compile(r"<[^>]+>")
def clean(s):
    return TAG.sub("", s or "").strip()

def norm(s):
    s = clean(s).split("(")[0]
    return re.sub(r"[^\w가-힣]", "", s.lower())

def clean_name(n):
    n = re.sub(r"[\(\[（].*?[\)\]）]", " ", n)
    n = re.sub(r"\s+in\s+\S+", " ", n)
    return re.sub(r"\s+", " ", n).strip()

def load_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                done.add(json.loads(line)["spot_name"])
            except Exception:
                pass
    return done

def cmd_crawl(limit=0):
    spots = json.load(open(SRC, encoding="utf-8"))
    uniq = {}
    for s in spots:
        uniq.setdefault(s["spot_name"], s)
    targets = list(uniq.items())
    if limit:
        random.seed(42)
        targets = random.sample(targets, min(limit, len(targets)))
        print(f"[관통 모드] random {len(targets)}건")
    done = load_done(OUT_CRAWL)
    if done:
        print(f"[재개] 기존 {len(done)}건 스킵")
    fout = open(OUT_CRAWL, "a", encoding="utf-8")
    t0, new, fails = time.time(), 0, 0
    for name, meta in targets:
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
            print(f"  [실패] {name}: {e!r}", flush=True)
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fout.flush()
        new += 1
        if new % 20 == 0:
            print(f"  {new}건 | {time.time()-t0:.0f}s | 실패 {fails}", flush=True)
    fout.close()
    print(f"[완료] 신규 {new} / 실패 {fails} → {OUT_CRAWL}")

def cmd_rescue():
    targets = []
    for r in csv.DictReader(open(REVIEW, encoding="utf-8-sig")):
        if r.get("판정") == "제외후보" or "실존의심" in r.get("플래그", ""):
            targets.append(r["카페명"])
    targets = list(dict.fromkeys(targets))
    print(f"재검색 대상: {len(targets)}곳")
    done = load_done(OUT_RESCUE)
    fout = open(OUT_RESCUE, "a", encoding="utf-8")
    rescued = 0
    for i, name in enumerate(targets):
        if name in done:
            continue
        cleaned = clean_name(name)
        rec = {"spot_name": name, "cleaned_name": cleaned}
        if not cleaned:
            rec["error"] = "빈 이름 (정리 후)"
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            continue
        key = norm(cleaned)
        def n_valid(b):
            return sum(1 for it in b.get("items", [])
                       if key and key in norm(it.get("title", "") + it.get("description", "")))
        try:
            q = f"제주 {cleaned}"
            blog = naver_get("blog", q, display=100, sort="sim")
            time.sleep(SLEEP)
            if n_valid(blog) == 0:
                q = cleaned
                blog = naver_get("blog", q, display=100, sort="sim")
                time.sleep(SLEEP)
            rec.update(query=q, blog=blog,
                       local=naver_get("local", f"제주 {cleaned}", display=5))
            time.sleep(SLEEP)
            if n_valid(blog) > 0 or rec["local"].get("items"):
                rescued += 1
        except Exception as e:
            rec["error"] = repr(e)
            print(f"  [실패] {name}: {e!r}", flush=True)
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fout.flush()
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(targets)} | 신호 살아남 {rescued}", flush=True)
    fout.close()
    print(f"[완료] 신호 확인 {rescued}곳 → {OUT_RESCUE}")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "crawl"
    if mode == "crawl":
        cmd_crawl(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif mode == "rescue":
        cmd_rescue()
    else:
        sys.exit("사용법: naver_crawl.py [crawl [N] | rescue]")

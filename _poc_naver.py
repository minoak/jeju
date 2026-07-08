# -*- coding: utf-8 -*-
"""
네이버 검색 API PoC — 제주 카페 텍스트를 실제로 가져올 수 있는지 실증.

준비:
  1. https://developers.naver.com > Application > 애플리케이션 등록
     - 사용 API: "검색" 체크 (심사 없음, 등록 즉시 사용 가능)
     - 환경: WEB 설정 아무 URL이나 (http://localhost)
  2. .env 에 두 줄 추가:
     NAVER_CLIENT_ID=발급받은_클라이언트_ID
     NAVER_CLIENT_SECRET=발급받은_시크릿

실행:  python _poc_naver.py
검증 포인트:
  - 블로그 검색: 카페명으로 후기 텍스트가 실제로 나오는가 (텍스트 보강 원료)
  - 지역 검색: 카페명으로 주소/좌표가 나오는가 (display 최대 5 제한 실측)
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))

# ---- .env 로드 (키 이름 앞뒤 공백 허용: "API_KEY =" 형태 대응) ----
def load_env(path=os.path.join(ROOT, ".env")):
    env = {}
    if not os.path.exists(path):
        return env
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()
CID = ENV.get("NAVER_CLIENT_ID", "")
CSECRET = ENV.get("NAVER_CLIENT_SECRET", "")

if not CID or not CSECRET:
    print("[중단] .env 에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 없습니다.")
    print("       파일 상단 주석의 '준비' 절차를 먼저 진행하세요.")
    sys.exit(1)

def naver_get(endpoint, query, display=5, sort=None):
    """endpoint: 'blog' | 'local'"""
    params = {"query": query, "display": display}
    if sort:
        params["sort"] = sort
    url = f"https://openapi.naver.com/v1/search/{endpoint}.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": CID,
        "X-Naver-Client-Secret": CSECRET,
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))

TAG = re.compile(r"<[^>]+>")
def clean(s):
    return TAG.sub("", s).replace("&quot;", '"').replace("&amp;", "&")

# ---- 테스트 표본: 실데이터에서 뽑은 high 1 + low 3 (low 보강이 목적이므로 low 위주) ----
SAMPLES = [
    ("high", "바다바라", "중문"),
    ("low", "이야이야요", "서귀포시내"),
    ("low", "제주당", "제주시내"),
    ("low", "Kiekee Coffee Stand", "제주시내"),
]

results = []
for richness, name, region in SAMPLES:
    q = f"제주 {name}"
    print("=" * 60)
    print(f"[{richness}] {name} ({region})  |  쿼리: '{q}'")

    # 1) 블로그 검색 — 텍스트 보강 원료
    try:
        blog = naver_get("blog", q, display=5, sort="sim")
        total = blog.get("total", 0)
        items = blog.get("items", [])
        print(f"  블로그: total={total:,}건")
        for it in items[:3]:
            print(f"    - [{it['postdate']}] {clean(it['title'])}")
            print(f"      {clean(it['description'])[:80]}")
    except Exception as e:
        print(f"  블로그: 실패 — {e!r}")
        blog = {"error": repr(e)}

    # 2) 지역 검색 — 주소/좌표 (display 최대 5 실측)
    try:
        local = naver_get("local", q, display=5)
        items = local.get("items", [])
        print(f"  지역검색: {len(items)}건 (요청 5)")
        for it in items[:2]:
            # mapx/mapy 는 경위도 * 1e7 (KATECH 아님, WGS84 정수 표기)
            print(f"    - {clean(it['title'])} | {it.get('roadAddress') or it.get('address')}")
    except Exception as e:
        print(f"  지역검색: 실패 — {e!r}")
        local = {"error": repr(e)}

    results.append({"richness": richness, "name": name, "region": region,
                    "blog": blog, "local": local})
    time.sleep(0.2)  # 초당 호출 제한 방어

out = os.path.join(ROOT, "_poc_naver_result.json")
json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("=" * 60)
print(f"원본 응답 저장: {out}")
print("판정 기준: low 카페도 블로그 total이 수십 건 이상 나오면 → 텍스트 보강 실증 성공")

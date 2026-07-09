# -*- coding: utf-8 -*-
"""
로컬 관통용 API 서버 — web(8503) ↔ 카드 정본 검색 다리.

실행:
  pip install fastapi uvicorn   (없으면)
  cd C:\\Users\\akals\\Documents\\GitHub\\jeju
  python -m uvicorn app.server:app --port 8000

엔드포인트:
  GET /search?q=조용한+카페&k=8   → { query, region, browse, total, cards: [...] }
  GET /evidence?name=프릳츠&q=조용  → 원문 근거 (블로그 인용 + 리뷰 + 쇼츠 반응)
  GET /photos?name=...             → 구글 사진 임시 URL (키는 서버에만)
  GET /health

설계 원칙 (2026-07-09 개편 — 런타임 LLM 철거):
  - 카드 정본(cards.json, merge.py 산출)이 유일한 카페 사전 — 중복은 병합이 이미 죽였다
  - 런타임 생성 LLM 없음. "왜 추천"은 코드가 결정적으로 조립(matched: 지역·태그·블로거)
    LLM의 자리는 오프라인 파이프라인(정제·태그·요약)이지 매 검색의 톨게이트가 아니다
  - 임베딩(text-embedding-3-large)은 유지 — 태그 사전 밖 자연어 조건의 폴백 (결정적·빠름)
  - 근거는 원문 인용만: /evidence quotes = 매칭 스니펫 코드 발췌 (지어내기 원천 차단)
  - 폐업은 지우지 않고 안내: 이름 조회에는 closed 카드로 응답, 검색·브라우즈에선 제외
  - 키는 서버에만 (.env) — 브라우저 노출 없음
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.error

import chromadb
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

try:
    from app import tagdict  # 태그 사전 (synonym 번역 — 어휘 매칭 게이트용)
except ImportError:
    import tagdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 키 로딩: 로컬은 .env 파일, 배포(Render 등)는 프로세스 환경변수 ----
# 우선순위: 환경변수 > .env 파일. Render엔 .env 파일이 없고 키를 환경변수로 주입한다.
env = {}
_envfile = os.path.join(ROOT, ".env")
if os.path.exists(_envfile):
    for line in open(_envfile, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
for _k in ("OPENAI_KEY", "API_KEY", "KAKAO_KEY", "KAKAO_JS_KEY"):
    if os.environ.get(_k):  # 환경변수가 있으면 우선 (배포)
        env[_k] = os.environ[_k]
if not env.get("OPENAI_KEY"):
    raise RuntimeError("OPENAI_KEY 없음 — 로컬은 .env, 배포는 환경변수(Render)로 주입하세요")
client = OpenAI(api_key=env["OPENAI_KEY"])  # 임베딩 전용 (생성 호출 없음)
GKEY = env.get("API_KEY")  # 유튜브=구글 클라우드 키. Places 사진도 이 키로

cdb = chromadb.PersistentClient(path=os.environ.get("CHROMA_DIR", os.path.join(ROOT, "chroma_smoke")))
col = cdb.get_collection(os.environ.get("CHROMA_COLLECTION", "cards"))  # 회귀 시 "smoke"로 복구

TAG = re.compile(r"<[^>]+>")
def _clean(s):
    return TAG.sub("", s or "").strip()
def _norm(s):
    s = _clean(s).split("(")[0]
    return re.sub(r"[^\w가-힣]", "", s.lower())

# ---- 카드 정본 로드 (merge.py 산출 — 병합·지역교정·폐업 강등 완료) ----
CARDS = {}      # 정본명 → 카드
ALIAS2CANON = {}  # 모든 변형 → 정본명
for c in json.load(open(os.path.join(ROOT, "data", "processed", "cards.json"), encoding="utf-8")):
    CARDS[c["name"]] = c
    ALIAS2CANON[c["name"]] = c["name"]
    for a in c.get("aliases", []):
        ALIAS2CANON[a] = c["name"]
SPOT_PID = {n: CARDS[cn].get("place_id") for n, cn in ALIAS2CANON.items() if CARDS[cn].get("place_id")}
print(f"[server] 카드 정본 {len(CARDS)}장 (이름 변형 {len(ALIAS2CANON)}개, place_id {len(set(SPOT_PID.values()))}곳)")

# ---- 서빙 명단: chroma(cards 컬렉션 = 판정 유지·비폐업만 적재) ----
SERVING = {}  # 정본명 → sources
for _m in col.get(include=["metadatas"])["metadatas"]:
    n = _m.get("spot_name")
    if n:
        e = SERVING.setdefault(n, [])
        if _m.get("source") and _m["source"] not in e:
            e.append(_m["source"])
print(f"[server] 서빙 코퍼스 {len(SERVING)}카페 / {col.count()}문서")

# ---- 이름 매치 레이어 (결정적 조회) ----
# 고유명사 조회는 임베딩의 직업이 아님 — "해지개" top10 전멸 실측 (2026-07-08).
# 사전 = 정본명 + 모든 변형(aliases). 어떤 변형으로 검색해도 정본 카드 1장.
# 폐업 카페도 사전에 남긴다 — 지우면 사용자가 모르고 찾아간다 (신뢰가 컨셉).
_NAME_STOP = {"카페", "커피", "제주", "제주도", "베이커리", "디저트", "브런치",
              "애월", "곽지", "한림", "협재", "함덕", "월정리", "세화", "김녕", "성산",
              "표선", "남원", "위미", "중문", "사계", "대정", "안덕", "우도", "구좌", "조천",
              "제주시내", "서귀포시내", "서귀포", "제주시", "월정"}

def _build_name_index():
    idx = {}  # 정규화 변형 → 정본명
    for alias, canon in ALIAS2CANON.items():
        if canon not in SERVING and not CARDS[canon]["closed"]:
            continue  # 서빙 밖 + 비폐업(보류/제외 판정)은 조회 대상 아님
        key = _norm(alias)
        if len(key) < 2 or key in _NAME_STOP:
            continue
        residual = key
        for sw in _NAME_STOP:
            residual = residual.replace(sw, "")
        if not residual:
            continue  # 스톱워드만으로 조립된 이름 ("애월카페" 아이러니 방지, 실측 2026-07-08)
        idx[key] = canon
    return idx

NAME_IDX = _build_name_index()
print(f"[server] 이름 사전 {len(NAME_IDX)}건 (폐업 안내 포함)")

def name_lookup(q, limit=2):
    """질의에서 카페명 탐지 → 정본명 목록. 긴 이름 우선.
    len>=3은 부분 포함, len==2는 완전 일치만 (오탐 방지)."""
    qn = _norm(q)
    hits = []
    for key, canon in NAME_IDX.items():
        if (len(key) >= 3 and key in qn) or key == qn:
            hits.append((len(key), canon))
    hits.sort(key=lambda x: -x[0])
    seen, out = set(), []
    for _, canon in hits:
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
        if len(out) >= limit:
            break
    return out

# ---- 질의 지역 해석 (카드 쪽 지역은 merge.py가 주소에서 확정 — 서버는 읽기만) ----
REGIONS = ["애월", "곽지", "한림", "협재", "한경", "함덕", "월정리", "세화", "김녕", "성산",
           "표선", "남원", "위미", "중문", "사계", "대정", "안덕", "우도", "구좌", "조천",
           "제주시내", "서귀포시내"]
ALIAS = {"서귀포": "서귀포시내", "제주시": "제주시내", "월정": "월정리"}
_LABEL2BF = {"협재": ("한림", "협재"), "곽지": ("애월", "곽지"), "월정리": ("구좌", "월정리"),
             "세화": ("구좌", "세화"), "김녕": ("구좌", "김녕"), "종달": ("구좌", "종달"),
             "송당": ("구좌", "송당"), "함덕": ("조천", "함덕"), "위미": ("남원", "위미"),
             "사계": ("안덕", "사계"), "중문": ("서귀포시내", "중문")}

def _label_to_bf(label):
    if not label:
        return None, None
    return _LABEL2BF.get(label, (label, None))

def detect_region(q):
    for r in REGIONS:
        if r in q:
            return r
    for a, std in ALIAS.items():
        if a in q:
            return std
    return None

# ---- 브라우즈 판별: 지역·일반어를 걷어내고 알맹이가 없으면 조건 없는 탐색 ----
_BROWSE_STRIP = sorted(_NAME_STOP | {"추천", "여행", "가볼만한", "가볼만", "곳", "리스트",
                                     "목록", "투어", "베스트", "유명한", "유명"}, key=len, reverse=True)

def is_browse(q):
    r = _norm(q)
    for t in _BROWSE_STRIP:
        r = r.replace(t, "")
    return not r

def _terms(q):
    """질의에서 조건 토큰 추출 — 지역·일반어 제외, 활용형 대비 축소형 포함."""
    out = []
    for tok in re.findall(r"[가-힣a-zA-Z]{2,}", q):
        if _norm(tok) in _NAME_STOP or tok in ("추천", "알려줘", "좋은", "있는", "가볼만한"):
            continue
        stems = {tok}
        if len(tok) >= 3:
            stems.add(tok[:-1])
        if len(tok) >= 4:
            stems.add(tok[:-2])
        out.append(sorted(stems, key=len))
    return out

# ---- 하드 배제: 쿼리 맥락이 특정 태그를 '금지'하는 경우 (완화 불가 — 하드조건 불가침) ----
# tagdict.exclude_map()이 배제 규칙의 단일 창구. 현재 노키즈존만: 아이 동반 쿼리에서 배제.
# 골드셋 G030("노키즈존 피하고 가족") Forbidden@5 100% 사건의 처방 — 배제는 지역완화보다
# 우선하고 어떤 완화에도 안 풀린다 (아이 동반자에게 노키즈존을 대안이라 줄 수 없다).
# "노키즈존 자체를 찾는" 쿼리(피하다 신호 없음)는 배제가 아니다 — 사용자가 원한 것.
_KID_SIGNALS = ("아이", "아기", "애기", "유아", "애들", "아들", "딸", "가족", "아이랑", "아기랑", "애기랑")
_AVOID_SIGNALS = ("피하", "말고", "빼고", "제외", "아닌", "싫", "없는", "안되는", "안 되는", "말 고")

def detect_exclusions(q):
    """쿼리에서 하드 배제할 태그 집합. 완화 사다리에서도 절대 안 풀린다."""
    excl = set()
    emap = tagdict.exclude_map()
    if "노키즈존" in emap:
        qn = _norm(q)
        kid = any(s in q for s in _KID_SIGNALS) or ("키즈" in q and "노키즈" not in qn)
        nokids_avoid = ("노키즈" in qn) and any(w in q for w in _AVOID_SIGNALS)
        if kid or nokids_avoid:
            excl.add("노키즈존")
    return excl

def _apply_exclusions(pool_names, excl_tags):
    """이름 집합에서 배제 태그를 가진 카페 제거. (제거된 수, 남은 집합) 반환."""
    if not excl_tags:
        return 0, pool_names
    kept = [n for n in pool_names
            if not (set(CARDS.get(n, {}).get("tags") or []) & excl_tags)]
    return len(pool_names) - len(kept), kept

# ---- 태그 번역기 (exact→임베딩→unresolved). server client를 embed_fn으로 주입 ----
# "선셋"은 synonym 정확매칭, "석양빛"은 태그사전 임베딩 최근접(0.55+), "물멍"은 unresolved.
# 임베딩 공간엔 카페가 아니라 태그 표현 수십 개만 — 임베딩은 찾지 않고 번역한다.
def _embed_one(text):
    return client.embeddings.create(model="text-embedding-3-large", input=[text]).data[0].embedding

try:
    from app import tagtrans as _tagtrans_mod
except ImportError:
    import tagtrans as _tagtrans_mod
_TAGTRANS = _tagtrans_mod.TagTranslator(embed_fn=_embed_one)
print(f"[server] 태그 번역기: 활성 {len(tagdict.active_tags())}종, "
      f"임베딩번역={'ON' if _TAGTRANS.embedding_ready else 'OFF(exact만 — tag_embed.py 미실행)'}")


def resolve_terms(q):
    """조건어 → 태그 번역 (임베딩은 사전 밖 term만, 카페 루프 밖 1회씩·tagtrans 내부 캐시).
    반환: {groups, want(정규화 태그 집합), log(번역 내역=깔때기), unresolved(미해석 term)}."""
    groups = _terms(q)
    want, log, unresolved = set(), [], []
    for group in groups:
        term = max(group, key=len)  # 그룹의 원형(가장 긴 형태)로 번역
        r = _TAGTRANS.translate(term)
        log.append(r)
        if r.get("tag"):
            want.add(_norm(r["tag"]))
        else:
            unresolved.append(term)
    return {"groups": groups, "want": want, "log": log, "unresolved": unresolved}


# ---- 어휘 매칭 게이트: 조건어(→번역 태그)가 카드 근거에 실재하는가 ----
# 임베딩은 짧은 "X 카페" 쿼리에서 유사도가 공통어 "카페"에 지배돼 무관 쿼리(승마·노래방)도
# top을 채운다 (실측 2026-07-10: 노래방 0.244 > 오션뷰 0.209). 그래서 관련성의 기준을
# 유사도가 아니라 "조건어가 근거에 실제로 있는가"로 둔다 — 근거가 없으면 침묵.
# 3경로: (a) 번역된 요구 태그가 카드 태그에 실재 (exact synonym + 임베딩 번역 통합),
#        (b) 조건어가 카드 태그에 부분매칭 (오션뷰·노을 등 원명이 곧 태그),
#        (c) 조건어가 요약 본문에 등장 (베이글·밀크티 등 태그 사전 밖 유효조건).
# = 결정 6 "승마클럽 사건(표면 토큰 함정)" 임베딩층 방어. 임베딩 유사도는 순위로만.
def _grounded(canon, resolved):
    c = CARDS.get(canon)
    if not c:
        return False
    tags_norm = set(_norm(t) for t in (c.get("tags") or []))
    if resolved["want"] & tags_norm:                            # (a) 번역 태그 실재
        return True
    summ = c.get("summary") or ""
    for group in resolved["groups"]:
        for s in group:                                         # (b) 태그 부분매칭
            sn = _norm(s)
            if len(sn) >= 2 and any(sn in tn for tn in tags_norm):
                return True
        for s in group:                                         # (c) 요약 등장
            if len(s) >= 2 and s in summ:
                return True
    return False

# ---- 결정적 근거: "왜 이 카페인가"를 코드가 조립 (LLM reason의 후임) ----
# 지어낼 수 없는 이유만: 질의와 겹친 태그 + 지역 일치 + 다수결(고유 블로거 수).
def match_info(q, card, want_b, want_f):
    stems = _terms(q)
    tags_hit = []
    for t in card.get("tags", []):
        tn = _norm(t)
        for st in stems:
            if any(s in tn or (len(_norm(s)) >= 2 and _norm(s) in tn) for s in st):
                tags_hit.append(t)
                break
    info = {}
    if want_b and card.get("region_bucket") == want_b:
        info["region"] = card.get("region_fine") if (want_f and card.get("region_fine") == want_f) \
            else card.get("region_bucket")
    if tags_hit:
        info["tags"] = tags_hit[:4]
    if card.get("bloggers"):
        info["bloggers"] = card["bloggers"]
    return info

def card_out(canon, score, sources, name_match=False, q="", want_b=None, want_f=None):
    """카드 정본 → /search 응답 카드 (하위호환: summary_blog 자리에 정본 summary)."""
    c = CARDS.get(canon) or {"name": canon, "closed": False}
    g = c.get
    out = {"spot_name": c["name"], "place_id": g("place_id"),
           "score": round(score, 3), "sources": sources,
           "region": g("region_fine") or g("region_bucket"),
           "region_bucket": g("region_bucket"), "region_fine": g("region_fine"),
           "summary_blog": g("summary", ""), "summary_youtube": "",
           "tags": g("tags", []), "video_ids": g("video_ids", [])[:3],
           "blog_links": g("blog_links", []), "address": g("address", ""),
           "category": g("category", ""),
           "mention_count": g("mention_count", 0), "bloggers": g("bloggers", 0),
           "caution": g("caution", []), "hours_hint": g("hours_hint", ""),
           "reaction_tone": g("reaction_tone", ""), "reaction_hint": g("reaction_hint", ""),
           "rating_avg": g("rating_avg"), "rating_count": g("rating_count"),
           "review_tone": g("review_tone", ""),
           "closed": g("closed", False),
           "lat": g("lat"), "lng": g("lng")}
    if name_match:
        out["name_match"] = True
    m = match_info(q, c, want_b, want_f)
    if m:
        out["matched"] = m
    return out


def _places_photo_uris(name, lat, lng, place_id=None, limit=8):
    """Places(New)로 카페 사진의 임시 URL 목록. photo name은 저장 금지·만료 대상이라 매 호출 신선하게."""
    if place_id:
        req = urllib.request.Request(
            "https://places.googleapis.com/v1/places/" + place_id,
            headers={"X-Goog-Api-Key": GKEY, "X-Goog-FieldMask": "id,photos"})
        d = json.load(urllib.request.urlopen(req, timeout=12))
        pid, photos = d.get("id"), d.get("photos", [])
    else:
        payload = {"textQuery": (name or "") + " 제주 카페", "languageCode": "ko", "maxResultCount": 1}
        if lat and lng:
            payload["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 600.0}}
        req = urllib.request.Request(
            "https://places.googleapis.com/v1/places:searchText",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": GKEY,
                     "X-Goog-FieldMask": "places.id,places.photos"})
        d = json.load(urllib.request.urlopen(req, timeout=12))
        places = d.get("places", [])
        if not places:
            return None, []
        pid, photos = places[0].get("id"), places[0].get("photos", [])
    uris = []
    for ph in photos[:limit]:
        murl = ("https://places.googleapis.com/v1/" + ph["name"] +
                "/media?maxWidthPx=800&skipHttpRedirect=true&key=" + GKEY)
        try:
            md = json.load(urllib.request.urlopen(murl, timeout=12))
            if md.get("photoUri"):
                uris.append(md["photoUri"])
        except Exception:
            pass
    return pid, uris


# ---- /evidence: 질의 키워드 → 원문 근거 (전부 코드 — LLM 은퇴 2026-07-09) ----
# "블로거 21명이 언급" + 원문 발췌 그대로. 스니펫은 정본매핑으로 접어 조각 전체에서 모은다.
_SNIPPETS = None          # 정본명 → [{t, date, blogger, link}]
_REACTIONS = None         # video_id → {summary, tone, n_comments}
_REVIEWS = None           # 정본명 → [{text, star}]  (카카오 방문자 리뷰)

def _load_snippets():
    global _SNIPPETS, _REACTIONS, _REVIEWS
    if _SNIPPETS is not None:
        return
    # 스니펫: pre-index(evidence_snippets.json) 우선 로드 — 57MB 원본 런타임 파싱 회피.
    # Render 무료 티어에서 첫 /evidence 17.6초→<1초 (2026-07-10). pipeline/build_evidence_index.py 산출.
    _idx = os.path.join(ROOT, "data", "processed", "evidence_snippets.json")
    if os.path.exists(_idx):
        _SNIPPETS = json.load(open(_idx, encoding="utf-8"))
        print(f"[server] 근거 스니펫: pre-index {sum(len(v) for v in _SNIPPETS.values())}건/{len(_SNIPPETS)}카페")
    else:
        # 폴백: 원본 직접 파싱 (로컬·pre-index 미생성 시). ⚠️ 매칭 규칙은 build_evidence_index.py 와 동일하게 유지.
        snip = {}
        for raw_name in ("네이버 크롤링.jsonl", "네이버 재검색 크롤링.jsonl"):
            p = os.path.join(ROOT, "data", "raw", raw_name)
            if not os.path.exists(p):
                continue
            for line in open(p, encoding="utf-8", errors="replace"):
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                key = _norm(rec.get("cleaned_name") or rec["spot_name"])
                canon = ALIAS2CANON.get(rec["spot_name"], rec["spot_name"])
                rows = []
                for it in rec.get("blog", {}).get("items", []):
                    txt = _clean(it.get("title", "") + " " + it.get("description", ""))
                    if key and key in _norm(txt) and it.get("postdate", "") >= "20240101":
                        rows.append({"t": txt, "date": it.get("postdate", ""),
                                     "blogger": it.get("bloggername", ""), "link": it.get("link", "")})
                if rows:
                    snip.setdefault(canon, []).extend(rows)
        _SNIPPETS = snip
        print(f"[server] 근거 스니펫: 원본 파싱 폴백 {sum(len(v) for v in snip.values())}건 (pre-index 없음)")
    rx = {}
    p = os.path.join(ROOT, "data", "processed", "댓글 정제.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("reaction_summary"):
                rx[r["video_id"]] = {"summary": r["reaction_summary"],
                                     "tone": r.get("reaction_tone", ""),
                                     "n_comments": r.get("n_comments", 0)}
    _REACTIONS = rx
    rv = {}
    p = os.path.join(ROOT, "data", "processed", "카카오리뷰.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("spot_name") and r.get("reviews"):
                canon = ALIAS2CANON.get(r["spot_name"], r["spot_name"])
                rv.setdefault(canon, []).extend(r["reviews"])
    _REVIEWS = rv
    print(f"[server] 근거 인덱스: 스니펫 {sum(len(v) for v in _SNIPPETS.values())}건/{len(_SNIPPETS)}카페, "
          f"반응 {len(rx)}편, 카카오리뷰 {sum(len(v) for v in rv.values())}건/{len(rv)}카페")

def _pick_review_quotes(reviews, terms, limit=3):
    """카카오 리뷰 인용 — 좋아요(별점 4~5)·별로요(별점 1~3)를 '각각' limit개까지 뽑아 프론트가
       방향별(👍/👎)로 나눠 표시. 질의 키워드 매칭 우선, 모자라면 키워드 무관 리뷰로 보충한다.
       부정 여론이 인용 정원(옛 high2+low1)이나 키워드 필터에 지워지지 않게 — 신뢰가 컨셉."""
    def hit(t):
        return not terms or any(any(s in t for s in stems) for stems in terms)
    valid = [r for r in reviews if (r.get("text") or "").strip()]
    def take(pool, n):   # 방향 안에서 키워드 매칭 먼저, 부족하면 나머지로 채움
        pref = [r for r in pool if hit(r["text"])]
        rest = [r for r in pool if not hit(r["text"])]
        return (pref + rest)[:n]
    low  = sorted([r for r in valid if (r.get("star") or 5) <= 3], key=lambda r: r.get("star") or 5)   # 낮은 별점 먼저
    high = sorted([r for r in valid if (r.get("star") or 5) >= 4], key=lambda r: -(r.get("star") or 5))  # 높은 별점 먼저
    out, seen = [], set()
    for r in take(high, limit) + take(low, limit):
        t = (r["text"] or "").strip().replace("\n", " ")
        if t and t not in seen:
            seen.add(t)
            out.append({"text": t[:140], "star": r.get("star")})
    return out

def _pick_blog_quotes(rows, terms, limit=3):
    """블로그 스니펫 원문 발췌 — 키워드 매칭 문장, 블로거 다양성 우선. 발췌는 원문 그대로(지어내기 원천 차단)."""
    out, seen_bloggers = [], set()
    for r in rows:  # 1순위: 서로 다른 블로거의 문장
        if r["blogger"] in seen_bloggers:
            continue
        seen_bloggers.add(r["blogger"])
        out.append(r["t"][:160])
        if len(out) >= limit:
            return out
    for r in rows:  # 블로거가 모자라면 중복 허용
        t = r["t"][:160]
        if t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out

def _evidence_impl(name: str, q: str = ""):
    _load_snippets()
    canon = ALIAS2CANON.get(name, name)
    rows = _SNIPPETS.get(canon, [])
    terms = _terms(q) if q else []
    if terms:
        matched = [r for r in rows if any(any(s in r["t"] for s in stems) for stems in terms)]
    else:
        matched = rows
    bloggers = len({r["blogger"] for r in matched if r["blogger"]})
    c = CARDS.get(canon, {})
    out = {"name": canon, "query": q,
           "n_snippets": len(rows), "n_matched": len(matched), "bloggers_matched": bloggers,
           "quotes": _pick_blog_quotes(matched, terms), "opinion": "",
           "rating_avg": c.get("rating_avg"), "rating_count": c.get("rating_count"),
           "review_tone": c.get("review_tone", ""),
           "review_quotes": _pick_review_quotes((_REVIEWS or {}).get(canon, []), terms),
           "youtube_reactions": []}
    for vid in (c.get("video_ids") or [])[:3]:
        r = (_REACTIONS or {}).get(vid)
        if r:
            out["youtube_reactions"].append({"video_id": vid, **r})
    return out


app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/evidence")
def evidence(name: str, q: str = ""):
    """카드 '근거 보기' — 실제 블로거 원문 인용 + 방문자 리뷰 + 쇼츠 댓글 반응 (전부 코드 발췌)."""
    return _evidence_impl(name, q)

def _search_core(q, k=8, debug=0):
    """임베딩+어휘게이트 검색 코어 — /search 엔드포인트와 /agent 판단 루프가 공유한다.
    동작은 종전 /search와 동일 (추출 리팩터 — 회귀 없음)."""
    region = detect_region(q)
    want_b, want_f = _label_to_bf(region)
    pinned = name_lookup(q)  # 이름 조회는 임베딩보다 먼저, 결정적으로
    browse = not pinned and is_browse(q)
    relaxed = False
    total = None
    emb_debug = None
    gated = 0  # 어휘 매칭 게이트로 걸러진 카페 수 (debug 관찰용)
    excluded = 0  # 하드 배제(노키즈존 등)로 걸러진 카페 수
    excl_tags = detect_exclusions(q)  # 배제 태그 집합 (browse·조건검색 공용)
    resolved = {"groups": [], "want": set(), "log": [], "unresolved": []}  # 번역 로그(조건검색서 채움)

    if browse:
        # 브라우즈: 빈 질의는 유사도가 노이즈 — 임베딩 생략, 다수결(union 블로거) 정렬 (원칙 8)
        k = max(k, 12)
        pool = []
        for n in SERVING:
            c = CARDS.get(n, {})
            if excl_tags and (set(c.get("tags") or []) & excl_tags):
                excluded += 1
                continue  # 하드 배제 (아이 동반 → 노키즈존) — browse에서도 완화 불가
            b, f = c.get("region_bucket"), c.get("region_fine")
            if want_b:
                if want_f and f == want_f:
                    tier = 0
                elif b == want_b:
                    tier = 1 if want_f else 0
                else:
                    continue
            else:
                tier = 0
            pool.append((tier, -c.get("bloggers", 0), -c.get("mention_count", 0), n))
        total = len(pool)
        pool.sort()
        ordered = [(n, 0.0, SERVING[n], False) for _, _, _, n in pool[:k]]
    else:
        q_emb = client.embeddings.create(model="text-embedding-3-large", input=[q]).data[0].embedding
        res = col.query(query_embeddings=[q_emb], n_results=max(k * 8, 64))

        if debug:
            emb_debug = sorted(
                [{"spot_name": m["spot_name"], "source": m.get("source"), "score": round(1 - d, 3)}
                 for m, d in zip(res["metadatas"][0], res["distances"][0])],
                key=lambda x: -x["score"])

        # spot 단위 병합: 같은 카페(blog+hybrid 문서)의 최고 점수 — 이름 중복은 merge가 이미 해소
        spots = {}
        for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
            n = meta["spot_name"]
            score = 1 - dist
            s = spots.setdefault(n, {"score": 0.0, "sources": []})
            s["score"] = max(s["score"], score)
            if meta["source"] not in s["sources"]:
                s["sources"].append(meta["source"])

        # 이름 매치 고정: 질의에 카페명이 있으면 지역 필터와 무관하게 무조건 앞 (폐업이면 안내 카드)
        ordered = []
        for canon in pinned:
            s = spots.pop(canon, None) or {"sources": SERVING.get(canon, [])}
            ordered.append((canon, 1.0, s["sources"], True))  # 확정 매치는 유사도가 아니라 1.0 고정

        # 어휘 매칭 게이트: 조건어가 근거에 실재하는 카페만 남긴다 (임베딩 유사도는 순위로 강등).
        # pinned(이름 조회)는 예외 — 이미 ordered로 분리됨. 조건어 없으면 게이트 비활성(통과).
        # 전멸 시 pool=0 → 지역완화(relaxed)도 0 → cards 빈 배열 → 프론트가 "못 찾았어요"로 침묵.
        resolved = resolve_terms(q)
        if resolved["groups"]:
            before = len(spots)
            spots = {n: s for n, s in spots.items() if _grounded(n, resolved)}
            gated = before - len(spots)

        # 하드 배제 (아이 동반 → 노키즈존 제거). 게이트 후·지역필터 전, 완화 불가.
        # pinned(이름 조회)는 ordered로 이미 분리돼 여기 영향 없음 — 콕 집은 카페는 배제 면제.
        if excl_tags:
            excluded, kept = _apply_exclusions(list(spots.keys()), excl_tags)
            spots = {n: spots[n] for n in kept}

        # 지역 필터 (카드 확정값 기준, 단계 완화: 세부 → 버킷 → 전체)
        def bf(n):
            c = CARDS.get(n, {})
            return c.get("region_bucket"), c.get("region_fine")
        pool = [(n, s["score"], s["sources"]) for n, s in spots.items()]
        _sc = lambda x: -x[1]
        if want_b:
            tier1 = [p for p in pool if want_f and bf(p[0])[1] == want_f]
            tier2 = [p for p in pool if bf(p[0])[0] == want_b and p not in tier1]
            regional = sorted(tier1, key=_sc) + sorted(tier2, key=_sc)
            if len(ordered) + len(regional) >= k:
                pool = regional
            else:
                relaxed = True
                others = sorted([p for p in pool if p not in regional], key=_sc)
                pool = regional + others
        else:
            pool = sorted(pool, key=_sc)
        ordered = (ordered + [(n, sc, src, False) for n, sc, src in pool])[:k]

    cards = [card_out(n, sc, src, nm, q=q, want_b=want_b, want_f=want_f)
             for n, sc, src, nm in ordered]

    out = {"query": q, "region": region, "relaxed": relaxed, "browse": browse,
           "total": total, "cards": cards,
           "translation": resolved["log"],      # 조건어→태그 번역 내역 ("이렇게 해석했어요")
           "unresolved": resolved["unresolved"]}  # 미해석 조건 (정직한 실패 / grade 트리거 자리)

    # 디버깅 모드: 후보 소집~정렬을 유리상자로 (?debug=1) — LLM 관문은 은퇴, 감시 지점 소멸
    if debug:
        out["debug"] = {
            "route": "조회" if pinned else ("브라우즈" if browse else "조건"),
            "region": {"detected": region, "bucket": want_b, "fine": want_f, "relaxed": relaxed},
            "gated": gated,  # 어휘 매칭 게이트로 걸러진 무관 카페 수 (조건검색만)
            "excluded": excluded,  # 하드 배제(노키즈존 등)로 걸러진 카페 수
            "exclude_tags": sorted(excl_tags),  # 이 쿼리에서 배제된 태그
            "terms": _terms(q),
            "pinned": pinned,
            "embedding": ({"n_docs": len(emb_debug),
                           "n_unique_cafes": len({d["spot_name"] for d in emb_debug}),
                           "docs": emb_debug[:40]} if emb_debug is not None else None),
            "final_order": [c["spot_name"] for c in cards],
            "matched": {c["spot_name"]: c.get("matched") for c in cards if c.get("matched")},
        }
    return out

@app.get("/search")
def search(q: str, k: int = 8, explain: int = 0, debug: int = 0):
    # explain은 하위호환으로 받기만 함 (LLM 층 은퇴). 코어에 그대로 위임.
    return _search_core(q, k, debug)

# ============================================================================
# 에이전틱 판단 루프 (/agent) — LLM이 결과를 평가하고 부족/무관하면 완화·외부검색.
# 신규 판단 노드는 judge 하나뿐. 완화·외부검색·종합은 코드가 실행(LLM은 판단·종합만).
# 결정 28 정신 유지: LLM은 도구(검색)가 준 근거 위에서만 말한다.
# ============================================================================
def _llm_json(system, user, max_retry=2):
    """gpt-5-mini json 호출 (router._llm_intent 패턴 미러). 실패 시 None — 실패 무해."""
    for i in range(max_retry):
        try:
            resp = client.chat.completions.create(
                model="gpt-5-mini",
                response_format={"type": "json_object"},
                max_completion_tokens=4000,
                reasoning_effort="minimal",
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )
            content = resp.choices[0].message.content or ""
            if not content.strip():
                return None
            d = json.loads(content)
            return d if isinstance(d, dict) else None
        except Exception as e:
            if i == max_retry - 1:
                print(f"[agent] LLM 실패 ({type(e).__name__}: {e})")
                return None
            time.sleep(2 ** i)
    return None


_JUDGE_SYS = """제주 카페 검색 결과가 사용자 질문에 맞는지 판단해 json으로만 답해.

## 출력 스키마
{"verdict": "충분" 또는 "부족" 또는 "무관", "drop": 완화할 조건어 문자열 또는 null, "reason": "한 문장"}

## 기준
- 충분: 결과가 질문 의도에 맞고 쓸 만하다.
- 부족: 방향은 맞지만 후보가 너무 적거나 특정 선호 조건이 좁아 아쉽다. 이때 drop에
  질문에 있던 '선호 조건어' 하나(분위기·뷰·메뉴 같은 완화 가능한 성질)를 넣어라.
- 무관: 결과가 질문의 핵심 대상과 동떨어졌다(질문이 원하는 종류가 결과에 거의 없음). drop=null.
- 지역·필수조건(주차·노키즈존 등)은 절대 drop 후보로 넣지 마라 — 완화 가능한 건 선호뿐.
- 결과가 0곳이면 무관 또는 부족으로 판단하라.
- 창의성 금지. 결과 목록에 있는 사실로만 판단."""


def judge(q, cards):
    """결과 카드를 보고 충분/부족/무관 판단 (LLM 1회). 실패 무해 → '충분' 폴백."""
    if cards:
        lines = []
        for i, c in enumerate(cards[:10], 1):
            tags = " ".join(c.get("tags") or [])
            summ = (c.get("summary_blog") or "")[:50]
            lines.append(f"{i}. {c['spot_name']} [{tags}] {summ}")
        user = f"질문: {q}\n결과 {len(cards)}곳:\n" + "\n".join(lines)
    else:
        user = f"질문: {q}\n결과: 0곳 (내부 데이터에서 못 찾음)"
    d = _llm_json(_JUDGE_SYS, user)
    if not d or d.get("verdict") not in ("충분", "부족", "무관"):
        return {"verdict": "충분", "drop": None, "reason": "판단 실패 — 기존 결과 유지"}
    return {"verdict": d["verdict"], "drop": d.get("drop"), "reason": d.get("reason", "")}


_SYNTH_SYS = """제주 카페 검색 결과를 근거로 답할 소개 한 줄과 카페별 추천 이유를 json으로 써.

## 출력 스키마
{"intro": "결과 전체를 요약하는 한 문장", "reasons": {"카페명": "추천 이유 한 문장", ...}}

## 규칙
- 제공된 카드의 태그·요약에 있는 사실만 사용. 없는 정보(주소·메뉴·평점·영업시간)를 지어내지 마.
- 카페명은 제공된 것과 글자 그대로 일치시켜라.
- intro는 담백한 한 문장. 과장·이모지·인사말 금지.
- reasons는 결과에 있는 카페만. 근거가 빈약하면 태그를 담백히 옮겨라."""


def synthesize_answer(q, cards):
    """근거(태그·요약) 위에서 소개 + 카페별 이유 종합 (LLM 1회). 실패 시 None."""
    lines = []
    for c in cards[:10]:
        tags = " ".join(c.get("tags") or [])
        summ = (c.get("summary_blog") or "")[:80]
        lines.append(f"- {c['spot_name']} [{tags}] {summ}")
    user = f"질문: {q}\n카페들:\n" + "\n".join(lines)
    return _llm_json(_SYNTH_SYS, user)


def _drop_condition(q, drop):
    """질의에서 완화 대상 조건어(및 짧은 어간)를 제거. 못 지우면 원 질의 그대로(→ 완화 무효)."""
    if not drop:
        return q
    for token in [drop, drop[:-1] if len(drop) >= 3 else None]:
        if token and token in q:
            return re.sub(r"\s{2,}", " ", q.replace(token, "")).strip()
    return q


def _kakao_query(q):
    """카카오 검색어 정제 — '카페' 등 일반어를 빼고 '제주 {핵심}'로.
    실측: "제주 노래방 카페"→0건이지만 "제주 노래방"→노래방 5곳, "제주 승마"→승마장 5곳
    (카카오는 문구 전체 매칭이라 '카페'가 붙으면 그 이름의 장소를 찾다 0건)."""
    core = q
    for w in ("카페", "커피", "맛집", "추천", "가볼만한", "곳"):
        core = core.replace(w, "")
    core = re.sub(r"\s{2,}", " ", core).strip()
    return "제주 " + (core if core else q)


def _kakao_search(q, size=5):
    """카카오 로컬 키워드 검색 (kakao_place.py:kakao 로직 미러). 키 없거나 실패 시 []."""
    key = env.get("KAKAO_KEY")
    if not key:
        return []
    url = ("https://dapi.kakao.com/v2/local/search/keyword.json?size=%d&query=" % size
           + urllib.parse.quote(q))
    req = urllib.request.Request(url, headers={"Authorization": "KakaoAK " + key})
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=10)).get("documents", [])
        except Exception as e:
            if i == 2:
                print(f"[agent] 카카오 검색 실패 ({type(e).__name__})")
                return []
            time.sleep(2 ** i)
    return []


_OUR_PIDS = set(str(p) for p in SPOT_PID.values() if p)  # 우리 코퍼스 place_id (중복 제거용)


def _kakao_to_cards(docs, limit=5):
    """카카오 document → 프론트 카드 계약에 맞춘 외부 카드. 우리 코퍼스 중복(place_id) 제외."""
    out = []
    for d in docs:
        pid = str(d.get("id") or "")
        if pid and pid in _OUR_PIDS:
            continue  # 이미 우리 데이터에 있는 곳 — 외부 폴백에서 제외
        addr = d.get("road_address_name") or d.get("address_name") or ""
        cat = (d.get("category_name") or "").split(">")[-1].strip()
        out.append({
            "spot_name": d.get("place_name", ""),
            "place_id": pid or None,
            "score": 0.0, "sources": ["kakao"], "name_match": False,
            "region": detect_region(addr) or "", "region_bucket": "", "region_fine": "",
            "summary_blog": "", "summary_youtube": "",
            "tags": [], "video_ids": [], "blog_links": [], "bloggers": 0, "mention_count": 0,
            "address": addr, "category": cat or "장소",
            "caution": [], "hours_hint": "",
            "reaction_tone": "", "reaction_hint": "",
            "rating_avg": None, "rating_count": None, "review_tone": "",
            "closed": False, "matched": None,
            "lat": (float(d["y"]) if d.get("y") else None),
            "lng": (float(d["x"]) if d.get("x") else None),
            "external": True, "reason": (cat + " · 카카오맵 검색 결과").strip(" ·"),
            "place_url": d.get("place_url", ""),
        })
        if len(out) >= limit:
            break
    return out


def run_agent(q, k=8):
    """판단 루프: 검색 → judge → (부족: 완화 재검색 / 무관·0건: 카카오) → 종합.
    최대 2 루프. LLM은 판단(judge)·종합(synthesize)에만, 나머지는 결정적 코드."""
    trace = []
    out = _search_core(q, k)
    cards = out["cards"]
    trace.append({"step": "검색", "n": len(cards), "detail": f"내부 코퍼스에서 {len(cards)}곳"})
    external = False

    for _ in range(2):
        v = judge(q, cards)
        trace.append({"step": "판단", "detail": f"{v['verdict']} — {v['reason']}"})
        if v["verdict"] == "충분":
            break
        if v["verdict"] == "부족" and v.get("drop"):
            q2 = _drop_condition(q, v["drop"])
            if q2 != q:
                trace.append({"step": "완화", "detail": f"'{v['drop']}' 조건을 빼고 다시 찾음"})
                out = _search_core(q2, k)
                cards = out["cards"]
                trace.append({"step": "재검색", "n": len(cards), "detail": f"{len(cards)}곳"})
                continue
        # 무관, 또는 완화해도 소용없음 → 외부 검색(카카오)
        kcards = _kakao_to_cards(_kakao_search(_kakao_query(q)))
        if kcards:
            external = True
            cards = kcards
            trace.append({"step": "외부검색", "n": len(cards),
                          "detail": f"카카오맵에서 {len(cards)}곳"})
        break

    # 종합
    if external:
        intro = f"우리 데이터엔 딱 맞는 곳이 없어서, 카카오맵에서 '{q}' 관련 {len(cards)}곳을 찾았어요."
    elif cards:
        ans = synthesize_answer(q, cards)
        if ans and ans.get("intro"):
            intro = ans["intro"]
            reasons = ans.get("reasons") or {}
            for c in cards:
                if c["spot_name"] in reasons:
                    c["reason"] = reasons[c["spot_name"]]
        else:
            intro = ""  # 실패 무해 — 프론트가 summary 첫 문장으로 폴백
    else:
        intro = f"'{q}'에 맞는 카페를 찾지 못했어요."

    out["cards"] = cards
    out["intro"] = intro
    out["agent_trace"] = trace
    out["external"] = external
    return out


@app.get("/agent")
def agent(q: str, k: int = 8):
    """에이전틱 판단 루프 엔드포인트. /search와 같은 응답 계약 + intro/agent_trace/external."""
    return run_agent(q, k)

@app.get("/photos")
def photos(name: str, lat: float = None, lng: float = None, place_id: str = None):
    """카페 구글 사진의 임시 URL 목록. 키는 서버에만 — 프론트엔 URL만 나감."""
    if not GKEY:
        return {"error": "no_api_key", "photos": []}
    try:
        pid, uris = _places_photo_uris(name, lat, lng, place_id)
        return {"name": name, "place_id": pid, "photos": uris}
    except urllib.error.HTTPError as e:
        return {"error": "google_%d" % e.code,
                "detail": e.read().decode("utf-8", "replace")[:200], "photos": []}
    except Exception as e:
        return {"error": type(e).__name__, "photos": []}


@app.get("/health")
def health():
    return {"ok": True, "docs": col.count(), "cafes": len(CARDS), "serving": len(SERVING),
            "place_id_map_size": len(SPOT_PID),
            "place_id_test": {n: SPOT_PID.get(n) for n in ("노을리", "노을리카페", "프릳츠커피")}}


# ---- 정적 프론트 서빙 (배포: 프론트 + API 를 한 서버에서) ----
# 로컬 개발 땐 프론트를 따로(:8503) 띄웠지만, 배포는 이 서버 하나가 web/ 도 서빙한다.
WEB_DIR = os.path.join(ROOT, "web")

@app.get("/config.local.js")
def config_local_js():
    """카카오맵 JS 키 주입 — config.local.js 는 gitignore 라 배포엔 파일이 없다.
    환경변수 KAKAO_JS_KEY 를 브라우저로 내려준다(도메인 등록으로 보호되는 공개키). 없으면 SVG 지도 폴백."""
    kjs = env.get("KAKAO_JS_KEY", "")
    return Response(f"window.KAKAO_JS_KEY = {json.dumps(kjs)};",
                    media_type="application/javascript")

# StaticFiles 마운트는 맨 마지막 — 위 API 라우트들이 먼저 매칭되고, 나머지 경로만 web/ 정적 파일로.
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

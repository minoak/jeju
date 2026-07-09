# -*- coding: utf-8 -*-
"""
태그 사전 접근층 (W2-4 지원 모듈, W3 소유 파일)

역할:
  - data/processed/태그사전v2.json (W1 산출물)이 존재하면 그걸 로드,
    없으면 내장 픽스처(활성 23 + 보류 4)로 동작한다.
  - router(W2)와 번역기(translate/translate_stub)가 태그 목록·하드조건·배제
    의미론을 전부 여기서만 읽는다 -- 태그 지식의 단일 창구.
    W1 본판(태그사전v2.json)이 나와도 이 모듈의 인터페이스는 그대로다.

스키마 (태그사전v2.json 계약과 동일):
  {"version": ..., "tags": [{"tag", "synonyms", "hard_capable", "exclude_for", "status"}]}

의미론:
  - status == "보류" 태그는 번역 해석 대상에서 제외한다 (unresolved 처리,
    W1 지침과 동일 의미론). "보류"가 아닌 status는 전부 활성으로 본다.
  - hard_capable: 가부(있다/없다)로 판정 가능한 태그만 True -- W2 router가
    하드조건 승격 시 이 필드를 참조해 코드로 후처리한다 (LLM 판정 금지).
  - exclude_for: "이 태그가 있으면 배제해야 하는 쿼리 맥락" 설명.
    현재 노키즈존만 해당 -- 아이 동반 쿼리에서 하드 배제.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # server.py:38 ROOT 패턴 미러
TAGDICT_PATH = os.path.join(ROOT, "data", "processed", "태그사전v2.json")


def _t(tag, synonyms, hard=False, exclude=None, status="활성"):
    """픽스처 표기를 짧게 하기 위한 내부 헬퍼 (스키마 딕트 생성)."""
    return {"tag": tag, "synonyms": synonyms, "hard_capable": hard,
            "exclude_for": exclude, "status": status}


# ---- 내장 픽스처 (W1 산출물이 나오기 전 임시 정본 -- 스텁용 최소 synonym 셋) ----
# 활성 23 = 기존 20 + 승격 3(포토존/핸드드립/한라산뷰). 보류 4는 status="보류"로
# 수록하되 번역 매칭 대상에서 제외된다.
#
# hard_capable=True: 애견동반, 노키즈존, 키즈친화, 포장(보류라 사실상 비활성).
# ⚠ 주차편함은 가부형이지만 hard_capable=False --
#   부여율 79%(790/996)로 변별력 의심, tag_audit 재평가 대기.
_FIXTURE = {
    "version": "fixture-2026-07-09",
    "tags": [
        # -- 뷰/풍경 --
        _t("오션뷰", ["바다뷰", "바다전망", "해변뷰", "비치뷰", "바다 보이는"]),
        _t("산방산뷰", ["산방산 전망"]),
        _t("숲뷰", ["숲속", "자연뷰"]),
        _t("한라산뷰", ["한라산 전망", "한라산 보이는"]),  # 승격 (tag_audit)
        _t("노을", ["선셋", "일몰", "석양", "노을 맛집"]),
        # -- 분위기 --
        _t("감성", ["감성적인", "분위기 좋은", "인테리어 예쁜", "아늑한"]),
        _t("조용함", ["조용한", "한적한", "고요한", "차분한"]),
        _t("대형", ["넓은", "대형카페"]),
        _t("포토존", ["포토스팟", "인생샷", "사진 맛집", "사진 찍기 좋은"]),  # 승격 (tag_audit)
        # -- 메뉴 --
        _t("베이커리", ["빵집", "빵 맛집"]),
        _t("브런치", ["브런치 카페", "아침식사"]),
        _t("디저트", ["디저트 맛집"]),
        _t("핸드드립", ["드립커피", "드립 커피", "로스터리", "스페셜티", "필터커피"]),  # 승격 (tag_audit)
        # -- 동반 조건 (가부형 = hard_capable) --
        _t("애견동반", ["반려견동반", "반려동물 동반", "반려동물동반", "강아지",
                    "반려견", "애견", "펫 프렌들리"], hard=True),
        _t("노키즈존", ["노키즈", "어른 전용"], hard=True,
           exclude="아이 동반 쿼리 (아이/아기/애기/유아/키즈 감지 시 하드 배제)"),
        _t("키즈친화", ["가족친화", "아이와 가볼만한", "아이랑", "아기랑", "키즈"], hard=True),
        # -- 공간/설비 --
        _t("통창", ["통유리", "전면 유리", "파노라마 창"]),
        _t("야외석", ["테라스", "야외 좌석", "마당"]),
        _t("루프탑", ["옥상", "루프톱"]),
        _t("주차편함", ["주차", "주차장", "주차 편한"]),  # ⚠ hard_capable=False (위 주석 참조)
        # -- 기타 --
        _t("웨이팅", ["오픈런"]),
        _t("신상", ["새로 생긴", "신규 오픈", "최근 오픈"]),
        _t("로컬", ["현지인", "로컬 맛집", "동네"]),
        # -- 보류 4 (번역 매칭 제외 -- unresolved 처리) --
        _t("포장", ["테이크아웃", "포장 가능"], hard=True, status="보류"),  # 보류라 사실상 비활성
        _t("정원", ["가든"], status="보류"),
        _t("가성비", ["저렴", "가격 착한"], status="보류"),
        _t("빈티지", ["레트로"], status="보류"),
    ],
}


def load_tagdict():
    """태그사전 로드. 파일(W1 정본)이 있으면 우선, 없거나 깨졌으면 내장 픽스처.

    반환: 스키마 딕트 {"version", "tags": [...]}. 어느 쪽을 썼는지 print 1줄.
    """
    if os.path.exists(TAGDICT_PATH):
        try:
            with open(TAGDICT_PATH, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("tags"), list) and d["tags"]:
                n_hold = sum(1 for t in d["tags"] if t.get("status") == "보류")
                print(f"[tagdict] 태그사전v2.json 로드 (version={d.get('version')}, "
                      f"활성 {len(d['tags']) - n_hold} / 보류 {n_hold})")
                return d
            # except 삼킴 금지 -- 스키마 이상은 경고 후 픽스처 폴백
            print("[tagdict] 경고: 태그사전v2.json 스키마 이상 (tags 리스트 없음/비어있음), 내장 픽스처로 폴백")
        except (OSError, json.JSONDecodeError) as e:
            print(f"[tagdict] 경고: 태그사전v2.json 로드 실패 ({e}), 내장 픽스처로 폴백")
    n_hold = sum(1 for t in _FIXTURE["tags"] if t["status"] == "보류")
    print(f"[tagdict] 내장 픽스처 사용 (활성 {len(_FIXTURE['tags']) - n_hold} / 보류 {n_hold})")
    return _FIXTURE


# ---- 모듈 로드 시 1회 로드 (어느 소스를 썼는지 위 print가 알린다) ----
TAGDICT = load_tagdict()
_BY_NAME = {t["tag"]: t for t in TAGDICT["tags"]}


def active_tags():
    """status가 "보류"가 아닌 태그명 리스트 (번역·검색 해석 대상)."""
    return [t["tag"] for t in TAGDICT["tags"] if t.get("status") != "보류"]


def is_hard(tag):
    """가부형(하드조건 승격 가능) 태그인가. 사전에 없는 태그는 False."""
    t = _BY_NAME.get(tag)
    return bool(t and t.get("hard_capable"))


def exclude_map():
    """{태그: exclude_for 설명} -- 현재 노키즈존만 해당.

    W2 router가 쿼리 맥락(아이 동반 등) 감지 시 intent.배제에 넣을 때 참조.
    """
    return {t["tag"]: t["exclude_for"] for t in TAGDICT["tags"] if t.get("exclude_for")}


def synonyms_of(tag):
    """태그의 synonym 리스트 (사본). 사전에 없는 태그는 빈 리스트."""
    t = _BY_NAME.get(tag)
    return list(t.get("synonyms", [])) if t else []


if __name__ == "__main__":
    # 가벼운 자가 점검 (본 스모크는 translate_stub.py __main__에 통합)
    act = active_tags()
    print(f"[tagdict] 활성 태그 {len(act)}개: {', '.join(act)}")
    assert len(act) == 23, f"활성 태그 수 이상: {len(act)}"
    assert "포장" not in act and "정원" not in act, "보류 태그가 활성 목록에 섞임"
    assert is_hard("애견동반") and is_hard("노키즈존") and is_hard("키즈친화")
    assert not is_hard("주차편함"), "주차편함은 hard_capable=False여야 함 (tag_audit 대기)"
    assert "노키즈존" in exclude_map()
    assert "선셋" in synonyms_of("노을")
    print("[tagdict] 자가 점검 통과")

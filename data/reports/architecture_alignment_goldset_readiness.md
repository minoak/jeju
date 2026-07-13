# Architecture Alignment And Goldset Readiness

기준 문서: `C:\Users\u\Downloads\제주카페_기술아키텍처.pptx`

## 결론

현재 구현은 아키텍처의 큰 방향과는 맞다. 특히 배치에서 판단을 끝내고 `cards.json`을 런타임의 단일 계약으로 쓰는 원칙은 잘 지켜지고 있다.

다만 PPT의 “런타임 LLM ① 해석 → 코드 검색 → LLM ② 종합” 구조는 현재 production path인 `app.server.search`에는 아직 완전히 연결되어 있지 않다. 이 구조는 `app/router.py`, `app/retrieve.py`, `app/relax.py`, `app/synthesize.py`에 별도 W2-W4 파이프라인으로 구현되어 있다.

따라서 골드셋 검증은 두 종류로 나눠야 한다.

1. 현재 서비스 검색 성능 검증: 지금 가능하고 이미 수행됨.
2. PPT 설계 아키텍처 검증: W2-W4를 실제 검색 엔드포인트 또는 평가기에 연결한 뒤 수행하는 것이 맞음.

## PPT Architecture Summary

| slide | 설계 의도 |
|---|---|
| 1 | 배치 타임과 런타임 분리. 카드 저장소가 두 무대를 잇는 유일한 다리 |
| 2 | 유튜브, 네이버 블로그, 카카오맵, 쇼츠 댓글을 각자 역할별로 사용 |
| 3 | 카페 한 곳은 카드 한 장. 신호/근거/태그/텍스트/신원층으로 구성 |
| 4 | 런타임은 LLM 해석, 코드 검색, LLM 종합으로 구성 |
| 5 | 임베딩은 카페 검색이 아니라 사용자 표현을 통제 태그로 번역하는 데 사용 |
| 6 | 원문 인용 검증, 하드 배제, 완화 사다리로 신뢰성 확보 |

## Alignment Check

| 설계 항목 | 현재 구현 상태 | 판단 |
|---|---|---|
| 배치에서 정제/판단 수행 | `pipeline/`, `merge.py`, `cards.json` 중심 구조 | 일치 |
| 런타임은 원본을 다시 건드리지 않음 | `server.py`는 `cards.json`, Chroma, 정제 파일만 읽음 | 대체로 일치 |
| 카드 저장소가 단일 계약 | `data/processed/cards.json` 831장 사용 | 일치 |
| place_id 기반 정본화 | duplicate place_id groups 0 | 일치 |
| closed 카드는 검색 제외 | Gold top-10 closed leakage 0 | 일치 |
| 원문 인용 검증 | `/evidence`, `synthesize.py` quote 검증 존재 | 일치 |
| 하드 배제 | W2-W4에는 존재. production `server.py` 검색에는 약함 | 부분 충돌 |
| 완화 사다리 | `app/relax.py`와 W2-W4 평가에는 존재. production `server.py`에는 단순 relax만 존재 | 부분 충돌 |
| LLM ① 해석 | `app/router.py`에 존재. production `server.py`에는 미연결 | 부분 충돌 |
| LLM ② 종합 | `app/synthesize.py`에 존재. production `server.py`는 runtime LLM 제거 | 의도 차이 존재 |
| 태그 표현 임베딩 번역 | PPT에는 핵심 구현으로 명시. 현재 production은 카페 Chroma 임베딩 검색 중심 | 충돌 가능 |
| 카페 순위는 읽을 수 있는 신호로만 결정 | W2-W4 retrieve는 코드 기반. production은 Chroma 유사도 + 코드 보정 | 부분 충돌 |

## 가장 중요한 상충 지점

### 1. PPT는 태그 번역용 임베딩, 현재 production은 카페 검색용 임베딩

PPT slide 5는 “임베딩은 찾지 않고 번역한다”고 되어 있다. 즉 임베딩 공간에는 카페 831장이 아니라 태그 표현 수십 개만 들어간다는 설계다.

현재 `app.server.search`는 질문 임베딩을 만들고 Chroma `cards` collection에서 카페 문서를 직접 검색한다. 이건 PPT의 이상적인 설명 가능 검색 구조와 다르다.

판단: 최종 설계를 PPT 기준으로 가져가려면, production 검색은 W2-W4의 tag translation + deterministic retrieve 쪽으로 이동해야 한다.

### 2. PPT는 runtime LLM 2회, 현재 production은 runtime 생성 LLM 0회

PPT는 LLM ① 해석, LLM ② 종합을 런타임 구성요소로 둔다. 반면 현재 `server.py`는 2026-07-09 개편 이후 runtime generation LLM을 제거했다.

이건 단순 버그는 아니다. 현재 production은 속도와 결정성을 위해 보수적으로 간 구조다. 다만 PPT의 설계 아키텍처와 1:1로 같지는 않다.

판단: 발표에서는 “현재 production은 deterministic fast path이고, PPT의 W2-W4 아키텍처는 다음 연결 대상”이라고 말하는 편이 정확하다.

### 3. 하드 배제가 production 성능에서 아직 약함

Goldset V2 결과에서 `Forbidden Exposure@5`가 20.0%다. 특히 “노키즈존 피하고 가족이 가기 좋은 카페” 같은 질문에서 금지 조건이 top-5에 노출됐다.

PPT slide 6의 “하드 배제는 어떤 완화에도 안 풀림” 원칙과 현재 production 결과가 충돌한다.

판단: 이 부분은 구조적 개선 우선순위 1번이다.

## Goldset Validation Timing

### 지금 한 Goldset 검증은 올바른가?

현재 production 검색 성능을 보는 목적이라면 올바르다.

근거:

- 평가 대상이 명확함: `cards.json` + `app.server.search`
- Gold 50 질문 사용
- Must Hit@5/@10, MRR, NDCG, Tag Match, Region Match, Forbidden Exposure를 계산함
- 이전 RAG는 recorded top-10 replay로 같은 V2 기준으로 비교함

### PPT 설계 아키텍처 검증으로도 올바른가?

아직은 부분적으로만 올바르다.

이유:

- PPT의 핵심 런타임 구조인 router → retrieve → relax → synthesize가 production `server.py`에 연결되어 있지 않음
- 태그 임베딩 번역 게이트가 production path에 없음
- 하드 배제가 production 결과에서 충분히 강제되지 않음

따라서 현재 Goldset 결과는 “현 production baseline” 검증이지 “PPT 최종 아키텍처 전체” 검증은 아니다.

## Current Goldset Result

| metric | current |
|---|---:|
| Must Hit@5 | 62.0% |
| Must Hit@10 | 76.0% |
| Canonical MRR@10 | 38.3% |
| NDCG@5 | 35.0% |
| NDCG@10 | 42.9% |
| Semantic Tag Match@5 | 67.2% |
| Semantic Tag Coverage@5 | 90.7% |
| Region Match@5 | 70.8% |
| Forbidden Exposure@5 | 20.0% |
| Determinism@10 | 100.0% |

## Previous vs Current

| metric | previous replay | current | delta |
|---|---:|---:|---:|
| Must Hit@5 | 62.0% | 62.0% | +0.0p |
| Must Hit@10 | 74.0% | 76.0% | +2.0p |
| Canonical MRR@10 | 42.4% | 38.3% | -4.1p |
| NDCG@5 | 36.9% | 35.0% | -1.9p |
| NDCG@10 | 43.1% | 42.9% | -0.2p |
| Semantic Tag Match@5 | 67.5% | 67.2% | -0.3p |
| Semantic Tag Coverage@5 | 90.7% | 90.7% | +0.0p |
| Region Match@5 | 60.0% | 70.8% | +10.8p |
| Forbidden Exposure@5 | 18.6% | 20.0% | +1.4p |

## Can We Run Goldset Validation Now?

가능하다. 단, 평가 목적을 명확히 해야 한다.

| 목적 | 지금 가능 여부 | 권장 방식 |
|---|---|---|
| 현재 production `server.py` 성능 측정 | 가능 | `eval/goldset_v2_eval.py` 실행 |
| 이전 RAG와 현재 RAG 비교 | 가능 | `eval/replay_previous_rag_v2_eval.py` 실행 |
| PPT 설계 전체 검증 | 아직 보류 | W2-W4 path를 평가기에 adapter로 연결 후 실행 |
| 하드 배제/완화 사다리 단위 검증 | 가능 | `eval/w234_검증.py` 또는 `goldset_v2_eval.py` W2-W4 포함 실행 |

## Recommended Next Step

1. Goldset V2는 현재 production baseline으로 계속 유지한다.
2. 별도 `goldset_w234_eval.py` 또는 adapter를 만들어 같은 Gold 50을 W2-W4 path로 평가한다.
3. 두 결과를 비교한다.
   - `server.py`: 현재 실제 서비스 baseline
   - `W2-W4`: PPT 설계 아키텍처 후보
4. W2-W4가 Forbidden Exposure와 NDCG@5에서 개선되면 production path로 승격한다.

## Final Judgment

아키텍처와 현재 구현은 큰 철학은 맞지만, 런타임 검색 구조는 아직 완전히 일치하지 않는다.

현재 Goldset 검증은 “지금 서비스가 얼마나 잘 검색하는가”를 보는 시점으로는 올바르다. 하지만 “PPT 설계 아키텍처가 성능을 개선했는가”를 증명하려면 W2-W4 경로를 같은 Goldset으로 따로 평가해야 한다.

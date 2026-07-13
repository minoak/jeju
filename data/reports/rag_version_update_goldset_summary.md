# RAG Version Update And Goldset Validation Summary

이 문서는 제주 카페 추천 RAG의 구조 변화와 골드셋 검증 결과를 버전별로 정리한 공유용 요약이다.

## 한 줄 결론

최신 RAG는 지역 조건 처리와 top-10 회수율은 개선됐지만, top-5 안에서 대표 정답을 더 위로 올리는 랭킹 품질은 이전 3-tier RAG보다 약간 낮다. 다음 개선 우선순위는 태그 재생성이 아니라 forbidden 조건 필터와 rerank다.

## Version Timeline

| version | 시점 | 핵심 구조 | 주요 개선 | 검증 상태 |
|---|---|---|---|---|
| V0 YouTube-first prototype | 7/7 이전 | 유튜브 수집/추출 중심, 영상 설명/태그 기반 카페 후보 생성 | 카페 후보 1,504 mention, 고유 이름 1,064개 확보 | Gold 50 이전 단계. 검색 품질 평가는 제한적 |
| V1 Blog-enriched seed RAG | 7/8 | 네이버 블로그 정제 + 유튜브 보조 근거 + hybrid embedding seed | 유튜브 low 카페를 블로그로 보강. 블로그 기준 high 947 / mid 29 / low 20. 검색 가능한 후보가 약 400대에서 약 980대로 증가 | 8개 비교 실험에서 블로그가 5승. Gold 50 정식 평가는 아직 전 |
| V2 Three-tier RAG | 7/9 낮 | name lookup / browse / condition search 3분기, Chroma + LLM reason, region 보정, place_id 정본화 | 이름 질의 고정, 지역 불일치 24.6% 보정, place_id 787/1,015 확보, `/evidence` 근거 API 추가 | Gold 50 평가 있음. 이번에 V2 메트릭으로 replay 재채점 |
| V3 Canonical deterministic RAG | 7/9 밤 이후 현재 | canonical `cards.json` 831장, Chroma `cards` 985문서, runtime LLM 제거, 코드 기반 matched reason, closed 제외 | 중복 place_id 0, alias lookup 100%, closed/non-serving leakage 0. 응답 속도와 재현성 개선 | Goldset V2 실제 실행 평가 완료 |

## Architecture Changes

### V0: YouTube-first prototype

- 지역 x 카테고리 격자와 포토스팟 채널을 수집했다.
- gpt-5-mini 2-pass로 추출과 실존 검증을 수행했다.
- 텍스트가 부족한 쇼츠도 제목/태그 기반 B-track으로 추출했다.
- 문제는 유튜브 설명/태그만으로는 카페 상세 정보가 빈약해서 low richness가 많았다는 점이다.

### V1: Blog-enriched seed RAG

- 네이버 블로그 검색 결과를 이용해 유튜브 low 카페를 보강했다.
- 블로그 본문 raw를 저장하지 않고 title/description/link/postdate 기반으로 정제했다.
- 블로그는 정보 신호, 유튜브는 영상 근거와 반응 신호로 역할을 나눴다.
- hybrid embedding seed를 만들어 네이버 문장형 근거와 유튜브 보조 근거를 함께 검색할 수 있게 했다.
- 이 시점의 핵심 성과는 “모델을 바꾼 것”이 아니라 “검색 가능한 데이터 밀도를 올린 것”이다.

### V2: Three-tier RAG

- 검색을 조회, 브라우즈, 조건 검색으로 나눴다.
- 고유 카페명은 임베딩 검색에 맡기지 않고 이름 사전으로 먼저 처리했다.
- 지역은 LLM 라벨이 아니라 주소 기반 코드 보정으로 처리했다.
- 조건 질의는 Chroma 검색 후 LLM이 intro/reason을 생성했다.
- place_id 기반 정본화가 들어가면서 중복과 실존 검증이 크게 좋아졌다.
- 단점은 runtime LLM과 중복 카드/별칭 문제가 아직 남아 있었다는 점이다.

### V3: Canonical deterministic RAG

- `merge.py`가 canonical card를 생성한다.
- 1,064개 이름 후보가 831개 canonical card로 병합됐다.
- Chroma collection `cards`에는 985문서가 들어간다.
- runtime LLM 생성은 제거하고, 추천 이유는 region/tags/bloggers 기반 코드로 생성한다.
- closed 카드는 검색/브라우즈에서 제외하고, 이름 조회에서는 폐업 안내로만 응답한다.
- `/evidence`는 LLM 의견 생성이 아니라 코드 기반 snippet/quote 검증으로 바뀌었다.

## Goldset Validation Setup

현재 골드셋은 추천형 질문 50개로 구성되어 있다.

평가 기준:

| metric | 의미 |
|---|---|
| Must Hit@5 / @10 | 대표 정답 카페가 top-k 안에 있는가 |
| Canonical MRR@10 | 대표 정답이 얼마나 앞 순위에 나오는가 |
| NDCG@5 / @10 | 좋은 후보가 상위권에 잘 정렬됐는가 |
| Semantic Tag Match@5 | top-5가 질문 의도 태그를 얼마나 만족하는가 |
| Semantic Tag Coverage@5 | 질문의 핵심 태그가 top-5 전체에서 얼마나 커버되는가 |
| Region Match@5 | 지역 조건이 맞는가 |
| Forbidden Exposure@5 | 피해야 할 조건이 노출되는가 |

NDCG relevance grade는 다음 신호를 합쳐 0~3점으로 계산한다.

- must_include 대표 카페 일치
- required_tags 일치
- required_region 일치
- optional_tags 일부 보너스
- forbidden_tags 노출 시 relevance 0

## Can All Versions Be Validated With Gold 50?

완전히 같은 조건으로는 어렵다. 각 버전마다 남아 있는 실행기/로그/산출물이 다르기 때문이다.

| version | Gold 50 검증 가능성 | 가능한 방식 | 공정성 판단 |
|---|---|---|---|
| V0 YouTube-first prototype | 제한적 | 당시 top-k 로그가 없으면 재현 불가. 현재 산출물로 adapter를 만들면 “재구성 평가”만 가능 | 낮음 |
| V1 Blog-enriched seed RAG | 가능하나 작업 필요 | `data/rag/hybrid_embedding_seed.jsonl`, `chroma_seed_test`, `chroma_smoke` 기반 adapter 작성 후 Gold 50 실행 | 중간 |
| V2 Three-tier RAG | 가능 | 당시 `rag_three_tier_evaluation.md` top-10 replay로 V2 metric 재채점 | 높음. 단 replay 평가 |
| V3 Canonical deterministic RAG | 가능 | 현재 `app.server.search`를 Gold 50으로 실제 실행 | 높음. 현재 production baseline |
| W2-W4 PPT architecture path | 가능하나 별도 구현 필요 | `router → retrieve → relax → synthesize` adapter를 만들어 Gold 50 실행 | 높음. PPT 설계 검증용 |

정리하면 “타임라인의 모든 버전”을 50 Goldset으로 평가할 수는 있지만, 평가의 성격이 다르다.

- V2/V3는 지금 바로 비교 가능하다.
- V1은 seed/chroma adapter를 만들면 가능하다.
- V0는 당시 실행 결과가 없으면 엄밀 비교가 아니라 복원 평가가 된다.
- PPT 아키텍처는 현재 production과 다른 W2-W4 경로를 별도로 평가해야 한다.

가장 권장하는 검증 순서는 다음과 같다.

1. V2 previous replay vs V3 current는 이미 완료된 비교 기준으로 유지한다.
2. V1 hybrid seed adapter를 만들어 Gold 50으로 추가 평가한다.
3. W2-W4 adapter를 만들어 PPT 설계 아키텍처 후보를 Gold 50으로 평가한다.
4. V0는 발표용 역사 설명에만 두고, 정량 비교표에는 “not strictly comparable”로 표시한다.

## Goldset Results

주의: V2는 당시 `rag_three_tier_evaluation.md`에 기록된 top-10 결과를 replay해서 재채점했다. V3는 최신 `app.server.search`를 실제 실행한 결과다.

### All-version Result

| version | mode | Must Hit@5 | Must Hit@10 | MRR@10 | NDCG@5 | NDCG@10 | Tag Match@5 | Region@5 | Forbidden@5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 YouTube-first | not runnable: surviving `source=youtube` docs missing | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| V1 Hybrid seed RAG | live seed adapter | 42.0% | 50.0% | 24.1% | 29.7% | 37.7% | 74.8% | 38.5% | 24.3% |
| V2 Three-tier RAG | previous replay | 62.0% | 74.0% | 42.4% | 36.9% | 43.1% | 67.5% | 60.0% | 18.6% |
| V3 Current production | live/current report | 62.0% | 76.0% | 38.3% | 35.0% | 42.9% | 67.2% | 70.8% | 20.0% |
| W2-W4 PPT architecture | live architecture adapter | 38.0% | 60.0% | 24.7% | 31.9% | 41.0% | 78.1% | 73.8% | 41.4% |

V0의 0점은 검색 성능 0이라는 뜻이 아니다. 현재 남아 있는 Chroma `smoke` 컬렉션에 `source=youtube` 문서가 0개라서 Gold 50을 엄밀히 재실행할 수 없다는 뜻이다.

### Cleanest Historical Comparison

| metric | V2 previous replay | V3 current | delta |
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

## Interpretation

### 좋아진 점

- `Must Hit@10`이 74.0%에서 76.0%로 올랐다.
- `Region Match@5`가 60.0%에서 70.8%로 크게 올랐다.
- 중복 place_id groups는 0이다.
- registered alias lookup success는 100.0%다.
- closed leakage와 non-serving leakage가 Gold top-10에서 0이다.
- repeat determinism은 100.0%다.

### 나빠진 점

- `Canonical MRR@10`이 42.4%에서 38.3%로 내려갔다.
- `NDCG@5`가 36.9%에서 35.0%로 내려갔다.
- 즉 대표 정답 또는 고품질 후보가 top-5 상단에 배치되는 힘은 약해졌다.
- `Forbidden Exposure@5`가 18.6%에서 20.0%로 나빠졌다.

### 핵심 해석

V3는 데이터 정본화와 운영 안정성은 좋아졌지만, 추천 랭킹 자체는 아직 충분히 좋아졌다고 보기 어렵다. 특히 top-10 안에는 더 잘 들어오지만, 1~5위 정렬은 V2보다 살짝 약하다.

## Version-by-version Performance Read

| version | 성능 변화 요약 |
|---|---|
| V0 | 검색 가능한 데이터가 부족했다. Goldset 비교 기준이 아직 없다. |
| V1 | 블로그 보강으로 정보 밀도가 크게 올라갔다. 검색 후보 풀을 넓힌 버전이다. |
| V2 | name/region/condition 분기로 실제 검색 시스템 형태가 잡혔다. Gold 50 기준 Must Hit@5 62.0%, Hit@10 74.0%. |
| V3 | canonical card와 deterministic server로 안정성이 좋아졌다. Hit@10과 region은 개선됐지만 MRR/NDCG는 소폭 하락했다. |

## Recommended Next Work

1. forbidden intent 필터를 검색 전/후 모두에 넣는다.
   - 예: “노키즈존 피하고”, “조용한”, “웨이팅 적은” 같은 질문에서 `노키즈존`, `혼잡가능`, `웨이팅` 노출을 강하게 감점한다.

2. top-5 reranker를 추가한다.
   - 현재는 top-10 회수율은 괜찮지만 상위 정렬이 약하다.
   - required tag, region, forbidden, must-like alias를 합친 deterministic rerank가 먼저다.

3. NDCG@5를 주 지표로 둔다.
   - Must Hit@5는 유지됐지만 NDCG@5가 내려갔기 때문에, 단순 정답 포함 여부보다 ranking quality를 봐야 한다.

4. V3 검색 결과의 실패 질문을 분해한다.
   - `Must Hit@10=0`
   - `NDCG@5 낮음`
   - `Forbidden@5 높음`
   - 이 세 그룹을 따로 보고 원인을 나눠야 한다.

## Source Reports

- `data/reports/rag_goldset_v2_evaluation.md`
- `data/reports/rag_goldset_v2_previous_replay.md`
- `data/reports/rag_goldset_v2_comparison.md`
- previous source replay: `stash@{0}^3:data/reports/rag_three_tier_evaluation.md`

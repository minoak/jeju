# Hybrid RAG Team Share

## Goal

Build a reproducible MVP search path that uses:

- Naver Blog RAG docs as the main recommendation evidence.
- YouTube support docs as weak corroborating evidence.
- A hybrid embedding seed that teammates can embed into Chroma or another vector DB.

No raw source data is edited by this flow.

## Current Inputs

| File | Role |
|---|---|
| `data/processed/네이버 정제.jsonl` | Preprocessed Naver Blog source used to build Naver RAG docs. |
| `data/processed/유튜브 정제.json` | Preprocessed YouTube source used to build YouTube support docs. |
| `data/processed/naver_rag_docs.jsonl` | Main RAG docs from Naver Blog summaries. |
| `data/processed/youtube_rag_support_docs.jsonl` | Cafe-level YouTube support docs grouped from `유튜브 정제.json`. |
| `data/processed/naver_tag_aliases.json` | Query/tag alias dictionary used by the baseline search. |

## Build Steps

Run from repo root:

```powershell
python pipeline/naver_mvp_rag/build_naver_rag_docs.py
python pipeline/youtube_support/build_youtube_support_docs.py
python rag/hybrid_rag_test.py
python rag/build_hybrid_embedding_seed.py
```

Outputs:

| File | Role |
|---|---|
| `data/processed/naver_rag_docs.jsonl` | Generated Naver RAG docs. |
| `data/processed/youtube_rag_support_docs.jsonl` | Generated YouTube support docs. |
| `data/reports/youtube_rag_support_report.md` | YouTube support doc build report. |
| `data/reports/hybrid_rag_test_report.md` | String baseline hybrid search test report. |
| `data/rag/hybrid_embedding_seed.jsonl` | Final seed for embedding. |
| `data/rag/hybrid_manifest.json` | Seed counts and source mix. |

## Seed Schema

Each row in `data/rag/hybrid_embedding_seed.jsonl` has:

```json
{
  "id": "hybrid_xxx",
  "text": "embedding target text",
  "metadata": {
    "cafe_name": "...",
    "normalized_name": "...",
    "source_types": ["naver_blog", "youtube"],
    "has_naver": true,
    "has_youtube": true,
    "tags": ["감성", "오션뷰"],
    "caution": ["주차"]
  },
  "collection": "jeju_cafe_hybrid",
  "source": "data/processed/naver_rag_docs.jsonl + data/processed/youtube_rag_support_docs.jsonl"
}
```

Recommended public-service filter:

```text
metadata.has_naver == true
```

This keeps Naver Blog evidence as the primary recommendation basis while still using YouTube text when available.

## Baseline Search Result

Latest run with the new YouTube support docs:

- Naver docs: 963
- YouTube support docs: 1062
- Name-merged candidate count: 957
- Naver+YouTube matched candidates: 857
- 10/10 default test questions returned top-5 results.

## Design Notes

- `source_keywords` from YouTube are kept in `support_text`, but they are not used to create `support_tags`.
- `주차`, `노키즈존`, and similar operational signals are kept as `caution`.
- Existing source data is read-only in this flow.
- The current search test is a string baseline. Embedding/rerank should be the next step after reviewing the seed quality.

## Next Step

Embed `data/rag/hybrid_embedding_seed.jsonl` into a new Chroma collection, for example `jeju_cafe_hybrid`, then compare retrieval against `data/reports/hybrid_rag_test_report.md`.

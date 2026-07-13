# Goldset V2 All-version Evaluation

Same Gold 50 rubric, different comparability modes. V0 is a runnability check because surviving youtube-only Chroma docs are missing, V2 is a replay, V3 and W2-W4 are live paths.

| version | mode | Must Hit@5 | Must Hit@10 | Canonical MRR@10 | NDCG@5 | NDCG@10 | Semantic Tag Match@5 | Semantic Tag Coverage@5 | Region Match@5 | Forbidden Exposure@5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 YouTube-only prototype | not runnable: source=youtube docs missing | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| V1 Hybrid seed RAG | live seed adapter | 42.0% | 50.0% | 24.1% | 29.7% | 37.7% | 74.8% | 93.3% | 38.5% | 24.3% |
| V2 Three-tier RAG | previous replay | 62.0% | 74.0% | 42.4% | 36.9% | 43.1% | 67.5% | 90.7% | 60.0% | 18.6% |
| V3 Current production | current report | 62.0% | 76.0% | 38.3% | 35.0% | 42.9% | 67.2% | 90.7% | 70.8% | 20.0% |
| W2-W4 PPT architecture | live adapter | 38.0% | 60.0% | 24.7% | 31.9% | 41.0% | 78.1% | 90.3% | 73.8% | 41.4% |

## Read

- V0 is not strictly comparable: the surviving Chroma collection has 0 `source=youtube` documents, so the row is a coverage/runnability check, not a performance score.
- V1 measures the hybrid seed corpus directly, so it tests seed quality more than the later production search stack.
- V2 and V3 are the cleanest historical comparison: previous replay vs current production.
- W2-W4 is the PPT architecture candidate path. It should be compared against V3 before promotion.
- Use NDCG@5 and Forbidden Exposure@5 as the main go/no-go metrics for architecture changes.

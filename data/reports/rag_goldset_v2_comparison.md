# RAG Goldset V2 Comparison

Previous RAG is evaluated by replaying the recorded top-10 results from `rag_three_tier_evaluation.md`. Current RAG uses the latest `rag_goldset_v2_evaluation.md` run.

| metric | previous replay | current | delta |
|---|---:|---:|---:|
| Must Hit@5 | 62.0% | 62.0% | +0.0% |
| Must Hit@10 | 74.0% | 76.0% | +2.0% |
| Canonical MRR@10 | 42.4% | 38.3% | -4.1% |
| NDCG@5 | 36.9% | 35.0% | -1.9% |
| NDCG@10 | 43.1% | 42.9% | -0.2% |
| Semantic Tag Match@5 | 67.5% | 67.2% | -0.3% |
| Semantic Tag Coverage@5 | 90.7% | 90.7% | +0.0% |
| Region Match@5 | 60.0% | 70.8% | +10.8% |
| Forbidden Exposure@5 | 18.6% | 20.0% | +1.4% |

## Read

- Current RAG keeps Must Hit@5 flat but improves Must Hit@10 slightly.
- NDCG is lower on current RAG, so representative or highly relevant cafes are less consistently ranked at the very top.
- Semantic tag scores are effectively flat, with a tiny decrease on current RAG.
- Forbidden exposure is worse on current RAG and should be treated as the highest-priority retrieval/rerank issue.

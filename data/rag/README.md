# Jeju Cafe Chroma Seed

This folder contains the RAG seed docs generated only from:

```text
data/share/jeju_cafe_pipeline_share.json
```

Files:

- `jeju_cafe_public.jsonl`: public recommendation docs, 410 rows.
- `jeju_cafe_review.jsonl`: internal review docs, 58 rows.
- `manifest.json`: source and document-count manifest.
- `hybrid_embedding_seed.jsonl`: Naver Blog + YouTube support seed docs for hybrid RAG experiments.
- `hybrid_manifest.json`: source mix and count manifest for the hybrid seed.

Build local Chroma embeddings:

```bash
python pipeline/embed.py
```

The Chroma persistent directory is:

```text
chroma_db/
```

`chroma_db/` is generated locally and is intentionally ignored by git. Team members can rebuild it from the checked-in JSONL seed files.

Hybrid RAG experiment seed:

```bash
python rag/build_hybrid_embedding_seed.py
```

See:

```text
docs/hybrid_rag_team_share.md
```

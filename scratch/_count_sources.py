# -*- coding: utf-8 -*-
"""chroma_smoke 소스별 문서 수 확인 (읽기 전용)."""
import os
from collections import Counter

import chromadb

ROOT = os.path.dirname(os.path.abspath(__file__))
col = chromadb.PersistentClient(path=os.path.join(ROOT, "chroma_smoke")).get_collection("smoke")
print("총 문서:", col.count())
metas = col.get(include=["metadatas"])["metadatas"]
print("소스별:", dict(Counter(m.get("source") for m in metas)))

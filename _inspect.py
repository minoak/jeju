# -*- coding: utf-8 -*-
import json, os
base = r"C:\Users\akals\Documents\GitHub\jeju\data"
files = [
    "processed/카페-전체자료.json",
    "processed/카페-변환.json",
    "processed/cafe_registry.json",
    "mock/cards.json",
    "golden/questions.json",
]
for f in files:
    p = os.path.join(base, f)
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("===", f, "| ERR:", repr(e)); print(); continue
    print("===", f, "| type:", type(d).__name__, "| len:", len(d) if hasattr(d, "__len__") else "-")
    s = d[0] if isinstance(d, list) and d else d
    if isinstance(s, dict):
        print("keys:", list(s.keys()))
    else:
        print("sample:", str(s)[:200])
    print()

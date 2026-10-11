#!/usr/bin/env python3
"""Offline smoke helpers (no embedding API): BM25 on assembled search_text + vector NN."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
from build_api_catalog import search_text_from_record  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "retrieval"
QUERIES = [
    "flange with bolt holes",
    "boolean cut a hole",
    "fillet round edges on a solid",
    "revolve a profile to make a cup",
]


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 1]


def bm25_top(
    query: str,
    catalog: list[dict],
    docs_tok: list[list[str]],
    df: dict[str, int],
    avgdl: float,
    k: int = 5,
) -> list[tuple[float, dict]]:
    n = len(catalog)
    k1, b = 1.5, 0.75
    q = tokenize(query)
    scores: list[float] = []
    for toks in docs_tok:
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        dl = len(toks) or 1
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            freq = tf[term]
            score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
        scores.append(score)
    idx = sorted(range(n), key=lambda i: -scores[i])[:k]
    return [(scores[i], catalog[i]) for i in idx]


def neighbors(
    matrix: np.ndarray,
    catalog: list[dict],
    doc_id: str,
    k: int = 5,
) -> list[tuple[float, dict]]:
    ids = {row["id"]: i for i, row in enumerate(catalog)}
    i = ids[doc_id]
    vec = matrix[i]
    vec = vec / max(float(np.linalg.norm(vec)), 1e-12)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    sims = (matrix / np.maximum(norms, 1e-12)) @ vec
    out: list[tuple[float, dict]] = []
    for j in np.argsort(-sims):
        j = int(j)
        if j == i:
            continue
        out.append((float(sims[j]), catalog[j]))
        if len(out) >= k:
            break
    return out


def main() -> int:
    catalog = [
        json.loads(line)
        for line in (ROOT / "catalog.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matrix = np.load(ROOT / "embeddings.npy")
    docs_tok = [tokenize(search_text_from_record(row)) for row in catalog]
    df: dict[str, int] = {}
    for toks in docs_tok:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    avgdl = sum(len(toks) for toks in docs_tok) / len(docs_tok)

    print("=== Offline lexical Top-5 (BM25; no embedding API) ===")
    for query in QUERIES:
        print(f"\nQuery: {query!r}")
        for rank, (score, row) in enumerate(
            bm25_top(query, catalog, docs_tok, df, avgdl),
            start=1,
        ):
            print(
                f"  {rank}. {score:.4f}  {row['id']}  [{row['agent_priority']}]  "
                f"{row['doc_category']}  tags={row['capability_tags']}"
            )

    print("\n=== Offline vector locality (NN of gold docs in embeddings.npy) ===")
    for gold in (
        "make_n_hole_flange_rsolid",
        "cut_rsolid",
        "fillet_rsolid",
        "revolve_rsolid",
    ):
        print(f"\nNeighbors of {gold}")
        for rank, (score, row) in enumerate(neighbors(matrix, catalog, gold), start=1):
            print(
                f"  {rank}. {score:.4f}  {row['id']}  [{row['agent_priority']}]  "
                f"tags={row['capability_tags']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

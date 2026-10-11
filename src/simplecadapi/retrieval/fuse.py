"""Normalize and fuse vector + BM25 scores."""

from __future__ import annotations

from typing import Sequence

import numpy as np

VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4


def min_max_normalize(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return arr
    lo = float(arr.min())
    hi = float(arr.max())
    if hi - lo < 1e-12:
        # All equal: keep zeros if already zero, else ones (signal present).
        if hi <= 0.0:
            return np.zeros_like(arr)
        return np.ones_like(arr)
    return (arr - lo) / (hi - lo)


def fuse_scores(
    score_vec: Sequence[float],
    score_bm25: Sequence[float],
    *,
    vector_weight: float = VECTOR_WEIGHT,
    bm25_weight: float = BM25_WEIGHT,
) -> np.ndarray:
    """score = w_v * norm(vec) + w_b * norm(bm25)."""
    v = min_max_normalize(score_vec)
    b = min_max_normalize(score_bm25)
    if v.shape != b.shape:
        raise ValueError(
            f"score length mismatch: vec={v.shape[0]} bm25={b.shape[0]}"
        )
    return vector_weight * v + bm25_weight * b

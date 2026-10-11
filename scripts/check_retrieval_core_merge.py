#!/usr/bin/env python3
"""Smoke-check Steps 1–2: ApiHit contract + core merge (no ranking yet)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simplecadapi.retrieval import (  # noqa: E402
    RETRIEVE_TOP_K,
    hit_from_catalog_row,
    load_catalog,
    merge_core_and_ranked,
    select_core_hits,
)


def main() -> int:
    catalog = load_catalog()
    core = select_core_hits(catalog)
    print(f"RETRIEVE_TOP_K={RETRIEVE_TOP_K}")
    print(f"catalog={len(catalog)}  core={len(core)}")
    print("core ids:")
    for hit in core:
        print(f"  - {hit.id}  reason={hit.reason}  pri={hit.agent_priority}")

    # Pretend ranked filler with distinct scores; core gets varied scores.
    core_scored = [
        hit_from_catalog_row(
            next(r for r in catalog if r["id"] == h.id),
            score=0.5 - i * 0.01,
            reason="core",
        )
        for i, h in enumerate(core)
    ]
    ranked = []
    core_ids = {h.id for h in core}
    fill_score = 0.9
    for row in catalog:
        if row["id"] in core_ids:
            continue
        if row.get("agent_priority") == "low":
            continue
        ranked.append(
            hit_from_catalog_row(row, score=fill_score, reason="fused"),
        )
        fill_score -= 0.05
        if len(ranked) >= 15:
            break

    merged = merge_core_and_ranked(core_scored, ranked, top_k=RETRIEVE_TOP_K)
    print(f"merged_len={len(merged)} (expect {RETRIEVE_TOP_K})")
    print("merged order (score desc):")
    for hit in merged:
        print(f"  {hit.score:5.2f}  [{hit.reason}]  {hit.id}")
    assert len(core) >= 1
    assert all(h.reason == "core" for h in core_scored)
    assert len(merged) == RETRIEVE_TOP_K, len(merged)
    assert {h.id for h in core}.issubset({h.id for h in merged})
    scores = [h.score for h in merged]
    assert scores == sorted(scores, reverse=True), scores
    # High-scoring fill can appear above lower-scoring core
    assert merged[0].reason == "fused"
    print("OK: contract + core membership + score order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

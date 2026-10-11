"""Core pack merge + truncate to RETRIEVE_TOP_K."""

from __future__ import annotations

import logging
from typing import Iterable, Mapping, Sequence

from .types import RETRIEVE_TOP_K, ApiHit, hit_from_catalog_row

logger = logging.getLogger(__name__)

_PRIORITY_TIE = {"core": 0, "normal": 1, "low": 2}


def select_core_hits(
    catalog: Sequence[Mapping],
    *,
    score: float = 1.0,
) -> list[ApiHit]:
    """Return hits for every catalog row with agent_priority == 'core'.

    Order follows catalog file order (stable). Duplicate ids are skipped.
    """
    hits: list[ApiHit] = []
    seen: set[str] = set()
    for row in catalog:
        if row.get("agent_priority") != "core":
            continue
        entry_id = str(row["id"])
        if entry_id in seen:
            continue
        seen.add(entry_id)
        hits.append(
            hit_from_catalog_row(row, score=score, reason="core"),
        )
    return hits


def sort_hits_by_score(hits: Sequence[ApiHit]) -> list[ApiHit]:
    """Highest relevance first; tie-break core > normal > low, then id."""
    return sorted(
        hits,
        key=lambda h: (
            -h.score,
            _PRIORITY_TIE.get(h.agent_priority, 3),
            h.id,
        ),
    )


def merge_core_and_ranked(
    core_hits: Sequence[ApiHit],
    ranked_hits: Sequence[ApiHit],
    *,
    top_k: int = RETRIEVE_TOP_K,
    sort_by_score: bool = True,
) -> list[ApiHit]:
    """Guarantee core pack membership, fill from ranked, optionally score-sort.

    Selection (membership):
    - Every core id is kept (unless core alone already exceeds top_k).
    - Remaining slots filled from ranked non-core (by ranked order / score).

    Presentation (order):
    - If ``sort_by_score`` (default), the final list is sorted by relevance
      descending so the model sees one coherent ranking — core items are
      *included*, not pinned as an alphabetical prefix.
    """
    if top_k <= 0:
        return []

    selected: list[ApiHit] = []
    seen: set[str] = set()

    for hit in core_hits:
        if hit.id in seen:
            continue
        selected.append(hit)
        seen.add(hit.id)
        if len(selected) >= top_k:
            break

    if len(selected) < top_k:
        for hit in ranked_hits:
            if hit.id in seen:
                continue
            selected.append(hit)
            seen.add(hit.id)
            if len(selected) >= top_k:
                break

    if len(selected) < top_k:
        logger.warning(
            "retrieve merge produced %s hits (< top_k=%s); "
            "catalog may be incomplete or filters too aggressive",
            len(selected),
            top_k,
        )

    if sort_by_score:
        return sort_hits_by_score(selected)
    return selected


def merge_core_with_catalog_ranked_rows(
    catalog: Sequence[Mapping],
    ranked_rows: Iterable[tuple[Mapping, float, str]],
    *,
    top_k: int = RETRIEVE_TOP_K,
    sort_by_score: bool = True,
) -> list[ApiHit]:
    """Convenience: core from catalog + ranked (row, score, reason) tuples."""
    core = select_core_hits(catalog)
    ranked = [
        hit_from_catalog_row(row, score=score, reason=reason)
        for row, score, reason in ranked_rows
    ]
    return merge_core_and_ranked(
        core,
        ranked,
        top_k=top_k,
        sort_by_score=sort_by_score,
    )

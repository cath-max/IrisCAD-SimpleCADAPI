"""Post-fuse industrial boosts / demotions (priority, boolean, thin bridges)."""

from __future__ import annotations

import re
from typing import Mapping, Sequence

import numpy as np

# Strong demotion for assembly/sketch/toolchain noise unless query asks for it.
LOW_PRIORITY_MULTIPLIER = 0.12
BOOLEAN_RSOLID_BONUS = 0.08
MUG_BRIDGE_BONUS = 0.14

_LOW_ALLOW_RE = re.compile(
    r"\b(assembly|assemblies|sketch|sketches|constraint|freecad|ql\b)\b",
    re.I,
)
_MUG_RE = re.compile(r"\b(mug|cup|杯子|马克杯|茶杯|水杯)\b", re.I)

# Thin spoken-language → engineering API bridge (not a synonym mega-table).
_MUG_BOOST_IDS: frozenset[str] = frozenset(
    {
        "revolve_rsolid",
        "make_cylinder_rsolid",
        "fillet_rsolid",
        "cut_rsolid",
        "extrude_rsolid",
        "shell_rsolid",
        "make_box_rsolid",
    }
)
# Tags only — keep narrow; do NOT include broad "primitive" (pulls 2d/assembly).
_MUG_BOOST_TAGS: frozenset[str] = frozenset({"revolve", "fillet"})


def query_allows_low_priority(query: str) -> bool:
    return bool(_LOW_ALLOW_RE.search(query))


def apply_boosts(
    fused: Sequence[float],
    catalog: Sequence[Mapping],
    query: str,
    *,
    low_multiplier: float = LOW_PRIORITY_MULTIPLIER,
    boolean_bonus: float = BOOLEAN_RSOLID_BONUS,
    mug_bonus: float = MUG_BRIDGE_BONUS,
) -> np.ndarray:
    """Return adjusted scores (same length as catalog / fused)."""
    scores = np.asarray(fused, dtype=np.float64).copy()
    if scores.shape[0] != len(catalog):
        raise ValueError(
            f"boost length mismatch: scores={scores.shape[0]} "
            f"catalog={len(catalog)}"
        )

    allow_low = query_allows_low_priority(query)
    mug = bool(_MUG_RE.search(query))

    for i, row in enumerate(catalog):
        entry_id = str(row["id"])
        priority = str(row.get("agent_priority") or "normal")
        tags = {str(t) for t in (row.get("capability_tags") or [])}

        if priority == "low" and not allow_low:
            scores[i] *= low_multiplier

        if "boolean" in tags and "_rsolid" in entry_id:
            scores[i] += boolean_bonus

        if mug:
            if entry_id in _MUG_BOOST_IDS:
                scores[i] += mug_bonus
            elif tags & _MUG_BOOST_TAGS:
                scores[i] += mug_bonus * 0.5
            elif "boolean" in tags and "_rsolid" in entry_id:
                scores[i] += mug_bonus * 0.5

    return scores

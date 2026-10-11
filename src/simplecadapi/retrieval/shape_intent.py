"""Small, deterministic shape cues for choosing related profile producers."""

from __future__ import annotations

from typing import Literal, Sequence

ProfileShape = Literal["circle", "rectangle", "polygon"]

_SHAPE_CUES: dict[ProfileShape, tuple[str, ...]] = {
    "circle": (
        "circle",
        "circular",
        "round",
        "cylinder",
        "cylindrical",
        "bore",
        "diameter",
        "opening",
        "圆形",
        "圆柱",
        "圆孔",
        "直径",
    ),
    "rectangle": (
        "rectangle",
        "rectangular",
        "block",
        "box",
        "square",
        "矩形",
        "长方形",
        "方形",
    ),
    "polygon": (
        "polygon",
        "polygonal",
        "polyline",
        "outline",
        "多边形",
        "轮廓",
    ),
}


def profile_shape_intent(query: str) -> ProfileShape | None:
    """Return one unambiguous requested profile shape, if the query states one."""
    normalized = query.casefold()
    matched = {
        shape
        for shape, cues in _SHAPE_CUES.items()
        if any(cue in normalized for cue in cues)
    }
    return next(iter(matched)) if len(matched) == 1 else None


def workflow_shape_rank(
    workflow_api_ids: Sequence[str],
    shape: ProfileShape | None,
) -> int:
    """Rank matching profile workflows ahead of neutral and conflicting ones."""
    if shape is None:
        return 1

    api_ids = " ".join(workflow_api_ids)
    matching_token = {
        "circle": "circle",
        "rectangle": "rectangle",
        "polygon": "polyline",
    }[shape]
    conflicting_tokens = {
        "circle": ("rectangle", "polyline"),
        "rectangle": ("circle", "polyline"),
        "polygon": ("circle", "rectangle"),
    }[shape]
    if matching_token in api_ids:
        return 0
    if any(token in api_ids for token in conflicting_tokens):
        return 2
    return 1


__all__ = ["ProfileShape", "profile_shape_intent", "workflow_shape_rank"]

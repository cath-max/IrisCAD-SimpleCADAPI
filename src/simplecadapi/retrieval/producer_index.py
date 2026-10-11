"""Startup-built lookup from geometry result types to producer API ids."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .signature_types import GEOMETRY_TYPES


def build_producer_index(catalog: Sequence[Mapping]) -> dict[str, tuple[str, ...]]:
    """Build a stable geometry type -> producer API id index from catalog rows."""
    producers: dict[str, list[str]] = {}
    for row in catalog:
        api_id = str(row["id"])
        for geometry_type in row.get("return_types") or ():
            if geometry_type not in GEOMETRY_TYPES:
                continue
            producers.setdefault(geometry_type, []).append(api_id)
    return {
        geometry_type: tuple(api_ids)
        for geometry_type, api_ids in producers.items()
    }


def validate_catalog_api_ids(catalog: Sequence[Mapping], api_ids: Iterable[str]) -> None:
    """Raise a clear error when a related-API configuration names a missing API."""
    catalog_ids = {str(row["id"]) for row in catalog}
    missing_ids = sorted(set(api_ids) - catalog_ids)
    if missing_ids:
        raise ValueError(
            "Related API configuration references missing catalog ids: "
            + ", ".join(missing_ids)
        )


__all__ = ["build_producer_index", "validate_catalog_api_ids"]

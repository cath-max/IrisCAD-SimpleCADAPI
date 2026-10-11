"""Assemble BM25 document text from catalog atomic fields.

Mirrors scripts/build_api_catalog.build_search_text — derived strings are
not stored in catalog.jsonl; built when the BM25 index is constructed.
"""

from __future__ import annotations

from typing import Mapping, Sequence


def build_search_text(
    *,
    symbol: str,
    signature: str | None,
    description: str,
    doc_category: str,
    import_surface: str | None,
    capability_tags: Sequence[str],
) -> str:
    parts = [
        f"symbol: {symbol}",
        f"category: {doc_category}",
    ]
    if capability_tags:
        parts.append(f"tags: {', '.join(capability_tags)}")
    if import_surface:
        parts.append(f"import: {import_surface}")
    if signature:
        parts.append(signature)
    if description:
        parts.append(description)
    return "\n".join(parts)


def search_text_from_record(record: Mapping) -> str:
    return build_search_text(
        symbol=str(record["symbol"]),
        signature=record.get("signature"),
        description=str(record.get("description") or ""),
        doc_category=str(record["doc_category"]),
        import_surface=record.get("import_surface"),
        capability_tags=list(record.get("capability_tags") or []),
    )

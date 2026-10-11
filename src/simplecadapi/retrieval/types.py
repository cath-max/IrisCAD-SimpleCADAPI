"""Retrieval result contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

# Final list length for one retrieve() call (core pack + ranked fills).
RETRIEVE_TOP_K = 20


@dataclass(frozen=True)
class ApiHit:
    """One API doc selected for the agent context."""

    id: str
    symbol: str
    path: str
    score: float
    agent_priority: str
    capability_tags: tuple[str, ...] = field(default_factory=tuple)
    reason: str = "fused"  # core | vector | bm25 | fused | forced | related:<consumer>:<role>
    body_markdown: str = ""
    doc_category: str = ""
    signature: str | None = None
    import_surface: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def hit_from_catalog_row(
    row: Mapping[str, Any],
    *,
    score: float = 0.0,
    reason: str = "fused",
    body_markdown: str = "",
) -> ApiHit:
    """Build an ApiHit from one catalog.jsonl object (atomic fields)."""
    tags = row.get("capability_tags") or []
    return ApiHit(
        id=str(row["id"]),
        symbol=str(row.get("symbol") or row["id"]),
        path=str(row.get("path") or f"docs/api/{row['id']}.md"),
        score=float(score),
        agent_priority=str(row.get("agent_priority") or "normal"),
        capability_tags=tuple(str(t) for t in tags),
        reason=reason,
        body_markdown=body_markdown,
        doc_category=str(row.get("doc_category") or ""),
        signature=row.get("signature"),
        import_surface=row.get("import_surface"),
        description=str(row.get("description") or ""),
    )

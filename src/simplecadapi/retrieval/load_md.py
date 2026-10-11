"""Load full API markdown bodies by catalog path."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .types import ApiHit


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_doc_path(path: str, *, repo_root: Path | None = None) -> Path:
    root = repo_root or default_repo_root()
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def read_api_markdown(path: str, *, repo_root: Path | None = None) -> str:
    doc = resolve_doc_path(path, repo_root=repo_root)
    if not doc.is_file():
        raise FileNotFoundError(f"API doc not found: {doc}")
    return doc.read_text(encoding="utf-8")


def attach_bodies(
    hits: Sequence[ApiHit],
    *,
    repo_root: Path | None = None,
) -> list[ApiHit]:
    """Return new hits with body_markdown filled (frozen dataclass)."""
    out: list[ApiHit] = []
    for hit in hits:
        body = ""
        try:
            body = read_api_markdown(hit.path, repo_root=repo_root)
        except FileNotFoundError:
            body = f"<!-- missing doc: {hit.path} -->"
        out.append(
            ApiHit(
                id=hit.id,
                symbol=hit.symbol,
                path=hit.path,
                score=hit.score,
                agent_priority=hit.agent_priority,
                capability_tags=hit.capability_tags,
                reason=hit.reason,
                body_markdown=body,
                doc_category=hit.doc_category,
                signature=hit.signature,
                import_surface=hit.import_surface,
                description=hit.description,
            )
        )
    return out


def format_api_prompt_slice(
    hits: Sequence[ApiHit],
    *,
    include_body: bool = True,
    max_body_chars: int | None = None,
) -> str:
    """Assemble a markdown slice suitable for an agent system prompt."""
    parts: list[str] = [
        "# Retrieved SimpleCADAPI reference",
        "",
        f"Selected {len(hits)} APIs (core pack included, score-ranked).",
        "",
    ]
    for i, hit in enumerate(hits, start=1):
        parts.append(f"## {i}. `{hit.symbol}` (`{hit.id}`)")
        parts.append(
            f"- priority: `{hit.agent_priority}` · reason: `{hit.reason}` · "
            f"score: `{hit.score:.4f}`"
        )
        if hit.capability_tags:
            parts.append(f"- tags: {', '.join(hit.capability_tags)}")
        if hit.signature:
            parts.append(f"- signature: `{hit.signature}`")
        if hit.description:
            parts.append(f"- summary: {hit.description}")
        parts.append(f"- path: `{hit.path}`")
        if include_body and hit.body_markdown:
            body = hit.body_markdown
            if max_body_chars is not None and len(body) > max_body_chars:
                body = body[: max_body_chars - 1].rstrip() + "…"
            parts.append("")
            parts.append(body)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def catalog_row_by_id(catalog: Sequence[Mapping], entry_id: str) -> Mapping | None:
    for row in catalog:
        if str(row["id"]) == entry_id:
            return row
    return None

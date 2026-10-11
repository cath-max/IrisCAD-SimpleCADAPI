#!/usr/bin/env python3
"""Parse docs/api/*.md + README categories into retrieval/catalog.jsonl.

Persists atomic catalog fields only. Derived strings for BM25 / embedding
(`search_text`, `embedding_text`) are NOT stored — call
`build_search_text` / `build_embedding_text` (or the `*_from_record`
helpers) when building the retrieval index offline / at process startup.
See retrieval/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from api_capability_rules import (  # noqa: E402
    derive_agent_priority,
    derive_capability_tags,
    industrial_cues_for_tags,
)
from simplecadapi.retrieval.signature_types import parse_signature_types  # noqa: E402
API_DIR = PROJECT_ROOT / "docs" / "api"
README_PATH = API_DIR / "README.md"
DEFAULT_OUT = PROJECT_ROOT / "retrieval" / "catalog.jsonl"

HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
README_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
README_LINK_RE = re.compile(
    r"^\s*-\s*\[([^\]]+)\]\(([^)]+\.md)\)",
    re.MULTILINE,
)
CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _section_body(markdown: str, section_title: str) -> str | None:
    """Return text under ## section_title until the next ## (exclusive)."""
    pattern = re.compile(
        rf"^##\s+{re.escape(section_title)}\s*$",
        re.MULTILINE,
    )
    match = pattern.search(markdown)
    if not match:
        return None
    start = match.end()
    next_h2 = SECTION_RE.search(markdown, start)
    end = next_h2.start() if next_h2 else len(markdown)
    return markdown[start:end].strip()


def parse_readme_categories(readme_text: str) -> dict[str, str]:
    """Map basename (e.g. make_box_rsolid.md) -> README ## section name."""
    mapping: dict[str, str] = {}
    current_section: str | None = None
    for line in readme_text.splitlines():
        h2 = README_H2_RE.match(line)
        if h2:
            current_section = h2.group(1).strip()
            continue
        link = README_LINK_RE.match(line)
        if link and current_section:
            href = link.group(2).strip()
            # README links are usually bare filenames under docs/api/
            name = Path(href).name
            mapping[name] = current_section
    return mapping


def parse_symbol(markdown: str, fallback_id: str) -> str:
    match = HEADING_RE.search(markdown)
    if match:
        return match.group(1).strip()
    return fallback_id


def parse_signature(markdown: str) -> str | None:
    for title in ("API Definition", "Class Definition"):
        body = _section_body(markdown, title)
        if not body:
            continue
        block = CODE_BLOCK_RE.search(body)
        if block:
            sig = block.group(1).strip()
            # Keep as a single logical signature; collapse excess blank lines.
            lines = [ln.rstrip() for ln in sig.splitlines() if ln.strip()]
            return "\n".join(lines) if lines else None
    return None


def parse_import_surface(markdown: str) -> str | None:
    body = _section_body(markdown, "Import Surface")
    if not body:
        return None
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        # "- top-level: `from ...`" or "- submodule: ..."
        content = stripped.lstrip("-").strip()
        if ":" in content:
            label = content.split(":", 1)[0].strip()
            if label:
                return label
        return content or None
    return None


def parse_description(markdown: str, max_chars: int = 1200) -> str:
    body = _section_body(markdown, "Description")
    if not body:
        return ""
    # Drop nested ### subsections' deep detail for catalog summary fields;
    # keep everything until first ### if present for a short overview.
    sub = re.search(r"^###\s+", body, re.MULTILINE)
    if sub:
        body = body[: sub.start()].strip()
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > max_chars:
        return body[: max_chars - 1].rstrip() + "…"
    return body


def parse_usage(markdown: str, max_chars: int = 1200) -> str:
    """Return the short natural-language API usage cue for embedding input."""
    body = _section_body(markdown, "Usage")
    if not body:
        return ""
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > max_chars:
        return body[: max_chars - 1].rstrip() + "…"
    return body


def build_search_text(
    *,
    symbol: str,
    signature: str | None,
    description: str,
    doc_category: str,
    import_surface: str | None,
    capability_tags: list[str],
) -> str:
    """Assemble BM25 document text from atomic fields (not persisted in jsonl)."""
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


def build_embedding_text(
    *,
    symbol: str,
    signature: str | None,
    description: str,
    doc_category: str,
    capability_tags: list[str],
    usage: str = "",
) -> str:
    """Assemble embedding input text from atomic fields (not persisted in jsonl)."""
    lines = [
        f"API: {symbol}",
        f"Category: {doc_category}",
    ]
    if capability_tags:
        lines.append(f"Tags: {', '.join(capability_tags)}")
    if signature:
        lines.append(f"Signature: {signature}")
    if description:
        lines.append(f"Summary: {description}")
    if usage:
        lines.append(f"Usage: {usage}")
    cues = industrial_cues_for_tags(capability_tags)
    if cues:
        lines.append(f"Industrial cues: {cues}")
    return "\n".join(lines)


def search_text_from_record(record: dict) -> str:
    """Index-build helper: BM25 string for one catalog row."""
    return build_search_text(
        symbol=record["symbol"],
        signature=record.get("signature"),
        description=record.get("description") or "",
        doc_category=record["doc_category"],
        import_surface=record.get("import_surface"),
        capability_tags=list(record.get("capability_tags") or []),
    )


def embedding_text_from_record(record: dict) -> str:
    """Index-build helper: embedding string for one catalog row."""
    return build_embedding_text(
        symbol=record["symbol"],
        signature=record.get("signature"),
        description=record.get("description") or "",
        doc_category=record["doc_category"],
        capability_tags=list(record.get("capability_tags") or []),
        usage=record.get("usage") or "",
    )


def parse_api_file(
    path: Path,
    *,
    api_dir: Path,
    categories: dict[str, str],
) -> dict:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(api_dir.parent.parent).as_posix()  # docs/api/...
    file_id = path.stem
    symbol = parse_symbol(text, file_id)
    signature = parse_signature(text)
    import_surface = parse_import_surface(text)
    description = parse_description(text)
    usage = parse_usage(text)
    doc_category = categories.get(path.name, "Uncategorized")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    capability_tags = derive_capability_tags(
        symbol=symbol,
        doc_category=doc_category,
        import_surface=import_surface,
    )
    agent_priority = derive_agent_priority(
        record_id=file_id,
        symbol=symbol,
        doc_category=doc_category,
        import_surface=import_surface,
        capability_tags=capability_tags,
    )
    input_types, return_types = parse_signature_types(signature)

    # Atomic fields only — do not persist search_text / embedding_text.
    return {
        "id": file_id,
        "path": rel if rel.startswith("docs/") else f"docs/api/{path.name}",
        "symbol": symbol,
        "signature": signature,
        "input_types": input_types,
        "return_types": return_types,
        "import_surface": import_surface,
        "doc_category": doc_category,
        "description": description,
        "usage": usage,
        "capability_tags": capability_tags,
        "agent_priority": agent_priority,
        "content_sha256": digest,
    }


def build_catalog(
    *,
    api_dir: Path = API_DIR,
    readme_path: Path = README_PATH,
) -> list[dict]:
    if not api_dir.is_dir():
        raise FileNotFoundError(f"API docs directory not found: {api_dir}")
    readme_text = (
        readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    )
    categories = parse_readme_categories(readme_text)

    records: list[dict] = []
    for path in sorted(api_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        records.append(
            parse_api_file(path, api_dir=api_dir, categories=categories),
        )
    return records


def write_catalog_jsonl(records: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in records:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def summarize(records: list[dict]) -> dict:
    by_category: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    missing_sig = 0
    missing_import = 0
    uncategorized = 0
    for row in records:
        cat = row["doc_category"]
        by_category[cat] = by_category.get(cat, 0) + 1
        pri = row.get("agent_priority") or "unset"
        by_priority[pri] = by_priority.get(pri, 0) + 1
        for tag in row.get("capability_tags") or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if not row.get("signature"):
            missing_sig += 1
        if not row.get("import_surface"):
            missing_import += 1
        if cat == "Uncategorized":
            uncategorized += 1
    return {
        "doc_count": len(records),
        "categories": dict(sorted(by_category.items(), key=lambda x: (-x[1], x[0]))),
        "priorities": dict(sorted(by_priority.items())),
        "top_tags": dict(
            sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))[:20],
        ),
        "missing_signature": missing_sig,
        "missing_import_surface": missing_import,
        "uncategorized": uncategorized,
        "core_ids": sorted(
            r["id"] for r in records if r.get("agent_priority") == "core"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build retrieval/catalog.jsonl from docs/api (parse only).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSONL path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--api-dir",
        type=Path,
        default=API_DIR,
        help="docs/api directory",
    )
    args = parser.parse_args(argv)

    api_dir = args.api_dir.resolve()
    readme_path = api_dir / "README.md"
    records = build_catalog(api_dir=api_dir, readme_path=readme_path)
    write_catalog_jsonl(records, args.out.resolve())
    stats = summarize(records)

    print(f"Wrote {stats['doc_count']} records -> {args.out.resolve()}")
    print(f"Uncategorized: {stats['uncategorized']}")
    print(f"Missing signature: {stats['missing_signature']}")
    print(f"Missing import_surface: {stats['missing_import_surface']}")
    print("agent_priority:")
    for name, count in stats["priorities"].items():
        print(f"  {count:4d}  {name}")
    print("core ids:")
    for core_id in stats["core_ids"]:
        print(f"  - {core_id}")
    print("Top capability_tags:")
    for name, count in stats["top_tags"].items():
        print(f"  {count:4d}  {name}")
    print("Categories:")
    for name, count in stats["categories"].items():
        print(f"  {count:4d}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

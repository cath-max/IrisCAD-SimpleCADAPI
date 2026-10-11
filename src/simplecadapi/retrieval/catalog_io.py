"""Load retrieval/catalog.jsonl."""

from __future__ import annotations

import json
from pathlib import Path


def default_catalog_path() -> Path:
    """Repo-root retrieval/catalog.jsonl (…/src/simplecadapi/retrieval → parents[3])."""
    return Path(__file__).resolve().parents[3] / "retrieval" / "catalog.jsonl"


def load_catalog(path: Path | None = None) -> list[dict]:
    catalog_path = path or default_catalog_path()
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Catalog not found: {catalog_path}")
    rows: list[dict] = []
    with catalog_path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSONL at {catalog_path}:{line_no}: {exc}"
                ) from exc
    if not rows:
        raise ValueError(f"Catalog is empty: {catalog_path}")
    return rows

"""Contract tests for embedding-only API usage documentation cues."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_api_retrieval_index as index_builder  # noqa: E402
from build_api_catalog import (  # noqa: E402
    build_embedding_text,
    build_search_text,
    parse_description,
    parse_usage,
)


def test_usage_is_separate_from_description_and_bm25() -> None:
    markdown = """## Description

Create a solid by sweeping a profile along a path.

## Usage

Create a curved tube, pipe, duct, rail, or blade along a guide path.
"""
    description = parse_description(markdown)
    usage = parse_usage(markdown)

    assert description == "Create a solid by sweeping a profile along a path."
    assert usage == "Create a curved tube, pipe, duct, rail, or blade along a guide path."
    assert usage not in build_search_text(
        symbol="sweep_rsolid",
        signature=None,
        description=description,
        doc_category="3D Operations",
        import_surface="top-level",
        capability_tags=["solid", "sweep"],
    )
    assert usage in build_embedding_text(
        symbol="sweep_rsolid",
        signature=None,
        description=description,
        doc_category="3D Operations",
        capability_tags=["solid", "sweep"],
        usage=usage,
    )


def test_embedding_text_fingerprint_reembeds_changed_usage(monkeypatch) -> None:
    catalog = [
        {
            "id": "sweep_rsolid",
            "content_sha256": "same-doc-hash",
            "symbol": "sweep_rsolid",
            "signature": None,
            "description": "Create a solid by sweeping a profile along a path.",
            "usage": "Create a curved tube along a guide path.",
            "doc_category": "3D Operations",
            "capability_tags": ["solid", "sweep"],
        }
    ]
    state = {
        "model": "test-model",
        "ids": {
            "sweep_rsolid": {
                "row": 0,
                "content_sha256": "same-doc-hash",
                "embedding_text_sha256": "outdated-fingerprint",
            }
        },
    }
    monkeypatch.setattr(
        index_builder,
        "embed_batch",
        lambda **_kwargs: [[1.0, 2.0]],
    )

    matrix, new_state, stats = index_builder.build_embeddings(
        catalog=catalog,
        api_key="unused",
        base_url="unused",
        model="test-model",
        state=state,
        old_matrix=np.array([[3.0, 4.0]], dtype=np.float32),
        batch_size=1,
        force=False,
    )

    assert stats["reused"] == 0
    assert stats["embedded"] == 1
    assert matrix.tolist() == [[1.0, 2.0]]
    assert new_state["ids"]["sweep_rsolid"]["embedding_text_sha256"] != "outdated-fingerprint"


def test_load_state_reads_existing_json(tmp_path: Path) -> None:
    state_path = tmp_path / "embedding_state.json"
    state_path.write_text('{"model": "test-model", "ids": {}}', encoding="utf-8")

    assert index_builder.load_state(state_path) == {"model": "test-model", "ids": {}}

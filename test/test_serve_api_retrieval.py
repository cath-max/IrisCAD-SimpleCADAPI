"""HTTP sidecar request contracts for CADAM retrieval filters."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simplecadapi.retrieval import ApiRetriever, load_catalog  # noqa: E402


def _service_module():
    path = ROOT / "scripts" / "serve_api_retrieval.py"
    spec = importlib.util.spec_from_file_location("serve_api_retrieval_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_passes_exclude_ids_to_hybrid_retrieval() -> None:
    service = _service_module()
    catalog = load_catalog(ROOT / "retrieval" / "catalog.jsonl")
    service._ENGINE = ApiRetriever(
        catalog=catalog,
        embeddings=np.zeros((len(catalog), 1), dtype=np.float64),
        repo_root=ROOT,
    )
    service._USE_VECTOR_DEFAULT = False

    excluded = [
        "translate_model_json_to_freecad_script",
        "add_gear_constraint_rassembly",
    ]
    payload = service.handle_retrieve(
        {"query": "assembly gear fixture", "use_vector": False, "exclude_ids": excluded}
    )

    assert len(payload["hit_ids"]) == 20
    assert set(payload["hit_ids"]).isdisjoint(excluded)
    assert payload["exclude_ids"] == excluded


def test_sidecar_rejects_invalid_exclude_ids() -> None:
    service = _service_module()
    service._ENGINE = object()

    with pytest.raises(ValueError, match="exclude_ids"):
        service.handle_retrieve({"query": "fixture", "exclude_ids": ["valid", 1]})

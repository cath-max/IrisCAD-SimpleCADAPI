"""Regression contract for retrieval core merge and forced operations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simplecadapi.retrieval import (  # noqa: E402
    RETRIEVE_TOP_K,
    ApiRetriever,
    hit_from_catalog_row,
    load_catalog,
    merge_core_and_ranked,
    select_core_hits,
)
from simplecadapi.retrieval.shape_intent import (  # noqa: E402
    profile_shape_intent,
    workflow_shape_rank,
)
from simplecadapi.retrieval.expand import (  # noqa: E402
    ExpansionSeed,
    expand_related_apis,
)
from simplecadapi.retrieval.producer_index import build_producer_index  # noqa: E402


EXPECTED_CORE_IDS = {
    "make_box_rsolid",
    "make_cylinder_rsolid",
    "union_rsolid",
    "cut_rsolid",
    "extrude_rsolid",
    "revolve_rsolid",
}
BASELINE_RANKINGS_PATH = ROOT / "test" / "fixtures" / "retrieval" / "baseline_bm25_rankings.json"


def _catalog() -> list[dict]:
    return load_catalog(ROOT / "retrieval" / "catalog.jsonl")


def _scored_core(catalog: list[dict]):
    rows_by_id = {str(row["id"]): row for row in catalog}
    return [
        hit_from_catalog_row(rows_by_id[hit.id], score=0.5 - index * 0.01, reason="core")
        for index, hit in enumerate(select_core_hits(catalog))
    ]


def test_catalog_has_the_exact_six_core_apis() -> None:
    core_ids = {hit.id for hit in select_core_hits(_catalog())}

    assert core_ids == EXPECTED_CORE_IDS


def test_merge_keeps_core_returns_top_k_and_sorts_by_score() -> None:
    catalog = _catalog()
    core = _scored_core(catalog)
    core_ids = {hit.id for hit in core}
    ranked = [
        hit_from_catalog_row(row, score=0.9 - index * 0.01, reason="fused")
        for index, row in enumerate(catalog)
        if row["id"] not in core_ids and row.get("agent_priority") != "low"
    ]

    merged = merge_core_and_ranked(core, ranked, top_k=RETRIEVE_TOP_K)

    assert len(merged) == RETRIEVE_TOP_K
    assert core_ids.issubset({hit.id for hit in merged})
    assert [hit.score for hit in merged] == sorted(
        (hit.score for hit in merged), reverse=True
    )
    assert merged[0].reason == "fused"


def test_forced_operation_enters_result_and_evicts_only_non_core() -> None:
    catalog = _catalog()
    scores = np.arange(len(catalog), dtype=np.float64)
    retriever = ApiRetriever(
        catalog=catalog,
        embeddings=np.zeros((len(catalog), 1), dtype=np.float64),
        repo_root=ROOT,
    )
    retriever.score_query = lambda *_args, **_kwargs: scores  # type: ignore[method-assign]

    baseline = retriever.retrieve("fixture", load_bodies=False, use_vector=False)
    forced = retriever.retrieve(
        "fixture",
        load_bodies=False,
        use_vector=False,
        operation="make_spline_redge",
    )

    baseline_ids = {hit.id for hit in baseline}
    forced_ids = {hit.id for hit in forced}
    evicted_ids = baseline_ids - forced_ids

    assert len(baseline) == len(forced) == RETRIEVE_TOP_K
    assert "make_spline_redge" not in baseline_ids
    assert "make_spline_redge" in forced_ids
    assert EXPECTED_CORE_IDS.issubset(forced_ids)
    assert evicted_ids
    assert evicted_ids.isdisjoint(EXPECTED_CORE_IDS)
    assert next(hit for hit in forced if hit.id == "make_spline_redge").reason == "forced"


def test_excluded_ids_never_return_or_bypass_filter_as_forced_operation() -> None:
    catalog = _catalog()
    retriever = ApiRetriever(
        catalog=catalog,
        embeddings=np.zeros((len(catalog), 1), dtype=np.float64),
        repo_root=ROOT,
    )
    retriever.score_query = lambda *_args, **_kwargs: np.arange(  # type: ignore[method-assign]
        len(catalog), dtype=np.float64
    )
    excluded = {
        "translate_model_json_to_freecad_script",
        "add_gear_constraint_rassembly",
        "make_spline_redge",
    }

    hits = retriever.retrieve(
        "assembly gear fixture",
        load_bodies=False,
        use_vector=False,
        operation="make_spline_redge",
        exclude_ids=excluded,
    )

    hit_ids = {hit.id for hit in hits}
    assert len(hits) == RETRIEVE_TOP_K
    assert hit_ids.isdisjoint(excluded)
    assert EXPECTED_CORE_IDS.issubset(hit_ids)


def test_excluded_related_producer_is_not_reinserted_by_expansion() -> None:
    catalog = _catalog()
    scores = np.zeros(len(catalog), dtype=np.float64)
    scores[next(i for i, row in enumerate(catalog) if row["id"] == "loft_rsolid")] = 1.0
    scores[next(i for i, row in enumerate(catalog) if row["id"] == "make_circle_rwire")] = 0.5
    retriever = ApiRetriever(
        catalog=catalog,
        embeddings=np.zeros((len(catalog), 1), dtype=np.float64),
        repo_root=ROOT,
    )
    retriever.score_query = lambda *_args, **_kwargs: scores  # type: ignore[method-assign]

    hits = retriever.retrieve(
        "a tapered connector between two round openings",
        load_bodies=False,
        use_vector=False,
        exclude_ids={"make_circle_rwire"},
    )

    assert len(hits) == RETRIEVE_TOP_K
    assert "make_circle_rwire" not in {hit.id for hit in hits}


def test_ranked_non_core_keeps_normal_priority_ahead_of_low_on_score_ties() -> None:
    catalog = _catalog()
    retriever = ApiRetriever(
        catalog=catalog,
        embeddings=np.zeros((len(catalog), 1), dtype=np.float64),
        repo_root=ROOT,
    )

    ranked = retriever.ranked_non_core(np.zeros(len(catalog), dtype=np.float64))
    priorities = [hit.agent_priority for hit in ranked]

    assert "normal" in priorities
    assert "low" in priorities
    assert priorities.index("low") > max(
        index for index, priority in enumerate(priorities) if priority == "normal"
    )


def test_bm25_baseline_rankings_are_stable_when_related_expansion_is_disabled() -> None:
    expected = json.loads(BASELINE_RANKINGS_PATH.read_text(encoding="utf-8"))
    catalog = _catalog()
    retriever = ApiRetriever(
        catalog=catalog,
        embeddings=np.zeros((len(catalog), 1), dtype=np.float64),
        repo_root=ROOT,
        related_api_expansion_enabled=False,
    )

    for query, expected_ids in expected.items():
        hits = retriever.retrieve(query, load_bodies=False, use_vector=False)

        assert [hit.id for hit in hits] == expected_ids


def test_profile_shape_intent_prioritizes_matching_related_producers() -> None:
    assert profile_shape_intent("a round opening") == "circle"
    assert profile_shape_intent("a rectangular block with a bore") is None
    assert workflow_shape_rank(("make_circle_rface",), "circle") == 0
    assert workflow_shape_rank(("make_face_from_wire_rface",), "circle") == 1
    assert workflow_shape_rank(("make_rectangle_rface",), "circle") == 2


def test_explicit_loft_profile_shape_uses_one_matching_wire_producer() -> None:
    catalog = _catalog()
    candidates = expand_related_apis(
        (ExpansionSeed("loft_rsolid", 1.0, "ranked"),),
        catalog,
        np.zeros(len(catalog), dtype=np.float64),
        {str(row["id"]): index for index, row in enumerate(catalog)},
        build_producer_index(catalog),
        (),
        query="a tapered connector between two round openings",
        query_allows_low_priority=False,
    )

    assert [candidate.api_id for candidate in candidates] == ["make_circle_rwire"]

#!/usr/bin/env python3
"""Benchmark warm API retrieval without live embedding requests."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simplecadapi.retrieval.retrieve as retrieve_module  # noqa: E402
from simplecadapi.retrieval import ApiRetriever, RETRIEVE_TOP_K  # noqa: E402

QUERIES = (
    "curved tube following a smooth route",
    "tapered connector between round openings",
    "spring-shaped solid with a round wire cross-section",
    "round over selected edges with a 2 mm radius",
    "hollow box with an open top and 2 mm walls",
    "rectangular closed outline for a later feature",
)
VECTOR_SOURCE_IDS = (
    "sweep_rsolid",
    "loft_rsolid",
    "helical_sweep_rsolid",
    "fillet_rsolid",
    "shell_rsolid",
    "make_rectangle_rface",
)


def percentile_ms(samples_ns: Sequence[int], percentile: float) -> float:
    """Return a stable millisecond percentile for positive timing samples."""
    if not samples_ns:
        return 0.0
    return float(np.percentile(np.asarray(samples_ns, dtype=np.float64), percentile) / 1e6)


def summarize(samples_ns: Sequence[int]) -> dict[str, float | int]:
    return {
        "samples": len(samples_ns),
        "p50_ms": percentile_ms(samples_ns, 50),
        "p95_ms": percentile_ms(samples_ns, 95),
    }


def benchmark_pass(
    engine: ApiRetriever,
    *,
    queries: Sequence[str],
    query_vectors: Sequence[Sequence[float] | None],
    use_vector: bool,
    iterations: int,
    load_bodies: bool,
) -> dict[str, dict[str, float | int]]:
    """Time one warm retrieval pass while attributing public pipeline phases."""
    phase_ns: dict[str, list[int]] = defaultdict(list)

    def timed(name: str, func: Callable):
        def wrapped(*args, **kwargs):
            started = time.perf_counter_ns()
            try:
                return func(*args, **kwargs)
            finally:
                phase_ns[name].append(time.perf_counter_ns() - started)

        return wrapped

    original_score_query = engine.score_query
    original_expand = retrieve_module.expand_related_apis
    original_merge = retrieve_module.merge_core_and_ranked
    original_attach = retrieve_module.attach_bodies
    engine.score_query = timed("score", original_score_query)  # type: ignore[method-assign]
    retrieve_module.expand_related_apis = timed("expansion", original_expand)
    retrieve_module.merge_core_and_ranked = timed("merge", original_merge)
    retrieve_module.attach_bodies = timed("body_loading", original_attach)
    try:
        for _ in range(iterations):
            for query, query_vec in zip(queries, query_vectors):
                started = time.perf_counter_ns()
                hits = engine.retrieve(
                    query,
                    load_bodies=load_bodies,
                    use_vector=use_vector,
                    query_vec=query_vec,
                )
                phase_ns["total"].append(time.perf_counter_ns() - started)
                if len(hits) != RETRIEVE_TOP_K:
                    raise RuntimeError(f"expected {RETRIEVE_TOP_K} hits, got {len(hits)}")
    finally:
        engine.score_query = original_score_query  # type: ignore[method-assign]
        retrieve_module.expand_related_apis = original_expand
        retrieve_module.merge_core_and_ranked = original_merge
        retrieve_module.attach_bodies = original_attach

    return {name: summarize(samples) for name, samples in sorted(phase_ns.items())}


def local_query_vectors(engine: ApiRetriever) -> tuple[np.ndarray, ...]:
    """Use already-loaded document vectors so benchmark loops never call an API."""
    return tuple(
        engine.embeddings[engine._id_to_index[api_id]].copy()
        for api_id in VECTOR_SOURCE_IDS
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Warm offline API retrieval benchmark (no live query embeddings)."
    )
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--body-iterations", type=int, default=30)
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args(argv)
    if args.iterations < 1 or args.body_iterations < 1:
        parser.error("iterations must be positive")

    engine = ApiRetriever(repo_root=PROJECT_ROOT)
    vectors = local_query_vectors(engine)

    # Warm all code paths before collecting samples.
    benchmark_pass(
        engine,
        queries=QUERIES,
        query_vectors=(None,) * len(QUERIES),
        use_vector=False,
        iterations=1,
        load_bodies=False,
    )
    benchmark_pass(
        engine,
        queries=QUERIES,
        query_vectors=vectors,
        use_vector=True,
        iterations=1,
        load_bodies=False,
    )

    report = {
        "query_count": len(QUERIES),
        "iterations": args.iterations,
        "vector_source": "already-loaded catalog embedding rows; no live embedding requests",
        "bm25_only_no_body": benchmark_pass(
            engine,
            queries=QUERIES,
            query_vectors=(None,) * len(QUERIES),
            use_vector=False,
            iterations=args.iterations,
            load_bodies=False,
        ),
        "precomputed_vector_no_body": benchmark_pass(
            engine,
            queries=QUERIES,
            query_vectors=vectors,
            use_vector=True,
            iterations=args.iterations,
            load_bodies=False,
        ),
        "bm25_only_with_body": benchmark_pass(
            engine,
            queries=QUERIES,
            query_vectors=(None,) * len(QUERIES),
            use_vector=False,
            iterations=args.body_iterations,
            load_bodies=True,
        ),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for the offline retrieval benchmark helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bench_api_retrieval_offline import percentile_ms, summarize  # noqa: E402


def test_percentile_summary_uses_milliseconds() -> None:
    samples = [1_000_000, 2_000_000, 3_000_000]

    assert percentile_ms(samples, 50) == 2.0
    assert summarize(samples) == {"samples": 3, "p50_ms": 2.0, "p95_ms": 2.9}

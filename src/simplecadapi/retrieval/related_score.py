"""Deterministic scores for API producers related to a retrieved consumer."""

from __future__ import annotations

from dataclasses import dataclass

from .boost import LOW_PRIORITY_MULTIPLIER

PROPAGATION_WEIGHT = 0.20


@dataclass(frozen=True)
class RelatedScore:
    """Score components retained for later ranking diagnostics."""

    producer_query_score: float
    propagation_score: float
    final_score: float


def calculate_related_score(
    producer_query_score: float,
    seed_query_score: float,
    relation_weight: float,
    *,
    producer_priority: str,
    query_allows_low_priority: bool,
    propagation_weight: float = PROPAGATION_WEIGHT,
) -> RelatedScore:
    """Combine existing query scores with one semantic producer relationship.

    ``producer_query_score`` and ``seed_query_score`` must come from the same
    ``ApiRetriever.score_query`` result, so this calculation never embeds a
    query or invokes a model. The producer base score already includes the
    normal low-priority demotion; apply that same multiplier to propagation.
    """
    propagation_score = propagation_weight * seed_query_score * relation_weight
    if producer_priority == "low" and not query_allows_low_priority:
        propagation_score *= LOW_PRIORITY_MULTIPLIER
    return RelatedScore(
        producer_query_score=producer_query_score,
        propagation_score=propagation_score,
        final_score=producer_query_score + propagation_score,
    )


__all__ = ["PROPAGATION_WEIGHT", "RelatedScore", "calculate_related_score"]

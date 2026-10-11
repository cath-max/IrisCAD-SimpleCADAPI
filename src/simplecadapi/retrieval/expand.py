"""Choose which retrieved consumer APIs may trigger related expansion."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Mapping, Sequence

from .related_score import RelatedScore, calculate_related_score
from .relations import RELATIONS_BY_CONSUMER
from .shape_intent import profile_shape_intent, workflow_shape_rank
from .types import ApiHit

CORE_TRIGGER_SCORE = 0.20
NON_CORE_TRIGGER_SCORE = 0.0
MAX_RELATED_APIS = 4
MAX_EXPANSION_DEPTH = 2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpansionSeed:
    """A related-API consumer admitted from the pre-expansion result set."""

    consumer_id: str
    score: float
    reason: str


@dataclass(frozen=True)
class ExpandedCandidate:
    """One producer selected through a semantic consumer input role."""

    api_id: str
    score: float
    reason: str
    depth: int
    workflow_api_ids: tuple[str, ...]
    producer_query_score: float
    seed_score: float
    relation_weight: float
    propagation_score: float


def select_expansion_seeds(
    pre_expansion_hits: Sequence[ApiHit],
    query_scores: Sequence[float],
    id_to_index: Mapping[str, int],
    *,
    core_trigger_score: float = CORE_TRIGGER_SCORE,
    non_core_trigger_score: float = NON_CORE_TRIGGER_SCORE,
) -> tuple[ExpansionSeed, ...]:
    """Select relation consumers without expanding fixed core membership itself.

    Non-core hits can seed only when they entered the pre-expansion Top-K with
    a positive query score. A forced hit remains a seed through its existing
    ``forced`` reason. Core consumers must independently clear
    ``core_trigger_score`` using their original score from
    ``ApiRetriever.score_query``. Golden-query tests tune these thresholds,
    propagation, and relation weights together.
    """
    seeds: list[ExpansionSeed] = []
    for hit in pre_expansion_hits:
        if hit.id not in RELATIONS_BY_CONSUMER:
            continue
        if hit.reason == "forced":
            seeds.append(ExpansionSeed(hit.id, hit.score, "forced"))
            logger.debug("related seed admitted: consumer=%s source=forced score=%.4f", hit.id, hit.score)
            continue
        if hit.agent_priority != "core" and hit.score > non_core_trigger_score:
            seeds.append(ExpansionSeed(hit.id, hit.score, "ranked"))
            logger.debug("related seed admitted: consumer=%s source=ranked score=%.4f", hit.id, hit.score)
            continue

        index = id_to_index.get(hit.id)
        if index is None:
            continue
        original_score = float(query_scores[index])
        if original_score >= core_trigger_score:
            seeds.append(ExpansionSeed(hit.id, original_score, "core_query_score"))
            logger.debug("related seed admitted: consumer=%s source=core_query_score score=%.4f", hit.id, original_score)
        else:
            logger.debug("related seed skipped: consumer=%s core_score=%.4f threshold=%.4f", hit.id, original_score, core_trigger_score)
    return tuple(seeds)


def expand_related_apis(
    seeds: Sequence[ExpansionSeed],
    catalog: Sequence[Mapping],
    query_scores: Sequence[float],
    id_to_index: Mapping[str, int],
    producer_index: Mapping[str, Sequence[str]],
    existing_ids: Sequence[str],
    *,
    query: str,
    query_allows_low_priority: bool,
    max_related_apis: int = MAX_RELATED_APIS,
    max_depth: int = MAX_EXPANSION_DEPTH,
) -> tuple[ExpandedCandidate, ...]:
    """Expand seed dependencies within a fixed API and traversal budget."""
    rows_by_id = {str(row["id"]): row for row in catalog}
    existing = set(existing_ids)
    candidates: dict[str, ExpandedCandidate] = {}
    shape_intent = profile_shape_intent(query)
    queue: list[tuple[str, float, int, frozenset[str]]] = [
        (seed.consumer_id, seed.score, 0, frozenset((seed.consumer_id,)))
        for seed in seeds
    ]

    def score_api(api_id: str, seed_score: float, relation_weight: float) -> RelatedScore:
        row = rows_by_id[api_id]
        score = calculate_related_score(
            float(query_scores[id_to_index[api_id]]),
            seed_score,
            relation_weight,
            producer_priority=str(row.get("agent_priority") or "normal"),
            query_allows_low_priority=query_allows_low_priority,
        )
        return score

    while queue and len(candidates) < max_related_apis:
        consumer_id, seed_score, depth, ancestry = queue.pop(0)
        relation = RELATIONS_BY_CONSUMER.get(consumer_id)
        if relation is None or depth >= max_depth:
            continue

        for role in relation.roles:
            workflows: list[tuple[tuple[str, ...], float, float]] = []
            for option in role.options:
                option_score = max(
                    score_api(api_id, seed_score, option.weight).final_score
                    for api_id in option.api_ids
                )
                workflows.append((option.api_ids, option_score, option.weight))

            if role.allow_type_producers:
                type_producers = tuple(
                    dict.fromkeys(
                        api_id
                        for geometry_type in role.geometry_types
                        for api_id in producer_index.get(geometry_type, ())
                    )
                )
                if role.requires_closed_profile:
                    type_producers = tuple(
                        api_id
                        for api_id in type_producers
                        if api_id in role.closed_type_producer_ids
                    )
                workflows.extend(
                    (
                        (api_id,),
                        score_api(api_id, seed_score, role.type_producer_weight).final_score,
                        role.type_producer_weight,
                    )
                    for api_id in type_producers
                )

            use_shape_intent = shape_intent is not None and role.name != "path"
            workflows.sort(
                key=lambda item: (
                    workflow_shape_rank(item[0], shape_intent)
                    if use_shape_intent
                    else 1,
                    -item[1],
                    len(item[0]),
                    tuple(id_to_index[api_id] for api_id in item[0]),
                )
            )
            workflow_limit = role.max_producers
            if use_shape_intent and role.name == "profiles":
                workflow_limit = 1
            for workflow, _workflow_score, relation_weight in workflows[:workflow_limit]:
                next_depth = depth + len(workflow)
                if next_depth > max_depth:
                    logger.debug("related workflow skipped: consumer=%s role=%s workflow=%s reason=depth depth=%d max_depth=%d", consumer_id, role.name, workflow, next_depth, max_depth)
                    continue
                new_ids = tuple(
                    api_id
                    for api_id in workflow
                    if api_id not in existing and api_id not in candidates
                )
                if len(candidates) + len(new_ids) > max_related_apis:
                    logger.debug("related workflow skipped: consumer=%s role=%s workflow=%s reason=budget additions=%d remaining=%d", consumer_id, role.name, workflow, len(new_ids), max_related_apis - len(candidates))
                    continue

                for position, api_id in enumerate(workflow, start=1):
                    if api_id in existing:
                        continue
                    related_score = score_api(api_id, seed_score, relation_weight)
                    candidate = ExpandedCandidate(
                        api_id=api_id,
                        score=related_score.final_score,
                        reason=f"related:{consumer_id}:{role.name}",
                        depth=depth + position,
                        workflow_api_ids=workflow,
                        producer_query_score=related_score.producer_query_score,
                        seed_score=seed_score,
                        relation_weight=relation_weight,
                        propagation_score=related_score.propagation_score,
                    )
                    previous = candidates.get(api_id)
                    if previous is None or candidate.score > previous.score:
                        candidates[api_id] = candidate
                        logger.debug("related candidate selected: api=%s consumer=%s role=%s shape_intent=%s producer_score=%.4f seed_score=%.4f relation_weight=%.2f propagation=%.4f final_score=%.4f workflow=%s", api_id, consumer_id, role.name, shape_intent if use_shape_intent else None, candidate.producer_query_score, candidate.seed_score, candidate.relation_weight, candidate.propagation_score, candidate.score, workflow)

                terminal_id = workflow[-1]
                if terminal_id not in ancestry and next_depth < max_depth:
                    terminal_score = score_api(terminal_id, seed_score, relation_weight).final_score
                    queue.append(
                        (
                            terminal_id,
                            terminal_score,
                            next_depth,
                            ancestry | frozenset(workflow),
                        )
                    )
                elif terminal_id in ancestry:
                    logger.debug("related workflow skipped: consumer=%s workflow=%s reason=cycle", consumer_id, workflow)

    return tuple(sorted(candidates.values(), key=lambda candidate: (-candidate.score, candidate.api_id)))


__all__ = [
    "CORE_TRIGGER_SCORE",
    "MAX_EXPANSION_DEPTH",
    "MAX_RELATED_APIS",
    "NON_CORE_TRIGGER_SCORE",
    "ExpandedCandidate",
    "ExpansionSeed",
    "expand_related_apis",
    "select_expansion_seeds",
]

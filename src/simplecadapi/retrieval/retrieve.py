"""Orchestrate hybrid retrieve → core merge → optional markdown bodies."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Collection, Mapping, Sequence

import numpy as np

from .bm25 import Bm25Index
from .boost import apply_boosts, query_allows_low_priority
from .catalog_io import default_catalog_path, load_catalog
from .embed import (
    cosine_similarities,
    default_embeddings_path,
    embed_query,
    load_embeddings,
    resolve_api_key,
)
from .fuse import BM25_WEIGHT, VECTOR_WEIGHT, fuse_scores
from .expand import expand_related_apis, select_expansion_seeds
from .load_md import attach_bodies, catalog_row_by_id, format_api_prompt_slice
from .merge import merge_core_and_ranked, select_core_hits
from .producer_index import build_producer_index
from .relations import validate_related_api_relations
from .types import RETRIEVE_TOP_K, ApiHit, hit_from_catalog_row

logger = logging.getLogger(__name__)


class ApiRetriever:
    """Caches catalog + BM25 + embedding matrix for repeated queries."""

    def __init__(
        self,
        *,
        catalog_path: Path | None = None,
        embeddings_path: Path | None = None,
        repo_root: Path | None = None,
        catalog: Sequence[Mapping] | None = None,
        embeddings: np.ndarray | None = None,
        related_api_expansion_enabled: bool = True,
    ) -> None:
        self.repo_root = repo_root or (
            (catalog_path or default_catalog_path()).resolve().parents[1]
        )
        self.catalog: list[dict] = list(catalog) if catalog is not None else load_catalog(
            catalog_path
        )
        self.embeddings = (
            embeddings
            if embeddings is not None
            else load_embeddings(embeddings_path or default_embeddings_path())
        )
        if self.embeddings.shape[0] != len(self.catalog):
            raise ValueError(
                f"embeddings rows ({self.embeddings.shape[0]}) != "
                f"catalog rows ({len(self.catalog)})"
            )
        self.bm25 = Bm25Index(self.catalog)
        self._id_to_index = {str(row["id"]): i for i, row in enumerate(self.catalog)}
        self.producer_index = build_producer_index(self.catalog)
        validate_related_api_relations(self.catalog)
        self.related_api_expansion_enabled = related_api_expansion_enabled

    def score_query(
        self,
        query: str,
        *,
        query_vec: Sequence[float] | None = None,
        use_vector: bool = True,
        vector_weight: float = VECTOR_WEIGHT,
        bm25_weight: float = BM25_WEIGHT,
    ) -> np.ndarray:
        """Fused + boosted scores aligned with catalog rows."""
        bm25_raw = self.bm25.scores(query)

        if use_vector:
            vec = list(query_vec) if query_vec is not None else embed_query(query)
            vec_raw = cosine_similarities(self.embeddings, vec)
        else:
            if resolve_api_key() is None and query_vec is None:
                logger.info("No embedding API key; using BM25-only scores")
            vec_raw = np.zeros(len(self.catalog), dtype=np.float64)

        fused = fuse_scores(
            vec_raw,
            bm25_raw,
            vector_weight=vector_weight if use_vector else 0.0,
            bm25_weight=bm25_weight if use_vector else 1.0,
        )
        return apply_boosts(fused, self.catalog, query)

    def ranked_non_core(
        self,
        scores: Sequence[float],
    ) -> list[ApiHit]:
        """Non-core catalog rows sorted by score descending.

        Tie-break: prefer ``normal`` over ``low``, then catalog order.
        """
        priority_rank = {"normal": 0, "low": 1}
        ranked: list[tuple[float, int, int]] = []
        for i, row in enumerate(self.catalog):
            pri = str(row.get("agent_priority") or "normal")
            if pri == "core":
                continue
            ranked.append(
                (
                    float(scores[i]),
                    priority_rank.get(pri, 2),
                    i,
                )
            )
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        hits: list[ApiHit] = []
        for score, _pri, i in ranked:
            hits.append(
                hit_from_catalog_row(
                    self.catalog[i],
                    score=score,
                    reason="fused",
                )
            )
        return hits

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = RETRIEVE_TOP_K,
        load_bodies: bool = True,
        query_vec: Sequence[float] | None = None,
        use_vector: bool = True,
        operation: str | None = None,
        exclude_ids: Collection[str] = (),
    ) -> list[ApiHit]:
        """Return exactly top_k hits (core + ranked fills) when catalog allows."""
        excluded_ids = frozenset(exclude_ids)
        scores = self.score_query(
            query,
            query_vec=query_vec,
            use_vector=use_vector,
        )
        core = [
            hit for hit in select_core_hits(self.catalog) if hit.id not in excluded_ids
        ]
        # Preserve core scores from the fused vector for observability.
        core_scored: list[ApiHit] = []
        for hit in core:
            idx = self._id_to_index.get(hit.id)
            score = float(scores[idx]) if idx is not None else hit.score
            core_scored.append(
                ApiHit(
                    id=hit.id,
                    symbol=hit.symbol,
                    path=hit.path,
                    score=score,
                    agent_priority=hit.agent_priority,
                    capability_tags=hit.capability_tags,
                    reason="core",
                    body_markdown="",
                    doc_category=hit.doc_category,
                    signature=hit.signature,
                    import_surface=hit.import_surface,
                    description=hit.description,
                )
            )

        ranked = [
            hit
            for hit in self.ranked_non_core(scores)
            if hit.id not in excluded_ids
        ]

        # ErrorGuidance hook: force a specific API into the ranked prefix.
        if operation:
            forced_row = catalog_row_by_id(self.catalog, operation)
            if forced_row is None:
                logger.warning("operation=%r not in catalog; ignored", operation)
            elif operation in excluded_ids:
                logger.warning("operation=%r is excluded; ignored", operation)
            elif str(forced_row.get("agent_priority") or "") != "core":
                idx = self._id_to_index[operation]
                forced = hit_from_catalog_row(
                    forced_row,
                    score=max(float(scores[idx]), 1.0),
                    reason="forced",
                )
                ranked = [forced] + [h for h in ranked if h.id != operation]

        pre_expansion = merge_core_and_ranked(core_scored, ranked, top_k=top_k)
        expanded = ()
        if self.related_api_expansion_enabled:
            seeds = select_expansion_seeds(pre_expansion, scores, self._id_to_index)
            expanded = tuple(
                candidate
                for candidate in expand_related_apis(
                seeds,
                self.catalog,
                scores,
                self._id_to_index,
                self.producer_index,
                [hit.id for hit in pre_expansion],
                query=query,
                query_allows_low_priority=query_allows_low_priority(query),
                )
                if candidate.api_id not in excluded_ids
                and not (set(candidate.workflow_api_ids) & excluded_ids)
            )
        if expanded:
            related_hits = {
                candidate.api_id: hit_from_catalog_row(
                    self.catalog[self._id_to_index[candidate.api_id]],
                    score=candidate.score,
                    reason=candidate.reason,
                )
                for candidate in expanded
            }
            protected_ids = tuple(
                dict.fromkeys(
                    api_id
                    for candidate in expanded
                    for api_id in candidate.workflow_api_ids
                )
            )
            ranked_by_id = {hit.id: hit for hit in ranked}
            forced_hits = [hit for hit in ranked if hit.reason == "forced"]
            forced_ids = {hit.id for hit in forced_hits}
            protected_hits = [
                related_hits.get(api_id, ranked_by_id[api_id])
                for api_id in protected_ids
                if api_id not in forced_ids
            ]
            ordinary_hits = [
                hit
                for hit in ranked
                if hit.reason != "forced" and hit.id not in protected_ids
            ]
            priority_rank = {"normal": 0, "low": 1}
            ordinary_hits.sort(
                key=lambda hit: (
                    -hit.score,
                    priority_rank.get(hit.agent_priority, 2),
                    self._id_to_index[hit.id],
                )
            )
            ranked = forced_hits + protected_hits + ordinary_hits

        merged = merge_core_and_ranked(core_scored, ranked, top_k=top_k)
        if expanded:
            pre_ids = {hit.id for hit in pre_expansion}
            merged_ids = {hit.id for hit in merged}
            logger.debug(
                "related expansion merge: protected_workflows=%s inserted=%s evicted=%s",
                [candidate.workflow_api_ids for candidate in expanded],
                sorted(merged_ids - pre_ids),
                sorted(pre_ids - merged_ids),
            )
        if load_bodies:
            merged = attach_bodies(merged, repo_root=self.repo_root)
        return merged


def retrieve_apis(
    query: str,
    *,
    top_k: int = RETRIEVE_TOP_K,
    load_bodies: bool = True,
    catalog_path: Path | None = None,
    embeddings_path: Path | None = None,
    repo_root: Path | None = None,
    query_vec: Sequence[float] | None = None,
    use_vector: bool = True,
    operation: str | None = None,
    exclude_ids: Collection[str] = (),
    retriever: ApiRetriever | None = None,
) -> list[ApiHit]:
    """Library entry: user utterance → list[ApiHit] (length top_k)."""
    engine = retriever or ApiRetriever(
        catalog_path=catalog_path,
        embeddings_path=embeddings_path,
        repo_root=repo_root,
    )
    return engine.retrieve(
        query,
        top_k=top_k,
        load_bodies=load_bodies,
        query_vec=query_vec,
        use_vector=use_vector,
        operation=operation,
        exclude_ids=exclude_ids,
    )


__all__ = [
    "ApiRetriever",
    "BM25_WEIGHT",
    "VECTOR_WEIGHT",
    "format_api_prompt_slice",
    "retrieve_apis",
]

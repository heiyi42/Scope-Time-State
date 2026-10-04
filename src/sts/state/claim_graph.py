from __future__ import annotations

from datetime import timedelta
from typing import Sequence

import networkx as nx
import numpy as np

from sts.state.config import StateThreadConfig
from sts.state.semantic_distance import semantic_distance, l2_normalize
from sts.state.models import ClaimGraphEdge, ClaimThreadFeature


class ClaimGraphBuilder:
    def __init__(self, config: StateThreadConfig):
        self.config = config

    def build(
        self,
        features: Sequence[ClaimThreadFeature],
        structured_vectors: np.ndarray,
    ) -> tuple[nx.DiGraph, list[ClaimGraphEdge]]:
        if self.config.pair_strategy != "exact":
            raise NotImplementedError("ANN is a Phase-B optimization")
        if len(features) > self.config.exact_pairwise_limit:
            raise ValueError(
                f"Scope has {len(features)} Claims, above exact_pairwise_limit="
                f"{self.config.exact_pairwise_limit}"
            )
        if len(features) != len(structured_vectors):
            raise ValueError("feature and embedding counts differ")

        normalized = l2_normalize(structured_vectors)
        graph = nx.DiGraph()
        graph.add_nodes_from(feature.claim_id for feature in features)
        if not features:
            return graph, []
        span_seconds = (
            features[-1].resolved_time - features[0].resolved_time
        ).total_seconds()
        max_gap = (
            timedelta(days=self.config.max_time_gap_days).total_seconds()
            if self.config.max_time_gap_days is not None
            else None
        )

        records = []
        for left_index, left in enumerate(features):
            for right_index in range(left_index + 1, len(features)):
                right = features[right_index]
                delta_seconds = (
                    right.resolved_time - left.resolved_time
                ).total_seconds()
                if max_gap is not None and delta_seconds > max_gap:
                    continue
                breakdown = semantic_distance(
                    normalized[left_index],
                    normalized[right_index],
                    delta_seconds,
                    span_seconds,
                    alpha=self.config.alpha,
                    # Preserve current membership while exposing participants
                    # and topical entities separately to downstream identity.
                    left_entities=tuple(
                        sorted(
                            set(left.participants)
                            | set(left.topic_entities)
                        )
                    ),
                    right_entities=tuple(
                        sorted(
                            set(right.participants)
                            | set(right.topic_entities)
                        )
                    ),
                    entity_mode=self.config.entity_mode,
                    entity_gamma=self.config.entity_gamma,
                    max_common_entities=self.config.max_common_entities,
                )
                if (
                    breakdown.adjusted_distance
                    >= self.config.edge_distance_threshold
                ):
                    continue
                record = ClaimGraphEdge(
                    source_claim_id=left.claim_id,
                    target_claim_id=right.claim_id,
                    semantic_similarity=breakdown.semantic_similarity,
                    time_decay=breakdown.time_decay,
                    raw_distance=breakdown.raw_distance,
                    adjusted_distance=breakdown.adjusted_distance,
                    entity_support=breakdown.entity_support,
                    shared_entity_count=breakdown.shared_entity_count,
                )
                records.append(record)
                graph.add_edge(
                    left.claim_id,
                    right.claim_id,
                    distance=record.adjusted_distance,
                    raw_distance=record.raw_distance,
                    semantic_similarity=record.semantic_similarity,
                    time_decay=record.time_decay,
                    entity_support=record.entity_support,
                )
        return graph, records

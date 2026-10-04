from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=float)
    if vectors.ndim != 2:
        raise ValueError("vectors must be a two-dimensional matrix")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vectors / norms


@dataclass(frozen=True)
class DistanceBreakdown:
    semantic_similarity: float
    time_decay: float
    raw_distance: float
    adjusted_distance: float
    entity_support: float
    shared_entity_count: int


def semantic_distance(
    left_vector: np.ndarray,
    right_vector: np.ndarray,
    delta_seconds: float,
    scope_span_seconds: float,
    *,
    alpha: float,
    left_entities: tuple[str, ...] = (),
    right_entities: tuple[str, ...] = (),
    entity_mode: str = "direct_overlap",
    entity_gamma: float = 0.1,
    max_common_entities: int = 5,
) -> DistanceBreakdown:
    similarity = float(np.dot(left_vector, right_vector))
    similarity = max(-1.0, min(1.0, similarity))
    span = max(float(scope_span_seconds), 1.0)
    decay = math.exp(-alpha * abs(delta_seconds) / span)
    raw_distance = 1.0 - similarity * decay

    shared_count = len(set(left_entities) & set(right_entities))
    entity_support = 0.0
    adjusted_distance = raw_distance
    if entity_mode == "direct_overlap" and shared_count:
        entity_support = 1.0 - math.exp(
            -entity_gamma * shared_count / max(max_common_entities, 1)
        )
        # Entity overlap is supporting evidence, so it may only shorten the
        # base semantic-temporal distance.  Applying the STS support factor
        # to similarity with an extra 0.5 baseline makes support values in
        # [0, 1] increase distance, contradicting that invariant.
        adjusted_distance = raw_distance * (1.0 - entity_support)
    elif entity_mode not in {"none", "direct_overlap"}:
        raise ValueError(f"Unsupported entity_mode: {entity_mode}")

    return DistanceBreakdown(
        semantic_similarity=similarity,
        time_decay=decay,
        raw_distance=raw_distance,
        adjusted_distance=adjusted_distance,
        entity_support=entity_support,
        shared_entity_count=shared_count,
    )

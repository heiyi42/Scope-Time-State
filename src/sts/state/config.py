from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional


@dataclass(frozen=True)
class StateThreadConfig:
    feature_version: str = "sts-claim-feature-v1"
    construction_version: str = "sts-state-thread-v1"
    min_claim_confidence: float = 0.6
    alpha: float = 10.0
    edge_distance_threshold: float = 0.7
    pair_strategy: Literal["exact", "ann"] = "exact"
    exact_pairwise_limit: int = 500
    ann_top_k: int = 20
    max_time_gap_days: Optional[float] = None
    entity_mode: Literal["none", "direct_overlap"] = (
        "direct_overlap"
    )
    entity_gamma: float = 0.1
    max_common_entities: int = 5
    prune_percentile: float = 70.0
    outdegree_limit: int = 1
    max_distinct_events_per_state: Optional[int] = None
    oversize_policy: Literal["none", "recursive_split"] = "none"
    state_id_jaccard_threshold: float = 0.5
    export_claim_graph: bool = True
    export_features: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_claim_confidence <= 1.0:
            raise ValueError("min_claim_confidence must be in [0, 1]")
        if not 0.0 <= self.edge_distance_threshold <= 2.0:
            raise ValueError("edge_distance_threshold must be in [0, 2]")
        if not 0.0 <= self.prune_percentile <= 100.0:
            raise ValueError("prune_percentile must be in [0, 100]")
        if self.exact_pairwise_limit < 1:
            raise ValueError("exact_pairwise_limit must be positive")

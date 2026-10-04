from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Literal, Tuple

from sts.graph.types import State
from sts.utils.datetime_utils import to_iso_format


@dataclass(frozen=True)
class ResolvedClaimTime:
    value: datetime
    start: datetime
    end: datetime
    precision: Literal[
        "second",
        "minute",
        "day",
        "month",
        "year",
        "event",
        "unknown",
    ]
    source: Literal[
        "claim_temporal",
        "event_time",
        "event_timestamp",
        "claim_timestamp",
    ]
    confidence: float


@dataclass(frozen=True)
class ClaimThreadFeature:
    claim_id: str
    structured_text: str
    content_text: str
    resolved_time: datetime
    time_start: datetime
    time_end: datetime
    time_precision: str
    time_source: str
    time_confidence: float
    participants: Tuple[str, ...]
    topic_entities: Tuple[str, ...]
    topic_terms: Tuple[str, ...]
    event_ids: Tuple[str, ...]
    claim_confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "structured_text": self.structured_text,
            "content_text": self.content_text,
            "resolved_time": to_iso_format(self.resolved_time),
            "time_start": to_iso_format(self.time_start),
            "time_end": to_iso_format(self.time_end),
            "time_precision": self.time_precision,
            "time_source": self.time_source,
            "time_confidence": self.time_confidence,
            "participants": list(self.participants),
            "topic_entities": list(self.topic_entities),
            "topic_terms": list(self.topic_terms),
            "event_ids": list(self.event_ids),
            "claim_confidence": self.claim_confidence,
        }


@dataclass(frozen=True)
class ClaimGraphEdge:
    source_claim_id: str
    target_claim_id: str
    semantic_similarity: float
    time_decay: float
    raw_distance: float
    adjusted_distance: float
    entity_support: float
    shared_entity_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_claim_id": self.source_claim_id,
            "target_claim_id": self.target_claim_id,
            "semantic_similarity": self.semantic_similarity,
            "time_decay": self.time_decay,
            "raw_distance": self.raw_distance,
            "adjusted_distance": self.adjusted_distance,
            "entity_support": self.entity_support,
            "shared_entity_count": self.shared_entity_count,
        }


@dataclass(frozen=True)
class StateMembership:
    state_id: str
    claim_id: str
    time_group_id: str
    time_rank: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation": "STATE_MEMBERSHIP",
            "state_id": self.state_id,
            "claim_id": self.claim_id,
            "time_group_id": self.time_group_id,
            "time_rank": self.time_rank,
        }


@dataclass(frozen=True)
class TemporalRelation:
    state_id: str
    source_time_group_id: str
    target_time_group_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation": "PRECEDES",
            "state_id": self.state_id,
            "source_time_group_id": self.source_time_group_id,
            "target_time_group_id": self.target_time_group_id,
        }


@dataclass
class StateBuildResult:
    scope_id: str
    states: list[State]
    pending_claim_ids: list[str]
    untimed_claim_ids: list[str]
    graph_stats: Dict[str, Any]
    diagnostics: Dict[str, Any]
    state_memberships: list[StateMembership] = field(default_factory=list)
    temporal_relations: list[TemporalRelation] = field(
        default_factory=list
    )
    candidate_edges: list[ClaimGraphEdge] = field(default_factory=list)
    features: list[ClaimThreadFeature] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "states": [state.to_dict() for state in self.states],
            "pending_claim_ids": self.pending_claim_ids,
            "untimed_claim_ids": self.untimed_claim_ids,
            "graph_stats": self.graph_stats,
            "diagnostics": self.diagnostics,
            "state_memberships": [
                edge.to_dict() for edge in self.state_memberships
            ],
            "temporal_relations": [
                edge.to_dict() for edge in self.temporal_relations
            ],
            "candidate_edges": [
                edge.to_dict() for edge in self.candidate_edges
            ],
            "features": [feature.to_dict() for feature in self.features],
        }

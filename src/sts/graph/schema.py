"""
STS evidence graph schema

- ClaimNode stores extracted evidence units.
- EventNode stores source conversation events.
- ScopeNode stores question-routing scopes.
- Explicit relation records preserve provenance between these objects.
"""

import numpy as np
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

from .types import Claim, Event, Scope, RawDataType


# ==================== Role Type Enumerations ====================

class ClaimRole(str, Enum):
    """Claim role types in an event."""
    CORE = "core"
    CONTEXT = "context"
    DETAIL = "detail"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    CAUSAL = "causal"



class EventRole(str, Enum):
    """Event role types in a scope."""
    INITIATING = "initiating"     # Initiating event
    DEVELOPING = "developing"     # Developing event
    CLIMAX = "climax"            # Climax event
    CONCLUDING = "concluding"     # Concluding event
    RECURRING = "recurring"       # Recurring pattern
    BACKGROUND = "background"     # Background event
    KEY_MOMENT = "key_moment"    # Key moment
    TRANSITION = "transition"     # Transition event



# ==================== Node and Relation Data Types ====================

class ClaimNode(BaseModel):
    """Claim evidence record."""
    id: str = Field(..., description="Claim unique identifier (claim_id)")
    content: str = Field(..., description="Claim content")
    event_ids: List[str] = Field(default_factory=list, description="List of event IDs that compose this claim")
    scope_id: str = Field(default="", description="Source scope ID")
    state_id: Optional[str] = Field(
        default=None,
        description="Assigned STS State ID after Claim threading",
    )

    confidence: float = Field(default=0.8, description="Confidence (0.0-1.0)")
    temporal: Optional[str] = Field(default=None, description="Time information, format: 'relative time (absolute time)'")
    spatial: Optional[str] = Field(default=None, description="Location information")
    keywords: List[str] = Field(default_factory=list, description="Keywords")
    query_patterns: List[str] = Field(default_factory=list, description="Query patterns that can be answered")
    timestamp: Optional[datetime] = Field(default=None, description="Timestamp")
    claim_type: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    evidence: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    relation: Dict[str, str] = Field(
        default_factory=dict,
        description="Relation ID to role mapping (relation_id -> role)"
    )

    @classmethod
    def from_claim(cls, claim: Claim, relation: Optional[Dict[str, str]] = None) -> 'ClaimNode':
        """Create ClaimNode from Claim data class"""
        return cls(
            id=claim.claim_id,
            content=claim.content,
            event_ids=claim.event_ids or [],
            scope_id=claim.scope_id or "",
            state_id=claim.state_id,
            confidence=claim.confidence,
            temporal=claim.temporal,
            spatial=claim.spatial,
            keywords=claim.keywords or [],
            query_patterns=claim.query_patterns or [],
            timestamp=claim.timestamp,
            claim_type=claim.claim_type,
            entities=claim.entities or [],
            evidence=claim.evidence,
            metadata=claim.metadata or {},
            relation=relation or {}
        )

    def to_claim(self) -> Claim:
        """Convert to Claim data class"""
        return Claim(
            claim_id=self.id,
            content=self.content,
            event_ids=self.event_ids,
            scope_id=self.scope_id,
            state_id=self.state_id,
            confidence=self.confidence,
            temporal=self.temporal,
            spatial=self.spatial,
            keywords=self.keywords,
            query_patterns=self.query_patterns,
            timestamp=self.timestamp,
            claim_type=self.claim_type,
            entities=self.entities,
            evidence=self.evidence,
            metadata=self.metadata,
        )

    def to_text(self) -> str:
        parts = [self.content]
        if self.temporal:
            parts.append(f"Time: {self.temporal}")
        if self.spatial:
            parts.append(f"Location: {self.spatial}")
        if len(parts) > 1:
            return f"{parts[0]} ({'; '.join(parts[1:])})"
        return self.content



class EventClaimRelation(BaseModel):
    """Connect Claims to their source Event."""
    id: str = Field(..., description="Relation unique identifier")

    relation: Dict[str, str] = Field(
        default_factory=dict,
        description="Claim ID to role mapping (claim_id -> role)"
    )

    weights: Optional[Dict[str, float]] = Field(
        default=None,
        description="Importance weight for each claim (claim_id -> weight)"
    )

    event_node_id: str = Field(
        default="",
        description="Corresponding event node ID (bidirectional link)"
    )

    created_at: Optional[datetime] = Field(default=None, description="Relation creation time")
    extraction_confidence: float = Field(default=0.8, description="Extraction confidence (0.0-1.0)")



class EventNode(BaseModel):
    """
    Source Event record.

    Stores complete event information
    This class extends the Event dataclass, adding graph-specific fields
    Field order is consistent with Event
    """
    # Node identifier
    id: str = Field(..., description="Node unique identifier, corresponds to event_id")

    # Core event fields (aligned with Event)
    user_id_list: List[str] = Field(default_factory=list, description="Involved user ID list")
    original_data: List[Dict[str, Any]] = Field(default_factory=list, description="Original data")
    timestamp: Optional[datetime] = Field(default=None, description="Event timestamp")
    summary: Optional[str] = Field(default=None, description="Event summary")

    # Optional event fields (aligned with Event)
    participants: Optional[List[str]] = Field(default=None, description="Participant list")
    type: Optional[RawDataType] = Field(default=None, description="Raw data type")
    keywords: Optional[List[str]] = Field(default=None, description="Keywords extracted from event")
    subject: Optional[str] = Field(default=None, description="Event subject")
    event_description: Optional[str] = Field(default=None, description="Event memory description")
    book_id: Optional[str] = None
    chapter_idx: Optional[int] = None
    event_time_text: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    event_type: Optional[str] = None
    extraction_confidence: float = 0.8
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # STSGraph structure fields
    relation: Dict[str, str] = Field(
        default_factory=dict,
        description="Relation ID to role mapping (relation_id -> role)"
    )
    event_claim_relation_id: str = Field(
        default="",
        description="Corresponding claim relation ID (bidirectional link)"
    )

    @classmethod
    def from_event(cls, event: Event, event_claim_relation_id: str = "", relation: Optional[Dict[str, str]] = None) -> 'EventNode':
        """Create EventNode from Event data class"""
        return cls(
            id=event.event_id,
            user_id_list=event.user_id_list,
            original_data=event.original_data,
            timestamp=event.timestamp,
            summary=event.summary,
            participants=event.participants,
            type=event.type,
            keywords=event.keywords,
            subject=event.subject,
            event_description=event.event_description,
            book_id=event.book_id,
            chapter_idx=event.chapter_idx,
            event_time_text=event.event_time_text,
            entities=event.entities or [],
            locations=event.locations or [],
            event_type=event.event_type,
            extraction_confidence=event.extraction_confidence,
            metadata=event.metadata or {},
            relation=relation or {},
            event_claim_relation_id=event_claim_relation_id
        )

    def to_event(self) -> Event:
        """Convert to Event data class"""
        return Event(
            event_id=self.id,
            user_id_list=self.user_id_list,
            original_data=self.original_data,
            timestamp=self.timestamp,
            summary=self.summary if self.summary else "",
            participants=self.participants,
            type=self.type,
            keywords=self.keywords,
            subject=self.subject,
            event_description=self.event_description,
            book_id=self.book_id,
            chapter_idx=self.chapter_idx,
            event_time_text=self.event_time_text,
            entities=self.entities,
            locations=self.locations,
            event_type=self.event_type,
            extraction_confidence=self.extraction_confidence,
            metadata=self.metadata,
        )



class ScopeEventRelation(BaseModel):
    """
    Connect Events to a routing Scope.

    Connects multiple event nodes to the same scope
    Describes each event's role and importance in the scope

    Responsibilities:
    - Store event role (initiating/developing/climax etc)
    - Store event weight (importance)
    - Do not store specific semantic content (stored by nodes)
    - Do not store binary relationships between nodes
    """
    # Relation identifier
    id: str = Field(..., description="Relation unique identifier")

    # Node role mapping
    relation: Dict[str, str] = Field(
        default_factory=dict,
        description="""
        Event ID to role mapping (event_id -> role)
        Role types refer to EventRole enum:
        - "initiating": Scope initiating event
        - "developing": Scope developing event
        - "climax": Scope climax event
        - "concluding": Scope concluding event
        - "recurring": Recurring pattern event
        - "background": Background event
        - "key_moment": Key moment
        - "transition": Transition event
        """
    )

    # Node weights
    weights: Optional[Dict[str, float]] = Field(
        default=None,
        description="""
        Importance weight of each event in the scope (event_id -> weight)
        Range: 0.0-1.0, higher value means more important
        Used for sorting and filtering during retrieval
        """
    )

    # Cross-layer connection
    scope_node_id: str = Field(
        default="",
        description="Corresponding scope node ID (bidirectional link)"
    )

    # Relation metadata
    created_at: Optional[datetime] = Field(
        default=None,
        description="Relation creation time"
    )

    coherence_score: float = Field(
        default=0.8,
        description="Scope coherence score, indicates how closely these events form a scope (0.0-1.0)"
    )



class ScopeNode(BaseModel):
    """
    Question-routing Scope record.

    Stores generalized scope information
    This class extends the Scope dataclass, adding graph-specific fields
    Field order is consistent with Scope
    Provides conversion methods between Scope and ScopeNode
    """
    # Node identifier
    id: str = Field(..., description="Node unique identifier, corresponds to scope_id")

    # Core scope fields (aligned with Scope)
    title: str = Field(..., description="Scope title/theme")
    summary: str = Field(..., description="Scope summary")
    event_ids: List[str] = Field(default_factory=list, description="List of event IDs that compose this scope")
    timestamp: Optional[datetime] = Field(default=None, description="Scope creation time (time of last event)")
    user_id_list: List[str] = Field(default_factory=list, description="Involved user ID list")

    # Optional scope fields (aligned with Scope)
    participants: Optional[List[str]] = Field(default=None, description="Participant list")
    keywords: Optional[List[str]] = Field(default=None, description="Keywords describing this scope")
    key_entities: List[str] = Field(default_factory=list)
    key_locations: List[str] = Field(default_factory=list)
    event_types: List[str] = Field(default_factory=list)
    time_start: Optional[datetime] = None
    time_end: Optional[datetime] = None
    scope_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # STSGraph structure fields
    scope_event_relation_id: str = Field(
        default="",
        description="Corresponding event relation ID (bidirectional link)"
    )

    @classmethod
    def from_scope(cls, scope: Scope, scope_event_relation_id: str = "") -> 'ScopeNode':
        """Create ScopeNode from Scope data class"""
        return cls(
            id=scope.scope_id,
            title=scope.title,
            summary=scope.summary,
            event_ids=scope.event_ids,
            timestamp=scope.timestamp,
            user_id_list=scope.user_id_list,
            participants=scope.participants,
            keywords=scope.keywords,
            key_entities=scope.key_entities or [],
            key_locations=scope.key_locations or [],
            event_types=scope.event_types or [],
            time_start=scope.time_start,
            time_end=scope.time_end,
            scope_type=scope.scope_type,
            metadata=scope.metadata or {},
            scope_event_relation_id=scope_event_relation_id
        )

    def to_scope(self) -> Scope:
        """Convert to Scope data class"""
        return Scope(
            scope_id=self.id,
            title=self.title,
            summary=self.summary,
            event_ids=self.event_ids,
            timestamp=self.timestamp,
            user_id_list=self.user_id_list,
            participants=self.participants,
            keywords=self.keywords,
            key_entities=self.key_entities,
            key_locations=self.key_locations,
            event_types=self.event_types,
            time_start=self.time_start,
            time_end=self.time_end,
            scope_type=self.scope_type,
            metadata=self.metadata,
        )



# ==================== STSGraph Container Class ====================

class STSGraph(BaseModel):
    """
    Evidence graph containing Claims, Events, Scopes, and explicit provenance
    relations. State threads are attached by the state subsystem.
    """
    # Claims and their source-Event relations.
    claims: Dict[str, ClaimNode] = Field(
        default_factory=dict,
        description="Claim node dictionary"
    )
    event_claim_relations: Dict[str, EventClaimRelation] = Field(
        default_factory=dict,
        description="Claim relation dictionary"
    )

    # Source Events and their Scope relations.
    events: Dict[str, EventNode] = Field(
        default_factory=dict,
        description="Event node dictionary, keyed by event ID"
    )
    scope_event_relations: Dict[str, ScopeEventRelation] = Field(
        default_factory=dict,
        description="Event relation dictionary, keyed by relation ID"
    )

    # Question-routing Scopes.
    scopes: Dict[str, ScopeNode] = Field(
        default_factory=dict,
        description="Scope node dictionary, keyed by scope ID"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'claims': {k: v.model_dump(mode='json') for k, v in self.claims.items()},
            'event_claim_relations': {k: v.model_dump(mode='json') for k, v in self.event_claim_relations.items()},
            'events': {k: v.model_dump(mode='json') for k, v in self.events.items()},
            'scope_event_relations': {k: v.model_dump(mode='json') for k, v in self.scope_event_relations.items()},
            'scopes': {k: v.model_dump(mode='json') for k, v in self.scopes.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'STSGraph':
        return cls(
            claims={k: ClaimNode(**v) for k, v in data.get('claims', {}).items()},
            event_claim_relations={k: EventClaimRelation(**v) for k, v in data.get('event_claim_relations', {}).items()},
            events={k: EventNode(**v) for k, v in data.get('events', {}).items()},
            scope_event_relations={k: ScopeEventRelation(**v) for k, v in data.get('scope_event_relations', {}).items()},
            scopes={k: ScopeNode(**v) for k, v in data.get('scopes', {}).items()}
        )

    def get_stats(self) -> Dict[str, int]:
        return {
            'claims': len(self.claims),
            'event_claim_relations': len(self.event_claim_relations),
            'events': len(self.events),
            'scope_event_relations': len(self.scope_event_relations),
            'scopes': len(self.scopes)
        }

    def add_node(self, layer: str, node_id: str, **kwargs):
        """
        Add node to specified layer

        Args:
            layer: Layer type ("claim", "event", "scope")
            node_id: Node ID
        """
        if layer == "claim":
            self.claims[node_id] = ClaimNode(
                id=node_id,
                content=kwargs.get("content", ""),
                event_ids=kwargs.get("event_ids", []),
                scope_id=kwargs.get("scope_id", ""),
                state_id=kwargs.get("state_id"),
                confidence=kwargs.get("confidence", 0.8),
                temporal=kwargs.get("temporal"),
                spatial=kwargs.get("spatial"),
                keywords=kwargs.get("keywords", []),
                query_patterns=kwargs.get("query_patterns", []),
                timestamp=kwargs.get("timestamp"),
                relation=kwargs.get("relation", {})
            )

        elif layer == "event":
            self.events[node_id] = EventNode(
                id=node_id,
                user_id_list=kwargs.get("user_id_list", []),
                original_data=kwargs.get("original_data", []),
                timestamp=kwargs.get("timestamp", None),
                summary=kwargs.get("summary", ""),
                participants=kwargs.get("participants", None),
                type=kwargs.get("type", None),
                keywords=kwargs.get("keywords", None),
                subject=kwargs.get("subject", None),
                event_description=kwargs.get("event_description", None),
                relation=kwargs.get("relation", {}),
                event_claim_relation_id=kwargs.get("event_claim_relation_id", "")
            )

        elif layer == "scope":
            self.scopes[node_id] = ScopeNode(
                id=node_id,
                title=kwargs.get("title", ""),
                summary=kwargs.get("summary", ""),
                event_ids=kwargs.get("event_ids", []),
                timestamp=kwargs.get("timestamp", None),
                user_id_list=kwargs.get("user_id_list", []),
                participants=kwargs.get("participants", None),
                keywords=kwargs.get("keywords", None),
                scope_event_relation_id=kwargs.get("scope_event_relation_id", "")
            )

        else:
            raise ValueError(f"Invalid layer: {layer}. Must be 'claim', 'event', or 'scope'")

    def add_relation(self, layer: str, relation_id: str, **kwargs):
        """
        Add relation to specified layer and update connected nodes' adjacency lists

        Args:
            layer: Layer type ("claim", "event")
            relation_id: Relation ID
        """
        if layer == "claim":
            self.event_claim_relations[relation_id] = EventClaimRelation(
                id=relation_id,
                relation=kwargs.get("relation", {}),
                weights=kwargs.get("weights", None),
                event_node_id=kwargs.get("event_node_id", ""),
                created_at=kwargs.get("created_at", None),
                extraction_confidence=kwargs.get("extraction_confidence", 0.8)
            )
            for node_id, role in kwargs.get("relation", {}).items():
                if node_id in self.claims:
                    self.claims[node_id].relation[relation_id] = role

        elif layer == "event":
            self.scope_event_relations[relation_id] = ScopeEventRelation(
                id=relation_id,
                relation=kwargs.get("relation", {}),
                weights=kwargs.get("weights", None),
                scope_node_id=kwargs.get("scope_node_id", ""),
                created_at=kwargs.get("created_at", None),
                coherence_score=kwargs.get("coherence_score", 0.8)
            )
            for node_id, role in kwargs.get("relation", {}).items():
                if node_id in self.events:
                    self.events[node_id].relation[relation_id] = role

        else:
            raise ValueError(f"Invalid layer: {layer}. Must be 'claim' or 'event'")

    def get_node(self, layer: str, node_id: str) -> Dict[str, Any]:
        if layer == "claim":
            node = self.claims.get(node_id)
            return node.model_dump() if node else {}
        elif layer == "event":
            node = self.events.get(node_id)
            return node.model_dump() if node else {}
        elif layer == "scope":
            node = self.scopes.get(node_id)
            return node.model_dump() if node else {}
        else:
            raise ValueError(f"Invalid layer: {layer}. Must be 'claim', 'event', or 'scope'")

    def get_relation(self, layer: str, relation_id: str) -> Dict[str, Any]:
        if layer == "claim":
            relation = self.event_claim_relations.get(relation_id)
            return relation.model_dump() if relation else {}
        elif layer == "event":
            relation = self.scope_event_relations.get(relation_id)
            return relation.model_dump() if relation else {}
        else:
            raise ValueError(f"Invalid layer: {layer}. Must be 'claim' or 'event'")

    def get_node_degree(self, layer: str, node_id: str) -> int:
        if layer == "claim" and node_id in self.claims:
            return len(self.claims[node_id].relation)
        elif layer == "event" and node_id in self.events:
            return len(self.events[node_id].relation)
        elif layer == "scope":
            return 0
        else:
            return 0

    def get_relation_degree(self, layer: str, relation_id: str) -> int:
        if layer == "claim":
            relation = self.event_claim_relations.get(relation_id)
            return len(relation.relation) if relation else 0
        elif layer == "event":
            relation = self.scope_event_relations.get(relation_id)
            return len(relation.relation) if relation else 0
        else:
            return 0

    def validate_bidirectional_links(self) -> Dict[str, List[str]]:
        """Validate consistency of all bidirectional links in the graph"""
        errors = {
            'claim_node_to_relation': [],
            'event_claim_relation_to_node': [],
            'event_claim_relation_to_event': [],
            'event_to_event_claim_relation': [],
            'event_node_to_relation': [],
            'scope_event_relation_to_node': [],
            'scope_event_relation_to_scope': [],
            'scope_to_scope_event_relation': []
        }

        # L1: ClaimNode -> EventClaimRelation
        for claim_id, claim in self.claims.items():
            for relation_id, role in claim.relation.items():
                if relation_id not in self.event_claim_relations:
                    errors['claim_node_to_relation'].append(
                        f"Claim '{claim_id}' references non-existent relation '{relation_id}'"
                    )
                elif claim_id not in self.event_claim_relations[relation_id].relation:
                    errors['claim_node_to_relation'].append(
                        f"Claim '{claim_id}' references relation '{relation_id}', but relation doesn't reference back"
                    )
                elif self.event_claim_relations[relation_id].relation[claim_id] != role:
                    errors['claim_node_to_relation'].append(
                        f"Claim '{claim_id}' has role '{role}' in relation '{relation_id}', but relation has role '{self.event_claim_relations[relation_id].relation[claim_id]}'"
                    )

        # L1: EventClaimRelation -> ClaimNode
        for relation_id, relation in self.event_claim_relations.items():
            for node_id, role in relation.relation.items():
                if node_id not in self.claims:
                    errors['event_claim_relation_to_node'].append(
                        f"Claim relation '{relation_id}' references non-existent claim '{node_id}'"
                    )
                elif relation_id not in self.claims[node_id].relation:
                    errors['event_claim_relation_to_node'].append(
                        f"Claim relation '{relation_id}' references claim '{node_id}', but claim doesn't reference back"
                    )
                elif self.claims[node_id].relation[relation_id] != role:
                    errors['event_claim_relation_to_node'].append(
                        f"Claim relation '{relation_id}' has role '{role}' for claim '{node_id}', but claim has role '{self.claims[node_id].relation[relation_id]}'"
                    )

        # L1-L2: EventClaimRelation -> EventNode
        for relation_id, relation in self.event_claim_relations.items():
            if relation.event_node_id:
                if relation.event_node_id not in self.events:
                    errors['event_claim_relation_to_event'].append(
                        f"Claim relation '{relation_id}' references non-existent event '{relation.event_node_id}'"
                    )
                elif self.events[relation.event_node_id].event_claim_relation_id != relation_id:
                    errors['event_claim_relation_to_event'].append(
                        f"Claim relation '{relation_id}' references event '{relation.event_node_id}', but event references relation '{self.events[relation.event_node_id].event_claim_relation_id}'"
                    )

        # L1-L2: EventNode -> EventClaimRelation
        for event_id, event in self.events.items():
            if event.event_claim_relation_id:
                if event.event_claim_relation_id not in self.event_claim_relations:
                    errors['event_to_event_claim_relation'].append(
                        f"Event '{event_id}' references non-existent claim relation '{event.event_claim_relation_id}'"
                    )
                elif self.event_claim_relations[event.event_claim_relation_id].event_node_id != event_id:
                    errors['event_to_event_claim_relation'].append(
                        f"Event '{event_id}' references claim relation '{event.event_claim_relation_id}', but relation references event '{self.event_claim_relations[event.event_claim_relation_id].event_node_id}'"
                    )

        # L2: EventNode -> ScopeEventRelation
        for event_id, event in self.events.items():
            for relation_id, role in event.relation.items():
                if relation_id not in self.scope_event_relations:
                    errors['event_node_to_relation'].append(
                        f"Event '{event_id}' references non-existent relation '{relation_id}'"
                    )
                elif event_id not in self.scope_event_relations[relation_id].relation:
                    errors['event_node_to_relation'].append(
                        f"Event '{event_id}' references relation '{relation_id}', but relation doesn't reference back"
                    )
                elif self.scope_event_relations[relation_id].relation[event_id] != role:
                    errors['event_node_to_relation'].append(
                        f"Event '{event_id}' has role '{role}' in relation '{relation_id}', but relation has role '{self.scope_event_relations[relation_id].relation[event_id]}'"
                    )

        # L2: ScopeEventRelation -> EventNode
        for relation_id, relation in self.scope_event_relations.items():
            for node_id, role in relation.relation.items():
                if node_id not in self.events:
                    errors['scope_event_relation_to_node'].append(
                        f"Event relation '{relation_id}' references non-existent event '{node_id}'"
                    )
                elif relation_id not in self.events[node_id].relation:
                    errors['scope_event_relation_to_node'].append(
                        f"Event relation '{relation_id}' references event '{node_id}', but event doesn't reference back"
                    )
                elif self.events[node_id].relation[relation_id] != role:
                    errors['scope_event_relation_to_node'].append(
                        f"Event relation '{relation_id}' has role '{role}' for event '{node_id}', but event has role '{self.events[node_id].relation[relation_id]}'"
                    )

        # L2-L3: ScopeEventRelation -> ScopeNode
        for relation_id, relation in self.scope_event_relations.items():
            if relation.scope_node_id:
                if relation.scope_node_id not in self.scopes:
                    errors['scope_event_relation_to_scope'].append(
                        f"Event relation '{relation_id}' references non-existent scope '{relation.scope_node_id}'"
                    )
                elif self.scopes[relation.scope_node_id].scope_event_relation_id != relation_id:
                    errors['scope_event_relation_to_scope'].append(
                        f"Event relation '{relation_id}' references scope '{relation.scope_node_id}', but scope references relation '{self.scopes[relation.scope_node_id].scope_event_relation_id}'"
                    )

        # L2-L3: ScopeNode -> ScopeEventRelation
        for scope_id, scope in self.scopes.items():
            if scope.scope_event_relation_id:
                if scope.scope_event_relation_id not in self.scope_event_relations:
                    errors['scope_to_scope_event_relation'].append(
                        f"Scope '{scope_id}' references non-existent event relation '{scope.scope_event_relation_id}'"
                    )
                elif self.scope_event_relations[scope.scope_event_relation_id].scope_node_id != scope_id:
                    errors['scope_to_scope_event_relation'].append(
                        f"Scope '{scope_id}' references event relation '{scope.scope_event_relation_id}', but relation references scope '{self.scope_event_relations[scope.scope_event_relation_id].scope_node_id}'"
                    )

        errors = {k: v for k, v in errors.items() if v}
        return errors


# ==================== STSGraph Embedding Container Class ====================

class STSGraphEmbedding(BaseModel):
    """Embeddings for STS evidence records and relations."""
    model_config = {"arbitrary_types_allowed": True}

    # Claim evidence embeddings.
    claims: Dict[str, np.ndarray] = Field(default_factory=dict)
    event_claim_relations: Dict[str, np.ndarray] = Field(default_factory=dict)

    # Source Event embeddings.
    events: Dict[str, np.ndarray] = Field(default_factory=dict)
    scope_event_relations: Dict[str, np.ndarray] = Field(default_factory=dict)

    # Scope embeddings.
    scopes: Dict[str, np.ndarray] = Field(default_factory=dict)

    def get_stats(self) -> Dict[str, int]:
        return {
            'claims': len(self.claims),
            'event_claim_relations': len(self.event_claim_relations),
            'events': len(self.events),
            'scope_event_relations': len(self.scope_event_relations),
            'scopes': len(self.scopes)
        }

    def to_dict(self) -> Dict[str, Any]:
        def convert_numpy(obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {k: convert_numpy(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy(item) for item in obj]
            else:
                return obj

        return convert_numpy({
            'claims': self.claims,
            'event_claim_relations': self.event_claim_relations,
            'events': self.events,
            'scope_event_relations': self.scope_event_relations,
            'scopes': self.scopes
        })

    def add_embedding(self, layer: str, node_id: str, embedding: np.ndarray):
        if layer == "claim":
            self.claims[node_id] = embedding
        elif layer == "event_claim_relation":
            self.event_claim_relations[node_id] = embedding
        elif layer == "event":
            self.events[node_id] = embedding
        elif layer == "scope_event_relation":
            self.scope_event_relations[node_id] = embedding
        elif layer == "scope":
            self.scopes[node_id] = embedding
        else:
            raise ValueError(f"Invalid layer: {layer}. Must be 'claim', 'event', 'scope', 'event_claim_relation', or 'scope_event_relation'")

    def get_embedding(self, layer: str, node_id: str) -> np.ndarray:
        if layer == "claim":
            return self.claims.get(node_id, np.array([]))
        elif layer == "event_claim_relation":
            return self.event_claim_relations.get(node_id, np.array([]))
        elif layer == "event":
            return self.events.get(node_id, np.array([]))
        elif layer == "scope_event_relation":
            return self.scope_event_relations.get(node_id, np.array([]))
        elif layer == "scope":
            return self.scopes.get(node_id, np.array([]))
        else:
            raise ValueError(f"Invalid layer: {layer}. Must be 'claim', 'event', 'scope', 'event_claim_relation', or 'scope_event_relation'")

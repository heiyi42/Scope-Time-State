"""
Core data types for STS graph memory system.

- Event: Memory event for storing conversation segments
- Claim: Knowledge claim extracted from scopes
- Scope: Scope abstraction grouping related events
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import datetime
import logging

from sts.utils.datetime_utils import to_iso_format

logger = logging.getLogger(__name__)


class RawDataType(Enum):
    """Types of content that can be processed."""
    CONVERSATION = "Conversation"
    BOOK_CHAPTER = "BookChapter"


@dataclass
class Event:
    """A timestamped conversation segment or benchmark chapter."""
    event_id: str
    user_id_list: List[str]
    original_data: List[Dict[str, Any]]
    timestamp: Optional[datetime.datetime]
    summary: str

    participants: Optional[List[str]] = None
    type: Optional[RawDataType] = None
    keywords: Optional[List[str]] = None
    subject: Optional[str] = None
    event_description: Optional[str] = None
    book_id: Optional[str] = None
    chapter_idx: Optional[int] = None
    event_time_text: Optional[str] = None
    entities: Optional[List[str]] = None
    locations: Optional[List[str]] = None
    event_type: Optional[str] = None
    extraction_confidence: float = 0.8
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.original_data:
            raise ValueError("original_data is required")
        if not self.summary:
            raise ValueError("summary is required")
        self.participants = self.participants or []
        self.keywords = self.keywords or []
        self.entities = self.entities or []
        self.locations = self.locations or []
        self.metadata = self.metadata or {}

    def __repr__(self) -> str:
        return f"Event(event_id={self.event_id}, original_data={self.original_data}, timestamp={self.timestamp}, summary={self.summary})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "user_id_list": self.user_id_list,
            "original_data": self.original_data,
            "timestamp": to_iso_format(self.timestamp) if self.timestamp else None,
            "summary": self.summary,
            "participants": self.participants,
            "type": str(self.type.value) if self.type else None,
            "keywords": self.keywords,
            "subject": self.subject,
            "event_description": self.event_description,
            "book_id": self.book_id,
            "chapter_idx": self.chapter_idx,
            "event_time_text": self.event_time_text,
            "entities": self.entities,
            "locations": self.locations,
            "event_type": self.event_type,
            "extraction_confidence": self.extraction_confidence,
            "metadata": self.metadata,
        }


@dataclass
class Claim:
    """
    Claim — Atomic, semantically complete information unit extracted from Events.

    Claims are first assigned to Scopes and are later organized into temporal
    States. ``state_id`` remains ``None`` until Claim threading completes.
    """
    claim_id: str
    content: str
    event_ids: List[str]
    scope_id: str

    state_id: Optional[str] = None
    confidence: float = 0.8
    temporal: Optional[str] = None
    spatial: Optional[str] = None
    keywords: Optional[List[str]] = None
    query_patterns: Optional[List[str]] = None
    timestamp: Optional[datetime.datetime] = None
    claim_type: Optional[str] = None
    entities: Optional[List[str]] = None
    evidence: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []
        if self.query_patterns is None:
            self.query_patterns = []
        self.entities = self.entities or []
        self.metadata = self.metadata or {}

    def __repr__(self) -> str:
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"Claim(id={self.claim_id}, content='{content_preview}')"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "content": self.content,
            "event_ids": self.event_ids,
            "scope_id": self.scope_id,
            "state_id": self.state_id,
            "confidence": self.confidence,
            "temporal": self.temporal,
            "spatial": self.spatial,
            "keywords": self.keywords,
            "query_patterns": self.query_patterns,
            "timestamp": to_iso_format(self.timestamp) if self.timestamp else None,
            "claim_type": self.claim_type,
            "entities": self.entities,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }

    def to_text(self) -> str:
        parts = [self.content]
        if self.temporal:
            parts.append(f"Time: {self.temporal}")
        if self.spatial:
            parts.append(f"Location: {self.spatial}")
        if len(parts) > 1:
            return f"{parts[0]} ({'; '.join(parts[1:])})"
        return self.content


@dataclass
class State:
    """A temporally ordered Claim thread inside one Scope."""

    state_id: str
    scope_id: str
    title: str
    summary: str
    claim_ids: List[str]
    event_ids: List[str]

    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None
    coherence: Optional[float] = None
    construction_method: str = "scope_conditioned_claim_thread"
    construction_version: str = "sts-state-thread-v1"
    construction_params: Optional[Dict[str, Any]] = None
    subject: Optional[str] = None
    dimension: Optional[str] = None
    topic_terms: Optional[List[str]] = None
    identity_coverage: Optional[float] = None
    identity_separation: Optional[float] = None
    is_mixed: bool = False
    representative_claim_ids: Optional[List[str]] = None
    time_groups: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_id": self.state_id,
            "scope_id": self.scope_id,
            "title": self.title,
            "summary": self.summary,
            "claim_ids": self.claim_ids,
            "event_ids": self.event_ids,
            "start_time": (
                to_iso_format(self.start_time) if self.start_time else None
            ),
            "end_time": to_iso_format(self.end_time) if self.end_time else None,
            "coherence": self.coherence,
            "construction_method": self.construction_method,
            "construction_version": self.construction_version,
            "construction_params": self.construction_params or {},
            "subject": self.subject,
            "dimension": self.dimension,
            "topic_terms": self.topic_terms or [],
            "identity_coverage": self.identity_coverage,
            "identity_separation": self.identity_separation,
            "is_mixed": self.is_mixed,
            "representative_claim_ids": (
                self.representative_claim_ids or []
            ),
            "time_groups": self.time_groups or [],
        }


@dataclass
class Scope:
    """
    Scope data structure.

    A scope is an abstraction of multiple related events, representing
    a recurring pattern, common context, or persistent activity.
    """
    scope_id: str
    title: str
    summary: str
    event_ids: List[str]
    timestamp: Optional[datetime.datetime]
    user_id_list: List[str]

    participants: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    key_entities: Optional[List[str]] = None
    key_locations: Optional[List[str]] = None
    event_types: Optional[List[str]] = None
    time_start: Optional[datetime.datetime] = None
    time_end: Optional[datetime.datetime] = None
    scope_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.scope_id:
            raise ValueError("scope_id is required")
        if not self.title:
            raise ValueError("title is required")
        if not self.summary:
            raise ValueError("summary is required")
        if not self.event_ids:
            raise ValueError("event_ids is required")
        self.participants = self.participants or []
        self.keywords = self.keywords or []
        self.key_entities = self.key_entities or []
        self.key_locations = self.key_locations or []
        self.event_types = self.event_types or []
        self.metadata = self.metadata or {}

    def __repr__(self) -> str:
        return f"Scope(scope_id={self.scope_id}, title={self.title}, event_count={len(self.event_ids)})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "title": self.title,
            "summary": self.summary,
            "event_ids": self.event_ids,
            "timestamp": to_iso_format(self.timestamp) if self.timestamp else None,
            "user_id_list": self.user_id_list,
            "participants": self.participants,
            "keywords": self.keywords,
            "key_entities": self.key_entities,
            "key_locations": self.key_locations,
            "event_types": self.event_types,
            "time_start": (
                to_iso_format(self.time_start) if self.time_start else None
            ),
            "time_end": to_iso_format(self.time_end) if self.time_end else None,
            "scope_type": self.scope_type,
            "metadata": self.metadata,
        }

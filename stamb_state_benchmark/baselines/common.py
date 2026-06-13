from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class BaselinePromptSpec:
    name: str
    visible_events: List[Dict[str, object]]
    instruction: str


def parse_time(value: Optional[str]) -> datetime:
    if not value:
        return datetime.min
    return datetime.fromisoformat(value)


def relevant_by_scope(events: Sequence[object], scope_id: str) -> List[object]:
    return [event for event in events if event.scope_id == scope_id]


def sort_by_time(events: Sequence[object], time_role: str) -> List[object]:
    return sorted(
        events,
        key=lambda event: parse_time(getattr(event, time_role) or event.updated_at),
        reverse=True,
    )


def resolve_valid_events(events: Sequence[object], time_role: str) -> Tuple[List[object], List[str]]:
    superseded_ids: Set[str] = {event.event_id for event in events if event.status == "superseded"}
    superseded_ids.update(target for event in events for target in event.supersedes)
    corrected_ids: Set[str] = set(target for event in events for target in event.corrects)
    invalid_ids = superseded_ids | corrected_ids
    valid_events = [
        event
        for event in sort_by_time(events, time_role)
        if event.event_id not in invalid_ids and event.state_relevant
    ]
    return valid_events, sorted(invalid_ids)


def event_view(
    event: object,
    include_relations: bool,
    include_state_relevant: bool,
    state_role: Optional[str] = None,
) -> Dict[str, object]:
    data: Dict[str, object] = {
        "event_id": event.event_id,
        "content": event.content,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "mentioned_at": event.mentioned_at,
        "updated_at": event.updated_at,
        "status": event.status,
    }
    if event.planned_for:
        data["planned_for"] = event.planned_for
    if include_relations:
        data["corrects"] = list(event.corrects)
        data["supersedes"] = list(event.supersedes)
    if include_state_relevant:
        data["state_relevant"] = event.state_relevant
    if state_role:
        data["state_role"] = state_role
    return data

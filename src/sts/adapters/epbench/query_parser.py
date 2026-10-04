from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class QueryPlan:
    mode: str = "single"
    answer_type: str = "full_event_details"
    mentioned_entities: list[str] = field(default_factory=list)
    mentioned_locations: list[str] = field(default_factory=list)
    mentioned_dates: list[str] = field(default_factory=list)
    mentioned_event_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_query_plan(question: str) -> QueryPlan:
    """Derive the control mode from question text, never benchmark metadata."""
    q = question.lower().strip()
    if any(cue in q for cue in ("last seen", "most recent", "latest")):
        mode = "latest"
    elif any(
        cue in q
        for cue in ("chronological order", "chronologically", "order of occurrence")
    ):
        mode = "chronological"
    elif (
        q.startswith(("list all", "enumerate", "name all"))
        or "provide a list of all" in q
        or "all events" in q
    ):
        mode = "all"
    else:
        mode = "single"

    if re.search(r"\b(when|date|dates|time|times)\b", q):
        answer_type = "times"
    elif re.search(r"\b(where|location|locations|place|places)\b", q):
        answer_type = "spaces"
    elif "other entit" in q:
        answer_type = "other_entities"
    elif re.search(r"\b(protagonist|protagonists|who|people|persons)\b", q):
        answer_type = "entities"
    elif "without describing" in q or "event type" in q:
        answer_type = "event_contents"
    else:
        answer_type = "full_event_details"

    return QueryPlan(
        mode=mode,
        answer_type=answer_type,
    )

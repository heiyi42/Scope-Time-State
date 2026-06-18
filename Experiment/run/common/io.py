from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from Experiment.run.common.models import Event, QueryCase
from Experiment.run.common.paths import PROJECT_DIR


def load_dotenv(path: Path = PROJECT_DIR / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def normalize_id_list(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value if item not in {None, "", "null"})
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if item not in {None, "", "null"})
    if value in {"", "null"}:
        return ()
    return (str(value),)


def build_event(row: Dict[str, object]) -> Event:
    return Event(
        event_id=str(row["event_id"]),
        scope_id=str(row["scope_id"]),
        content=str(row["content"]),
        event_type=str(row["event_type"]),
        occurred_at=str(row["occurred_at"]),
        mentioned_at=str(row["mentioned_at"]),
        updated_at=str(row["updated_at"]),
        status=str(row.get("status", "active")),
        planned_for=row.get("planned_for") if row.get("planned_for") is not None else None,
        deadline_at=row.get("deadline_at") if row.get("deadline_at") is not None else None,
        source_id=row.get("source_id") if row.get("source_id") is not None else None,
        metadata=dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {},
        corrects=normalize_id_list(row.get("corrects")),
        supersedes=normalize_id_list(row.get("supersedes")),
        state_relevant=bool(row.get("state_relevant", True)),
        has_status_annotation="status" in row,
        has_state_relevant_annotation="state_relevant" in row,
        has_relation_annotations="corrects" in row or "supersedes" in row,
    )


def load_events(path: Path) -> List[Event]:
    rows = json.loads(path.read_text())
    return [build_event(dict(row)) for row in rows]


def load_events_with_annotations(events_path: Path, annotations_path: Optional[Path]) -> List[Event]:
    if annotations_path is None or not annotations_path.exists():
        return load_events(events_path)
    rows = json.loads(events_path.read_text())
    annotations = {
        str(row["event_id"]): row
        for row in json.loads(annotations_path.read_text())
    }
    merged_rows: List[Dict[str, object]] = []
    for row in rows:
        merged = dict(row)
        annotation = annotations.get(str(row["event_id"]))
        if annotation:
            merged["status"] = annotation.get("event_status", "active")
            merged["state_relevant"] = bool(annotation.get("updates_state", True))
            merged["corrects"] = list(annotation.get("corrects", []))
            merged["supersedes"] = list(annotation.get("supersedes", []))
        merged_rows.append(merged)
    return [build_event(row) for row in merged_rows]


def load_cases(path: Path) -> List[QueryCase]:
    rows = json.loads(path.read_text())
    def support_values(raw: Dict[str, object]) -> Dict[str, Tuple[str, ...]]:
        normalized: Dict[str, Tuple[str, ...]] = {}
        for slot, value in raw.items():
            if isinstance(value, list):
                normalized[slot] = tuple(str(item) for item in value)
            else:
                normalized[slot] = (str(value),)
        return normalized

    return [
        QueryCase(
            case_id=row["case_id"],
            query=row["query"],
            scope_id=row["scope_id"],
            operation=row["operation"],
            time_roles=normalize_id_list(row.get("time_roles", row.get("time_role", "updated_at"))),
            output_slots=tuple(row.get("output_slots", [])),
            gold_events=normalize_id_list(row.get("gold_events")),
            gold_state_slots=dict(row["gold_state_slots"]),
            gold_slot_support=support_values(row["gold_slot_support"]),
            difficulty_tags=tuple(str(tag) for tag in row.get("difficulty_tags", [])),
            hard_negative_events=normalize_id_list(row.get("hard_negative_events")),
            answerability=str(row.get("answerability", "answerable")),
        )
        for row in rows
    ]


def validate_benchmark(events: Sequence[Event], cases: Sequence[QueryCase]) -> None:
    events_by_id = {event.event_id: event for event in events}
    errors: List[str] = []
    for case in cases:
        scoped_ids = {event.event_id for event in events if event.scope_id == case.scope_id}
        if not scoped_ids:
            errors.append(f"{case.case_id}: no events for scope_id={case.scope_id}")
        for event_id in case.gold_events:
            if event_id not in events_by_id:
                errors.append(f"{case.case_id}: gold event does not exist: {event_id}")
            elif event_id not in scoped_ids:
                errors.append(f"{case.case_id}: gold event outside scope: {event_id}")
        for slot in case.output_slots:
            if slot not in case.gold_state_slots:
                errors.append(f"{case.case_id}: missing gold_state_slots[{slot}]")
            if slot not in case.gold_slot_support:
                errors.append(f"{case.case_id}: missing gold_slot_support[{slot}]")
        for slot, event_ids in case.gold_slot_support.items():
            if slot not in case.output_slots:
                errors.append(f"{case.case_id}: support for unknown slot: {slot}")
            for event_id in event_ids:
                if event_id not in events_by_id:
                    errors.append(f"{case.case_id}: support event does not exist: {event_id}")
                elif event_id not in scoped_ids:
                    errors.append(f"{case.case_id}: support event outside scope: {event_id}")
                if event_id not in case.gold_events:
                    errors.append(f"{case.case_id}: support event not listed in gold_events: {event_id}")
    if errors:
        formatted = "\n".join(f"- {error}" for error in errors)
        raise RuntimeError(f"benchmark validation failed:\n{formatted}")

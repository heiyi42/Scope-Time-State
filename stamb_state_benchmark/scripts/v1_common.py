from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
LEGACY_DATA_DIR = BENCHMARK_DIR / "data"
DEFAULT_V0_DIR = BENCHMARK_DIR / "data" / "v0"
DEFAULT_V1_DIR = BENCHMARK_DIR / "data" / "v1"
DEFAULT_OUTPUT_DIR = BENCHMARK_DIR / "output"

RAW_EVENT_FIELDS = (
    "event_id",
    "scope_id",
    "content",
    "event_type",
    "occurred_at",
    "mentioned_at",
    "updated_at",
    "planned_for",
    "deadline_at",
    "source_id",
    "metadata",
)

EVENT_LEAKAGE_FIELDS = {
    "status",
    "state_relevant",
    "updates_state",
    "event_status",
    "corrects",
    "supersedes",
    "gold_events",
    "gold_slot_support",
    "gold_state_slots",
}

PUBLIC_CASE_FORBIDDEN_FIELDS = {
    "scope_id",
    "time_roles",
    "difficulty_tags",
    "gold_events",
    "gold_state_slots",
    "gold_slot_support",
    "hard_negative_events",
    "answerability",
    "output_slots",
    "gold_fields_usage",
}

TIME_ROLE_FIELDS = {"occurred_at", "mentioned_at", "updated_at", "planned_for", "deadline_at"}
ANSWERABILITY_VALUES = {"answerable", "unknown_current", "insufficient_evidence", "ambiguous"}
EVENT_STATUS_VALUES = {"active", "superseded", "uncertain", "deleted", "historical_only"}

DEFAULT_SCOPE_SPLITS = {
    "train": ["aaai_memory", "amp_project", "sql_lab_q6", "robot_nav", "thesis_ch2", "mobile_auth"],
    "dev": ["grant_app", "labeling_guideline"],
    "test": ["recsys_ablation", "deployment_incident"],
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_legacy_events(path: Path) -> List[Dict[str, Any]]:
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [dict(row) for row in rows]


def load_legacy_cases(path: Path) -> List[Dict[str, Any]]:
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [dict(row) for row in rows]


def normalize_id_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in {None, "", "null"}]
    if isinstance(value, tuple):
        return [str(item) for item in value if item not in {None, "", "null"}]
    if value in {"", "null"}:
        return []
    return [str(value)]


def normalize_slot_support(raw: Mapping[str, Any]) -> Dict[str, List[str]]:
    return {str(slot): normalize_id_list(value) for slot, value in raw.items()}


def event_time_value(event: Mapping[str, Any], field: str) -> str:
    value = event.get(field)
    return str(value) if value is not None else ""


def latest_event_for_scope(events: Sequence[Mapping[str, Any]], scope_id: str, time_field: str = "updated_at") -> Mapping[str, Any] | None:
    scoped = [event for event in events if event.get("scope_id") == scope_id]
    if not scoped:
        return None
    return max(scoped, key=lambda event: event_time_value(event, time_field))


def collect_case_event_ids(case: Mapping[str, Any]) -> Set[str]:
    ids: Set[str] = set(normalize_id_list(case.get("gold_events")))
    for values in normalize_slot_support(case.get("gold_slot_support", {})).values():
        ids.update(values)
    return ids


def text_features(text: str) -> Set[str]:
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    latin = re.findall(r"[A-Za-z0-9_]+", text.lower())
    return set(cjk + latin)


def keyword_overlap(a: str, b: str) -> int:
    return len(text_features(a) & text_features(b))


def infer_difficulty_tags(case: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> List[str]:
    tags: Set[str] = set()
    scope_id = str(case.get("scope_id", ""))
    gold_ids = set(normalize_id_list(case.get("gold_events")))
    support_ids = collect_case_event_ids(case)
    scoped_events = [event for event in events if event.get("scope_id") == scope_id]
    support_events = [event for event in scoped_events if event.get("event_id") in support_ids]
    latest = latest_event_for_scope(events, scope_id, str(case.get("time_role", "updated_at")))

    if latest and latest.get("event_id") not in gold_ids:
        tags.add("latest_event_vs_state")
    if latest and latest.get("state_relevant") is False:
        tags.update({"latest_event_vs_state", "non_update_latest"})
    if any(event.get("event_type") == "mention" and event.get("event_id") not in gold_ids for event in scoped_events):
        tags.add("stale_mention_distractor")
    if any(event.get("event_type") == "correction" or event.get("corrects") for event in support_events):
        tags.add("correction_aware")
    if str(case.get("operation")) == "state_summary" or len(case.get("output_slots", [])) > 1:
        tags.add("multi_facet_summary")
    if any("替代" in str(event.get("content", "")) or "转向" in str(event.get("content", "")) for event in support_events):
        tags.add("branch_pivot")
    if any(event.get("supersedes") or event.get("corrects") for event in support_events):
        tags.add("facet_specific_validity")
    if any(event.get("planned_for") for event in support_events):
        tags.add("cross_time_constraint")

    if not tags:
        tags.add("facet_specific_validity" if str(case.get("operation")) == "state_lookup" else "latest_event_vs_state")
    return sorted(tags)


def infer_hard_negative_events(case: Mapping[str, Any], events: Sequence[Mapping[str, Any]], limit: int = 3) -> List[str]:
    scope_id = str(case.get("scope_id", ""))
    gold_ids = set(normalize_id_list(case.get("gold_events")))
    query = str(case.get("query", ""))
    candidates: List[Tuple[int, str]] = []
    for event in events:
        event_id = str(event.get("event_id", ""))
        if event.get("scope_id") != scope_id or event_id in gold_ids:
            continue
        score = keyword_overlap(query, str(event.get("content", "")))
        if event.get("status") != "active":
            score += 4
        if event.get("state_relevant") is False:
            score += 3
        if event.get("event_type") in {"mention", "execution_log"}:
            score += 2
        if event.get("corrects") or event.get("supersedes"):
            score += 1
        if score > 0:
            candidates.append((score, event_id))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [event_id for _, event_id in candidates[:limit]]


def build_scope_splits(scopes: Iterable[str]) -> Dict[str, List[str]]:
    scope_set = set(scopes)
    default_scope_set = {scope for split_scopes in DEFAULT_SCOPE_SPLITS.values() for scope in split_scopes}
    if scope_set == default_scope_set:
        return {split: list(split_scopes) for split, split_scopes in DEFAULT_SCOPE_SPLITS.items()}

    ordered = sorted(scope_set)
    train_end = max(1, round(len(ordered) * 0.7))
    dev_end = max(train_end + 1, round(len(ordered) * 0.85)) if len(ordered) > 2 else train_end
    return {
        "train": ordered[:train_end],
        "dev": ordered[train_end:dev_end],
        "test": ordered[dev_end:],
    }


def summarize_counts(values: Iterable[Any], key_name: str) -> List[Dict[str, Any]]:
    return [{key_name: key, "n": count} for key, count in sorted(Counter(values).items(), key=lambda item: str(item[0]))]


def is_iso_timestamp_or_null(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True

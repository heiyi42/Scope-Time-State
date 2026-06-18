from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set

from v1_common import (
    ANSWERABILITY_VALUES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_V1_DIR,
    EVENT_LEAKAGE_FIELDS,
    EVENT_STATUS_VALUES,
    TIME_ROLE_FIELDS,
    is_iso_timestamp_or_null,
    normalize_id_list,
    read_json,
    write_json,
)


def duplicate_values(values: Sequence[str]) -> List[str]:
    return sorted([value for value, count in Counter(values).items() if count > 1])


def add_reference_errors(
    errors: List[str],
    owner: str,
    field: str,
    event_ids: Sequence[str],
    events_by_id: Mapping[str, Mapping[str, Any]],
    expected_scope: str | None = None,
) -> None:
    for event_id in event_ids:
        event = events_by_id.get(event_id)
        if event is None:
            errors.append(f"{owner}: {field} references missing event_id={event_id}")
        elif expected_scope is not None and event.get("scope_id") != expected_scope:
            errors.append(f"{owner}: {field} references event outside scope: {event_id}")


def validate_events_raw(events: Sequence[Mapping[str, Any]], errors: List[str]) -> None:
    for event in events:
        event_id = str(event.get("event_id", "<missing>"))
        leaked = sorted(EVENT_LEAKAGE_FIELDS & set(event.keys()))
        if leaked:
            errors.append(f"{event_id}: events_raw leaks fields {leaked}")
        for field in ("occurred_at", "mentioned_at", "updated_at", "planned_for", "deadline_at"):
            if not is_iso_timestamp_or_null(event.get(field)):
                errors.append(f"{event_id}: {field} is not ISO timestamp or null")
        if "metadata" not in event or not isinstance(event.get("metadata"), dict):
            errors.append(f"{event_id}: metadata must be an object")


def validate_event_annotations(
    annotations: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
    errors: List[str],
) -> None:
    annotation_ids = [str(annotation.get("event_id")) for annotation in annotations]
    for duplicate in duplicate_values(annotation_ids):
        errors.append(f"duplicate event annotation for event_id={duplicate}")
    if set(annotation_ids) != set(events_by_id):
        missing = sorted(set(events_by_id) - set(annotation_ids))
        extra = sorted(set(annotation_ids) - set(events_by_id))
        if missing:
            errors.append(f"missing event_annotations for {missing}")
        if extra:
            errors.append(f"event_annotations for unknown events {extra}")

    for annotation in annotations:
        event_id = str(annotation.get("event_id", "<missing>"))
        if not isinstance(annotation.get("updates_state"), bool):
            errors.append(f"{event_id}: updates_state must be bool")
        if annotation.get("event_status") not in EVENT_STATUS_VALUES:
            errors.append(f"{event_id}: invalid event_status={annotation.get('event_status')}")
        add_reference_errors(errors, event_id, "corrects", normalize_id_list(annotation.get("corrects")), events_by_id)
        add_reference_errors(errors, event_id, "supersedes", normalize_id_list(annotation.get("supersedes")), events_by_id)


def validate_cases(
    cases: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
    errors: List[str],
) -> None:
    case_ids = [str(case.get("case_id")) for case in cases]
    for duplicate in duplicate_values(case_ids):
        errors.append(f"duplicate case_id={duplicate}")

    scopes = {str(event.get("scope_id")) for event in events_by_id.values()}
    for case in cases:
        case_id = str(case.get("case_id", "<missing>"))
        scope_id = str(case.get("scope_id", ""))
        if scope_id not in scopes:
            errors.append(f"{case_id}: scope_id has no events: {scope_id}")
        time_roles = case.get("time_roles")
        if not isinstance(time_roles, list) or not time_roles:
            errors.append(f"{case_id}: time_roles must be a non-empty list")
        else:
            for role in time_roles:
                if role not in TIME_ROLE_FIELDS:
                    errors.append(f"{case_id}: invalid time_role={role}")
        if not isinstance(case.get("difficulty_tags"), list) or not case.get("difficulty_tags"):
            errors.append(f"{case_id}: difficulty_tags must be a non-empty list")
        if case.get("answerability") not in ANSWERABILITY_VALUES:
            errors.append(f"{case_id}: invalid answerability={case.get('answerability')}")

        gold_events = normalize_id_list(case.get("gold_events"))
        hard_negatives = normalize_id_list(case.get("hard_negative_events"))
        add_reference_errors(errors, case_id, "gold_events", gold_events, events_by_id, expected_scope=scope_id)
        add_reference_errors(errors, case_id, "hard_negative_events", hard_negatives, events_by_id, expected_scope=scope_id)
        overlap = sorted(set(gold_events) & set(hard_negatives))
        if overlap:
            errors.append(f"{case_id}: hard_negative_events overlap gold_events: {overlap}")

        gold_slot_support = case.get("gold_slot_support", {})
        if not isinstance(gold_slot_support, dict):
            errors.append(f"{case_id}: gold_slot_support must be an object")
            continue
        output_slots = set(str(slot) for slot in case.get("output_slots", []))
        for slot in output_slots:
            if slot not in case.get("gold_state_slots", {}):
                errors.append(f"{case_id}: missing gold_state_slots[{slot}]")
            if slot not in gold_slot_support:
                errors.append(f"{case_id}: missing gold_slot_support[{slot}]")
        for slot, event_ids in gold_slot_support.items():
            support_ids = normalize_id_list(event_ids)
            if str(slot) not in output_slots:
                errors.append(f"{case_id}: support for unknown output slot {slot}")
            add_reference_errors(errors, case_id, f"gold_slot_support[{slot}]", support_ids, events_by_id, expected_scope=scope_id)
            missing_from_gold = sorted(set(support_ids) - set(gold_events))
            if missing_from_gold:
                errors.append(f"{case_id}: support events not listed in gold_events: {missing_from_gold}")


def validate_claim_annotations(
    claims: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
    errors: List[str],
) -> None:
    claim_ids = [str(claim.get("claim_id")) for claim in claims]
    for duplicate in duplicate_values(claim_ids):
        errors.append(f"duplicate claim_id={duplicate}")
    for claim in claims:
        claim_id = str(claim.get("claim_id", "<missing>"))
        add_reference_errors(errors, claim_id, "source_event_ids", normalize_id_list(claim.get("source_event_ids")), events_by_id)
        for field in ("valid_from", "valid_to"):
            if not is_iso_timestamp_or_null(claim.get(field)):
                errors.append(f"{claim_id}: {field} is not ISO timestamp or null")


def validate_splits(
    splits: Mapping[str, Sequence[str]],
    cases: Sequence[Mapping[str, Any]],
    event_scopes: Set[str],
    errors: List[str],
) -> None:
    split_names = {"train", "dev", "test"}
    if set(splits.keys()) != split_names:
        errors.append(f"splits must contain exactly {sorted(split_names)}")
    assigned: Dict[str, str] = {}
    for split, scopes in splits.items():
        for scope in scopes:
            if scope in assigned:
                errors.append(f"scope appears in multiple splits: {scope}")
            assigned[str(scope)] = split
            if scope not in event_scopes:
                errors.append(f"{split}: unknown scope={scope}")
    missing = sorted(event_scopes - set(assigned))
    if missing:
        errors.append(f"scopes missing from splits: {missing}")

    cases_by_split: Dict[str, List[Mapping[str, Any]]] = {split: [] for split in split_names}
    for case in cases:
        split = assigned.get(str(case.get("scope_id")))
        if split:
            cases_by_split[split].append(case)
    for split, split_cases in cases_by_split.items():
        if not split_cases:
            errors.append(f"{split}: has no cases")
            continue
        if not any(case.get("operation") in {"state_summary", "state_lookup"} for case in split_cases):
            errors.append(f"{split}: lacks state_summary/state_lookup cases")


def validate(v1_dir: Path) -> Dict[str, Any]:
    events = read_json(v1_dir / "events_raw.json")
    event_annotations = read_json(v1_dir / "event_annotations.json")
    claim_annotations = read_json(v1_dir / "claim_annotations.json")
    cases = read_json(v1_dir / "cases.json")
    splits = read_json(v1_dir / "splits.json")

    errors: List[str] = []
    event_ids = [str(event.get("event_id")) for event in events]
    for duplicate in duplicate_values(event_ids):
        errors.append(f"duplicate event_id={duplicate}")
    events_by_id = {str(event.get("event_id")): event for event in events}

    validate_events_raw(events, errors)
    validate_event_annotations(event_annotations, events_by_id, errors)
    validate_claim_annotations(claim_annotations, events_by_id, errors)
    validate_cases(cases, events_by_id, errors)
    validate_splits(splits, cases, {str(event.get("scope_id")) for event in events}, errors)

    return {
        "v1_dir": str(v1_dir),
        "ok": not errors,
        "event_count": len(events),
        "case_count": len(cases),
        "claim_annotation_count": len(claim_annotations),
        "split_scope_counts": {split: len(scopes) for split, scopes in splits.items()},
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate STAMB-State v1 scaffold files.")
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR / "validation_report.json")
    args = parser.parse_args()

    report = validate(args.v1_dir)
    write_json(args.out, report)
    print(f"ok={report['ok']} events={report['event_count']} cases={report['case_count']}")
    print(f"wrote {args.out}")
    if report["errors"]:
        print("errors:")
        for error in report["errors"]:
            print(f"- {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

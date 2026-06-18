from __future__ import annotations

from typing import Dict, Iterable, List, Set, Tuple

from Experiment.run.common.io import normalize_id_list


def dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    deduped: List[str] = []
    for value in values:
        text = str(value)
        if text in seen or text in {"", "null"}:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def minimize_locked_state_evidence(locked_raw: Dict[str, object], case: QueryCase) -> Dict[str, object]:
    minimized = deepcopy(locked_raw)
    original_evidence = dedupe_preserve_order(normalize_id_list(minimized.get("evidence_events")))
    raw_slots = minimized.get("state_slots", {})
    support_union: List[str] = []
    if isinstance(raw_slots, dict):
        for slot in case.output_slots:
            item = raw_slots.get(slot)
            if not isinstance(item, dict):
                continue
            support_events = dedupe_preserve_order(normalize_support_events(item))
            item["support_events"] = support_events
            item["support_event"] = support_events[0] if support_events else None
            support_union.extend(support_events)
    minimized_evidence = dedupe_preserve_order(support_union)
    minimized["evidence_events"] = minimized_evidence
    trace = minimized.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["evidence_minimizer"] = {
        "policy": "evidence_events_exact_union_of_slot_support_events",
        "original_evidence_events": original_evidence,
        "minimized_evidence_events": minimized_evidence,
        "removed_evidence_events": [
            event_id for event_id in original_evidence if event_id not in set(minimized_evidence)
        ],
    }
    minimized["pipeline_trace"] = trace
    return minimized


def normalize_support_events(item: Dict[str, object]) -> Tuple[str, ...]:
    raw_events = item.get("support_events")
    support_events: List[str] = []
    if isinstance(raw_events, list):
        support_events = [str(event_id) for event_id in raw_events if event_id not in {None, "", "null"}]
    support = item.get("support_event")
    if support not in {None, "", "null"}:
        support_text = str(support)
        if support_text not in support_events:
            support_events.insert(0, support_text)
    return tuple(support_events)

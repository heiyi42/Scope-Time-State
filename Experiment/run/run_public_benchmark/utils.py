from __future__ import annotations

from typing import Dict, List, Sequence, Tuple


def public_visible_event_ids(visible_events: Sequence[Dict[str, object]]) -> set[str]:
    return {
        str(event.get("event_id"))
        for event in visible_events
        if isinstance(event, dict) and event.get("event_id") not in {None, "", "null"}
    }


def public_visible_event_id_repair_map(visible_events: Sequence[Dict[str, object]]) -> Dict[str, str]:
    suffix_candidates: Dict[str, set[str]] = {}
    for event_id in public_visible_event_ids(visible_events):
        suffixes = {event_id.rsplit("_", 1)[-1]}
        if "_" in event_id:
            suffixes.add(event_id.split("_", 1)[1])
        for suffix in suffixes:
            if not suffix or suffix == event_id:
                continue
            suffix_candidates.setdefault(suffix, set()).add(event_id)
    return {
        suffix: next(iter(candidates))
        for suffix, candidates in suffix_candidates.items()
        if len(candidates) == 1
    }


def normalize_id_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in {None, "", "null"}]


def normalize_public_output(raw: Dict[str, object]) -> Tuple[List[str], List[Dict[str, object]], str]:
    raw_facets = raw.get("facets", [])
    facets: List[Dict[str, object]] = []
    if isinstance(raw_facets, list):
        for index, item in enumerate(raw_facets):
            if not isinstance(item, dict):
                continue
            support_events = normalize_id_list(item.get("support_events"))
            support_event = item.get("support_event")
            if support_event not in {None, "", "null"} and str(support_event) not in support_events:
                support_events.insert(0, str(support_event))
            facets.append(
                {
                    "index": index,
                    "name": str(item.get("name", f"facet_{index + 1}")),
                    "value": str(item.get("value", "")),
                    "support_events": support_events,
                }
            )
    raw_state_slots = raw.get("state_slots", {})
    if not facets and isinstance(raw_state_slots, dict):
        for index, (name, item) in enumerate(raw_state_slots.items()):
            if isinstance(item, dict):
                facets.append(
                    {
                        "index": index,
                        "name": str(name),
                        "value": str(item.get("value", "")),
                        "support_events": normalize_id_list(item.get("support_events")),
                    }
                )
            else:
                facets.append(
                    {
                        "index": index,
                        "name": str(name),
                        "value": str(item),
                        "support_events": [],
                    }
                )
    evidence = normalize_id_list(raw.get("evidence_events"))
    for facet in facets:
        for event_id in facet["support_events"]:
            if event_id not in evidence:
                evidence.append(event_id)
    return evidence, facets, str(raw.get("answer", ""))

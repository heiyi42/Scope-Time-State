from __future__ import annotations

from copy import deepcopy
import json
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from Experiment.common import BaselinePromptSpec
from Experiment.run.common.io import normalize_id_list
from Experiment.run.common.llm_client import LLMClient
from Experiment.run.common.models import QueryCase
from Experiment.run.common.metrics import declared_evidence_events
from Experiment.run.common.utils import dedupe_preserve_order, normalize_support_events
from Experiment.run.run_oracle_benchmark.prompts import retriever_system_prompt, user_prompt


def event_ids_from_visible_events(visible_events: Sequence[Dict[str, object]]) -> Set[str]:
    return {
        str(event.get("event_id"))
        for event in visible_events
        if isinstance(event, dict) and event.get("event_id") not in {None, "", "null"}
    }


def visible_event_id_repair_map(visible_events: Sequence[Dict[str, object]]) -> Dict[str, str]:
    suffix_candidates: Dict[str, Set[str]] = {}
    for event_id in event_ids_from_visible_events(visible_events):
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


def validate_and_repair_event_ids(
    raw: Dict[str, object],
    visible_events: Sequence[Dict[str, object]],
    case: QueryCase,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    visible_ids = event_ids_from_visible_events(visible_events)
    repair_map = visible_event_id_repair_map(visible_events)
    repaired_raw = deepcopy(raw)
    repairs: List[Dict[str, str]] = []
    dropped_invalid: List[Dict[str, str]] = []

    def repair_one(event_id: object, field: str) -> Optional[str]:
        if event_id in {None, "", "null"}:
            return None
        text = str(event_id)
        if text in visible_ids:
            return text
        replacement = repair_map.get(text)
        if replacement is not None:
            repairs.append({"field": field, "from": text, "to": replacement})
            return replacement
        dropped_invalid.append({"field": field, "event_id": text})
        return None

    def repair_list(raw_events: object, field: str) -> List[str]:
        fixed: List[str] = []
        for index, event_id in enumerate(normalize_id_list(raw_events)):
            repaired = repair_one(event_id, f"{field}[{index}]")
            if repaired is not None and repaired not in fixed:
                fixed.append(repaired)
        return fixed

    repaired_raw["evidence_events"] = repair_list(repaired_raw.get("evidence_events"), "evidence_events")
    raw_slots = repaired_raw.get("state_slots", {})
    if isinstance(raw_slots, dict):
        for slot in case.output_slots:
            item = raw_slots.get(slot)
            if not isinstance(item, dict):
                continue
            support_events = repair_list(
                normalize_support_events(item),
                f"state_slots.{slot}.support_events",
            )
            item["support_events"] = support_events
            item["support_event"] = support_events[0] if support_events else None

    if dropped_invalid:
        status = "invalid_removed"
    elif repairs:
        status = "repaired"
    else:
        status = "ok"
    trace = repaired_raw.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    event_id_validation = {
        "status": status,
        "visible_event_count": len(visible_ids),
        "repairs": repairs,
        "dropped_invalid_event_ids": dropped_invalid,
    }
    trace["event_id_validation"] = event_id_validation
    repaired_raw["pipeline_trace"] = trace
    return repaired_raw, event_id_validation


def raw_support_sets(raw: Dict[str, object], case: QueryCase) -> Dict[str, Tuple[str, ...]]:
    raw_slots = raw.get("state_slots", {})
    if not isinstance(raw_slots, dict):
        return {}
    supports: Dict[str, Tuple[str, ...]] = {}
    for slot in case.output_slots:
        item = raw_slots.get(slot)
        if isinstance(item, dict):
            supports[slot] = normalize_support_events(item)
    return supports


def declared_events_from_raw(raw: Dict[str, object], case: QueryCase) -> Set[str]:
    return declared_evidence_events(
        normalize_id_list(raw.get("evidence_events")),
        raw_support_sets(raw, case),
    )


def restrict_auditor_to_candidate_events(
    audited_raw: Dict[str, object],
    candidate_locked_state: Dict[str, object],
    case: QueryCase,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    allowed_events = declared_events_from_raw(candidate_locked_state, case)
    restricted = deepcopy(audited_raw)
    dropped: List[Dict[str, str]] = []

    def keep_allowed(events: Iterable[str], field: str) -> List[str]:
        kept: List[str] = []
        for index, event_id in enumerate(events):
            text = str(event_id)
            if text in allowed_events:
                if text not in kept:
                    kept.append(text)
            else:
                dropped.append({"field": f"{field}[{index}]", "event_id": text})
        return kept

    raw_slots = restricted.get("state_slots", {})
    support_union: List[str] = []
    if isinstance(raw_slots, dict):
        for slot in case.output_slots:
            item = raw_slots.get(slot)
            if not isinstance(item, dict):
                continue
            support_events = keep_allowed(
                normalize_support_events(item),
                f"state_slots.{slot}.support_events",
            )
            item["support_events"] = support_events
            item["support_event"] = support_events[0] if support_events else None
            support_union.extend(support_events)
    candidate_evidence = keep_allowed(
        normalize_id_list(restricted.get("evidence_events")),
        "evidence_events",
    )
    if support_union:
        restricted["evidence_events"] = dedupe_preserve_order(support_union)
    else:
        restricted["evidence_events"] = candidate_evidence

    trace = restricted.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    subset_guard = {
        "status": "dropped_added_events" if dropped else "ok",
        "allowed_event_count": len(allowed_events),
        "dropped_events_not_in_candidate": dropped,
    }
    trace["support_auditor_subset_guard"] = subset_guard
    restricted["pipeline_trace"] = trace
    return restricted, subset_guard


def retriever_retry_user_prompt(
    spec: BaselinePromptSpec,
    case: QueryCase,
    validation_trace: Dict[str, object],
) -> str:
    payload = json.loads(user_prompt(spec, case))
    payload["visible_event_ids"] = sorted(event_ids_from_visible_events(spec.visible_events))
    payload["previous_output_error"] = {
        "problem": "previous retriever output used event ids that are not in visible_event_ids",
        "dropped_invalid_event_ids": validation_trace.get("dropped_invalid_event_ids", []),
        "required_fix": (
            "Rewrite the full JSON. Every evidence_events/support_event/support_events value must be copied "
            "exactly from visible_event_ids. Do not use short ids such as e1/e2/e3."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def complete_validated_retriever(
    client: LLMClient,
    spec: BaselinePromptSpec,
    case: QueryCase,
    readout_policy: str,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    system = retriever_system_prompt(readout_policy)
    raw = client.complete_json(system, user_prompt(spec, case))
    repaired, validation = validate_and_repair_event_ids(raw, spec.visible_events, case)
    if validation["dropped_invalid_event_ids"]:
        retry_raw = client.complete_json(system, retriever_retry_user_prompt(spec, case, validation))
        retry_repaired, retry_validation = validate_and_repair_event_ids(retry_raw, spec.visible_events, case)
        retry_validation["retry_after_invalid_event_ids"] = {
            "initial_validation": validation,
            "retry_used": True,
        }
        retry_trace = retry_repaired.get("pipeline_trace", {})
        if not isinstance(retry_trace, dict):
            retry_trace = {}
        retry_trace["event_id_validation"] = retry_validation
        retry_repaired["pipeline_trace"] = retry_trace
        return retry_repaired, retry_validation
    return repaired, validation

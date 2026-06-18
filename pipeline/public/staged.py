from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional, Sequence, Tuple

from Experiment.common import BaselinePromptSpec
from Experiment.run.common.llm_client import LLMClient
from Experiment.run.common.utils import dedupe_preserve_order
from Experiment.run.run_public_benchmark.prompts import (
    public_composer_system_prompt,
    public_composer_user_prompt,
    public_retriever_system_prompt,
    public_retriever_user_prompt,
    public_verifier_system_prompt,
    public_verifier_user_prompt,
)
from Experiment.run.run_public_benchmark.types import PublicCase
from Experiment.run.run_public_benchmark.utils import (
    normalize_id_list,
    normalize_public_output,
    public_visible_event_id_repair_map,
    public_visible_event_ids,
)


def validate_and_repair_public_event_ids(
    raw: Dict[str, object],
    visible_events: Sequence[Dict[str, object]],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    visible_ids = public_visible_event_ids(visible_events)
    repair_map = public_visible_event_id_repair_map(visible_events)
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

    support_union: List[str] = []
    raw_facets = repaired_raw.get("facets", [])
    if isinstance(raw_facets, list):
        for index, item in enumerate(raw_facets):
            if not isinstance(item, dict):
                continue
            support_events = repair_list(item.get("support_events"), f"facets[{index}].support_events")
            support_event = repair_one(item.get("support_event"), f"facets[{index}].support_event")
            if support_event is not None and support_event not in support_events:
                support_events.insert(0, support_event)
            item["support_events"] = support_events
            item["support_event"] = support_events[0] if support_events else None
            support_union.extend(support_events)

    repaired_evidence = repair_list(repaired_raw.get("evidence_events"), "evidence_events")
    repaired_raw["evidence_events"] = dedupe_preserve_order(support_union) if support_union else repaired_evidence

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


def complete_validated_public_retriever(
    client: LLMClient,
    spec: BaselinePromptSpec,
    case: PublicCase,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    system = public_retriever_system_prompt()
    raw = client.complete_json(system, public_retriever_user_prompt(spec, case))
    repaired, validation = validate_and_repair_public_event_ids(raw, spec.visible_events)
    if validation["dropped_invalid_event_ids"]:
        retry_raw = client.complete_json(system, public_retriever_user_prompt(spec, case, validation))
        retry_repaired, retry_validation = validate_and_repair_public_event_ids(retry_raw, spec.visible_events)
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


def merge_public_state_with_answer(
    locked_raw: Dict[str, object],
    composer_raw: Dict[str, object],
    verifier_raw: Dict[str, object],
) -> Dict[str, object]:
    evidence_events, facets, _ = normalize_public_output(locked_raw)
    trace = locked_raw.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["public_composer_output"] = composer_raw
    trace["public_verifier_output"] = verifier_raw
    return {
        "evidence_events": evidence_events,
        "facets": facets,
        "coverage_check": verifier_raw.get("coverage_check", composer_raw.get("coverage_check", {})),
        "answer": str(verifier_raw.get("answer", composer_raw.get("answer", ""))),
        "pipeline_trace": trace,
    }


def run_public_ours_pipeline(
    client: LLMClient,
    spec: BaselinePromptSpec,
    case: PublicCase,
    router_raw: Optional[Dict[str, object]],
    routed_scope: Optional[str],
    routed_time_role: Optional[str],
) -> Dict[str, object]:
    locked_raw, retriever_validation = complete_validated_public_retriever(client, spec, case)
    trace = locked_raw.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace.update(
        {
            "pipeline": "public_scope_time_state_staged",
            "scope_router_output": router_raw,
            "routed_scope": routed_scope,
            "inferred_time_role": routed_time_role,
            "public_retriever_output": {
                "evidence_events": locked_raw.get("evidence_events", []),
                "facets": locked_raw.get("facets", []),
            },
            "public_retriever_event_id_validation": retriever_validation,
        }
    )
    locked_raw["pipeline_trace"] = trace
    composer_raw = client.complete_json(public_composer_system_prompt(), public_composer_user_prompt(case, locked_raw))
    verifier_raw = client.complete_json(
        public_verifier_system_prompt(),
        public_verifier_user_prompt(case, locked_raw, composer_raw),
    )
    return merge_public_state_with_answer(locked_raw, composer_raw, verifier_raw)

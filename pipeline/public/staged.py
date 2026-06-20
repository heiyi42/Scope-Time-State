from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional, Sequence, Tuple

from Experiment.common import BaselinePromptSpec
from Experiment.run.common.llm_client import LLMClient
from Experiment.run.common.utils import dedupe_preserve_order
from Experiment.run.run_public_benchmark.prompts import (
    public_composer_system_prompt,
    public_composer_user_prompt,
    public_state_facet_repair_system_prompt,
    public_state_facet_repair_user_prompt,
    public_state_packet_system_prompt,
    public_state_packet_user_prompt,
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


STATE_PACKET_KEYS = (
    "predicted_scope",
    "time_roles",
    "candidate_events",
    "claims",
    "relations",
    "rejected_claims",
    "state_facets",
)


def raw_state_packet(raw: Dict[str, object]) -> Dict[str, object]:
    packet = raw.get("state_packet")
    if isinstance(packet, dict):
        return deepcopy(packet)
    return {key: deepcopy(raw[key]) for key in STATE_PACKET_KEYS if key in raw}


def state_facet_items(raw_facets: object) -> List[Dict[str, object]]:
    facets: List[Dict[str, object]] = []
    if isinstance(raw_facets, dict):
        for name, item in raw_facets.items():
            if isinstance(item, dict):
                facet = deepcopy(item)
            else:
                facet = {"value": str(item)}
            facet.setdefault("name", str(name))
            facets.append(facet)
    elif isinstance(raw_facets, list):
        for index, item in enumerate(raw_facets):
            if not isinstance(item, dict):
                continue
            facet = deepcopy(item)
            facet.setdefault("name", str(facet.get("facet_type", f"facet_{index + 1}")))
            facets.append(facet)
    return facets


def visible_event_id_order(visible_events: Sequence[Dict[str, object]]) -> List[str]:
    return [
        str(event.get("event_id"))
        for event in visible_events
        if isinstance(event, dict) and event.get("event_id") not in {None, "", "null"}
    ]


def validate_and_repair_public_state_packet(
    raw: Dict[str, object],
    visible_events: Sequence[Dict[str, object]],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    visible_ids = public_visible_event_ids(visible_events)
    visible_order = visible_event_id_order(visible_events)
    repair_map = public_visible_event_id_repair_map(visible_events)
    repaired_raw = deepcopy(raw)
    packet = raw_state_packet(raw)
    repairs: List[Dict[str, str]] = []
    dropped_invalid: List[Dict[str, str]] = []
    schema_warnings: List[str] = []

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

    if not packet:
        schema_warnings.append("missing_state_packet")

    candidate_events = repair_list(packet.get("candidate_events"), "state_packet.candidate_events")
    if not candidate_events:
        candidate_events = list(visible_order)

    raw_claims = packet.get("claims", [])
    repaired_claims: List[Dict[str, object]] = []
    if isinstance(raw_claims, list):
        for index, item in enumerate(raw_claims):
            if not isinstance(item, dict):
                continue
            claim = deepcopy(item)
            claim_id = str(claim.get("claim_id") or f"claim_{len(repaired_claims) + 1}")
            claim["claim_id"] = claim_id
            event_id = repair_one(claim.get("event_id"), f"state_packet.claims[{index}].event_id")
            if event_id is not None:
                claim["event_id"] = event_id
            elif claim.get("event_id") not in {None, "", "null"}:
                continue
            repaired_claims.append(claim)
    else:
        schema_warnings.append("claims_not_list")
    claims_by_id = {
        str(claim.get("claim_id")): claim
        for claim in repaired_claims
        if claim.get("claim_id") not in {None, "", "null"}
    }

    raw_relations = packet.get("relations", [])
    repaired_relations: List[Dict[str, object]] = []
    if isinstance(raw_relations, list):
        for index, item in enumerate(raw_relations):
            if not isinstance(item, dict):
                continue
            relation = deepcopy(item)
            relation["evidence_event_ids"] = repair_list(
                relation.get("evidence_event_ids"),
                f"state_packet.relations[{index}].evidence_event_ids",
            )
            repaired_relations.append(relation)
    elif raw_relations is not None and raw_relations != "":
        schema_warnings.append("relations_not_list")

    raw_rejected = packet.get("rejected_claims", [])
    repaired_rejected: List[Dict[str, object]] = []
    if isinstance(raw_rejected, list):
        for index, item in enumerate(raw_rejected):
            if not isinstance(item, dict):
                continue
            rejected = deepcopy(item)
            event_id = repair_one(rejected.get("event_id"), f"state_packet.rejected_claims[{index}].event_id")
            if event_id is not None:
                rejected["event_id"] = event_id
            elif rejected.get("event_id") not in {None, "", "null"}:
                continue
            repaired_rejected.append(rejected)
    elif raw_rejected is not None and raw_rejected != "":
        schema_warnings.append("rejected_claims_not_list")

    support_union: List[str] = []
    repaired_state_facets: List[Dict[str, object]] = []
    raw_facets = state_facet_items(packet.get("state_facets"))
    if not raw_facets:
        schema_warnings.append("missing_state_facets")
    for index, item in enumerate(raw_facets):
        facet = deepcopy(item)
        support_events = repair_list(facet.get("support_events"), f"state_packet.state_facets[{index}].support_events")
        support_event = repair_one(facet.get("support_event"), f"state_packet.state_facets[{index}].support_event")
        if support_event is not None and support_event not in support_events:
            support_events.insert(0, support_event)
        if not support_events:
            for claim_id in normalize_id_list(facet.get("support_claims")):
                claim = claims_by_id.get(claim_id)
                if not isinstance(claim, dict):
                    continue
                event_id = claim.get("event_id")
                if event_id not in {None, "", "null"} and str(event_id) not in support_events:
                    support_events.append(str(event_id))
        facet["name"] = str(facet.get("name") or facet.get("facet_type") or f"facet_{index + 1}")
        facet["value"] = str(facet.get("value", ""))
        facet["status"] = str(facet.get("status", "active"))
        facet["support_events"] = support_events
        facet["support_event"] = support_events[0] if support_events else None
        repaired_state_facets.append(facet)
        support_union.extend(support_events)

    repaired_evidence = repair_list(
        repaired_raw.get("evidence_events", packet.get("evidence_events")),
        "evidence_events",
    )
    packet["candidate_events"] = candidate_events
    packet["claims"] = repaired_claims
    packet["relations"] = repaired_relations
    packet["rejected_claims"] = repaired_rejected
    packet["state_facets"] = repaired_state_facets
    if not isinstance(packet.get("predicted_scope"), dict):
        packet["predicted_scope"] = {}
    raw_time_roles = packet.get("time_roles")
    if isinstance(raw_time_roles, list):
        packet["time_roles"] = normalize_id_list(raw_time_roles)
    elif raw_time_roles in {None, "", "null"}:
        packet["time_roles"] = []
    else:
        packet["time_roles"] = [str(raw_time_roles)]

    derived_facets = [
        {
            "index": index,
            "name": str(facet.get("name", f"facet_{index + 1}")),
            "value": str(facet.get("value", "")),
            "status": str(facet.get("status", "active")),
            "support_events": normalize_id_list(facet.get("support_events")),
        }
        for index, facet in enumerate(repaired_state_facets)
    ]
    if not derived_facets and isinstance(repaired_raw.get("facets"), list):
        schema_warnings.append("used_legacy_facets_fallback")
        for index, item in enumerate(repaired_raw.get("facets", [])):
            if not isinstance(item, dict):
                continue
            support_events = repair_list(item.get("support_events"), f"facets[{index}].support_events")
            derived_facets.append(
                {
                    "index": index,
                    "name": str(item.get("name", f"facet_{index + 1}")),
                    "value": str(item.get("value", "")),
                    "status": "active",
                    "support_events": support_events,
                }
            )
            support_union.extend(support_events)

    repaired_raw["state_packet"] = packet
    repaired_raw["facets"] = derived_facets
    repaired_raw["evidence_events"] = dedupe_preserve_order(support_union) if support_union else repaired_evidence

    if dropped_invalid:
        status = "invalid_removed"
    elif repairs:
        status = "repaired"
    elif schema_warnings:
        status = "schema_warning"
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
        "schema_warnings": schema_warnings,
        "state_packet_invariants": {
            "candidate_events_visible": all(event_id in visible_ids for event_id in candidate_events),
            "claims_have_visible_event_ids": all(
                claim.get("event_id") in visible_ids
                for claim in repaired_claims
                if claim.get("event_id") not in {None, "", "null"}
            ),
            "state_facets_have_support_events": all(
                bool(facet.get("support_events")) or facet.get("status") == "insufficient_evidence"
                for facet in repaired_state_facets
            ),
            "facet_count": len(repaired_state_facets),
            "claim_count": len(repaired_claims),
            "relation_count": len(repaired_relations),
            "rejected_claim_count": len(repaired_rejected),
        },
    }
    trace["event_id_validation"] = event_id_validation
    repaired_raw["pipeline_trace"] = trace
    return repaired_raw, event_id_validation


def needs_state_facet_repair(validation: Dict[str, object]) -> bool:
    warnings = validation.get("schema_warnings", [])
    invariants = validation.get("state_packet_invariants", {})
    return "missing_state_facets" in warnings or invariants.get("facet_count") == 0


def state_packet_validation_quality(validation: Dict[str, object]) -> Tuple[int, int, int, int]:
    invariants = validation.get("state_packet_invariants", {})
    facet_count = int(invariants.get("facet_count") or 0)
    claim_count = int(invariants.get("claim_count") or 0)
    dropped_count = len(validation.get("dropped_invalid_event_ids", []) or [])
    warning_count = len(validation.get("schema_warnings", []) or [])
    return facet_count, -dropped_count, claim_count, -warning_count


def choose_state_packet_candidate(
    initial: Tuple[Dict[str, object], Dict[str, object]],
    retry: Tuple[Dict[str, object], Dict[str, object]],
) -> Tuple[str, Dict[str, object], Dict[str, object]]:
    initial_raw, initial_validation = initial
    retry_raw, retry_validation = retry
    if state_packet_validation_quality(retry_validation) > state_packet_validation_quality(initial_validation):
        return "retry", retry_raw, retry_validation
    return "initial", initial_raw, initial_validation


def repair_missing_public_state_facets(
    client: LLMClient,
    spec: BaselinePromptSpec,
    case: PublicCase,
    locked_raw: Dict[str, object],
    validation: Dict[str, object],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    raw = client.complete_json(
        public_state_facet_repair_system_prompt(),
        public_state_facet_repair_user_prompt(case, locked_raw, validation, spec.visible_events),
    )
    repaired_input = deepcopy(locked_raw)
    packet = raw_state_packet(repaired_input)
    raw_facets = raw.get("state_facets")
    if raw_facets is None and isinstance(raw.get("state_packet"), dict):
        raw_facets = raw["state_packet"].get("state_facets")
    if raw_facets is None:
        raw_facets = raw.get("facets", [])
    packet["state_facets"] = raw_facets
    repaired_input["state_packet"] = packet
    repaired, repair_validation = validate_and_repair_public_state_packet(repaired_input, spec.visible_events)
    trace = repaired.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["public_state_facet_repair_output"] = raw
    trace["public_state_facet_repair_validation"] = repair_validation
    repaired["pipeline_trace"] = trace
    return repaired, repair_validation


def complete_validated_public_state_packet(
    client: LLMClient,
    spec: BaselinePromptSpec,
    case: PublicCase,
    routed_scope: Optional[str],
    routed_time_role: Optional[str],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    system = public_state_packet_system_prompt()
    raw = client.complete_json(system, public_state_packet_user_prompt(spec, case, routed_scope, routed_time_role))
    repaired, validation = validate_and_repair_public_state_packet(raw, spec.visible_events)
    if validation["dropped_invalid_event_ids"] or validation["schema_warnings"]:
        retry_raw = client.complete_json(
            system,
            public_state_packet_user_prompt(spec, case, routed_scope, routed_time_role, validation),
        )
        retry_repaired, retry_validation = validate_and_repair_public_state_packet(retry_raw, spec.visible_events)
        chosen_source, chosen_repaired, chosen_validation = choose_state_packet_candidate(
            (repaired, validation),
            (retry_repaired, retry_validation),
        )
        chosen_validation = deepcopy(chosen_validation)
        chosen_validation["retry_after_invalid_state_packet"] = {
            "initial_validation": validation,
            "retry_validation": retry_validation,
            "retry_used": True,
            "chosen_output": chosen_source,
        }
        chosen_trace = chosen_repaired.get("pipeline_trace", {})
        if not isinstance(chosen_trace, dict):
            chosen_trace = {}
        chosen_trace["event_id_validation"] = chosen_validation
        chosen_repaired["pipeline_trace"] = chosen_trace
        if needs_state_facet_repair(chosen_validation):
            facet_repaired, facet_validation = repair_missing_public_state_facets(
                client,
                spec,
                case,
                chosen_repaired,
                chosen_validation,
            )
            facet_validation["retry_after_invalid_state_packet"] = {
                "initial_validation": validation,
                "retry_validation": retry_validation,
                "chosen_output": chosen_source,
                "facet_repair_used": True,
            }
            facet_trace = facet_repaired.get("pipeline_trace", {})
            if not isinstance(facet_trace, dict):
                facet_trace = {}
            facet_trace["event_id_validation"] = facet_validation
            facet_repaired["pipeline_trace"] = facet_trace
            return facet_repaired, facet_validation
        return chosen_repaired, chosen_validation
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
    merged = {
        "evidence_events": evidence_events,
        "facets": facets,
        "coverage_check": verifier_raw.get("coverage_check", composer_raw.get("coverage_check", {})),
        "answer": str(verifier_raw.get("answer", composer_raw.get("answer", ""))),
        "pipeline_trace": trace,
    }
    if isinstance(locked_raw.get("state_packet"), dict):
        merged["state_packet"] = locked_raw["state_packet"]
    return merged


def run_public_ours_pipeline(
    client: LLMClient,
    spec: BaselinePromptSpec,
    case: PublicCase,
    router_raw: Optional[Dict[str, object]],
    routed_scope: Optional[str],
    routed_time_role: Optional[str],
) -> Dict[str, object]:
    locked_raw, state_packet_validation = complete_validated_public_state_packet(
        client,
        spec,
        case,
        routed_scope,
        routed_time_role,
    )
    trace = locked_raw.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace.update(
        {
            "pipeline": "public_scope_time_state_state_packet",
            "scope_router_output": router_raw,
            "routed_scope": routed_scope,
            "inferred_time_role": routed_time_role,
            "public_state_packet_output": locked_raw.get("state_packet", {}),
            "public_state_packet_derived_facets": {
                "evidence_events": locked_raw.get("evidence_events", []),
                "facets": locked_raw.get("facets", []),
            },
            "public_state_packet_event_id_validation": state_packet_validation,
        }
    )
    locked_raw["pipeline_trace"] = trace
    composer_raw = client.complete_json(public_composer_system_prompt(), public_composer_user_prompt(case, locked_raw))
    verifier_raw = client.complete_json(
        public_verifier_system_prompt(),
        public_verifier_user_prompt(case, locked_raw, composer_raw),
    )
    return merge_public_state_with_answer(locked_raw, composer_raw, verifier_raw)

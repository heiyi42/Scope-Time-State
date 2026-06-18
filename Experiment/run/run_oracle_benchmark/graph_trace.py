from __future__ import annotations

from copy import deepcopy
import re
from typing import Dict, List, Optional, Sequence

from Experiment.run.common.io import normalize_id_list
from Experiment.run.common.models import QueryCase
from Experiment.run.common.utils import dedupe_preserve_order, normalize_support_events


def infer_trace_claim_type(slot: str, value: str, event: Optional[Dict[str, object]]) -> str:
    text = f"{slot}\n{value}".lower()
    event_type = str(event.get("event_type", "")) if isinstance(event, dict) else ""
    if "invalidated" in text or "旧" in text or "替代" in text or "失效" in text:
        return "invalidated_state"
    if "无法确认" in text or "没有明确" in text or "unknown" in text or "insufficient" in text:
        return "unknown_current"
    if "next" in text or "下一步" in text:
        return "plan_or_next_step"
    if "risk" in text or "风险" in text:
        return "risk"
    if event_type:
        return event_type
    return "state_claim"


def infer_trace_state_status(slot: str, value: str) -> str:
    text = f"{slot}\n{value}".lower()
    if "insufficient" in text or "证据不足" in text or "没有足够证据" in text:
        return "insufficient_evidence"
    if "无法确认" in text or "不能确认" in text or "unknown" in text or "unclear" in text:
        return "unknown_current"
    if "invalidated" in text or "失效" in text or "替代" in text or "不再" in text:
        return "superseded_or_corrected"
    return "active"


def infer_trace_relation_type(slot: str, value: str) -> str:
    text = f"{slot}\n{value}".lower()
    if "correct" in text or "纠正" in text or "修复" in text:
        return "CORRECTS"
    if "invalid" in text or "失效" in text or "替代" in text or "不再" in text:
        return "SUPERSEDES"
    if "conflict" in text or "冲突" in text:
        return "CONFLICTS_WITH"
    return "DERIVES_STATE_WITH"


def trace_rejection_reason(event: Dict[str, object], case: QueryCase) -> str:
    event_id = str(event.get("event_id", ""))
    if event.get("state_role") == "invalidated_context_only":
        return "invalidated_context_only"
    if event_id in set(case.hard_negative_events):
        return "hard_negative_or_stale_distractor"
    event_type = str(event.get("event_type", ""))
    if event_type == "mention":
        return "mention_only_or_non_update"
    if event_type == "plan":
        return "not_selected_as_current_support_or_plan_only"
    return "not_selected_as_minimal_support"


def answer_sentences(answer: str) -> List[str]:
    parts = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?])\s+|[。\n]+", answer)
        if part and part.strip()
    ]
    return parts or ([answer.strip()] if answer.strip() else [])


def build_graph_trace(
    case: QueryCase,
    visible_events: Sequence[Dict[str, object]],
    final_raw: Dict[str, object],
    trace_status: str = "generated_from_locked_state",
) -> Dict[str, object]:
    event_by_id = {
        str(event.get("event_id")): event
        for event in visible_events
        if isinstance(event, dict) and event.get("event_id") not in {None, "", "null"}
    }
    candidate_events = list(event_by_id)
    raw_slots = final_raw.get("state_slots", {})
    if not isinstance(raw_slots, dict):
        raw_slots = {}

    claims: List[Dict[str, object]] = []
    relations: List[Dict[str, object]] = []
    state_facets: Dict[str, Dict[str, object]] = {}
    support_claims_by_slot: Dict[str, List[str]] = {}
    selected_support_events: List[str] = []

    for slot in case.output_slots:
        item = raw_slots.get(slot)
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", ""))
        support_events = dedupe_preserve_order(normalize_support_events(item))
        selected_support_events.extend(support_events)
        slot_claim_ids: List[str] = []
        for index, event_id in enumerate(support_events):
            event = event_by_id.get(event_id)
            claim_id = f"{slot}__claim_{index + 1}__{event_id}"
            slot_claim_ids.append(claim_id)
            claims.append(
                {
                    "claim_id": claim_id,
                    "event_id": event_id,
                    "facet_type": slot,
                    "value": value,
                    "claim_type": infer_trace_claim_type(slot, value, event),
                    "time_role": case.time_role,
                    "source_id": event.get("source_id") if isinstance(event, dict) else None,
                }
            )
        support_claims_by_slot[slot] = slot_claim_ids
        state_facets[slot] = {
            "value": value,
            "status": infer_trace_state_status(slot, value),
            "support_claims": slot_claim_ids,
            "support_event": item.get("support_event"),
            "support_events": support_events,
        }

        if len(slot_claim_ids) >= 2:
            relations.append(
                {
                    "type": infer_trace_relation_type(slot, value),
                    "from": slot_claim_ids[-1],
                    "to": slot_claim_ids[0],
                    "facet_type": slot,
                    "reason": "state facet requires multiple support claims, usually old/new evidence or parallel evidence",
                }
            )

    selected_support = set(selected_support_events)
    first_current_claim_id = claims[0]["claim_id"] if claims else None
    rejected_claims: List[Dict[str, object]] = []
    for event_id, event in event_by_id.items():
        if event_id in selected_support:
            continue
        rejected_claim_id = f"rejected__{event_id}"
        reason = trace_rejection_reason(event, case)
        rejected_claims.append(
            {
                "claim_id": rejected_claim_id,
                "event_id": event_id,
                "reason": reason,
                "event_type": event.get("event_type"),
                "state_role": event.get("state_role"),
            }
        )
        if reason == "invalidated_context_only" and first_current_claim_id:
            relations.append(
                {
                    "type": "SUPERSEDES",
                    "from": first_current_claim_id,
                    "to": rejected_claim_id,
                    "facet_type": "validity",
                    "reason": "current selected state evidence supersedes or corrects invalidated context",
                }
            )
    evidence_events = dedupe_preserve_order(normalize_id_list(final_raw.get("evidence_events")))
    answer = str(final_raw.get("answer", ""))
    answer_trace = [
        {
            "sentence": sentence,
            "state_facets": list(state_facets),
            "support_events": evidence_events,
        }
        for sentence in answer_sentences(answer)
    ]
    source_ids = dedupe_preserve_order(
        str(event_by_id[event_id].get("source_id"))
        for event_id in evidence_events
        if event_id in event_by_id and event_by_id[event_id].get("source_id") not in {None, "", "null"}
    )
    return {
        "trace_status": trace_status,
        "scope": case.scope_id,
        "operation": case.operation,
        "time_roles": list(case.time_roles),
        "candidate_events": candidate_events,
        "claims": claims,
        "relations": relations,
        "rejected_claims": rejected_claims,
        "state_facets": state_facets,
        "answer_trace": answer_trace,
        "trace_invariants": {
            "state_facets_have_support_events": all(
                bool(facet.get("support_events")) or facet.get("status") == "insufficient_evidence"
                for facet in state_facets.values()
            ),
            "answer_sentences_have_state_facet_links": all(
                bool(item.get("state_facets")) for item in answer_trace
            )
            if answer_trace
            else True,
        },
        "source_ids": source_ids,
    }


def graph_trace_to_locked_state(
    graph_trace: Dict[str, object],
    fallback_locked_raw: Dict[str, object],
    case: QueryCase,
) -> Dict[str, object]:
    locked = deepcopy(fallback_locked_raw)
    raw_facets = graph_trace.get("state_facets", {})
    if not isinstance(raw_facets, dict):
        raw_facets = {}

    claims_by_id = {
        str(claim.get("claim_id")): claim
        for claim in graph_trace.get("claims", [])
        if isinstance(claim, dict) and claim.get("claim_id") not in {None, "", "null"}
    }
    fallback_slots = fallback_locked_raw.get("state_slots", {})
    if not isinstance(fallback_slots, dict):
        fallback_slots = {}

    state_slots: Dict[str, Dict[str, object]] = {}
    support_union: List[str] = []
    missing_facets: List[str] = []
    fallback_slots_used: List[str] = []

    for slot in case.output_slots:
        facet = raw_facets.get(slot)
        if isinstance(facet, dict):
            support_events = dedupe_preserve_order(normalize_id_list(facet.get("support_events")))
            support_event = facet.get("support_event")
            if support_event not in {None, "", "null"}:
                support_text = str(support_event)
                if support_text not in support_events:
                    support_events.insert(0, support_text)
            if not support_events:
                for claim_id in normalize_id_list(facet.get("support_claims")):
                    claim = claims_by_id.get(claim_id)
                    if not isinstance(claim, dict):
                        continue
                    event_id = claim.get("event_id")
                    if event_id not in {None, "", "null"} and str(event_id) not in support_events:
                        support_events.append(str(event_id))
            value = str(facet.get("value", ""))
            state_slots[slot] = {
                "value": value,
                "support_event": support_events[0] if support_events else None,
                "support_events": support_events,
            }
            support_union.extend(support_events)
            continue

        missing_facets.append(slot)
        fallback_slot = fallback_slots.get(slot)
        if isinstance(fallback_slot, dict):
            support_events = dedupe_preserve_order(normalize_support_events(fallback_slot))
            state_slots[slot] = {
                "value": str(fallback_slot.get("value", "")),
                "support_event": support_events[0] if support_events else None,
                "support_events": support_events,
            }
            support_union.extend(support_events)
            fallback_slots_used.append(slot)

    locked["state_slots"] = state_slots
    locked["evidence_events"] = dedupe_preserve_order(support_union)
    trace = locked.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["graph_trace_to_locked_state"] = {
        "status": "used_fallback_slots" if fallback_slots_used else "ok",
        "source": "graph_trace.state_facets",
        "state_slot_count": len(state_slots),
        "missing_facets": missing_facets,
        "fallback_slots_used": fallback_slots_used,
    }
    locked["pipeline_trace"] = trace
    return locked


def attach_answer_trace_to_graph_trace(
    graph_trace: Dict[str, object],
    visible_events: Sequence[Dict[str, object]],
    final_raw: Dict[str, object],
) -> Dict[str, object]:
    traced = deepcopy(graph_trace)
    state_facets = traced.get("state_facets", {})
    if not isinstance(state_facets, dict):
        state_facets = {}
    evidence_events = dedupe_preserve_order(normalize_id_list(final_raw.get("evidence_events")))
    answer = str(final_raw.get("answer", ""))
    traced["answer_trace"] = [
        {
            "sentence": sentence,
            "state_facets": list(state_facets),
            "support_events": evidence_events,
        }
        for sentence in answer_sentences(answer)
    ]

    event_by_id = {
        str(event.get("event_id")): event
        for event in visible_events
        if isinstance(event, dict) and event.get("event_id") not in {None, "", "null"}
    }
    traced["source_ids"] = dedupe_preserve_order(
        str(event_by_id[event_id].get("source_id"))
        for event_id in evidence_events
        if event_id in event_by_id and event_by_id[event_id].get("source_id") not in {None, "", "null"}
    )
    invariants = traced.get("trace_invariants", {})
    if not isinstance(invariants, dict):
        invariants = {}
    answer_trace = traced["answer_trace"]
    invariants["answer_sentences_have_state_facet_links"] = (
        all(bool(item.get("state_facets")) for item in answer_trace) if answer_trace else True
    )
    invariants["answer_trace_support_matches_final_evidence"] = all(
        item.get("support_events") == evidence_events for item in answer_trace
    )
    traced["trace_invariants"] = invariants
    traced["trace_status"] = "runtime_intermediate_with_answer_trace"
    return traced


def graph_trace_generation_summary(graph_trace: Dict[str, object]) -> Dict[str, object]:
    return {
        "status": graph_trace.get("trace_status"),
        "claims": len(graph_trace.get("claims", [])),
        "relations": len(graph_trace.get("relations", [])),
        "rejected_claims": len(graph_trace.get("rejected_claims", [])),
        "state_facets": len(graph_trace.get("state_facets", {})),
    }

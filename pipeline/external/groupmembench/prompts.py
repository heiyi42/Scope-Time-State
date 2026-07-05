from __future__ import annotations

import hashlib
import json
from typing import Dict, Sequence

from pipeline.external.groupmembench.adapters.base import TaskAdapter
from pipeline.external.groupmembench.graph_schema import EDGE_TYPES, NODE_TYPES
from pipeline.external.groupmembench.loader import GroupMessage, GroupQuestion
from pipeline.external.groupmembench.routing import ScopeRoute
from pipeline.external.groupmembench.time_roles import time_role_instruction


def prompt_cache_namespace(
    question: GroupQuestion,
    adapter: TaskAdapter | None,
    stage: str,
    **extra: object,
) -> Dict[str, object]:
    task_label = adapter.qtype if adapter is not None else ("state_query" if question.qtype == "abstention" else question.qtype)
    namespace: Dict[str, object] = {
        "benchmark": "GroupMemBench",
        "domain": question.domain,
        "task": task_label,
        "stage": stage,
    }
    if task_label == "state_query":
        seed = f"{question.domain}\n{question.asking_user_id}\n{question.question}"
        namespace["case_key"] = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    else:
        namespace["question_id"] = question.question_id
    namespace.update(extra)
    return namespace


def target_state_contract(route: ScopeRoute) -> Dict[str, object]:
    return {
        "target_scope_id": route.target_scope.scope_id,
        "state_target": route.target_scope.state_target,
        "state_target_terms": list(route.target_scope.state_target_terms),
        "rule": (
            "Accepted Claims and active StateFacets must answer this query-conditioned state dimension, not merely "
            "the broader project scope. A Claim about progress, risk, review, sign-off, owner, date, or status is "
            "wrong_target unless the question asks for that dimension or the Claim directly changes the requested "
            "state target."
        ),
        "support_edge_rule": (
            "Claim -[:SUPPORTS]-> StateFacet is exact-target support only. Lexical overlap with the question is not "
            "enough: a Claim about a nearby control, SLA, validation check, owner, date, status, or risk is wrong_target "
            "unless it names the same requested state object. Near-miss Claims must be rejected, not used as supports."
        ),
    }


def claim_extraction_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the Claim extraction stage for GroupMemBench. Use only the provided visible Episode/Event nodes. "
        "Do not use hidden metadata, benchmark answers, decision labels, noise labels, or any data outside the current "
        "domain and question. Build only Event -[:ASSERTS]-> Claim candidates. Do not decide the final answer. "
        "The graph definition is exactly the image schema: node types are "
        f"{', '.join(NODE_TYPES)} and edge types are {', '.join(EDGE_TYPES)}. Return valid JSON only.\n\n"
        f"Task adapter:\n{json.dumps(adapter.prompt_payload(), ensure_ascii=False, indent=2)}"
    )


def claim_extraction_user_prompt(
    question: GroupQuestion,
    route: ScopeRoute,
    candidate_messages: Sequence[GroupMessage],
    chunk_index: int,
    chunk_count: int,
    routed_time_role: str | None = None,
    validation_error: Dict[str, object] | None = None,
) -> str:
    payload: Dict[str, object] = {
        "cache_namespace": prompt_cache_namespace(question, None, "claim_extraction", chunk_index=chunk_index),
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "target_scope": route.target_scope.as_dict(),
        "routed_time_role": routed_time_role,
        "time_role_contract": time_role_instruction(routed_time_role),
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "visible_event_ids": [message.event_id for message in candidate_messages],
        "visible_events": [message.visible_event() for message in candidate_messages],
        "task": (
            "Extract atomic Claim nodes asserted by the visible Episode/Event nodes. Each accepted Claim must copy "
            "one event_id exactly from visible_event_ids. Keep old, updated, conflicting, corrected, date, owner, "
            "scope, responsibility, blocker, status, and insufficient-evidence-relevant claims when they may affect "
            "the question. If a sentence states a deadline, date, owner, responsible role, condition, or exception, "
            "keep those qualifiers in the same Claim value instead of splitting away the date or target. If a decision "
            "also states a cost, delay, risk, or tradeoff that qualifies the accepted state, keep that qualifier in the "
            "same Claim value. If a correction sentence such as Change:, New plan:, New path:, or Proposed change: "
            "has action, owner, dependency, and target clauses, keep the whole correction sentence as one Claim instead "
            "of reducing it to only the first action clause. Use routed_time_role to set time_value/time_role on date-like claims. Do not create "
            "StateFacet nodes in this stage."
        ),
        "output_schema": {
            "claims": [
                {
                    "claim_id": "local id, will be normalized by the runner",
                    "event_id": "Msg_... copied exactly from visible_event_ids",
                    "facet_type": "deadline|owner|current_approach|blocker|status|responsibility|scope|date|...",
                    "value": "atomic state assertion text",
                    "claim_type": "decision|risk|plan|completion|mention|correction|observation|date|unsupported_candidate",
                    "time_value": "date/time mentioned by the claim when explicit, otherwise null",
                    "time_role": "occurred_at|mentioned_at|updated_at|planned_for|deadline_at|null",
                }
            ],
            "rejected_claims": [
                {
                    "event_id": "Msg_...",
                    "reason": "mention_only|irrelevant|wrong_scope|unsupported|duplicate|not_stateful",
                }
            ],
        },
    }
    if validation_error:
        payload["previous_output_error"] = validation_error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def state_selection_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the Claim-graph state selection stage for GroupMemBench. The Claim nodes have already been extracted "
        "from scoped Episode/Event nodes, and a separate validity/currentness stage has already labeled which Claim "
        "nodes are accepted as current valid for this query. Use only the provided Claim nodes, validity decisions, "
        "and visible source events. Add StateFacet nodes supported by accepted current Claim ids. Do not use hidden "
        "metadata or benchmark answers. Return valid JSON only.\n\n"
        f"Task adapter:\n{json.dumps(adapter.prompt_payload(), ensure_ascii=False, indent=2)}"
    )


def support_verification_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the graph support verification stage for GroupMemBench. A previous stage has already built active "
        "StateFacet nodes and Claim -[:SUPPORTS]-> StateFacet edges. Verify only whether each support edge is exact-target "
        "evidence for the user's query-conditioned state target. Do not write the final answer. Do not use hidden metadata "
        "or benchmark answers. Return valid JSON only.\n\n"
        f"Task adapter:\n{json.dumps(adapter.prompt_payload(), ensure_ascii=False, indent=2)}"
    )


def validity_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the Claim validity/currentness adjudication stage for GroupMemBench. Claim nodes have already been "
        "extracted from scoped Episode/Event nodes. Decide which Claim nodes are current valid for the user's query, "
        "which are stale/superseded/invalid/wrong-target/discussion-only, and which Claim-level validity relations "
        "hold. Do not create StateFacet nodes and do not write the final answer. Do not use hidden metadata or "
        "benchmark answers. Return valid JSON only.\n\n"
        f"Task adapter:\n{json.dumps(adapter.prompt_payload(), ensure_ascii=False, indent=2)}"
    )


def validity_user_prompt(
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    candidate_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
    scope_messages: Sequence[GroupMessage] | None = None,
    routed_time_role: str | None = None,
    validation_error: Dict[str, object] | None = None,
) -> str:
    scope_messages = scope_messages or source_messages
    payload: Dict[str, object] = {
        "cache_namespace": prompt_cache_namespace(question, adapter, "claim_validity"),
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "target_scope": route.target_scope.as_dict(),
        "target_state_contract": target_state_contract(route),
        "candidate_scope_nodes": route.candidate_scopes,
        "routed_time_role": routed_time_role,
        "time_role_contract": time_role_instruction(routed_time_role),
        "in_scope_episode_event_count": len(scope_messages),
        "in_scope_episode_event_ids": [message.event_id for message in scope_messages],
        "candidate_claims": list(candidate_claims),
        "source_events": [message.visible_event() for message in source_messages],
        "task": (
            "For the query, mark each relevant Claim as current_valid, stale, superseded, invalidated, conflicting, "
            "discussion_only, wrong_target, or irrelevant. A Claim can be historically true but not current valid. "
            "Accept only Claim nodes that directly assert the current answer state for the query target, including "
            "necessary owners, dependencies, exceptions, and scope boundaries. Reject generic process gates, open-choice "
            "discussion, or adjacent cleanup work unless it directly changes the requested state value. For update "
            "questions, do not accept an earlier proposal, generic discussion, or unresolved option when a later scoped "
            "Claim gives the accepted current state. Treat explicit revision markers such as Change:, "
            "New plan:, New path:, Proposed change:, revise/revisit, and 'no longer works' as strong Claim-level "
            "currentness signals unless an even more specific later Claim directly overrides the same target. Do not "
            "mark those Claims stale just because a shorter same-event extraction exists or later messages discuss "
            "adjacent fallback, sign-off, or cleanup work. When two Claims overlap, prefer the richer Claim that "
            "preserves required owner/dependency/scope qualifiers over a shorter duplicate. A later shorter "
            "confirmation, analogy, or progress/status note does not SUPERSEDE an earlier richer Claim unless it "
            "explicitly removes, replaces, or contradicts the earlier qualifiers. If the earlier richer Claim and a "
            "later shorter Claim assert the same current state, keep the richer Claim current_valid too, so the "
            "StateFacet can preserve required qualifiers such as included subflows, recovery states, before-sign-off "
            "conditions, owner/dependency boundaries, and accepted delay/tradeoff. If a later decision confirms the "
            "direction but omits those qualifiers, it SUPPORTS the same StateFacet together with the richer Claim; it "
            "does not SUPERSEDE the richer Claim. Apply target_state_contract "
            "strictly: broad progress/status/risk/review Claims inside the same project scope are wrong_target unless "
            "they directly answer or change the requested state target. Accept no Claim unless it directly answers "
            "the requested target; nearby role/date/status/control/validation mentions are not enough. If the "
            "question asks for a specific object such as a stable control set, the accepted Claim must name that "
            "object or its explicit equivalent; a Claim about an adjacent SLA control, validation metric, audit "
            "boundary, or queue-volume check is wrong_target even if words overlap. Leave accepted_current_claims "
            "empty when no Claim directly supports the requested answer. Relations must connect existing Claim ids only."
        ),
        "output_schema": {
            "validity_packet": {
                "target_scope_id": "must equal target_scope.scope_id",
                "accepted_current_claims": [
                    {
                        "claim_id": "claim id copied from candidate_claims",
                        "facet_type": "short facet target",
                        "reason": "why this claim is current valid for the query",
                    }
                ],
                "rejected_claims": [
                    {
                        "claim_id": "claim id copied from candidate_claims",
                        "event_id": "source event id copied from the claim",
                        "validity": "stale|superseded|invalidated|conflicting|discussion_only|wrong_target|irrelevant|insufficient_evidence",
                        "reason": "why this claim must not support an active StateFacet",
                    }
                ],
                "relations": [
                    {
                        "type": "CORRECTS|SUPERSEDES|CONFLICTS_WITH",
                        "from": "newer_or_left_claim_id",
                        "to": "older_or_right_claim_id",
                        "evidence_event_ids": ["Msg_..."],
                        "reason": "why this relation controls current validity",
                    }
                ],
            }
        },
    }
    if validation_error:
        payload["previous_output_error"] = validation_error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def state_selection_user_prompt(
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    candidate_claims: Sequence[Dict[str, object]],
    validity_packet: Dict[str, object],
    source_messages: Sequence[GroupMessage],
    scope_messages: Sequence[GroupMessage] | None = None,
    routed_time_role: str | None = None,
    validation_error: Dict[str, object] | None = None,
) -> str:
    scope_messages = scope_messages or source_messages
    payload: Dict[str, object] = {
        "cache_namespace": prompt_cache_namespace(question, adapter, "state_selection"),
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "target_scope": route.target_scope.as_dict(),
        "target_state_contract": target_state_contract(route),
        "candidate_scope_nodes": route.candidate_scopes,
        "routed_time_role": routed_time_role,
        "time_role_contract": time_role_instruction(routed_time_role),
        "in_scope_episode_event_count": len(scope_messages),
        "in_scope_episode_event_ids": [message.event_id for message in scope_messages],
        "candidate_claims": list(candidate_claims),
        "validity_packet": validity_packet,
        "source_events": [message.visible_event() for message in source_messages],
        "task": (
            "Resolve the current query-conditioned StateFacet nodes from the provided Claim graph candidates. "
            "Use validity_packet.accepted_current_claims as the only support pool for active StateFacets. Stale, "
            "superseded, invalidated, discussion-only, wrong-target, or irrelevant Claims must not support an active "
            "StateFacet. Prefer accepted current Claim(s) that directly answer the question target instead of "
            "combining competing current options. Non-current Claims may appear only in rejected_claims or relations. "
            "Every support_claims edge is an exact-target SUPPORTS edge: do not attach a Claim to a StateFacet when "
            "it only shares broad words with the question. If accepted_current_claims is empty or only near-miss "
            "Claims exist, return one insufficient_evidence StateFacet with empty supports. "
            "Do not invent new Claim ids. Return a compact state_packet: do not echo candidate_claims, source_events, "
            "validity_packet, or every rejected validity decision. The StateFacet value must be the requested state "
            "value, not a narrative summary; exclude process gates, open-choice text, and adjacent discussion unless "
            "they are part of the requested current state. If one accepted Claim contains the full owner/dependency/"
            "scope-qualified answer and another is only a shorter duplicate, support the StateFacet with the fuller "
            "Claim. Merge non-conflicting required qualifiers from accepted Claims that assert the same current state. "
            "Preserve included subflows, recovery states, before-sign-off conditions, and accepted delay/tradeoff when "
            "the question asks for a current scope, plan, responsibility, or approval state. Exclude analogies, "
            "prior-project examples, and rationale anecdotes from the StateFacet value unless the question asks for "
            "that rationale. Apply target_state_contract strictly: do not create active StateFacets for progress, "
            "status, risk, review, owner, or date dimensions unless the question asks for those dimensions or they "
            "directly change the requested state target. For a scope target, the active StateFacet must describe the "
            "current inclusion/exclusion/boundary of that scope, not generic approval progress or review status. "
            "For date questions, lock the StateFacet time_value/time_role from routed_time_role; occurred_at uses the supporting "
            "event timestamp, while deadline_at/planned_for use the date asserted in the Claim content. Do not write "
            "the final answer yet."
        ),
        "output_schema": {
            "state_packet": {
                "target_scope_id": "must equal target_scope.scope_id",
                "relations": [
                    {
                        "type": "CORRECTS|SUPERSEDES|CONFLICTS_WITH",
                        "from": "newer_or_left_claim_id",
                        "to": "older_or_right_claim_id",
                        "evidence_event_ids": ["Msg_..."],
                        "reason": "why this relation exists",
                    }
                ],
                "rejected_claims": [
                    {
                        "claim_id": "claim id if available",
                        "event_id": "Msg_...",
                        "reason": "stale|mention_only|plan_only|wrong_scope|unsupported|insufficient_evidence|irrelevant",
                    }
                ],
                "state_facets": [
                    {
                        "facet_id": "facet_1",
                        "name": "short facet name",
                        "value": "current valid state text, or insufficient-evidence explanation",
                        "status": "active|unknown_current|insufficient_evidence|superseded_or_corrected|conflict_unresolved",
                        "support_claims": ["claim_id"],
                        "support_events": ["Msg_..."],
                        "current_after": "timestamp copied from a supporting event, or null",
                        "time_value": "YYYY-MM-DD when the StateFacet is temporal, otherwise null",
                        "time_role": "occurred_at|mentioned_at|updated_at|planned_for|deadline_at|null",
                    }
                ],
            }
        },
    }
    if validation_error:
        payload["previous_output_error"] = validation_error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def support_verification_user_prompt(
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    active_state_facets: Sequence[Dict[str, object]],
    support_claims: Sequence[Dict[str, object]],
    rejected_or_near_miss_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
    routed_time_role: str | None = None,
) -> str:
    payload: Dict[str, object] = {
        "cache_namespace": prompt_cache_namespace(question, adapter, "support_verification"),
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "target_scope": route.target_scope.as_dict(),
        "target_state_contract": target_state_contract(route),
        "candidate_scope_nodes": route.candidate_scopes,
        "routed_time_role": routed_time_role,
        "time_role_contract": time_role_instruction(routed_time_role),
        "active_state_facets": list(active_state_facets),
        "support_claims": list(support_claims),
        "rejected_or_near_miss_claims": list(rejected_or_near_miss_claims),
        "source_events": [message.visible_event() for message in source_messages],
        "task": (
            "For each active StateFacet, verify whether its support_claims directly answer the requested target state. "
            "A support Claim must name the same requested object, role, date, control, owner, status, or scope boundary "
            "asked by the question, or an explicit equivalent in the source event. Same project scope, lexical overlap, "
            "adjacent process gates, nearby owners, related controls, or generic progress/status are not enough. If a "
            "question asks for a semantic role such as trigger, criterion, condition, exception, owner, deadline, "
            "approver, blocker, or required action, the source Claim must assert that role directly; do not infer that "
            "a list of fields, process requirements, reviewer mentions, or adjacent status updates fills the requested "
            "role. If a support Claim is a near miss, mark that support as wrong_target or insufficient_direct_support. "
            "If no support Claim remains exact-target for a facet, mark the facet insufficient_evidence. This check is "
            "query-agnostic: apply the same rule to every task type."
        ),
        "output_schema": {
            "support_verification": {
                "target_scope_id": "must equal target_scope.scope_id",
                "facet_decisions": [
                    {
                        "facet_id": "facet id copied from active_state_facets",
                        "decision": "supported|insufficient_evidence",
                        "supported_claim_ids": ["claim ids that exactly support this facet"],
                        "rejected_supports": [
                            {
                                "claim_id": "support claim id to remove",
                                "validity": "wrong_target|insufficient_direct_support|stale|superseded|invalidated|conflicting|irrelevant",
                                "reason": "why this claim cannot support the queried StateFacet",
                            }
                        ],
                        "reason": "short decision rationale",
                    }
                ],
            }
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def composer_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the answer composition stage for GroupMemBench. Use only the locked StateFacet nodes "
        "from the graph state packet. Do not add new claims, search for new evidence, change support_events, "
        "or use hidden benchmark answers. If the question asks for a date, status, owner, team, or scope value, "
        "answer with that target value rather than a narrative evidence summary. Date or deadline answers must be "
        "a single YYYY-MM-DD value when the locked graph supports a date. Who/team/owner answers should be concise, "
        "but preserve the requested action or relation when the question asks who is being asked to do something. "
        "If the question asks for one thing the user needs signed off, answer with the single minimal required item, "
        "not a comma-separated list of related sign-offs or downstream confirmations. "
        "Field-list answers must be only the requested fields. Status answers must be only the status value. "
        "Responsibility answers must be the concise responsibility/action, not a full sentence with unrelated actors. "
        "For scope/plan/update answers, preserve included items, conditions, owners/dependencies, and accepted "
        "delay/tradeoff qualifiers from the locked facets and supporting claims, but omit analogies, prior-project "
        "examples, and narrative rationale unless explicitly requested. "
        "Return valid JSON only.\n\n"
        f"Task answer guidance: {adapter.answer_instruction}"
    )


def composer_user_prompt(question: GroupQuestion, locked_raw: Dict[str, object]) -> str:
    packet = locked_raw.get("state_packet", {}) if isinstance(locked_raw.get("state_packet"), dict) else {}
    graph_trace = locked_raw.get("graph_trace", {}) if isinstance(locked_raw.get("graph_trace"), dict) else {}
    graph_nodes = graph_trace.get("nodes", {}) if isinstance(graph_trace.get("nodes"), dict) else {}
    entity_scope = graph_nodes.get("entity_scope", {}) if isinstance(graph_nodes.get("entity_scope"), dict) else {}
    payload = {
        "cache_namespace": prompt_cache_namespace(question, None, "composer"),
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "target_state_contract": {
            "target_scope_id": packet.get("target_scope_id"),
            "state_target": entity_scope.get("state_target"),
            "state_target_terms": entity_scope.get("state_target_terms", []),
            "rule": "Answer only the locked StateFacet(s) that match this requested state target.",
        },
        "locked_state_facets": packet.get("state_facets", []),
        "locked_claims": packet.get("claims", []),
        "locked_relations": packet.get("relations", []),
        "task": "Write the final answer from locked_state_facets only.",
        "output_schema": {"coverage_check": {"facet_id_or_name": True}, "answer": "string"},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def direct_baseline_system_prompt() -> str:
    return (
        "You are a careful GroupMemBench QA agent. Use only the retrieved conversation passages. "
        "If the answer is not supported by the passages, say that no information is available. "
        "Return valid JSON only."
    )


def direct_baseline_user_prompt(question: GroupQuestion, messages: Sequence[GroupMessage]) -> str:
    payload = {
        "cache_namespace": prompt_cache_namespace(question, None, "direct_baseline", variant="bm25_message"),
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "retrieved_passages": [message.visible_event() for message in messages],
        "output_schema": {"answer": "string"},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

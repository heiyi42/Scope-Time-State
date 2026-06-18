from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import math
import re
from typing import Dict, Iterable, List, Sequence, Tuple

from ...common import BaselinePromptSpec, event_view, parse_time


MAX_VISIBLE_EVENTS = 25

STATE_SCHEMA: Dict[str, Dict[str, str]] = {
    "identity_and_background": {
        "core_identity_or_role": "multi",
        "skill_or_language_background": "multi",
        "stable_social_context": "multi",
        "current_status_or_affiliation": "multi",
    },
    "stable_preferences": {
        "enduring_preference": "multi",
        "habitual_choice_pattern": "multi",
        "value_or_priority_tendency": "multi",
    },
    "location_and_living": {
        "current_base_location": "single",
        "living_arrangement_or_settlement": "single",
        "location_linked_condition": "multi",
    },
    "weather_and_environment": {
        "current_weather_pattern": "single",
        "environmental_condition": "multi",
        "weather_linked_adjustment": "multi",
    },
    "health_and_mobility": {
        "current_health_state": "single",
        "functional_limitation": "multi",
        "health_linked_adjustment": "multi",
    },
    "work_and_schedule": {
        "current_workload": "multi",
        "schedule_pressure_or_bandwidth": "single",
        "work_transition_or_change": "multi",
        "standing_commitment_or_availability": "multi",
    },
    "finance_and_resources": {
        "financial_constraint": "multi",
        "resource_availability": "multi",
        "resource_linked_adjustment": "multi",
        "resource_access_or_recoverability": "multi",
    },
    "family_and_caregiving": {
        "caregiving_responsibility": "multi",
        "household_obligation": "multi",
        "family_linked_constraint": "multi",
    },
    "routine_and_transport": {
        "current_commute_mode": "single",
        "transport_access_condition": "multi",
        "routine_shift": "multi",
    },
    "current_focus_and_goals": {
        "current_primary_focus": "multi",
        "short_horizon_goal": "multi",
        "goal_linked_constraint": "multi",
    },
}

AFFECTED_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "location_and_living": ("routine_and_transport", "weather_and_environment", "current_focus_and_goals"),
    "weather_and_environment": ("location_and_living", "routine_and_transport"),
    "health_and_mobility": ("routine_and_transport", "work_and_schedule", "current_focus_and_goals"),
    "work_and_schedule": ("current_focus_and_goals", "routine_and_transport", "family_and_caregiving"),
    "finance_and_resources": ("current_focus_and_goals", "work_and_schedule"),
    "routine_and_transport": ("work_and_schedule", "health_and_mobility"),
    "current_focus_and_goals": ("work_and_schedule", "stable_preferences", "finance_and_resources"),
}

EVENT_SLOT_RULES: Dict[str, Tuple[str, str, str]] = {
    "paper_reading": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "related_work": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "idea": ("current_focus_and_goals", "current_primary_focus", "direct"),
    "decision": ("current_focus_and_goals", "current_primary_focus", "direct"),
    "plan": ("current_focus_and_goals", "short_horizon_goal", "direct"),
    "deadline": ("work_and_schedule", "standing_commitment_or_availability", "direct"),
    "progress": ("work_and_schedule", "current_workload", "direct"),
    "draft": ("work_and_schedule", "current_workload", "direct"),
    "execution_log": ("work_and_schedule", "current_workload", "direct"),
    "experiment": ("work_and_schedule", "current_workload", "direct"),
    "issue": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "diagnosis": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "correction": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "fix": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "incident": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "mitigation": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "root_cause": ("current_focus_and_goals", "goal_linked_constraint", "direct"),
    "budget": ("finance_and_resources", "financial_constraint", "direct"),
    "team_change": ("identity_and_background", "current_status_or_affiliation", "direct"),
    "feedback": ("stable_preferences", "value_or_priority_tendency", "direct"),
    "guideline": ("stable_preferences", "value_or_priority_tendency", "direct"),
    "mention": ("current_focus_and_goals", "goal_linked_constraint", "upstream"),
    "review": ("current_focus_and_goals", "goal_linked_constraint", "upstream"),
}

REVISION_MARKERS = (
    "纠正",
    "修正",
    "更正",
    "替代",
    "转向",
    "改为",
    "不再",
    "恢复",
    "已解决",
    "修复",
    "取消",
    "废弃",
    "推翻",
    "invalid",
    "replace",
    "resolved",
    "fixed",
    "cancel",
)

STALE_OR_HISTORICAL_MARKERS = (
    "复盘",
    "回顾",
    "随口",
    "又提到",
    "没有新结论",
    "历史",
    "旧",
    "不是新的",
    "过期",
    "作废",
    "stale",
    "previous",
    "old",
)

UNRESOLVED_MARKERS = (
    "计划",
    "准备",
    "待",
    "草稿",
    "未复核",
    "没有完成记录",
    "无法确认",
    "还没确认",
    "todo",
    "draft",
    "pending",
)

COMPLETION_MARKERS = (
    "完成",
    "提交",
    "已补",
    "通过",
    "已解决",
    "修复",
    "done",
    "submitted",
    "completed",
    "passed",
)

STOP_TERMS = {
    "the",
    "and",
    "for",
    "with",
    "项目",
    "最近",
    "现在",
    "当前",
    "下一步",
    "问题",
    "什么",
    "怎么",
    "怎么样",
    "安排",
    "状态",
}


@dataclass(frozen=True)
class StateUpdateCandidate:
    candidate_id: str
    domain: str
    slot: str
    value: str
    source_type: str
    confidence: float
    timestamp: str
    evidence_event_id: str
    evidence_span: str


@dataclass(frozen=True)
class QueryAnalysis:
    intent: str
    presupposed_states: List[str]
    basis_slots: List[str]
    requested_action: str


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str, limit: int = 180) -> str:
    text = normalize_space(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def contains_any(text: str, markers: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def term_features(text: str) -> Counter[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9_+-]{2,}", lowered)
    cjk_sequences = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    terms: List[str] = [token for token in latin if token not in STOP_TERMS]
    for sequence in cjk_sequences:
        if sequence not in STOP_TERMS:
            terms.append(sequence)
        terms.extend(sequence[i : i + 2] for i in range(max(0, len(sequence) - 1)))
    return Counter(token for token in terms if token and token not in STOP_TERMS)


def cosine_counter(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def event_time(event: object) -> str:
    return str(
        getattr(event, "updated_at", None)
        or getattr(event, "occurred_at", None)
        or getattr(event, "mentioned_at", None)
        or ""
    )


def slot_cardinality(domain: str, slot: str) -> str:
    return STATE_SCHEMA.get(domain, {}).get(slot, "multi")


def primary_slot_for_event(event: object) -> Tuple[str, str, str]:
    event_type = str(getattr(event, "event_type", ""))
    content = str(getattr(event, "content", ""))
    if contains_any(content, ("预算", "经费", "费用", "成本", "budget")):
        return "finance_and_resources", "financial_constraint", "direct"
    if contains_any(content, ("deadline", "截止", "排期", "安排")):
        return "work_and_schedule", "standing_commitment_or_availability", "direct"
    if contains_any(content, ("下一步", "计划", "待办", "准备")):
        return "current_focus_and_goals", "short_horizon_goal", "direct"
    if contains_any(content, ("完成", "提交", "草稿", "复核", "运行", "实验")):
        return "work_and_schedule", "current_workload", "direct"
    if contains_any(content, ("风险", "不够强", "问题", "故障", "阻塞", "修复", "纠正")):
        return "current_focus_and_goals", "goal_linked_constraint", "direct"
    return EVENT_SLOT_RULES.get(event_type, ("current_focus_and_goals", "goal_linked_constraint", "upstream"))


def candidate_confidence(event: object, domain: str, slot: str) -> float:
    content = str(getattr(event, "content", ""))
    event_type = str(getattr(event, "event_type", ""))
    score = 0.62
    if event_type in {"decision", "correction", "fix", "mitigation", "root_cause", "deadline", "plan"}:
        score += 0.24
    if contains_any(content, REVISION_MARKERS):
        score += 0.12
    if contains_any(content, STALE_OR_HISTORICAL_MARKERS):
        score -= 0.18
    if contains_any(content, UNRESOLVED_MARKERS) and not contains_any(content, COMPLETION_MARKERS):
        score -= 0.05
    if slot_cardinality(domain, slot) == "single":
        score += 0.05
    return max(0.05, min(0.99, score))


def extract_state_update_candidates(event: object, ordinal: int) -> List[StateUpdateCandidate]:
    domain, slot, source_type = primary_slot_for_event(event)
    content = compact(str(getattr(event, "content", "")), 220)
    confidence = candidate_confidence(event, domain, slot)
    event_id = str(getattr(event, "event_id"))
    candidates = [
        StateUpdateCandidate(
            candidate_id=f"cupmem_delta_{ordinal}_0",
            domain=domain,
            slot=slot,
            value=content,
            source_type=source_type,
            confidence=confidence,
            timestamp=event_time(event),
            evidence_event_id=event_id,
            evidence_span=content,
        )
    ]
    if contains_any(content, ("下一步", "计划", "安排")) and slot != "short_horizon_goal":
        candidates.append(
            StateUpdateCandidate(
                candidate_id=f"cupmem_delta_{ordinal}_1",
                domain="current_focus_and_goals",
                slot="short_horizon_goal",
                value=content,
                source_type="direct",
                confidence=max(0.42, confidence - 0.08),
                timestamp=event_time(event),
                evidence_event_id=event_id,
                evidence_span=content,
            )
        )
    return candidates


def query_analysis(query: str) -> QueryAnalysis:
    query_text = query.lower()
    basis_slots: List[str] = []
    presupposed: List[str] = []
    if contains_any(query_text, ("还在", "还是", "since", "既然", "之前", "旧")):
        presupposed.append("query may presuppose an older state")
    if contains_any(query_text, ("风险", "不够强", "问题", "故障", "issue")):
        basis_slots.append("current_focus_and_goals/goal_linked_constraint")
    if contains_any(query_text, ("下一步", "安排", "计划", "planned", "next")):
        basis_slots.append("current_focus_and_goals/short_horizon_goal")
    if contains_any(query_text, ("最近", "怎么样", "状态", "到哪", "current", "latest")):
        basis_slots.extend(["current_focus_and_goals/current_primary_focus", "work_and_schedule/current_workload"])
    if contains_any(query_text, ("预算", "经费", "budget")):
        basis_slots.append("finance_and_resources/financial_constraint")
    if contains_any(query_text, ("提交", "完成", "修复", "解决")):
        basis_slots.append("work_and_schedule/current_workload")
    if not basis_slots:
        basis_slots.append("current_focus_and_goals/goal_linked_constraint")
    return QueryAnalysis(
        intent="state_resolution" if presupposed else "authorized_current_state_readout",
        presupposed_states=presupposed,
        basis_slots=sorted(set(basis_slots)),
        requested_action="LLM adjudicates current valid state from unadjudicated candidates",
    )


def candidate_slot_key(candidate: StateUpdateCandidate) -> str:
    return f"{candidate.domain}/{candidate.slot}"


def candidate_relevance(candidate: StateUpdateCandidate, query_terms: Counter[str], analysis: QueryAnalysis) -> float:
    basis_bonus = 0.45 if candidate_slot_key(candidate) in analysis.basis_slots else 0.0
    return basis_bonus + candidate.confidence * 0.2 + cosine_counter(query_terms, term_features(candidate.value))


def unique_ordered(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def candidate_flags(candidate: StateUpdateCandidate) -> Dict[str, bool]:
    value = candidate.value
    return {
        "revision_or_invalidation_cue": contains_any(value, REVISION_MARKERS),
        "stale_or_historical_cue": contains_any(value, STALE_OR_HISTORICAL_MARKERS),
        "unresolved_without_completion_cue": contains_any(value, UNRESOLVED_MARKERS) and not contains_any(value, COMPLETION_MARKERS),
        "completion_or_resolution_cue": contains_any(value, COMPLETION_MARKERS),
    }


def candidate_view(candidate: StateUpdateCandidate, relevance: float = 0.0) -> Dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "domain": candidate.domain,
        "slot": candidate.slot,
        "slot_cardinality": slot_cardinality(candidate.domain, candidate.slot),
        "value": candidate.value,
        "source_type": candidate.source_type,
        "confidence": round(candidate.confidence, 3),
        "query_relevance": round(relevance, 3),
        "timestamp": candidate.timestamp,
        "evidence_event_id": candidate.evidence_event_id,
        "evidence_span": candidate.evidence_span,
        "llm_adjudication_status": "UNADJUDICATED",
        "cues": candidate_flags(candidate),
    }


def build_candidates(events: Sequence[object]) -> List[StateUpdateCandidate]:
    sorted_events = sorted(events, key=lambda event: parse_time(event_time(event)))
    candidates: List[StateUpdateCandidate] = []
    for ordinal, event in enumerate(sorted_events, start=1):
        candidates.extend(extract_state_update_candidates(event, ordinal))
    return candidates


def select_event_ids(
    events: Sequence[object],
    candidates: Sequence[StateUpdateCandidate],
    analysis: QueryAnalysis,
    query: str,
) -> List[str]:
    query_terms = term_features(query)
    scored = [
        (candidate_relevance(candidate, query_terms, analysis), candidate)
        for candidate in candidates
    ]
    scored.sort(key=lambda pair: (pair[0], parse_time(pair[1].timestamp)), reverse=True)
    candidate_ids = [candidate.evidence_event_id for _, candidate in scored]
    recent_ids = [
        str(getattr(event, "event_id"))
        for event in sorted(events, key=lambda event: parse_time(event_time(event)), reverse=True)
    ]
    return unique_ordered(candidate_ids + recent_ids)[:MAX_VISIBLE_EVENTS]


def collect_visible_events(
    events: Sequence[object],
    candidates: Sequence[StateUpdateCandidate],
    analysis: QueryAnalysis,
    query: str,
) -> List[Dict[str, object]]:
    events_by_id = {str(getattr(event, "event_id")): event for event in events}
    candidates_by_event: Dict[str, List[StateUpdateCandidate]] = defaultdict(list)
    query_terms = term_features(query)
    relevance_by_candidate = {
        candidate.candidate_id: candidate_relevance(candidate, query_terms, analysis)
        for candidate in candidates
    }
    for candidate in candidates:
        candidates_by_event[candidate.evidence_event_id].append(candidate)

    selected_ids = select_event_ids(events, candidates, analysis, query)
    visible: List[Dict[str, object]] = []
    for rank, event_id in enumerate(selected_ids, start=1):
        event = events_by_id.get(event_id)
        if event is None:
            continue
        view = event_view(event, include_relations=False, include_state_relevant=False)
        event_candidates = candidates_by_event.get(event_id, [])
        view["cupmem_rank"] = rank
        view["cupmem_candidate_status"] = "UNADJUDICATED"
        view["state_update_candidates"] = [
            candidate_view(candidate, relevance_by_candidate.get(candidate.candidate_id, 0.0))
            for candidate in event_candidates
        ]
        view["query_analysis"] = {
            "intent": analysis.intent,
            "presupposed_states": analysis.presupposed_states,
            "basis_slots": analysis.basis_slots,
            "requested_action": analysis.requested_action,
        }
        visible.append(view)
    return visible


def build_instruction(
    candidates: Sequence[StateUpdateCandidate],
    analysis: QueryAnalysis,
    query: str,
    has_output_slots: bool,
) -> str:
    query_terms = term_features(query)
    candidate_stream = [
        candidate_view(candidate, candidate_relevance(candidate, query_terms, analysis))
        for candidate in sorted(candidates, key=lambda item: parse_time(item.timestamp))
    ]
    output_rule = (
        "7. state_slots must contain only the requested output_slots."
        if has_output_slots
        else (
            "7. Public End-to-End setting: there are no hidden output_slots. Free-identify the "
            "current-state facets required by the query, and return them through the outer JSON "
            "schema's facets/evidence_events/answer fields. Do not request or assume output_slots."
        )
    )
    return (
        "按 STALE 论文中的 CUPMem / Current-state Updating and Propagation-aware Memory 模拟 "
        "validity-aware consolidation。这个版本不在代码里预先判定 KEEP/STALE/REPLACE/UNKNOWN；"
        "你必须作为 LLM adjudicator 完成 write-side evidence-to-state updating、"
        "active/stale/unknown-current adjudication、stale-state search 和 query-time constrained readout。"
        "候选抽取阶段只给出 unadjudicated state-update candidates；stale states 可以被归档并用于解释，"
        "但不能直接当作当前状态输出。"
        "typed_state_schema="
        f"{json.dumps(STATE_SCHEMA, ensure_ascii=False)}。"
        "affected_domain_graph="
        f"{json.dumps(AFFECTED_DOMAINS, ensure_ascii=False)}。"
        "query_analysis="
        f"{json.dumps({'intent': analysis.intent, 'presupposed_states': analysis.presupposed_states, 'basis_slots': analysis.basis_slots, 'requested_action': analysis.requested_action}, ensure_ascii=False)}。"
        "candidate_stream="
        f"{json.dumps(candidate_stream, ensure_ascii=False)}。"
        "Adjudication rules to apply inside the LLM workflow: "
        "1. For each relevant candidate, decide whether it is ADD/REFINE/REPLACE/STALE/UNKNOWN_CURRENT relative to older candidates. "
        "2. Same-slot single-valued later evidence can replace older state, but only if the event text supports the replacement. "
        "3. Revision/correction/fix/cancellation cues can make older direct/affected/global states stale; stale states may support explanation but not current state. "
        "4. If evidence only shows a plan, todo, draft, pending review, or missing completion record, do not infer completion; mark the completion state as unknown-current in the value. "
        "5. If the query presupposes a stale state, resist the premise and answer from the adjudicated current/unknown basis. "
        "6. support_event/support_events/evidence_events must use raw visible event_id values only, never candidate_id. "
        f"{output_rule}"
    )


def build_cupmem_prompt_spec(events: Sequence[object], case: object) -> BaselinePromptSpec:
    scope_id = getattr(case, "scope_id", None)
    scoped_events = [event for event in events if scope_id and getattr(event, "scope_id", None) == scope_id]
    event_stream = scoped_events or list(events)
    candidates = build_candidates(event_stream)
    analysis = query_analysis(str(getattr(case, "query", "")))
    visible = collect_visible_events(event_stream, candidates, analysis, str(getattr(case, "query", "")))
    instruction = build_instruction(
        candidates,
        analysis,
        str(getattr(case, "query", "")),
        has_output_slots=bool(getattr(case, "output_slots", None)),
    )
    return BaselinePromptSpec("validity_aware_consolidation", visible, instruction)

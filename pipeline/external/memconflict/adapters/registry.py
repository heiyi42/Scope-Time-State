from __future__ import annotations

from pipeline.external.memconflict.adapters.base import TaskAdapter


_ADAPTERS = {
    "dynamic_conflict": TaskAdapter(
        conflict_type="dynamic_conflict",
        task_name="dynamic_temporal_validity",
        task_instruction=(
            "Resolve a dynamic memory conflict. A later true user-state update supersedes "
            "earlier states after the update session, while older states may still appear in memory."
        ),
        evidence_instruction=(
            "Find the user-state memories that describe the old value, the later update, and the "
            "current valid value at query time. The first relevant_memory_ids and valid_evidence "
            "items must be the current/updated memory supporting the final answer, not the outdated "
            "memory. Put older superseded states only after the updated evidence or in "
            "competing_or_invalid_evidence, and keep source/session dates explicit."
        ),
        answer_instruction=(
            "Answer with the current valid state. If the question asks how something changed, state "
            "the old-to-new direction. If it asks whether it changed, answer directly and mention "
            "the update when supported. Preserve the exact old and new values when they appear in "
            "the selected evidence."
        ),
    ),
    "static_conflict": TaskAdapter(
        conflict_type="static_conflict",
        task_name="static_factual_preservation",
        task_instruction=(
            "Resolve a static memory conflict. Stable user facts may be contradicted later by a "
            "false or incompatible mention; the task is to preserve the benchmark-defined stable "
            "fact and acknowledge the conflict when it matters."
        ),
        evidence_instruction=(
            "Find memories that state the stable fact and memories that introduce a contradictory "
            "claim. Always search for both sides of the contradiction before answering; if a "
            "contradictory candidate is present in the candidate memories, include it in "
            "competing_or_invalid_evidence even when the stable fact is clear. Do not treat recency "
            "alone as truth for static facts; rank fact-preserving evidence above unsupported "
            "contradictions."
        ),
        answer_instruction=(
            "Answer with the best-supported stable fact. When contradictory memories coexist, say "
            "that the sources are inconsistent before giving the preserved fact, including the "
            "contradictory value when it is available."
        ),
    ),
    "conditional_conflict": TaskAdapter(
        conflict_type="conditional_conflict",
        task_name="conditional_applicability",
        task_instruction=(
            "Resolve a conditional memory conflict. Multiple preferences can be valid, but each "
            "applies only under its associated condition."
        ),
        evidence_instruction=(
            "Find condition-value pairs for the target preference and rank the pair whose condition "
            "matches the current query above conditionally inapplicable alternatives. Extract the "
            "full condition span, including time, situation, purpose, and constraints; do not reduce "
            "it to a single keyword when the memory provides richer applicability details."
        ),
        answer_instruction=(
            "Answer with the condition or condition-value association requested by the question. "
            "Preserve the binding between the preference value and its condition. For questions "
            "asking 'under what condition', include the complete condition span from the evidence, "
            "not only the shortest phrase."
        ),
    ),
}

TASK_TYPES = tuple(_ADAPTERS.keys())


def get_adapter(conflict_type: str) -> TaskAdapter:
    try:
        return _ADAPTERS[conflict_type]
    except KeyError as exc:
        known = ", ".join(TASK_TYPES)
        raise ValueError(f"unsupported MemConflict conflict_type={conflict_type!r}; known={known}") from exc

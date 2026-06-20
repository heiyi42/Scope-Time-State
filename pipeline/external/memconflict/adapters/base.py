from __future__ import annotations

from dataclasses import dataclass


BASE_RESPONSE_SCHEMA = (
    '{"answer": "...", "evidence_memory_ids": ["S5:T1:user"], '
    '"conflict_notes": ["..."]}'
)

EVIDENCE_RESPONSE_SCHEMA = (
    '{"relevant_memory_ids": ["S5:T1:user"], '
    '"valid_evidence": [{"memory_id": "S5:T1:user", "fact": "...", "reason": "..."}], '
    '"competing_or_invalid_evidence": [{"memory_id": "S1:T1:user", "claim": "...", "reason": "..."}], '
    '"conflict_summary": "..."}'
)

TASK_ADAPTER_RESPONSE_SCHEMA = (
    '{"answer": "...", "evidence_memory_ids": ["S5:T1:user"], '
    '"state_facets": [{"name": "...", "value": "...", "support_memory_ids": ["S5:T1:user"]}], '
    '"rejected_claims": [{"claim": "...", "reason": "...", "support_memory_ids": ["S1:T1:user"]}], '
    '"answer_rationale": "..."}'
)


@dataclass(frozen=True)
class TaskAdapter:
    conflict_type: str
    task_name: str
    task_instruction: str
    evidence_instruction: str
    answer_instruction: str

    def response_schema(self, variant: str) -> str:
        if variant == "scope_time_state_task_adapter":
            return TASK_ADAPTER_RESPONSE_SCHEMA
        return BASE_RESPONSE_SCHEMA


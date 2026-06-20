from __future__ import annotations

from dataclasses import dataclass


BASE_RESPONSE_SCHEMA = '{"answer": "..."}'
STATE_RESPONSE_SCHEMA = (
    '{"answer": "...", "evidence_session_indices": [1], '
    '"state_facets": [{"name": "...", "value": "...", "support_session_indices": [1]}], '
    '"rejected_claims": [{"claim": "...", "reason": "...", "support_session_indices": [1]}], '
    '"answer_rationale": "..."}'
)


@dataclass(frozen=True)
class TaskAdapter:
    task_type: str
    dim_key: str
    response_key: str
    meta_key: str
    task_name: str
    task_instruction: str
    evidence_instruction: str
    answer_instruction: str

    def response_schema(self, variant: str) -> str:
        if variant == "scope_time_state_task_adapter":
            return STATE_RESPONSE_SCHEMA
        return BASE_RESPONSE_SCHEMA

from __future__ import annotations

from dataclasses import dataclass


BASELINE_RESPONSE_SCHEMA = '{"answer": "...", "evidence_dialog_ids": ["D1:1", "..."]}'

TASK_ADAPTER_RESPONSE_SCHEMA = (
    '{"answer": "...", "evidence_dialog_ids": ["D1:1", "..."], '
    '"state_facets": [{"name": "...", "value": "...", "support_dialog_ids": ["D1:1"]}], '
    '"rejected_claims": [{"claim": "...", "reason": "...", "support_dialog_ids": ["D1:1"]}], '
    '"answer_rationale": "..."}'
)


@dataclass(frozen=True)
class TaskAdapter:
    category: int
    question_type: str
    task_name: str
    task_instruction: str
    scope_time_state_instruction: str
    evidence_instruction: str = ""
    answer_instruction: str = ""

    def instruction(self) -> str:
        return f"{self.task_instruction} {self.scope_time_state_instruction}"

    def evidence_prompt_instruction(self) -> str:
        return self.evidence_instruction or self.task_instruction

    def answer_prompt_instruction(self) -> str:
        return self.answer_instruction or self.task_instruction

    def response_schema(self, variant: str) -> str:
        if variant == "scope_time_state_task_adapter":
            return TASK_ADAPTER_RESPONSE_SCHEMA
        return BASELINE_RESPONSE_SCHEMA

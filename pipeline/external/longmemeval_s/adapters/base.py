from __future__ import annotations

from dataclasses import dataclass


ABSTENTION_INSTRUCTION = (
    "The question may contain a false premise or ask for unknown information. "
    "If the evidence does not establish the requested fact, say that the information is not available "
    "and briefly identify the missing or contradicted premise."
)

BASELINE_RESPONSE_SCHEMA = '{"answer": "..."}'

SCOPE_TIME_STATE_RESPONSE_SCHEMA = (
    '{"answer": "...", "evidence_session_ids": ["..."], '
    '"state_facets": [{"name": "...", "value": "...", "support_session_ids": ["..."]}], '
    '"rejected_claims": [{"claim": "...", "reason": "...", "support_session_ids": ["..."]}]}'
)

TASK_ADAPTER_RESPONSE_SCHEMA = (
    '{"answer": "...", "evidence_session_ids": ["..."], '
    '"state_facets": [{"name": "...", "value": "...", "support_session_ids": ["..."]}], '
    '"rejected_claims": [{"claim": "...", "reason": "...", "support_session_ids": ["..."]}], '
    '"answer_rationale": "..."}'
)


@dataclass(frozen=True)
class TaskAdapter:
    question_type: str
    task_name: str
    task_instruction: str
    scope_time_state_instruction: str
    evidence_instruction: str = ""
    answer_instruction: str = ""

    def instruction(self, is_abstention: bool) -> str:
        parts = [self.task_instruction, self.scope_time_state_instruction]
        if is_abstention:
            parts.append(ABSTENTION_INSTRUCTION)
        else:
            parts.append(
                "If the provided sessions still do not contain enough evidence, answer \"I don't know\" instead of guessing."
            )
        return " ".join(parts)

    def response_schema(self, variant: str) -> str:
        if variant == "scope_time_state_public":
            return SCOPE_TIME_STATE_RESPONSE_SCHEMA
        if variant == "scope_time_state_task_adapter":
            return TASK_ADAPTER_RESPONSE_SCHEMA
        return BASELINE_RESPONSE_SCHEMA

    def evidence_prompt_instruction(self) -> str:
        return self.evidence_instruction or self.task_instruction

    def answer_prompt_instruction(self) -> str:
        return self.answer_instruction or self.task_instruction

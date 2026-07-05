from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class TaskAdapter:
    qtype: str
    task_name: str
    scope_instruction: str
    claim_instruction: str
    relation_instruction: str
    facet_instruction: str
    answer_instruction: str
    source_anchor_required: bool = False
    alias_normalization_required: bool = False

    def prompt_payload(self) -> Dict[str, object]:
        return {
            "qtype": self.qtype,
            "task_name": self.task_name,
            "scope_instruction": self.scope_instruction,
            "claim_instruction": self.claim_instruction,
            "relation_instruction": self.relation_instruction,
            "facet_instruction": self.facet_instruction,
            "answer_instruction": self.answer_instruction,
            "source_anchor_required": self.source_anchor_required,
            "alias_normalization_required": self.alias_normalization_required,
        }


TASK_TYPES: Tuple[str, ...] = (
    "multi_hop",
    "knowledge_update",
    "temporal",
    "user_implicit",
    "term_ambiguity",
    "abstention",
)


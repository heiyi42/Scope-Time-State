from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Event:
    event_id: str
    scope_id: str
    content: str
    event_type: str
    occurred_at: str
    mentioned_at: str
    updated_at: str
    status: str = "active"
    planned_for: Optional[str] = None
    deadline_at: Optional[str] = None
    source_id: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)
    corrects: Tuple[str, ...] = ()
    supersedes: Tuple[str, ...] = ()
    state_relevant: bool = True
    has_status_annotation: bool = False
    has_state_relevant_annotation: bool = False
    has_relation_annotations: bool = False


@dataclass(frozen=True)
class QueryCase:
    case_id: str
    query: str
    scope_id: str
    operation: str
    time_roles: Tuple[str, ...]
    output_slots: Tuple[str, ...]
    gold_events: Tuple[str, ...]
    gold_state_slots: Dict[str, str]
    gold_slot_support: Dict[str, Tuple[str, ...]]
    difficulty_tags: Tuple[str, ...] = ()
    hard_negative_events: Tuple[str, ...] = ()
    answerability: str = "answerable"

    @property
    def time_role(self) -> str:
        return self.time_roles[0] if self.time_roles else "updated_at"


@dataclass
class EvalRow:
    case_id: str
    query: str
    event_f1: float
    event_precision: float
    gold_event_recall: float
    context_event_recall: Optional[float]
    slot_support_accuracy: float
    slot_support_f1: float
    required_support_f1: float
    slot_value_judge: Optional[float]
    answer_judge: Optional[float]
    invalid_distractor_rate: Optional[float]
    over_evidence_rate: Optional[float]
    over_evidence_count: int
    unknown_current_correct: Optional[float]
    unknown_current_false_completion: Optional[bool]
    hard_negative_hits: List[str]
    time_roles: Tuple[str, ...]
    difficulty_tags: Tuple[str, ...]
    answerability: str
    pred_events: List[str]
    pred_state_slots: Dict[str, Dict[str, object]]
    answer: str
    raw_output: Dict[str, object]
    judge_output: Optional[Dict[str, object]]

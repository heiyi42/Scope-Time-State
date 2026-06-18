from __future__ import annotations

import os
from typing import Dict, List, Tuple

from Experiment.run.common.metrics import (
    context_events,
    declared_evidence_events,
    f1,
    gold_support_event_pool,
    over_evidence_diagnostic,
    set_precision,
    set_recall,
    slot_support_f1,
    support_accuracy,
    unknown_current_diagnostic,
)
from Experiment.run.common.models import EvalRow, QueryCase
from Experiment.run.common.utils import normalize_support_events


def normalize_model_output(raw: Dict[str, object], case: QueryCase) -> Tuple[List[str], Dict[str, Dict[str, object]], str]:
    evidence = raw.get("evidence_events", [])
    if not isinstance(evidence, list):
        evidence = []
    pred_events = [str(item) for item in evidence]

    state_slots: Dict[str, Dict[str, object]] = {}

    raw_slots = raw.get("state_slots", {})
    if isinstance(raw_slots, dict):
        for slot in case.output_slots:
            item = raw_slots.get(slot)
            if isinstance(item, dict):
                value = item.get("value")
                support = item.get("support_event")
                support_events = normalize_support_events(item)
                state_slots[slot] = {
                    "value": str(value) if value is not None else "",
                    "support_event": str(support) if support not in {None, "null", ""} else None,
                    "support_events": list(support_events),
                }
            elif isinstance(item, str):
                state_slots[slot] = {"value": item, "support_event": None, "support_events": []}

    answer = raw.get("answer", "")
    return pred_events, state_slots, str(answer)


def evaluate_output(raw: Dict[str, object], case: QueryCase) -> EvalRow:
    pred_events, state_slots, answer = normalize_model_output(raw, case)
    pred_event_set = set(pred_events)
    hard_negative_set = set(case.hard_negative_events)
    hard_negative_hits = sorted(pred_event_set & hard_negative_set)
    invalid_distractor_rate = (
        round(len(hard_negative_hits) / len(pred_event_set), 3)
        if pred_event_set and hard_negative_set
        else None
    )
    pred_support = {slot: item.get("support_event") for slot, item in state_slots.items()}
    pred_support_sets = {
        slot: tuple(str(event_id) for event_id in item.get("support_events", []))
        for slot, item in state_slots.items()
    }
    declared_events = declared_evidence_events(pred_events, pred_support_sets)
    over_evidence_rate, over_evidence_count = over_evidence_diagnostic(declared_events, case)
    unknown_current_correct, unknown_current_false_completion = unknown_current_diagnostic(state_slots, answer, case)
    required_support_events = gold_support_event_pool(case)
    ctx_events = context_events(case)
    return EvalRow(
        case_id=case.case_id,
        query=case.query,
        event_f1=round(f1(pred_events, case.gold_events), 3),
        event_precision=round(set_precision(pred_events, case.gold_events), 3),
        gold_event_recall=round(set_recall(pred_events, case.gold_events), 3),
        context_event_recall=round(set_recall(pred_events, ctx_events), 3) if ctx_events else None,
        slot_support_accuracy=round(support_accuracy(pred_support, case.gold_slot_support), 3),
        slot_support_f1=round(slot_support_f1(pred_support_sets, case.gold_slot_support), 3),
        required_support_f1=round(f1(pred_events, required_support_events), 3),
        slot_value_judge=None,
        answer_judge=None,
        invalid_distractor_rate=invalid_distractor_rate,
        over_evidence_rate=over_evidence_rate,
        over_evidence_count=over_evidence_count,
        unknown_current_correct=unknown_current_correct,
        unknown_current_false_completion=unknown_current_false_completion,
        hard_negative_hits=hard_negative_hits,
        time_roles=case.time_roles,
        difficulty_tags=case.difficulty_tags,
        answerability=case.answerability,
        pred_events=pred_events,
        pred_state_slots=state_slots,
        answer=answer,
        raw_output=raw,
        judge_output=None,
    )


def should_skip_judge_failures() -> bool:
    return os.environ.get("JUDGE_FAILURE_POLICY", "fail").lower() == "skip"

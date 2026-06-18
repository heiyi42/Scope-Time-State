from __future__ import annotations

import re
from typing import Dict, Iterable, Optional, Sequence, Set, Tuple

from Experiment.run.common.models import QueryCase


def f1(predicted: Iterable[str], gold: Iterable[str]) -> float:
    pred_set = set(predicted)
    gold_set = set(gold)
    if not pred_set and not gold_set:
        return 1.0
    if not pred_set or not gold_set:
        return 0.0
    tp = len(pred_set & gold_set)
    precision = tp / len(pred_set)
    recall = tp / len(gold_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def set_precision(predicted: Iterable[str], gold: Iterable[str]) -> float:
    pred_set = set(predicted)
    gold_set = set(gold)
    if not pred_set and not gold_set:
        return 1.0
    if not pred_set:
        return 0.0
    return len(pred_set & gold_set) / len(pred_set)


def set_recall(predicted: Iterable[str], gold: Iterable[str]) -> float:
    pred_set = set(predicted)
    gold_set = set(gold)
    if not pred_set and not gold_set:
        return 1.0
    if not gold_set:
        return 1.0
    return len(pred_set & gold_set) / len(gold_set)


def support_accuracy(predicted: Dict[str, Optional[str]], gold: Dict[str, Tuple[str, ...]]) -> float:
    if not gold:
        return 1.0
    correct = sum(1 for key, values in gold.items() if predicted.get(key) in values)
    return correct / len(gold)


def slot_support_f1(predicted: Dict[str, Tuple[str, ...]], gold: Dict[str, Tuple[str, ...]]) -> float:
    if not gold:
        return 1.0
    scores = []
    for slot, gold_events in gold.items():
        scores.append(f1(predicted.get(slot, ()), gold_events))
    return sum(scores) / len(scores)


def gold_support_event_pool(case: QueryCase) -> Set[str]:
    return {event_id for values in case.gold_slot_support.values() for event_id in values}


def context_events(case: QueryCase) -> Set[str]:
    return set(case.gold_events) - gold_support_event_pool(case)


UNKNOWN_CURRENT_MARKERS = (
    "无法确认",
    "不能确认",
    "不能确定",
    "无法确定",
    "没有完成记录",
    "无完成记录",
    "没有提交记录",
    "无提交记录",
    "没有补完记录",
    "无补完记录",
    "没有复核记录",
    "无复核记录",
    "没有明确完成",
    "没有明确提交",
    "没有明确补完",
    "没有明确复核",
    "没有足够证据",
    "证据不足",
    "只有计划",
    "只有安排",
    "只有草稿",
    "仍待",
    "还只是计划",
    "no completion record",
    "no submission record",
    "no review record",
    "cannot confirm",
    "can't confirm",
    "not enough evidence",
    "insufficient evidence",
    "only planned",
    "only a plan",
    "unknown",
    "unclear",
    "not confirmed",
)

FALSE_COMPLETION_PATTERNS = (
    r"(?<!无法确认)(?<!不能确认)(?<!无法确定)(?<!不能确定)已经完成",
    r"(?<!无法确认)(?<!不能确认)(?<!无法确定)(?<!不能确定)已完成",
    r"完成了",
    r"已经提交",
    r"已提交",
    r"正式提交",
    r"已经补完",
    r"已补完",
    r"补完了",
    r"复核完成",
    r"培训完成",
    r"\bcompleted\b",
    r"\bsubmitted\b",
    r"\bdone\b",
    r"\bfinished\b",
)


def declared_evidence_events(pred_events: Sequence[str], pred_support_sets: Dict[str, Tuple[str, ...]]) -> Set[str]:
    declared = {str(event_id) for event_id in pred_events if event_id not in {None, "", "null"}}
    for support_events in pred_support_sets.values():
        declared.update(str(event_id) for event_id in support_events if event_id not in {None, "", "null"})
    return declared


def over_evidence_diagnostic(declared_events: Set[str], case: QueryCase) -> Tuple[Optional[float], int]:
    if not declared_events:
        return None, 0
    required_support = gold_support_event_pool(case)
    extra_events = declared_events - required_support
    return round(len(extra_events) / len(declared_events), 3), len(extra_events)


def is_unknown_current_case(case: QueryCase) -> bool:
    return case.answerability == "unknown_current" or "unknown_current" in set(case.difficulty_tags)


def text_has_any(text: str, markers: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def unknown_current_text(state_slots: Dict[str, Dict[str, object]], answer: str) -> str:
    values = [
        str(item.get("value", ""))
        for item in state_slots.values()
        if isinstance(item, dict)
    ]
    values.append(str(answer))
    return "\n".join(values)


def false_completion_claim(text: str) -> bool:
    if not text.strip():
        return False
    if text_has_any(text, UNKNOWN_CURRENT_MARKERS):
        return False
    lowered = text.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in FALSE_COMPLETION_PATTERNS)


def unknown_current_diagnostic(
    state_slots: Dict[str, Dict[str, object]],
    answer: str,
    case: QueryCase,
) -> Tuple[Optional[float], Optional[bool]]:
    if not is_unknown_current_case(case):
        return None, None
    text = unknown_current_text(state_slots, answer)
    has_unknown_marker = text_has_any(text, UNKNOWN_CURRENT_MARKERS)
    false_completed = false_completion_claim(text)
    return (1.0 if has_unknown_marker and not false_completed else 0.0), false_completed

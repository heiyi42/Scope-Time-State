from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from v1_common import normalize_id_list, write_json


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def normalize_text(value: Any) -> str:
    text = str(value).lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。；：、“”\"'`（）()\\[\\]{}<>《》]", "", text)
    return text


def f1(predicted: Iterable[str], gold: Iterable[str]) -> Dict[str, float]:
    pred_set = set(str(item) for item in predicted)
    gold_set = set(str(item) for item in gold)
    true_positive = len(pred_set & gold_set)
    precision = true_positive / len(pred_set) if pred_set else (1.0 if not gold_set else 0.0)
    recall = true_positive / len(gold_set) if gold_set else (1.0 if not pred_set else 0.0)
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": score}


def flatten_slot_support(row: Mapping[str, Any]) -> List[str]:
    support = row.get("gold_slot_support", {})
    ids: List[str] = []
    if isinstance(support, Mapping):
        for values in support.values():
            ids.extend(normalize_id_list(values))
    return sorted(set(ids))


def hard_negative_type_pairs(row: Mapping[str, Any]) -> List[str]:
    pairs: List[str] = []
    raw = row.get("hard_negative_types", {})
    if not isinstance(raw, Mapping):
        return pairs
    for event_id, labels in raw.items():
        if isinstance(labels, list):
            for label in labels:
                pairs.append(f"{event_id}::{label}")
    return sorted(set(pairs))


def slot_value_exact(row: Mapping[str, Any]) -> List[str]:
    slots = row.get("gold_state_slots", {})
    if not isinstance(slots, Mapping):
        return []
    return [f"{slot}::{normalize_text(value)}" for slot, value in sorted(slots.items())]


def index_by_case_id(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    return {str(row["case_id"]): row for row in rows}


def compare_rows(predicted_rows: Sequence[Mapping[str, Any]], gold_rows: Sequence[Mapping[str, Any]], label: str) -> Dict[str, Any]:
    pred_by_id = index_by_case_id(predicted_rows)
    gold_by_id = index_by_case_id(gold_rows)
    shared_ids = sorted(set(pred_by_id) & set(gold_by_id))
    missing_predictions = sorted(set(gold_by_id) - set(pred_by_id))
    extra_predictions = sorted(set(pred_by_id) - set(gold_by_id))

    answerability_correct = 0
    support_scores: List[Dict[str, float]] = []
    hard_negative_scores: List[Dict[str, float]] = []
    hard_negative_type_scores: List[Dict[str, float]] = []
    slot_value_scores: List[Dict[str, float]] = []
    answerability_confusion: Counter[str] = Counter()

    for case_id in shared_ids:
        pred = pred_by_id[case_id]
        gold = gold_by_id[case_id]
        pred_answerability = str(pred.get("answerability", ""))
        gold_answerability = str(gold.get("answerability", ""))
        if pred_answerability == gold_answerability:
            answerability_correct += 1
        answerability_confusion[f"{gold_answerability}->{pred_answerability}"] += 1
        support_scores.append(f1(flatten_slot_support(pred), flatten_slot_support(gold)))
        hard_negative_scores.append(f1(normalize_id_list(pred.get("hard_negative_events")), normalize_id_list(gold.get("hard_negative_events"))))
        hard_negative_type_scores.append(f1(hard_negative_type_pairs(pred), hard_negative_type_pairs(gold)))
        slot_value_scores.append(f1(slot_value_exact(pred), slot_value_exact(gold)))

    def mean_metric(scores: Sequence[Mapping[str, float]], key: str) -> float:
        return sum(score[key] for score in scores) / len(scores) if scores else 0.0

    return {
        "label": label,
        "gold_cases": len(gold_by_id),
        "predicted_cases": len(pred_by_id),
        "shared_cases": len(shared_ids),
        "missing_predictions": missing_predictions,
        "extra_predictions": extra_predictions,
        "answerability_accuracy": answerability_correct / len(shared_ids) if shared_ids else 0.0,
        "answerability_confusion": dict(sorted(answerability_confusion.items())),
        "support_event": {key: mean_metric(support_scores, key) for key in ["precision", "recall", "f1"]},
        "hard_negative_event": {key: mean_metric(hard_negative_scores, key) for key in ["precision", "recall", "f1"]},
        "hard_negative_type": {key: mean_metric(hard_negative_type_scores, key) for key in ["precision", "recall", "f1"]},
        "slot_value_exact": {key: mean_metric(slot_value_scores, key) for key in ["precision", "recall", "f1"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score STAMB-State annotation agreement against gold or between annotators.")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--second-annotations", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    gold_rows = read_jsonl(args.gold)
    annotation_rows = read_jsonl(args.annotations)
    report: Dict[str, Any] = {
        "against_gold": compare_rows(annotation_rows, gold_rows, "annotations_vs_gold")
    }
    if args.second_annotations:
        second_rows = read_jsonl(args.second_annotations)
        report["second_against_gold"] = compare_rows(second_rows, gold_rows, "second_annotations_vs_gold")
        report["annotator_agreement"] = compare_rows(annotation_rows, second_rows, "annotations_vs_second_annotations")
    if args.out:
        write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

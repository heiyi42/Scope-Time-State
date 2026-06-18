from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EXPERIMENT_DIR.parent
BENCHMARK_DIR = PROJECT_DIR / "stamb_state_benchmark"
sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.run_oracle_benchmark import (
    QueryCase,
    declared_evidence_events,
    context_events,
    f1,
    gold_support_event_pool,
    load_cases,
    over_evidence_diagnostic,
    set_precision,
    set_recall,
    slot_support_f1,
    slot_judge_score,
    support_accuracy,
    answer_judge_score,
    unknown_current_diagnostic,
)


def support_map(row: Dict[str, object], case: QueryCase) -> Dict[str, Optional[str]]:
    raw_slots = row.get("pred_state_slots", {})
    if not isinstance(raw_slots, dict):
        return {}
    supports: Dict[str, Optional[str]] = {}
    for slot in case.output_slots:
        item = raw_slots.get(slot)
        if not isinstance(item, dict):
            supports[slot] = None
            continue
        support = item.get("support_event")
        supports[slot] = str(support) if support not in {None, "", "null"} else None
    return supports


def support_set_map(row: Dict[str, object], case: QueryCase) -> Dict[str, Tuple[str, ...]]:
    raw_slots = row.get("pred_state_slots", {})
    if not isinstance(raw_slots, dict):
        return {}
    supports: Dict[str, Tuple[str, ...]] = {}
    for slot in case.output_slots:
        item = raw_slots.get(slot)
        if not isinstance(item, dict):
            supports[slot] = ()
            continue
        support_events = []
        raw_support_events = item.get("support_events")
        if isinstance(raw_support_events, list):
            support_events = [str(event_id) for event_id in raw_support_events if event_id not in {None, "", "null"}]
        support = item.get("support_event")
        if support not in {None, "", "null"}:
            support_text = str(support)
            if support_text not in support_events:
                support_events.insert(0, support_text)
        supports[slot] = tuple(support_events)
    return supports


def score_case(row: Dict[str, object], case: QueryCase) -> Dict[str, Optional[float]]:
    pred_events = row.get("pred_events", [])
    if not isinstance(pred_events, list):
        pred_events = []
    pred_event_ids = [str(event_id) for event_id in pred_events]
    ctx = context_events(case)
    pred_set = set(pred_event_ids)
    hard_negative_set = set(case.hard_negative_events)
    invalid_distractor_rate = (
        round(len(pred_set & hard_negative_set) / len(pred_set), 3)
        if pred_set and hard_negative_set
        else None
    )
    support_sets = support_set_map(row, case)
    declared_events = declared_evidence_events(pred_event_ids, support_sets)
    over_evidence_rate, over_evidence_count = over_evidence_diagnostic(declared_events, case)
    raw_slots = row.get("pred_state_slots", {})
    state_slots = raw_slots if isinstance(raw_slots, dict) else {}
    unknown_current_correct, unknown_current_false_completion = unknown_current_diagnostic(
        state_slots,
        str(row.get("answer", "")),
        case,
    )
    judge_output = row.get("judge_output")
    slot_value_judge = row.get("slot_value_judge")
    answer_judge = row.get("answer_judge")
    if isinstance(judge_output, dict):
        slot_value_judge = slot_judge_score(judge_output, case)
        answer_judge = answer_judge_score(judge_output)
    return {
        "event_f1": round(f1(pred_event_ids, case.gold_events), 3),
        "required_support_f1": round(f1(pred_event_ids, gold_support_event_pool(case)), 3),
        "event_precision": round(set_precision(pred_event_ids, case.gold_events), 3),
        "gold_event_recall": round(set_recall(pred_event_ids, case.gold_events), 3),
        "context_event_recall": round(set_recall(pred_event_ids, ctx), 3) if ctx else None,
        "slot_support_accuracy": round(support_accuracy(support_map(row, case), case.gold_slot_support), 3),
        "slot_support_f1": round(slot_support_f1(support_sets, case.gold_slot_support), 3),
        "slot_value_judge": slot_value_judge,
        "answer_judge": answer_judge,
        "invalid_distractor_rate": invalid_distractor_rate,
        "over_evidence_rate": over_evidence_rate,
        "over_evidence_count": float(over_evidence_count),
        "unknown_current_correct": unknown_current_correct,
        "unknown_current_false_completion": 1.0 if unknown_current_false_completion else 0.0
        if unknown_current_false_completion is not None
        else None,
    }


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 3)


def summarize_scores(scored_rows: Sequence[Tuple[Dict[str, object], QueryCase, Dict[str, Optional[float]]]]) -> Dict[str, object]:
    return {
        "n_cases": len(scored_rows),
        "event_f1": mean(score["event_f1"] for _, _, score in scored_rows),
        "required_support_f1": mean(score["required_support_f1"] for _, _, score in scored_rows),
        "event_precision": mean(score["event_precision"] for _, _, score in scored_rows),
        "gold_event_recall": mean(score["gold_event_recall"] for _, _, score in scored_rows),
        "context_event_recall": mean(score["context_event_recall"] for _, _, score in scored_rows),
        "slot_support_accuracy": mean(score["slot_support_accuracy"] for _, _, score in scored_rows),
        "slot_support_f1": mean(score["slot_support_f1"] for _, _, score in scored_rows),
        "slot_value_judge": mean(score["slot_value_judge"] for _, _, score in scored_rows),
        "answer_judge": mean(score["answer_judge"] for _, _, score in scored_rows),
        "invalid_distractor_rate": mean(score["invalid_distractor_rate"] for _, _, score in scored_rows),
        "over_evidence_rate": mean(score["over_evidence_rate"] for _, _, score in scored_rows),
        "unknown_current_accuracy": mean(score["unknown_current_correct"] for _, _, score in scored_rows),
        "unknown_current_false_completion_rate": mean(
            score["unknown_current_false_completion"] for _, _, score in scored_rows
        ),
    }


def breakdown_by_difficulty(
    scored_rows: Sequence[Tuple[Dict[str, object], QueryCase, Dict[str, Optional[float]]]]
) -> Dict[str, Dict[str, object]]:
    tags = sorted({tag for _, case, _ in scored_rows for tag in case.difficulty_tags})
    return {
        tag: summarize_scores([item for item in scored_rows if tag in item[1].difficulty_tags])
        for tag in tags
    }


def breakdown_by_answerability(
    scored_rows: Sequence[Tuple[Dict[str, object], QueryCase, Dict[str, Optional[float]]]]
) -> Dict[str, Dict[str, object]]:
    labels = sorted({case.answerability for _, case, _ in scored_rows})
    return {
        label: summarize_scores([item for item in scored_rows if item[1].answerability == label])
        for label in labels
    }


def analyze_result(path: Path, cases_by_id: Dict[str, QueryCase]) -> List[Dict[str, object]]:
    results = json.loads(path.read_text())
    if not isinstance(results, list):
        raise RuntimeError(f"{path} is not a benchmark result list")
    summaries: List[Dict[str, object]] = []
    for result in results:
        rows = result.get("cases", [])
        if not isinstance(rows, list):
            continue
        scored_rows: List[Tuple[Dict[str, object], QueryCase, Dict[str, Optional[float]]]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            case_id = str(row.get("case_id", ""))
            case = cases_by_id.get(case_id)
            if case is None:
                continue
            scored_rows.append((row, case, score_case(row, case)))
        if not scored_rows:
            continue
        summary = summarize_scores(scored_rows)
        summary.update(
            {
                "file": str(path),
                "variant": result.get("variant", "unknown"),
                "data_version": result.get("data_version"),
                "track": result.get("track"),
                "breakdown_by_difficulty": breakdown_by_difficulty(scored_rows),
                "breakdown_by_answerability": breakdown_by_answerability(scored_rows),
                "low_cases": [
                    {
                        "case_id": row.get("case_id"),
                        "difficulty_tags": list(case.difficulty_tags),
                        "answerability": case.answerability,
                        "event_f1": score["event_f1"],
                        "required_support_f1": score["required_support_f1"],
                        "event_precision": score["event_precision"],
                        "gold_event_recall": score["gold_event_recall"],
                        "context_event_recall": score["context_event_recall"],
                        "slot_support_accuracy": score["slot_support_accuracy"],
                        "slot_support_f1": score["slot_support_f1"],
                        "slot_value_judge": score["slot_value_judge"],
                        "answer_judge": score["answer_judge"],
                        "invalid_distractor_rate": score["invalid_distractor_rate"],
                        "over_evidence_rate": score["over_evidence_rate"],
                        "over_evidence_count": score["over_evidence_count"],
                        "unknown_current_correct": score["unknown_current_correct"],
                        "unknown_current_false_completion": score["unknown_current_false_completion"],
                    }
                    for row, case, score in scored_rows
                    if score["slot_support_accuracy"] != 1.0
                    or score["slot_support_f1"] != 1.0
                    or score["slot_value_judge"] not in {None, 1.0}
                    or score["answer_judge"] not in {None, 1.0}
                    or score["invalid_distractor_rate"] not in {None, 0.0}
                    or score["over_evidence_rate"] not in {None, 0.0}
                    or score["unknown_current_correct"] not in {None, 1.0}
                ],
            }
        )
        summaries.append(summary)
    return summaries


def print_table(summaries: Sequence[Dict[str, object]]) -> None:
    print(f"{'file':<34} {'variant':<34} {'n':>4} {'ev_f1':>7} {'req_f1':>7} {'ev_p':>7} {'ev_r':>7} {'support':>8} {'sup_f1':>8} {'hard_neg':>8} {'over_ev':>8} {'unk_cur':>8} {'slot_j':>8} {'ans_j':>8}")
    print("-" * 168)
    for summary in summaries:
        def fmt(key: str, width: int = 7) -> str:
            value = summary.get(key)
            return f"{value:>{width}.3f}" if isinstance(value, float) else f"{'n/a':>{width}}"

        print(
            f"{Path(str(summary['file'])).name:<34} "
            f"{str(summary['variant']):<34} "
            f"{summary.get('n_cases', 'n/a'):>4} "
            f"{fmt('event_f1')} "
            f"{fmt('required_support_f1')} "
            f"{fmt('event_precision')} "
            f"{fmt('gold_event_recall')} "
            f"{fmt('slot_support_accuracy', 8)} "
            f"{fmt('slot_support_f1', 8)} "
            f"{fmt('invalid_distractor_rate', 8)} "
            f"{fmt('over_evidence_rate', 8)} "
            f"{fmt('unknown_current_accuracy', 8)} "
            f"{fmt('slot_value_judge', 8)} "
            f"{fmt('answer_judge', 8)}"
        )


def print_breakdowns(summaries: Sequence[Dict[str, object]]) -> None:
    def fmt(value: object) -> str:
        return f"{value:.3f}" if isinstance(value, float) else "n/a"

    for summary in summaries:
        print(f"\n{Path(str(summary['file'])).name} / {summary['variant']} difficulty breakdown")
        for tag, metrics in summary.get("breakdown_by_difficulty", {}).items():
            print(
                f"{tag:<30} n={metrics['n_cases']:<3} "
                f"sup_f1={fmt(metrics['slot_support_f1'])} "
                f"slot_j={fmt(metrics['slot_value_judge'])} "
                f"ans_j={fmt(metrics['answer_judge'])} "
                f"hard_neg={fmt(metrics['invalid_distractor_rate'])} "
                f"over_ev={fmt(metrics['over_evidence_rate'])} "
                f"unk_cur={fmt(metrics['unknown_current_accuracy'])}"
            )
        print(f"\n{Path(str(summary['file'])).name} / {summary['variant']} answerability breakdown")
        for label, metrics in summary.get("breakdown_by_answerability", {}).items():
            print(
                f"{label:<30} n={metrics['n_cases']:<3} "
                f"sup_f1={fmt(metrics['slot_support_f1'])} "
                f"slot_j={fmt(metrics['slot_value_judge'])} "
                f"ans_j={fmt(metrics['answer_judge'])} "
                f"hard_neg={fmt(metrics['invalid_distractor_rate'])} "
                f"over_ev={fmt(metrics['over_evidence_rate'])} "
                f"unk_cur={fmt(metrics['unknown_current_accuracy'])}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute metric views for saved STAMB-State results.")
    parser.add_argument("results", nargs="+", help="Result JSON files to analyze.")
    parser.add_argument("--cases", default=str(BENCHMARK_DIR / "data/v1/cases.json"))
    parser.add_argument("--show-low-cases", action="store_true")
    parser.add_argument("--show-breakdown", action="store_true")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    cases_by_id = {case.case_id: case for case in cases}
    summaries: List[Dict[str, object]] = []
    for result_path in args.results:
        summaries.extend(analyze_result(Path(result_path), cases_by_id))
    print_table(summaries)
    if args.show_breakdown:
        print_breakdowns(summaries)
    if args.show_low_cases:
        for summary in summaries:
            print(f"\n{Path(str(summary['file'])).name} / {summary['variant']} low cases")
            for row in summary["low_cases"]:
                print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


BENCHMARK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCHMARK_DIR))

from run_llm_benchmark import (
    QueryCase,
    context_events,
    f1,
    gold_support_event_pool,
    load_cases,
    set_precision,
    set_recall,
    slot_support_f1,
    support_accuracy,
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
    return {
        "event_f1": round(f1(pred_event_ids, case.gold_events), 3),
        "required_support_f1": round(f1(pred_event_ids, gold_support_event_pool(case)), 3),
        "event_precision": round(set_precision(pred_event_ids, case.gold_events), 3),
        "gold_event_recall": round(set_recall(pred_event_ids, case.gold_events), 3),
        "context_event_recall": round(set_recall(pred_event_ids, ctx), 3) if ctx else None,
        "slot_support_accuracy": round(support_accuracy(support_map(row, case), case.gold_slot_support), 3),
        "slot_support_f1": round(slot_support_f1(support_set_map(row, case), case.gold_slot_support), 3),
        "slot_value_judge": row.get("slot_value_judge"),
        "answer_judge": row.get("answer_judge"),
    }


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 3)


def analyze_result(path: Path, cases_by_id: Dict[str, QueryCase]) -> List[Dict[str, object]]:
    results = json.loads(path.read_text())
    if not isinstance(results, list):
        raise RuntimeError(f"{path} is not a benchmark result list")
    summaries: List[Dict[str, object]] = []
    for result in results:
        rows = result.get("cases", [])
        if not isinstance(rows, list):
            continue
        scored_rows: List[Tuple[Dict[str, object], Dict[str, Optional[float]]]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            case_id = str(row.get("case_id", ""))
            case = cases_by_id.get(case_id)
            if case is None:
                continue
            scored_rows.append((row, score_case(row, case)))
        if not scored_rows:
            continue
        summaries.append(
            {
                "file": str(path),
                "variant": result.get("variant", "unknown"),
                "event_f1": mean(score["event_f1"] for _, score in scored_rows),
                "required_support_f1": mean(score["required_support_f1"] for _, score in scored_rows),
                "event_precision": mean(score["event_precision"] for _, score in scored_rows),
                "gold_event_recall": mean(score["gold_event_recall"] for _, score in scored_rows),
                "context_event_recall": mean(score["context_event_recall"] for _, score in scored_rows),
                "slot_support_accuracy": mean(score["slot_support_accuracy"] for _, score in scored_rows),
                "slot_support_f1": mean(score["slot_support_f1"] for _, score in scored_rows),
                "slot_value_judge": mean(score["slot_value_judge"] for _, score in scored_rows),
                "answer_judge": mean(score["answer_judge"] for _, score in scored_rows),
                "low_cases": [
                    {
                        "case_id": row.get("case_id"),
                        "event_f1": score["event_f1"],
                        "required_support_f1": score["required_support_f1"],
                        "event_precision": score["event_precision"],
                        "gold_event_recall": score["gold_event_recall"],
                        "context_event_recall": score["context_event_recall"],
                        "slot_support_accuracy": score["slot_support_accuracy"],
                        "slot_support_f1": score["slot_support_f1"],
                        "slot_value_judge": score["slot_value_judge"],
                        "answer_judge": score["answer_judge"],
                    }
                    for row, score in scored_rows
                    if score["slot_support_accuracy"] != 1.0
                    or score["slot_support_f1"] != 1.0
                    or score["slot_value_judge"] not in {None, 1.0}
                    or score["answer_judge"] not in {None, 1.0}
                ],
            }
        )
    return summaries


def print_table(summaries: Sequence[Dict[str, object]]) -> None:
    print(f"{'file':<34} {'variant':<34} {'ev_f1':>7} {'req_f1':>7} {'ev_p':>7} {'ev_r':>7} {'support':>8} {'sup_f1':>8} {'slot_j':>8} {'ans_j':>8}")
    print("-" * 134)
    for summary in summaries:
        def fmt(key: str, width: int = 7) -> str:
            value = summary.get(key)
            return f"{value:>{width}.3f}" if isinstance(value, float) else f"{'n/a':>{width}}"

        print(
            f"{Path(str(summary['file'])).name:<34} "
            f"{str(summary['variant']):<34} "
            f"{fmt('event_f1')} "
            f"{fmt('required_support_f1')} "
            f"{fmt('event_precision')} "
            f"{fmt('gold_event_recall')} "
            f"{fmt('slot_support_accuracy', 8)} "
            f"{fmt('slot_support_f1', 8)} "
            f"{fmt('slot_value_judge', 8)} "
            f"{fmt('answer_judge', 8)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute metric views for saved STAMB-State results.")
    parser.add_argument("results", nargs="+", help="Result JSON files to analyze.")
    parser.add_argument("--cases", default=str(BENCHMARK_DIR / "data/cases.json"))
    parser.add_argument("--show-low-cases", action="store_true")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    cases_by_id = {case.case_id: case for case in cases}
    summaries: List[Dict[str, object]] = []
    for result_path in args.results:
        summaries.extend(analyze_result(Path(result_path), cases_by_id))
    print_table(summaries)
    if args.show_low_cases:
        for summary in summaries:
            print(f"\n{Path(str(summary['file'])).name} / {summary['variant']} low cases")
            for row in summary["low_cases"]:
                print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

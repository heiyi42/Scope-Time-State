from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence

from Experiment.run.run_public_benchmark.types import PublicEvalRow


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 3)


def summarize_rows(rows: Sequence[PublicEvalRow]) -> Dict[str, object]:
    return {
        "n_cases": len(rows),
        "avg_evidence_support_f1": mean(row.evidence_support_f1 for row in rows),
        "avg_evidence_precision": mean(row.evidence_precision for row in rows),
        "avg_gold_event_recall": mean(row.gold_event_recall for row in rows),
        "avg_facet_recall": mean(row.facet_recall for row in rows),
        "avg_facet_precision": mean(row.facet_precision for row in rows),
        "avg_answer_judge": mean(row.answer_judge for row in rows),
        "avg_answer_judge_10": mean(row.answer_judge_10 for row in rows),
        "avg_unsupported_claim_rate": mean(row.unsupported_claim_rate for row in rows),
        "avg_invalid_distractor_rate": mean(row.invalid_distractor_rate for row in rows),
        "avg_over_evidence_rate": mean(row.over_evidence_rate for row in rows),
        "unknown_current_accuracy": mean(row.unknown_current_correct for row in rows),
        "unknown_current_false_completion_rate": mean(
            1.0 if row.unknown_current_false_completion else 0.0
            for row in rows
            if row.unknown_current_false_completion is not None
        ),
        "unknown_current_cases": len([row for row in rows if row.unknown_current_correct is not None]),
        "unknown_current_false_completion_cases": [
            row.case_id for row in rows if row.unknown_current_false_completion
        ],
    }


def print_public_summary(
    provider: str,
    model: str,
    results: Sequence[Dict[str, object]],
    judge_provider: Optional[str],
    judge_model: Optional[str],
) -> None:
    print("STAMB-State public End-to-End benchmark")
    print(f"provider={provider} model={model}")
    if judge_provider and judge_model:
        print(f"judge_provider={judge_provider} judge_model={judge_model}")
    print("NOTE: public cases hide scope_id, output_slots, gold states, and gold support.")
    print()
    print(
        f"{'variant':<34} {'n':>4} {'ev_sup':>7} {'ev_p':>7} {'ev_r':>7} "
        f"{'facet_r':>8} {'facet_p':>8} {'ans_j':>8} {'ans_10':>8} "
        f"{'unsup':>8} {'hard_neg':>8} {'over_ev':>8} {'unk_cur':>8}"
    )
    print("-" * 143)
    for result in results:
        values = {
            "ev_sup": result.get("avg_evidence_support_f1"),
            "ev_p": result.get("avg_evidence_precision"),
            "ev_r": result.get("avg_gold_event_recall"),
            "facet_r": result.get("avg_facet_recall"),
            "facet_p": result.get("avg_facet_precision"),
            "ans_j": result.get("avg_answer_judge"),
            "ans_10": result.get("avg_answer_judge_10"),
            "unsup": result.get("avg_unsupported_claim_rate"),
            "hard_neg": result.get("avg_invalid_distractor_rate"),
            "over_ev": result.get("avg_over_evidence_rate"),
            "unk_cur": result.get("unknown_current_accuracy"),
        }
        formatted = {
            key: f"{value:>8.3f}" if isinstance(value, float) else f"{'n/a':>8}"
            for key, value in values.items()
        }
        print(
            f"{result['variant']:<34} {result['n_cases']:>4} "
            f"{formatted['ev_sup']} {formatted['ev_p']} {formatted['ev_r']} "
            f"{formatted['facet_r']} {formatted['facet_p']} {formatted['ans_j']} {formatted['ans_10']} "
            f"{formatted['unsup']} {formatted['hard_neg']} {formatted['over_ev']} {formatted['unk_cur']}"
        )
    print()

"""Path adapter around the official STEM and ARTEM evaluation modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from config import BOOK_ID, DEFAULT_OUTPUT_ROOT, OFFICIAL_ARTEM_DIR, book_output_dir


if str(OFFICIAL_ARTEM_DIR) not in sys.path:
    sys.path.insert(0, str(OFFICIAL_ARTEM_DIR))

import ARTEM_evaluation as official_artem_eval  # noqa: E402
import STEM_evaluation as official_stem_eval  # noqa: E402


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, default=str)
        stream.write("\n")


def run_stem_evaluation(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    """Evaluate retrieval with official STEM functions on the selected QA rows."""
    book_dir = book_output_dir(output_root)
    retrieval_path = book_dir / f"match_based_retrieval_results_book{BOOK_ID}.json"
    selected_qa_path = book_dir / "qa_selected_for_retrieval.json"
    with retrieval_path.open("r", encoding="utf-8") as stream:
        retrieval_data = json.load(stream)
    ground_truth = official_stem_eval.load_ground_truth(str(selected_qa_path))
    results = official_stem_eval.compare_retrieval_results(retrieval_data, ground_truth)

    output_dir = book_dir / "stem_evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "STEM_retrieval_results_analysis.json"
    results.to_json(results_path, orient="records", indent=2)
    official_stem_eval.create_performance_table(results).to_json(
        output_dir / "STEM_performance_table_bins.json", orient="records", indent=2
    )
    official_stem_eval.create_retrieval_type_table(results).to_json(
        output_dir / "STEM_performance_table_types.json", orient="records", indent=2
    )
    official_stem_eval.create_get_type_table(results).to_json(
        output_dir / "STEM_performance_table_get_types.json", orient="records", indent=2
    )
    official_stem_eval.create_recall_vs_chronological_comparison(results).to_json(
        output_dir / "STEM_recall_vs_chronological.json", orient="records", indent=2
    )
    _write_json(
        output_dir / "STEM_overall_performance.json",
        {
            "overall_f1_score": official_stem_eval.get_overall_f1_score(results),
            "mean_precision": results["precision"].mean(),
            "mean_recall": results["recall"].mean(),
            "f1_std": results["f1_score"].std(),
            "total_queries": len(results),
        },
    )
    print(f"Official STEM evaluation ready: {results_path}")
    return results_path


def latest_answer_result(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    output_dir = book_output_dir(output_root) / "art_evaluation_results"
    candidates = sorted(
        output_dir.glob("artem_gpt-4o-mini_q*_detailed_results.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"No official ARTEM detailed result found under {output_dir}")
    return candidates[-1]


def run_artem_evaluation(
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    detailed_result_path: Path | str | None = None,
) -> Path:
    """Evaluate integrated answers using official ARTEM evaluation functions."""
    detailed_path = (
        Path(detailed_result_path)
        if detailed_result_path is not None
        else latest_answer_result(output_root)
    )
    evaluation_rows = official_artem_eval.load_evaluation_results(str(detailed_path))
    retrieval_data, ground_truth = official_artem_eval.convert_to_artem_format(evaluation_rows)
    results = official_artem_eval.compare_retrieval_results(
        retrieval_data, ground_truth, evaluation_rows
    )
    results = official_artem_eval.correct_bin_zero_f1_scores_with_model_answers(
        results, evaluation_rows
    )

    output_dir = book_output_dir(output_root) / "artem_evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "ARTEM_retrieval_results_analysis.json"
    results.to_json(results_path, orient="records", indent=2)
    official_artem_eval.create_performance_table(results).to_json(
        output_dir / "ARTEM_performance_table_bins.json", orient="records", indent=2
    )
    official_artem_eval.create_retrieval_type_table(results).to_json(
        output_dir / "ARTEM_performance_table_types.json", orient="records", indent=2
    )
    official_artem_eval.create_get_type_table(results).to_json(
        output_dir / "ARTEM_performance_table_get_types.json", orient="records", indent=2
    )
    official_artem_eval.create_recall_vs_chronological_comparison(results).to_json(
        output_dir / "ARTEM_recall_vs_chronological.json", orient="records", indent=2
    )
    _write_json(
        output_dir / "ARTEM_overall_performance.json",
        {
            "overall_f1_score": official_artem_eval.get_overall_f1_score(results),
            "mean_precision": results["precision"].mean(),
            "mean_recall": results["recall"].mean(),
            "f1_std": results["f1_score"].std(),
            "total_queries": len(results),
            "source_detailed_result": str(detailed_path.resolve()),
        },
    )
    print(f"Official ARTEM evaluation ready: {results_path}")
    return results_path

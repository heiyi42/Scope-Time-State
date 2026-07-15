"""Run the official ARTEM method through the fixed EPBench Long Book adapter."""

from __future__ import annotations

import argparse
from pathlib import Path

from config import DEFAULT_OUTPUT_ROOT, validate_source_paths
from answer_eval import run_answer_and_eval
from extraction import extract_events, prepare_qa
from official_evaluation import run_artem_evaluation, run_stem_evaluation
from retrieval import run_epbench_retrieval


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=(
            "prepare",
            "extract",
            "retrieve",
            "stem-eval",
            "answer",
            "artem-eval",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--limit-chapters", type=int)
    parser.add_argument("--question-offset", type=int, default=0)
    parser.add_argument("--limit-questions", type=int, default=686)
    parser.add_argument("--max-retrievals", type=int, default=20)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    validate_source_paths()
    if args.stage in {"prepare", "extract", "all"}:
        print(f"Prepared QA: {prepare_qa(args.output_root)}")
    if args.stage in {"extract", "all"}:
        extract_events(
            output_root=args.output_root,
            limit_chapters=args.limit_chapters,
            resume=not args.no_resume,
            use_cache=not args.no_cache,
        )
    if args.stage in {"retrieve", "all"}:
        print(
            "Retrieval ready: "
            f"{run_epbench_retrieval(args.output_root, args.limit_questions, args.question_offset, args.max_retrievals)}"
        )
    if args.stage in {"stem-eval", "all"}:
        run_stem_evaluation(args.output_root)
    if args.stage in {"answer", "all"}:
        detailed_result = run_answer_and_eval(
            output_root=args.output_root,
            question_offset=args.question_offset,
            limit_questions=args.limit_questions,
            use_cache=not args.no_cache,
        )
    else:
        detailed_result = None
    if args.stage in {"artem-eval", "all"}:
        run_artem_evaluation(args.output_root, detailed_result)


if __name__ == "__main__":
    main()

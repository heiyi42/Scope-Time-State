from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, Optional, Sequence

from Experiment.run.common.io import (
    load_cases,
    load_dotenv,
    load_events,
    load_events_with_annotations,
    validate_benchmark,
)
from Experiment.run.common.paths import BENCHMARK_DIR
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config
from pipeline.oracle import run_variant
from Experiment.registry import canonical_variant_name, main_baseline_names


def print_summary(
    provider: str,
    model: str,
    results: Sequence[Dict[str, object]],
    judge_provider: Optional[str],
    judge_model: Optional[str],
) -> None:
    print("STAMB-State LLM benchmark")
    print(f"provider={provider} model={model}")
    if judge_provider and judge_model:
        print(f"judge_provider={judge_provider} judge_model={judge_model}")
    print("NOTE: variants share this runner; TSM and Validity/CUPMem use paper-structured memory stages, while Graphiti/Zep runs separately.")
    print()
    has_judge = any(result.get("avg_slot_value_judge") is not None for result in results)
    if has_judge:
        print(f"{'variant':<34} {'ev_f1':>7} {'req_f1':>7} {'ev_p':>7} {'ev_r':>7} {'support':>8} {'sup_f1':>8} {'hard_neg':>8} {'over_ev':>8} {'unk_cur':>8} {'slot_j':>8} {'ans_j':>8}")
        print("-" * 131)
    else:
        print(f"{'variant':<34} {'ev_f1':>7} {'req_f1':>7} {'ev_p':>7} {'ev_r':>7} {'support':>8} {'sup_f1':>8} {'hard_neg':>8} {'over_ev':>8} {'unk_cur':>8}")
        print("-" * 111)
    for result in results:
        hard_negative_rate = result.get("avg_invalid_distractor_rate")
        hard_negative_text = f"{hard_negative_rate:>8.3f}" if isinstance(hard_negative_rate, float) else f"{'n/a':>8}"
        over_evidence_rate = result.get("avg_over_evidence_rate")
        over_evidence_text = f"{over_evidence_rate:>8.3f}" if isinstance(over_evidence_rate, float) else f"{'n/a':>8}"
        unknown_current_accuracy = result.get("unknown_current_accuracy")
        unknown_current_text_value = (
            f"{unknown_current_accuracy:>8.3f}" if isinstance(unknown_current_accuracy, float) else f"{'n/a':>8}"
        )
        base = (
            f"{result['variant']:<34} "
            f"{result['avg_event_f1']:>7.3f} "
            f"{result['avg_required_support_f1']:>7.3f} "
            f"{result['avg_event_precision']:>7.3f} "
            f"{result['avg_gold_event_recall']:>7.3f} "
            f"{result['avg_slot_support_accuracy']:>8.3f} "
            f"{result['avg_slot_support_f1']:>8.3f} "
            f"{hard_negative_text} "
            f"{over_evidence_text} "
            f"{unknown_current_text_value}"
        )
        if has_judge:
            slot_judge = result.get("avg_slot_value_judge")
            answer_judge = result.get("avg_answer_judge")
            slot_text = f"{slot_judge:>8.3f}" if isinstance(slot_judge, float) else f"{'n/a':>8}"
            answer_text = f"{answer_judge:>8.3f}" if isinstance(answer_judge, float) else f"{'n/a':>8}"
            print(f"{base} {slot_text} {answer_text}")
        else:
            print(base)
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an LLM-backed STAMB-State benchmark.")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--data-version", choices=("v0", "v1", "v1_1"), default="v1")
    parser.add_argument(
        "--track",
        choices=("oracle_facet", "end_to_end"),
        default="oracle_facet",
        help="Use oracle_facet here; end_to_end public runs live in Experiment/run/run_public_benchmark.py.",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        default=list(main_baseline_names()),
    )
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--judge", action="store_true", help="Use an LLM judge for semantic slot-value grading.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument(
        "--tsm-construction-mode",
        choices=("llm", "heuristic"),
        default="llm",
        help="Use LLM extraction/update/summarization for TSM construction, or explicit heuristic fallback.",
    )
    parser.add_argument(
        "--ours-pipeline",
        choices=("two_stage", "stateframe", "graph_trace"),
        default="two_stage",
        help=(
            "Use the selected Ours readout pipeline. Main-table default is two_stage; "
            "stateframe and graph_trace are ablations."
        ),
    )
    parser.add_argument(
        "--ours-readout-policy",
        choices=("baseline", "minimized_no_background"),
        default="baseline",
        help="Use baseline Ours readout, or an explicit answer-focused minimizer/no-background ablation.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate benchmark files without calling an LLM.")
    parser.add_argument("--events", default=None)
    parser.add_argument("--cases", default=None)
    parser.add_argument("--event-annotations", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--cache", default=None)
    return parser.parse_args()


def resolve_data_paths(args: argparse.Namespace) -> Dict[str, Path]:
    if args.data_version in {"v1", "v1_1"}:
        data_dir = BENCHMARK_DIR / "data" / args.data_version
        events = Path(args.events) if args.events else data_dir / "events_raw.json"
        cases = Path(args.cases) if args.cases else data_dir / "cases.json"
        annotations = (
            Path(args.event_annotations)
            if args.event_annotations
            else data_dir / "event_annotations.json"
        )
        output = (
            Path(args.output)
            if args.output
            else BENCHMARK_DIR / f"output/results_{args.data_version}_{args.track}.json"
        )
        cache = (
            Path(args.cache)
            if args.cache
            else BENCHMARK_DIR / f"output/llm_cache.{args.data_version}_{args.track}.json"
        )
    else:
        events = Path(args.events) if args.events else BENCHMARK_DIR / "data/events.json"
        cases = Path(args.cases) if args.cases else BENCHMARK_DIR / "data/cases.json"
        annotations = Path(args.event_annotations) if args.event_annotations else None
        output = Path(args.output) if args.output else BENCHMARK_DIR / "output/results.json"
        cache = Path(args.cache) if args.cache else BENCHMARK_DIR / "output/llm_cache.json"
    return {
        "events": events,
        "cases": cases,
        "event_annotations": annotations,
        "output": output,
        "cache": cache,
    }


def main() -> int:
    args = parse_args()
    load_dotenv()
    if args.track == "end_to_end":
        print(
            "End-to-end v1 public track is implemented in Experiment/run/run_public_benchmark.py. "
            "Use Experiment/run/run_llm_benchmark.py for oracle_facet diagnostics.",
            file=sys.stderr,
        )
        return 2

    paths = resolve_data_paths(args)
    events = load_events(paths["events"])
    oracle_events = (
        load_events_with_annotations(paths["events"], paths["event_annotations"])
        if args.data_version in {"v1", "v1_1"}
        else events
    )
    cases = load_cases(paths["cases"])
    validate_benchmark(events, cases)
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    if args.dry_run:
        scopes = {event.scope_id for event in events}
        print(
            f"valid benchmark: data_version={args.data_version} track={args.track} "
            f"events={len(events)} cases={len(cases)} scopes={len(scopes)}"
        )
        print(f"events_path={paths['events']}")
        print(f"cases_path={paths['cases']}")
        return 0

    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    client = LLMClient(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=paths["cache"],
        use_cache=not args.no_cache,
    )

    judge_client: Optional[LLMClient] = None
    judge_model: Optional[str] = None
    if args.judge:
        try:
            judge_api_key, judge_model, judge_api_base = provider_config(args.judge_provider)
        except RuntimeError as exc:
            print(f"Judge config error: {exc}", file=sys.stderr)
            return 2
        judge_cache = paths["cache"].with_name(f"{paths['cache'].stem}.{args.judge_provider}_judge.json")
        judge_client = LLMClient(
            provider=args.judge_provider,
            model=judge_model,
            api_key=judge_api_key,
            api_base=judge_api_base,
            cache_path=judge_cache,
            use_cache=not args.no_cache,
        )

    print(f"target_provider={args.provider} target_model={model}", flush=True)
    if judge_client is not None:
        print(f"judge_provider={args.judge_provider} judge_model={judge_model}", flush=True)
    try:
        results = [
            run_variant(
                client,
                judge_client,
                variant_name,
                oracle_events if canonical_variant_name(variant_name) == "temporal_kg_oracle_schema" else events,
                cases,
                tsm_construction_mode=args.tsm_construction_mode,
                ours_pipeline=args.ours_pipeline,
                ours_readout_policy=args.ours_readout_policy,
            )
            for variant_name in args.variants
        ]
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        if args.judge and exc.provider == args.judge_provider:
            print(
                "This happened during LLM-as-a-judge scoring. "
                "Fix the judge provider API settings, or rerun without --judge for generation-only metrics.",
                file=sys.stderr,
            )
        return 1
    for result in results:
        result["data_version"] = args.data_version
        result["track"] = args.track
        result["events_path"] = str(paths["events"])
        result["cases_path"] = str(paths["cases"])
    print_summary(args.provider, model, results, args.judge_provider if args.judge else None, judge_model)

    output_path = paths["output"]
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nWrote {output_path}")
    return 0

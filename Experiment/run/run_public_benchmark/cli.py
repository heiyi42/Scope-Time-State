from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, Optional

from Experiment.run.common.io import load_cases, load_dotenv, load_events, validate_benchmark
from Experiment.run.common.paths import BENCHMARK_DIR
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config
from Experiment.run.common.subsets import load_subset_ids, select_cases_by_id
from pipeline.public import print_public_summary, run_public_variant
from Experiment.run.run_public_benchmark.routing import load_public_cases, load_scope_profiles, validate_public_cases
from Experiment.run.run_public_benchmark.types import (
    PUBLIC_VARIANT_ALIASES,
    SUPPORTED_VARIANTS,
    canonical_public_variant_name,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STAMB-State public End-to-End benchmark.")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--data-version", choices=("v1", "v1_1", "v1_2", "v1_3"), default="v1")
    parser.add_argument("--variants", nargs="+", default=list(SUPPORTED_VARIANTS))
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--case-subset", default="", help="Named case-id subset from data/<version>/subsets.json.")
    parser.add_argument("--case-subset-file", default=None, help="JSON list, or JSON object used with --case-subset.")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--judge", action="store_true", help="Use an LLM judge for free-facet alignment.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--dry-run", action="store_true", help="Validate files without calling an LLM.")
    parser.add_argument("--events", default=None)
    parser.add_argument("--public-cases", default=None)
    parser.add_argument("--scope-profiles", default=None)
    parser.add_argument(
        "--scope-top-k",
        type=int,
        default=0,
        help="Number of scope profiles to pass to the LLM router; 0 means all profiles.",
    )
    parser.add_argument(
        "--tsm-construction-mode",
        choices=("llm", "heuristic"),
        default="llm",
        help="TSM memory construction mode. Use heuristic only for offline/debug smoke tests.",
    )
    parser.add_argument("--gold-cases", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--cache", default=None)
    return parser.parse_args()


def resolve_data_paths(args: argparse.Namespace) -> Dict[str, Path]:
    data_dir = BENCHMARK_DIR / "data" / args.data_version
    return {
        "events": Path(args.events) if args.events else data_dir / "events_raw.json",
        "public_cases": Path(args.public_cases) if args.public_cases else data_dir / "public/cases.json",
        "scope_profiles": Path(args.scope_profiles) if args.scope_profiles else data_dir / "public/scope_profiles.json",
        "gold_cases": Path(args.gold_cases) if args.gold_cases else data_dir / "cases.json",
        "output": Path(args.output) if args.output else BENCHMARK_DIR / f"output/results_{args.data_version}_end_to_end.json",
        "cache": Path(args.cache) if args.cache else BENCHMARK_DIR / f"output/llm_cache.{args.data_version}_end_to_end.json",
    }


def main() -> int:
    args = parse_args()
    load_dotenv()
    paths = resolve_data_paths(args)
    events_path = paths["events"]
    public_cases_path = paths["public_cases"]
    scope_profiles_path = paths["scope_profiles"]
    gold_cases_path = paths["gold_cases"]
    output_path = paths["output"]
    cache_path = paths["cache"]

    events = load_events(events_path)
    scope_profiles = load_scope_profiles(scope_profiles_path, events)
    hidden_cases = load_cases(gold_cases_path)
    validate_benchmark(events, hidden_cases)
    public_cases = load_public_cases(public_cases_path)
    validate_public_cases(public_cases, hidden_cases)
    subset_ids = load_subset_ids(
        data_dir=BENCHMARK_DIR / "data" / args.data_version,
        subset_name=args.case_subset,
        subset_path=Path(args.case_subset_file) if args.case_subset_file else None,
    )
    if subset_ids:
        public_cases = select_cases_by_id(public_cases, subset_ids)
    if args.limit_cases:
        public_cases = public_cases[: args.limit_cases]

    hidden_cases_by_id = {case.case_id: case for case in hidden_cases}
    for variant_name in args.variants:
        canonical_name = canonical_public_variant_name(variant_name)
        if canonical_name not in SUPPORTED_VARIANTS:
            known = ", ".join(tuple(SUPPORTED_VARIANTS) + tuple(PUBLIC_VARIANT_ALIASES))
            print(f"unsupported public variant: {variant_name}; supported variants: {known}", file=sys.stderr)
            return 2

    if args.dry_run:
        print(
            f"valid public benchmark: events={len(events)} public_cases={len(public_cases)} "
            f"hidden_cases={len(hidden_cases)} variants={','.join(args.variants)}"
        )
        if subset_ids:
            print(f"case_subset={args.case_subset or args.case_subset_file} selected_cases={len(subset_ids)}")
        print(f"events_path={events_path}")
        print(f"public_cases_path={public_cases_path}")
        print(f"scope_profiles_path={scope_profiles_path} profiles={len(scope_profiles)}")
        print(f"gold_cases_path={gold_cases_path}")
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
        cache_path=cache_path,
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
        judge_cache = cache_path.with_name(f"{cache_path.stem}.{args.judge_provider}_judge.json")
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
            run_public_variant(
                client,
                judge_client,
                variant_name,
                events,
                scope_profiles,
                public_cases,
                hidden_cases_by_id,
                args.scope_top_k,
                args.tsm_construction_mode,
            )
            for variant_name in args.variants
        ]
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for result in results:
        result["data_version"] = args.data_version
        result["track"] = "end_to_end"
        result["events_path"] = str(events_path)
        result["public_cases_path"] = str(public_cases_path)
        result["gold_cases_path"] = str(gold_cases_path)
        if canonical_public_variant_name(str(result.get("variant", ""))) in {"tsm_global_public", "tsm_scope_routed_public"}:
            result["tsm_construction_mode"] = args.tsm_construction_mode

    print_public_summary(args.provider, model, results, args.judge_provider if args.judge else None, judge_model)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(f"\nWrote {output_path}")
    return 0

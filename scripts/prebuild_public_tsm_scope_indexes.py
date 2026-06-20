from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Dict, List, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.Main_Baseline.tsm.tsm_memory import build_tsm_index  # noqa: E402
from Experiment.run.common.io import load_dotenv, load_events  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from Experiment.run.common.paths import BENCHMARK_DIR  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prebuild public scope-routed TSM LLM construction cache without running "
            "public cases, answer generation, or judge scoring."
        )
    )
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--data-version", choices=("v1", "v1_1", "v1_2", "v1_3"), default="v1_1")
    parser.add_argument("--events", default=None)
    parser.add_argument("--cache", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=None,
        help="Optional explicit scope_id list. Default: every scope present in events.",
    )
    parser.add_argument(
        "--limit-scopes",
        type=int,
        default=0,
        help="Prebuild only the first N scopes after sorting. Useful for smoke tests.",
    )
    parser.add_argument(
        "--include-global",
        action="store_true",
        help="Also build the all-event global TSM index in the same cache.",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate scope selection without calling the LLM.",
    )
    args = parser.parse_args()
    if args.limit_scopes < 0:
        parser.error("--limit-scopes must be >= 0")
    return args


def resolve_paths(args: argparse.Namespace) -> Dict[str, Path]:
    data_dir = BENCHMARK_DIR / "data" / args.data_version
    return {
        "events": Path(args.events) if args.events else data_dir / "events_raw.json",
        "cache": (
            Path(args.cache)
            if args.cache
            else BENCHMARK_DIR / f"output/llm_cache.{args.data_version}_public_tsm_llm_scope_prebuild.json"
        ),
        "output": (
            Path(args.output)
            if args.output
            else BENCHMARK_DIR / f"output/tsm_scope_prebuild_{args.data_version}.json"
        ),
    }


def group_events_by_scope(events: Sequence[object]) -> Dict[str, List[object]]:
    grouped: Dict[str, List[object]] = defaultdict(list)
    for event in events:
        grouped[str(getattr(event, "scope_id"))].append(event)
    return dict(sorted(grouped.items()))


def selected_scope_ids(args: argparse.Namespace, grouped: Dict[str, List[object]]) -> List[str]:
    available = set(grouped)
    if args.scopes:
        missing = [scope_id for scope_id in args.scopes if scope_id not in available]
        if missing:
            raise ValueError(f"unknown scope_id(s): {', '.join(missing)}")
        scope_ids = list(dict.fromkeys(args.scopes))
    else:
        scope_ids = sorted(grouped)
    if args.limit_scopes:
        scope_ids = scope_ids[: args.limit_scopes]
    return scope_ids


def main() -> int:
    args = parse_args()
    load_dotenv()
    paths = resolve_paths(args)
    events = load_events(paths["events"])
    grouped = group_events_by_scope(events)
    try:
        scope_ids = selected_scope_ids(args, grouped)
    except ValueError as exc:
        print(f"Scope selection error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(
            f"valid TSM scope prebuild: data_version={args.data_version} "
            f"events={len(events)} scopes={len(scope_ids)} include_global={args.include_global}"
        )
        print(f"events_path={paths['events']}")
        print(f"cache_path={paths['cache']}")
        print(f"output_path={paths['output']}")
        for scope_id in scope_ids:
            print(f"- {scope_id}: events={len(grouped[scope_id])}")
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
    initial_cache_entries = len(client.cache)
    summaries: List[Dict[str, object]] = []

    try:
        if args.include_global:
            before = len(client.cache)
            print(f"prebuilding TSM index scope=__global__ events={len(events)}", flush=True)
            index = build_tsm_index(events, construction_llm=client.complete_json, construction_mode="llm")
            summaries.append(
                {
                    "scope_id": "__global__",
                    "event_count": len(index.events),
                    "entity_count": len(index.entity_nodes),
                    "temporal_fact_count": len(index.temporal_facts),
                    "durative_memory_count": len(index.durative_memories),
                    "construction_mode": index.construction_mode,
                    "cache_entries_before": before,
                    "cache_entries_after": len(client.cache),
                    "cache_entries_added": len(client.cache) - before,
                }
            )

        for scope_id in scope_ids:
            scoped_events = grouped[scope_id]
            before = len(client.cache)
            print(f"prebuilding TSM index scope={scope_id} events={len(scoped_events)}", flush=True)
            index = build_tsm_index(scoped_events, construction_llm=client.complete_json, construction_mode="llm")
            summaries.append(
                {
                    "scope_id": scope_id,
                    "event_count": len(index.events),
                    "entity_count": len(index.entity_nodes),
                    "temporal_fact_count": len(index.temporal_facts),
                    "durative_memory_count": len(index.durative_memories),
                    "construction_mode": index.construction_mode,
                    "cache_entries_before": before,
                    "cache_entries_after": len(client.cache),
                    "cache_entries_added": len(client.cache) - before,
                }
            )
    except LLMRequestError as exc:
        print("LLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = {
        "data_version": args.data_version,
        "provider": args.provider,
        "model": model,
        "events_path": str(paths["events"]),
        "cache_path": str(paths["cache"]),
        "initial_cache_entries": initial_cache_entries,
        "final_cache_entries": len(client.cache),
        "cache_entries_added": len(client.cache) - initial_cache_entries,
        "scope_count": len(scope_ids),
        "include_global": args.include_global,
        "scopes": summaries,
    }
    paths["output"].parent.mkdir(parents=True, exist_ok=True)
    paths["output"].write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        f"prebuilt {len(summaries)} TSM index(es); "
        f"cache_entries_added={result['cache_entries_added']} final_cache_entries={result['final_cache_entries']}",
        flush=True,
    )
    print(f"Wrote {paths['output']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

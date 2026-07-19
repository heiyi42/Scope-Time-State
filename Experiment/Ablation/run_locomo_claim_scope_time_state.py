from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Optional, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = PROJECT_DIR / "Experiment" / "Other_BenchMark" / "LoCoMo-QA"
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state import graph_query_runner  # noqa: E402


POLICIES = graph_query_runner.CLAIM_RETRIEVAL_POLICIES
VARIANT = "graph_embedding_scope_claim"
DEFAULT_SAMPLE_IDS = (
    "conv-26",
    "conv-30",
    "conv-41",
    "conv-42",
    "conv-43",
    "conv-44",
    "conv-47",
    "conv-48",
    "conv-49",
    "conv-50",
)
DEFAULT_RESULT_DIR = (
    PROJECT_DIR / "Graph" / "results" / "locomo_qa" / "claim_scope_time_state_ablation"
)
CURRENT_GRAPH_ROOT = (
    PROJECT_DIR / "Graph" / "graph" / "locomo_qa_sample_graph_v2_state_merge"
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the additive LoCoMo claim -> scope-claim -> scope-claim-time -> "
            "scope-claim-time-state ablation without replacing Event policies."
        )
    )
    parser.add_argument("policy", choices=(*POLICIES, "all"))
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument("--all-samples", action="store_true")
    parser.add_argument("--data", type=Path, default=graph_query_runner.DATA_PATH)
    parser.add_argument("--graph-dir", type=Path)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument(
        "--embedding-base-url",
        default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", ""),
    )
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument("--answer-workers", type=int, default=1)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--no-cache", action="store_true")
    return parser


def graph_dir(args: argparse.Namespace) -> Path:
    if args.graph_dir is not None:
        return args.graph_dir
    path = CURRENT_GRAPH_ROOT / args.sample_id
    if path.exists():
        return path
    return graph_query_runner.default_query_graph_dir(args.sample_id)


def result_path(args: argparse.Namespace, policy: str) -> Path:
    return args.result_dir / policy / args.sample_id / f"{policy}.json"


def cache_path(args: argparse.Namespace, policy: str) -> Path:
    return args.result_dir / "cache" / policy / args.sample_id / f"{policy}.json"


def embedding_cache_path(args: argparse.Namespace) -> Path:
    return (
        args.result_dir
        / "cache"
        / args.sample_id
        / f"embeddings.{args.embedding_model}.json"
    )


def query_args(args: argparse.Namespace, policy: str) -> list[str]:
    values = [
        "--data", str(args.data),
        "--sample-id", args.sample_id,
        "--graph-dir", str(graph_dir(args)),
        "--provider", args.provider,
        "--model", args.model,
        "--variants", VARIANT,
        "--retrieval-policy", policy,
        "--top-k", "16",
        "--max-claim-lines", "24",
        "--scope-top-k", "14",
        "--scope-backoff-k", "8",
        "--scope-types", "speaker,entity,topic",
        "--scope-anchor-routing", "reserve",
        "--candidate-k", "80",
        "--embedding-candidate-k", "80",
        "--max-context-events", "24",
        "--max-state-lines", "0",
        "--evidence-selector", "direct",
        "--binding-gate", "off",
        "--time-role-selector", "llm-top2",
        "--event-time-routing", "prefilter",
        "--graph-expansion", "relation-aware",
        "--evidence-citation-source", "answer",
        "--embedding-model", args.embedding_model,
        "--embedding-batch-size", str(args.embedding_batch_size),
        "--answer-workers", str(args.answer_workers),
        "--limit-cases", str(args.limit_cases),
        "--output", str(result_path(args, policy)),
        "--cache", str(cache_path(args, policy)),
        "--embedding-cache", str(embedding_cache_path(args)),
    ]
    if args.embedding_base_url:
        values.extend(("--embedding-base-url", args.embedding_base_url))
    if args.question_types:
        values.extend(("--question-types", *args.question_types))
    if args.no_cache:
        values.append("--no-cache")
    return values


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = make_parser().parse_args(argv)
    policies = POLICIES if args.policy == "all" else (args.policy,)
    sample_ids = DEFAULT_SAMPLE_IDS if args.all_samples else (args.sample_id,)
    if args.all_samples and args.graph_dir is not None:
        raise ValueError("--graph-dir identifies one sample; omit it with --all-samples")
    for sample_id in sample_ids:
        sample_args = argparse.Namespace(**{**vars(args), "sample_id": sample_id})
        for policy in policies:
            status = graph_query_runner.main(query_args(sample_args, policy))
            if status != 0:
                return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

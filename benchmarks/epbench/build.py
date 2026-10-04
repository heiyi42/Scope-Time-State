#!/usr/bin/env python3
"""Build the strict EPBench Scope -> Claim -> State/TimeGroup graph."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sts.adapters.epbench.build_pipeline import EPBenchGraphBuilder
from sts.config import ExperimentConfig
from sts.providers.embeddings import OpenAIEmbeddingProvider
from sts.providers.openai import OpenAIProvider


DEFAULT_DATA = (
    PROJECT_ROOT / "data" / "epbench"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "epbench" / "book1"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--data-folder", type=Path, default=DEFAULT_DATA)
    value.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    value.add_argument("--book-id", default="book1")
    value.add_argument("--limit", type=int, help="Smoke-test chapter limit")
    value.add_argument("--concurrency", type=int, default=8)
    value.add_argument(
        "--scope-candidate-top-k",
        type=int,
        default=ExperimentConfig.scope_candidate_top_k,
    )
    value.add_argument(
        "--scope-event-shuffle-seed",
        type=int,
        default=int(os.environ.get("STS_SCOPE_EVENT_SHUFFLE_SEED", "42")),
    )
    value.add_argument(
        "--disable-scope-event-shuffle",
        action="store_true",
        help="Process Events in source chapter order instead of seeded shuffled order",
    )
    value.add_argument(
        "--event-scope-weight-threshold",
        type=float,
        default=float(
            os.environ.get("STS_EVENT_SCOPE_WEIGHT_THRESHOLD", "0.6")
        ),
    )
    value.add_argument(
        "--disable-low-weight-repool",
        action="store_true",
        help="Disable low-weight Event-to-Scope detachment and repooling",
    )
    value.add_argument(
        "--model",
        default=os.environ.get("STS_MODEL", "gpt-4.1-mini"),
    )
    value.add_argument(
        "--base-url",
        default=os.environ.get(
            "OPENAI_BASE_URL",
            os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        ),
    )
    value.add_argument(
        "--embedding-base-url",
        default=ExperimentConfig.embedding_base_url,
    )
    value.add_argument(
        "--embedding-model",
        default=ExperimentConfig.embedding_model,
    )
    return value


async def run(args: argparse.Namespace) -> Path:
    provider = OpenAIProvider(
        model=args.model,
        api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY"),
        base_url=args.base_url.rstrip("/"),
        temperature=0,
    )
    embedding_provider = OpenAIEmbeddingProvider(
        base_url=args.embedding_base_url,
        model_name=args.embedding_model,
        api_key=(
            os.environ.get("OPENAI_EMBEDDING_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ),
    )
    return await EPBenchGraphBuilder(
        provider,
        embedding_provider,
        concurrency=args.concurrency,
        scope_candidate_top_k=args.scope_candidate_top_k,
        enable_low_weight_repool=not args.disable_low_weight_repool,
        event_scope_weight_threshold=args.event_scope_weight_threshold,
        shuffle_scope_events=not args.disable_scope_event_shuffle,
        scope_event_shuffle_seed=args.scope_event_shuffle_seed,
    ).build(
        args.data_folder,
        args.output_dir,
        book_id=args.book_id,
        limit=args.limit,
    )


def main() -> None:
    args = parser().parse_args()
    print(
        "[STS-EPBench] CLI: "
        f"model={args.model}, concurrency={args.concurrency}, "
        f"low_weight_repool={not args.disable_low_weight_repool}, "
        f"threshold={args.event_scope_weight_threshold}, "
        f"scope_event_shuffle={not args.disable_scope_event_shuffle}, "
        f"shuffle_seed={args.scope_event_shuffle_seed}, "
        f"scope_candidate_top_k={args.scope_candidate_top_k}, "
        f"embedding_model={args.embedding_model}",
        flush=True,
    )
    path = asyncio.run(run(args))
    print(f"[STS-EPBench] done: {path}", flush=True)


if __name__ == "__main__":
    main()

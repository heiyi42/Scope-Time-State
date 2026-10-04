#!/usr/bin/env python3
"""Answer EPBench questions from a strict STS EPBench graph."""

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

from sts.adapters.epbench.qa_pipeline import EPBenchQARunner
from sts.config import ExperimentConfig
from sts.providers.embeddings import OpenAIEmbeddingProvider
from sts.providers.openai import OpenAIProvider


DEFAULT_DATA = (
    PROJECT_ROOT / "data" / "epbench"
)
DEFAULT_GRAPH = PROJECT_ROOT / "results" / "epbench" / "book1" / "graph.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "epbench" / "book1" / "qa.json"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--data-folder", type=Path, default=DEFAULT_DATA)
    value.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    value.add_argument("--offset", type=int, default=0)
    value.add_argument("--limit", type=int, help="Smoke-test question limit")
    value.add_argument("--concurrency", type=int, default=8)
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
    return await EPBenchQARunner(
        provider,
        embedding_provider,
        concurrency=args.concurrency,
    ).run(
        args.graph,
        args.data_folder,
        args.output,
        offset=args.offset,
        limit=args.limit,
    )


def main() -> None:
    args = parser().parse_args()
    path = asyncio.run(run(args))
    print(path)


if __name__ == "__main__":
    main()

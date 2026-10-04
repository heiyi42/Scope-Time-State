#!/usr/bin/env python3
"""Judge completed STS EPBench answers with the EPBench item metric."""

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

from sts.adapters.epbench.judge_pipeline import EPBenchJudgeRunner
from sts.providers.openai import OpenAIProvider


DEFAULT_DATA = (
    PROJECT_ROOT / "data" / "epbench"
)
DEFAULT_QA = PROJECT_ROOT / "results" / "epbench" / "book1" / "qa.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "results" / "epbench" / "book1" / "judge.json"
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--data-folder", type=Path, default=DEFAULT_DATA)
    value.add_argument("--qa", type=Path, default=DEFAULT_QA)
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    value.add_argument("--limit", type=int, help="Smoke-test answer limit")
    value.add_argument("--concurrency", type=int, default=8)
    value.add_argument(
        "--model",
        default=os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o-mini"),
    )
    value.add_argument(
        "--base-url",
        default=os.environ.get(
            "OPENAI_BASE_URL",
            os.environ.get(
                "OPENROUTER_BASE_URL",
                "https://openrouter.ai/api/v1",
            ),
        ),
    )
    return value


async def run(args: argparse.Namespace) -> Path:
    provider = OpenAIProvider(
        model=args.model,
        api_key=(
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
        ),
        base_url=args.base_url.rstrip("/"),
        temperature=0,
    )
    return await EPBenchJudgeRunner(
        provider,
        concurrency=args.concurrency,
    ).run(
        args.qa,
        args.data_folder,
        args.output,
        limit=args.limit,
    )


def main() -> None:
    args = parser().parse_args()
    print(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

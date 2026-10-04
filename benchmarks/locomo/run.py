"""Run STS on LoCoMo."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

try:
    from .adapter import (
        COMMAND_TASKS,
        DEFAULT_DATASET,
        DEFAULT_RESULTS,
        run_sts,
    )
except ImportError:
    from adapter import COMMAND_TASKS, DEFAULT_DATASET, DEFAULT_RESULTS, run_sts


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=tuple(COMMAND_TASKS))
    value.add_argument("--sample-id", default="all", help="LoCoMo sample_id, or 'all'.")
    value.add_argument("--data", type=Path, default=DEFAULT_DATASET)
    value.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS)
    value.add_argument("--project-root", type=Path)
    value.add_argument("--artifact-dir", type=Path)
    value.add_argument("--result-dir", type=Path)
    value.add_argument(
        "--retrieval-type",
        choices=("vector", "rrf"),
        default="rrf",
    )
    value.add_argument("--state-top-k", type=positive_int)
    value.add_argument("--concurrency", type=positive_int, default=4)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return run_sts(
        args.command,
        data=args.data,
        sample_id=args.sample_id,
        results_root=args.results_root,
        project_root=args.project_root,
        retrieval_type=args.retrieval_type,
        state_top_k=args.state_top_k,
        concurrency=args.concurrency,
        artifact_dir=args.artifact_dir,
        result_dir=args.result_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())

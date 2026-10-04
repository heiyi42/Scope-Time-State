"""Command-line entry point for the STS pipeline."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


TASK_MODULES = {
    "extract": "sts.extraction.pipeline",
    "construct": "sts.graph.construction",
    "index": "sts.retrieval.index",
    "retrieve": "sts.retrieval.search",
    "answer": "sts.generation.answer",
    "evaluate": "sts.evaluation.locomo_judge",
}
DEFAULT_WORKFLOW = (
    "extract",
    "construct",
    "index",
    "retrieve",
    "answer",
)


def run_task(task: str) -> int:
    """Run one pipeline task in an isolated Python process."""
    module = TASK_MODULES[task]
    print(f"\n[STS] task={task} module={module}", flush=True)
    completed = subprocess.run(
        [sys.executable, "-m", module],
        cwd=Path.cwd(),
        env=os.environ.copy(),
        check=False,
    )
    return int(completed.returncode)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the STS memory pipeline.")
    value.add_argument(
        "tasks",
        nargs="*",
        choices=tuple(TASK_MODULES),
        help=(
            "Tasks to run in order. If omitted, runs extract, construct, "
            "index, retrieve, and answer."
        ),
    )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    tasks = tuple(args.tasks) or DEFAULT_WORKFLOW
    for task in tasks:
        returncode = run_task(task)
        if returncode:
            print(f"[STS] task={task} failed with exit code {returncode}", flush=True)
            return returncode
    print("[STS] workflow completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

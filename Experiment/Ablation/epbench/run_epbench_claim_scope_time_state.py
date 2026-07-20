"""Run the four-policy Claim--Scope--Time--State ablation on an existing EPBench graph."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[3]
STS_PARENT = (
    PROJECT_ROOT
    / "Experiment"
    / "Other_BenchMark"
    / "Episodic-Memory"
    / "Baseline"
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(STS_PARENT) not in sys.path:
    sys.path.insert(0, str(STS_PARENT))

from STS.config import GRAPH_DIR  # noqa: E402
from STS.run import main as sts_main  # noqa: E402
from STS.staged import CLAIM_RETRIEVAL_POLICIES  # noqa: E402


ABLATION_ROOT = Path(__file__).resolve().parent
DEFAULT_GRAPH_DIR = GRAPH_DIR / "book1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", choices=(*CLAIM_RETRIEVAL_POLICIES, "all"))
    parser.add_argument("--stage", choices=("retrieve", "qa", "official"), default="qa")
    parser.add_argument("--graph-dir", type=Path, default=DEFAULT_GRAPH_DIR)
    parser.add_argument("--result-root", type=Path, default=ABLATION_ROOT / "results")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--answer-model", default="gpt-4o-mini")
    parser.add_argument("--judge-model", default="gpt-4o-mini")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--embedding-batch-size", type=int, default=24)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--question-offset", type=int, default=0)
    parser.add_argument("--question-limit", type=int, default=686)
    parser.add_argument("--question-get", action="append", choices=("all", "latest", "chronological"), default=[])
    parser.add_argument("--refresh-existing", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    return parser


def _sts_args(args: argparse.Namespace, policy: str) -> list[str]:
    result_dir = args.result_root.resolve() / policy
    values = [
        "--stage", args.stage,
        "--graph-dir", str(args.graph_dir.resolve()),
        "--result-dir", str(result_dir),
        "--retrieval-policy", policy,
        "--model", args.model,
        "--answer-model", args.answer_model,
        "--judge-model", args.judge_model,
        "--embedding-model", args.embedding_model,
        "--embedding-batch-size", str(args.embedding_batch_size),
        "--workers", str(args.workers),
        "--question-offset", str(args.question_offset),
        "--question-limit", str(args.question_limit),
        "--scope-top-k", "14",
        "--scope-backoff-k", "8",
        "--claim-candidate-k", "80",
        "--claim-seed-k", "16",
        "--final-claim-k", "24",
        "--final-chapter-k", "24",
        "--time-role-selector", "llm-top2",
    ]
    for question_get in args.question_get:
        values.extend(("--question-get", question_get))
    if args.refresh_existing:
        values.append("--refresh-existing")
    if args.no_resume:
        values.append("--no-resume")
    if args.no_cache:
        values.append("--no-cache")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policies = CLAIM_RETRIEVAL_POLICIES if args.policy == "all" else (args.policy,)
    if args.stage == "official":
        missing = [
            policy
            for policy in policies
            if not (args.result_root / policy / "qa.json").is_file()
        ]
        if missing:
            raise FileNotFoundError(
                "official ARTEM scoring needs completed QA output first: " + ", ".join(missing)
            )
    for policy in policies:
        status = sts_main(_sts_args(args, policy))
        if status:
            return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

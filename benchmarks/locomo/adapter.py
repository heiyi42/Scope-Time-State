"""LoCoMo dataset adapter for the STS pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "data" / "locomo" / "locomo10.json"
DEFAULT_RESULTS = PROJECT_ROOT / "results" / "locomo"

COMMAND_TASKS = {
    "build": ("extract", "construct", "index"),
    "query": ("retrieve", "answer"),
    "evaluate": ("evaluate",),
    "run": ("extract", "construct", "index", "retrieve", "answer"),
}


def load_env_file(path: Path) -> None:
    """Load repository environment values without overriding the shell."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(), value.strip().strip('"').strip("'")
        )


def safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", value.strip())
    return cleaned.strip("._") or "all"


def resolve_project_root(explicit: Path | None = None) -> Path:
    root = (explicit or PROJECT_ROOT).resolve()
    if not (root / "src" / "sts" / "cli.py").is_file():
        raise FileNotFoundError(f"STS source package not found below {root}")
    return root


def select_dataset(source: Path, sample_id: str, results_root: Path) -> Path:
    source = source.resolve()
    if sample_id == "all":
        return source
    rows = json.loads(source.read_text(encoding="utf-8"))
    selected = [row for row in rows if str(row.get("sample_id")) == sample_id]
    if len(selected) != 1:
        raise ValueError(
            f"expected exactly one sample_id={sample_id!r}, found {len(selected)}"
        )
    snapshot_dir = results_root / "input"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"{safe_part(sample_id)}.json"
    snapshot.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return snapshot


def resolve_artifact_dir(
    results_root: Path,
    experiment: str,
    explicit: Path | None = None,
) -> Path:
    required = ("graphs", "bm25_index", "vectors")
    candidates = (
        [explicit.resolve()]
        if explicit is not None
        else sorted(
            path
            for path in results_root.glob(f"{experiment}_*")
            if path.is_dir()
            and all((path / name).is_dir() for name in required)
        )
    )
    if len(candidates) != 1:
        rendered = ", ".join(str(path) for path in candidates) or "none"
        raise FileNotFoundError(
            "query requires exactly one completed construction artifact; "
            f"found {len(candidates)}: {rendered}. Pass --artifact-dir explicitly."
        )
    return candidates[0]


def resolve_response_dir(
    results_root: Path,
    experiment: str,
    explicit: Path | None = None,
) -> Path:
    candidates = (
        [explicit.resolve()]
        if explicit is not None
        else sorted(
            path
            for path in results_root.glob(f"{experiment}_*")
            if path.is_dir() and (path / "responses.json").is_file()
        )
    )
    if len(candidates) != 1:
        rendered = ", ".join(str(path) for path in candidates) or "none"
        raise FileNotFoundError(
            "evaluation requires exactly one result directory containing "
            f"responses.json; found {len(candidates)}: {rendered}. "
            "Pass --result-dir explicitly."
        )
    return candidates[0]


def run_sts(
    command: str,
    *,
    data: Path = DEFAULT_DATASET,
    sample_id: str = "all",
    results_root: Path = DEFAULT_RESULTS,
    project_root: Path | None = None,
    extra_tasks: Iterable[str] | None = None,
    retrieval_type: str = "rrf",
    state_top_k: int | None = None,
    concurrency: int = 4,
    artifact_dir: Path | None = None,
    result_dir: Path | None = None,
) -> int:
    load_env_file(PROJECT_ROOT / ".env")
    root = resolve_project_root(project_root)
    results_root = results_root.resolve()
    dataset = select_dataset(data, sample_id, results_root)
    tasks = tuple(extra_tasks or COMMAND_TASKS[command])
    experiment = f"STS-V2-{safe_part(sample_id)}"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(root / "src"),
            "STS_DATASET_PATH": str(dataset),
            "STS_RESULTS_DIR": str(results_root),
            "STS_EXPERIMENT_NAME": experiment,
            "STS_RETRIEVAL_TYPE": retrieval_type,
            "STS_MAX_CONCURRENT_REQUESTS": str(concurrency),
        }
    )
    if state_top_k is not None:
        env["STS_STATE_TOP_K"] = str(state_top_k)
    if command == "query":
        env["STS_ARTIFACT_DIR"] = str(
            resolve_artifact_dir(results_root, experiment, artifact_dir)
        )
    if command == "evaluate":
        env["STS_RESULT_DIR"] = str(
            resolve_response_dir(results_root, experiment, result_dir)
        )
    completed = subprocess.run(
        [sys.executable, "-m", "sts.cli", *tasks],
        cwd=root,
        env=env,
        check=False,
    )
    return int(completed.returncode)

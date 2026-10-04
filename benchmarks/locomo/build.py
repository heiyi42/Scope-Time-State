"""Build LoCoMo STS artifacts with resumable task checkpoints."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

try:
    from .adapter import (
        DEFAULT_DATASET,
        DEFAULT_RESULTS,
        resolve_project_root,
        safe_part,
        select_dataset,
    )
except ImportError:
    from adapter import (
        DEFAULT_DATASET,
        DEFAULT_RESULTS,
        resolve_project_root,
        safe_part,
        select_dataset,
    )


BUILD_TASKS = {
    "extract": ("sts.extraction.pipeline", "events"),
    "construct": ("sts.graph.construction", "graphs"),
    "index": ("sts.retrieval.index", "vectors"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "src" / "sts").rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def completed_checkpoint(path: Path, fingerprint: str) -> bool:
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    return (
        payload.get("status") == "completed"
        and payload.get("fingerprint") == fingerprint
    )


def stream_task(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            return process.wait()
        except KeyboardInterrupt:
            print("\n[pause] stopping the active task", flush=True)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            return 130


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--sample-id", default="all", help="LoCoMo sample_id, or 'all'.")
    value.add_argument("--data", type=Path, default=DEFAULT_DATASET)
    value.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS)
    value.add_argument("--project-root", type=Path)
    value.add_argument("--force", action="store_true")
    value.add_argument("--dry-run", action="store_true")
    value.add_argument(
        "--stop-after",
        choices=tuple(BUILD_TASKS),
        help="Stop after the selected task completes.",
    )
    return value


def main() -> int:
    args = parser().parse_args()
    root = resolve_project_root(args.project_root)
    results_root = args.results_root.resolve()
    dataset = select_dataset(args.data, args.sample_id, results_root)
    sample_slug = safe_part(args.sample_id)
    experiment = f"STS-V2-{sample_slug}"
    checkpoint_dir = results_root / "checkpoints" / sample_slug
    log_dir = results_root / "logs" / sample_slug
    fingerprint = hashlib.sha256(
        (
            sha256_file(dataset)
            + source_fingerprint(root)
            + experiment
        ).encode()
    ).hexdigest()

    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(root / "src"),
            "STS_DATASET_PATH": str(dataset),
            "STS_RESULTS_DIR": str(results_root),
            "STS_EXPERIMENT_NAME": experiment,
        }
    )

    print(f"[build] sample={args.sample_id}")
    print(f"[build] dataset={dataset}")
    print(f"[build] project={root}")
    print(f"[build] results={results_root}")
    print(f"[build] fingerprint={fingerprint}")

    for task, (module, output_kind) in BUILD_TASKS.items():
        checkpoint = checkpoint_dir / f"{task}.json"
        log_path = log_dir / f"{task}.log"
        command = [sys.executable, "-m", module]
        if not args.force and completed_checkpoint(checkpoint, fingerprint):
            print(f"[checkpoint] task={task} status=completed action=skip")
            if args.stop_after == task:
                return 0
            continue
        if args.dry_run:
            print(f"[dry-run] task={task} module={module}")
            continue

        started_at = now()
        record = {
            "task": task,
            "module": module,
            "status": "running",
            "fingerprint": fingerprint,
            "sample_id": args.sample_id,
            "dataset": str(dataset),
            "project_root": str(root),
            "results_root": str(results_root),
            "command": command,
            "log": str(log_path),
            "started_at": started_at,
        }
        atomic_json(checkpoint, record)
        returncode = stream_task(command, cwd=root, env=env, log_path=log_path)
        status = (
            "completed"
            if returncode == 0
            else "paused"
            if returncode == 130
            else "failed"
        )
        atomic_json(
            checkpoint,
            {
                **record,
                "status": status,
                "expected_output_kind": output_kind,
                "finished_at": now(),
                "returncode": returncode,
            },
        )
        print(f"[checkpoint] task={task} status={status}")
        if returncode:
            return returncode
        if args.stop_after == task:
            return 0

    print("[build] construction artifacts completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

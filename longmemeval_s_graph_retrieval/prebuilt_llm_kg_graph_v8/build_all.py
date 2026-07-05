from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Deque, Iterable

from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.common import load_rows_utf8, resolve_data_path
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v8.status_utils import (
    atomic_write_json,
    parse_iso_timestamp,
    read_json,
    utc_now_iso,
)
from pipeline.external.longmemeval_s.adapters import TASK_TYPES
from pipeline.external.longmemeval_s.runner import select_rows


METHOD_NAME = "prebuilt_llm_kg_graph_v8"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


@dataclass
class RunningCase:
    question_id: str
    question_type: str
    process: subprocess.Popen[bytes]
    log_handle: object
    started_at: float
    log_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="v6 build-only graph prebuild scheduler.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--question-ids", nargs="+", default=[])
    parser.add_argument("--graph-batch-size", type=int, default=5)
    parser.add_argument("--max-facets", type=int, default=40)
    parser.add_argument("--construction-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--construction-model", default="deepseek-v4-flash")
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--graph-dir", default=None)
    parser.add_argument("--max-global-workers", type=int, default=1)
    parser.add_argument("--parallel-per-type", type=int, default=1)
    parser.add_argument("--heartbeat-seconds", type=int, default=120)
    parser.add_argument("--stuck-timeout-seconds", type=int, default=900)
    parser.add_argument("--request-timeout-seconds", type=int, default=300)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-claims-per-event", type=int, default=4)
    parser.add_argument("--max-entity-labels", type=int, default=6)
    parser.add_argument("--max-scope-labels", type=int, default=4)
    parser.add_argument("--partial-graph-every", type=int, default=1)
    parser.add_argument("--run-state-reconcile", action="store_true")
    parser.add_argument("--no-partial-graph", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_global_workers < 1:
        parser.error("--max-global-workers must be >= 1")
    if args.parallel_per_type < 1:
        parser.error("--parallel-per-type must be >= 1")
    if args.heartbeat_seconds < 1:
        parser.error("--heartbeat-seconds must be >= 1")
    if args.stuck_timeout_seconds < 1:
        parser.error("--stuck-timeout-seconds must be >= 1")
    return args


def select_target_rows(args: argparse.Namespace):
    data_path = resolve_data_path(args.data)
    rows = select_rows(load_rows_utf8(data_path), args.question_types, args.limit_cases, args.limit_per_type)
    if args.question_ids:
        allowed = set(args.question_ids)
        rows = [row for row in rows if row.question_id in allowed]
    unsupported = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported:
        raise ValueError(f"unsupported question types in selection: {unsupported}")
    return data_path, rows


def graph_path_for(args: argparse.Namespace, question_id: str, question_type: str = "") -> Path:
    artifact_dir = Path(args.artifact_dir)
    graph_dir = Path(args.graph_dir) if args.graph_dir else artifact_dir / "graphs"
    if question_type:
        graph_dir = graph_dir / question_type
    return graph_dir / f"{question_id}.graph.json"


def pending_rows(args: argparse.Namespace, rows: Iterable[object]) -> list[object]:
    pending = []
    for row in rows:
        if graph_path_for(args, row.question_id, row.question_type).exists() and not args.overwrite:
            continue
        pending.append(row)
    return pending


def command_for_case(args: argparse.Namespace, question_id: str) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v8.build_one_case",
        "--question-id",
        question_id,
        "--graph-batch-size",
        str(args.graph_batch_size),
        "--max-facets",
        str(args.max_facets),
        "--construction-provider",
        args.construction_provider,
        "--construction-model",
        args.construction_model,
        "--artifact-dir",
        str(Path(args.artifact_dir)),
        "--request-timeout-seconds",
        str(args.request_timeout_seconds),
        "--max-tokens",
        str(args.max_tokens),
        "--max-claims-per-event",
        str(args.max_claims_per_event),
        "--max-entity-labels",
        str(args.max_entity_labels),
        "--max-scope-labels",
        str(args.max_scope_labels),
        "--partial-graph-every",
        str(args.partial_graph_every),
    ]
    if args.data:
        cmd.extend(["--data", args.data])
    if args.graph_dir:
        cmd.extend(["--graph-dir", args.graph_dir])
    if args.run_state_reconcile:
        cmd.append("--run-state-reconcile")
    if args.no_partial_graph:
        cmd.append("--no-partial-graph")
    if args.no_cache:
        cmd.append("--no-cache")
    if args.no_resume:
        cmd.append("--no-resume")
    if args.overwrite:
        cmd.append("--overwrite")
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def launch_case(args: argparse.Namespace, row: object) -> RunningCase:
    artifact_dir = Path(args.artifact_dir)
    log_dir = artifact_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{row.question_id}.log"
    status_path = artifact_dir / "status" / f"{row.question_id}.status.json"
    atomic_write_json(
        status_path,
        {
            "method": METHOD_NAME,
            "question_id": row.question_id,
            "question_type": row.question_type,
            "status": "scheduled",
            "stage": "launching_worker",
            "pid": None,
            "error": None,
            "started_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        },
    )
    log_handle = log_path.open("ab")
    process = subprocess.Popen(
        command_for_case(args, row.question_id),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    try:
        payload = read_json(status_path)
        payload["status"] = "running"
        payload["stage"] = "worker_started"
        payload["pid"] = process.pid
        payload["updated_at"] = utc_now_iso()
        atomic_write_json(status_path, payload)
    except (OSError, json.JSONDecodeError):
        pass
    return RunningCase(
        question_id=row.question_id,
        question_type=row.question_type,
        process=process,
        log_handle=log_handle,
        started_at=time.time(),
        log_path=log_path,
    )


def read_statuses(artifact_dir: Path) -> dict[str, dict[str, object]]:
    status_dir = artifact_dir / "status"
    statuses: dict[str, dict[str, object]] = {}
    if not status_dir.exists():
        return statuses
    for path in status_dir.glob("*.status.json"):
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        question_id = str(payload.get("question_id") or path.stem.replace(".status", ""))
        statuses[question_id] = payload
    return statuses


def seconds_since(value: str) -> float | None:
    parsed = parse_iso_timestamp(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def heartbeat(
    args: argparse.Namespace,
    rows: list[object],
    running: dict[str, RunningCase],
    completed: set[str],
    failed: set[str],
    skipped: int,
    pending_count: int,
) -> None:
    statuses = read_statuses(Path(args.artifact_dir))
    print("", flush=True)
    print(f"[Heartbeat] {utc_now_iso()}", flush=True)
    print(f"method: {METHOD_NAME}", flush=True)
    print(f"total selected: {len(rows)}", flush=True)
    print(f"completed this run: {len(completed)}", flush=True)
    print(f"failed this run: {len(failed)}", flush=True)
    print(f"skipped existing: {skipped}", flush=True)
    print(f"running: {len(running)}", flush=True)
    print(f"pending not launched: {pending_count}", flush=True)
    for question_id, item in sorted(running.items()):
        status = statuses.get(question_id, {})
        last_update = seconds_since(str(status.get("updated_at") or ""))
        last_update_text = "unknown" if last_update is None else f"{int(last_update)}s"
        stage = status.get("stage") or "unknown"
        completed_batches = status.get("completed_batches")
        total_batches = status.get("total_batches")
        elapsed = int(time.time() - item.started_at)
        print(
            f"- {item.question_type} / {question_id} / stage={stage} / "
            f"batches={completed_batches}/{total_batches} / elapsed={elapsed}s / last_update={last_update_text}",
            flush=True,
        )
        if last_update is not None and last_update > args.stuck_timeout_seconds:
            print(f"  possible_stuck: last update {int(last_update)}s ago", flush=True)


def main() -> int:
    args = parse_args()
    try:
        data_path, rows = select_target_rows(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ("graphs", "partial_graphs", "batches", "state", "intermediate", "status", "logs", "cache", "errors"):
        (artifact_dir / subdir).mkdir(parents=True, exist_ok=True)

    selected = list(rows)
    work_rows = pending_rows(args, selected)
    skipped = len(selected) - len(work_rows)
    rows_by_type: dict[str, Deque[object]] = defaultdict(deque)
    for row in work_rows:
        rows_by_type[row.question_type].append(row)

    manifest = {
        "method": METHOD_NAME,
        "data_path": str(data_path),
        "started_at": utc_now_iso(),
        "n_selected": len(selected),
        "n_pending_at_start": len(work_rows),
        "skipped_existing": skipped,
        "question_types": dict(Counter(row.question_type for row in selected)),
        "construction_provider": args.construction_provider,
        "construction_model": args.construction_model,
        "graph_batch_size": args.graph_batch_size,
        "max_facets": args.max_facets,
        "max_claims_per_event": args.max_claims_per_event,
        "max_entity_labels": args.max_entity_labels,
        "max_scope_labels": args.max_scope_labels,
        "run_state_reconcile": args.run_state_reconcile,
        "max_global_workers": args.max_global_workers,
        "parallel_per_type": args.parallel_per_type,
        "heartbeat_seconds": args.heartbeat_seconds,
        "stuck_timeout_seconds": args.stuck_timeout_seconds,
        "question_independent_construction": True,
        "build_only": True,
        "auto_kill": False,
    }
    atomic_write_json(artifact_dir / "build_manifest.started.json", manifest)

    print(
        f"[build_all] selected={len(selected)} pending={len(work_rows)} skipped_existing={skipped} "
        f"types={dict(Counter(row.question_type for row in selected))}",
        flush=True,
    )
    if args.dry_run:
        print("[build_all] dry-run only; no API calls should be made by workers.", flush=True)

    running: dict[str, RunningCase] = {}
    running_by_type: Counter[str] = Counter()
    completed: set[str] = set()
    failed: set[str] = set()
    last_heartbeat = 0.0

    def pending_total() -> int:
        return sum(len(queue) for queue in rows_by_type.values())

    try:
        while pending_total() or running:
            for question_type in list(rows_by_type.keys()):
                while (
                    rows_by_type[question_type]
                    and len(running) < args.max_global_workers
                    and running_by_type[question_type] < args.parallel_per_type
                ):
                    row = rows_by_type[question_type].popleft()
                    item = launch_case(args, row)
                    running[item.question_id] = item
                    running_by_type[item.question_type] += 1
                    print(f"[build_all] launched {item.question_type} / {item.question_id}", flush=True)

            for question_id, item in list(running.items()):
                return_code = item.process.poll()
                if return_code is None:
                    continue
                item.log_handle.close()
                del running[question_id]
                running_by_type[item.question_type] -= 1
                if return_code == 0:
                    completed.add(question_id)
                    print(f"[build_all] completed {item.question_type} / {question_id}", flush=True)
                else:
                    failed.add(question_id)
                    print(
                        f"[build_all] failed {item.question_type} / {question_id} rc={return_code} "
                        f"log={item.log_path}",
                        flush=True,
                    )

            now = time.time()
            if now - last_heartbeat >= args.heartbeat_seconds:
                heartbeat(args, selected, running, completed, failed, skipped, pending_total())
                last_heartbeat = now
            time.sleep(2)
    finally:
        for item in running.values():
            try:
                item.log_handle.flush()
            except Exception:
                pass

    finished_manifest = dict(manifest)
    finished_manifest.update(
        {
            "finished_at": utc_now_iso(),
            "completed": sorted(completed),
            "failed": sorted(failed),
            "n_completed": len(completed),
            "n_failed": len(failed),
        }
    )
    atomic_write_json(artifact_dir / "build_manifest.finished.json", finished_manifest)
    print(f"[build_all] done completed={len(completed)} failed={len(failed)} skipped={skipped}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())


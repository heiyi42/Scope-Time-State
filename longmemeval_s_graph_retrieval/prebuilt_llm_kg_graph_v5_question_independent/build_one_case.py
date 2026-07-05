from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMRequestError, provider_config
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.common import (
    candidate_sessions_for_row,
    load_rows_utf8,
    resolve_data_path,
)
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.graph_store import write_graph_artifact
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.stable_client import (
    StableRequestsJsonClient,
)
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.status_utils import (
    StatusWriter,
    atomic_write_json,
    utc_now_iso,
)
from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import (
    TaskSemanticsLocalGraphBuilder,
)

from .llm_extractor import QuestionIndependentGraphExtractor


METHOD_NAME = "prebuilt_llm_kg_graph_v5_question_independent"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one question-independent v5 graph artifact.")
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--data", default=None)
    parser.add_argument("--graph-batch-size", type=int, default=5)
    parser.add_argument("--max-facets", type=int, default=40)
    parser.add_argument("--construction-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--construction-model", default="deepseek-v4-flash")
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--graph-dir", default=None)
    parser.add_argument("--request-timeout-seconds", type=int, default=300)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.graph_batch_size < 1:
        parser.error("--graph-batch-size must be >= 1")
    if args.max_facets < 1:
        parser.error("--max-facets must be >= 1")
    if args.request_timeout_seconds < 1:
        parser.error("--request-timeout-seconds must be >= 1")
    if args.max_tokens < 1:
        parser.error("--max-tokens must be >= 1")
    return args


def find_row(data_path: Path, question_id: str) -> Any:
    for row in load_rows_utf8(data_path):
        if row.question_id == question_id:
            return row
    raise ValueError(f"question_id not found: {question_id}")


def all_sessions_for_row(row: Any) -> list[dict[str, object]]:
    return candidate_sessions_for_row(row, list(row.haystack_session_ids))


def main() -> int:
    args = parse_args()
    load_dotenv()
    artifact_dir = Path(args.artifact_dir)
    graph_dir = Path(args.graph_dir) if args.graph_dir else artifact_dir / "graphs"
    status_dir = artifact_dir / "status"
    intermediate_dir = artifact_dir / "intermediate" / args.question_id
    cache_dir = artifact_dir / "cache"
    error_dir = artifact_dir / "errors"

    status = StatusWriter(
        status_dir / f"{args.question_id}.status.json",
        {
            "method": METHOD_NAME,
            "question_id": args.question_id,
            "status": "running",
            "stage": "initializing",
            "pid": os.getpid(),
            "error": None,
        },
    )

    try:
        status.update(stage="loading_case")
        data_path = resolve_data_path(args.data)
        row = find_row(data_path, args.question_id)
        status.update(question_type=row.question_type)
        graph_dir = graph_dir / row.question_type
        graph_path = graph_dir / f"{args.question_id}.graph.json"
        if graph_path.exists() and not args.overwrite:
            status.update(status="completed", stage="skip_existing_graph", graph_path=str(graph_path))
            print(f"[{args.question_id}] skip existing graph {graph_path}", flush=True)
            return 0

        sessions = all_sessions_for_row(row)
        intermediate_payload = {
            "method": METHOD_NAME,
            "question_id": row.question_id,
            "question_type": row.question_type,
            "source_session_ids": list(row.haystack_session_ids),
            "n_source_sessions": len(sessions),
            "question_independent_construction": True,
            "created_at": utc_now_iso(),
        }
        atomic_write_json(intermediate_dir / "case_input.json", intermediate_payload)

        if args.dry_run:
            status.update(status="completed", stage="dry_run", n_source_sessions=len(sessions))
            print(f"[{args.question_id}] dry-run ok sessions={len(sessions)} graph_path={graph_path}", flush=True)
            return 0

        status.update(stage="configuring_llm_client")
        api_key, default_model, api_base = provider_config(args.construction_provider)

        def on_client_status(stage: str, payload: dict[str, Any]) -> None:
            status.update(stage=stage, **payload)

        client = StableRequestsJsonClient(
            model=args.construction_model or default_model,
            api_key=api_key,
            api_base=api_base,
            cache_path=cache_dir / f"{args.question_id}.llm_cache.json",
            use_cache=not args.no_cache,
            request_timeout=args.request_timeout_seconds,
            max_tokens=args.max_tokens,
            status_callback=on_client_status,
        )
        extractor = QuestionIndependentGraphExtractor(client)
        builder = TaskSemanticsLocalGraphBuilder(
            batch_size=args.graph_batch_size,
            max_facets=args.max_facets,
            extractor=extractor,
        )

        status.update(stage="building_question_independent_graph")
        graph = builder.build(
            sessions=sessions,
            question="",
            question_type="",
            question_date="",
        )
        graph.graph["method"] = METHOD_NAME
        graph.graph["question_independent_construction"] = True
        graph.graph.pop("question", None)
        graph.graph.pop("question_type", None)
        graph.graph.pop("question_date", None)

        status.update(stage="writing_graph")
        metadata = {
            "method": METHOD_NAME,
            "base_schema": "prebuilt_llm_kg_graph_v2_stability_first",
            "question_id": row.question_id,
            "question_type": row.question_type,
            "source_session_ids": list(row.haystack_session_ids),
            "n_source_sessions": len(sessions),
            "construction_provider": args.construction_provider,
            "construction_model": args.construction_model,
            "graph_batch_size": args.graph_batch_size,
            "max_facets": args.max_facets,
            "max_tokens": args.max_tokens,
            "request_timeout_seconds": args.request_timeout_seconds,
            "question_independent_construction": True,
        }
        write_graph_artifact(graph_path, graph, metadata)
        summary = {
            "question_id": row.question_id,
            "question_type": row.question_type,
            "graph_path": str(graph_path),
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "llm_calls": client.call_index,
            "n_source_sessions": len(sessions),
            "completed_at": utc_now_iso(),
        }
        atomic_write_json(intermediate_dir / "build_summary.json", summary)
        status.update(
            status="completed",
            stage="completed",
            graph_path=str(graph_path),
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
            llm_calls=client.call_index,
        )
        print(f"[{args.question_id}] wrote {graph_path}", flush=True)
        return 0
    except (LLMRequestError, Exception) as exc:
        error_payload = {
            "method": METHOD_NAME,
            "question_id": args.question_id,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "failed_at": utc_now_iso(),
        }
        atomic_write_json(error_dir / f"{args.question_id}.error.json", error_payload)
        status.update(status="failed", stage="failed", error=error_payload)
        print(f"[{args.question_id}] failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


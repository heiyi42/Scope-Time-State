from __future__ import annotations

import argparse
from collections import Counter
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
from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import TaskSemanticsLocalGraphBuilder
from longmemeval_s_graph_retrieval.task_semantics_local_graph.llm_extractor import LLMGraphExtractor
from pipeline.external.longmemeval_s.runner import bm25_top_session_ids, retrieval_query

from .stable_client import StableRequestsJsonClient
from .status_utils import StatusWriter, atomic_write_json, utc_now_iso


METHOD_NAME = "prebuilt_llm_kg_graph_v2_stability_first"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one stability-first graph artifact for one LongMemEval-S case.")
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--data", default=None)
    parser.add_argument("--task-candidate-k", type=int, default=20)
    parser.add_argument("--graph-batch-size", type=int, default=5)
    parser.add_argument("--max-facets", type=int, default=12)
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
    if args.task_candidate_k < 1:
        parser.error("--task-candidate-k must be >= 1")
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
    rows = load_rows_utf8(data_path)
    for row in rows:
        if row.question_id == question_id:
            return row
    raise ValueError(f"question_id not found: {question_id}")


def main() -> int:
    args = parse_args()
    load_dotenv()
    artifact_dir = Path(args.artifact_dir)
    graph_dir = Path(args.graph_dir) if args.graph_dir else artifact_dir / "graphs"
    status_dir = artifact_dir / "status"
    intermediate_dir = artifact_dir / "intermediate" / args.question_id
    cache_dir = artifact_dir / "cache"
    error_dir = artifact_dir / "errors"
    # graph_dir is resolved after row is loaded so question_type is known
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
        status.update(question_type=row.question_type, question=row.question)
        graph_dir = graph_dir / row.question_type
        graph_path = graph_dir / f"{args.question_id}.graph.json"
        if graph_path.exists() and not args.overwrite:
            status.update(status="completed", stage="skip_existing_graph", graph_path=str(graph_path))
            print(f"[{args.question_id}] skip existing graph {graph_path}", flush=True)
            return 0
        if args.dry_run:
            status.update(status="completed", stage="dry_run")
            print(f"[{args.question_id}] dry-run ok", flush=True)
            return 0

        status.update(stage="bm25_candidate_selection")
        selected_session_ids = bm25_top_session_ids(
            row,
            args.task_candidate_k,
            query_text=retrieval_query(row, expand=True),
        )
        sessions = candidate_sessions_for_row(row, selected_session_ids)
        intermediate_payload = {
            "method": METHOD_NAME,
            "question_id": row.question_id,
            "question_type": row.question_type,
            "question": row.question,
            "question_date": row.question_date,
            "candidate_session_ids": list(selected_session_ids),
            "answer_session_ids": list(row.answer_session_ids),
            "n_candidate_sessions": len(sessions),
            "created_at": utc_now_iso(),
        }
        atomic_write_json(intermediate_dir / "case_input.json", intermediate_payload)

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
        extractor = LLMGraphExtractor(client)
        builder = TaskSemanticsLocalGraphBuilder(
            batch_size=args.graph_batch_size,
            max_facets=args.max_facets,
            extractor=extractor,
        )

        status.update(stage="building_graph")
        graph = builder.build(
            sessions=sessions,
            question=row.question,
            question_type=row.question_type,
            question_date=row.question_date,
        )
        status.update(stage="writing_graph")
        metadata = {
            "method": METHOD_NAME,
            "base_method": "prebuilt_llm_kg_graph",
            "question_id": row.question_id,
            "question_type": row.question_type,
            "question": row.question,
            "question_date": row.question_date,
            "candidate_session_ids": list(selected_session_ids),
            "answer_session_ids": list(row.answer_session_ids),
            "construction_provider": args.construction_provider,
            "construction_model": args.construction_model,
            "task_candidate_k": args.task_candidate_k,
            "graph_batch_size": args.graph_batch_size,
            "max_facets": args.max_facets,
            "max_tokens": args.max_tokens,
            "request_timeout_seconds": args.request_timeout_seconds,
        }
        write_graph_artifact(graph_path, graph, metadata)
        summary = {
            "question_id": row.question_id,
            "question_type": row.question_type,
            "graph_path": str(graph_path),
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "llm_calls": client.call_index,
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

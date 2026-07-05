from __future__ import annotations

import argparse
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
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v8.stable_client import (
    StableRequestsJsonClient,
)
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v8.status_utils import (
    StatusWriter,
    atomic_write_json,
    utc_now_iso,
)

from .checkpoint_builder import CheckpointedQuestionIndependentGraphBuilder
from .llm_extractor import QuestionIndependentGraphExtractor


METHOD_NAME = "prebuilt_llm_kg_graph_v8"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one v6 question-independent graph with batch checkpoints.")
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
    if args.graph_batch_size < 1:
        parser.error("--graph-batch-size must be >= 1")
    if args.max_facets < 1:
        parser.error("--max-facets must be >= 1")
    if args.request_timeout_seconds < 1:
        parser.error("--request-timeout-seconds must be >= 1")
    if args.max_tokens < 1:
        parser.error("--max-tokens must be >= 1")
    if args.max_claims_per_event < 0:
        parser.error("--max-claims-per-event must be >= 0")
    if args.max_entity_labels < 1:
        parser.error("--max-entity-labels must be >= 1")
    if args.max_scope_labels < 1:
        parser.error("--max-scope-labels must be >= 1")
    if args.partial_graph_every < 1:
        parser.error("--partial-graph-every must be >= 1")
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
    graph_root = Path(args.graph_dir) if args.graph_dir else artifact_dir / "graphs"
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
        graph_dir = graph_root / row.question_type
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

        batch_dir = artifact_dir / "batches" / row.question_type / row.question_id
        partial_graph_path = None
        if not args.no_partial_graph:
            partial_graph_path = artifact_dir / "partial_graphs" / row.question_type / f"{row.question_id}.partial.graph.json"

        if args.dry_run:
            status.update(
                status="completed",
                stage="dry_run",
                n_source_sessions=len(sessions),
                graph_path=str(graph_path),
                batch_dir=str(batch_dir),
                partial_graph_path=str(partial_graph_path) if partial_graph_path else None,
            )
            print(f"[{args.question_id}] dry-run ok sessions={len(sessions)} graph_path={graph_path}", flush=True)
            return 0

        status.update(stage="configuring_llm_client")
        api_key, default_model, api_base = provider_config(args.construction_provider)

        def on_status(stage: str, payload: dict[str, Any]) -> None:
            status.update(stage=stage, **payload)

        client = StableRequestsJsonClient(
            model=args.construction_model or default_model,
            api_key=api_key,
            api_base=api_base,
            cache_path=cache_dir / f"{args.question_id}.llm_cache.json",
            use_cache=not args.no_cache,
            request_timeout=args.request_timeout_seconds,
            max_tokens=args.max_tokens,
            status_callback=on_status,
        )
        extractor = QuestionIndependentGraphExtractor(client)
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
            "max_claims_per_event": args.max_claims_per_event,
            "max_entity_labels": args.max_entity_labels,
            "max_scope_labels": args.max_scope_labels,
            "run_state_reconcile": args.run_state_reconcile,
            "question_independent_construction": True,
            "build_only": True,
        }
        builder = CheckpointedQuestionIndependentGraphBuilder(
            extractor=extractor,
            batch_size=args.graph_batch_size,
            max_facets=args.max_facets,
            batch_dir=batch_dir,
            partial_graph_path=partial_graph_path,
            partial_graph_every=args.partial_graph_every,
            resume=not args.no_resume,
            run_state_reconcile=args.run_state_reconcile,
            max_claims_per_event=args.max_claims_per_event,
            max_entity_labels=args.max_entity_labels,
            max_scope_labels=args.max_scope_labels,
            status_callback=on_status,
        )

        status.update(stage="building_checkpointed_graph")
        result = builder.build(sessions=sessions, metadata=metadata, question_id=row.question_id)

        status.update(stage="writing_final_graph")
        final_metadata = dict(metadata)
        final_metadata.update(
            {
                "partial": False,
                "completed_at": utc_now_iso(),
                "total_batches": result.total_batches,
                "completed_batches": result.completed_batches,
                "llm_batch_calls": result.llm_batch_calls,
                "reused_batch_checkpoints": result.reused_batch_checkpoints,
                "state_reconcile_ran": result.state_reconcile_ran,
            }
        )
        write_graph_artifact(graph_path, result.graph, final_metadata)
        summary = {
            "question_id": row.question_id,
            "question_type": row.question_type,
            "graph_path": str(graph_path),
            "partial_graph_path": str(result.partial_graph_path) if result.partial_graph_path else None,
            "batch_dir": str(batch_dir),
            "nodes": result.graph.number_of_nodes(),
            "edges": result.graph.number_of_edges(),
            "llm_calls": client.call_index,
            "llm_batch_calls": result.llm_batch_calls,
            "reused_batch_checkpoints": result.reused_batch_checkpoints,
            "total_batches": result.total_batches,
            "completed_batches": result.completed_batches,
            "n_source_sessions": len(sessions),
            "completed_at": utc_now_iso(),
        }
        atomic_write_json(intermediate_dir / "build_summary.json", summary)
        status.update(
            status="completed",
            stage="completed",
            graph_path=str(graph_path),
            partial_graph_path=str(result.partial_graph_path) if result.partial_graph_path else None,
            batch_dir=str(batch_dir),
            nodes=result.graph.number_of_nodes(),
            edges=result.graph.number_of_edges(),
            llm_calls=client.call_index,
            total_batches=result.total_batches,
            completed_batches=result.completed_batches,
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


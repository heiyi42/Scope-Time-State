from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Sequence

from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.common import load_rows_utf8, resolve_data_path
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.graph_store import load_graph
from pipeline.external.longmemeval_s.adapters import TASK_TYPES
from pipeline.external.longmemeval_s.runner import LMERow, precision, recall, select_rows

from .run_scope_eval import artifact_path, average
from .scope_retriever_v7_4 import BM25ScopeProfileGraphRetriever


METHOD_NAME = "prebuilt_llm_kg_graph_v7_4_bm25_scope_first"
DEFAULT_GRAPH_DIR = (
    Path(__file__).resolve().parents[1] / "prebuilt_llm_kg_graph_v6_build_only" / "artifacts" / "graphs"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "outputs" / "scope_eval_v7_4.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate v7.4 BM25 scope-profile retrieval without answer generation.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--question-ids", nargs="+", default=[])
    parser.add_argument("--top-scopes", type=int, default=8)
    parser.add_argument("--top-entities", type=int, default=8)
    parser.add_argument("--max-events-per-scope", type=int, default=160)
    parser.add_argument("--max-claims", type=int, default=48)
    parser.add_argument("--max-sessions", type=int, default=20)
    parser.add_argument("--max-evidence", type=int, default=20)
    parser.add_argument("--neighbor-window", type=int, default=2)
    parser.add_argument("--relation-depth", type=int, default=1)
    parser.add_argument("--lexical-fallback-events", type=int, default=12)
    parser.add_argument("--scope-profile-events", type=int, default=120)
    parser.add_argument("--scope-profile-claims", type=int, default=160)
    parser.add_argument("--scope-profile-event-tokens", type=int, default=80)
    parser.add_argument("--scope-profile-claim-tokens", type=int, default=60)
    parser.add_argument("--scope-label-weight", type=int, default=3)
    parser.add_argument("--entity-label-weight", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    validate_args(parser, args)
    return args


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.top_scopes < 1:
        parser.error("--top-scopes must be >= 1")
    if args.top_entities < 0:
        parser.error("--top-entities must be >= 0")
    if args.max_events_per_scope < 1:
        parser.error("--max-events-per-scope must be >= 1")
    if args.max_claims < 1:
        parser.error("--max-claims must be >= 1")
    if args.max_sessions < 1:
        parser.error("--max-sessions must be >= 1")
    if args.max_evidence < 1:
        parser.error("--max-evidence must be >= 1")
    if args.neighbor_window < 0:
        parser.error("--neighbor-window must be >= 0")
    if args.relation_depth < 0:
        parser.error("--relation-depth must be >= 0")
    if args.lexical_fallback_events < 0:
        parser.error("--lexical-fallback-events must be >= 0")
    if args.scope_profile_events < 1:
        parser.error("--scope-profile-events must be >= 1")
    if args.scope_profile_claims < 1:
        parser.error("--scope-profile-claims must be >= 1")
    if args.scope_profile_event_tokens < 1:
        parser.error("--scope-profile-event-tokens must be >= 1")
    if args.scope_profile_claim_tokens < 1:
        parser.error("--scope-profile-claim-tokens must be >= 1")
    if args.scope_label_weight < 1:
        parser.error("--scope-label-weight must be >= 1")
    if args.entity_label_weight < 0:
        parser.error("--entity-label-weight must be >= 0")


def select_target_rows(args: argparse.Namespace) -> tuple[Path, List[LMERow]]:
    data_path = resolve_data_path(args.data)
    rows = select_rows(load_rows_utf8(data_path), args.question_types, args.limit_cases, args.limit_per_type)
    if args.question_ids:
        allowed = set(args.question_ids)
        rows = [row for row in rows if row.question_id in allowed]
    unsupported = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported:
        raise ValueError(f"unsupported question types in selection: {unsupported}")
    return data_path, rows


def make_retriever(args: argparse.Namespace) -> BM25ScopeProfileGraphRetriever:
    return BM25ScopeProfileGraphRetriever(
        top_scopes=args.top_scopes,
        top_entities=args.top_entities,
        max_events_per_scope=args.max_events_per_scope,
        max_claims=args.max_claims,
        max_sessions=args.max_sessions,
        max_evidence=args.max_evidence,
        neighbor_window=args.neighbor_window,
        relation_depth=args.relation_depth,
        lexical_fallback_events=args.lexical_fallback_events,
        scope_profile_events=args.scope_profile_events,
        scope_profile_claims=args.scope_profile_claims,
        scope_profile_event_tokens=args.scope_profile_event_tokens,
        scope_profile_claim_tokens=args.scope_profile_claim_tokens,
        scope_label_weight=args.scope_label_weight,
        entity_label_weight=args.entity_label_weight,
    )


def retriever_config(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "top_scopes": args.top_scopes,
        "top_entities": args.top_entities,
        "max_events_per_scope": args.max_events_per_scope,
        "max_claims": args.max_claims,
        "max_sessions": args.max_sessions,
        "max_evidence": args.max_evidence,
        "neighbor_window": args.neighbor_window,
        "relation_depth": args.relation_depth,
        "lexical_fallback_events": args.lexical_fallback_events,
        "scope_profile_events": args.scope_profile_events,
        "scope_profile_claims": args.scope_profile_claims,
        "scope_profile_event_tokens": args.scope_profile_event_tokens,
        "scope_profile_claim_tokens": args.scope_profile_claim_tokens,
        "scope_label_weight": args.scope_label_weight,
        "entity_label_weight": args.entity_label_weight,
    }


def summarize_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(str(row["question_type"]), []).append(row)
    summary: Dict[str, Any] = {
        "n": len(rows),
        "evidence_session_recall": average(row["evidence_session_recall"] for row in rows),
        "evidence_session_precision": average(row["evidence_session_precision"] for row in rows),
        "scope_count": average(row["n_matched_scopes"] for row in rows),
        "evidence_count": average(row["n_evidence_snippets"] for row in rows),
        "by_question_type": {},
    }
    for question_type, typed_rows in sorted(by_type.items()):
        summary["by_question_type"][question_type] = {
            "n": len(typed_rows),
            "evidence_session_recall": average(row["evidence_session_recall"] for row in typed_rows),
            "evidence_session_precision": average(row["evidence_session_precision"] for row in typed_rows),
            "scope_count": average(row["n_matched_scopes"] for row in typed_rows),
            "evidence_count": average(row["n_evidence_snippets"] for row in typed_rows),
        }
    return summary


def main() -> int:
    args = parse_args()
    try:
        data_path, rows = select_target_rows(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    graph_dir = Path(args.graph_dir)
    missing = [row.question_id for row in rows if not artifact_path(graph_dir, row).exists()]
    question_types = Counter(row.question_type for row in rows)
    if args.dry_run:
        print(
            f"valid v7.4 BM25 scope eval: rows={len(rows)} missing_graphs={len(missing)} "
            f"question_types={dict(question_types)} graph_dir={graph_dir} data_path={data_path}"
        )
        if missing:
            print(f"missing graph ids: {missing[:10]}")
        return 0 if not missing else 1
    if missing:
        print(f"missing {len(missing)} graph artifacts; first missing ids: {missing[:10]}", file=sys.stderr)
        return 2

    retriever = make_retriever(args)
    eval_rows: List[Dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        path = artifact_path(graph_dir, row)
        graph = load_graph(path)
        packet = retriever.retrieve_state_packet(graph, row.question, row.question_type, row.question_date)
        evidence_session_ids = list(packet.get("relevant_session_ids") or [])
        eval_rows.append(
            {
                "question_id": row.question_id,
                "question_type": row.question_type,
                "question": row.question,
                "graph_artifact": str(path),
                "answer_session_ids": list(row.answer_session_ids),
                "evidence_session_ids": evidence_session_ids,
                "evidence_session_recall": recall(evidence_session_ids, row.answer_session_ids),
                "evidence_session_precision": precision(evidence_session_ids, row.answer_session_ids),
                "matched_scopes": packet.get("matched_scopes") or [],
                "matched_entities": packet.get("matched_entities") or [],
                "scoped_node_counts": packet.get("scoped_node_counts") or {},
                "n_matched_scopes": len(packet.get("matched_scopes") or []),
                "n_evidence_snippets": len(packet.get("evidence_snippets") or []),
                "scope_ranker": packet.get("scope_ranker"),
                "graph_state_packet": packet,
            }
        )
        print(
            f"[{METHOD_NAME}] {index}/{len(rows)} {row.question_id} {row.question_type} "
            f"recall={eval_rows[-1]['evidence_session_recall']:.3f}",
            flush=True,
        )

    output = {
        "benchmark": "LongMemEval-S",
        "method": METHOD_NAME,
        "data_path": str(data_path),
        "graph_dir": str(graph_dir),
        "question_types": dict(question_types),
        "retriever": retriever_config(args),
        "summary": summarize_rows(eval_rows),
        "rows": eval_rows,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

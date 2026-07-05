from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Dict, List, Optional, Sequence

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.common import load_rows_utf8, resolve_data_path
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.graph_store import load_graph, load_graph_artifact
from pipeline.external.longmemeval_s.adapters import TASK_TYPES, get_adapter
from pipeline.external.longmemeval_s.runner import (
    LMERow,
    TextJudgeClient,
    answer_system_prompt,
    answer_user_prompt,
    evidence_ids_from_extraction,
    local_answer_match,
    normalize_session_ids,
    precision,
    print_summary,
    recall,
    select_rows,
    summarize,
)

from .bm25_llm_scope_filter_retriever import BM25LLMScopeFilterError, BM25LLMScopeFilterGraphRetriever


METHOD_NAME = "prebuilt_llm_kg_graph_v10_1"
DEFAULT_GRAPH_DIR = Path(__file__).resolve().parent / "artifacts" / "graphs"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "outputs" / "results_v10_1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LongMemEval-S using V10.1 BM25 scope recall plus LLM scope denoising.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--question-ids", nargs="+", default=[])
    parser.add_argument("--answer-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--answer-model", default="gpt-4o-mini")
    parser.add_argument("--answer-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v10_1_answer.json"))
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--judge-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v10_1_judge.json"))
    parser.add_argument("--scope-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--scope-model", default="gpt-4o-mini")
    parser.add_argument("--scope-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v10_1_scope.json"))
    parser.add_argument("--scope-profile-events", type=int, default=5)
    parser.add_argument("--scope-profile-claims", type=int, default=10)
    parser.add_argument("--scope-label-weight", type=int, default=3)
    parser.add_argument("--entity-label-weight", type=int, default=2)
    parser.add_argument("--scope-profile-event-tokens", type=int, default=80)
    parser.add_argument("--scope-profile-claim-tokens", type=int, default=60)
    parser.add_argument("--filter-profile-events", type=int, default=4)
    parser.add_argument("--filter-profile-claims", type=int, default=6)
    parser.add_argument("--filter-profile-entities", type=int, default=8)
    parser.add_argument("--filter-profile-facets", type=int, default=4)
    parser.add_argument("--filter-profile-event-tokens", type=int, default=45)
    parser.add_argument("--filter-profile-claim-tokens", type=int, default=45)
    parser.add_argument("--filter-profile-facet-tokens", type=int, default=30)
    parser.add_argument("--min-filtered-scopes", type=int, default=2)
    parser.add_argument("--scope-filter-fallback", choices=("bm25", "error"), default="bm25")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    validate_args(parser, args)
    return args


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.scope_profile_events < 1:
        parser.error("--scope-profile-events must be >= 1")
    if args.scope_profile_claims < 1:
        parser.error("--scope-profile-claims must be >= 1")
    if args.scope_profile_event_tokens < 1:
        parser.error("--scope-profile-event-tokens must be >= 1")
    if args.scope_profile_claim_tokens < 1:
        parser.error("--scope-profile-claim-tokens must be >= 1")
    if args.scope_label_weight < 0:
        parser.error("--scope-label-weight must be >= 0")
    if args.entity_label_weight < 0:
        parser.error("--entity-label-weight must be >= 0")
    if args.filter_profile_events < 1:
        parser.error("--filter-profile-events must be >= 1")
    if args.filter_profile_claims < 1:
        parser.error("--filter-profile-claims must be >= 1")
    if args.filter_profile_entities < 1:
        parser.error("--filter-profile-entities must be >= 1")
    if args.filter_profile_facets < 1:
        parser.error("--filter-profile-facets must be >= 1")
    if args.filter_profile_event_tokens < 1:
        parser.error("--filter-profile-event-tokens must be >= 1")
    if args.filter_profile_claim_tokens < 1:
        parser.error("--filter-profile-claim-tokens must be >= 1")
    if args.filter_profile_facet_tokens < 1:
        parser.error("--filter-profile-facet-tokens must be >= 1")
    if args.min_filtered_scopes < 1:
        parser.error("--min-filtered-scopes must be >= 1")


def make_client(provider: str, model: str, cache_path: Path, use_cache: bool) -> LLMClient:
    api_key, default_model, api_base = provider_config(provider)
    return LLMClient(
        provider=provider,
        model=model or default_model,
        api_key=api_key,
        api_base=api_base,
        cache_path=cache_path,
        use_cache=use_cache,
    )


def make_retriever(args: argparse.Namespace, scope_client: LLMClient) -> BM25LLMScopeFilterGraphRetriever:
    return BM25LLMScopeFilterGraphRetriever(
        scope_client=scope_client,
        scope_profile_events=args.scope_profile_events,
        scope_profile_claims=args.scope_profile_claims,
        scope_label_weight=args.scope_label_weight,
        entity_label_weight=args.entity_label_weight,
        scope_profile_event_tokens=args.scope_profile_event_tokens,
        scope_profile_claim_tokens=args.scope_profile_claim_tokens,
        filter_profile_events=args.filter_profile_events,
        filter_profile_claims=args.filter_profile_claims,
        filter_profile_entities=args.filter_profile_entities,
        filter_profile_facets=args.filter_profile_facets,
        filter_profile_event_tokens=args.filter_profile_event_tokens,
        filter_profile_claim_tokens=args.filter_profile_claim_tokens,
        filter_profile_facet_tokens=args.filter_profile_facet_tokens,
        min_filtered_scopes=args.min_filtered_scopes,
        scope_filter_fallback=args.scope_filter_fallback,
    )


def retriever_config(args: argparse.Namespace) -> Dict[str, object]:
    return {
        "scope_ranker": "bm25_scope_profile_llm_filter",
        "scope_provider": args.scope_provider,
        "scope_model": args.scope_model or None,
        "scope_cache": args.scope_cache,
        "scope_filter_fallback": args.scope_filter_fallback,
        "min_filtered_scopes": args.min_filtered_scopes,
        "scope_profile_events": args.scope_profile_events,
        "scope_profile_claims": args.scope_profile_claims,
        "scope_label_weight": args.scope_label_weight,
        "entity_label_weight": args.entity_label_weight,
        "scope_profile_event_tokens": args.scope_profile_event_tokens,
        "scope_profile_claim_tokens": args.scope_profile_claim_tokens,
        "filter_profile_events": args.filter_profile_events,
        "filter_profile_claims": args.filter_profile_claims,
        "filter_profile_entities": args.filter_profile_entities,
        "filter_profile_facets": args.filter_profile_facets,
        "filter_profile_event_tokens": args.filter_profile_event_tokens,
        "filter_profile_claim_tokens": args.filter_profile_claim_tokens,
        "filter_profile_facet_tokens": args.filter_profile_facet_tokens,
        "bm25_k1": 1.5,
        "bm25_b": 0.75,
    }


def artifact_path(graph_dir: Path, row: LMERow) -> Path:
    typed_path = graph_dir / row.question_type / f"{row.question_id}.graph.json"
    if typed_path.exists():
        return typed_path
    direct_path = graph_dir / f"{row.question_id}.graph.json"
    if direct_path.exists():
        return direct_path
    recursive_matches = list(graph_dir.glob(f"*/{row.question_id}.graph.json"))
    if recursive_matches:
        return recursive_matches[0]
    return typed_path


def run_rows(
    rows: Sequence[LMERow],
    graph_dir: Path,
    answer_client: LLMClient,
    judge_client: Optional[TextJudgeClient],
    retriever: BM25LLMScopeFilterGraphRetriever,
) -> Dict[str, object]:
    eval_rows: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        adapter = get_adapter(row.question_type)
        path = artifact_path(graph_dir, row)
        artifact = load_graph_artifact(path)
        graph = load_graph(path)
        state_packet = retriever.retrieve_state_packet(
            graph,
            question=row.question,
            question_type=row.question_type,
            question_date=row.question_date,
        )
        output = answer_client.complete_json(
            answer_system_prompt(adapter),
            answer_user_prompt(row, state_packet, adapter),
        )
        hypothesis = str(output.get("answer") or output.get("hypothesis") or "").strip()
        evidence_session_ids = normalize_session_ids(output.get("evidence_session_ids"))
        if not evidence_session_ids:
            evidence_session_ids = evidence_ids_from_extraction(state_packet)
        candidate_session_ids = list((artifact.get("metadata") or {}).get("source_session_ids") or [])
        autoeval_label = judge_client.judge(row, hypothesis) if judge_client is not None else None
        eval_rows.append(
            {
                "question_id": row.question_id,
                "question_type": row.question_type,
                "task_adapter": adapter.task_name,
                "is_abstention": row.question_id.endswith("_abs"),
                "question": row.question,
                "answer": row.answer,
                "gold_answer": row.answer,
                "hypothesis": hypothesis,
                "autoeval_label": autoeval_label,
                "local_answer_match": local_answer_match(row.answer, hypothesis),
                "candidate_session_ids": candidate_session_ids,
                "answer_session_ids": list(row.answer_session_ids),
                "evidence_session_ids": evidence_session_ids,
                "candidate_session_recall": recall(candidate_session_ids, row.answer_session_ids),
                "candidate_session_precision": precision(candidate_session_ids, row.answer_session_ids),
                "evidence_session_recall": recall(evidence_session_ids, row.answer_session_ids),
                "evidence_session_precision": precision(evidence_session_ids, row.answer_session_ids),
                "state_facets": output.get("state_facets"),
                "rejected_claims": output.get("rejected_claims"),
                "answer_rationale": output.get("answer_rationale"),
                "graph_state_packet": state_packet,
                "graph_artifact": str(path),
            }
        )
        print(f"[{METHOD_NAME}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    return {"variant": METHOD_NAME, "summary": summarize(eval_rows), "rows": eval_rows}


def main() -> int:
    args = parse_args()
    load_dotenv()
    data_path = resolve_data_path(args.data)
    graph_dir = Path(args.graph_dir)
    rows: List[LMERow] = list(
        select_rows(
            load_rows_utf8(data_path),
            args.question_types,
            args.limit_cases,
            args.limit_per_type,
        )
    )
    if args.question_ids:
        allowed = set(args.question_ids)
        rows = [row for row in rows if row.question_id in allowed]
    unsupported = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported:
        print(f"unsupported question types in selection: {unsupported}", file=sys.stderr)
        return 2

    missing = [row.question_id for row in rows if not artifact_path(graph_dir, row).exists()]
    question_types = Counter(row.question_type for row in rows)
    if args.dry_run:
        print(
            f"valid v10.1 BM25+LLM scope graph eval run: rows={len(rows)} missing_graphs={len(missing)} "
            f"question_types={dict(question_types)} graph_dir={graph_dir} data_path={data_path}"
        )
        if missing:
            print(f"missing graph ids: {missing[:10]}")
        return 0 if not missing else 1
    if missing:
        print(f"missing {len(missing)} graph artifacts; first missing ids: {missing[:10]}", file=sys.stderr)
        return 2

    try:
        scope_client = make_client(
            args.scope_provider,
            args.scope_model,
            Path(args.scope_cache),
            use_cache=not args.no_cache,
        )
        retriever = make_retriever(args, scope_client)
        answer_client = make_client(
            args.answer_provider,
            args.answer_model,
            Path(args.answer_cache),
            use_cache=not args.no_cache,
        )
        judge_client: Optional[TextJudgeClient] = None
        if args.judge:
            judge_api_key, judge_default_model, judge_api_base = provider_config(args.judge_provider)
            judge_client = TextJudgeClient(
                provider=args.judge_provider,
                model=args.judge_model or judge_default_model,
                api_key=judge_api_key,
                api_base=judge_api_base,
                cache_path=Path(args.judge_cache),
                use_cache=not args.no_cache,
            )
        result = run_rows(rows, graph_dir, answer_client, judge_client, retriever)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except (LLMRequestError, BM25LLMScopeFilterError, ValueError) as exc:
        print(f"\nLLM request failed: {exc}", file=sys.stderr)
        return 1

    output = {
        "benchmark": "LongMemEval-S",
        "method": METHOD_NAME,
        "data_path": str(data_path),
        "graph_dir": str(graph_dir),
        "answer_provider": args.answer_provider,
        "answer_model": args.answer_model,
        "judge_provider": args.judge_provider if args.judge else None,
        "judge_model": args.judge_model if args.judge else None,
        "variants": [METHOD_NAME],
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "question_types": dict(question_types),
        "retriever": retriever_config(args),
        "results": [result],
    }
    print_summary(args.answer_provider, args.answer_model, [result])
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

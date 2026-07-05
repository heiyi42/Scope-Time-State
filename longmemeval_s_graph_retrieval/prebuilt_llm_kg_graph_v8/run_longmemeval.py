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

from .llm_scope_retriever import LLMScopeSelectionError, LLMScopeSelectorGraphRetriever


METHOD_NAME = "prebuilt_llm_kg_graph_v8"
DEFAULT_GRAPH_DIR = Path(__file__).resolve().parent / "artifacts" / "graphs"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "outputs" / "results_v8.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LongMemEval-S using V8 LLM semantic scope selection.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--question-ids", nargs="+", default=[])
    parser.add_argument("--answer-provider", default="openai")
    parser.add_argument("--answer-model", default="gpt-4o-mini")
    parser.add_argument("--answer-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v8_answer.json"))
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-provider", default="openai")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--judge-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v8_judge.json"))
    parser.add_argument("--scope-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--scope-model", default="gpt-4o-mini")
    parser.add_argument("--scope-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v8_scope.json"))
    parser.add_argument("--scope-profile-events", type=int, default=3)
    parser.add_argument("--scope-profile-claims", type=int, default=5)
    parser.add_argument("--scope-profile-entities", type=int, default=5)
    parser.add_argument("--scope-profile-facets", type=int, default=3)
    parser.add_argument("--scope-profile-event-tokens", type=int, default=30)
    parser.add_argument("--scope-profile-claim-tokens", type=int, default=40)
    parser.add_argument("--scope-profile-facet-tokens", type=int, default=20)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def make_scope_client(args: argparse.Namespace) -> LLMClient:
    api_key, default_model, api_base = provider_config(args.scope_provider)
    model = args.scope_model or default_model
    return LLMClient(
        provider=args.scope_provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.scope_cache),
        use_cache=not args.no_cache,
    )


def make_retriever(args: argparse.Namespace, scope_client: LLMClient) -> LLMScopeSelectorGraphRetriever:
    return LLMScopeSelectorGraphRetriever(
        scope_client=scope_client,
        scope_profile_events=args.scope_profile_events,
        scope_profile_claims=args.scope_profile_claims,
        scope_profile_entities=args.scope_profile_entities,
        scope_profile_facets=args.scope_profile_facets,
        scope_profile_event_tokens=args.scope_profile_event_tokens,
        scope_profile_claim_tokens=args.scope_profile_claim_tokens,
        scope_profile_facet_tokens=args.scope_profile_facet_tokens,
    )


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


def make_client(provider: str, model: str, cache_path: Path, use_cache: bool) -> LLMClient:
    api_key, default_model, api_base = provider_config(provider)
    actual_model = model or default_model
    return LLMClient(
        provider=provider,
        model=actual_model,
        api_key=api_key,
        api_base=api_base,
        cache_path=cache_path,
        use_cache=use_cache,
    )


def run_rows(
    rows: Sequence[LMERow],
    graph_dir: Path,
    answer_client: LLMClient,
    judge_client: Optional[TextJudgeClient],
    retriever: LLMScopeSelectorGraphRetriever,
) -> Dict[str, object]:
    results: List[Dict] = []
    for index, row in enumerate(rows, start=1):
        path = artifact_path(graph_dir, row)
        artifact = load_graph_artifact(path)
        graph = load_graph(path)
        state_packet = retriever.retrieve_state_packet(
            graph, row.question, row.question_type, row.question_date
        )
        adapter = get_adapter(row.question_type)
        output = answer_client.complete_json(
            answer_system_prompt(adapter),
            answer_user_prompt(row, state_packet, adapter),
        )
        hypothesis = str(output.get("answer") or output.get("hypothesis") or "").strip()
        autoeval_label = judge_client.judge(row, hypothesis) if judge_client is not None else None
        evidence_session_ids = normalize_session_ids(output.get("evidence_session_ids"))
        if not evidence_session_ids:
            evidence_session_ids = evidence_ids_from_extraction(state_packet)
        candidate_session_ids = list((artifact.get("metadata") or {}).get("source_session_ids") or [])
        results.append({
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
        })
        print(f"[{METHOD_NAME}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    return {"variant": METHOD_NAME, "summary": summarize(results), "rows": results}


def main() -> int:
    args = parse_args()
    load_dotenv()

    data_path = resolve_data_path(args.data)
    rows: List[LMERow] = list(select_rows(
        load_rows_utf8(data_path),
        args.question_types,
        args.limit_cases,
        args.limit_per_type,
    ))
    if args.question_ids:
        allowed = set(args.question_ids)
        rows = [r for r in rows if r.question_id in allowed]
    unsupported = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported:
        print(f"unsupported question types in selection: {unsupported}", file=sys.stderr)
        return 2

    graph_dir = Path(args.graph_dir)
    missing = [r.question_id for r in rows if not artifact_path(graph_dir, r).exists()]
    question_types = Counter(r.question_type for r in rows)

    if args.dry_run:
        print(f"valid v8: rows={len(rows)} missing={len(missing)} types={dict(question_types)}")
        return 0 if not missing else 1

    if missing:
        print(f"missing {len(missing)} graphs: {missing[:10]}", file=sys.stderr)
        return 2

    try:
        scope_client = make_scope_client(args)
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
    except (LLMRequestError, LLMScopeSelectionError, ValueError) as exc:
        print(f"LLM request failed: {exc}", file=sys.stderr)
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
        "question_types": dict(question_types),
        "results": [result],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(args.answer_provider, args.answer_model, [result])
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

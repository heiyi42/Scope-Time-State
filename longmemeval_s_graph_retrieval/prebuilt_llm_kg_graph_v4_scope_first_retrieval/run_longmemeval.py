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
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.scope_first_retriever import (
    ScopeFirstGraphRetriever,
)
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


DEFAULT_GRAPH_DIR = Path(__file__).resolve().parent / "artifacts" / "graphs"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "outputs" / "results_v4_scope_first_retrieval.json"
VARIANT = "prebuilt_llm_kg_graph_v4_scope_first_retrieval"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LongMemEval-S using v4 scope-first graph retrieval.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--answer-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--answer-model", default="gpt-4o-mini")
    parser.add_argument("--answer-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v4_scope_first_answer.json"))
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--judge-model", default="gpt-4o-2024-08-06")
    parser.add_argument("--judge-cache", default=str(DEFAULT_OUTPUT.parent / "llm_cache.v4_scope_first_judge.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


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
) -> Dict[str, object]:
    retriever = ScopeFirstGraphRetriever()
    eval_rows: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        adapter = get_adapter(row.question_type)
        path = artifact_path(graph_dir, row)
        if not path.exists():
            raise FileNotFoundError(f"missing prebuilt graph artifact for {row.question_id}: {path}")
        artifact = load_graph_artifact(path)
        graph = load_graph(path)
        state_packet = retriever.retrieve_state_packet(
            graph,
            question=row.question,
            question_type=row.question_type,
        )
        output = answer_client.complete_json(
            answer_system_prompt(adapter),
            answer_user_prompt(row, state_packet, adapter),
        )
        hypothesis = str(output.get("answer", "")).strip()
        evidence_session_ids = normalize_session_ids(output.get("evidence_session_ids"))
        if not evidence_session_ids:
            evidence_session_ids = evidence_ids_from_extraction(state_packet)
        candidate_session_ids = list((artifact.get("metadata") or {}).get("candidate_session_ids") or [])
        autoeval_label = judge_client.judge(row, hypothesis) if judge_client is not None else None
        eval_rows.append(
            {
                "question_id": row.question_id,
                "question_type": row.question_type,
                "task_adapter": adapter.task_name,
                "is_abstention": row.question_id.endswith("_abs"),
                "question": row.question,
                "gold_answer": row.answer,
                "hypothesis": hypothesis,
                "candidate_session_ids": candidate_session_ids,
                "evidence_session_ids": evidence_session_ids,
                "answer_session_ids": list(row.answer_session_ids),
                "candidate_session_recall": recall(candidate_session_ids, row.answer_session_ids),
                "candidate_session_precision": precision(candidate_session_ids, row.answer_session_ids),
                "evidence_session_recall": recall(evidence_session_ids, row.answer_session_ids),
                "evidence_session_precision": precision(evidence_session_ids, row.answer_session_ids),
                "local_answer_match": local_answer_match(row.answer, hypothesis),
                "autoeval_label": autoeval_label,
                "state_facets": output.get("state_facets"),
                "rejected_claims": output.get("rejected_claims"),
                "answer_rationale": output.get("answer_rationale"),
                "graph_state_packet": state_packet,
                "graph_artifact": str(path),
            }
        )
        print(f"[{VARIANT}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    return {"variant": VARIANT, "summary": summarize(eval_rows), "rows": eval_rows}


def main() -> int:
    args = parse_args()
    load_dotenv()
    data_path = resolve_data_path(args.data)
    graph_dir = Path(args.graph_dir)
    rows = select_rows(load_rows_utf8(data_path), args.question_types, args.limit_cases, args.limit_per_type)
    unsupported = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported:
        print(f"unsupported question types in selection: {unsupported}", file=sys.stderr)
        return 2
    missing = [row.question_id for row in rows if not artifact_path(graph_dir, row).exists()]
    question_types = Counter(row.question_type for row in rows)
    if args.dry_run:
        print(
            f"valid v4 scope-first graph eval run: rows={len(rows)} missing_graphs={len(missing)} "
            f"question_types={dict(question_types)} graph_dir={graph_dir} data_path={data_path}"
        )
        if missing:
            print(f"missing graph ids: {missing[:10]}")
        return 0 if not missing else 1
    if missing:
        print(f"missing {len(missing)} graph artifacts; first missing ids: {missing[:10]}", file=sys.stderr)
        return 2

    try:
        answer_client = make_client(
            args.answer_provider,
            args.answer_model,
            Path(args.answer_cache),
            use_cache=not args.no_cache,
        )
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    judge_client: Optional[TextJudgeClient] = None
    if args.judge:
        try:
            judge_api_key, judge_default_model, judge_api_base = provider_config(args.judge_provider)
        except RuntimeError as exc:
            print(f"Judge config error: {exc}", file=sys.stderr)
            return 2
        judge_client = TextJudgeClient(
            provider=args.judge_provider,
            model=args.judge_model or judge_default_model,
            api_key=judge_api_key,
            api_base=judge_api_base,
            cache_path=Path(args.judge_cache),
            use_cache=not args.no_cache,
        )

    try:
        result = run_rows(rows, graph_dir, answer_client, judge_client)
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = {
        "benchmark": "LongMemEval-S",
        "method": VARIANT,
        "data_path": str(data_path),
        "graph_dir": str(graph_dir),
        "answer_provider": args.answer_provider,
        "answer_model": args.answer_model,
        "judge_provider": args.judge_provider if args.judge else None,
        "judge_model": args.judge_model if args.judge else None,
        "variants": [VARIANT],
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "question_types": dict(question_types),
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

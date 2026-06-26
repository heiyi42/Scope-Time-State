from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Dict, List, Optional, Sequence

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config
from pipeline.external.longmemeval_s.adapters import TASK_TYPES, get_adapter
from pipeline.external.longmemeval_s.runner import (
    DATA_PATH as DEFAULT_RUNNER_DATA_PATH,
    LMERow,
    TextJudgeClient,
    answer_system_prompt,
    answer_user_prompt,
    bm25_top_session_ids,
    evidence_ids_from_extraction,
    local_answer_match,
    normalize_session_ids,
    precision,
    print_summary,
    recall,
    retrieval_query,
    select_rows,
    summarize,
)

from .pipeline import build_state_packet_with_llm_client


PROJECT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_DIR / "longmemeval_s_graph_retrieval" / "task_semantics_local_graph" / "outputs"
LOCAL_DATA_FALLBACK = (
    PROJECT_DIR
    / "Experiment"
    / "Other_BenchMark"
    / "LongMemEval-S"
    / "LongMemEval-S_data"
    / "data"
    / "longmemeval_s_cleaned.json"
)
VARIANT = "task_semantics_local_graph"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LongMemEval-S with task-semantics local graph construction.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--task-candidate-k", type=int, default=20)
    parser.add_argument("--graph-batch-size", type=int, default=5)
    parser.add_argument("--max-facets", type=int, default=12)
    parser.add_argument("--construction-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--construction-model", default="gpt-4o-mini")
    parser.add_argument("--answer-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--answer-model", default="gpt-4o-mini")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--judge-model", default="gpt-4o-2024-08-06")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "results_task_semantics_local_graph.json"))
    parser.add_argument("--construction-cache", default=str(OUTPUT_DIR / "llm_cache.task_graph_construction.json"))
    parser.add_argument("--answer-cache", default=str(OUTPUT_DIR / "llm_cache.task_graph_answer.json"))
    parser.add_argument("--judge-cache", default=str(OUTPUT_DIR / "llm_cache.task_graph_judge.json"))
    args = parser.parse_args()
    if args.task_candidate_k < 1:
        parser.error("--task-candidate-k must be >= 1")
    if args.graph_batch_size < 1:
        parser.error("--graph-batch-size must be >= 1")
    if args.max_facets < 1:
        parser.error("--max-facets must be >= 1")
    return args


def resolve_data_path(raw_path: Optional[str]) -> Path:
    if raw_path:
        return Path(raw_path)
    if DEFAULT_RUNNER_DATA_PATH.exists():
        return DEFAULT_RUNNER_DATA_PATH
    return LOCAL_DATA_FALLBACK


def load_rows_utf8(path: Path) -> List[LMERow]:
    raw_rows = json.loads(path.read_text(encoding="utf-8"))
    rows: List[LMERow] = []
    for raw in raw_rows:
        rows.append(
            LMERow(
                question_id=str(raw["question_id"]),
                question_type=str(raw["question_type"]),
                question=str(raw["question"]),
                answer=str(raw["answer"]),
                question_date=str(raw["question_date"]),
                haystack_session_ids=tuple(str(item) for item in raw["haystack_session_ids"]),
                haystack_dates=tuple(str(item) for item in raw["haystack_dates"]),
                haystack_sessions=tuple(tuple(dict(turn) for turn in session) for session in raw["haystack_sessions"]),
                answer_session_ids=tuple(str(item) for item in raw["answer_session_ids"]),
            )
        )
    return rows


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


def candidate_sessions_for_row(row: LMERow, session_ids: Sequence[str]) -> List[Dict[str, object]]:
    by_id = {
        session_id: (date, session)
        for session_id, date, session in zip(row.haystack_session_ids, row.haystack_dates, row.haystack_sessions)
    }
    candidates: List[Dict[str, object]] = []
    for session_id in session_ids:
        if session_id not in by_id:
            continue
        date, turns = by_id[session_id]
        candidates.append(
            {
                "session_id": session_id,
                "date": date,
                "turns": [dict(turn) for turn in turns],
            }
        )
    return candidates


def run_rows(
    rows: Sequence[LMERow],
    construction_client: LLMClient,
    answer_client: LLMClient,
    judge_client: Optional[TextJudgeClient],
    args: argparse.Namespace,
) -> Dict[str, object]:
    eval_rows: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        adapter = get_adapter(row.question_type)
        selected_session_ids = bm25_top_session_ids(
            row,
            args.task_candidate_k,
            query_text=retrieval_query(row, expand=True),
        )
        candidate_sessions = candidate_sessions_for_row(row, selected_session_ids)
        state_packet = build_state_packet_with_llm_client(
            sessions=candidate_sessions,
            question=row.question,
            question_type=row.question_type,
            question_date=row.question_date,
            llm_client=construction_client,
            batch_size=args.graph_batch_size,
            max_facets=args.max_facets,
        )
        output = answer_client.complete_json(
            answer_system_prompt(adapter),
            answer_user_prompt(row, state_packet, adapter),
        )
        hypothesis = str(output.get("answer", "")).strip()
        evidence_session_ids = normalize_session_ids(output.get("evidence_session_ids"))
        if not evidence_session_ids:
            evidence_session_ids = evidence_ids_from_extraction(state_packet)
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
                "candidate_session_ids": list(selected_session_ids),
                "evidence_session_ids": evidence_session_ids,
                "answer_session_ids": list(row.answer_session_ids),
                "candidate_session_recall": recall(selected_session_ids, row.answer_session_ids),
                "candidate_session_precision": precision(selected_session_ids, row.answer_session_ids),
                "evidence_session_recall": recall(evidence_session_ids, row.answer_session_ids),
                "evidence_session_precision": precision(evidence_session_ids, row.answer_session_ids),
                "local_answer_match": local_answer_match(row.answer, hypothesis),
                "autoeval_label": autoeval_label,
                "state_facets": output.get("state_facets"),
                "rejected_claims": output.get("rejected_claims"),
                "answer_rationale": output.get("answer_rationale"),
                "graph_state_packet": state_packet,
            }
        )
        print(f"[{VARIANT}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    return {"variant": VARIANT, "summary": summarize(eval_rows), "rows": eval_rows}


def main() -> int:
    args = parse_args()
    load_dotenv()
    data_path = resolve_data_path(args.data)
    rows = select_rows(load_rows_utf8(data_path), args.question_types, args.limit_cases, args.limit_per_type)
    unsupported_question_types = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported_question_types:
        print(f"unsupported question types in selection: {unsupported_question_types}", file=sys.stderr)
        return 2
    question_types = Counter(row.question_type for row in rows)
    if args.dry_run:
        print(
            f"valid task-semantics graph run: rows={len(rows)} "
            f"question_types={dict(question_types)} data_path={data_path}"
        )
        return 0

    try:
        construction_client = make_client(
            args.construction_provider,
            args.construction_model,
            Path(args.construction_cache),
            use_cache=not args.no_cache,
        )
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
        result = run_rows(rows, construction_client, answer_client, judge_client, args)
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
        "construction_provider": args.construction_provider,
        "construction_model": args.construction_model,
        "answer_provider": args.answer_provider,
        "answer_model": args.answer_model,
        "judge_provider": args.judge_provider if args.judge else None,
        "judge_model": args.judge_model if args.judge else None,
        "variants": [VARIANT],
        "task_candidate_k": args.task_candidate_k,
        "graph_batch_size": args.graph_batch_size,
        "max_facets": args.max_facets,
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "question_types": dict(question_types),
        "results": [result],
    }
    print_summary(args.answer_provider, args.answer_model, [result])
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[5]
BASELINE_DIR = Path(__file__).resolve().parents[1]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMClient, provider_config
from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex
from pipeline.external.temporal_grounding import format_temporal_grounding
from pipeline.external.time_role_selection import select_time_roles
from ours_scope_time_state.loader import CACHE_DIR, DATA_DIR, EVERMEMBENCH_DIR, GRAPH_OUTPUT_DIR, RESULT_DIR
from ours_scope_time_state.qa_probe import (
    BM25Index,
    gold_event_ids,
    group_key,
    load_graph_documents,
    qa_query_text,
)
from ours_scope_time_state.staged import STSGraphEvidenceIndex


TASK_ORDER = ("F_SH", "F_MH", "F_TP", "MA_C", "MA_P", "MA_U", "P_Style", "P_Skill", "P_Title")
PROMPTS_PATH = BASELINE_DIR / "common/official_eval/prompts.yaml"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small EverMemBench QA evaluation over a built topic graph.")
    parser.add_argument("--topic", default="01")
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument("--graph-dir", type=Path, default=GRAPH_OUTPUT_DIR / "evermembench_topic_graph_v2_state_merge/01")
    parser.add_argument("--limit-per-task", type=int, default=5, help="Rows per task; 0 means all available rows.")
    parser.add_argument(
        "--task-prefixes",
        default="",
        help="Comma-separated task prefixes to evaluate, e.g. P_Style,P_Skill,P_Title. Empty means all tasks.",
    )
    parser.add_argument("--question-type", choices=("all", "open_ended", "multiple_choice"), default="all")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-event-chars", type=int, default=900)
    parser.add_argument("--graph-expansion", choices=("sts", "none"), default="sts")
    parser.add_argument("--scope-routing", choices=("sts", "none"), default="sts")
    parser.add_argument("--scope-top-k", type=int, default=4)
    parser.add_argument("--scope-types", default="group,person")
    parser.add_argument(
        "--state-final-top",
        type=int,
        default=16,
        help="Number of StateFacets directly retained by the unified STS expansion.",
    )
    parser.add_argument("--max-context-events", type=int, default=40)
    parser.add_argument(
        "--time-role-selector",
        choices=("llm", "none"),
        default="llm",
        help="Question-only time-role routing for Event reranking and StateFacet selection.",
    )
    parser.add_argument(
        "--temporal-grounding",
        choices=("question-only", "none"),
        default="question-only",
        help="Deterministically ground relative time from selected graph evidence; none is the ablation.",
    )
    parser.add_argument("--embedding-retrieval", choices=("none", "hybrid"), default="hybrid")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument(
        "--embedding-targets",
        default="event,scope",
        help="Comma-separated hybrid targets: event,state,scope.",
    )
    parser.add_argument(
        "--embedding-cache",
        type=Path,
        default=CACHE_DIR / "embedding_cache.evermembench_qa_eval.json",
    )
    parser.add_argument("--embedding-batch-size", type=int, default=24)
    parser.add_argument(
        "--embedding-candidate-k",
        type=int,
        default=32,
        help="Number of independent BM25 and dense candidates retained per retrieval stage.",
    )
    parser.add_argument("--embedding-base-url", default=None)
    parser.add_argument(
        "--include-options-in-query",
        action="store_true",
        help="Append multiple-choice option text to retrieval queries.",
    )
    parser.add_argument("--prompts-path", type=Path, default=PROMPTS_PATH)
    parser.add_argument("--answer-provider", choices=("openai", "deepseek", "local"), default="openai")
    parser.add_argument("--answer-model", default="gpt-4o-mini")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek", "local"), default="deepseek")
    parser.add_argument("--judge-model", default="deepseek-v4-flash")
    parser.add_argument("--answer-workers", type=int, default=4)
    parser.add_argument("--judge-workers", type=int, default=4)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULT_DIR
        / "evermembench_topic_graph_v2_state_merge/qa_eval_gpt4omini_5_per_task_deepseek_v4_flash_judge.sts_scope_first_graph_expansion_top10_max40_question_query.json",
    )
    parser.add_argument(
        "--answer-cache",
        type=Path,
        default=CACHE_DIR / "evermembench_topic_graph_v2_state_merge/llm_cache.qa_eval.answer.gpt4omini.official_prompt.json",
    )
    parser.add_argument(
        "--judge-cache",
        type=Path,
        default=CACHE_DIR / "evermembench_topic_graph_v2_state_merge/llm_cache.qa_eval.judge.deepseek_v4_flash.json",
    )
    return parser.parse_args()


def select_qa_items(items: Sequence[Mapping[str, Any]], limit_per_task: int) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        prefix = group_key(str(item.get("id") or ""))
        if prefix in TASK_ORDER:
            grouped[prefix].append(dict(item))
    selected: List[Dict[str, Any]] = []
    for prefix in TASK_ORDER:
        selected.extend(grouped[prefix] if limit_per_task <= 0 else grouped[prefix][:limit_per_task])
    return selected


def question_type(item: Mapping[str, Any]) -> str:
    options = item.get("options")
    if isinstance(options, Mapping) and options:
        return "multiple_choice"
    return "open_ended"


def filter_by_question_type(items: Sequence[Dict[str, Any]], question_type_filter: str) -> List[Dict[str, Any]]:
    if question_type_filter == "all":
        return list(items)
    return [item for item in items if question_type(item) == question_type_filter]


def format_options(item: Mapping[str, Any]) -> str:
    options = item.get("options")
    if not isinstance(options, Mapping):
        return ""
    return "\n".join(f"{key}. {options[key]}" for key in sorted(options))


def load_answer_client(provider: str, model_override: str, cache_path: Path, use_cache: bool) -> LLMClient:
    api_key, model, api_base = provider_config(provider)
    return LLMClient(provider, model_override or model, api_key, api_base, cache_path, use_cache)


def parse_scope_types(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_embedding_targets(value: str) -> set[str]:
    allowed = {"event", "state", "scope"}
    targets = {part.strip() for part in value.split(",") if part.strip()}
    unknown = targets - allowed
    if unknown:
        raise ValueError(f"unknown embedding targets: {sorted(unknown)}; allowed={sorted(allowed)}")
    return targets


def parse_task_prefixes(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def scope_type_policy_for_question(item: Mapping[str, Any], configured_scope_types: Sequence[str]) -> Dict[str, Any]:
    del item
    configured = [str(scope_type) for scope_type in configured_scope_types if scope_type]
    return {
        "name": "configured_scope_types",
        "configured_scope_types": configured,
        "effective_scope_types": configured,
        "task_label_used": False,
        "reason": "one shared v2 scope policy for every question",
    }


def order_routed_scopes_for_policy(
    routed_scopes: Sequence[Mapping[str, Any]],
    scope_type_policy: Mapping[str, Any],
    top_k: int,
) -> List[Dict[str, Any]]:
    del scope_type_policy
    return [dict(scope) for scope in routed_scopes[:top_k]]


def truncate_text(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 20].rstrip() + " ...[truncated]"


def dedupe_list(values: Sequence[object]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def build_context(
    top_events: Sequence[str],
    doc_by_event: Mapping[str, str],
    max_event_chars: int,
    notes_by_event: Optional[Mapping[str, Sequence[str]]] = None,
    graph_preamble: str = "",
) -> str:
    blocks: List[str] = []
    if graph_preamble.strip():
        blocks.append(graph_preamble.strip())
    for rank, event_id in enumerate(top_events, start=1):
        doc = truncate_text(doc_by_event.get(event_id, ""), max_event_chars)
        notes = []
        if notes_by_event is not None:
            notes = [str(value) for value in notes_by_event.get(event_id, []) if value]
        note_text = f"\ngraph_trace={' | '.join(notes)}" if notes else ""
        blocks.append(f"[{rank}] event_id={event_id}{note_text}\n{doc}")
    return "\n\n".join(blocks)


def load_answer_prompts(path: Path) -> Dict[str, str]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load the official EverMemBench prompt config") from exc

    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    answer_config = config.get("answer") or {}
    prompts = {
        "multiple_choice": str(answer_config.get("multiple_choice") or ""),
        "open_ended": str(answer_config.get("open_ended") or ""),
    }
    missing = [name for name, prompt in prompts.items() if not prompt.strip()]
    if missing:
        raise ValueError(f"missing official answer prompt(s) in {path}: {', '.join(missing)}")
    return prompts


def answer_prompt(item: Mapping[str, Any], context: str, prompts: Mapping[str, str]) -> str:
    if question_type(item) == "multiple_choice":
        return prompts["multiple_choice"].format(context=context, question=item.get("Q"), options=format_options(item))
    return prompts["open_ended"].format(context=context, question=item.get("Q"))


def judge_system_prompt() -> str:
    return (
        "You are an expert grader that determines if answers to questions match a gold standard answer. "
        "Return strict JSON only."
    )


def judge_user_prompt(item: Mapping[str, Any], generated_answer: str) -> str:
    question = item.get("Q") or item.get("question") or ""
    gold_answer = item.get("A") or item.get("gold_answer") or ""
    return (
        "Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given:\n"
        "    (1) a question (about a multi-person group chat),\n"
        "    (2) a 'gold' (ground truth) answer,\n"
        "    (3) a generated answer\n"
        "which you will score as CORRECT/WRONG.\n\n"
        "The questions are about events, facts, or details mentioned in multi-person group chat conversations.\n"
        "The gold answer is usually a concise answer that includes the key information.\n\n"
        "The generated answer might be longer, but you should be generous with your grading -\n"
        "as long as it contains the same key information as the gold answer, it should be CORRECT.\n\n"
        "For time-related questions, the gold answer will be a specific date/time.\n"
        "The generated answer might use different formats (e.g., \"May 7th\" vs \"7 May\" vs \"2025-05-07\"),\n"
        "but as long as it refers to the same date/time, it should be CORRECT.\n\n"
        "For the specific window of date, a +/- 1 day difference is acceptable due to timezone processing variations.\n\n"
        "For multiple choice questions where the gold answer is a letter (A/B/C/D),\n"
        "the generated answer should match exactly to be CORRECT.\n\n"
        "Now grade this:\n"
        f"Question: {question}\n"
        f"Gold answer: {gold_answer}\n"
        f"Generated answer: {generated_answer}\n\n"
        "First, provide a short (one sentence) explanation of your reasoning,\n"
        "then finish with CORRECT or WRONG.\n"
        "Do NOT include both CORRECT and WRONG in your response.\n\n"
        "Return the label in JSON format with the key \"label\": {\"label\": \"CORRECT\"} or {\"label\": \"WRONG\"}.\n"
        "You may include a short \"rationale\" field."
    )


def parse_mc_answer(value: Any) -> str:
    response = str(value or "").strip().upper()
    if not response:
        return ""
    if len(response) == 1 and response in "ABCD":
        return response
    match = re.search(r"\b([ABCD])[.):,\s]", response)
    if match:
        return match.group(1)
    match = re.search(r"(?:ANSWER|CHOICE|OPTION|SELECT)[:\s]+([ABCD])\b", response)
    if match:
        return match.group(1)
    if response[0] in "ABCD" and (len(response) == 1 or not response[1].isalpha()):
        return response[0]
    if response[-1] in "ABCD" and (len(response) == 1 or not response[-2].isalpha()):
        return response[-1]
    return response


def normalize_judge_label(raw: Mapping[str, Any]) -> str:
    label = raw.get("label", "WRONG")
    if isinstance(label, Mapping):
        label = label.get("label", "WRONG")
    return str(label).strip().upper()


def accuracy_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    correct = sum(1 for row in rows if row.get("is_correct"))
    total = len(rows)
    return {"total": total, "correct": correct, "accuracy": correct / total if total else 0.0}


def summarize(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_task: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    by_type: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[str(row["task"])].append(row)
        by_type[str(row["question_type"])].append(row)

    return {
        "overall": accuracy_stats(rows),
        "by_task": {task: accuracy_stats(by_task[task]) for task in TASK_ORDER if task in by_task},
        "by_type": {key: accuracy_stats(value) for key, value in sorted(by_type.items())},
    }


def official_detailed_results(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    detailed: List[Dict[str, Any]] = []
    for row in rows:
        detailed.append(
            {
                "question_id": row["id"],
                "question": row["question"],
                "question_type": row["question_type"],
                "golden_answer": row["gold_answer"],
                "generated_answer": row["generated_answer"],
                "is_correct": bool(row["is_correct"]),
                "metadata": {
                    "task": row["task"],
                    "parsed_answer": row.get("parsed_answer"),
                    "judge_label": row.get("judge_label"),
                    "generated_evidence_event_ids": row.get("generated_evidence_event_ids", []),
                    "seed_events": row.get("seed_events", []),
                    "top_events": row.get("top_events", []),
                    "graph_expansion_trace": row.get("graph_expansion_trace", {}),
                    "retrieval_diagnostics": row.get("retrieval_diagnostics", {}),
                },
            }
        )
    return detailed


def retrieval_diagnostics(item: Mapping[str, Any], top_events: Sequence[str]) -> Dict[str, Any]:
    gold = gold_event_ids(item)
    ranked = [str(event_id) for event_id in top_events]
    hits = [event_id for event_id in ranked if event_id in gold]
    first_rank: Optional[int] = None
    for rank, event_id in enumerate(ranked, start=1):
        if event_id in gold:
            first_rank = rank
            break
    return {
        "gold_count": len(gold),
        "gold_hit_at_k": bool(hits),
        "gold_hit_count_at_k": len(hits),
        "gold_recall_at_k": len(hits) / max(1, len(gold)),
        "first_gold_rank": first_rank,
        "gold_hits_at_k": hits,
    }


def search_event_candidates(
    bm25_index: BM25Index,
    embedding_index: Optional[OpenAIEmbeddingIndex],
    query: str,
    top_k: int,
    *,
    allowed_event_ids: Optional[Sequence[str]] = None,
    embedding_candidate_k: int = 32,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    candidate_limit = max(top_k, int(embedding_candidate_k or 0))
    lexical_hits = bm25_index.search(
        query,
        candidate_limit,
        allowed_doc_ids=allowed_event_ids,
    )
    for rank, hit in enumerate(lexical_hits, start=1):
        event_id = str(hit.event_id)
        rows[event_id] = {
            "event_id": event_id,
            "lexical_score": float(hit.score),
            "lexical_rank": rank,
            "embedding_score": 0.0,
            "embedding_rank": None,
        }
    embedding_hits: Sequence[Any] = []
    if embedding_index is not None:
        embedding_hits = embedding_index.search(
            query,
            candidate_limit,
            allowed_doc_ids=allowed_event_ids,
        )
        for rank, hit in enumerate(
            embedding_hits,
            start=1,
        ):
            row = rows.setdefault(
                str(hit.doc_id),
                {
                    "event_id": str(hit.doc_id),
                    "lexical_score": 0.0,
                    "lexical_rank": None,
                    "embedding_score": 0.0,
                    "embedding_rank": None,
                },
            )
            row["embedding_score"] = max(float(hit.score), 0.0)
            row["embedding_rank"] = rank
    for row in rows.values():
        row["score"] = round(float(row["lexical_score"]) + 8.0 * float(row["embedding_score"]), 6)
        if row.get("lexical_rank") is not None and row.get("embedding_rank") is not None:
            row["retrieval_source"] = "hybrid"
        elif row.get("embedding_rank") is not None:
            row["retrieval_source"] = "embedding"
        else:
            row["retrieval_source"] = "bm25"
    ranked_rows = sorted(
        rows.values(),
        key=lambda row: (
            -float(row.get("score") or 0.0),
            row.get("lexical_rank") if row.get("lexical_rank") is not None else 10**9,
            row.get("embedding_rank") if row.get("embedding_rank") is not None else 10**9,
            str(row.get("event_id") or ""),
        ),
    )
    return ranked_rows, {
        "method": "bm25_embedding_union" if embedding_index is not None else "bm25",
        "candidate_limit_per_retriever": candidate_limit,
        "lexical_candidate_count": len(lexical_hits),
        "embedding_candidate_count": len(embedding_hits),
        "union_candidate_count": len(ranked_rows),
        "top_scores": ranked_rows[:20],
    }


def rerank_event_candidates_by_time(
    candidates: Sequence[Mapping[str, Any]],
    graph_evidence: Optional[STSGraphEvidenceIndex],
    time_roles: Sequence[str],
    top_k: int,
) -> tuple[List[str], List[Dict[str, Any]]]:
    selected_roles = {str(role) for role in time_roles if role}
    reranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        event_id = str(candidate.get("event_id") or "")
        profile = graph_evidence.event_time_profile(event_id) if graph_evidence is not None else {
            "time_roles": [],
            "time_values": [],
            "time_ids": [],
            "current_state_facet_ids": [],
        }
        event_roles = {str(role) for role in profile.get("time_roles", []) if role}
        matched_roles = sorted(selected_roles.intersection(event_roles))
        time_role_score = 0.0
        if selected_roles:
            time_role_score = 2.0 + 0.5 * len(matched_roles) if matched_roles else -0.5
        row = dict(candidate)
        row.update(
            {
                "base_retrieval_score": round(float(candidate.get("score") or 0.0), 6),
                "selected_time_roles": sorted(selected_roles),
                "event_time_roles": list(profile.get("time_roles", [])),
                "matched_time_roles": matched_roles,
                "time_role_score": round(time_role_score, 4),
                "time_values": list(profile.get("time_values", [])),
                "time_ids": list(profile.get("time_ids", [])),
                "current_state_facet_ids": list(profile.get("current_state_facet_ids", [])),
                "score": round(float(candidate.get("score") or 0.0) + time_role_score, 6),
            }
        )
        reranked.append(row)
    reranked.sort(
        key=lambda row: (
            -float(row.get("score") or 0.0),
            row.get("lexical_rank") if row.get("lexical_rank") is not None else 10**9,
            row.get("embedding_rank") if row.get("embedding_rank") is not None else 10**9,
            str(row.get("event_id") or ""),
        )
    )
    selected = reranked[:top_k]
    return [str(row["event_id"]) for row in selected], reranked


def run_answer(
    item: Mapping[str, Any],
    index: BM25Index,
    embedding_event_index: Optional[OpenAIEmbeddingIndex],
    doc_ids: Sequence[str],
    doc_by_event: Mapping[str, str],
    graph_evidence: Optional[STSGraphEvidenceIndex],
    answer_client: LLMClient,
    answer_prompts: Mapping[str, str],
    top_k: int,
    max_event_chars: int,
    include_options_in_query: bool,
    graph_expansion: str,
    scope_routing: str,
    scope_top_k: int,
    scope_types: Sequence[str],
    state_final_top: int,
    max_context_events: int,
    time_role_selector: str,
    temporal_grounding: str,
    embedding_candidate_k: int,
) -> Dict[str, Any]:
    retrieval_include_options = bool(include_options_in_query)
    query_text = qa_query_text(item, include_options=retrieval_include_options)
    scope_route_query = str(item.get("Q") or "")
    expansion_query = query_text
    scope_type_policy = scope_type_policy_for_question(item, scope_types)
    effective_scope_types = [str(scope_type) for scope_type in scope_type_policy["effective_scope_types"]]
    routed_scopes: List[Dict[str, Any]] = []
    scoped_event_ids: set[str] = set()
    scoped_doc_ids: List[str] = []
    if scope_routing == "sts":
        if graph_evidence is None:
            raise ValueError("scope_routing=sts requires STSGraphEvidenceIndex")
        routed_scopes = graph_evidence.route_scopes(scope_route_query, scope_top_k, effective_scope_types)
        routed_scopes = order_routed_scopes_for_policy(routed_scopes, scope_type_policy, scope_top_k)
        scoped_event_ids = graph_evidence.events_for_scopes([str(scope["scope_id"]) for scope in routed_scopes])
        scoped_doc_ids = [event_id for event_id in doc_ids if event_id in scoped_event_ids]
    event_candidates, seed_search_trace = search_event_candidates(
        index,
        embedding_event_index,
        query_text,
        top_k,
        allowed_event_ids=scoped_doc_ids or None,
        embedding_candidate_k=embedding_candidate_k,
    )
    time_role_selection: Dict[str, Any] = (
        select_time_roles(scope_route_query, answer_client, time_role_selector)
        if graph_expansion == "sts"
        else {
            "time_roles": [],
            "source": "not_used_graph_expansion_none",
            "question": scope_route_query,
        }
    )
    seed_events, time_rerank_trace = rerank_event_candidates_by_time(
        event_candidates,
        graph_evidence,
        time_role_selection["time_roles"],
        top_k,
    )
    seed_retrieval_trace: Dict[str, Any] = {
        "query": query_text,
        "option_text_used": retrieval_include_options,
        "requested_include_options_in_query": bool(include_options_in_query),
        **seed_search_trace,
        "time_rerank": time_rerank_trace[:20],
    }
    scope_trace = {
        "mode": scope_routing,
        "route_query": scope_route_query,
        "scope_type_policy": scope_type_policy,
        "effective_scope_types": effective_scope_types,
        "scope_order_policy": "score_order",
        "routed_scopes": routed_scopes,
        "scoped_event_count": len(scoped_event_ids),
    }
    graph_trace: Dict[str, Any] = {
        "mode": "none",
        "pipeline_order": ["scope_routing", "event_candidate_retrieval", "time_role_selection", "event_time_rerank"],
        "seed_event_ids": seed_events,
        "scope_routing": scope_trace,
        "seed_retrieval": seed_retrieval_trace,
    }
    notes_by_event: Dict[str, List[str]] = {}
    expanded_evidence: Any = None
    temporal_grounding_rows: List[Dict[str, Any]] = []
    if graph_expansion == "sts":
        if graph_evidence is None:
            raise ValueError("graph_expansion=sts requires STSGraphEvidenceIndex")
        expanded_evidence = graph_evidence.expand(
            item,
            seed_events,
            include_options_in_query=retrieval_include_options,
            state_search_k=state_final_top,
            max_context_events=max_context_events,
            query_text=expansion_query,
            scope_ids=[str(scope["scope_id"]) for scope in routed_scopes] if scope_routing == "sts" else None,
            time_roles=time_role_selection["time_roles"],
        )
        top_events = expanded_evidence.event_ids
        notes_by_event = expanded_evidence.notes_by_event
        scope_lines = [
            "- "
            + "; ".join(
                [
                    f"rank={rank}",
                    f"scope_id={scope.get('scope_id')}",
                    f"type={scope.get('scope_type')}",
                    f"label={scope.get('label')}",
                    f"score={scope.get('score'):.4f}",
                    f"event_count={scope.get('event_count')}",
                ]
            )
            for rank, scope in enumerate(routed_scopes, start=1)
        ]
        state_lines = [f"- {line}" for line in expanded_evidence.state_summaries]
        relation_lines = [f"- {line}" for line in expanded_evidence.relation_summaries[:12]]
        if temporal_grounding == "question-only":
            temporal_grounding_rows = graph_evidence.temporal_grounding_rows(
                scope_route_query,
                top_events,
                time_role_selection["time_roles"],
            )
        temporal_lines = [
            "- " + format_temporal_grounding(row, include_resolved=True)
            for row in temporal_grounding_rows
        ]
        preamble_parts = []
        if scope_lines:
            preamble_parts.append("[STS_SCOPE_ROUTING]\n" + "\n".join(scope_lines))
        if temporal_lines:
            preamble_parts.append("[STS_TEMPORAL_GROUNDING]\n" + "\n".join(temporal_lines))
        if state_lines:
            preamble_parts.append("[STS_GRAPH_STATE_FACETS]\n" + "\n".join(state_lines))
        if relation_lines:
            preamble_parts.append("[STS_GRAPH_RELATIONS]\n" + "\n".join(relation_lines))
        graph_preamble = "\n\n".join(preamble_parts)
        graph_trace = {
            "mode": "sts",
            "pipeline_order": [
                "scope_routing",
                "event_candidate_retrieval",
                "time_role_selection",
                "event_time_rerank",
                "statefacet_validity_selection",
                "graph_expansion",
                "temporal_grounding",
            ],
            **expanded_evidence.trace(),
            "scope_routing": scope_trace,
            "seed_retrieval": seed_retrieval_trace,
            "time_role_selection": time_role_selection,
            "temporal_grounding": {
                "mode": temporal_grounding,
                "input_boundary": [
                    "question_text",
                    "selected_graph_events",
                    "claim_time_values",
                    "source_event_timestamps",
                ],
                "uses_task_labels": False,
                "uses_gold": False,
                "rows": temporal_grounding_rows,
            },
        }
    else:
        top_events = seed_events
        graph_preamble = ""
    context = build_context(
        top_events,
        doc_by_event,
        max_event_chars,
        notes_by_event=notes_by_event,
        graph_preamble=graph_preamble,
    )
    raw_answer = answer_client.complete_text("", answer_prompt(item, context, answer_prompts)).strip()
    if question_type(item) == "multiple_choice":
        answer = parse_mc_answer(raw_answer)
    else:
        answer = raw_answer
    return {
        "id": item.get("id"),
        "task": group_key(str(item.get("id") or "")),
        "question_type": question_type(item),
        "question": item.get("Q"),
        "gold_answer": item.get("A"),
        "generated_answer": answer,
        "generated_raw": raw_answer,
        "generated_evidence_event_ids": [],
        "seed_events": seed_events,
        "top_events": top_events,
        "graph_expansion_trace": graph_trace,
        "retrieval_diagnostics": retrieval_diagnostics(item, top_events),
    }


def judge_row(row: Mapping[str, Any], judge_client: LLMClient) -> Dict[str, Any]:
    if row["question_type"] == "multiple_choice":
        parsed = parse_mc_answer(row["generated_answer"])
        gold = parse_mc_answer(row["gold_answer"])
        return {**row, "parsed_answer": parsed, "judge_label": None, "judge_raw": None, "is_correct": parsed == gold}

    raw_judge = judge_client.complete_json(
        judge_system_prompt(),
        judge_user_prompt(row, str(row["generated_answer"])),
    )
    label = normalize_judge_label(raw_judge)
    return {
        **row,
        "parsed_answer": None,
        "judge_label": label,
        "judge_raw": raw_judge,
        "is_correct": label == "CORRECT",
    }


def run_parallel(items: Sequence[Mapping[str, Any]], workers: int, fn) -> List[Dict[str, Any]]:
    if workers <= 1:
        return [fn(item) for item in items]
    results: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fn, item): index for index, item in enumerate(items)}
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
            print(f"  done {len(results)}/{len(items)}", flush=True)
    return [results[index] for index in range(len(items))]


def main() -> None:
    args = parse_args()
    load_dotenv()

    qa_path = args.qa_path or DATA_DIR / args.topic / f"qa_{args.topic}.json"
    qa_items = json.loads(qa_path.read_text(encoding="utf-8"))
    task_prefixes = parse_task_prefixes(args.task_prefixes)
    selected_all = select_qa_items(qa_items, args.limit_per_task)
    if task_prefixes:
        selected_all = [item for item in selected_all if group_key(str(item.get("id") or "")) in set(task_prefixes)]
    selected = filter_by_question_type(selected_all, args.question_type)
    expected_total = None
    if args.limit_per_task > 0 and not task_prefixes:
        expected_total = (
            len(selected_all)
            if args.question_type == "all"
            else sum(1 for item in selected_all if question_type(item) == args.question_type)
        )
    if expected_total is not None and len(selected) != expected_total:
        counts = Counter(group_key(str(item.get("id") or "")) for item in selected)
        raise RuntimeError(f"selected {len(selected)} rows, expected {expected_total}; counts={dict(counts)}")
    answer_prompts = load_answer_prompts(args.prompts_path)
    scope_types = parse_scope_types(args.scope_types)
    embedding_targets = parse_embedding_targets(args.embedding_targets)

    doc_ids, documents, _ = load_graph_documents(args.graph_dir, "graph_context")
    doc_by_event = dict(zip(doc_ids, documents))
    index = BM25Index(doc_ids, documents)
    graph_evidence = (
        STSGraphEvidenceIndex.load(args.graph_dir)
        if args.graph_expansion == "sts" or args.scope_routing == "sts"
        else None
    )
    embedding_event_index: Optional[OpenAIEmbeddingIndex] = None
    if args.embedding_retrieval == "hybrid":
        embedding_namespace = f"evermembench:{args.graph_dir}"
        if "event" in embedding_targets:
            embedding_event_index = OpenAIEmbeddingIndex(
                doc_ids,
                documents,
                model=args.embedding_model,
                cache_path=args.embedding_cache,
                namespace=f"{embedding_namespace}:events",
                batch_size=args.embedding_batch_size,
                base_url=args.embedding_base_url,
            )
        if graph_evidence is not None:
            graph_evidence.enable_embedding_retrieval(
                model=args.embedding_model,
                cache_path=args.embedding_cache,
                namespace=f"{embedding_namespace}:graph",
                batch_size=args.embedding_batch_size,
                base_url=args.embedding_base_url,
                targets=embedding_targets - {"event"},
                candidate_k=args.embedding_candidate_k,
            )

    answer_client = load_answer_client(args.answer_provider, args.answer_model, args.answer_cache, not args.no_cache)
    judge_client = load_answer_client(args.judge_provider, args.judge_model, args.judge_cache, not args.no_cache)

    print(
        f"EverMemBench QA eval topic={args.topic} rows={len(selected)} "
        f"task_prefixes={task_prefixes or 'all'} "
        f"question_type={args.question_type} "
        f"answer={args.answer_provider}/{args.answer_model} judge={args.judge_provider}/{args.judge_model} "
        f"top_k={args.top_k} scope_routing={args.scope_routing} scope_top_k={args.scope_top_k} "
        f"graph_expansion={args.graph_expansion} "
        f"state_final_top={args.state_final_top} "
        f"max_context_events={args.max_context_events} "
        f"time_role_selector={args.time_role_selector} "
        f"temporal_grounding={args.temporal_grounding} "
        f"graph_retriever=sts_generic_graphrag "
        f"embedding_retrieval={args.embedding_retrieval} embedding_model={args.embedding_model if args.embedding_retrieval == 'hybrid' else 'none'} "
        f"embedding_targets={sorted(embedding_targets) if args.embedding_retrieval == 'hybrid' else []} "
        f"embedding_candidate_k={args.embedding_candidate_k if args.embedding_retrieval == 'hybrid' else 0} "
        f"include_options_in_query={args.include_options_in_query}",
        flush=True,
    )
    print("Answering...", flush=True)
    answered = run_parallel(
        selected,
        args.answer_workers,
        lambda item: run_answer(
            item,
            index,
            embedding_event_index,
            doc_ids,
            doc_by_event,
            graph_evidence,
            answer_client,
            answer_prompts,
            args.top_k,
            args.max_event_chars,
            args.include_options_in_query,
            args.graph_expansion,
            args.scope_routing,
            args.scope_top_k,
            scope_types,
            args.state_final_top,
            args.max_context_events,
            args.time_role_selector,
            args.temporal_grounding,
            args.embedding_candidate_k,
        ),
    )
    print("Judging...", flush=True)
    judged = run_parallel(answered, args.judge_workers, lambda row: judge_row(row, judge_client))
    summary = summarize(judged)

    output = {
        "total_questions": summary["overall"]["total"],
        "correct": summary["overall"]["correct"],
        "accuracy": summary["overall"]["accuracy"],
        "accuracy_by_type": summary["by_type"],
        "detailed_results": official_detailed_results(judged),
        "topic_id": args.topic,
        "qa_path": str(qa_path),
        "graph_dir": str(args.graph_dir),
        "selection": {
            "task_order": list(TASK_ORDER),
            "task_prefixes": task_prefixes,
            "limit_per_task": args.limit_per_task,
            "question_type": args.question_type,
        },
        "retrieval": {
            "mode": "graph_context",
            "scope_routing": args.scope_routing,
            "scope_top_k": args.scope_top_k,
            "scope_types": scope_types,
            "scope_type_policy": "one_shared_v2_scope_policy_without_task_labels",
            "graph_expansion": args.graph_expansion,
            "include_options_in_query": args.include_options_in_query,
            "top_k": args.top_k,
            "state_final_top": args.state_final_top,
            "max_context_events": args.max_context_events,
            "time_role_selector": args.time_role_selector,
            "temporal_grounding": args.temporal_grounding,
            "graph_retriever": "sts_generic_graphrag",
            "embedding_retrieval": args.embedding_retrieval,
            "embedding_model": args.embedding_model if args.embedding_retrieval == "hybrid" else None,
            "embedding_targets": sorted(embedding_targets) if args.embedding_retrieval == "hybrid" else [],
            "embedding_cache": str(args.embedding_cache) if args.embedding_retrieval == "hybrid" else None,
            "embedding_candidate_k": args.embedding_candidate_k if args.embedding_retrieval == "hybrid" else 0,
            "task_label_used_for_retrieval": False,
            "option_text_used_for_sts_retrieval": False,
            "max_event_chars": args.max_event_chars,
        },
        "answer_model": {
            "provider": args.answer_provider,
            "model": args.answer_model,
            "prompt_source": str(args.prompts_path),
        },
        "judge_model": {"provider": args.judge_provider, "model": args.judge_model, "scope": "open_ended_only"},
        "summary": summary,
        "rows": judged,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()

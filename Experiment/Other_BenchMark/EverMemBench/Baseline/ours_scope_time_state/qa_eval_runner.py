from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
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
FMH_SELECTOR_PROMPT_CANDIDATE_CAP = 32
FMH_SELECTOR_EVIDENCE_CHARS = 220


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small EverMemBench QA evaluation over a built topic graph.")
    parser.add_argument("--topic", default="01")
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument("--graph-dir", type=Path, default=GRAPH_OUTPUT_DIR / "evermembench_topic_graph_llm_v1/01")
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
    parser.add_argument("--temporal-interval", choices=("auto", "none"), default="none")
    parser.add_argument("--temporal-top-k", type=int, default=50)
    parser.add_argument(
        "--time-selector",
        choices=("llm", "none"),
        default="llm",
        help="Select concrete graph time candidates with an LLM before deterministic date arithmetic.",
    )
    parser.add_argument("--fmh-endpoint-selector", choices=("llm", "none"), default="none")
    parser.add_argument("--fmh-endpoint-candidates", type=int, default=160)
    parser.add_argument("--embedding-retrieval", choices=("none", "hybrid"), default="none")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument(
        "--embedding-targets",
        default="event,state,scope",
        help="Comma-separated hybrid targets: event,state,scope,temporal,effort.",
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
        help="Maximum BM25 candidates per retrieval stage to rerank with embeddings.",
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
        / "evermembench_topic_graph_llm_v1/qa_eval_gpt4omini_5_per_task_deepseek_v4_flash_judge.sts_scope_first_graph_expansion_top10_max40_question_query.json",
    )
    parser.add_argument(
        "--answer-cache",
        type=Path,
        default=CACHE_DIR / "evermembench_topic_graph_llm_v1/llm_cache.qa_eval.answer.gpt4omini.official_prompt.json",
    )
    parser.add_argument(
        "--judge-cache",
        type=Path,
        default=CACHE_DIR / "evermembench_topic_graph_llm_v1/llm_cache.qa_eval.judge.deepseek_v4_flash.json",
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
    allowed = {"event", "state", "scope", "temporal", "effort"}
    targets = {part.strip() for part in value.split(",") if part.strip()}
    unknown = targets - allowed
    if unknown:
        raise ValueError(f"unknown embedding targets: {sorted(unknown)}; allowed={sorted(allowed)}")
    return targets


def parse_task_prefixes(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


PROFILE_SCOPE_NEGATIVE_RE = re.compile(
    r"\b(how long|which of the following .*processing|which of the following .*correct|"
    r"correct processing logic|processing logic is correct|"
    r"according to system regulations|what is the correct|without waiting|start working on it without|"
    r"can't delay .* any longer|according to our team's rules|where should .* uploaded|quickly check|"
    r"go through a change request|what do you think of this solution)\b",
    re.I,
)
PROFILE_SCOPE_ACTOR_RE = re.compile(
    r"\bI\s*\([^)]+\)|\bme\s*\([^)]+\)|\bI(?:'m| am)\b|\bmy\b|\bmy manager\b|\bmy boss\b|\bmy key clients\b|"
    r"\bmy presentation\b|\bmy remarks\b|\bmy response\b|\bmy team\b|\bwe\b|\bour team's\b|"
    r"\bcould you\s*\([^)]+\)\s*please\b|\basked me\b|\bconsulted me\b",
    re.I,
)
PROFILE_SCOPE_REQUEST_RE = re.compile(
    r"\b(what aspects should I focus|what suggestions should I|what should I suggest|"
    r"what are your suggestions|what would you suggest|do you have any suggestions|"
    r"how would you suggest|what kind of .* should I propose|what is my most appropriate next step|"
    r"what is the most efficient and suitable method|which of the following solutions is most worth adopting|"
    r"general optimization strategies .* share|asked me .* think of a way|how can I quickly implement|"
    r"how (?:should I|I should) .*?(?:prepare|respond|approach|integrate|implement)|how should I prepare (?:my )?"
    r"(?:remarks|presentation|response|integration plan)|how should I respond|from what angles should I approach|"
    r"from what angle should I approach|how would you approach this|under what circumstances|"
    r"identify the key aspects|brainstorm some ideas|brainstorm my entry points|organize my thoughts|"
    r"plan what work we can start)\b|"
    r"\b(draft|write|summari[sz]e|prepare|brainstorm|identify|propose|suggest|respond|post|outline|organize|compile)\b.*"
    r"\b(group message|message|reply|summary|outline|response|remarks|presentation|follow-up plan|"
    r"work plan|sharing outline|deployment plan|integration plan|implementation plan|technical considerations|"
    r"proposal|criteria|ideas|suggestions|professional responsibilities|progress update|report|speech draft|"
    r"speech|talking points|key points|sharing points|work priorities|checklist|thoughts)\b",
    re.I,
)


def scope_type_policy_for_question(item: Mapping[str, Any], configured_scope_types: Sequence[str]) -> Dict[str, Any]:
    configured = [str(scope_type) for scope_type in configured_scope_types if scope_type]
    if "task_object" not in configured:
        return {
            "name": "configured_scope_types",
            "configured_scope_types": configured,
            "effective_scope_types": configured,
            "task_object_demoted": False,
            "task_label_used": False,
            "reason": "task_object_not_configured",
        }

    question = str(item.get("Q") or "")
    negative_match = PROFILE_SCOPE_NEGATIVE_RE.search(question)
    actor_match = PROFILE_SCOPE_ACTOR_RE.search(question)
    request_match = PROFILE_SCOPE_REQUEST_RE.search(question)
    if actor_match and request_match and not negative_match:
        effective = [scope_type for scope_type in configured if scope_type != "task_object"]
        return {
            "name": "question_semantic_profile_scope",
            "configured_scope_types": configured,
            "effective_scope_types": effective,
            "task_object_demoted": True,
            "task_label_used": False,
            "reason": "profile_or_advice_request_centers_on_person_group_not_task_object",
            "matched_actor_cue": actor_match.group(0),
            "matched_request_cue": request_match.group(0),
        }

    return {
        "name": "question_semantic_scope",
        "configured_scope_types": configured,
        "effective_scope_types": configured,
        "task_object_demoted": False,
        "task_label_used": False,
        "reason": "question_does_not_match_profile_scope_pattern",
        "blocked_by_negative_cue": negative_match.group(0) if negative_match else None,
    }


def order_routed_scopes_for_policy(
    routed_scopes: Sequence[Mapping[str, Any]],
    scope_type_policy: Mapping[str, Any],
    top_k: int,
) -> List[Dict[str, Any]]:
    scopes = [dict(scope) for scope in routed_scopes]
    if not scopes or not scope_type_policy.get("task_object_demoted"):
        return scopes
    if scope_type_policy.get("name") != "question_semantic_profile_scope":
        return scopes

    type_priority = {"person": 0, "group": 1}
    scopes.sort(
        key=lambda scope: (
            type_priority.get(str(scope.get("scope_type") or ""), 2),
            -float(scope.get("score") or 0.0),
            str(scope.get("scope_id") or ""),
        )
    )
    return scopes[:top_k]


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
                    "temporal_interval_trace": row.get("temporal_interval_trace", {}),
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


def search_seed_events(
    bm25_index: BM25Index,
    embedding_index: Optional[OpenAIEmbeddingIndex],
    query: str,
    top_k: int,
    *,
    allowed_event_ids: Optional[Sequence[str]] = None,
    embedding_candidate_k: int = 32,
) -> tuple[List[str], Dict[str, Any]]:
    allowed = {str(event_id) for event_id in allowed_event_ids or [] if event_id}
    rows: Dict[str, Dict[str, Any]] = {}
    for rank, hit in enumerate(bm25_index.search(query, max(top_k, top_k * 4)), start=1):
        event_id = str(hit.event_id)
        if allowed and event_id not in allowed:
            continue
        rows[event_id] = {
            "event_id": event_id,
            "lexical_score": float(hit.score),
            "lexical_rank": rank,
            "embedding_score": 0.0,
            "embedding_rank": None,
        }
        if len(rows) >= max(top_k, top_k * 2) and embedding_index is None:
            break
    candidate_limit = max(top_k, int(embedding_candidate_k or 0)) if embedding_candidate_k > 0 else len(rows)
    embedding_candidate_ids = list(rows)[:candidate_limit]
    if embedding_index is not None and embedding_candidate_ids:
        for rank, hit in enumerate(
            embedding_index.search(
                query,
                min(max(top_k * 4, top_k), len(embedding_candidate_ids)),
                allowed_doc_ids=embedding_candidate_ids,
                max_candidates=candidate_limit,
            ),
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
    )[:top_k]
    return [str(row["event_id"]) for row in ranked_rows], {
        "method": "bm25_embedding_hybrid" if embedding_index is not None else "bm25",
        "embedding_candidate_limit": candidate_limit if embedding_index is not None else 0,
        "embedding_candidate_count": len(embedding_candidate_ids) if embedding_index is not None else 0,
        "top_scores": ranked_rows[:20],
    }


def should_use_temporal_interval(item: Mapping[str, Any], mode: str) -> bool:
    if mode != "auto":
        return False
    question = str(item.get("Q") or "").lower()
    if parse_fmh_endpoints(item) is not None:
        return False
    if re.search(r"\b(workdays?|working days?|business days?|person-days?)\b", question):
        return False
    if "actually invested" in question or "were spent" in question:
        return False
    return bool(
        re.search(
            r"initiation to finalization|start to finish|from start|span from start|last from start|"
            r"start to delivery|start to the official release|how long did it take|how many days did it take|"
            r"how many days did .* take|how many days did .* last|days passed from|started .* until .* completed",
            question,
        )
    )


def should_use_fmh_long_interval(item: Mapping[str, Any], mode: str) -> bool:
    if mode != "auto":
        return False
    question = str(item.get("Q") or "").lower()
    if not ("how long" in question or "how many days" in question):
        return False
    return parse_fmh_endpoints(item) is not None


def should_use_effort_metric(item: Mapping[str, Any], mode: str) -> bool:
    if mode != "auto":
        return False
    question = str(item.get("Q") or "").lower()
    return bool(
        re.search(
            r"\b(workdays?|working days?|person-days?|man-days?|actual effort|actual work hours|planned effort|"
            r"spent|invested)\b",
            question,
        )
    )


def temporal_endpoint_queries(item: Mapping[str, Any]) -> List[Dict[str, str]]:
    question = " ".join(str(item.get("Q") or "").split())
    def clean_task_query(value: str) -> str:
        cleaned = re.sub(r"(?i)^in the .+? project,\s*", "", value).strip()
        cleaned = re.sub(r"(?i),?\s*led by [A-Z][A-Za-z ]+,\s*", " ", cleaned).strip()
        cleaned = re.sub(r"(?i),?\s*including .*$", "", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" ,")

    patterns = (
        r"(?i)\bhow many days did (.+?) take from initiation to finalization(?:\?|$)",
        r"(?i)\bhow many days did (.+?) take from start to finish(?:,|\?|$)",
        r"(?i)\bhow many days did (.+?) span from start to finish(?:\?|$)",
        r"(?i)\bhow many days did (.+?) last from start to finish(?:\?|$)",
        r"(?i)\bhow many days did it take for (.+?)(?:\?|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            query = clean_task_query(match.group(1))
            return [{"role": "task", "query": query}]
    return [{"role": "task", "query": question}]


def parse_iso_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        return None


def clean_fmh_evidence_query(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"(?i)\b(?:in|within|for) the [a-z][a-z \-]+? (?:project )?group\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bthe [a-z][a-z \-]+? (?:project )?group to\b", " to ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:was|were|is|are|has been|had been) (?:completed|developed|finalized|concluded|finished)\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bhow long did it take (?:for|before)\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bto start\b", " start ", cleaned)
    cleaned = re.sub(r"(?i)\bbefore\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ,")


def split_fmh_leading_group_context(question: str) -> tuple[str, str]:
    match = re.match(
        r"(?i)^in the ([a-z][a-z \-]+? (?:project )?group|[a-z][a-z \-]+? system chat),\s*(.+)$",
        question,
    )
    if not match:
        return "", question
    return match.group(1).strip(), match.group(2).strip()


def extract_fmh_group_context(text: str) -> str:
    patterns = (
        r"(?i)\b(?:in|within|for) the ([a-z][a-z \-]+? (?:project )?group)\b",
        r"(?i)\b(?:in|within|for) the ([a-z][a-z \-]+? system chat)\b",
        r"(?i)\bthe ([a-z][a-z \-]+? (?:project )?group) to\b",
        r"(?i)\bthe ([a-z][a-z \-]+? (?:project )?group) (?:start|begin|began|started|begins)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def fmh_group_query_terms(group_context: str) -> str:
    terms = re.sub(r"(?i)\bproject group\b", " ", group_context)
    terms = re.sub(r"(?i)\bgroup\b", " ", terms)
    terms = re.sub(r"(?i)\bsystem chat\b", " ", terms)
    terms = re.sub(r"(?i)\bchat\b", " ", terms)
    terms = re.sub(r"\s+", " ", terms)
    return terms.strip(" ,")


def fmh_endpoint_queries(text: str, leading_group_context: str = "") -> Dict[str, str]:
    scope_query = " ".join(part for part in (leading_group_context, text) if part).strip()
    evidence_query = clean_fmh_evidence_query(text) or scope_query
    group_context = leading_group_context or extract_fmh_group_context(text)
    group_terms = fmh_group_query_terms(group_context)
    word_count = len(re.findall(r"[A-Za-z0-9]+", evidence_query))
    lowered = evidence_query.lower()
    generic_endpoint = bool(re.search(r"\b(interview|notes?)\b", lowered))
    if group_terms and (
        (leading_group_context and word_count <= 8)
        or word_count <= 4
        or generic_endpoint
    ):
        evidence_query = f"{evidence_query} {group_terms}".strip()
    return {"scope_query": scope_query, "evidence_query": evidence_query, "group_context": group_context}


def should_inherit_fmh_leading_group(consequent: str, leading_group_context: str) -> bool:
    if not leading_group_context.strip():
        return False
    group_context = extract_fmh_group_context(consequent)
    if not group_context:
        return True
    return group_context.lower() in {"project group", "same project group"}


def parse_fmh_endpoints(item: Mapping[str, Any]) -> Optional[Dict[str, Dict[str, Any]]]:
    question = " ".join(str(item.get("Q") or "").split())
    leading_group_context, parse_question = split_fmh_leading_group_context(question)
    patterns = (
        r"(?i)(?:^|,\s*)after (.+?), how long did it take before (.+?)(?:\?|$)",
        r"(?i)(?:^|,\s*)after (.+?), how long did it take for (.+?)(?:\?|$)",
        r"(?i)(?:^|,\s*)after (.+?), how long did it take them to (.+?)(?:\?|$)",
        r"(?i)(?:^|,\s*)after (.+?), how long did it take to ((?:start|begin|commence) .+?)(?:\?|$)",
        r"(?i)\bhow long after (.+?) did (.+?)(?:\?|$)",
        r"(?i)(?:^|,\s*)after (.+?), how many days (?:passed|elapsed) before (.+?)(?:\?|$)",
    )
    antecedent = ""
    consequent = ""
    for pattern in patterns:
        match = re.search(pattern, parse_question)
        if match:
            antecedent = match.group(1).strip()
            consequent = match.group(2).strip()
            break
    if not antecedent or not consequent:
        return None
    antecedent_queries = fmh_endpoint_queries(antecedent, leading_group_context)
    consequent_leading_group = (
        leading_group_context if should_inherit_fmh_leading_group(consequent, leading_group_context) else ""
    )
    consequent_queries = fmh_endpoint_queries(consequent, consequent_leading_group)
    return {
        "antecedent": {
            "name": "antecedent",
            "scope_query": antecedent_queries["scope_query"],
            "evidence_query": antecedent_queries["evidence_query"],
            "leading_group_context": leading_group_context,
            "group_context": antecedent_queries["group_context"],
            "endpoint_kind": "end",
            "time_roles": ["completed_at", "finalized_at", "occurred_at"],
        },
        "consequent": {
            "name": "consequent",
            "scope_query": consequent_queries["scope_query"],
            "evidence_query": consequent_queries["evidence_query"],
            "group_context": consequent_queries["group_context"],
            "endpoint_kind": "start",
            "time_roles": ["started_at", "planned_for", "occurred_at"],
        },
    }


def fmh_endpoint_route_queries(endpoint: Mapping[str, Any]) -> Dict[str, str]:
    scope_query = str(endpoint.get("scope_query") or "")
    evidence_query = str(endpoint.get("evidence_query") or scope_query)
    leading_group_context = str(endpoint.get("leading_group_context") or "").strip()
    group_context = str(endpoint.get("group_context") or "").strip()
    route_query_parts = [scope_query]
    if group_context and group_context.lower() not in scope_query.lower():
        route_query_parts.append(group_context)
    route_query = " ".join(part for part in route_query_parts if part).strip() or evidence_query
    context_query = group_context or leading_group_context or route_query
    task_query = evidence_query or scope_query or route_query
    return {
        "route_query": route_query,
        "task_query": task_query,
        "context_query": context_query,
    }


def fmh_task_query_variants(task_query: str) -> List[str]:
    query = " ".join(str(task_query or "").split())
    if not query:
        return []
    variants: List[str] = []

    def add(value: str) -> None:
        normalized = " ".join(value.split()).strip(" \t\r\n'\"`.,:;!?")
        normalized = re.sub(r"^(?:the|a|an)\s+", "", normalized, flags=re.I)
        if normalized and normalized.lower() not in {item.lower() for item in variants}:
            variants.append(normalized)

    add(query)
    stripped = re.sub(
        r"(?i)^(?:start|begin|began|started|starting)\s+"
        r"(?:(?:to\s+)?(?:develop|build|implement|test|write|design)|"
        r"(?:developing|building|implementing|testing|writing|designing)|"
        r"(?:work|working)\s+on)\s+",
        "",
        query,
    )
    add(stripped)
    stripped = re.sub(
        r"\b(?:backend|front[- ]?end|frontend|server[- ]?side|client[- ]?side|mobile|web)\s+"
        r"(?:service|module|component|page|api|interface|system|application)\s+for\s+",
        "",
        query,
        flags=re.I,
    )
    add(stripped)
    stripped = re.sub(
        r"\b(?:service|module|component|page|api|interface|system|application)\s+for\s+",
        "",
        query,
        flags=re.I,
    )
    add(stripped)
    stripped = re.sub(
        r"\b(?:development|implementation|writing|drawing|design|research|verification|testing)\s+of\s+",
        "",
        query,
        flags=re.I,
    )
    add(stripped)

    for variant in list(variants):
        add(re.sub(r"(?i)\buser center module\b", "personal center page", variant))
        add(re.sub(r"(?i)\buser center\b", "personal center", variant))
        add(re.sub(r"(?i)\bpersonal center\b", "user center", variant))
        add(re.sub(r"(?i)\bhomepage dashboard\b", "workbench homepage", variant))
        add(re.sub(r"(?i)\bgroup leader\b", "team leader", variant))
        if re.search(r"(?i)\bworkbench\b", variant) and re.search(r"(?i)\bhomepage|dashboard\b", variant):
            add("workbench homepage")
            add("workbench homepage UI task")
    return variants[:8]


def select_fmh_endpoint_scopes(
    graph_evidence: STSGraphEvidenceIndex,
    endpoint: Mapping[str, Any],
    scope_top_k: int,
    scope_types: Sequence[str],
    max_groups: int,
) -> Dict[str, Any]:
    allowed_types = {str(scope_type) for scope_type in scope_types if scope_type}
    queries = fmh_endpoint_route_queries(endpoint)
    task_scope_limit = max(10, scope_top_k * 2) if "task_object" in allowed_types else 0
    task_query_variants = fmh_task_query_variants(queries["task_query"])
    task_scopes: List[Dict[str, Any]] = []
    seen_task_scope_ids: set[str] = set()
    if task_scope_limit > 0:
        per_variant_limit = max(6, scope_top_k)
        for variant in task_query_variants:
            variant_added = 0
            for scope in graph_evidence.route_scopes(variant, per_variant_limit, ["task_object"]):
                scope_id = str(scope.get("scope_id") or "")
                if not scope_id or scope_id in seen_task_scope_ids:
                    continue
                scope_copy = dict(scope)
                scope_copy["route_query_variant"] = variant
                task_scopes.append(scope_copy)
                seen_task_scope_ids.add(scope_id)
                variant_added += 1
                if variant_added >= per_variant_limit:
                    break
    has_explicit_group_context = bool(endpoint.get("group_context") or endpoint.get("leading_group_context"))
    group_scopes = (
        graph_evidence.route_scopes(queries["context_query"], max_groups, ["group"])
        if "group" in allowed_types and max_groups > 0 and has_explicit_group_context
        else []
    )
    has_explicit_person_name = bool(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", queries["route_query"]))
    person_scopes = (
        graph_evidence.route_scopes(queries["route_query"], 1, ["person"])
        if "person" in allowed_types and has_explicit_person_name
        else []
    )
    endpoint_scopes: List[Dict[str, Any]] = []
    seen_scope_ids: set[str] = set()
    for scope in [*task_scopes, *group_scopes, *person_scopes]:
        scope_id = str(scope.get("scope_id") or "")
        if not scope_id or scope_id in seen_scope_ids:
            continue
        endpoint_scopes.append(dict(scope))
        seen_scope_ids.add(scope_id)
    if not endpoint_scopes:
        endpoint_scopes = graph_evidence.route_scopes(queries["route_query"], scope_top_k, scope_types)
    return {
        **queries,
        "task_query_variants": task_query_variants,
        "task_scopes": task_scopes,
        "context_scopes": [*group_scopes, *person_scopes],
        "endpoint_scopes": endpoint_scopes,
        "selection_strategy": "fmh_group_context_then_task_object_grounding",
    }


def fmh_scoped_event_filter(
    graph_evidence: STSGraphEvidenceIndex,
    endpoint_scopes: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    task_object_scope_ids = [
        str(scope.get("scope_id") or "")
        for scope in endpoint_scopes
        if scope.get("scope_type") == "task_object" and scope.get("scope_id")
    ]
    context_scope_ids = [
        str(scope.get("scope_id") or "")
        for scope in endpoint_scopes
        if scope.get("scope_type") in {"group", "person", "project"} and scope.get("scope_id")
    ]
    all_scope_ids = [str(scope.get("scope_id") or "") for scope in endpoint_scopes if scope.get("scope_id")]
    task_events = graph_evidence.events_for_scopes(task_object_scope_ids) if task_object_scope_ids else set()
    context_events = graph_evidence.events_for_scopes(context_scope_ids) if context_scope_ids else set()
    all_events = graph_evidence.events_for_scopes(all_scope_ids) if all_scope_ids else set()
    strategy = "scope_union"
    event_ids = all_events
    if task_events and context_events:
        event_ids = task_events.union(context_events)
        strategy = "task_object_context_multichannel"
    elif task_events:
        event_ids = task_events
        strategy = "task_object_only"
    elif context_events:
        event_ids = context_events
        strategy = "context_scope_only"
    return {
        "event_ids": event_ids,
        "task_event_ids": task_events,
        "context_event_ids": context_events,
        "intersection_event_ids": task_events.intersection(context_events),
        "strategy": strategy,
        "task_object_scope_ids": task_object_scope_ids,
        "context_scope_ids": context_scope_ids,
        "all_scope_ids": all_scope_ids,
    }


def fmh_requires_same_person(question: str) -> bool:
    lowered = question.lower()
    return bool(
        re.search(
            r"colleague responsible|person responsible|responsible for this task|they started|them to start|their next independent",
            lowered,
        )
    )


def fmh_next_independent_task_question(question: str) -> bool:
    lowered = question.lower()
    return bool(re.search(r"\bnext independent task\b|\bnext task\b|\banother independent task\b", lowered))


FMH_INDEPENDENT_START_RE = re.compile(
    r"\bofficially started\b|"
    r"\bstarting today\b|"
    r"\bstart(?:ed|ing)?\s+(?:working|organizing|analysing|analyzing|implementing|configuring|writing|developing|building|using)\b|"
    r"\bbegin(?:s|ning)?\s+(?:to\s+)?(?:work|organize|analyse|analyze|implement|configure|write|develop|build)\b|"
    r"\bnew task has started\b|"
    r"\busing .{0,80}\bto implement\b|"
    r"\bstarting (?:the )?.{0,80}\b(?:deployment|implementation|development|configuration|coding|testing)\b",
    re.I,
)


def fmh_candidate_event_text(candidate: Mapping[str, Any], doc_by_event: Mapping[str, str]) -> str:
    event_id = str(candidate.get("event_id") or "")
    return str(doc_by_event.get(event_id) or "")


def fmh_independent_task_start_score(
    candidate: Mapping[str, Any],
    graph_evidence: Optional[STSGraphEvidenceIndex],
    doc_by_event: Mapping[str, str],
) -> float:
    claim: Mapping[str, Any] = {}
    if graph_evidence is not None:
        claim = graph_evidence.claims.get(str(candidate.get("source_id") or ""), {})
    facet_key = str(candidate.get("facet_key") or claim.get("facet_key") or "").lower()
    phase_role = str(candidate.get("phase_role") or claim.get("phase_role") or "").lower()
    text = " ".join(
        str(part)
        for part in (
            candidate.get("evidence_text"),
            candidate.get("subject"),
            candidate.get("predicate") or claim.get("predicate"),
            candidate.get("object") or claim.get("object"),
            candidate.get("value") or claim.get("value"),
            fmh_candidate_event_text(candidate, doc_by_event),
        )
        if part
    )
    score = 0.0
    if FMH_INDEPENDENT_START_RE.search(text):
        score += 8.0
    if phase_role in {"planned_start", "started"}:
        score += 3.0
    if facet_key == "owner":
        score += 5.0
    elif facet_key in {"next_step", "status"}:
        score += 1.0
    if candidate.get("task_object_labels"):
        score += 2.0
    if str(candidate.get("source") or "") == "event":
        score += 1.0
    if (
        facet_key == "next_step"
        and not candidate.get("task_object_labels")
        and not FMH_INDEPENDENT_START_RE.search(text)
    ):
        score -= 4.0
    return score


def temporal_person_hints(question: str) -> List[str]:
    hints: List[str] = []
    patterns = (
        r"led by ([A-Z][a-z]+ [A-Z][a-z]+)",
        r"([A-Z][a-z]+ [A-Z][a-z]+) was responsible",
        r"did it take (?:for )?([A-Z][a-z]+ [A-Z][a-z]+) to",
        r"take ([A-Z][a-z]+ [A-Z][a-z]+) to",
        r"official release by ([A-Z][a-z]+ [A-Z][a-z]+)",
        r"([A-Z][a-z]+ [A-Z][a-z]+) started working",
        r"([A-Z][a-z]+ [A-Z][a-z]+) completed",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, question):
            hint = match.group(1).strip()
            if hint not in hints:
                hints.append(hint)
    return hints


def temporal_resolution_query(base_query: str, item: Mapping[str, Any]) -> str:
    question = str(item.get("Q") or "")
    hints = temporal_person_hints(question)
    return " ".join(part for part in [base_query, " ".join(hints)] if part).strip()


def temporal_answer_from_dates(item: Mapping[str, Any], start: date, end: date) -> str:
    days = (end - start).days + 1
    return f"The task started on {start.isoformat()}, and ended on {end.isoformat()}, lasting {days} days."


def business_days_inclusive(start: date, end: date) -> int:
    current = start
    days = 0
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def effort_answer_from_dates(question: str, start: date, end: date) -> str:
    days = business_days_inclusive(start, end)
    if "planned" in question.lower() or "scheduled" in question.lower():
        return f"The task is scheduled to take {days} working days."
    return f"The task actually took {days} working days."


def effort_duration_start_query(question: str) -> str:
    cleaned = re.sub(r",?\s*which ultimately\b.*?(?:\?|$)", "?", question, flags=re.I)
    cleaned = re.sub(r"\band ultimately\b.*?(?:\?|$)", "?", cleaned, flags=re.I)
    cleaned = re.sub(r"(?i)^in the .+? project,\s*", "", cleaned).strip()
    patterns = (
        r"(?i)how many (?:person-days|workdays|working days|days) (?:were|was) (?:actually )?(?:spent|invested)(?: in total)? by ([A-Z][A-Za-z ]+?) on (.+?)(?:\?|$)",
        r"(?i)how many (?:person-days|workdays|working days|days) (?:were|was) (?:actually )?(?:spent|invested)(?: in total)? on (.+?)(?:\?|$)",
        r"(?i)how many (?:person-days|workdays|working days|days) did ([A-Z][A-Za-z ]+?) (?:actually )?(?:spend|invest) on (.+?)(?:,|\?|$)",
        r"(?i)how many (?:person-days|workdays|working days|days) did it take for ([A-Z][A-Za-z ]+?) to (.+?)(?:\?|$)",
        r"(?i)how many working days did it actually take ([A-Z][A-Za-z ]+?) to (.+?)(?:\?|$)",
        r"(?i)regarding the (.+?), what is the planned effort",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        groups = [group for group in match.groups() if group]
        extracted = " ".join(groups)
        return " ".join(extracted.strip(" ?").split()) or question
    return " ".join(cleaned.strip(" ?").split()) or question


def temporal_selector_candidate_rows(candidates: Sequence[Mapping[str, Any]], max_candidates: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for candidate in candidates[:max_candidates]:
        rows.append(
            {
                "prompt_index": len(rows) + 1,
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "time_id": str(candidate.get("time_id") or ""),
                "event_id": str(candidate.get("event_id") or ""),
                "date": str(candidate.get("event_date") or ""),
                "time_role": str(candidate.get("time_role") or ""),
                "time_value_source": str(candidate.get("time_value_source") or ""),
                "source": str(candidate.get("source") or ""),
                "score": round(float(candidate.get("score") or 0.0), 4),
                "text": truncate_text(str(candidate.get("evidence_text") or ""), 340),
            }
        )
    return rows


def temporal_selector_block(title: str, candidates: Sequence[Mapping[str, Any]]) -> str:
    lines = [title]
    for candidate in candidates:
        lines.append(
            "\n".join(
                [
                    f"[{candidate['prompt_index']}] candidate_id={candidate['candidate_id']}",
                    f"time_id={candidate['time_id']}; event_id={candidate['event_id']}; date={candidate['date']}",
                    f"time_role={candidate['time_role']}; source={candidate['source']}; time_value_source={candidate['time_value_source']}; score={candidate['score']}",
                    f"text={candidate['text']}",
                ]
            )
        )
    return "\n\n".join(lines)


def temporal_pair_selector_prompt(
    item: Mapping[str, Any],
    start_query: str,
    end_query: str,
    start_candidates: Sequence[Mapping[str, Any]],
    end_candidates: Sequence[Mapping[str, Any]],
) -> str:
    return (
        "Select the concrete graph time candidates needed to answer the temporal question.\n"
        "Use only the listed candidates. Do not invent dates, event ids, time ids, or facts.\n"
        "Pick the candidate whose evidence text best matches the target task/entity in the question, not merely a generic start or completion cue.\n"
        "Return the start candidate for the task's beginning/planned beginning and the end candidate for completion/finalization/delivery.\n"
        "If the question asks for workdays/person-days spent on one task, still select the task start and task end candidates; arithmetic is done outside this selector.\n\n"
        f"Question: {item.get('Q')}\n"
        f"Start query: {start_query}\n"
        f"End query: {end_query}\n\n"
        + temporal_selector_block("Start candidates:", start_candidates)
        + "\n\n"
        + temporal_selector_block("End candidates:", end_candidates)
        + "\n\nReturn strict JSON with keys: "
        '{"start_candidate_id": string, "start_prompt_index": number, '
        '"end_candidate_id": string, "end_prompt_index": number, "confidence": number}. '
        "Do not include explanations or extra keys."
    )


def lookup_temporal_prompt_candidate(
    raw: Mapping[str, Any],
    prefix: str,
    prompt_candidates: Sequence[Mapping[str, Any]],
    all_candidates: Sequence[Mapping[str, Any]],
) -> Optional[Mapping[str, Any]]:
    selected_candidate_id = str(raw.get(f"{prefix}_candidate_id") or "").strip()
    selected_index: Optional[int] = None
    try:
        selected_index = int(raw.get(f"{prefix}_prompt_index")) if raw.get(f"{prefix}_prompt_index") is not None else None
    except (TypeError, ValueError):
        selected_index = None

    prompt_selected: Optional[Mapping[str, Any]] = None
    for candidate in prompt_candidates:
        if selected_candidate_id and str(candidate.get("candidate_id") or "") == selected_candidate_id:
            prompt_selected = candidate
            break
        if selected_index is not None and int(candidate.get("prompt_index") or -1) == selected_index:
            prompt_selected = candidate
            break
    if prompt_selected is None:
        return None
    candidate_id = str(prompt_selected.get("candidate_id") or "")
    for candidate in all_candidates:
        if str(candidate.get("candidate_id") or "") == candidate_id:
            return candidate
    return None


def temporal_pair_from_candidates(
    start_candidate: Mapping[str, Any],
    end_candidate: Mapping[str, Any],
    inclusive: bool,
    selection_mode: str,
) -> Optional[Dict[str, Any]]:
    start_date = parse_iso_date(start_candidate.get("event_date"))
    end_date = parse_iso_date(end_candidate.get("event_date"))
    if start_date is None or end_date is None or end_date < start_date:
        return None
    day_delta = (end_date - start_date).days
    computed_days = day_delta + 1 if inclusive else day_delta
    pair_score = float(start_candidate.get("score") or 0.0) + float(end_candidate.get("score") or 0.0)
    if start_candidate.get("group") == end_candidate.get("group"):
        pair_score += 12.0
    else:
        pair_score -= 4.0
    if 2 <= computed_days <= 14:
        pair_score += min(8.0, float(computed_days))
    if computed_days == 1:
        pair_score -= 3.0
    if computed_days > 21:
        pair_score -= 10.0
    if start_candidate.get("source") == "claim":
        pair_score += 1.0
    if end_candidate.get("source") == "claim":
        pair_score += 1.0
    return {
        "pair_score": pair_score,
        "start": dict(start_candidate),
        "end": dict(end_candidate),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "computed_days": computed_days,
        "inclusive": inclusive,
        "selection_mode": selection_mode,
    }


def best_temporal_pair(
    start_candidates: Sequence[Mapping[str, Any]],
    end_candidates: Sequence[Mapping[str, Any]],
    inclusive: bool,
) -> Optional[Dict[str, Any]]:
    best_pair: Optional[Dict[str, Any]] = None
    for start_candidate in start_candidates:
        for end_candidate in end_candidates:
            pair = temporal_pair_from_candidates(start_candidate, end_candidate, inclusive, "deterministic_graph_score")
            if pair is None:
                continue
            if best_pair is None or float(pair.get("pair_score") or 0.0) > float(best_pair.get("pair_score") or 0.0):
                best_pair = pair
    return best_pair


def select_temporal_pair_with_llm(
    item: Mapping[str, Any],
    start_query: str,
    end_query: str,
    start_candidates: Sequence[Mapping[str, Any]],
    end_candidates: Sequence[Mapping[str, Any]],
    answer_client: LLMClient,
    max_candidates: int,
    inclusive: bool,
) -> Dict[str, Any]:
    prompt_start = temporal_selector_candidate_rows(start_candidates, max_candidates)
    prompt_end = temporal_selector_candidate_rows(end_candidates, max_candidates)
    if not prompt_start or not prompt_end:
        return {
            "enabled": True,
            "selector": "llm_graph_time_pair_selector",
            "selected_pair": None,
            "error": "no_prompt_candidates",
            "start_prompt_candidate_count": len(prompt_start),
            "end_prompt_candidate_count": len(prompt_end),
        }
    try:
        raw = answer_client.complete_json(
            "You are a precise graph time-node selector. Return JSON only.",
            temporal_pair_selector_prompt(item, start_query, end_query, prompt_start, prompt_end),
        )
    except Exception as exc:
        return {
            "enabled": True,
            "selector": "llm_graph_time_pair_selector",
            "selected_pair": None,
            "raw": None,
            "error": f"selector_failed:{type(exc).__name__}",
            "start_prompt_candidate_count": len(prompt_start),
            "end_prompt_candidate_count": len(prompt_end),
        }
    selected_start = lookup_temporal_prompt_candidate(raw, "start", prompt_start, start_candidates)
    selected_end = lookup_temporal_prompt_candidate(raw, "end", prompt_end, end_candidates)
    selected_pair = (
        temporal_pair_from_candidates(selected_start, selected_end, inclusive, "llm_graph_time_pair_selector")
        if isinstance(selected_start, Mapping) and isinstance(selected_end, Mapping)
        else None
    )
    return {
        "enabled": True,
        "selector": "llm_graph_time_pair_selector",
        "selected_pair": selected_pair,
        "selected_start": dict(selected_start) if selected_start else None,
        "selected_end": dict(selected_end) if selected_end else None,
        "raw": raw,
        "error": None if selected_pair else "selected_candidate_not_found_or_invalid_dates",
        "start_prompt_candidate_count": len(prompt_start),
        "end_prompt_candidate_count": len(prompt_end),
    }


def resolve_temporal_interval_with_selector(
    item: Mapping[str, Any],
    graph_evidence: STSGraphEvidenceIndex,
    start_query: str,
    end_query: str,
    start_endpoint_kind: str,
    end_endpoint_kind: str,
    top_k: int,
    scope_ids: Sequence[str],
    inclusive: bool,
    start_time_roles: Sequence[str],
    end_time_roles: Sequence[str],
    boost_event_ids: Sequence[str],
    answer_client: Optional[LLMClient],
    time_selector: str,
    selector_candidates: int,
) -> Dict[str, Any]:
    candidate_k = max(top_k, selector_candidates if time_selector == "llm" else top_k)
    start_candidates = graph_evidence.rank_temporal_endpoint_candidates(
        start_query,
        start_endpoint_kind,
        candidate_k,
        scope_ids=scope_ids,
        allowed_time_roles=start_time_roles,
        boost_event_ids=boost_event_ids,
    )
    end_candidates = graph_evidence.rank_temporal_endpoint_candidates(
        end_query,
        end_endpoint_kind,
        candidate_k,
        scope_ids=scope_ids,
        allowed_time_roles=end_time_roles,
        boost_event_ids=boost_event_ids,
    )
    deterministic_pair = best_temporal_pair(start_candidates, end_candidates, inclusive)
    selector_trace: Dict[str, Any] = {"enabled": False, "selector": time_selector}
    selected_pair = deterministic_pair
    if time_selector == "llm" and answer_client is not None:
        selector_trace = select_temporal_pair_with_llm(
            item,
            start_query,
            end_query,
            start_candidates,
            end_candidates,
            answer_client,
            selector_candidates,
            inclusive,
        )
        if isinstance(selector_trace.get("selected_pair"), Mapping):
            selected_pair = selector_trace["selected_pair"]
    return {
        "resolver": "sts_temporal_endpoint_graph",
        "start_query": start_query,
        "end_query": end_query,
        "start_endpoint_kind": start_endpoint_kind,
        "end_endpoint_kind": end_endpoint_kind,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "top_start_candidates": start_candidates[:8],
        "top_end_candidates": end_candidates[:8],
        "deterministic_selected_pair": deterministic_pair,
        "time_selector": selector_trace,
        "selected_pair": selected_pair,
        "error": None if selected_pair else "no_valid_temporal_pair",
    }


def effort_metric_target_count(question: str) -> int:
    lowered = question.lower()
    if re.search(r"\btwo tasks?\b|following two tasks|these two tasks|combined|collectively|both tasks", lowered):
        return 2
    if re.search(r"\bfor [a-z]+ [a-z]+ .+?\band for [a-z]+ [a-z]+", lowered):
        return 2
    if re.search(r"\band in the .+? project,?\s+to\b", lowered):
        return 2
    if re.search(r"\btotal (?:actual )?(?:workdays?|working days?|person-days?|effort).+?,\s+and (?:the|a|an) ", lowered):
        return 2
    return 1


def format_metric_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def try_effort_metric_answer(
    item: Mapping[str, Any],
    graph_evidence: Optional[STSGraphEvidenceIndex],
    scope_ids: Sequence[str],
    seed_event_ids: Sequence[str],
    top_k: int,
    answer_client: Optional[LLMClient] = None,
    time_selector: str = "none",
    selector_candidates: int = 80,
) -> tuple[Optional[str], Dict[str, Any]]:
    if graph_evidence is None:
        return None, {"enabled": False, "reason": "missing_graph_evidence"}
    question = " ".join(str(item.get("Q") or "").split())
    target_count = effort_metric_target_count(question)
    trace: Dict[str, Any] = {
        "enabled": True,
        "resolver": "sts_effort_metric_graph",
        "query": question,
        "target_count": target_count,
        "scope_ids": list(scope_ids),
    }
    if target_count == 1:
        query = effort_duration_start_query(question)
        interval_trace = resolve_temporal_interval_with_selector(
            item,
            graph_evidence,
            start_query=effort_duration_start_query(question),
            end_query=query,
            start_endpoint_kind="start",
            end_endpoint_kind="end",
            top_k=top_k,
            scope_ids=scope_ids,
            inclusive=True,
            start_time_roles=["started_at", "planned_for", "occurred_at"],
            end_time_roles=["completed_at", "finalized_at", "occurred_at"],
            boost_event_ids=seed_event_ids,
            answer_client=answer_client,
            time_selector=time_selector,
            selector_candidates=selector_candidates,
        )
        trace["temporal_duration"] = interval_trace
        selected = interval_trace.get("selected_pair")
        if isinstance(selected, Mapping):
            try:
                start = date.fromisoformat(str(selected["start_date"]))
                end = date.fromisoformat(str(selected["end_date"]))
            except (KeyError, ValueError):
                trace["temporal_duration_error"] = "invalid_selected_pair_dates"
            else:
                answer = effort_answer_from_dates(question, start, end)
                trace["computed_answer"] = answer
                trace["error"] = None
                return answer, trace
    candidates = graph_evidence.rank_effort_metric_candidates(
        question,
        max(top_k, target_count * 8),
        scope_ids=scope_ids,
        boost_event_ids=seed_event_ids,
    )
    fallback_candidates: List[Dict[str, Any]] = []
    if len(candidates) < target_count and scope_ids:
        fallback_candidates = graph_evidence.rank_effort_metric_candidates(
            question,
            max(top_k, target_count * 8),
            scope_ids=None,
            boost_event_ids=seed_event_ids,
        )
        seen_claims = {str(candidate.get("claim_id") or "") for candidate in candidates}
        for candidate in fallback_candidates:
            claim_id = str(candidate.get("claim_id") or "")
            if claim_id and claim_id not in seen_claims:
                candidates.append(candidate)
                seen_claims.add(claim_id)
            if len(candidates) >= max(top_k, target_count * 8):
                break
    selected: List[Dict[str, Any]] = []
    seen_events: set[str] = set()
    skipped_low_relevance: List[Dict[str, Any]] = []
    boosted_event_set = {str(event_id) for event_id in seed_event_ids if event_id}
    for candidate in candidates:
        event_id = str(candidate.get("event_id") or "")
        value = candidate.get("metric_value_num")
        if value is None:
            continue
        coverage = float((candidate.get("content_match_trace") or {}).get("coverage") or 0.0)
        if event_id not in boosted_event_set and coverage < 0.30:
            skipped_low_relevance.append(candidate)
            continue
        if target_count > 1 and event_id in seen_events:
            continue
        selected.append(candidate)
        if event_id:
            seen_events.add(event_id)
        if len(selected) >= target_count:
            break
    trace.update(
        {
            "candidate_count": len(candidates),
            "top_candidates": candidates[:10],
            "fallback_unscoped_candidate_count": len(fallback_candidates),
            "selected_candidates": selected,
            "skipped_low_relevance_metric_candidates": skipped_low_relevance[:10],
        }
    )
    if len(selected) < target_count:
        trace["error"] = "insufficient_metric_candidates"
        return None, trace
    values = [float(candidate.get("metric_value_num") or 0.0) for candidate in selected]
    total = sum(values)
    units = [str(candidate.get("metric_unit") or "days") for candidate in selected]
    unit = units[0] if len(set(units)) == 1 else "days"
    if target_count > 1:
        answer = f"The two tasks took {format_metric_value(total)} {unit} in total."
    else:
        answer = f"{format_metric_value(total)} {unit}."
    trace["computed_answer"] = answer
    trace["error"] = None
    return answer, trace


def try_temporal_interval_answer(
    item: Mapping[str, Any],
    graph_evidence: Optional[STSGraphEvidenceIndex],
    scope_ids: Sequence[str],
    top_k: int,
    answer_client: Optional[LLMClient] = None,
    time_selector: str = "none",
    selector_candidates: int = 80,
) -> tuple[Optional[str], Dict[str, Any]]:
    if graph_evidence is None:
        return None, {"enabled": False, "reason": "missing_graph_evidence"}
    endpoint_queries = temporal_endpoint_queries(item)
    query = temporal_resolution_query(" ".join(str(endpoint.get("query") or "") for endpoint in endpoint_queries), item)

    trace = resolve_temporal_interval_with_selector(
        item,
        graph_evidence,
        start_query=query,
        end_query=query,
        start_endpoint_kind="start",
        end_endpoint_kind="end",
        top_k=top_k,
        scope_ids=scope_ids,
        inclusive=True,
        start_time_roles=["started_at", "planned_for", "occurred_at"],
        end_time_roles=["completed_at", "finalized_at", "occurred_at"],
        boost_event_ids=[],
        answer_client=answer_client,
        time_selector=time_selector,
        selector_candidates=selector_candidates,
    )
    trace["enabled"] = True
    trace["endpoint_queries"] = list(endpoint_queries)
    selected = trace.get("selected_pair")
    if not isinstance(selected, Mapping):
        return None, trace
    try:
        start = date.fromisoformat(str(selected["start_date"]))
        end = date.fromisoformat(str(selected["end_date"]))
    except (KeyError, ValueError):
        trace["error"] = "invalid_selected_pair_dates"
        return None, trace
    answer = temporal_answer_from_dates(item, start, end)
    trace["computed_answer"] = answer
    return answer, trace


def resolve_fmh_endpoint(
    item: Mapping[str, Any],
    endpoint: Mapping[str, Any],
    seed_index: BM25Index,
    embedding_event_index: Optional[OpenAIEmbeddingIndex],
    doc_by_event: Mapping[str, str],
    graph_evidence: STSGraphEvidenceIndex,
    scope_top_k: int,
    scope_types: Sequence[str],
    state_search_k: int,
    max_context_events: int,
    temporal_top_k: int,
    embedding_candidate_k: int,
) -> Dict[str, Any]:
    scope_query = str(endpoint.get("scope_query") or "")
    evidence_query = str(endpoint.get("evidence_query") or scope_query)
    endpoint_kind = str(endpoint.get("endpoint_kind") or "")
    leading_group_context = str(endpoint.get("leading_group_context") or "").strip()
    group_context = str(endpoint.get("group_context") or "").strip()
    use_single_group_scope = bool(leading_group_context or (endpoint_kind == "start" and group_context))
    scope_selection = select_fmh_endpoint_scopes(
        graph_evidence,
        endpoint,
        scope_top_k,
        scope_types,
        max_groups=1 if use_single_group_scope else 2,
    )
    route_query = str(scope_selection["route_query"])
    endpoint_scopes = [dict(scope) for scope in scope_selection["endpoint_scopes"]]
    scope_ids = [str(scope["scope_id"]) for scope in endpoint_scopes]
    scoped_filter = fmh_scoped_event_filter(graph_evidence, endpoint_scopes)
    scoped_event_ids = {str(event_id) for event_id in scoped_filter["event_ids"]}
    task_object_scope_ids = [str(scope_id) for scope_id in scoped_filter["task_object_scope_ids"]]
    context_scope_ids = [str(scope_id) for scope_id in scoped_filter["context_scope_ids"]]
    task_event_ids = {str(event_id) for event_id in scoped_filter["task_event_ids"]}
    context_event_ids = {str(event_id) for event_id in scoped_filter["context_event_ids"]}
    expansion_scope_ids = task_object_scope_ids or scope_ids
    scoped_doc_ids = [event_id for event_id in doc_by_event if event_id in scoped_event_ids]
    endpoint_seed_index = seed_index
    if scoped_doc_ids:
        endpoint_seed_index = BM25Index(scoped_doc_ids, [doc_by_event[event_id] for event_id in scoped_doc_ids])
    seed_events, seed_trace = search_seed_events(
        endpoint_seed_index,
        embedding_event_index,
        evidence_query,
        min(temporal_top_k, max_context_events),
        allowed_event_ids=scoped_doc_ids or None,
        embedding_candidate_k=embedding_candidate_k,
    )
    expanded = graph_evidence.expand(
        item,
        seed_events,
        include_options_in_query=False,
        state_search_k=state_search_k,
        max_context_events=max_context_events,
        query_text=evidence_query,
        scope_ids=expansion_scope_ids,
    )
    boosted_events = list(dict.fromkeys(seed_events + expanded.event_ids))
    candidate_channels: List[tuple[str, List[Dict[str, Any]]]] = []
    if task_event_ids:
        candidate_channels.append(
            (
                "task_object",
                graph_evidence.rank_temporal_endpoint_candidates(
                    evidence_query,
                    str(endpoint.get("endpoint_kind") or ""),
                    temporal_top_k,
                    scope_ids=task_object_scope_ids,
                    allowed_time_roles=[str(role) for role in endpoint.get("time_roles") or []],
                    boost_event_ids=boosted_events,
                    allowed_event_ids=sorted(task_event_ids),
                ),
            )
        )
    if context_event_ids:
        candidate_channels.append(
            (
                "context",
                graph_evidence.rank_temporal_endpoint_candidates(
                    evidence_query,
                    str(endpoint.get("endpoint_kind") or ""),
                    temporal_top_k,
                    scope_ids=context_scope_ids,
                    allowed_time_roles=[str(role) for role in endpoint.get("time_roles") or []],
                    boost_event_ids=boosted_events,
                    allowed_event_ids=sorted(context_event_ids),
                ),
            )
        )
    if not candidate_channels:
        candidate_channels.append(
            (
                "scope_union",
                graph_evidence.rank_temporal_endpoint_candidates(
                    evidence_query,
                    str(endpoint.get("endpoint_kind") or ""),
                    temporal_top_k,
                    scope_ids=scope_ids,
                    allowed_time_roles=[str(role) for role in endpoint.get("time_roles") or []],
                    boost_event_ids=boosted_events,
                    allowed_event_ids=sorted(scoped_event_ids) if scoped_event_ids else None,
                ),
            )
        )
    if task_event_ids or context_event_ids:
        candidate_channels.append(
            (
                "global_query",
                graph_evidence.rank_temporal_endpoint_candidates(
                    evidence_query,
                    str(endpoint.get("endpoint_kind") or ""),
                    temporal_top_k,
                    allowed_time_roles=[str(role) for role in endpoint.get("time_roles") or []],
                    boost_event_ids=boosted_events,
                ),
            )
        )
    candidates_by_id: Dict[str, Dict[str, Any]] = {}
    for channel_name, channel_candidates in candidate_channels:
        for candidate in channel_candidates:
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id:
                continue
            existing = candidates_by_id.get(candidate_id)
            candidate_copy = dict(candidate)
            channels = set(existing.get("retrieval_channels", []) if existing else [])
            channels.add(channel_name)
            candidate_copy["retrieval_channels"] = sorted(channels)
            if existing is None or float(candidate_copy.get("score") or 0.0) > float(existing.get("score") or 0.0):
                candidates_by_id[candidate_id] = candidate_copy
            else:
                existing["retrieval_channels"] = sorted(channels)
    for candidate in candidates_by_id.values():
        channels = set(candidate.get("retrieval_channels", []) or [])
        adjustment = 0.0
        if {"task_object", "context"} <= channels:
            adjustment += 14.0
        elif "context" in channels:
            adjustment += 5.0
        elif "task_object" in channels:
            adjustment += -8.0 if context_event_ids else 2.0
        if "global_query" in channels and not ({"task_object", "context"} & channels):
            adjustment -= 6.0
        candidate["channel_score_adjustment"] = adjustment
        candidate["score"] = float(candidate.get("score") or 0.0) + adjustment
    candidates = sorted(candidates_by_id.values(), key=lambda item: (-float(item.get("score") or 0.0), str(item.get("event_id") or "")))
    candidates = candidates[:temporal_top_k]
    if not candidates:
        fallback_scope_ids = scope_ids
        fallback_event_ids = graph_evidence.events_for_scopes(fallback_scope_ids) if fallback_scope_ids else set()
        candidates = graph_evidence.rank_temporal_endpoint_candidates(
            evidence_query,
            str(endpoint.get("endpoint_kind") or ""),
            temporal_top_k,
            scope_ids=fallback_scope_ids,
            allowed_time_roles=[str(role) for role in endpoint.get("time_roles") or []],
            boost_event_ids=boosted_events,
            allowed_event_ids=sorted(fallback_event_ids) if fallback_event_ids else None,
        )
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    return {
        "endpoint": dict(endpoint),
        "scope_routing": {
            "route_query": route_query,
            "task_query": scope_selection["task_query"],
            "task_query_variants": list(scope_selection.get("task_query_variants", []) or []),
            "context_query": scope_selection["context_query"],
            "selection_strategy": scope_selection["selection_strategy"],
            "routed_scopes": endpoint_scopes,
            "task_scopes": scope_selection["task_scopes"],
            "context_scopes": scope_selection["context_scopes"],
            "endpoint_scopes": endpoint_scopes,
            "task_object_scope_ids": task_object_scope_ids,
            "context_scope_ids": context_scope_ids,
            "scoped_event_strategy": scoped_filter["strategy"],
            "scoped_event_count": len(scoped_event_ids),
            "task_event_count": len(task_event_ids),
            "context_event_count": len(context_event_ids),
            "intersection_event_count": len(scoped_filter["intersection_event_ids"]),
            "candidate_channels": [
                {"channel": channel_name, "candidate_count": len(channel_candidates)}
                for channel_name, channel_candidates in candidate_channels
            ],
        },
        "time_role_route": {
            "endpoint_kind": endpoint.get("endpoint_kind"),
            "time_roles": list(endpoint.get("time_roles") or []),
            "strategy": "evermembench_fmh_endpoint_time_role_rules",
        },
        "seed_event_ids": seed_events,
        "seed_retrieval": seed_trace,
        "graph_expansion": expanded.trace(),
        "candidate_event_boost_count": len(boosted_events),
        "top_candidates": candidates[:10],
        "candidates": candidates,
    }


def fmh_prompt_candidates(candidates: Sequence[Mapping[str, Any]], max_candidates: int) -> List[Dict[str, Any]]:
    prompt_candidates: List[Dict[str, Any]] = []
    seen_candidates: set[str] = set()
    prompt_limit = min(max_candidates, FMH_SELECTOR_PROMPT_CANDIDATE_CAP)
    for candidate in candidates:
        event_id = str(candidate.get("event_id") or "")
        candidate_id = str(candidate.get("candidate_id") or "")
        time_id = str(candidate.get("time_id") or "")
        seen_key = candidate_id or time_id or event_id
        if not event_id or not seen_key or seen_key in seen_candidates:
            continue
        seen_candidates.add(seen_key)
        prompt_candidates.append(
            {
                "prompt_index": len(prompt_candidates) + 1,
                "candidate_id": candidate_id,
                "time_id": time_id,
                "rank": candidate.get("rank"),
                "event_id": event_id,
                "event_date": candidate.get("event_date"),
                "group": candidate.get("group"),
                "speaker": candidate.get("speaker"),
                "time_role": candidate.get("time_role"),
                "time_value_source": candidate.get("time_value_source"),
                "source": candidate.get("source"),
                "retrieval_channels": list(candidate.get("retrieval_channels", []) or []),
                "score": round(float(candidate.get("score") or 0.0), 4),
                "subject": truncate_text(str(candidate.get("subject") or ""), 120),
                "predicate": truncate_text(str(candidate.get("predicate") or ""), 80),
                "object": truncate_text(str(candidate.get("object") or ""), 120),
                "value": truncate_text(str(candidate.get("value") or ""), 120),
                "task_object_labels": [
                    truncate_text(str(label), 80)
                    for label in list(candidate.get("task_object_labels", []) or [])[:4]
                ],
                "quality_reasons": list(candidate.get("quality_reasons", []) or []),
                "evidence_text": truncate_text(str(candidate.get("evidence_text") or ""), FMH_SELECTOR_EVIDENCE_CHARS),
            }
        )
        if len(prompt_candidates) >= prompt_limit:
            break
    return prompt_candidates


def fmh_pair_candidate_block(title: str, candidates: Sequence[Mapping[str, Any]]) -> str:
    lines = [title]
    for candidate in candidates:
        lines.append(
            "\n".join(
                [
                    f"[{candidate['prompt_index']}] candidate_id={candidate['candidate_id']}",
                    f"time_id={candidate['time_id']}; event_id={candidate['event_id']}; date={candidate['event_date']}; group={candidate['group']}; speaker={candidate['speaker']}",
                    f"time_role={candidate['time_role']}; time_value_source={candidate['time_value_source']}; source={candidate['source']}; channels={','.join(candidate['retrieval_channels'])}; retrieval_rank={candidate['rank']}; score={candidate['score']}",
                    f"subject={candidate['subject']}; predicate={candidate['predicate']}; object={candidate['object']}; value={candidate['value']}; task_labels={candidate['task_object_labels']}; quality={candidate['quality_reasons']}",
                    f"text={candidate['evidence_text']}",
                ]
            )
        )
    return "\n\n".join(lines)


def fmh_pair_selector_prompt(
    item: Mapping[str, Any],
    endpoints: Mapping[str, Mapping[str, Any]],
    antecedent_candidates: Sequence[Mapping[str, Any]],
    consequent_candidates: Sequence[Mapping[str, Any]],
    same_person_required: bool = False,
) -> str:
    antecedent = endpoints["antecedent"]
    consequent = endpoints["consequent"]
    return (
        "Select one valid pair of graph time candidates for a long-interval question.\n"
        "Use only the listed candidates. Do not answer the full question and do not invent dates, time ids, event ids, or facts.\n"
        "The antecedent candidate must be the concrete graph Time for the event described after 'after/how long after'.\n"
        "The consequent candidate must be the concrete graph Time for the event described after 'before/for/did ... start/begin'.\n"
        "For the antecedent, prefer completed_at/finalized_at Time nodes when the endpoint says completed, developed, finalized, concluded, or uploaded.\n"
        "For the consequent, prefer started_at/planned_for Time nodes when the endpoint says start, begin, began, planned start, or begin working.\n"
        "The consequent date must be the same day as or after the antecedent date.\n"
        f"Same person required: {str(same_person_required).lower()}. "
        "If true, both selected candidates must have the same speaker field.\n"
        "Prioritize semantic match to the endpoint descriptions over generic words such as started, completed, task, report, system, or project.\n"
        "Do not substitute a later implementation/API/performance/follow-up task for an earlier interview, requirements, design, guide, manual, or report endpoint.\n"
        "If an endpoint says market entry, go-to-market, or GTM, choose candidates that explicitly match that market-entry/GTM strategy; do not substitute content operations, promotional material, or channel plan strategies unless the endpoint asks for those.\n"
        "If several candidates describe the same deliverable family, choose the earliest candidate after the antecedent where the consequent task itself starts.\n"
        "Project deliverable paraphrases may differ, for example guide/manual/materials/report, but the selected candidate must still match the endpoint's business object and group.\n\n"
        f"Question: {item.get('Q')}\n\n"
        f"Antecedent endpoint kind: {antecedent.get('endpoint_kind')}\n"
        f"Antecedent scope query: {antecedent.get('scope_query')}\n"
        f"Antecedent evidence query: {antecedent.get('evidence_query')}\n"
        f"Antecedent time roles: {', '.join(str(role) for role in antecedent.get('time_roles') or [])}\n\n"
        f"Consequent endpoint kind: {consequent.get('endpoint_kind')}\n"
        f"Consequent scope query: {consequent.get('scope_query')}\n"
        f"Consequent evidence query: {consequent.get('evidence_query')}\n"
        f"Consequent time roles: {', '.join(str(role) for role in consequent.get('time_roles') or [])}\n\n"
        + fmh_pair_candidate_block("Antecedent candidates:", antecedent_candidates)
        + "\n\n"
        + fmh_pair_candidate_block("Consequent candidates:", consequent_candidates)
        + "\n\nReturn strict JSON with keys: "
        '{"antecedent_candidate_id": string, "antecedent_time_id": string, "antecedent_prompt_index": number, '
        '"consequent_candidate_id": string, "consequent_time_id": string, "consequent_prompt_index": number, '
        '"confidence": number}. Do not include explanations or extra keys.'
    )


def fmh_lookup_selected_candidate(
    raw: Mapping[str, Any],
    prefix: str,
    prompt_candidates: Sequence[Mapping[str, Any]],
    all_candidates: Sequence[Mapping[str, Any]],
) -> Optional[Mapping[str, Any]]:
    selected_candidate_id = str(raw.get(f"{prefix}_candidate_id") or "").strip()
    selected_time_id = str(raw.get(f"{prefix}_time_id") or "").strip()
    selected_event_id = str(raw.get(f"{prefix}_event_id") or "").strip()
    selected_index: Optional[int] = None
    try:
        selected_index = int(raw.get(f"{prefix}_prompt_index")) if raw.get(f"{prefix}_prompt_index") is not None else None
    except (TypeError, ValueError):
        selected_index = None

    prompt_selected: Optional[Mapping[str, Any]] = None
    for candidate in prompt_candidates:
        if selected_candidate_id and str(candidate.get("candidate_id") or "") == selected_candidate_id:
            prompt_selected = candidate
            break
        if selected_time_id and str(candidate.get("time_id") or "") == selected_time_id:
            prompt_selected = candidate
            break
        if selected_event_id and str(candidate.get("event_id") or "") == selected_event_id:
            prompt_selected = candidate
            break
        if selected_index is not None and int(candidate.get("prompt_index") or -1) == selected_index:
            prompt_selected = candidate
            break
    if prompt_selected is None:
        return None

    prompt_candidate_id = str(prompt_selected.get("candidate_id") or "")
    prompt_time_id = str(prompt_selected.get("time_id") or "")
    prompt_event_id = str(prompt_selected.get("event_id") or "")
    for candidate in all_candidates:
        if str(candidate.get("candidate_id") or "") == prompt_candidate_id:
            return candidate
    for candidate in all_candidates:
        if prompt_time_id and str(candidate.get("time_id") or "") == prompt_time_id:
            return candidate
    for candidate in all_candidates:
        if str(candidate.get("event_id") or "") == prompt_event_id:
            return candidate
    return None


def select_fmh_pair_with_llm(
    item: Mapping[str, Any],
    endpoints: Mapping[str, Mapping[str, Any]],
    antecedent_candidates: Sequence[Mapping[str, Any]],
    consequent_candidates: Sequence[Mapping[str, Any]],
    answer_client: LLMClient,
    max_candidates: int,
    same_person_required: bool = False,
) -> Dict[str, Any]:
    prompt_antecedent = fmh_prompt_candidates(antecedent_candidates, max_candidates)
    prompt_consequent = fmh_prompt_candidates(consequent_candidates, max_candidates)
    if not prompt_antecedent or not prompt_consequent:
        return {
            "enabled": True,
            "selected_antecedent": None,
            "selected_consequent": None,
            "error": "no_prompt_candidates",
            "antecedent_prompt_candidate_count": len(prompt_antecedent),
            "consequent_prompt_candidate_count": len(prompt_consequent),
        }
    try:
        raw = answer_client.complete_json(
            "You are a precise graph time-node selector for temporal QA. Return JSON only.",
            fmh_pair_selector_prompt(item, endpoints, prompt_antecedent, prompt_consequent, same_person_required),
        )
    except Exception as exc:
        return {
            "enabled": True,
            "selected_antecedent": None,
            "selected_consequent": None,
            "raw": None,
            "antecedent_prompt_candidate_count": len(prompt_antecedent),
            "consequent_prompt_candidate_count": len(prompt_consequent),
            "error": f"selector_failed:{type(exc).__name__}",
        }
    selected_antecedent = fmh_lookup_selected_candidate(raw, "antecedent", prompt_antecedent, antecedent_candidates)
    selected_consequent = fmh_lookup_selected_candidate(raw, "consequent", prompt_consequent, consequent_candidates)
    return {
        "enabled": True,
        "selector": "llm_graph_fmh_time_pair_selector",
        "selected_antecedent": dict(selected_antecedent) if selected_antecedent else None,
        "selected_consequent": dict(selected_consequent) if selected_consequent else None,
        "raw": raw,
        "antecedent_prompt_candidate_count": len(prompt_antecedent),
        "consequent_prompt_candidate_count": len(prompt_consequent),
        "error": None if selected_antecedent and selected_consequent else "selected_candidate_not_found",
    }


def normalize_fmh_speaker(candidate: Mapping[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(candidate.get("speaker") or "").strip()).lower()


def normalize_fmh_person(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def fmh_candidate_structured_people(
    graph_evidence: Optional[STSGraphEvidenceIndex],
    candidate: Mapping[str, Any],
) -> List[str]:
    if graph_evidence is None:
        return []
    people: List[str] = []
    seen: set[str] = set()
    for scope_id in graph_evidence.candidate_task_object_scope_ids(candidate):
        for person in sorted(graph_evidence.responsible_people_by_task_scope.get(scope_id, set())):
            key = normalize_fmh_person(person)
            if key and key not in seen:
                seen.add(key)
                people.append(str(person))
    return people


def fmh_candidate_people(
    graph_evidence: Optional[STSGraphEvidenceIndex],
    candidate: Mapping[str, Any],
) -> List[str]:
    people: List[str] = []
    seen: set[str] = set()
    for person in fmh_candidate_structured_people(graph_evidence, candidate):
        key = normalize_fmh_person(person)
        if key and key not in seen:
            seen.add(key)
            people.append(str(person))
    speaker = str(candidate.get("speaker") or "").strip()
    key = normalize_fmh_person(speaker)
    if key and key not in seen:
        seen.add(key)
        people.append(speaker)
    return people


def fmh_shared_person_match(
    graph_evidence: Optional[STSGraphEvidenceIndex],
    start_candidate: Mapping[str, Any],
    end_candidate: Mapping[str, Any],
    allow_speaker_fallback: bool = True,
) -> Dict[str, Any]:
    start_structured = fmh_candidate_structured_people(graph_evidence, start_candidate)
    end_structured = fmh_candidate_structured_people(graph_evidence, end_candidate)
    start_structured_by_key = {normalize_fmh_person(person): person for person in start_structured}
    end_structured_by_key = {normalize_fmh_person(person): person for person in end_structured}
    shared_structured = sorted(set(start_structured_by_key).intersection(end_structured_by_key))
    if shared_structured:
        return {
            "matched": True,
            "match_source": "responsibility",
            "matched_people": [start_structured_by_key[key] for key in shared_structured],
            "start_structured_people": start_structured,
            "end_structured_people": end_structured,
        }
    start_speaker = normalize_fmh_speaker(start_candidate)
    end_speaker = normalize_fmh_speaker(end_candidate)
    if allow_speaker_fallback and start_speaker and start_speaker == end_speaker:
        return {
            "matched": True,
            "match_source": "speaker_fallback",
            "matched_people": [str(start_candidate.get("speaker") or "").strip()],
            "start_structured_people": start_structured,
            "end_structured_people": end_structured,
        }
    return {
        "matched": False,
        "match_source": "",
        "matched_people": [],
        "start_structured_people": start_structured,
        "end_structured_people": end_structured,
    }


def fmh_candidates_share_person(
    graph_evidence: Optional[STSGraphEvidenceIndex],
    start_candidate: Mapping[str, Any],
    end_candidate: Mapping[str, Any],
) -> bool:
    return bool(fmh_shared_person_match(graph_evidence, start_candidate, end_candidate).get("matched"))


def validate_fmh_pair(
    start_candidate: Mapping[str, Any],
    end_candidate: Mapping[str, Any],
    same_person_required: bool,
    graph_evidence: Optional[STSGraphEvidenceIndex] = None,
) -> tuple[bool, str, Optional[date], Optional[date]]:
    start_date = parse_iso_date(start_candidate.get("event_date"))
    end_date = parse_iso_date(end_candidate.get("event_date"))
    if start_date is None or end_date is None:
        return False, "missing_endpoint_date", start_date, end_date
    if end_date < start_date:
        return False, "end_before_start", start_date, end_date
    if start_candidate.get("event_id") == end_candidate.get("event_id"):
        return False, "same_event_selected", start_date, end_date
    if same_person_required:
        person_match = fmh_shared_person_match(graph_evidence, start_candidate, end_candidate)
        if not person_match.get("matched"):
            return False, "same_person_required_responsibility_mismatch", start_date, end_date
    return True, "", start_date, end_date


def try_fmh_long_interval_answer(
    item: Mapping[str, Any],
    seed_index: BM25Index,
    embedding_event_index: Optional[OpenAIEmbeddingIndex],
    doc_by_event: Mapping[str, str],
    graph_evidence: Optional[STSGraphEvidenceIndex],
    scope_top_k: int,
    scope_types: Sequence[str],
    state_search_k: int,
    max_context_events: int,
    temporal_top_k: int,
    answer_client: Optional[LLMClient] = None,
    endpoint_selector: str = "none",
    endpoint_candidates: int = 160,
    embedding_candidate_k: int = 32,
) -> tuple[Optional[str], Dict[str, Any]]:
    if graph_evidence is None:
        return None, {"enabled": False, "reason": "missing_graph_evidence"}
    endpoints = parse_fmh_endpoints(item)
    if endpoints is None:
        return None, {"enabled": False, "reason": "could_not_parse_fmh_endpoints"}
    endpoint_top_k = max(temporal_top_k, endpoint_candidates) if endpoint_selector == "llm" else temporal_top_k

    antecedent = resolve_fmh_endpoint(
        item,
        endpoints["antecedent"],
        seed_index,
        embedding_event_index,
        doc_by_event,
        graph_evidence,
        scope_top_k,
        scope_types,
        state_search_k,
        max_context_events,
        endpoint_top_k,
        embedding_candidate_k,
    )
    consequent = resolve_fmh_endpoint(
        item,
        endpoints["consequent"],
        seed_index,
        embedding_event_index,
        doc_by_event,
        graph_evidence,
        scope_top_k,
        scope_types,
        state_search_k,
        max_context_events,
        endpoint_top_k,
        embedding_candidate_k,
    )
    same_person_required = fmh_requires_same_person(str(item.get("Q") or ""))
    same_responsible_next_task = same_person_required and fmh_next_independent_task_question(str(item.get("Q") or ""))
    responsible_next_pairing_enabled = same_responsible_next_task
    responsible_expansion_candidates: List[Dict[str, Any]] = []
    if same_responsible_next_task:
        responsible_expansion_candidates = graph_evidence.temporal_endpoint_candidates(
            str(endpoints["consequent"].get("endpoint_kind") or "start"),
            allowed_time_roles=[str(role) for role in endpoints["consequent"].get("time_roles") or []],
        )
    llm_selection: Dict[str, Any] = {"enabled": False}
    if endpoint_selector == "llm" and answer_client is not None:
        llm_selection = select_fmh_pair_with_llm(
            item,
            endpoints,
            antecedent["candidates"],
            consequent["candidates"],
            answer_client,
            endpoint_candidates,
            same_person_required,
        )

    best_pair: Optional[Dict[str, Any]] = None
    if isinstance(llm_selection, Mapping):
        start_candidate = llm_selection.get("selected_antecedent")
        end_candidate = llm_selection.get("selected_consequent")
        if isinstance(start_candidate, Mapping) and isinstance(end_candidate, Mapping):
            valid_pair, invalid_reason, start_date, end_date = validate_fmh_pair(
                start_candidate,
                end_candidate,
                same_person_required,
                graph_evidence,
            )
            llm_selection["post_validation_error"] = None if valid_pair else invalid_reason
            if valid_pair and same_responsible_next_task:
                independent_start_score = fmh_independent_task_start_score(end_candidate, graph_evidence, doc_by_event)
                llm_selection["post_validation_independent_start_score"] = round(independent_start_score, 4)
                if independent_start_score < 8.0:
                    valid_pair = False
                    llm_selection["post_validation_error"] = "same_person_next_task_not_independent_start"
            if valid_pair and start_date is not None and end_date is not None:
                person_match = fmh_shared_person_match(graph_evidence, start_candidate, end_candidate)
                best_pair = {
                    "pair_score": 1000.0
                    + float(start_candidate.get("score") or 0.0)
                    + float(end_candidate.get("score") or 0.0),
                    "start": dict(start_candidate),
                    "end": dict(end_candidate),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "computed_days": (end_date - start_date).days,
                    "inclusive": False,
                    "selection_mode": "llm_graph_fmh_time_pair_selector",
                    "person_match": person_match,
                }

    def candidate_key(candidate: Mapping[str, Any]) -> str:
        return "|".join(
            str(candidate.get(key) or "")
            for key in ("candidate_id", "source_id", "event_id", "time_id", "event_date")
        )

    def consequent_candidates_for_start(start_candidate: Mapping[str, Any]) -> List[Dict[str, Any]]:
        candidates_by_key: Dict[str, Dict[str, Any]] = {}
        for candidate in consequent["candidates"]:
            key = candidate_key(candidate)
            candidate_copy = dict(candidate)
            candidate_copy["fmh_independent_start_score"] = round(
                fmh_independent_task_start_score(candidate_copy, graph_evidence, doc_by_event),
                4,
            )
            candidates_by_key[key] = candidate_copy
        if not responsible_next_pairing_enabled:
            return list(candidates_by_key.values())

        start_group = str(start_candidate.get("group") or "")
        for candidate in responsible_expansion_candidates:
            if start_group and str(candidate.get("group") or "") != start_group:
                continue
            person_match = fmh_shared_person_match(graph_evidence, start_candidate, candidate)
            if not person_match.get("matched"):
                continue
            independent_start_score = fmh_independent_task_start_score(candidate, graph_evidence, doc_by_event)
            if independent_start_score < 8.0:
                continue
            key = candidate_key(candidate)
            candidate_copy = dict(candidate)
            candidate_copy["fmh_independent_start_score"] = round(independent_start_score, 4)
            candidate_copy["fmh_person_match"] = person_match
            channels = set(candidate_copy.get("retrieval_channels", []) or [])
            channels.add("responsible_person_expansion")
            candidate_copy["retrieval_channels"] = sorted(channels)
            candidate_copy["score"] = float(candidate_copy.get("score") or 0.0) + independent_start_score
            existing = candidates_by_key.get(key)
            if existing is None or float(candidate_copy.get("score") or 0.0) > float(existing.get("score") or 0.0):
                candidates_by_key[key] = candidate_copy
        return list(candidates_by_key.values())

    start_candidates_for_pairing = list(antecedent["candidates"])
    responsible_start_confidence_reason = "not_required"
    if same_responsible_next_task and start_candidates_for_pairing:
        anchor_start_candidate = start_candidates_for_pairing[0]
        anchor_group = str(anchor_start_candidate.get("group") or "")
        anchor_people = {
            normalize_fmh_person(person)
            for person in fmh_candidate_people(graph_evidence, anchor_start_candidate)
            if normalize_fmh_person(person)
        }
        finalish_start_candidates = [
            candidate
            for candidate in start_candidates_for_pairing
            if "non_final_end_penalty" not in {str(reason) for reason in candidate.get("quality_reasons", []) or []}
        ]
        confidence_candidates = finalish_start_candidates or start_candidates_for_pairing
        if anchor_people:
            anchored_candidates = []
            for candidate in confidence_candidates:
                if anchor_group and str(candidate.get("group") or "") != anchor_group:
                    continue
                candidate_people = {
                    normalize_fmh_person(person)
                    for person in fmh_candidate_people(graph_evidence, candidate)
                    if normalize_fmh_person(person)
                }
                if anchor_people.intersection(candidate_people):
                    anchored_candidates.append(candidate)
            if anchored_candidates:
                confidence_candidates = anchored_candidates
                responsible_start_confidence_reason = "anchored_to_top_start_person"
        top_start_score = max(float(candidate.get("score") or 0.0) for candidate in confidence_candidates)
        top_start_date = str(confidence_candidates[0].get("event_date") or "")
        selected_start_candidates = [
            candidate
            for candidate in confidence_candidates
            if str(candidate.get("event_date") or "") == top_start_date
            or float(candidate.get("score") or 0.0) >= top_start_score * 0.95
        ][:4]
        high_confidence_people: set[str] = set()
        for candidate in selected_start_candidates:
            if float(candidate.get("score") or 0.0) < top_start_score * 0.9:
                continue
            high_confidence_people.update(
                normalize_fmh_person(person)
                for person in fmh_candidate_people(graph_evidence, candidate)
                if normalize_fmh_person(person)
            )
        if len(high_confidence_people) > 1:
            responsible_next_pairing_enabled = False
            responsible_start_confidence_reason = "ambiguous_high_score_start_people"
            start_candidates_for_pairing = list(antecedent["candidates"])
        else:
            if responsible_start_confidence_reason == "not_required":
                responsible_start_confidence_reason = "confident_start_person"
            start_candidates_for_pairing = selected_start_candidates

    for start_candidate in start_candidates_for_pairing:
        if (
            best_pair is not None
            and best_pair.get("selection_mode") == "llm_graph_fmh_time_pair_selector"
            and not same_person_required
        ):
            break
        for end_candidate in consequent_candidates_for_start(start_candidate):
            valid_pair, _, start_date, end_date = validate_fmh_pair(
                start_candidate,
                end_candidate,
                same_person_required,
                graph_evidence,
            )
            if not valid_pair or start_date is None or end_date is None:
                continue
            computed_days = (end_date - start_date).days
            person_match = fmh_shared_person_match(graph_evidence, start_candidate, end_candidate)
            if responsible_next_pairing_enabled:
                if start_candidate.get("group") and start_candidate.get("group") != end_candidate.get("group"):
                    continue
                independent_start_score = float(end_candidate.get("fmh_independent_start_score") or 0.0)
                if independent_start_score < 8.0:
                    continue
                pair_score = 5000.0 - (float(computed_days) * 10.0)
                pair_score += min(80.0, float(start_candidate.get("score") or 0.0) * 0.2)
                pair_score += min(80.0, float(end_candidate.get("score") or 0.0) * 0.2)
                pair_score += independent_start_score * 15.0
                if person_match.get("match_source") == "responsibility":
                    pair_score += 60.0
                elif person_match.get("match_source") == "speaker_fallback":
                    pair_score += 20.0
                if start_candidate.get("source") == "claim":
                    pair_score += 5.0
                if end_candidate.get("source") == "claim":
                    pair_score += 2.0
                if computed_days == 0:
                    pair_score -= 500.0
                selection_mode = "responsible_person_next_independent_task_pair"
            else:
                pair_score = float(start_candidate.get("score") or 0.0) + float(end_candidate.get("score") or 0.0)
                if start_candidate.get("source") == "claim":
                    pair_score += 1.0
                if end_candidate.get("source") == "claim":
                    pair_score += 1.0
                if start_candidate.get("speaker") and start_candidate.get("speaker") == end_candidate.get("speaker"):
                    pair_score += 8.0
                if start_candidate.get("group") and end_candidate.get("group"):
                    pair_score += 6.0 if start_candidate.get("group") == end_candidate.get("group") else -4.0
                selection_mode = "deterministic_graph_fmh_pair"
            pair = {
                "pair_score": pair_score,
                "start": start_candidate,
                "end": end_candidate,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "computed_days": computed_days,
                "inclusive": False,
                "selection_mode": selection_mode,
                "person_match": person_match,
            }
            if best_pair is None or pair_score > float(best_pair.get("pair_score") or 0.0):
                best_pair = pair

    trace = {
        "enabled": True,
        "resolver": "sts_fmh_dual_endpoint_scope_time_graph",
        "same_person_required": same_person_required,
        "same_responsible_next_task": same_responsible_next_task,
        "responsible_person_expansion": {
            "enabled": responsible_next_pairing_enabled,
            "disabled_reason": None if responsible_next_pairing_enabled else responsible_start_confidence_reason,
            "candidate_count": len(responsible_expansion_candidates),
            "independent_start_score_threshold": 8.0,
            "start_pairing_candidate_count": len(start_candidates_for_pairing),
        },
        "antecedent": {key: value for key, value in antecedent.items() if key != "candidates"},
        "consequent": {key: value for key, value in consequent.items() if key != "candidates"},
        "llm_pair_selection": llm_selection,
        "selected_pair": best_pair,
        "error": None if best_pair else "no_valid_fmh_pair",
    }
    if not best_pair:
        return None, trace
    answer = (
        f"From {best_pair['start_date']} to {best_pair['end_date']}, "
        f"there is a period of {best_pair['computed_days']} days."
    )
    trace["computed_answer"] = answer
    return answer, trace


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
    temporal_interval: str,
    temporal_top_k: int,
    time_selector: str,
    fmh_endpoint_selector: str,
    fmh_endpoint_candidates: int,
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
    seed_index = index
    if scope_routing == "sts":
        if graph_evidence is None:
            raise ValueError("scope_routing=sts requires STSGraphEvidenceIndex")
        routed_scopes = graph_evidence.route_scopes(scope_route_query, scope_top_k, effective_scope_types)
        routed_scopes = order_routed_scopes_for_policy(routed_scopes, scope_type_policy, scope_top_k)
        scoped_event_ids = graph_evidence.events_for_scopes([str(scope["scope_id"]) for scope in routed_scopes])
        scoped_doc_ids = [event_id for event_id in doc_ids if event_id in scoped_event_ids]
        if scoped_doc_ids:
            seed_index = BM25Index(scoped_doc_ids, [doc_by_event[event_id] for event_id in scoped_doc_ids])
    seed_events, seed_search_trace = search_seed_events(
        seed_index,
        embedding_event_index,
        query_text,
        top_k,
        allowed_event_ids=scoped_doc_ids or None,
        embedding_candidate_k=embedding_candidate_k,
    )
    seed_retrieval_trace: Dict[str, Any] = {
        "query": query_text,
        "option_text_used": retrieval_include_options,
        "requested_include_options_in_query": bool(include_options_in_query),
        **seed_search_trace,
    }
    scope_trace = {
        "mode": scope_routing,
        "route_query": scope_route_query,
        "scope_type_policy": scope_type_policy,
        "effective_scope_types": effective_scope_types,
        "scope_order_policy": "profile_person_first" if scope_type_policy.get("task_object_demoted") else "score_order",
        "routed_scopes": routed_scopes,
        "scoped_event_count": len(scoped_event_ids),
    }
    graph_trace: Dict[str, Any] = {
        "mode": "none",
        "seed_event_ids": seed_events,
        "scope_routing": scope_trace,
        "seed_retrieval": seed_retrieval_trace,
    }
    notes_by_event: Dict[str, List[str]] = {}
    expanded_evidence: Any = None
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
        preamble_parts = []
        if scope_lines:
            preamble_parts.append("[STS_SCOPE_ROUTING]\n" + "\n".join(scope_lines))
        if state_lines:
            preamble_parts.append("[STS_GRAPH_STATE_FACETS]\n" + "\n".join(state_lines))
        if relation_lines:
            preamble_parts.append("[STS_GRAPH_RELATIONS]\n" + "\n".join(relation_lines))
        graph_preamble = "\n\n".join(preamble_parts)
        graph_trace = {
            "mode": "sts",
            **expanded_evidence.trace(),
            "scope_routing": scope_trace,
            "seed_retrieval": seed_retrieval_trace,
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
    scope_ids = [str(scope["scope_id"]) for scope in routed_scopes] if scope_routing == "sts" else []
    temporal_trace: Dict[str, Any] = {}
    raw_answer: str
    if should_use_fmh_long_interval(item, temporal_interval):
        temporal_answer, temporal_trace = try_fmh_long_interval_answer(
            item,
            seed_index,
            embedding_event_index,
            doc_by_event,
            graph_evidence,
            scope_top_k,
            scope_types,
            state_final_top,
            max_context_events,
            temporal_top_k,
            answer_client=answer_client,
            endpoint_selector=fmh_endpoint_selector,
            endpoint_candidates=fmh_endpoint_candidates,
            embedding_candidate_k=embedding_candidate_k,
        )
        graph_trace["fmh_long_interval"] = temporal_trace
        raw_answer = temporal_answer.strip() if temporal_answer else answer_client.complete_text("", answer_prompt(item, context, answer_prompts)).strip()
    elif should_use_effort_metric(item, temporal_interval):
        temporal_answer, temporal_trace = try_effort_metric_answer(
            item,
            graph_evidence,
            scope_ids,
            top_events,
            temporal_top_k,
            answer_client=answer_client,
            time_selector=time_selector,
            selector_candidates=fmh_endpoint_candidates,
        )
        graph_trace["effort_metric"] = temporal_trace
        raw_answer = temporal_answer.strip() if temporal_answer else answer_client.complete_text("", answer_prompt(item, context, answer_prompts)).strip()
    elif should_use_temporal_interval(item, temporal_interval):
        temporal_answer, temporal_trace = try_temporal_interval_answer(
            item,
            graph_evidence,
            scope_ids,
            temporal_top_k,
            answer_client=answer_client,
            time_selector=time_selector,
            selector_candidates=fmh_endpoint_candidates,
        )
        graph_trace["temporal_interval"] = temporal_trace
        raw_answer = temporal_answer.strip() if temporal_answer else answer_client.complete_text("", answer_prompt(item, context, answer_prompts)).strip()
    else:
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
        "temporal_interval_trace": temporal_trace,
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
        f"temporal_interval={args.temporal_interval} temporal_top_k={args.temporal_top_k} "
        f"time_selector={args.time_selector} "
        f"fmh_endpoint_selector={args.fmh_endpoint_selector} fmh_endpoint_candidates={args.fmh_endpoint_candidates} "
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
            args.temporal_interval,
            args.temporal_top_k,
            args.time_selector,
            args.fmh_endpoint_selector,
            args.fmh_endpoint_candidates,
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
            "scope_type_policy": "question_semantic_profile_scope_demotes_task_object_and_orders_person_first_without_task_label",
            "graph_expansion": args.graph_expansion,
            "include_options_in_query": args.include_options_in_query,
            "top_k": args.top_k,
            "state_final_top": args.state_final_top,
            "max_context_events": args.max_context_events,
            "temporal_interval": args.temporal_interval,
            "temporal_top_k": args.temporal_top_k,
            "time_selector": args.time_selector,
            "fmh_endpoint_selector": args.fmh_endpoint_selector,
            "fmh_endpoint_candidates": args.fmh_endpoint_candidates,
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

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import string
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config
from pipeline.external.longmemeval_s.adapters import TASK_TYPES, get_adapter
from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


DATA_PATH = PROJECT_DIR / "Experiment/Other_BenchMark/LongMemEval-S/data/longmemeval_s_cleaned.json"
OUTPUT_DIR = PROJECT_DIR / "stamb_state_benchmark/output"
SUPPORTED_VARIANTS = (
    "bm25_session",
    "recent_sessions",
    "oracle_sessions",
    "full_history",
    "scope_time_state_public",
    "scope_time_state_task_adapter",
)


@dataclass(frozen=True)
class LMERow:
    question_id: str
    question_type: str
    question: str
    answer: str
    question_date: str
    haystack_session_ids: Tuple[str, ...]
    haystack_dates: Tuple[str, ...]
    haystack_sessions: Tuple[Tuple[Dict[str, object], ...], ...]
    answer_session_ids: Tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LongMemEval-S with lightweight external benchmark adapters.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--variants", nargs="+", default=["bm25_session"])
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument(
        "--task-candidate-k",
        type=int,
        default=20,
        help="BM25 candidate session count for scope_time_state_task_adapter.",
    )
    parser.add_argument("--max-context-chars", type=int, default=60000)
    parser.add_argument("--max-session-chars", type=int, default=10000)
    parser.add_argument(
        "--task-max-session-chars",
        type=int,
        default=4000,
        help="Per-session character cap for scope_time_state_task_adapter evidence extraction.",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--judge", action="store_true", help="Run the official-style LongMemEval LLM judge.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Override the judge model. Defaults to gpt-4o-2024-08-06 for OpenAI to match LongMemEval.",
    )
    parser.add_argument("--judge-cache", default=str(OUTPUT_DIR / "llm_cache.longmemeval_s_judge.json"))
    parser.add_argument("--dry-run", action="store_true", help="Validate data and selected cases without LLM calls.")
    parser.add_argument("--list-tasks", action="store_true", help="Print supported LongMemEval-S task adapters.")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "results_longmemeval_s_smoke.json"))
    parser.add_argument("--cache", default=str(OUTPUT_DIR / "llm_cache.longmemeval_s.json"))
    return parser.parse_args()


def load_rows(path: Path) -> List[LMERow]:
    raw_rows = json.loads(path.read_text())
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


def select_rows(
    rows: Sequence[LMERow],
    question_types: Sequence[str],
    limit: int,
    limit_per_type: int,
) -> List[LMERow]:
    selected = list(rows)
    if question_types:
        allowed = set(question_types)
        selected = [row for row in selected if row.question_type in allowed]
    if limit_per_type:
        counts: Counter[str] = Counter()
        balanced: List[LMERow] = []
        for row in selected:
            if counts[row.question_type] >= limit_per_type:
                continue
            balanced.append(row)
            counts[row.question_type] += 1
        selected = balanced
    if limit:
        selected = selected[:limit]
    return selected


def tokenized(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_']+", text.lower())


def session_text(session: Sequence[Dict[str, object]]) -> str:
    parts: List[str] = []
    for turn in session:
        role = str(turn.get("role", "unknown"))
        content = str(turn.get("content", ""))
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "did",
    "do",
    "for",
    "from",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


def important_query_terms(question: str) -> List[str]:
    return [term for term in tokenized(question) if len(term) > 1 and term not in STOPWORDS]


def rough_term_match(query_term: str, document_term: str) -> bool:
    if query_term == document_term:
        return True
    if len(query_term) >= 4 and document_term.startswith(query_term):
        return True
    if len(document_term) >= 4 and query_term.startswith(document_term):
        return True
    return False


def turn_overlap_score(text: str, query_terms: Sequence[str]) -> int:
    document_terms = tokenized(text)
    score = 0
    for query_term in query_terms:
        score += sum(1 for document_term in document_terms if rough_term_match(query_term, document_term))
    return score


def trim_text_around_terms(text: str, query_terms: Sequence[str], max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    lowered = text.lower()
    positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
    if not positions:
        return text[: max_chars // 2] + "\n[...]\n" + text[-max_chars // 2 :]
    center = min(positions)
    start = max(0, center - max_chars // 2)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    prefix = "[TRUNCATED]\n" if start > 0 else ""
    suffix = "\n[TRUNCATED]" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def compact_session_text_for_question(
    session: Sequence[Dict[str, object]],
    question: str,
    max_chars: int,
) -> str:
    full_text = session_text(session)
    if len(full_text) <= max_chars:
        return full_text

    query_terms = important_query_terms(question)
    if not query_terms:
        return full_text[: max_chars // 2] + "\n[...]\n" + full_text[-max_chars // 2 :]

    turns = [
        f"{str(turn.get('role', 'unknown'))}: {str(turn.get('content', ''))}"
        for turn in session
    ]
    scored_turns = [
        (turn_overlap_score(turn_text, query_terms), index)
        for index, turn_text in enumerate(turns)
    ]
    hit_indices = [index for score, index in sorted(scored_turns, key=lambda item: (-item[0], item[1])) if score > 0]
    if not hit_indices:
        return full_text[: max_chars // 2] + "\n[...]\n" + full_text[-max_chars // 2 :]

    selected_indices = set()
    for index in hit_indices[:6]:
        selected_indices.update({index - 1, index, index + 1})
    selected = [index for index in sorted(selected_indices) if 0 <= index < len(turns)]

    per_turn_budget = max(700, max_chars // max(len(selected), 1))
    chunks = []
    total_chars = 0
    previous_index: Optional[int] = None
    for index in selected:
        if previous_index is not None and index > previous_index + 1:
            chunks.append("[...]")
        turn_text = trim_text_around_terms(turns[index], query_terms, per_turn_budget)
        if total_chars + len(turn_text) > max_chars and chunks:
            break
        chunks.append(turn_text)
        total_chars += len(turn_text)
        previous_index = index
    return "\n".join(chunks)


QUERY_EXPANSIONS = {
    "doctor": ("physician", "specialist", "dermatologist", "ent", "appointment", "clinic"),
    "doctors": ("physician", "specialist", "dermatologist", "ent", "appointment", "clinic"),
    "money": ("cost", "costs", "spent", "paid", "expense", "expenses", "dollars", "$"),
    "spent": ("cost", "costs", "paid", "expense", "expenses", "dollars", "$"),
    "expenses": ("cost", "costs", "spent", "paid", "dollars", "$"),
    "plants": ("plant", "bought", "got", "acquired", "nursery"),
    "plant": ("plants", "bought", "got", "acquired", "nursery"),
    "projects": ("project", "led", "leading", "lead", "team", "responsible"),
    "project": ("projects", "led", "leading", "lead", "team", "responsible"),
    "clothing": ("clothes", "boots", "blazer", "shirt", "dress", "pants", "pick", "return", "store"),
    "hotel": ("hotels", "view", "views", "rooftop", "pool", "balcony", "unique", "amenities"),
    "kitchen": ("utensil", "utensils", "countertop", "countertops", "granite", "sink", "clutter"),
}


def retrieval_query(row: LMERow, expand: bool) -> str:
    if not expand:
        return row.question
    terms = tokenized(row.question)
    expanded_terms = list(terms)
    for term in terms:
        expanded_terms.extend(QUERY_EXPANSIONS.get(term, ()))
    return row.question + " " + " ".join(expanded_terms)


def select_session_ids(row: LMERow, variant: str, top_k: int) -> List[str]:
    if variant == "oracle_sessions":
        return list(row.answer_session_ids)
    if variant == "recent_sessions":
        return list(row.haystack_session_ids[-top_k:])
    if variant == "full_history":
        return list(row.haystack_session_ids)
    if variant in {"bm25_session", "scope_time_state_public", "scope_time_state_task_adapter"}:
        return bm25_top_session_ids(
            row,
            top_k,
            query_text=retrieval_query(row, expand=variant == "scope_time_state_task_adapter"),
        )
    raise ValueError(f"unsupported variant: {variant}")


def bm25_top_session_ids(row: LMERow, top_k: int, query_text: Optional[str] = None) -> List[str]:
    documents = [session_text(session) for session in row.haystack_sessions]
    doc_terms = [Counter(tokenized(doc)) for doc in documents]
    query_terms = Counter(tokenized(query_text or row.question))
    if not query_terms:
        return list(row.haystack_session_ids[:top_k])
    doc_count = len(doc_terms)
    avg_len = sum(sum(counter.values()) for counter in doc_terms) / max(doc_count, 1)
    df: Counter[str] = Counter()
    for counter in doc_terms:
        df.update(counter.keys())

    k1 = 1.5
    b = 0.75
    scores: List[Tuple[float, int]] = []
    for index, counter in enumerate(doc_terms):
        doc_len = sum(counter.values())
        score = 0.0
        for term, query_count in query_terms.items():
            freq = counter.get(term, 0)
            if freq == 0:
                continue
            idf = math.log(1.0 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
            denom = freq + k1 * (1.0 - b + b * doc_len / max(avg_len, 1.0))
            score += query_count * idf * (freq * (k1 + 1.0) / denom)
        scores.append((score, index))
    scores.sort(key=lambda item: (-item[0], item[1]))
    return [row.haystack_session_ids[index] for _, index in scores[:top_k]]


def build_context(row: LMERow, selected_session_ids: Sequence[str], max_context_chars: int, max_session_chars: int) -> str:
    selected = set(selected_session_ids)
    chunks: List[str] = []
    total_chars = 0
    for session_id, date, session in zip(row.haystack_session_ids, row.haystack_dates, row.haystack_sessions):
        if session_id not in selected:
            continue
        body = session_text(session)
        if len(body) > max_session_chars:
            body = body[:max_session_chars] + "\n[TRUNCATED]"
        chunk = f"<session id=\"{session_id}\" date=\"{date}\">\n{body}\n</session>"
        if total_chars + len(chunk) > max_context_chars and chunks:
            break
        chunks.append(chunk)
        total_chars += len(chunk)
    return "\n\n".join(chunks)


def build_ranked_context(
    row: LMERow,
    selected_session_ids: Sequence[str],
    max_context_chars: int,
    max_session_chars: int,
) -> str:
    sessions_by_id = {
        session_id: (date, session)
        for session_id, date, session in zip(row.haystack_session_ids, row.haystack_dates, row.haystack_sessions)
    }
    chunks: List[str] = []
    total_chars = 0
    for rank, session_id in enumerate(selected_session_ids, start=1):
        if session_id not in sessions_by_id:
            continue
        date, session = sessions_by_id[session_id]
        body = compact_session_text_for_question(session, row.question, max_session_chars)
        chunk = f"<session id=\"{session_id}\" date=\"{date}\" retrieval_rank=\"{rank}\">\n{body}\n</session>"
        remaining = max_context_chars - total_chars
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            if chunks and remaining < 1000:
                break
            chunk = chunk[:remaining] + "\n[CONTEXT_TRUNCATED]"
        chunks.append(chunk)
        total_chars += len(chunk)
    return "\n\n".join(chunks)


def system_prompt(variant: str, adapter: TaskAdapter) -> str:
    if variant == "scope_time_state_public":
        return (
            "You are adapting a Scope-Time-State memory pipeline to LongMemEval-S. "
            "Use only the provided timestamped chat sessions. First identify candidate current facts, "
            "updates, stale or superseded facts, and temporal constraints relevant to the question. "
            "Then answer the question and cite the session IDs that directly support the answer. "
            "Return strict JSON with keys answer, evidence_session_ids, state_facets, rejected_claims. "
            "Only put directly supporting session IDs in evidence_session_ids. "
            f"The active task adapter is {adapter.task_name}. "
            "If the provided sessions do not contain enough evidence, answer \"I don't know\"."
        )
    return (
        "You answer LongMemEval-S questions using only the provided timestamped chat sessions. "
        "Return strict JSON with key answer. If the provided sessions do not contain enough evidence, "
        "answer \"I don't know\" rather than inventing details."
    )


def user_prompt(row: LMERow, variant: str, context: str, adapter: TaskAdapter) -> str:
    response_schema = adapter.response_schema(variant)
    return (
        f"Benchmark: LongMemEval-S\n"
        f"Variant: {variant}\n"
        f"Question date: {row.question_date}\n"
        f"Question type: {row.question_type}\n"
        f"Task adapter: {adapter.task_name}\n"
        f"Task instruction: {adapter.instruction(row.question_id.endswith('_abs'))}\n"
        f"Question: {row.question}\n\n"
        f"History sessions:\n{context}\n\n"
        "Respond as JSON only:\n"
        f"{response_schema}"
    )


def evidence_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the evidence extraction stage of a Scope-Time-State memory pipeline for LongMemEval-S. "
        "Use only the provided sessions. Do not answer the question yet. "
        "Select the smallest set of directly useful evidence snippets, preserving session IDs and dates. "
        "For updates, keep both stale and updated facts. For temporal questions, keep all dated events needed for calculation. "
        f"The active task adapter is {adapter.task_name}. "
        "Return strict JSON only."
    )


def evidence_user_prompt(row: LMERow, context: str, adapter: TaskAdapter) -> str:
    abstention_note = (
        "This may be an abstention case; if the requested fact is not established, set enough_evidence to false."
        if row.question_id.endswith("_abs")
        else "If relevant evidence is present, keep it even when the final answer requires computation."
    )
    return (
        f"Benchmark: LongMemEval-S\n"
        f"Variant: scope_time_state_task_adapter evidence extraction\n"
        f"Question date: {row.question_date}\n"
        f"Question type: {row.question_type}\n"
        f"Task adapter: {adapter.task_name}\n"
        f"Evidence instruction: {adapter.evidence_prompt_instruction()}\n"
        f"{abstention_note}\n"
        f"Question: {row.question}\n\n"
        f"Candidate sessions:\n{context}\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"relevant_session_ids\": [\"...\"], "
        "\"evidence_snippets\": ["
        "{\"session_id\": \"...\", \"date\": \"...\", \"role\": \"user|assistant|both\", "
        "\"content\": \"short quote or faithful summary\", \"why_relevant\": \"...\"}"
        "], "
        "\"state_facets\": [{\"name\": \"...\", \"value\": \"...\", \"support_session_ids\": [\"...\"]}], "
        "\"rejected_claims\": [{\"claim\": \"...\", \"reason\": \"stale|contradicted|irrelevant|unsupported\", "
        "\"support_session_ids\": [\"...\"]}], "
        "\"enough_evidence\": true"
        "}"
    )


def answer_system_prompt(adapter: TaskAdapter) -> str:
    if adapter.question_type == "single-session-preference":
        return (
            "You are the answer composition stage of a Scope-Time-State memory pipeline for LongMemEval-S. "
            "Ground personalization only in the extracted evidence JSON. "
            "You may use general commonsense or domain knowledge to make a practical recommendation, "
            "but the recommendation must clearly reflect the user's remembered preference, setup, or constraint. "
            "Do not ask for clarification when preference evidence is available; give a directly useful answer. "
            "Cite only session IDs that directly support the personalized preference. "
            f"The active task adapter is {adapter.task_name}. "
            "Return strict JSON only."
        )
    return (
        "You are the answer composition stage of a Scope-Time-State memory pipeline for LongMemEval-S. "
        "Use only the extracted evidence JSON. Do not use outside knowledge. "
        "Answer concisely and cite only session IDs that directly support the final answer. "
        f"The active task adapter is {adapter.task_name}. "
        "Return strict JSON only."
    )


def answer_user_prompt(row: LMERow, extraction: Dict[str, object], adapter: TaskAdapter) -> str:
    abstention_note = (
        "This is an abstention-style case. If the evidence does not establish the requested fact, answer that the information is not available."
        if row.question_id.endswith("_abs")
        else "If the evidence establishes the answer, answer directly rather than saying I don't know."
    )
    evidence_json = json.dumps(extraction, ensure_ascii=False, indent=2)
    return (
        f"Benchmark: LongMemEval-S\n"
        f"Variant: scope_time_state_task_adapter answer composition\n"
        f"Question date: {row.question_date}\n"
        f"Question type: {row.question_type}\n"
        f"Task adapter: {adapter.task_name}\n"
        f"Answer instruction: {adapter.answer_prompt_instruction()}\n"
        f"{abstention_note}\n"
        f"Question: {row.question}\n\n"
        f"Extracted evidence JSON:\n{evidence_json}\n\n"
        "Respond as JSON only:\n"
        f"{adapter.response_schema('scope_time_state_task_adapter')}"
    )


def normalize_answer(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.translate(str.maketrans("", "", string.punctuation))
    lowered = re.sub(r"\b(a|an|the)\b", " ", lowered)
    return " ".join(lowered.split())


def local_answer_match(gold: str, hypothesis: str) -> bool:
    gold_norm = normalize_answer(gold)
    hyp_norm = normalize_answer(hypothesis)
    if not gold_norm or not hyp_norm:
        return False
    return gold_norm == hyp_norm or gold_norm in hyp_norm or hyp_norm in gold_norm


def answer_check_prompt(row: LMERow, response: str) -> str:
    if row.question_id.endswith("_abs"):
        return (
            "I will give you an unanswerable question, an explanation, and a response from a model. "
            "Please answer yes if the model correctly identifies the question as unanswerable. "
            "The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\n"
            f"Question: {row.question}\n\n"
            f"Explanation: {row.answer}\n\n"
            f"Model Response: {response}\n\n"
            "Does the model correctly identify the question as unanswerable? Answer yes or no only."
        )
    if row.question_type in {"single-session-user", "single-session-assistant", "multi-session"}:
        return (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
            "If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. "
            "If the response only contains a subset of the information required by the answer, answer no. \n\n"
            f"Question: {row.question}\n\n"
            f"Correct Answer: {row.answer}\n\n"
            f"Model Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    if row.question_type == "temporal-reasoning":
        return (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
            "If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. "
            "If the response only contains a subset of the information required by the answer, answer no. "
            "In addition, do not penalize off-by-one errors for the number of days. "
            "If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\n"
            f"Question: {row.question}\n\n"
            f"Correct Answer: {row.answer}\n\n"
            f"Model Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    if row.question_type == "knowledge-update":
        return (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
            "If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\n"
            f"Question: {row.question}\n\n"
            f"Correct Answer: {row.answer}\n\n"
            f"Model Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    if row.question_type == "single-session-preference":
        return (
            "I will give you a question, a rubric for desired personalized response, and a response from a model. "
            "Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
            "The model does not need to reflect all the points in the rubric. "
            "The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\n"
            f"Question: {row.question}\n\n"
            f"Rubric: {row.answer}\n\n"
            f"Model Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    raise ValueError(f"unsupported question_type={row.question_type}")


class TextJudgeClient:
    def __init__(self, provider: str, model: str, api_key: str, api_base: str, cache_path: Path, use_cache: bool):
        from openai import OpenAI

        self.provider = provider
        self.model = model
        self.api_base = api_base
        timeout_seconds = float(os.environ.get("LLM_REQUEST_TIMEOUT", "120"))
        max_retries = int(os.environ.get("LLM_MAX_RETRIES", "1"))
        self.client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout_seconds, max_retries=max_retries)
        self.cache_path = cache_path
        self.use_cache = use_cache
        self.cache: Dict[str, str] = {}
        if use_cache and cache_path.exists():
            self.cache = json.loads(cache_path.read_text())

    def judge(self, row: LMERow, response: str) -> Dict[str, object]:
        prompt = answer_check_prompt(row, response)
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "api_base": self.api_base,
                    "prompt": prompt,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.use_cache and cache_key in self.cache:
            judge_response = self.cache[cache_key]
        else:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10,
            )
            judge_response = (completion.choices[0].message.content or "").strip()
            if self.use_cache:
                next_cache = dict(self.cache)
                next_cache[cache_key] = judge_response
                self.cache = next_cache
                self.cache_path.parent.mkdir(exist_ok=True)
                self.cache_path.write_text(json.dumps(next_cache, ensure_ascii=False, indent=2) + "\n")
        return {
            "model": self.model,
            "label": "yes" in judge_response.lower(),
            "response": judge_response,
        }


def recall(selected: Sequence[str], gold: Sequence[str]) -> Optional[float]:
    gold_set = set(gold)
    if not gold_set:
        return None
    return len(gold_set & set(selected)) / len(gold_set)


def precision(selected: Sequence[str], gold: Sequence[str]) -> Optional[float]:
    selected_set = set(selected)
    if not selected_set:
        return None
    return len(selected_set & set(gold)) / len(selected_set)


def normalize_session_ids(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in {None, "", "null"}]
    if isinstance(value, tuple):
        return [str(item) for item in value if item not in {None, "", "null"}]
    if value in {"", "null"}:
        return []
    return [str(value)]


def ordered_unique(items: Iterable[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def evidence_ids_from_extraction(extraction: Dict[str, object]) -> List[str]:
    ids: List[str] = []
    ids.extend(normalize_session_ids(extraction.get("relevant_session_ids")))
    snippets = extraction.get("evidence_snippets")
    if isinstance(snippets, list):
        for snippet in snippets:
            if isinstance(snippet, dict):
                ids.extend(normalize_session_ids(snippet.get("session_id")))
    for field_name in ("state_facets", "rejected_claims"):
        items = extraction.get(field_name)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    ids.extend(normalize_session_ids(item.get("support_session_ids")))
    return ordered_unique(ids)


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 4)


def summarize(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    by_type: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_type[str(row["question_type"])].append(row)
    by_question_type = {
        question_type: {
            "n_cases": len(type_rows),
            "local_answer_match": mean(1.0 if row["local_answer_match"] else 0.0 for row in type_rows),
            "official_answer_accuracy": mean(
                1.0 if row["autoeval_label"]["label"] else 0.0
                for row in type_rows
                if row.get("autoeval_label") is not None
            ),
            "candidate_session_recall": mean(row["candidate_session_recall"] for row in type_rows),
            "candidate_session_precision": mean(row["candidate_session_precision"] for row in type_rows),
            "evidence_session_recall": mean(row["evidence_session_recall"] for row in type_rows),
            "evidence_session_precision": mean(row["evidence_session_precision"] for row in type_rows),
        }
        for question_type, type_rows in sorted(by_type.items())
    }
    return {
        "n_cases": len(rows),
        "local_answer_match": mean(1.0 if row["local_answer_match"] else 0.0 for row in rows),
        "official_answer_accuracy": mean(
            1.0 if row["autoeval_label"]["label"] else 0.0
            for row in rows
            if row.get("autoeval_label") is not None
        ),
        "candidate_session_recall": mean(row["candidate_session_recall"] for row in rows),
        "candidate_session_precision": mean(row["candidate_session_precision"] for row in rows),
        "evidence_session_recall": mean(row["evidence_session_recall"] for row in rows),
        "evidence_session_precision": mean(row["evidence_session_precision"] for row in rows),
        "abstention_accuracy": mean(
            1.0 if row["autoeval_label"]["label"] else 0.0
            for row in rows
            if row.get("autoeval_label") is not None and row["is_abstention"]
        ),
        "task_averaged_official_answer_accuracy": mean(
            metrics["official_answer_accuracy"] for metrics in by_question_type.values()
        ),
        "by_question_type": by_question_type,
    }


def print_summary(provider: str, model: str, results: Sequence[Dict[str, object]]) -> None:
    print("LongMemEval-S external benchmark")
    print(f"provider={provider} model={model}")
    print("NOTE: local_answer_match is a rough smoke metric; official_answer_accuracy is the paper-facing judge metric when present.")
    print()
    print(
        f"{'variant':<31} {'n':>4} {'ans_j':>8} {'task_avg':>9} {'ans_local':>10} "
        f"{'cand_r':>8} {'cand_p':>8} {'ev_r':>8} {'ev_p':>8}"
    )
    print("-" * 108)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<31} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['official_answer_accuracy']):>8} "
            f"{format_metric(summary['task_averaged_official_answer_accuracy']):>9} "
            f"{format_metric(summary['local_answer_match']):>10} "
            f"{format_metric(summary['candidate_session_recall']):>8} "
            f"{format_metric(summary['candidate_session_precision']):>8} "
            f"{format_metric(summary['evidence_session_recall']):>8} "
            f"{format_metric(summary['evidence_session_precision']):>8}"
        )
    print()


def format_metric(value: object) -> str:
    return f"{value:.3f}" if isinstance(value, float) else "n/a"


def run_variant(
    client: LLMClient,
    judge_client: Optional[TextJudgeClient],
    rows: Sequence[LMERow],
    variant: str,
    args: argparse.Namespace,
) -> Dict[str, object]:
    eval_rows: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        adapter = get_adapter(row.question_type)
        candidate_k = args.task_candidate_k if variant == "scope_time_state_task_adapter" else args.top_k
        selected_session_ids = select_session_ids(row, variant, candidate_k)
        evidence_extraction: Optional[Dict[str, object]] = None
        if variant == "scope_time_state_task_adapter":
            context = build_ranked_context(
                row,
                selected_session_ids,
                args.max_context_chars,
                args.task_max_session_chars,
            )
            evidence_extraction = client.complete_json(
                evidence_system_prompt(adapter),
                evidence_user_prompt(row, context, adapter),
            )
            output = client.complete_json(
                answer_system_prompt(adapter),
                answer_user_prompt(row, evidence_extraction, adapter),
            )
        else:
            context = build_context(row, selected_session_ids, args.max_context_chars, args.max_session_chars)
            output = client.complete_json(system_prompt(variant, adapter), user_prompt(row, variant, context, adapter))
        hypothesis = str(output.get("answer", "")).strip()
        if variant in {"scope_time_state_public", "scope_time_state_task_adapter"}:
            evidence_session_ids = normalize_session_ids(output.get("evidence_session_ids"))
            if not evidence_session_ids and evidence_extraction is not None:
                evidence_session_ids = evidence_ids_from_extraction(evidence_extraction)
        else:
            evidence_session_ids = list(selected_session_ids)
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
                "state_facets": output.get("state_facets")
                if variant in {"scope_time_state_public", "scope_time_state_task_adapter"}
                else None,
                "rejected_claims": output.get("rejected_claims")
                if variant in {"scope_time_state_public", "scope_time_state_task_adapter"}
                else None,
                "answer_rationale": output.get("answer_rationale")
                if variant == "scope_time_state_task_adapter"
                else None,
                "evidence_extraction": evidence_extraction,
            }
        )
        print(f"[{variant}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    return {"variant": variant, "summary": summarize(eval_rows), "rows": eval_rows}


def main() -> int:
    args = parse_args()
    if args.list_tasks:
        for question_type in sorted(TASK_TYPES):
            adapter = get_adapter(question_type)
            print(f"{question_type}\t{adapter.task_name}")
        return 0
    for variant in args.variants:
        if variant not in SUPPORTED_VARIANTS:
            print(f"unsupported variant: {variant}; supported: {', '.join(SUPPORTED_VARIANTS)}", file=sys.stderr)
            return 2

    load_dotenv()
    data_path = Path(args.data)
    rows = select_rows(load_rows(data_path), args.question_types, args.limit_cases, args.limit_per_type)
    unsupported_question_types = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported_question_types:
        print(f"unsupported question types in selection: {unsupported_question_types}", file=sys.stderr)
        return 2
    question_types = Counter(row.question_type for row in rows)
    if args.dry_run:
        print(
            f"valid LongMemEval-S data: rows={len(rows)} variants={','.join(args.variants)} "
            f"question_types={dict(question_types)}"
        )
        print(f"data_path={data_path}")
        return 0

    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    client = LLMClient(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )
    judge_client: Optional[TextJudgeClient] = None
    judge_model: Optional[str] = None
    if args.judge:
        try:
            judge_api_key, judge_model, judge_api_base = provider_config(args.judge_provider)
        except RuntimeError as exc:
            print(f"Judge config error: {exc}", file=sys.stderr)
            return 2
        if args.judge_model:
            judge_model = args.judge_model
        elif args.judge_provider == "openai":
            judge_model = "gpt-4o-2024-08-06"
        judge_client = TextJudgeClient(
            provider=args.judge_provider,
            model=judge_model,
            api_key=judge_api_key,
            api_base=judge_api_base,
            cache_path=Path(args.judge_cache),
            use_cache=not args.no_cache,
        )

    try:
        results = [run_variant(client, judge_client, rows, variant, args) for variant in args.variants]
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = {
        "benchmark": "LongMemEval-S",
        "data_path": str(data_path),
        "provider": args.provider,
        "model": model,
        "judge_provider": args.judge_provider if args.judge else None,
        "judge_model": judge_model,
        "variants": list(args.variants),
        "top_k": args.top_k,
        "task_candidate_k": args.task_candidate_k,
        "task_max_session_chars": args.task_max_session_chars,
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "question_types": dict(question_types),
        "task_adapters": {question_type: get_adapter(question_type).task_name for question_type in sorted(question_types)},
        "results": results,
    }
    print_summary(args.provider, model, results)
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    for result in results:
        jsonl_path = output_path.with_name(f"{output_path.stem}.{result['variant']}.hypotheses.jsonl")
        with jsonl_path.open("w") as handle:
            for row in result["rows"]:
                handle.write(
                    json.dumps(
                        {"question_id": row["question_id"], "hypothesis": row["hypothesis"]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        if args.judge:
            judged_jsonl_path = output_path.with_name(f"{output_path.stem}.{result['variant']}.judged.jsonl")
            with judged_jsonl_path.open("w") as handle:
                for row in result["rows"]:
                    handle.write(
                        json.dumps(
                            {
                                "question_id": row["question_id"],
                                "hypothesis": row["hypothesis"],
                                "autoeval_label": row["autoeval_label"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

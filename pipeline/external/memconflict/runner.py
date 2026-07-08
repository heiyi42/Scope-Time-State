from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.memconflict.adapters import TASK_TYPES, get_adapter  # noqa: E402
from pipeline.external.memconflict.adapters.base import EVIDENCE_RESPONSE_SCHEMA, TaskAdapter  # noqa: E402
from pipeline.external.paths import EXTERNAL_CACHE_DIR, EXTERNAL_RESULT_DIR  # noqa: E402


DATA_PATH = PROJECT_DIR / "Experiment/Other_BenchMark/MemConflict/data/Step4_4.jsonl"
CACHE_DIR = EXTERNAL_CACHE_DIR
RESULT_DIR = EXTERNAL_RESULT_DIR
SUPPORTED_VARIANTS = (
    "bm25_memory",
    "recent_memory",
    "full_prefix",
    "scope_time_state_task_adapter",
)
WHITE_BOX_TOP_K_VALUES = (2, 3, 5)


@dataclass(frozen=True)
class DialogueTurn:
    role: str
    content: str
    turn_index: int
    message_index: int


@dataclass(frozen=True)
class SessionRecord:
    session_id: int
    session_index: int
    date: str
    dialogue: Tuple[DialogueTurn, ...]


@dataclass(frozen=True)
class MemoryItem:
    memory_id: str
    session_id: int
    session_index: int
    date: str
    role: str
    content: str
    score: Optional[float] = None

    def context_text(self) -> str:
        return f"[{self.memory_id}] date={self.date} session={self.session_id} role={self.role}\n{self.content}"

    def retrieved_payload(self, rank: int) -> Dict[str, Any]:
        return {
            "rank": rank,
            "memory_id": self.memory_id,
            "memory": self.content,
            "created_at": self.date,
            "session_id": self.session_id,
            "score": self.score,
        }


@dataclass(frozen=True)
class MemConflictCase:
    case_id: str
    persona_id: str
    session_id: int
    session_index: int
    date: str
    question_id: str
    question: str
    answer: str
    conflict_type: str
    ability_target: str
    difficulty: str
    sessions: Tuple[SessionRecord, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MemConflict with external conflict-aware adapters.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--variants", nargs="+", default=["scope_time_state_task_adapter"])
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument(
        "--limit-per-type",
        type=int,
        default=0,
        help="Select at most N questions per conflict type after filtering.",
    )
    parser.add_argument("--conflict-types", nargs="+", default=[], help="dynamic_conflict static_conflict conditional_conflict")
    parser.add_argument("--difficulties", nargs="+", default=[], help="Optional difficulty filter, e.g. easy medium hard.")
    parser.add_argument("--top-k", type=int, default=3, help="Primary retrieved-memory cutoff for white-box metrics.")
    parser.add_argument(
        "--task-candidate-k",
        type=int,
        default=18,
        help="BM25 memory candidates passed to scope_time_state_task_adapter before conflict-aware reranking.",
    )
    parser.add_argument(
        "--memory-granularity",
        choices=("user_turn", "turn", "session"),
        default="user_turn",
        help="Memory item construction. user_turn mirrors the official A-MEM script default.",
    )
    parser.add_argument("--max-context-chars", type=int, default=50000)
    parser.add_argument("--max-memory-chars", type=int, default=2200)
    parser.add_argument("--judge", action="store_true", help="Run an LLM-assisted MemConflict-style judge.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--dry-run", action="store_true", help="Validate data and selected cases without LLM calls.")
    parser.add_argument("--list-tasks", action="store_true", help="Print supported MemConflict conflict adapters.")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output", default=str(RESULT_DIR / "results_memconflict_smoke.json"))
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.memconflict.json"))
    parser.add_argument("--judge-cache", default=str(CACHE_DIR / "llm_cache.memconflict_judge.json"))
    return parser.parse_args()


def extract_dialogue_turn_order(key_name: str) -> int:
    match = re.search(r"(\d+)$", str(key_name))
    if not match:
        return 10**9
    return int(match.group(1))


def build_dialogue_turns(session_dialogue: Any) -> Tuple[DialogueTurn, ...]:
    if not isinstance(session_dialogue, dict):
        return tuple()
    turns: List[DialogueTurn] = []
    message_index = 0
    for key in sorted(session_dialogue.keys(), key=extract_dialogue_turn_order):
        turn_index = extract_dialogue_turn_order(key)
        messages = session_dialogue.get(key)
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "")).strip().lower()
            content = str(message.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            message_index += 1
            turns.append(DialogueTurn(role=role, content=content, turn_index=turn_index, message_index=message_index))
    return tuple(turns)


def load_cases(path: Path) -> List[MemConflictCase]:
    cases: List[MemConflictCase] = []
    with path.open() as handle:
        for persona_index, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            persona_id = str(raw.get("ID") or f"persona_{persona_index}")
            session_records: List[SessionRecord] = []
            for session_index, session in enumerate(raw.get("Full_Session_Chain", [])):
                session_id = int(session.get("Session_ID", session_index))
                session_records.append(
                    SessionRecord(
                        session_id=session_id,
                        session_index=session_index,
                        date=str(session.get("Date", "")),
                        dialogue=build_dialogue_turns(session.get("Session_Dialogue")),
                    )
                )
                for question_index, question_item in enumerate(session.get("Session_Questions", []) or [], start=1):
                    conflict_type = str(question_item.get("conflict_type", "")).strip()
                    question = str(question_item.get("question", "")).strip()
                    answer = str(question_item.get("answer", "")).strip()
                    if not conflict_type or not question or not answer:
                        continue
                    question_id = str(question_item.get("question_id") or f"Q_{question_index:03d}")
                    cases.append(
                        MemConflictCase(
                            case_id=f"{persona_id}:S{session_id}:{question_id}:{question_index}",
                            persona_id=persona_id,
                            session_id=session_id,
                            session_index=session_index,
                            date=str(session.get("Date", "")),
                            question_id=question_id,
                            question=question,
                            answer=answer,
                            conflict_type=conflict_type,
                            ability_target=str(question_item.get("ability_target", "")),
                            difficulty=str(question_item.get("difficulty", "")),
                            sessions=tuple(session_records),
                        )
                    )
    return cases


def select_cases(
    cases: Sequence[MemConflictCase],
    conflict_types: Sequence[str],
    difficulties: Sequence[str],
    limit_cases: int,
    limit_per_type: int,
) -> List[MemConflictCase]:
    selected = list(cases)
    if conflict_types:
        allowed = set(conflict_types)
        selected = [case for case in selected if case.conflict_type in allowed]
    if difficulties:
        allowed_difficulties = {item.lower() for item in difficulties}
        selected = [case for case in selected if case.difficulty.lower() in allowed_difficulties]
    if limit_per_type:
        counts: Counter[str] = Counter()
        balanced: List[MemConflictCase] = []
        for case in selected:
            if counts[case.conflict_type] >= limit_per_type:
                continue
            balanced.append(case)
            counts[case.conflict_type] += 1
        selected = balanced
    if limit_cases:
        selected = selected[:limit_cases]
    return selected


def build_memory_items(case: MemConflictCase, granularity: str, max_memory_chars: int) -> List[MemoryItem]:
    items: List[MemoryItem] = []
    for session in case.sessions:
        if granularity == "session":
            transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in session.dialogue)
            if transcript:
                items.append(
                    MemoryItem(
                        memory_id=f"S{session.session_id}:session",
                        session_id=session.session_id,
                        session_index=session.session_index,
                        date=session.date,
                        role="session",
                        content=trim_memory_text(transcript, max_memory_chars),
                    )
                )
            continue
        for turn in session.dialogue:
            if granularity == "user_turn" and turn.role != "user":
                continue
            items.append(
                MemoryItem(
                    memory_id=f"S{session.session_id}:T{turn.message_index}:{turn.role}",
                    session_id=session.session_id,
                    session_index=session.session_index,
                    date=session.date,
                    role=turn.role,
                    content=trim_memory_text(turn.content, max_memory_chars),
                )
            )
    return items


def trim_memory_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n[TRUNCATED]\n" + text[-half:]


def tokenized(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_']+", text.lower())


def bm25_rank_memory_items(items: Sequence[MemoryItem], query_text: str) -> List[MemoryItem]:
    documents = [item.context_text() for item in items]
    doc_terms = [Counter(tokenized(doc)) for doc in documents]
    query_terms = Counter(tokenized(query_text))
    if not query_terms:
        return list(reversed(items))
    doc_count = len(doc_terms)
    avg_len = sum(sum(counter.values()) for counter in doc_terms) / max(doc_count, 1)
    df: Counter[str] = Counter()
    for counter in doc_terms:
        df.update(counter.keys())
    k1 = 1.5
    b = 0.75
    scored: List[Tuple[float, int, MemoryItem]] = []
    for index, (item, terms) in enumerate(zip(items, doc_terms)):
        doc_len = sum(terms.values()) or 1
        score = 0.0
        for term, query_count in query_terms.items():
            tf = terms.get(term, 0)
            if tf <= 0:
                continue
            idf = math.log(1 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1e-9))
            score += idf * (tf * (k1 + 1) / denom) * query_count
        scored.append((score, index, MemoryItem(**{**item.__dict__, "score": round(score, 6)})))
    scored.sort(key=lambda item: (-item[0], -item[2].session_index, item[1]))
    return [item for _, _, item in scored]


def retrieval_query(case: MemConflictCase, adapter: TaskAdapter) -> str:
    expansion = query_expansion_terms(case.question)
    return " ".join(
        part
        for part in [
            case.question,
            case.conflict_type,
            adapter.task_name,
            expansion,
        ]
        if part
    )


def query_expansion_terms(question: str) -> str:
    normalized = normalize_text(question)
    expansions: List[str] = []
    if any(term in normalized for term in ("residence", "live", "living", "moved", "move", "relocated", "address", "city")):
        expansions.extend(["residence", "home", "live", "living", "moved", "move", "relocated", "relocate", "city", "place"])
    if any(term in normalized for term in ("gender", "pronoun", "male", "female", "man", "woman")):
        expansions.extend(["gender", "male", "female", "man", "woman", "guy", "identifies", "pronouns", "she", "her", "he", "him"])
    if any(term in normalized for term in ("university", "college", "school", "attend", "attended", "graduate", "graduated")):
        expansions.extend(
            [
                "university",
                "college",
                "school",
                "attended",
                "graduate",
                "graduated",
                "grad",
                "studied",
                "study",
                "alma",
                "mater",
                "degree",
                "classmate",
                "classmates",
                "alumni",
                "reunion",
            ]
        )
    if any(term in normalized for term in ("prefer", "preference", "condition", "when")):
        expansions.extend(["prefer", "preference", "condition", "when", "under", "while", "during"])
    return " ".join(expansions)


def select_candidate_items(case: MemConflictCase, variant: str, args: argparse.Namespace) -> List[MemoryItem]:
    all_items = build_memory_items(case, args.memory_granularity, args.max_memory_chars)
    adapter = get_adapter(case.conflict_type)
    if variant == "recent_memory":
        return list(reversed(all_items))[: args.top_k]
    if variant == "full_prefix":
        return all_items
    candidate_k = args.task_candidate_k if variant == "scope_time_state_task_adapter" else args.top_k
    ranked = bm25_rank_memory_items(all_items, retrieval_query(case, adapter))
    if variant == "scope_time_state_task_adapter":
        return diversify_conflict_candidates(case, ranked, all_items, candidate_k)
    return ranked[:candidate_k]


def diversify_conflict_candidates(
    case: MemConflictCase,
    ranked: Sequence[MemoryItem],
    all_items: Sequence[MemoryItem],
    candidate_k: int,
) -> List[MemoryItem]:
    if candidate_k <= 0:
        return list(ranked)
    if case.conflict_type not in {"dynamic_conflict", "static_conflict"}:
        return list(ranked[:candidate_k])
    reserve = min(8, max(2, candidate_k // 3))
    selected: List[MemoryItem] = list(ranked[: max(0, candidate_k - reserve)])
    selected_ids = {item.memory_id for item in selected}
    matching_items = [item for item in all_items if item_matches_query_focus(case.question, item)]
    boundary_items = matching_items[: reserve] + list(reversed(matching_items[-reserve:]))
    for item in boundary_items:
        if item.memory_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.memory_id)
        if len(selected) >= candidate_k:
            break
    for item in ranked:
        if len(selected) >= candidate_k:
            break
        if item.memory_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.memory_id)
    return selected


def item_matches_query_focus(question: str, item: MemoryItem) -> bool:
    focus_terms = set(meaningful_tokens(question))
    focus_terms.update(meaningful_tokens(query_expansion_terms(question)))
    if not focus_terms:
        return False
    item_terms = set(meaningful_tokens(item.content))
    return bool(focus_terms & item_terms)


def format_memory_context(items: Sequence[MemoryItem], max_chars: int) -> str:
    if not items:
        return "No retrieved memories."
    chunks: List[str] = []
    total = 0
    for rank, item in enumerate(items, start=1):
        chunk = f"{rank}. {item.context_text()}"
        if chunks and total + len(chunk) + 2 > max_chars:
            chunks.append("[CONTEXT TRUNCATED]")
            break
        chunks.append(chunk)
        total += len(chunk) + 2
    return "\n\n".join(chunks)


def direct_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You answer MemConflict benchmark questions using only the retrieved memory context. "
        "The query is issued immediately after the listed current session, so never rely on future sessions. "
        "Resolve memory conflicts by temporal validity, factual correctness, and contextual applicability.\n\n"
        f"Task: {adapter.task_instruction}\n"
        f"Answer guidance: {adapter.answer_instruction}\n"
        "Return valid JSON only."
    )


def direct_user_prompt(case: MemConflictCase, context: str, adapter: TaskAdapter, variant: str) -> str:
    return (
        f"Conflict type: {case.conflict_type}\n"
        f"Current session: S{case.session_id} on {case.date}\n"
        "\n"
        f"Retrieved memory context:\n{context}\n\n"
        f"Question: {case.question}\n\n"
        f"Return JSON with this schema:\n{adapter.response_schema(variant)}"
    )


def evidence_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the evidence-selection stage of a conflict-aware long-term memory pipeline. "
        "Select and rank memory items that are valid for the current query, and explicitly reject "
        "outdated, contradictory, conditionally inapplicable, or wrong-entity memories.\n\n"
        f"Task: {adapter.task_instruction}\n"
        f"Evidence guidance: {adapter.evidence_instruction}\n"
        "The order of relevant_memory_ids matters for white-box ranking: put the memory item that "
        "most directly supports the final correct answer first.\n"
        "Return valid JSON only."
    )


def evidence_user_prompt(case: MemConflictCase, context: str) -> str:
    return (
        f"Conflict type: {case.conflict_type}\n"
        f"Current session: S{case.session_id} on {case.date}\n"
        f"Question: {case.question}\n\n"
        f"Candidate memories:\n{context}\n\n"
        "Return JSON with this schema:\n"
        f"{EVIDENCE_RESPONSE_SCHEMA}"
    )


def answer_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the answer-composition stage of a conflict-aware long-term memory pipeline. "
        "Use the selected evidence and rejected-claim analysis; do not introduce unsupported facts. "
        "Also inspect the candidate memories to catch an omitted conflict or applicability condition "
        "before finalizing the answer.\n\n"
        f"Task: {adapter.task_instruction}\n"
        f"Answer guidance: {adapter.answer_instruction}\n"
        "Return valid JSON only."
    )


def answer_user_prompt(case: MemConflictCase, evidence: Dict[str, Any], candidate_context: str, adapter: TaskAdapter) -> str:
    return (
        f"Conflict type: {case.conflict_type}\n"
        f"Current session: S{case.session_id} on {case.date}\n"
        f"Question: {case.question}\n\n"
        f"Evidence extraction JSON:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}\n\n"
        f"Candidate memory context for verification:\n{candidate_context}\n\n"
        f"Return JSON with this schema:\n{adapter.response_schema('scope_time_state_task_adapter')}"
    )


def normalize_text(text: Any) -> str:
    normalized = str(text or "").replace("_", " ").replace("-", " ").lower()
    normalized = re.sub(r"[\"'`]", " ", normalized)
    normalized = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def extract_answer_variants(text: Any) -> List[str]:
    raw_text = str(text or "").strip()
    if not raw_text:
        return []
    variants: List[str] = []
    for separator in ("||", "\n", ";"):
        if separator in raw_text:
            variants.extend(part.strip() for part in raw_text.split(separator))
    variants.append(raw_text)
    normalized: List[str] = []
    for variant in variants:
        value = normalize_text(variant)
        if value and value not in normalized:
            normalized.append(value)
    return normalized


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "their",
    "they",
    "this",
    "to",
    "under",
    "user",
    "was",
    "what",
    "when",
    "where",
    "which",
    "with",
    "yes",
    "no",
}


def meaningful_tokens(text: Any) -> List[str]:
    return [token for token in normalize_text(text).split() if len(token) > 1 and token not in STOPWORDS]


def partial_credit_score(gold_answer: Any, model_answer: Any) -> float:
    gold_variants = extract_answer_variants(gold_answer)
    model_variants = extract_answer_variants(model_answer)
    if not gold_variants or not model_variants:
        return 0.0
    for gold in gold_variants:
        if gold in {"yes", "no"}:
            for model in model_variants:
                if model == gold or model.startswith(f"{gold} "):
                    return 1.0
    if any(gold == model for gold in gold_variants for model in model_variants):
        return 1.0
    best_overlap = 0.0
    best_shared = 0
    for gold in gold_variants:
        gold_tokens = set(meaningful_tokens(gold))
        if not gold_tokens:
            continue
        for model in model_variants:
            model_tokens = set(meaningful_tokens(model))
            if not model_tokens:
                continue
            shared = gold_tokens & model_tokens
            best_shared = max(best_shared, len(shared))
            best_overlap = max(best_overlap, len(shared) / max(1, len(gold_tokens)))
            if len(gold) >= 8 and gold in model:
                return 0.5
            if len(model) >= 8 and model in gold:
                return 0.5
    if best_shared >= 2 or best_overlap >= 0.5:
        return 0.5
    return 0.0


def has_update_order_signal(model_answer: Any) -> bool:
    normalized = normalize_text(model_answer)
    has_change = any(marker in normalized for marker in ("changed", "change", "updated", "update", "moved", "switched"))
    has_order = any(left in normalized and right in normalized for left, right in (("from", "to"), ("previously", "now"), ("before", "now")))
    return has_change and has_order


def has_conflict_recognition_signal(model_answer: Any) -> bool:
    normalized = normalize_text(model_answer)
    return any(marker in normalized for marker in ("inconsisten", "conflict", "contradict", "disagree", "mismatch", "uncertain"))


def lexical_support_rank(case: MemConflictCase, items: Sequence[MemoryItem]) -> int:
    target_tokens = set(meaningful_tokens(case.answer))
    if len(target_tokens) <= 1:
        target_tokens.update(meaningful_tokens(case.question))
        target_tokens.update(meaningful_tokens(query_expansion_terms(case.question)))
    if not target_tokens:
        return 0
    threshold = max(2, min(4, math.ceil(len(target_tokens) * 0.3)))
    for rank, item in enumerate(items, start=1):
        item_text = normalize_text(item.content)
        if any(variant and len(variant) >= 12 and variant in item_text for variant in extract_answer_variants(case.answer)):
            return rank
        item_tokens = set(meaningful_tokens(item.content))
        shared = target_tokens & item_tokens
        if len(shared) >= threshold or len(shared) / max(1, len(target_tokens)) >= 0.45:
            return rank
    return 0


def white_box_names(conflict_type: str, top_k: int) -> Tuple[str, str, str]:
    if conflict_type == "dynamic_conflict":
        return f"updated_evidence_hit_at_{top_k}", f"updated_evidence_log_rank_score_at_{top_k}", "updated_evidence_first_support_rank"
    if conflict_type == "static_conflict":
        return f"truth_evidence_hit_at_{top_k}", f"truth_evidence_log_rank_score_at_{top_k}", "truth_evidence_first_support_rank"
    if conflict_type == "conditional_conflict":
        return (
            f"correct_condition_evidence_hit_at_{top_k}",
            f"correct_condition_evidence_log_rank_score_at_{top_k}",
            "correct_condition_evidence_first_support_rank",
        )
    raise ValueError(f"unsupported conflict_type={conflict_type}")


def support_metrics(conflict_type: str, support_rank: int, top_k: int) -> Tuple[Dict[str, float], Dict[str, int]]:
    hit_name, rank_score_name, support_rank_name = white_box_names(conflict_type, top_k)
    if 1 <= support_rank <= top_k:
        return {
            hit_name: 1.0,
            rank_score_name: 1.0 / math.log2(float(support_rank) + 1.0),
        }, {support_rank_name: support_rank}
    return {hit_name: 0.0, rank_score_name: 0.0}, {support_rank_name: 0}


def local_black_box_metrics(case: MemConflictCase, hypothesis: str) -> Dict[str, float]:
    answer_score = partial_credit_score(case.answer, hypothesis)
    if case.conflict_type == "dynamic_conflict":
        return {
            "dynamic_answer_accuracy": answer_score,
            "update_awareness_and_order_consistency_score": 1.0 if answer_score >= 0.5 and has_update_order_signal(hypothesis) else 0.0,
        }
    if case.conflict_type == "static_conflict":
        return {
            "static_answer_accuracy": answer_score,
            "conflict_recognition_score": 1.0 if has_conflict_recognition_signal(hypothesis) else 0.0,
        }
    if case.conflict_type == "conditional_conflict":
        return {"conditional_answer_accuracy": 1.0 if answer_score >= 0.5 else 0.0}
    raise ValueError(f"unsupported conflict_type={case.conflict_type}")


def build_judge_prompt(case: MemConflictCase, hypothesis: str, retrieved_items: Sequence[MemoryItem], top_k: int) -> str:
    retrieved_text = "\n".join(
        f"{rank}. [{item.date}] {item.content} (memory_id={item.memory_id}, score={item.score})"
        for rank, item in enumerate(retrieved_items[:top_k], start=1)
    ) or "No retrieved memories."
    if case.conflict_type == "dynamic_conflict":
        metric_lines = (
            "- answer_accuracy: 1.0 if the model answer captures the reference updated/current fact; "
            "0.5 if partially correct; 0.0 if wrong.\n"
            "- diagnostic_score: 1 if the answer recognizes update/change order when relevant; otherwise 0.\n"
            "- support_rank: 1-based rank of the first retrieved memory containing updated-state evidence; 0 if absent."
        )
    elif case.conflict_type == "static_conflict":
        metric_lines = (
            "- answer_accuracy: 1.0 if the model answer captures the reference stable true fact; "
            "0.5 if partially correct; 0.0 if wrong.\n"
            "- diagnostic_score: 1 if the answer recognizes inconsistent/contradictory sources; otherwise 0.\n"
            "- support_rank: 1-based rank of the first retrieved memory containing truth-supporting evidence; 0 if absent."
        )
    else:
        metric_lines = (
            "- answer_accuracy: 1.0 if the model answer gives the reference condition or condition-value association; 0.0 if wrong.\n"
            "- diagnostic_score: 0, because conditional conflicts have no extra diagnostic metric.\n"
            "- support_rank: 1-based rank of the first retrieved memory containing correct-condition evidence; 0 if absent."
        )
    return (
        f"You are evaluating one MemConflict {case.conflict_type} question.\n\n"
        f"Question: {case.question}\n"
        f"Reference Answer: {case.answer}\n"
        f"Model Answer: {hypothesis}\n\n"
        f"Top-{top_k} Retrieved Memories:\n{retrieved_text}\n\n"
        f"Metric definitions:\n{metric_lines}\n\n"
        'Return JSON exactly as {"answer_accuracy": 0.0, "diagnostic_score": 0, "support_rank": 0, "reasoning": "..."}'
    )


def judge_case(
    judge_client: Optional[LLMClient],
    case: MemConflictCase,
    hypothesis: str,
    retrieved_items: Sequence[MemoryItem],
    top_k: int,
) -> Optional[Dict[str, Any]]:
    if judge_client is None:
        return None
    parsed = judge_client.complete_json(
        "You are a strict evaluator for memory-conflict experiments. Return valid JSON only.",
        build_judge_prompt(case, hypothesis, retrieved_items, top_k),
    )
    try:
        answer_accuracy = float(parsed.get("answer_accuracy", 0.0) or 0.0)
    except (TypeError, ValueError):
        answer_accuracy = 0.0
    answer_accuracy = 1.0 if answer_accuracy >= 0.75 else 0.5 if answer_accuracy >= 0.25 else 0.0
    try:
        diagnostic_score = 1.0 if int(parsed.get("diagnostic_score", 0) or 0) else 0.0
    except (TypeError, ValueError):
        diagnostic_score = 0.0
    try:
        support_rank = int(parsed.get("support_rank", 0) or 0)
    except (TypeError, ValueError):
        support_rank = 0
    if support_rank < 0 or support_rank > top_k:
        support_rank = 0
    metrics: Dict[str, float]
    if case.conflict_type == "dynamic_conflict":
        metrics = {
            "dynamic_answer_accuracy": answer_accuracy,
            "update_awareness_and_order_consistency_score": diagnostic_score,
        }
    elif case.conflict_type == "static_conflict":
        metrics = {
            "static_answer_accuracy": answer_accuracy,
            "conflict_recognition_score": diagnostic_score,
        }
    else:
        metrics = {"conditional_answer_accuracy": 1.0 if answer_accuracy >= 0.5 else 0.0}
    white_metrics, metadata = support_metrics(case.conflict_type, support_rank, top_k)
    metrics.update(white_metrics)
    return {
        "judge_method": "llm_judge",
        "metrics": metrics,
        "white_box_metadata": metadata,
        "reasoning": str(parsed.get("reasoning", "")),
    }


def rerank_by_extraction(candidates: Sequence[MemoryItem], extraction: Dict[str, Any]) -> List[MemoryItem]:
    by_id = {item.memory_id: item for item in candidates}
    ordered_ids: List[str] = []
    for value in extraction.get("relevant_memory_ids", []) if isinstance(extraction.get("relevant_memory_ids"), list) else []:
        memory_id = resolve_memory_id(str(value), by_id)
        if memory_id in by_id and memory_id not in ordered_ids:
            ordered_ids.append(memory_id)
    for field_name in ("valid_evidence", "state_facets"):
        items = extraction.get(field_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_ids = item.get("support_memory_ids") or item.get("memory_id") or item.get("memory_ids")
            if not isinstance(raw_ids, list):
                raw_ids = [raw_ids]
            for raw_id in raw_ids:
                memory_id = resolve_memory_id(str(raw_id), by_id)
                if memory_id in by_id and memory_id not in ordered_ids:
                    ordered_ids.append(memory_id)
    reranked = [by_id[memory_id] for memory_id in ordered_ids]
    reranked.extend(item for item in candidates if item.memory_id not in ordered_ids)
    return reranked


def resolve_memory_id(raw_id: str, by_id: Dict[str, MemoryItem]) -> str:
    if raw_id in by_id:
        return raw_id
    prefix = raw_id.rstrip(":")
    matches = [memory_id for memory_id in by_id if memory_id.startswith(f"{prefix}:")]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return sorted(matches)[0]
    return raw_id


def evaluate_case(
    judge_client: Optional[LLMClient],
    case: MemConflictCase,
    hypothesis: str,
    retrieved_items: Sequence[MemoryItem],
    top_k: int,
) -> Dict[str, Any]:
    try:
        judged = judge_case(judge_client, case, hypothesis, retrieved_items, top_k)
    except LLMRequestError:
        raise
    except Exception as exc:
        judged = {
            "judge_method": "local_rule_fallback",
            "metrics": {},
            "white_box_metadata": {},
            "reasoning": f"LLM judge failed; local fallback used: {exc}",
        }
    if judged is None:
        judged = {
            "judge_method": "local_rule",
            "metrics": {},
            "white_box_metadata": {},
            "reasoning": "Local lexical smoke scoring; use --judge for paper-facing scoring.",
        }
    if not judged["metrics"]:
        support_rank = lexical_support_rank(case, retrieved_items[:top_k])
        metrics = local_black_box_metrics(case, hypothesis)
        white_metrics, metadata = support_metrics(case.conflict_type, support_rank, top_k)
        metrics.update(white_metrics)
        judged["metrics"] = metrics
        judged["white_box_metadata"] = metadata
    return judged


def run_variant(
    client: LLMClient,
    judge_client: Optional[LLMClient],
    cases: Sequence[MemConflictCase],
    variant: str,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        adapter = get_adapter(case.conflict_type)
        candidates = select_candidate_items(case, variant, args)
        evidence_extraction: Optional[Dict[str, Any]] = None
        if variant == "scope_time_state_task_adapter":
            candidate_context = format_memory_context(candidates, args.max_context_chars)
            evidence_extraction = client.complete_json(
                evidence_system_prompt(adapter),
                evidence_user_prompt(case, candidate_context),
            )
            ranked_items = rerank_by_extraction(candidates, evidence_extraction)
            output = client.complete_json(
                answer_system_prompt(adapter),
                answer_user_prompt(case, evidence_extraction, candidate_context, adapter),
            )
        else:
            ranked_items = candidates
            context_items = candidates if variant == "full_prefix" else candidates[: args.top_k]
            context = format_memory_context(context_items, args.max_context_chars)
            output = client.complete_json(
                direct_system_prompt(adapter),
                direct_user_prompt(case, context, adapter, variant),
            )
        hypothesis = str(output.get("answer", "")).strip()
        retrieved_for_eval = ranked_items[: max(args.top_k, max(WHITE_BOX_TOP_K_VALUES))]
        eval_result = evaluate_case(judge_client, case, hypothesis, retrieved_for_eval, args.top_k)
        rows.append(
            {
                "case_id": case.case_id,
                "persona_id": case.persona_id,
                "session_id": case.session_id,
                "date": case.date,
                "question_id": case.question_id,
                "conflict_type": case.conflict_type,
                "task_adapter": adapter.task_name,
                "ability_target": case.ability_target,
                "difficulty": case.difficulty,
                "question": case.question,
                "gold_answer": case.answer,
                "hypothesis": hypothesis,
                "candidate_memory_ids": [item.memory_id for item in candidates],
                "retrieved_memory_ids": [item.memory_id for item in retrieved_for_eval],
                "retrieved_memories": [item.retrieved_payload(rank) for rank, item in enumerate(retrieved_for_eval, start=1)],
                "model_output": output,
                "evidence_extraction": evidence_extraction,
                "evaluation": eval_result,
            }
        )
        print(f"[{variant}] {index}/{len(cases)} {case.case_id} {case.conflict_type}", flush=True)
    return {"variant": variant, "summary": summarize(rows, args.top_k), "rows": rows}


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 4)


def summarize(rows: Sequence[Dict[str, Any]], top_k: int) -> Dict[str, Any]:
    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_type[row["conflict_type"]].append(row)

    def metric(row: Dict[str, Any], key: str) -> Optional[float]:
        value = row["evaluation"]["metrics"].get(key)
        return float(value) if isinstance(value, (int, float)) else None

    by_conflict_type: Dict[str, Dict[str, Any]] = {}
    for conflict_type, type_rows in sorted(by_type.items()):
        hit_name, rank_score_name, _ = white_box_names(conflict_type, top_k)
        if conflict_type == "dynamic_conflict":
            answer_key = "dynamic_answer_accuracy"
            diagnostic_key = "update_awareness_and_order_consistency_score"
        elif conflict_type == "static_conflict":
            answer_key = "static_answer_accuracy"
            diagnostic_key = "conflict_recognition_score"
        else:
            answer_key = "conditional_answer_accuracy"
            diagnostic_key = None
        by_conflict_type[conflict_type] = {
            "n_cases": len(type_rows),
            "answer_accuracy": mean(metric(row, answer_key) for row in type_rows),
            "diagnostic_score": mean(metric(row, diagnostic_key) for row in type_rows) if diagnostic_key else None,
            "support_hit_at_k": mean(metric(row, hit_name) for row in type_rows),
            "support_rank_score_at_k": mean(metric(row, rank_score_name) for row in type_rows),
        }
    return {
        "n_cases": len(rows),
        "top_k": top_k,
        "answer_accuracy": mean(item["answer_accuracy"] for item in by_conflict_type.values()),
        "support_hit_at_k": mean(item["support_hit_at_k"] for item in by_conflict_type.values()),
        "support_rank_score_at_k": mean(item["support_rank_score_at_k"] for item in by_conflict_type.values()),
        "by_conflict_type": by_conflict_type,
    }


def format_metric(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, float) else "n/a"


def print_summary(provider: str, model: str, results: Sequence[Dict[str, Any]]) -> None:
    print("MemConflict external benchmark")
    print(f"provider={provider} model={model}")
    print("NOTE: local_rule scoring is a smoke metric; use --judge for LLM-assisted MemConflict scoring.")
    print()
    print(f"{'variant':<32} {'n':>4} {'AA':>8} {'SEH@K':>8} {'SRS':>8}")
    print("-" * 66)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<32} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['answer_accuracy']):>8} "
            f"{format_metric(summary['support_hit_at_k']):>8} "
            f"{format_metric(summary['support_rank_score_at_k']):>8}"
        )
    print()


def main() -> int:
    args = parse_args()
    if args.list_tasks:
        for conflict_type in TASK_TYPES:
            adapter = get_adapter(conflict_type)
            print(f"{conflict_type}\t{adapter.task_name}")
        return 0
    for variant in args.variants:
        if variant not in SUPPORTED_VARIANTS:
            print(f"unsupported variant: {variant}; supported: {', '.join(SUPPORTED_VARIANTS)}", file=sys.stderr)
            return 2
    unknown_conflicts = sorted(set(args.conflict_types) - set(TASK_TYPES))
    if unknown_conflicts:
        print(f"unsupported conflict types: {unknown_conflicts}; supported: {', '.join(TASK_TYPES)}", file=sys.stderr)
        return 2

    data_path = Path(args.data)
    cases = select_cases(load_cases(data_path), args.conflict_types, args.difficulties, args.limit_cases, args.limit_per_type)
    conflict_counts = Counter(case.conflict_type for case in cases)
    unsupported = sorted(set(conflict_counts) - set(TASK_TYPES))
    if unsupported:
        print(f"unsupported conflict types in selected data: {unsupported}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(
            f"valid MemConflict data: cases={len(cases)} variants={','.join(args.variants)} "
            f"conflict_types={dict(conflict_counts)}"
        )
        print(f"data_path={data_path}")
        return 0
    if not cases:
        print("no MemConflict cases selected", file=sys.stderr)
        return 2

    load_dotenv()
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
    judge_client: Optional[LLMClient] = None
    judge_model: Optional[str] = None
    if args.judge:
        try:
            judge_api_key, judge_model, judge_api_base = provider_config(args.judge_provider)
        except RuntimeError as exc:
            print(f"Judge config error: {exc}", file=sys.stderr)
            return 2
        judge_client = LLMClient(
            provider=args.judge_provider,
            model=judge_model,
            api_key=judge_api_key,
            api_base=judge_api_base,
            cache_path=Path(args.judge_cache),
            use_cache=not args.no_cache,
        )

    try:
        results = [run_variant(client, judge_client, cases, variant, args) for variant in args.variants]
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = {
        "benchmark": "MemConflict",
        "data_path": str(data_path),
        "provider": args.provider,
        "model": model,
        "judge_provider": args.judge_provider if args.judge else None,
        "judge_model": judge_model,
        "variants": list(args.variants),
        "top_k": args.top_k,
        "task_candidate_k": args.task_candidate_k,
        "memory_granularity": args.memory_granularity,
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "conflict_types": dict(conflict_counts),
        "task_adapters": {conflict_type: get_adapter(conflict_type).task_name for conflict_type in sorted(conflict_counts)},
        "results": results,
    }
    print_summary(args.provider, model, results)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    for result in results:
        jsonl_path = output_path.with_name(f"{output_path.stem}.{result['variant']}.hypotheses.jsonl")
        with jsonl_path.open("w") as handle:
            for row in result["rows"]:
                handle.write(
                    json.dumps(
                        {
                            "case_id": row["case_id"],
                            "conflict_type": row["conflict_type"],
                            "hypothesis": row["hypothesis"],
                            "metrics": row["evaluation"]["metrics"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

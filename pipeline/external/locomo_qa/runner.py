from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
import json
import math
from pathlib import Path
import re
import string
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.locomo_qa.adapters import TASK_TYPES, get_adapter, task_type_from_category  # noqa: E402
from pipeline.external.locomo_qa.adapters.base import TaskAdapter  # noqa: E402


DATA_PATH = PROJECT_DIR / "Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json"
OUTPUT_DIR = PROJECT_DIR / "stamb_state_benchmark/output"
SUPPORTED_VARIANTS = (
    "bm25_dialog",
    "recent_dialog",
    "oracle_dialog",
    "full_history",
    "scope_time_state_task_adapter",
)


@dataclass(frozen=True)
class DialogTurn:
    dia_id: str
    session_id: str
    session_index: int
    session_date_time: str
    speaker: str
    text: str
    image_caption: str
    image_query: str


@dataclass(frozen=True)
class Session:
    session_id: str
    session_index: int
    date_time: str
    turns: Tuple[DialogTurn, ...]
    session_summary: str


@dataclass(frozen=True)
class Observation:
    session_id: str
    session_index: int
    speaker: str
    text: str
    dialog_ids: Tuple[str, ...]


@dataclass(frozen=True)
class LoCoMoQARow:
    sample_id: str
    question_id: str
    qa_index: int
    category: int
    question_type: str
    question: str
    answer: Optional[str]
    evidence_dialog_ids: Tuple[str, ...]
    evidence_session_ids: Tuple[str, ...]
    sessions: Tuple[Session, ...]
    turns: Tuple[DialogTurn, ...]
    observations: Tuple[Observation, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run text-only LoCoMo QA with task adapters.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--variants", nargs="+", default=["bm25_dialog"])
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument(
        "--selection-strategy",
        choices=("round_robin", "sequential"),
        default="round_robin",
        help="How --limit-per-type selects rows. round_robin balances across LoCoMo conversations.",
    )
    parser.add_argument(
        "--question-types",
        nargs="+",
        default=[],
        help="Task names such as single-hop, multi-hop, temporal, open-domain, adversarial. commonsense is accepted as an alias.",
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument(
        "--task-candidate-k",
        type=int,
        default=80,
        help="BM25 candidate dialog count for scope_time_state_task_adapter.",
    )
    parser.add_argument("--max-context-chars", type=int, default=60000)
    parser.add_argument(
        "--max-memory-chars",
        type=int,
        default=30000,
        help="Public LoCoMo observation/session-summary memory budget for scope_time_state_task_adapter.",
    )
    parser.add_argument(
        "--memory-top-n",
        type=int,
        default=48,
        help="Top public observation/session-summary records passed to scope_time_state_task_adapter.",
    )
    parser.add_argument("--max-dialog-chars", type=int, default=1400)
    parser.add_argument(
        "--context-window-turns",
        type=int,
        default=3,
        help="Include +/- N neighboring dialog turns around each retrieved dialog seed.",
    )
    parser.add_argument(
        "--memory-context-window-turns",
        type=int,
        default=0,
        help="Include +/- N neighboring turns around dialog IDs from public memory records.",
    )
    parser.add_argument(
        "--memory-router",
        action="store_true",
        help="Enable an LLM router over public memory records before evidence extraction. Default is off.",
    )
    parser.add_argument(
        "--router-raw-candidate-k",
        type=int,
        default=24,
        help="Raw retrieved dialog seeds retained when --memory-router is enabled.",
    )
    parser.add_argument(
        "--router-dialog-window-turns",
        type=int,
        default=1,
        help="Include +/- N neighboring turns around dialog IDs selected by --memory-router.",
    )
    parser.add_argument(
        "--task-max-dialog-chars",
        type=int,
        default=900,
        help="Per-dialog character cap for task-adapter evidence extraction.",
    )
    parser.add_argument(
        "--answer-verifier",
        action="store_true",
        help="Enable a generic answer verification stage for scope_time_state_task_adapter. Default is off.",
    )
    parser.add_argument(
        "--answer-contract",
        action="store_true",
        help="Enable a question-only answer contract stage before routing/evidence extraction. Default is off.",
    )
    parser.add_argument(
        "--answer-with-context",
        action="store_true",
        help="Pass the same public memory and raw dialog candidates to answer composition. Default is off.",
    )
    parser.add_argument(
        "--include-session-summary",
        action="store_true",
        help="Append public session summaries to each session/dialog context. Default uses raw dialogs only.",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate data and selected cases without LLM calls.")
    parser.add_argument("--list-tasks", action="store_true", help="Print supported LoCoMo QA task adapters.")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "results_locomo_qa_smoke.json"))
    parser.add_argument("--cache", default=str(OUTPUT_DIR / "llm_cache.locomo_qa.json"))
    return parser.parse_args()


def load_rows(path: Path) -> List[LoCoMoQARow]:
    raw_samples = json.loads(path.read_text())
    rows: List[LoCoMoQARow] = []
    for sample in raw_samples:
        sample_id = str(sample["sample_id"])
        sessions = parse_sessions(dict(sample["conversation"]), dict(sample.get("session_summary", {})))
        turns = tuple(turn for session in sessions for turn in session.turns)
        observations = parse_observations(dict(sample.get("observation", {})))
        for qa_index, qa in enumerate(sample.get("qa", [])):
            category = int(qa["category"])
            question_type = task_type_from_category(category)
            evidence_dialog_ids = normalize_dialog_ids(qa.get("evidence"))
            rows.append(
                LoCoMoQARow(
                    sample_id=sample_id,
                    question_id=f"{sample_id}::qa_{qa_index:04d}",
                    qa_index=qa_index,
                    category=category,
                    question_type=question_type,
                    question=str(qa["question"]),
                    answer=None if qa.get("answer") is None else str(qa["answer"]),
                    evidence_dialog_ids=tuple(evidence_dialog_ids),
                    evidence_session_ids=tuple(ordered_unique(dialog_id_to_session_id(item) for item in evidence_dialog_ids)),
                    sessions=sessions,
                    turns=turns,
                    observations=observations,
                )
            )
    return rows


def parse_sessions(conversation: Dict[str, object], session_summary: Dict[str, object]) -> Tuple[Session, ...]:
    session_indices = sorted(
        int(match.group(1))
        for key in conversation
        for match in [re.fullmatch(r"session_(\d+)", key)]
        if match is not None
    )
    sessions: List[Session] = []
    for session_index in session_indices:
        session_key = f"session_{session_index}"
        raw_turns = conversation.get(session_key, [])
        if not isinstance(raw_turns, list):
            continue
        date_time = str(conversation.get(f"{session_key}_date_time", ""))
        session_id = f"S{session_index}"
        turns: List[DialogTurn] = []
        for raw_turn in raw_turns:
            if not isinstance(raw_turn, dict):
                continue
            dia_id = str(raw_turn.get("dia_id", ""))
            if not dia_id:
                continue
            turns.append(
                DialogTurn(
                    dia_id=dia_id,
                    session_id=session_id,
                    session_index=session_index,
                    session_date_time=date_time,
                    speaker=str(raw_turn.get("speaker", "unknown")),
                    text=str(raw_turn.get("text", raw_turn.get("clean_text", raw_turn.get("compressed_text", "")))),
                    image_caption=str(raw_turn.get("blip_caption", raw_turn.get("caption", "")) or ""),
                    image_query=str(raw_turn.get("query", raw_turn.get("search_query", "")) or ""),
                )
            )
        sessions.append(
            Session(
                session_id=session_id,
                session_index=session_index,
                date_time=date_time,
                turns=tuple(turns),
                session_summary=str(session_summary.get(f"{session_key}_summary", "") or ""),
            )
        )
    return tuple(sessions)


def parse_observations(raw_observations: Dict[str, object]) -> Tuple[Observation, ...]:
    observations: List[Observation] = []
    for key, raw_session_observation in raw_observations.items():
        match = re.fullmatch(r"session_(\d+)_observation", str(key))
        if match is None or not isinstance(raw_session_observation, dict):
            continue
        session_index = int(match.group(1))
        session_id = f"S{session_index}"
        for speaker, raw_items in raw_session_observation.items():
            if not isinstance(raw_items, list):
                continue
            for raw_item in raw_items:
                if not isinstance(raw_item, list) or not raw_item:
                    continue
                text = str(raw_item[0])
                dialog_ids = normalize_dialog_ids(raw_item[1:] if len(raw_item) > 1 else [])
                if not text or not dialog_ids:
                    continue
                observations.append(
                    Observation(
                        session_id=session_id,
                        session_index=session_index,
                        speaker=str(speaker),
                        text=text,
                        dialog_ids=tuple(dialog_ids),
                    )
                )
    return tuple(observations)


def normalize_question_type(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "single": "single-hop",
        "single-hop-qa": "single-hop",
        "multi": "multi-hop",
        "multi-hop-qa": "multi-hop",
        "time": "temporal",
        "temporal-reasoning": "temporal",
        "commonsense": "open-domain",
        "common-sense": "open-domain",
        "open-domain-knowledge": "open-domain",
        "world-knowledge": "open-domain",
        "commonsense-world-knowledge": "open-domain",
        "false-premise": "adversarial",
    }
    return aliases.get(normalized, normalized)


def select_rows(
    rows: Sequence[LoCoMoQARow],
    question_types: Sequence[str],
    limit: int,
    limit_per_type: int,
    selection_strategy: str = "round_robin",
) -> List[LoCoMoQARow]:
    selected = list(rows)
    if question_types:
        allowed = {normalize_question_type(item) for item in question_types}
        selected = [row for row in selected if row.question_type in allowed]
    if limit_per_type:
        if selection_strategy == "sequential":
            selected = limit_rows_per_type_sequential(selected, limit_per_type)
        elif selection_strategy == "round_robin":
            selected = limit_rows_per_type_round_robin(selected, limit_per_type)
        else:
            raise ValueError(f"unsupported selection_strategy={selection_strategy}")
    if limit:
        selected = selected[:limit]
    return selected


def limit_rows_per_type_sequential(rows: Sequence[LoCoMoQARow], limit_per_type: int) -> List[LoCoMoQARow]:
    counts: Counter[str] = Counter()
    selected: List[LoCoMoQARow] = []
    for row in rows:
        if counts[row.question_type] >= limit_per_type:
            continue
        selected.append(row)
        counts[row.question_type] += 1
    return selected


def limit_rows_per_type_round_robin(rows: Sequence[LoCoMoQARow], limit_per_type: int) -> List[LoCoMoQARow]:
    type_order: List[str] = []
    sample_order_by_type: Dict[str, List[str]] = defaultdict(list)
    rows_by_type_sample: Dict[str, Dict[str, List[LoCoMoQARow]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.question_type not in type_order:
            type_order.append(row.question_type)
        if row.sample_id not in rows_by_type_sample[row.question_type]:
            sample_order_by_type[row.question_type].append(row.sample_id)
        rows_by_type_sample[row.question_type][row.sample_id].append(row)

    selected: List[LoCoMoQARow] = []
    for question_type in type_order:
        picks: List[LoCoMoQARow] = []
        sample_order = sample_order_by_type[question_type]
        sample_rows = rows_by_type_sample[question_type]
        round_index = 0
        while len(picks) < limit_per_type:
            added = False
            for sample_id in sample_order:
                rows_for_sample = sample_rows[sample_id]
                if round_index >= len(rows_for_sample):
                    continue
                picks.append(rows_for_sample[round_index])
                added = True
                if len(picks) >= limit_per_type:
                    break
            if not added:
                break
            round_index += 1
        selected.extend(picks)
    return selected


def sample_counts_by_question_type(rows: Sequence[LoCoMoQARow]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts[row.question_type][row.sample_id] += 1
    return {question_type: dict(counter) for question_type, counter in sorted(counts.items())}


def canonical_term(term: str) -> str:
    if term.endswith("ies") and len(term) > 4:
        return term[:-3] + "y"
    if term.endswith("ing") and len(term) > 5:
        return term[:-3]
    if term.endswith("ed") and len(term) > 4:
        return term[:-2]
    if term.endswith("s") and len(term) > 4:
        return term[:-1]
    return term


def tokenized(text: str) -> List[str]:
    return [canonical_term(term) for term in re.findall(r"[a-zA-Z0-9_']+", text.lower())]


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "did",
    "do",
    "does",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
}

QUERY_EXPANSIONS = {
    "adoption": ("agency", "agencies", "family", "children", "kids"),
    "activity": ("activities", "hobby", "hobbies", "bowling", "cooking", "game", "games"),
    "charity": ("race", "mental", "health", "awareness"),
    "country": ("city", "trip", "travel", "visiting", "boston", "jasper", "paris", "tokyo"),
    "dog": ("puppy", "pet", "toby", "treats"),
    "field": ("fields", "education", "career", "psychology", "counseling", "mental", "health"),
    "financial": ("wealthy", "middle-class", "resources", "kids", "having", "lot", "afford"),
    "friend": ("friends", "team", "teammates", "group"),
    "health": ("weight", "obesity", "exercise", "run", "doctor", "fitness"),
    "indoor": ("cooking", "recipes", "hobbies", "dog", "puppy", "treats"),
    "lewis": ("fantasy", "magical", "harry", "potter", "books"),
    "problem": ("problems", "weight", "obesity", "exercise", "run"),
    "research": ("researching", "searched", "search", "looked", "looking"),
    "status": ("wealthy", "middle-class", "resources", "kids", "having", "lot", "afford"),
    "support": ("supported", "supportive", "community", "group"),
    "work": ("job", "career", "project", "office"),
    "school": ("class", "education", "student", "students"),
    "book": ("books", "reading", "fantasy", "magical", "harry", "potter"),
    "meet": ("meeting", "planned", "plan", "go", "join", "pub", "game", "vr"),
    "plann": ("plan", "meet", "go", "join", "pub", "game", "vr"),
    "family": ("kids", "children", "husband", "parent"),
}

MONTH_TO_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

NUM_TO_MONTH = {value: key for key, value in MONTH_TO_NUM.items()}


def extract_calendar_dates(text: str) -> List[date]:
    dates: List[date] = []
    month_names = "|".join(MONTH_TO_NUM)
    patterns = (
        rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{month_names}),?\s+(?P<year>\d{{4}})\b",
        rf"\b(?P<month>{month_names})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>\d{{4}})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text.lower()):
            try:
                dates.append(
                    date(
                        int(match.group("year")),
                        MONTH_TO_NUM[match.group("month")],
                        int(match.group("day")),
                    )
                )
            except ValueError:
                continue
    return dates


def extract_month_year_terms(text: str) -> Tuple[set[int], set[int]]:
    lowered = text.lower()
    months = {number for name, number in MONTH_TO_NUM.items() if re.search(rf"\b{name}\b", lowered)}
    years = {int(year) for year in re.findall(r"\b(20\d{2})\b", lowered)}
    return months, years


def important_query_terms(question: str) -> List[str]:
    return [term for term in tokenized(question) if len(term) > 1 and term not in STOPWORDS]


def retrieval_query(row: LoCoMoQARow, expand: bool) -> str:
    if not expand:
        return row.question
    terms = tokenized(row.question)
    expanded = list(terms)
    for term in terms:
        expanded.extend(QUERY_EXPANSIONS.get(term, ()))
    return row.question + " " + " ".join(expanded)


def turn_text(turn: DialogTurn, include_id: bool = True) -> str:
    prefix = f"{turn.dia_id} " if include_id else ""
    parts = [f"{prefix}{turn.speaker}: {turn.text}"]
    if turn.image_caption:
        parts.append(f"Image caption: {turn.image_caption}")
    if turn.image_query:
        parts.append(f"Image search query: {turn.image_query}")
    return "\n".join(parts)


def document_text(turn: DialogTurn) -> str:
    return f"{turn.speaker} {turn.text} {turn.image_caption} {turn.image_query}"


def select_dialog_ids(row: LoCoMoQARow, variant: str, top_k: int) -> List[str]:
    if variant == "oracle_dialog":
        return list(row.evidence_dialog_ids)
    if variant == "recent_dialog":
        return [turn.dia_id for turn in row.turns[-top_k:]]
    if variant == "full_history":
        return [turn.dia_id for turn in row.turns]
    if variant == "bm25_dialog":
        return bm25_top_dialog_ids(
            row,
            top_k,
            query_text=retrieval_query(row, expand=False),
        )
    if variant == "scope_time_state_task_adapter":
        return hybrid_memory_top_dialog_ids(row, top_k, query_text=retrieval_query(row, expand=True))
    raise ValueError(f"unsupported variant: {variant}")


def dialog_sort_key(dialog_id: str) -> Tuple[int, int]:
    match = re.fullmatch(r"D(\d+):(\d+)", dialog_id)
    if not match:
        return (10**9, 10**9)
    return (int(match.group(1)), int(match.group(2)))


def expand_dialog_window(
    row: LoCoMoQARow,
    seed_dialog_ids: Sequence[str],
    window_turns: int,
) -> List[str]:
    if window_turns <= 0:
        return ordered_unique(seed_dialog_ids)
    turns_by_session: Dict[int, List[DialogTurn]] = defaultdict(list)
    for turn in row.turns:
        turns_by_session[turn.session_index].append(turn)
    index_by_id: Dict[str, Tuple[int, int]] = {}
    for session_index, turns in turns_by_session.items():
        for index, turn in enumerate(turns):
            index_by_id[turn.dia_id] = (session_index, index)

    expanded: List[str] = []
    for seed_id in seed_dialog_ids:
        location = index_by_id.get(seed_id)
        if location is None:
            continue
        session_index, turn_index = location
        session_turns = turns_by_session[session_index]
        start = max(0, turn_index - window_turns)
        end = min(len(session_turns), turn_index + window_turns + 1)
        for turn in session_turns[start:end]:
            if turn.dia_id not in expanded:
                expanded.append(turn.dia_id)
    return expanded


def bm25_scores(query_text: str, documents: Sequence[str]) -> List[Tuple[float, int]]:
    doc_terms = [Counter(tokenized(doc)) for doc in documents]
    query_terms = Counter(tokenized(query_text))
    if not query_terms:
        return [(0.0, index) for index in range(len(documents))]
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
    return scores


def bm25_top_dialog_ids(row: LoCoMoQARow, top_k: int, query_text: Optional[str] = None) -> List[str]:
    documents = [document_text(turn) for turn in row.turns]
    scores = bm25_scores(query_text or row.question, documents)
    return [row.turns[index].dia_id for _, index in scores[:top_k]]


def session_time_relevance(question: str, session: Session) -> float:
    question_months, question_years = extract_month_year_terms(question)
    session_months, session_years = extract_month_year_terms(session.date_time)
    score = 0.0
    if question_months & session_months:
        score += 6.0
    if question_years & session_years:
        score += 4.0
    question_dates = extract_calendar_dates(question)
    session_dates = extract_calendar_dates(session.date_time)
    for question_date in question_dates:
        for session_date in session_dates:
            distance = abs((session_date - question_date).days)
            if distance == 0:
                score += 12.0
            elif distance <= 1:
                score += 10.0
            elif distance <= 7:
                score += 4.0
    return score


def ranked_public_memory_entries(row: LoCoMoQARow, query_text: str) -> List[Tuple[float, int, str]]:
    entries: List[Tuple[str, str]] = []
    for observation in row.observations:
        dialog_ids = ", ".join(observation.dialog_ids)
        entries.append(
            (
                f"{observation.speaker} {observation.text} {dialog_ids}",
                (
                    f'<observation session_id="{observation.session_id}" speaker="{observation.speaker}" '
                    f'dialog_ids="{dialog_ids}">\n'
                    f"{observation.text}\n"
                    "</observation>"
                ),
            )
        )
    for session in row.sessions:
        if not session.session_summary:
            continue
        session_dialog_range = ""
        if session.turns:
            session_dialog_range = f"{session.turns[0].dia_id}-{session.turns[-1].dia_id}"
        entries.append(
            (
                f"{session.date_time} {session.session_summary} {session_dialog_range}",
                (
                    f'<session_summary session_id="{session.session_id}" date="{session.date_time}" '
                    f'dialog_range="{session_dialog_range}">\n'
                    f"{session.session_summary}\n"
                    "</session_summary>"
                ),
            )
        )
    if not entries:
        return []
    scores = bm25_scores(query_text, [score_text for score_text, _ in entries])
    session_summary_offset = len(row.observations)
    enriched: List[Tuple[float, int, str]] = []
    for score, index in scores:
        if index >= session_summary_offset:
            session = row.sessions[index - session_summary_offset]
            score += session_time_relevance(query_text, session)
        enriched.append((score, index, entries[index][1]))
    return sorted(enriched, key=lambda item: (-item[0], item[1]))


def build_public_memory_context(row: LoCoMoQARow, query_text: str, max_memory_chars: int, top_n: int) -> str:
    chunks: List[str] = []
    total_chars = 0
    ranked_entries = ranked_public_memory_entries(row, query_text)[:top_n]
    if not ranked_entries:
        return ""
    for rank, (score, _index, body) in enumerate(ranked_entries, start=1):
        score_attr = f"{score:.4f}"
        chunk = f'<memory_entry rank="{rank}" score="{score_attr}">\n{body}\n</memory_entry>'
        remaining = max_memory_chars - total_chars
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            if chunks and remaining < 600:
                break
            chunk = chunk[:remaining] + "\n[MEMORY_CONTEXT_TRUNCATED]"
        chunks.append(chunk)
        total_chars += len(chunk)
    return "\n\n".join(chunks)


def hybrid_memory_top_dialog_ids(row: LoCoMoQARow, top_k: int, query_text: str) -> List[str]:
    turns_by_id = {turn.dia_id: turn for turn in row.turns}
    turn_documents = [document_text(turn) for turn in row.turns]
    turn_scores = bm25_scores(query_text, turn_documents)
    score_by_dialog: Dict[str, float] = {}

    for score, index in turn_scores[: max(top_k * 2, top_k)]:
        if score <= 0:
            continue
        score_by_dialog[row.turns[index].dia_id] = max(score_by_dialog.get(row.turns[index].dia_id, 0.0), score)

    observation_documents = [
        f"{observation.speaker}: {observation.text}"
        for observation in row.observations
    ]
    for score, index in bm25_scores(query_text, observation_documents):
        if score <= 0:
            continue
        observation = row.observations[index]
        for dialog_id in observation.dialog_ids:
            if dialog_id in turns_by_id:
                score_by_dialog[dialog_id] = max(score_by_dialog.get(dialog_id, 0.0), score * 1.6)

    session_score_by_index: Dict[int, float] = {}
    session_summaries = [session.session_summary for session in row.sessions]
    for score, index in bm25_scores(query_text, session_summaries):
        score += session_time_relevance(query_text, row.sessions[index])
        if score <= 0:
            continue
        session_score_by_index[row.sessions[index].session_index] = score

    if session_score_by_index:
        turn_score_by_dialog = {row.turns[index].dia_id: score for score, index in turn_scores}
        turns_by_session: Dict[int, List[DialogTurn]] = defaultdict(list)
        for turn in row.turns:
            turns_by_session[turn.session_index].append(turn)
        for session_index, session_score in session_score_by_index.items():
            session_turns = turns_by_session.get(session_index, [])
            ranked_session_turns = sorted(
                session_turns,
                key=lambda turn: (-turn_score_by_dialog.get(turn.dia_id, 0.0), dialog_sort_key(turn.dia_id)),
            )
            first_turns = session_turns[:8]
            for turn in first_turns:
                blended_score = session_score * 1.2 + turn_score_by_dialog.get(turn.dia_id, 0.0)
                score_by_dialog[turn.dia_id] = max(score_by_dialog.get(turn.dia_id, 0.0), blended_score)
            for turn in ranked_session_turns[:12]:
                blended_score = session_score * 0.8 + turn_score_by_dialog.get(turn.dia_id, 0.0)
                score_by_dialog[turn.dia_id] = max(score_by_dialog.get(turn.dia_id, 0.0), blended_score)
            if session_score < 8.0:
                continue
            # A high time/session-summary match often means the discriminating fact is expressed with
            # a weak lexical cue such as "yesterday"; include the full session before final top-k trimming.
            for turn in sorted(
                turns_by_session.get(session_index, []),
                key=lambda turn: dialog_sort_key(turn.dia_id),
            ):
                blended_score = session_score * 0.25 + turn_score_by_dialog.get(turn.dia_id, 0.0)
                score_by_dialog[turn.dia_id] = max(score_by_dialog.get(turn.dia_id, 0.0), blended_score)

    ranked = sorted(score_by_dialog.items(), key=lambda item: (-item[1], dialog_sort_key(item[0])))
    if len(ranked) < top_k:
        for score, index in turn_scores:
            dialog_id = row.turns[index].dia_id
            if dialog_id in score_by_dialog:
                continue
            ranked.append((dialog_id, score))
            if len(ranked) >= top_k:
                break
    return [dialog_id for dialog_id, _ in ranked[:top_k]]


def build_context(
    row: LoCoMoQARow,
    selected_dialog_ids: Sequence[str],
    max_context_chars: int,
    max_dialog_chars: int,
    include_session_summary: bool,
    ranked: bool,
) -> str:
    turns_by_id = {turn.dia_id: turn for turn in row.turns}
    sessions_by_id = {session.session_id: session for session in row.sessions}
    chunks: List[str] = []
    total_chars = 0
    dialog_ids = selected_dialog_ids if ranked else [turn.dia_id for turn in row.turns if turn.dia_id in set(selected_dialog_ids)]
    for rank, dia_id in enumerate(dialog_ids, start=1):
        turn = turns_by_id.get(dia_id)
        if turn is None:
            continue
        body = turn_text(turn)
        if len(body) > max_dialog_chars:
            body = body[:max_dialog_chars] + "\n[TRUNCATED]"
        session = sessions_by_id.get(turn.session_id)
        summary = ""
        if include_session_summary and session is not None and session.session_summary:
            summary = f"\nSession summary: {session.session_summary[:900]}"
        rank_attr = f' retrieval_rank="{rank}"' if ranked else ""
        chunk = (
            f'<dialog id="{turn.dia_id}" session_id="{turn.session_id}" date="{turn.session_date_time}"{rank_attr}>\n'
            f"{body}{summary}\n"
            "</dialog>"
        )
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
    if variant == "scope_time_state_task_adapter":
        return answer_system_prompt(adapter)
    return (
        "You answer LoCoMo QA questions using only the provided conversation text, session dates, "
        "and text metadata from image captions or image search queries. Do not use image URLs directly. "
        "Return strict JSON with keys answer and evidence_dialog_ids. "
        "Cite only dialog IDs that directly support the answer. "
        "Keep answer as a short gold-style phrase, date, name, or comma-separated list; do not add explanation unless required. "
        "For false-premise or unavailable information, answer \"No information available\" or "
        "\"Not mentioned in the conversation\"."
    )


def user_prompt(row: LoCoMoQARow, variant: str, context: str, adapter: TaskAdapter) -> str:
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: {variant}\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Official category: {row.category}\n"
        f"Question type: {row.question_type}\n"
        f"Task adapter: {adapter.task_name}\n"
        f"Task instruction: {adapter.instruction()}\n"
        f"Question: {row.question}\n\n"
        f"Conversation evidence candidates:\n{context}\n\n"
        "Respond as JSON only:\n"
        f"{adapter.response_schema(variant)}"
    )


def evidence_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the evidence extraction stage of a Scope-Time-State memory pipeline for LoCoMo QA. "
        "Use only the provided public LoCoMo memory index, candidate dialog turns, session dates, "
        "and text metadata from image captions/search queries. "
        "Do not answer the question yet. Select a small set of directly useful evidence snippets, preserving dialog IDs. "
        "Public observations and session summaries are allowed memory records; when an observation is relevant, "
        "carry forward its dialog_ids as the support. "
        "For misleading or false-premise questions, keep the turns that expose the contradiction or wrong speaker. "
        f"The active task adapter is {adapter.task_name}. Return strict JSON only."
    )


def answer_contract_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the question-analysis stage of a Scope-Time-State memory pipeline for LoCoMo QA. "
        "Use only the question text and task metadata. Do not use conversation evidence and do not answer the question. "
        "Produce a compact answer contract that downstream retrieval and evidence extraction can use to reject topical distractors. "
        f"The active task adapter is {adapter.task_name}. Return strict JSON only."
    )


def answer_contract_user_prompt(row: LoCoMoQARow, adapter: TaskAdapter) -> str:
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: scope_time_state_task_adapter answer contract\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Official category: {row.category}\n"
        f"Question type: {row.question_type}\n"
        f"Task instruction: {adapter.instruction()}\n"
        f"Question: {row.question}\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"subject\": \"exact entity or entities asked about\", "
        "\"relation\": \"specific relation/action/state requested\", "
        "\"time_scope\": \"date, month, range, ordering constraint, or none\", "
        "\"answer_type\": \"country|date|month|person|place|activity|field|status|health_condition|yes_no_with_reason|set|abstain|other\", "
        "\"cardinality\": \"single|set|yes_no_with_reason|abstain\", "
        "\"output_format\": \"short phrase|comma-separated set|yes/no plus reason|country|date|abstention\", "
        "\"must_include\": [\"semantic requirements, not gold answers\"], "
        "\"must_exclude\": [\"topical distractors or wrong relations\"], "
        "\"contract_rationale\": \"short explanation of the contract\""
        "}"
    )


def answer_contract_block(contract: Optional[Dict[str, object]]) -> str:
    if not contract:
        return ""
    return (
        "Question-only answer contract. Use this to filter evidence and answer format; if it conflicts with the literal "
        "question, prefer the literal question.\n"
        f"{json.dumps(contract, ensure_ascii=False, indent=2)}\n\n"
    )


def memory_router_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the public-memory routing stage of a Scope-Time-State memory pipeline for LoCoMo QA. "
        "Use only the provided public LoCoMo observation/session_summary records. Do not answer the question. "
        "Select dialog IDs and session IDs that are likely to contain direct evidence for the exact subject, relation, "
        "date, and answer type requested by the question. Prefer recall over precision, but reject merely topical records. "
        f"The active task adapter is {adapter.task_name}. Return strict JSON only."
    )


def memory_router_user_prompt(
    row: LoCoMoQARow,
    memory_context: str,
    adapter: TaskAdapter,
    contract: Optional[Dict[str, object]] = None,
) -> str:
    memory_block = memory_context or "[no public memory records selected]"
    contract_block = answer_contract_block(contract)
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: scope_time_state_task_adapter public-memory routing\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Official category: {row.category}\n"
        f"Question type: {row.question_type}\n"
        f"Routing instruction: {adapter.evidence_prompt_instruction()}\n"
        f"Question: {row.question}\n\n"
        f"{contract_block}"
        "Public memory index candidates from released LoCoMo observation/session_summary fields:\n"
        f"{memory_block}\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"routed_dialog_ids\": [\"D1:1\"], "
        "\"routed_session_ids\": [\"S1\"], "
        "\"rejected_memory_ranks\": [{\"rank\": 1, \"reason\": \"topical_distractor|wrong_subject|wrong_relation|wrong_time|unsupported\"}], "
        "\"routing_rationale\": \"short reason\""
        "}"
    )


def evidence_user_prompt(
    row: LoCoMoQARow,
    memory_context: str,
    context: str,
    adapter: TaskAdapter,
    contract: Optional[Dict[str, object]] = None,
) -> str:
    memory_block = memory_context or "[no public memory records selected]"
    contract_block = answer_contract_block(contract)
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: scope_time_state_task_adapter evidence extraction\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Official category: {row.category}\n"
        f"Question type: {row.question_type}\n"
        f"Evidence instruction: {adapter.evidence_prompt_instruction()}\n"
        f"Question: {row.question}\n\n"
        f"{contract_block}"
        "Public memory index candidates from the released LoCoMo observation/session_summary fields:\n"
        f"{memory_block}\n\n"
        f"Candidate raw dialog turns:\n{context}\n\n"
        "Evidence selection policy:\n"
        "- Select evidence for the exact subject, relation, date, and answer type asked by the question.\n"
        "- If an answer contract is provided, use its subject, relation, time_scope, answer_type, and cardinality to filter candidates.\n"
        "- Reject merely topical turns when they do not answer the requested relation.\n"
        "- For temporal questions, prioritize the session date and relative expressions such as yesterday, last week, last month, and first.\n"
        "- For open-domain questions, cite the conversation facts that license the outside-knowledge bridge, including image captions/search queries when relevant.\n"
        "- For multi-hop questions, include every distinct supporting fact needed for the final set; do not stop after one matching turn.\n"
        "- For multi-hop comparison questions, separate shared relations from merely shared topics.\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"relevant_dialog_ids\": [\"D1:1\"], "
        "\"evidence_snippets\": ["
        "{\"dialog_id\": \"D1:1\", \"session_id\": \"S1\", \"date\": \"...\", "
        "\"speaker\": \"...\", \"content\": \"short quote or faithful summary\", \"why_relevant\": \"...\"}"
        "], "
        "\"state_facets\": [{\"name\": \"...\", \"value\": \"...\", \"support_dialog_ids\": [\"D1:1\"]}], "
        "\"rejected_claims\": [{\"claim\": \"...\", \"reason\": \"stale|contradicted|wrong_speaker|unsupported|irrelevant\", "
        "\"support_dialog_ids\": [\"D1:1\"]}], "
        "\"enough_evidence\": true"
        "}"
    )


def answer_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the answer composition stage of a Scope-Time-State memory pipeline for LoCoMo QA. "
        "Use only the extracted evidence JSON. You may use ordinary commonsense or stable world knowledge only for "
        "the open-domain task adapter, and only as a bridge from cited conversation evidence. "
        "Return strict JSON with answer, evidence_dialog_ids, state_facets, rejected_claims, and answer_rationale. "
        "Put explanation in answer_rationale, not in answer. Keep answer as a short gold-style phrase, date, name, "
        "or comma-separated list. Prefer full canonical names over abbreviations. "
        "For false-premise or unavailable information, answer \"No information available\" or "
        "\"Not mentioned in the conversation\". "
        f"The active task adapter is {adapter.task_name}."
    )


def answer_user_prompt(
    row: LoCoMoQARow,
    extraction: Dict[str, object],
    adapter: TaskAdapter,
    memory_context: str = "",
    context: str = "",
    contract: Optional[Dict[str, object]] = None,
) -> str:
    evidence_json = json.dumps(extraction, ensure_ascii=False, indent=2)
    contract_block = answer_contract_block(contract)
    candidate_context = ""
    if memory_context or context:
        candidate_context = (
            "Use the extracted evidence JSON first. If it is incomplete, contradicted, or only topically related, "
            "you may correct it using the same public candidates below. Cite any corrected dialog IDs in evidence_dialog_ids.\n\n"
            "Public memory index candidates:\n"
            f"{memory_context or '[no public memory records selected]'}\n\n"
            f"Candidate raw dialog turns:\n{context or '[no raw dialog candidates selected]'}\n\n"
        )
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: scope_time_state_task_adapter answer composition\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Official category: {row.category}\n"
        f"Question type: {row.question_type}\n"
        f"Answer instruction: {adapter.answer_prompt_instruction()}\n"
        f"Question: {row.question}\n\n"
        f"{contract_block}"
        f"Extracted evidence JSON:\n{evidence_json}\n\n"
        f"{candidate_context}"
        "Answer-format constraints:\n"
        "- Put only the final short answer in the answer field.\n"
        "- For multi-answer questions, include the complete requested set as comma-separated short phrases.\n"
        "- For multi-hop comparison questions, answer the shared relation/state requested by the question, not every shared topic.\n"
        "- For adversarial false-premise questions, answer exactly \"No information available\" unless the evidence directly supports the requested fact for the exact subject.\n"
        "- For adversarial what/which questions, abstain if the evidence only repeats the broad category from the question and does not name the requested specific value.\n"
        "- For temporal questions, compute relative dates from session dates before answering; if the question asks for a month, answer month and year only.\n"
        "- For questions asking for a country, infer the country from cited cities/places when needed, use full country names, and do not include city names unless asked.\n"
        "- For open-domain status, health, field, and identity questions, return the canonical label/entity implied by evidence, not a loose description of the evidence.\n"
        "- For open-domain yes/no questions, include a short evidence-grounded reason after the polarity rather than only yes or no.\n"
        "- For open-domain alternative questions, choose only the option supported by the cited conversation facts.\n"
        "- Do not include distractors or related but unasked facts in the answer field.\n"
        "- If the question wording starts with 'In what country', answer in the form 'In <country>'.\n\n"
        "Respond as JSON only:\n"
        f"{adapter.response_schema('scope_time_state_task_adapter')}"
    )


def verifier_system_prompt(adapter: TaskAdapter) -> str:
    return (
        "You are the verification stage of a Scope-Time-State memory pipeline for LoCoMo QA. "
        "Use only the provided public memory records, raw dialog candidates, extracted evidence, and draft answer. "
        "Your job is to catch missing evidence, topical distractors, wrong date arithmetic, wrong answer type, "
        "and incomplete multi-hop answer sets. Return strict JSON in the same final-answer schema. "
        f"The active task adapter is {adapter.task_name}."
    )


def verifier_user_prompt(
    row: LoCoMoQARow,
    memory_context: str,
    context: str,
    extraction: Dict[str, object],
    draft_output: Dict[str, object],
    adapter: TaskAdapter,
    contract: Optional[Dict[str, object]] = None,
) -> str:
    extraction_json = json.dumps(extraction, ensure_ascii=False, indent=2)
    draft_json = json.dumps(draft_output, ensure_ascii=False, indent=2)
    contract_block = answer_contract_block(contract)
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: scope_time_state_task_adapter verification\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Official category: {row.category}\n"
        f"Question type: {row.question_type}\n"
        f"Task adapter: {adapter.task_name}\n"
        f"Question: {row.question}\n\n"
        f"{contract_block}"
        "Public memory index candidates:\n"
        f"{memory_context or '[no public memory records selected]'}\n\n"
        f"Candidate raw dialog turns:\n{context}\n\n"
        f"Initial extracted evidence JSON:\n{extraction_json}\n\n"
        f"Initial draft answer JSON:\n{draft_json}\n\n"
        "Verification checklist:\n"
        "- Answer the exact question, not a nearby topical question.\n"
        "- If the draft cites a distractor, replace it with the candidate turns that directly support the requested relation.\n"
        "- If the question asks for a date/month/year/range, recompute it from session dates and relative expressions.\n"
        "- If the question asks for a country, infer the country from cited locations and answer only the country unless wording asks otherwise.\n"
        "- If the question asks for alternatives, choose only the supported alternative.\n"
        "- If the question asks for a set, include every distinct requested item supported by candidates and omit extras.\n"
        "- Keep the answer field concise; put reasoning only in answer_rationale.\n\n"
        "Respond as JSON only:\n"
        f"{adapter.response_schema('scope_time_state_task_adapter')}"
    )


def normalize_answer(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace(",", "")
    lowered = text.lower()
    lowered = lowered.translate(str.maketrans("", "", string.punctuation))
    lowered = re.sub(r"\b(a|an|the|and)\b", " ", lowered)
    return " ".join(lowered.split())


def stem_tokens(tokens: Sequence[str]) -> List[str]:
    try:
        from nltk.stem import PorterStemmer
    except ImportError:
        return list(tokens)
    stemmer = PorterStemmer()
    return [stemmer.stem(token) for token in tokens]


def official_f1_score(prediction: object, ground_truth: object) -> float:
    prediction_tokens = stem_tokens(normalize_answer(prediction).split())
    ground_truth_tokens = stem_tokens(normalize_answer(ground_truth).split())
    if not prediction_tokens or not ground_truth_tokens:
        return 0.0
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision_value = num_same / len(prediction_tokens)
    recall_value = num_same / len(ground_truth_tokens)
    return (2 * precision_value * recall_value) / (precision_value + recall_value)


def official_multi_answer_f1(prediction: object, ground_truth: object) -> float:
    predictions = [item.strip() for item in str(prediction).split(",")]
    ground_truths = [item.strip() for item in str(ground_truth).split(",")]
    if not ground_truths:
        return 0.0
    return sum(max(official_f1_score(pred, gold) for pred in predictions) for gold in ground_truths) / len(ground_truths)


def official_style_answer_score(row: LoCoMoQARow, hypothesis: str) -> float:
    if row.category == 5:
        lowered = hypothesis.lower()
        return 1.0 if "no information available" in lowered or "not mentioned" in lowered else 0.0
    answer = row.answer or ""
    if row.category == 3:
        answer = answer.split(";")[0].strip()
    if row.category == 1:
        return official_multi_answer_f1(hypothesis, answer)
    if row.category in {2, 3, 4}:
        return official_f1_score(hypothesis, answer)
    raise ValueError(f"unsupported LoCoMo category={row.category}")


def exact_match_score(prediction: object, ground_truth: object) -> bool:
    prediction_tokens = set(normalize_answer(prediction).split())
    ground_truth_tokens = set(normalize_answer(ground_truth).split())
    return bool(prediction_tokens) and prediction_tokens == ground_truth_tokens


def normalize_dialog_ids(value: object) -> List[str]:
    if value is None:
        return []
    items: List[object] = []

    def collect(raw: object) -> None:
        if isinstance(raw, (list, tuple)):
            for item in raw:
                collect(item)
        else:
            items.append(raw)

    collect(value)
    return ordered_unique(
        str(item).strip().replace("(", "").replace(")", "")
        for item in items
        if item not in {None, "", "null"}
    )


def ordered_unique(items: Iterable[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def dialog_id_to_session_id(dialog_id: str) -> str:
    match = re.match(r"D(\d+):", dialog_id)
    if not match:
        return ""
    return f"S{match.group(1)}"


def normalize_output_dialog_ids(value: object) -> List[str]:
    ids = normalize_dialog_ids(value)
    expanded: List[str] = []
    for item in ids:
        if "," in item:
            expanded.extend(part.strip() for part in item.split(","))
        else:
            expanded.append(item)
    return ordered_unique(item for item in expanded if re.match(r"D\d+:\d+", item))


def normalize_output_session_ids(value: object) -> List[str]:
    ids = normalize_dialog_ids(value)
    expanded: List[str] = []
    for item in ids:
        if "," in item:
            expanded.extend(part.strip() for part in item.split(","))
        else:
            expanded.append(item)
    return ordered_unique(item for item in expanded if re.fullmatch(r"S\d+", item))


def session_dialog_ids(row: LoCoMoQARow, session_ids: Sequence[str]) -> List[str]:
    allowed = set(session_ids)
    return [turn.dia_id for session in row.sessions if session.session_id in allowed for turn in session.turns]


def dialog_ids_from_text(text: str) -> List[str]:
    return ordered_unique(re.findall(r"D\d+:\d+", text))


def evidence_ids_from_extraction(extraction: Dict[str, object]) -> List[str]:
    ids: List[str] = []
    ids.extend(normalize_output_dialog_ids(extraction.get("relevant_dialog_ids")))
    snippets = extraction.get("evidence_snippets")
    if isinstance(snippets, list):
        for snippet in snippets:
            if isinstance(snippet, dict):
                ids.extend(normalize_output_dialog_ids(snippet.get("dialog_id")))
                ids.extend(normalize_output_dialog_ids(snippet.get("dialog_ids")))
    for field_name in ("state_facets", "rejected_claims"):
        items = extraction.get(field_name)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    ids.extend(normalize_output_dialog_ids(item.get("support_dialog_ids")))
    return ordered_unique(ids)


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


def f1_from_precision_recall(precision_value: Optional[float], recall_value: Optional[float]) -> Optional[float]:
    if precision_value is None or recall_value is None:
        return None
    if precision_value + recall_value == 0:
        return 0.0
    return 2 * precision_value * recall_value / (precision_value + recall_value)


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
        question_type: summarize_flat(type_rows)
        for question_type, type_rows in sorted(by_type.items())
    }
    summary = summarize_flat(rows)
    summary["task_averaged_answer_f1"] = mean(metrics["answer_f1"] for metrics in by_question_type.values())
    summary["by_question_type"] = by_question_type
    return summary


def summarize_flat(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    return {
        "n_cases": len(rows),
        "answer_f1": mean(float(row["answer_f1"]) for row in rows),
        "exact_match": mean(1.0 if row["exact_match"] else 0.0 for row in rows if row["category"] != 5),
        "candidate_dialog_recall": mean(row["candidate_dialog_recall"] for row in rows),
        "candidate_dialog_precision": mean(row["candidate_dialog_precision"] for row in rows),
        "candidate_session_recall": mean(row["candidate_session_recall"] for row in rows),
        "evidence_dialog_recall": mean(row["evidence_dialog_recall"] for row in rows),
        "evidence_dialog_precision": mean(row["evidence_dialog_precision"] for row in rows),
        "evidence_dialog_f1": mean(row["evidence_dialog_f1"] for row in rows),
    }


def format_metric(value: object) -> str:
    return f"{value:.3f}" if isinstance(value, float) else "n/a"


def print_summary(provider: str, model: str, results: Sequence[Dict[str, object]]) -> None:
    print("LoCoMo QA text-only benchmark")
    print(f"provider={provider} model={model}")
    print("NOTE: answer_f1 follows the public LoCoMo lexical F1 rules; category 5 is abstention-style.")
    print()
    print(
        f"{'variant':<31} {'n':>4} {'ans_f1':>8} {'task_avg':>9} {'cand_r':>8} "
        f"{'cand_p':>8} {'ev_r':>8} {'ev_p':>8} {'ev_f1':>8}"
    )
    print("-" * 105)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<31} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['answer_f1']):>8} "
            f"{format_metric(summary['task_averaged_answer_f1']):>9} "
            f"{format_metric(summary['candidate_dialog_recall']):>8} "
            f"{format_metric(summary['candidate_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_recall']):>8} "
            f"{format_metric(summary['evidence_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_f1']):>8}"
        )
    print()


def run_variant(
    client: LLMClient,
    rows: Sequence[LoCoMoQARow],
    variant: str,
    args: argparse.Namespace,
) -> Dict[str, object]:
    eval_rows: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        adapter = get_adapter(row.question_type)
        answer_contract: Optional[Dict[str, object]] = None
        if variant == "scope_time_state_task_adapter" and args.answer_contract:
            answer_contract = client.complete_json(
                answer_contract_system_prompt(adapter),
                answer_contract_user_prompt(row, adapter),
            )
        candidate_k = args.task_candidate_k if variant == "scope_time_state_task_adapter" else args.top_k
        retrieved_dialog_ids = select_dialog_ids(row, variant, candidate_k)
        selected_dialog_ids = expand_dialog_window(row, retrieved_dialog_ids, args.context_window_turns)
        evidence_extraction: Optional[Dict[str, object]] = None
        answer_verification: Optional[Dict[str, object]] = None
        initial_output: Optional[Dict[str, object]] = None
        memory_routing: Optional[Dict[str, object]] = None
        memory_context = ""
        memory_candidate_dialog_ids: List[str] = []
        routed_dialog_ids: List[str] = []
        routed_session_ids: List[str] = []
        if variant == "scope_time_state_task_adapter":
            memory_context = build_public_memory_context(
                row,
                retrieval_query(row, expand=True),
                args.max_memory_chars,
                args.memory_top_n,
            )
            memory_candidate_dialog_ids = dialog_ids_from_text(memory_context)
            if args.memory_router:
                memory_routing = client.complete_json(
                    memory_router_system_prompt(adapter),
                    memory_router_user_prompt(row, memory_context, adapter, answer_contract),
                )
                routed_dialog_ids = normalize_output_dialog_ids(
                    memory_routing.get("routed_dialog_ids", memory_routing.get("dialog_ids"))
                )
                routed_session_ids = normalize_output_session_ids(
                    memory_routing.get("routed_session_ids", memory_routing.get("session_ids"))
                )
                selected_dialog_ids = ordered_unique(
                    expand_dialog_window(row, retrieved_dialog_ids[: args.router_raw_candidate_k], args.context_window_turns)
                    + expand_dialog_window(row, routed_dialog_ids, args.router_dialog_window_turns)
                    + session_dialog_ids(row, routed_session_ids)
                )
            else:
                selected_dialog_ids = ordered_unique(
                    expand_dialog_window(row, retrieved_dialog_ids, args.context_window_turns)
                    + expand_dialog_window(row, memory_candidate_dialog_ids, args.memory_context_window_turns)
                )
            context = build_context(
                row,
                selected_dialog_ids,
                args.max_context_chars,
                args.task_max_dialog_chars,
                args.include_session_summary,
                ranked=True,
            )
            evidence_extraction = client.complete_json(
                evidence_system_prompt(adapter),
                evidence_user_prompt(row, memory_context, context, adapter, answer_contract),
            )
            extraction_dialog_ids = evidence_ids_from_extraction(evidence_extraction)
            selected_dialog_ids = ordered_unique(
                list(selected_dialog_ids) + memory_candidate_dialog_ids + extraction_dialog_ids
            )
            output = client.complete_json(
                answer_system_prompt(adapter),
                answer_user_prompt(
                    row,
                    evidence_extraction,
                    adapter,
                    memory_context if args.answer_with_context else "",
                    context if args.answer_with_context else "",
                    answer_contract,
                ),
            )
            initial_output = dict(output)
            if args.answer_verifier:
                answer_verification = client.complete_json(
                    verifier_system_prompt(adapter),
                    verifier_user_prompt(row, memory_context, context, evidence_extraction, output, adapter, answer_contract),
                )
                output = answer_verification
        else:
            context = build_context(
                row,
                selected_dialog_ids,
                args.max_context_chars,
                args.max_dialog_chars,
                args.include_session_summary,
                ranked=variant != "full_history",
            )
            output = client.complete_json(system_prompt(variant, adapter), user_prompt(row, variant, context, adapter))
        hypothesis = str(output.get("answer", "")).strip()
        if variant == "scope_time_state_task_adapter":
            evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
            if not evidence_dialog_ids and evidence_extraction is not None:
                evidence_dialog_ids = evidence_ids_from_extraction(evidence_extraction)
        else:
            evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
            if not evidence_dialog_ids:
                evidence_dialog_ids = list(selected_dialog_ids)
        candidate_session_ids = ordered_unique(dialog_id_to_session_id(item) for item in selected_dialog_ids)
        evidence_session_ids = ordered_unique(dialog_id_to_session_id(item) for item in evidence_dialog_ids)
        evidence_dialog_precision = precision(evidence_dialog_ids, row.evidence_dialog_ids)
        evidence_dialog_recall = recall(evidence_dialog_ids, row.evidence_dialog_ids)
        eval_rows.append(
            {
                "question_id": row.question_id,
                "sample_id": row.sample_id,
                "qa_index": row.qa_index,
                "category": row.category,
                "question_type": row.question_type,
                "task_adapter": adapter.task_name,
                "question": row.question,
                "gold_answer": row.answer,
                "hypothesis": hypothesis,
                "retrieved_dialog_ids": list(retrieved_dialog_ids),
                "memory_candidate_dialog_ids": list(memory_candidate_dialog_ids),
                "routed_dialog_ids": list(routed_dialog_ids),
                "routed_session_ids": list(routed_session_ids),
                "candidate_dialog_ids": list(selected_dialog_ids),
                "candidate_session_ids": candidate_session_ids,
                "evidence_dialog_ids": evidence_dialog_ids,
                "evidence_session_ids": evidence_session_ids,
                "gold_evidence_dialog_ids": list(row.evidence_dialog_ids),
                "gold_evidence_session_ids": list(row.evidence_session_ids),
                "candidate_dialog_recall": recall(selected_dialog_ids, row.evidence_dialog_ids),
                "candidate_dialog_precision": precision(selected_dialog_ids, row.evidence_dialog_ids),
                "candidate_session_recall": recall(candidate_session_ids, row.evidence_session_ids),
                "evidence_dialog_recall": evidence_dialog_recall,
                "evidence_dialog_precision": evidence_dialog_precision,
                "evidence_dialog_f1": f1_from_precision_recall(evidence_dialog_precision, evidence_dialog_recall),
                "answer_f1": official_style_answer_score(row, hypothesis),
                "exact_match": exact_match_score(hypothesis, row.answer) if row.category != 5 else False,
                "state_facets": output.get("state_facets") if variant == "scope_time_state_task_adapter" else None,
                "rejected_claims": output.get("rejected_claims") if variant == "scope_time_state_task_adapter" else None,
                "answer_rationale": output.get("answer_rationale") if variant == "scope_time_state_task_adapter" else None,
                "answer_contract": answer_contract,
                "memory_routing": memory_routing,
                "evidence_extraction": evidence_extraction,
                "initial_output": initial_output,
                "answer_verification": answer_verification,
                "public_memory_context_chars": len(memory_context),
            }
        )
        print(f"[{variant}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    return {"variant": variant, "summary": summarize(eval_rows), "rows": eval_rows}


def validate_selection(rows: Sequence[LoCoMoQARow]) -> Optional[str]:
    unknown = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unknown:
        return f"unsupported question types in selection: {unknown}"
    if not rows:
        return "empty selection; check --question-types/--limit-cases"
    return None


def main() -> int:
    args = parse_args()
    if args.list_tasks:
        for question_type in sorted(TASK_TYPES):
            adapter = get_adapter(question_type)
            print(f"{question_type}\tcategory={adapter.category}\t{adapter.task_name}")
        return 0
    for variant in args.variants:
        if variant not in SUPPORTED_VARIANTS:
            print(f"unsupported variant: {variant}; supported: {', '.join(SUPPORTED_VARIANTS)}", file=sys.stderr)
            return 2

    rows = select_rows(
        load_rows(Path(args.data)),
        args.question_types,
        args.limit_cases,
        args.limit_per_type,
        args.selection_strategy,
    )
    validation_error = validate_selection(rows)
    if validation_error:
        print(validation_error, file=sys.stderr)
        return 2
    question_types = Counter(row.question_type for row in rows)
    categories = Counter(row.category for row in rows)
    if args.dry_run:
        print(
            f"valid LoCoMo QA data: rows={len(rows)} variants={','.join(args.variants)} "
            f"question_types={dict(question_types)} categories={dict(categories)} "
            f"selection_strategy={args.selection_strategy}"
        )
        print(f"sample_counts_by_question_type={sample_counts_by_question_type(rows)}")
        print(f"data_path={Path(args.data)}")
        return 0

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

    try:
        results = [run_variant(client, rows, variant, args) for variant in args.variants]
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = {
        "benchmark": "LoCoMo QA",
        "data_path": str(Path(args.data)),
        "provider": args.provider,
        "model": model,
        "variants": list(args.variants),
        "top_k": args.top_k,
        "task_candidate_k": args.task_candidate_k,
        "max_memory_chars": args.max_memory_chars,
        "memory_top_n": args.memory_top_n,
        "context_window_turns": args.context_window_turns,
        "memory_context_window_turns": args.memory_context_window_turns,
        "memory_router": args.memory_router,
        "router_raw_candidate_k": args.router_raw_candidate_k,
        "router_dialog_window_turns": args.router_dialog_window_turns,
        "answer_contract": args.answer_contract,
        "answer_verifier": args.answer_verifier,
        "answer_with_context": args.answer_with_context,
        "include_session_summary": args.include_session_summary,
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "selection_strategy": args.selection_strategy,
        "sample_counts_by_question_type": sample_counts_by_question_type(rows),
        "question_types": dict(question_types),
        "categories": dict(categories),
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
                        {
                            "question_id": row["question_id"],
                            "sample_id": row["sample_id"],
	                            "qa_index": row["qa_index"],
	                            "category": row["category"],
	                            "question_type": row["question_type"],
	                            "hypothesis": row["hypothesis"],
	                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


BENCHMARK_DIR = Path(__file__).resolve().parents[2]
DATA_PATH = BENCHMARK_DIR / "data/locomo10.json"


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


@dataclass(frozen=True)
class LoCoMoSample:
    sample_id: str
    sessions: Tuple[Session, ...]
    turns: Tuple[DialogTurn, ...]


@dataclass(frozen=True)
class LoCoMoQAItem:
    sample_id: str
    question_id: str
    qa_index: int
    category: int
    question_type: str
    question: str
    answer: Optional[str]
    evidence_dialog_ids: Tuple[str, ...]
    evidence_session_ids: Tuple[str, ...]


CATEGORY_TO_QUESTION_TYPE = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}


def load_samples(path: Path = DATA_PATH) -> List[LoCoMoSample]:
    raw_samples = json.loads(path.read_text())
    samples: List[LoCoMoSample] = []
    for raw_sample in raw_samples:
        sample = dict(raw_sample)
        sample_id = str(sample["sample_id"])
        sessions = parse_sessions(dict(sample["conversation"]))
        turns = tuple(turn for session in sessions for turn in session.turns)
        samples.append(LoCoMoSample(sample_id=sample_id, sessions=sessions, turns=turns))
    return samples


def load_sample(path: Path = DATA_PATH, sample_id: str = "conv-26") -> LoCoMoSample:
    samples = load_samples(path)
    for sample in samples:
        if sample.sample_id == sample_id:
            return sample
    available = ", ".join(sample.sample_id for sample in samples)
    raise ValueError(f"sample_id={sample_id!r} not found in {path}; available: {available}")


def load_sample_qa(path: Path = DATA_PATH, sample_id: str = "conv-26") -> List[LoCoMoQAItem]:
    raw_samples = json.loads(path.read_text())
    for raw_sample in raw_samples:
        sample = dict(raw_sample)
        if str(sample.get("sample_id")) != sample_id:
            continue
        rows: List[LoCoMoQAItem] = []
        for qa_index, qa in enumerate(sample.get("qa", [])):
            if not isinstance(qa, dict):
                continue
            category = int(qa["category"])
            evidence_dialog_ids = tuple(normalize_dialog_ids(qa.get("evidence")))
            rows.append(
                LoCoMoQAItem(
                    sample_id=sample_id,
                    question_id=f"{sample_id}::qa_{qa_index:04d}",
                    qa_index=qa_index,
                    category=category,
                    question_type=CATEGORY_TO_QUESTION_TYPE.get(category, f"category-{category}"),
                    question=str(qa["question"]),
                    answer=None if qa.get("answer") is None else str(qa["answer"]),
                    evidence_dialog_ids=evidence_dialog_ids,
                    evidence_session_ids=tuple(ordered_unique(dialog_id_to_session_id(item) for item in evidence_dialog_ids)),
                )
            )
        return rows
    available = ", ".join(str(sample.get("sample_id")) for sample in raw_samples)
    raise ValueError(f"sample_id={sample_id!r} not found in {path}; available: {available}")


def parse_sessions(conversation: Dict[str, object]) -> Tuple[Session, ...]:
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
        sessions.append(Session(session_id=session_id, session_index=session_index, date_time=date_time, turns=tuple(turns)))
    return tuple(sessions)


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


def dialog_sort_key(dialog_id: str) -> Tuple[int, int]:
    match = re.fullmatch(r"D(\d+):(\d+)", dialog_id)
    if not match:
        return (10**9, 10**9)
    return (int(match.group(1)), int(match.group(2)))


def sample_turns_by_id(sample: LoCoMoSample, turns: Sequence[DialogTurn] | None = None) -> Dict[str, DialogTurn]:
    source = sample.turns if turns is None else turns
    return {turn.dia_id: turn for turn in source}

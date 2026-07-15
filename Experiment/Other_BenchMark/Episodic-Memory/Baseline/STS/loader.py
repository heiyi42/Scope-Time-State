"""Stage-separated loaders for the fixed EPBench Long Book corpus."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .config import BOOK_PATH, QA_PATH


CHAPTER_RE = re.compile(
    r"(?:\A|\n)Chapter\s+(\d+)\s*\n\n(.*?)(?=\nChapter\s+\d+\s*\n\n|\Z)",
    re.DOTALL,
)


@dataclass(frozen=True)
class Chapter:
    chapter_id: int
    text: str


@dataclass(frozen=True)
class QAItem:
    row_index: int
    q_idx: int
    question: str
    correct_answer: list[str]
    correct_answer_chapters: list[int]
    retrieval_type: str = ""
    get: str = "all"


def load_chapters(book_path: Path = BOOK_PATH) -> list[Chapter]:
    payload = json.loads(Path(book_path).read_text(encoding="utf-8"))
    if not isinstance(payload, str):
        raise TypeError("EPBench book.json must contain one JSON string")
    chapters = [
        Chapter(chapter_id=int(match.group(1)), text=match.group(2).strip())
        for match in CHAPTER_RE.finditer(payload)
    ]
    expected_ids = list(range(1, 197))
    if len(chapters) != 196 or [row.chapter_id for row in chapters] != expected_ids:
        raise ValueError("fixed EPBench corpus must contain ordered chapters 1..196")
    if any(not row.text for row in chapters):
        raise ValueError("fixed EPBench corpus contains an empty chapter")
    return chapters


def _python_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def load_qa(qa_path: Path = QA_PATH) -> list[QAItem]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("EPBench QA loading requires pandas and a parquet engine") from exc

    frame = pd.read_parquet(Path(qa_path))
    required = {"q_idx", "question", "correct_answer", "correct_answer_chapters"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"EPBench QA parquet is missing columns: {missing}")
    rows: list[QAItem] = []
    for row_index, row in enumerate(frame.itertuples(index=False)):
        values = row._asdict()
        rows.append(
            QAItem(
                row_index=row_index,
                q_idx=int(values["q_idx"]),
                question=str(values["question"]),
                correct_answer=[str(item) for item in _python_list(values["correct_answer"])],
                correct_answer_chapters=[
                    int(item) for item in _python_list(values["correct_answer_chapters"])
                ],
                retrieval_type=str(values.get("retrieval_type") or ""),
                get=str(values.get("get") or "all").lower(),
            )
        )
    return rows


__all__ = ["Chapter", "QAItem", "load_chapters", "load_qa"]

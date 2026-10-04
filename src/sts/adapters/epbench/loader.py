from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


CHAPTER_PATTERN = re.compile(
    r"(?:\A|\n\n+)Chapter\s+(\d+)\s*\n+",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class EPBenchChapter:
    chapter_idx: int
    text: str


def load_book_chapters(data_folder: str | Path) -> list[EPBenchChapter]:
    folder = Path(data_folder)
    book = json.loads((folder / "book.json").read_text(encoding="utf-8"))
    if not isinstance(book, str):
        raise ValueError("EPBench book.json must contain one JSON string")

    matches = list(CHAPTER_PATTERN.finditer(book))
    chapters = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(book)
        chapters.append(
            EPBenchChapter(
                chapter_idx=int(match.group(1)),
                text=book[match.end():end].strip(),
            )
        )
    if not chapters:
        raise ValueError("No 'Chapter N' boundaries found in book.json")
    indices = [chapter.chapter_idx for chapter in chapters]
    if len(indices) != len(set(indices)):
        raise ValueError("Duplicate EPBench chapter indices")
    return chapters


def load_qa_questions(data_folder: str | Path) -> list[dict]:
    """Expose only identifiers and natural-language questions to strict QA."""
    frame = pd.read_parquet(Path(data_folder) / "df_qa.parquet")
    return [
        {"qa_id": int(row.q_idx), "row_idx": int(index), "question": str(row.question)}
        for index, row in frame[["q_idx", "question"]].reset_index(drop=True).iterrows()
    ]

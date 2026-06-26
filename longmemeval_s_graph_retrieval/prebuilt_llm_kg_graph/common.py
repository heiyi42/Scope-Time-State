from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pipeline.external.longmemeval_s.runner import DATA_PATH as DEFAULT_RUNNER_DATA_PATH, LMERow


PROJECT_DIR = Path(__file__).resolve().parents[2]
LOCAL_DATA_FALLBACK = (
    PROJECT_DIR
    / "Experiment"
    / "Other_BenchMark"
    / "LongMemEval-S"
    / "LongMemEval-S_data"
    / "data"
    / "longmemeval_s_cleaned.json"
)


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


def candidate_sessions_for_row(row: LMERow, session_ids: list[str]) -> list[dict[str, object]]:
    by_id = {
        session_id: (date, session)
        for session_id, date, session in zip(row.haystack_session_ids, row.haystack_dates, row.haystack_sessions)
    }
    candidates: list[dict[str, object]] = []
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


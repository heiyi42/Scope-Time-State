from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence, TypeVar


CaseT = TypeVar("CaseT")


def load_subset_ids(data_dir: Path, subset_name: str = "", subset_path: Path | None = None) -> List[str]:
    if not subset_name and subset_path is None:
        return []
    path = subset_path if subset_path is not None else data_dir / "subsets.json"
    if not path.exists():
        raise RuntimeError(f"case subset file not found: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if subset_name:
        if not isinstance(rows, Mapping) or subset_name not in rows:
            available = ", ".join(sorted(str(key) for key in rows)) if isinstance(rows, Mapping) else "<invalid>"
            raise RuntimeError(f"case subset {subset_name!r} not found in {path}; available: {available}")
        value = rows[subset_name]
    else:
        value = rows
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"case subset in {path} must be a list of case_id strings")
    return list(value)


def select_cases_by_id(cases: Sequence[CaseT], case_ids: Iterable[str]) -> List[CaseT]:
    requested = list(case_ids)
    if not requested:
        return list(cases)
    by_id = {str(getattr(case, "case_id")): case for case in cases}
    missing = [case_id for case_id in requested if case_id not in by_id]
    if missing:
        raise RuntimeError(f"case subset references missing case_id values: {missing}")
    return [by_id[case_id] for case_id in requested]

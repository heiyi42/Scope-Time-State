from __future__ import annotations

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Any, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    last_error: OSError | None = None
    for attempt in range(5):
        try:
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))
    if last_error is not None:
        raise last_error


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_iso_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class StatusWriter:
    def __init__(self, path: Path, base_payload: Mapping[str, Any]) -> None:
        self.path = path
        self.payload: dict[str, Any] = dict(base_payload)
        now = utc_now_iso()
        self.payload.setdefault("created_at", now)
        self.payload.setdefault("started_at", now)
        self.payload["updated_at"] = now
        atomic_write_json(self.path, self.payload)

    def update(self, **updates: Any) -> None:
        self.payload.update(updates)
        self.payload["updated_at"] = utc_now_iso()
        atomic_write_json(self.path, self.payload)


from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipeline.external.paths import EXTERNAL_CACHE_DIR, EXTERNAL_GRAPH_DIR, EXTERNAL_OUTPUT_ROOT, EXTERNAL_RESULT_DIR


PROJECT_DIR = Path(__file__).resolve().parents[3]
EVERMEMBENCH_DIR = PROJECT_DIR / "Experiment/Other_BenchMark/EverMemBench"
DATA_DIR = EVERMEMBENCH_DIR / "dataset"
OUTPUT_ROOT = EXTERNAL_OUTPUT_ROOT
GRAPH_OUTPUT_DIR = EXTERNAL_GRAPH_DIR
CACHE_DIR = EXTERNAL_CACHE_DIR
RESULT_DIR = EXTERNAL_RESULT_DIR
OUTPUT_DIR = RESULT_DIR


@dataclass(frozen=True)
class EverMemEvent:
    topic_id: str
    date: str
    group: str
    message_index: int
    speaker: str
    time: str
    text: str

    @property
    def event_id(self) -> str:
        return f"{self.topic_id}:{self.date}:{self.group}:{self.message_index}"

    @property
    def occurred_at(self) -> str:
        return self.time or self.date

    @property
    def sort_key(self) -> Tuple[str, str, str, int]:
        return (self.date, self.time, self.group, self.message_index)

    def visible_event(self) -> Dict[str, Any]:
        return {
            "node_type": "Episode/Event",
            "event_id": self.event_id,
            "topic_id": self.topic_id,
            "date": self.date,
            "group": self.group,
            "message_index": self.message_index,
            "speaker": self.speaker,
            "time": self.time,
            "occurred_at": self.occurred_at,
            "text": self.text,
            "source_type": "dialogue",
            "metadata": {
                "topic_id": self.topic_id,
                "date": self.date,
                "group": self.group,
                "message_index": self.message_index,
                "speaker": self.speaker,
            },
        }


def topic_dialogue_path(data_root: Path, topic_id: str) -> Path:
    return data_root / topic_id / "dialogue.json"


def parse_message_index(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def load_topic_events(topic_id: str, data_root: Optional[Path] = None, event_limit: int = 0) -> List[EverMemEvent]:
    root = data_root or DATA_DIR
    path = topic_dialogue_path(root, topic_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"dialogue JSON must be a list of daily records: {path}")

    events: List[EverMemEvent] = []
    for day in raw:
        if not isinstance(day, dict):
            continue
        record_topic = str(day.get("topic_id") or topic_id)
        date = str(day.get("date") or "")
        dialogues = day.get("dialogues")
        if not isinstance(dialogues, dict):
            continue
        for group, messages in dialogues.items():
            if not isinstance(messages, list):
                continue
            for fallback_index, message in enumerate(messages, start=1):
                if not isinstance(message, dict):
                    continue
                text = " ".join(str(message.get("dialogue") or "").split())
                if not text:
                    continue
                events.append(
                    EverMemEvent(
                        topic_id=record_topic,
                        date=date,
                        group=str(group),
                        message_index=parse_message_index(message.get("message_index"), fallback_index),
                        speaker=str(message.get("speaker") or ""),
                        time=str(message.get("time") or ""),
                        text=text,
                    )
                )
                if event_limit and len(events) >= event_limit:
                    break
            if event_limit and len(events) >= event_limit:
                break
        if event_limit and len(events) >= event_limit:
            break

    events.sort(key=lambda item: item.sort_key)
    seen = set()
    duplicates = []
    for event in events:
        if event.event_id in seen:
            duplicates.append(event.event_id)
        seen.add(event.event_id)
    if duplicates:
        sample = ", ".join(duplicates[:5])
        raise ValueError(f"duplicate EverMemBench event ids for topic {topic_id}: {sample}")
    return events

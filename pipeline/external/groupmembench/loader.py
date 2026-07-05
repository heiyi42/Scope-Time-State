from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
GROUPMEMBENCH_DIR = PROJECT_DIR / "Experiment/Other_BenchMark/GroupMemBench"
DATA_DIR = GROUPMEMBENCH_DIR / "dataset/data/final"
SOURCE_DIR = GROUPMEMBENCH_DIR / "source/GroupMemBench"
QUESTION_DIR = SOURCE_DIR / "questions"
OUTPUT_DIR = PROJECT_DIR / "stamb_state_benchmark/output"

DOMAINS: Tuple[str, ...] = ("Finance", "Technology", "Healthcare", "Manufacturing")


@dataclass(frozen=True)
class GroupMessage:
    domain: str
    channel: str
    msg_node: str
    content: str
    author: str
    role: str
    timestamp: str
    reply_to: Optional[str]
    phase_name: str
    topic: str
    message_type: str
    path_type: str

    @property
    def event_id(self) -> str:
        return self.msg_node

    def scope_key(self) -> Tuple[str, str, str, str]:
        return (self.domain, self.channel, self.phase_name, self.topic)

    def visible_event(self) -> Dict[str, object]:
        return {
            "event_id": self.event_id,
            "content": self.content,
            "event_type": "group_message",
            "occurred_at": self.timestamp,
            "updated_at": self.timestamp,
            "source_id": self.author,
            "metadata": {
                "domain": self.domain,
                "channel": self.channel,
                "phase_name": self.phase_name,
                "topic": self.topic,
                "reply_to": self.reply_to,
                "role": self.role,
                "author": self.author,
                "msg_node": self.msg_node,
                "message_type": self.message_type,
            },
        }


@dataclass(frozen=True)
class GroupQuestion:
    domain: str
    qtype: str
    question_id: str
    question: str
    answer: str
    asking_user_id: str

    @property
    def case_id(self) -> str:
        return f"{self.domain}:{self.qtype}:{self.question_id}"


@dataclass(frozen=True)
class ScopeNode:
    scope_id: str
    domain: str
    channel: str
    phase_name: str
    topic: str
    scope_type: str = "project_phase_topic"
    source_anchor: Optional[str] = None
    state_target: Optional[str] = None
    state_target_terms: Tuple[str, ...] = ()
    base_scope_id: Optional[str] = None
    reply_thread: Optional[str] = None
    event_count: int = 0

    def text(self) -> str:
        parts = [self.domain, self.channel, self.phase_name, self.topic]
        if self.state_target:
            parts.append(self.state_target)
        if self.reply_thread:
            parts.append(self.reply_thread)
        if self.source_anchor:
            parts.append(self.source_anchor)
        return " ".join(part for part in parts if part)

    def as_dict(self) -> Dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "type": self.scope_type,
            "domain": self.domain,
            "channel": self.channel,
            "phase_name": self.phase_name,
            "topic": self.topic,
            "reply_thread": self.reply_thread,
            "source_anchor": self.source_anchor,
            "state_target": self.state_target,
            "state_target_terms": list(self.state_target_terms),
            "base_scope_id": self.base_scope_id,
            "event_count": self.event_count,
        }


def scope_id_for(
    domain: str,
    channel: str,
    phase_name: str,
    topic: str,
    source_anchor: Optional[str] = None,
    state_target: Optional[str] = None,
) -> str:
    parts = [domain, channel, phase_name, topic]
    if state_target:
        parts.append(f"target={state_target}")
    if source_anchor:
        parts.append(f"source={source_anchor}")
    return "::".join(part.strip() or "unknown" for part in parts)


def conversation_path(domain: str) -> Path:
    return DATA_DIR / domain / f"synthetic_domain_channels_rolevariants_{domain}.json"


def questions_path(domain: str, qtype: str) -> Path:
    return QUESTION_DIR / domain / f"{qtype}.jsonl"


def load_domain_messages(domain: str, path: Optional[Path] = None) -> List[GroupMessage]:
    data_path = path or conversation_path(domain)
    raw = json.loads(data_path.read_text())
    messages: List[GroupMessage] = []
    if not isinstance(raw, dict):
        raise ValueError(f"conversation JSON must be an object keyed by channel: {data_path}")
    for channel, channel_messages in raw.items():
        if not isinstance(channel_messages, list):
            continue
        for item in channel_messages:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            msg_node = str(item.get("msg_node", "")).strip()
            if not content or not msg_node:
                continue
            reply_to = item.get("reply_to")
            messages.append(
                GroupMessage(
                    domain=domain,
                    channel=str(channel),
                    msg_node=msg_node,
                    content=content,
                    author=str(item.get("author", "")),
                    role=str(item.get("role", "")),
                    timestamp=str(item.get("timestamp", "")),
                    reply_to=str(reply_to) if reply_to not in {None, "", "null"} else None,
                    phase_name=str(item.get("phase_name", "")),
                    topic=str(item.get("topic", "")),
                    message_type=str(item.get("message_type", "")),
                    path_type=str(item.get("path_type", "")),
                )
            )
    messages.sort(key=lambda item: (item.channel, item.timestamp, item.msg_node))
    return messages


def load_questions(domain: str, qtype: str, path: Optional[Path] = None) -> List[GroupQuestion]:
    q_path = path or questions_path(domain, qtype)
    questions: List[GroupQuestion] = []
    with q_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            questions.append(
                GroupQuestion(
                    domain=domain,
                    qtype=qtype,
                    question_id=str(raw["id"]),
                    question=str(raw["question"]),
                    answer=str(raw.get("answer", "")),
                    asking_user_id=str(raw.get("asking_user_id", "")),
                )
            )
    return questions


def build_scope_inventory(messages: Sequence[GroupMessage], source_anchor: Optional[str] = None) -> List[ScopeNode]:
    counts = Counter(message.scope_key() for message in messages)
    scopes = [
        ScopeNode(
            scope_id=scope_id_for(domain, channel, phase_name, topic, source_anchor),
            domain=domain,
            channel=channel,
            phase_name=phase_name,
            topic=topic,
            source_anchor=source_anchor,
            event_count=count,
        )
        for (domain, channel, phase_name, topic), count in counts.items()
    ]
    scopes.sort(key=lambda item: (item.domain, item.channel, item.phase_name, item.topic))
    return scopes


def filter_messages_for_scope(messages: Sequence[GroupMessage], scope: ScopeNode) -> List[GroupMessage]:
    return [
        message
        for message in messages
        if message.domain == scope.domain
        and message.channel == scope.channel
        and message.phase_name == scope.phase_name
        and message.topic == scope.topic
    ]


def select_questions(
    questions: Sequence[GroupQuestion],
    limit_cases: int,
    limit_per_type: int,
) -> List[GroupQuestion]:
    selected = list(questions)
    if limit_per_type:
        selected = selected[:limit_per_type]
    if limit_cases:
        selected = selected[:limit_cases]
    return selected


def count_by_qtype(questions: Iterable[GroupQuestion]) -> Dict[str, int]:
    return dict(Counter(question.qtype for question in questions))

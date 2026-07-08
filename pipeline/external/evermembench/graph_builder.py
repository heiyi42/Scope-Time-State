from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config
from pipeline.external.evermembench.loader import CACHE_DIR, DATA_DIR, GRAPH_OUTPUT_DIR, EverMemEvent, load_topic_events


NODE_TYPES = ("Episode/Event", "Claim", "StateFacet", "Entity/Scope", "Time")
EDGE_TYPES = (
    "MENTIONS",
    "IN_SCOPE",
    "ASSERTS",
    "OCCURRED_AT",
    "HAS_TIME",
    "CORRECTS",
    "SUPERSEDES",
    "CONFLICTS_WITH",
    "SUPPORTS",
    "CURRENT_AFTER",
    "CURRENT_STATE_OF",
    "RESPONSIBLE_FOR",
)
EDGE_ENDPOINT_TYPES: Mapping[str, Tuple[str, str]] = {
    "MENTIONS": ("Episode/Event", "Entity/Scope"),
    "IN_SCOPE": ("Episode/Event", "Entity/Scope"),
    "ASSERTS": ("Episode/Event", "Claim"),
    "OCCURRED_AT": ("Episode/Event", "Time"),
    "HAS_TIME": ("Claim", "Time"),
    "CORRECTS": ("Claim", "Claim"),
    "SUPERSEDES": ("Claim", "Claim"),
    "CONFLICTS_WITH": ("Claim", "Claim"),
    "SUPPORTS": ("Claim", "StateFacet"),
    "CURRENT_AFTER": ("StateFacet", "Time"),
    "CURRENT_STATE_OF": ("StateFacet", "Entity/Scope"),
    "RESPONSIBLE_FOR": ("Entity/Scope", "Entity/Scope"),
}


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    model: str
    api_key: str
    api_base: str
    cache_path: Path
    use_cache: bool

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
ISO_DATE_RE = re.compile(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)")
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z ._-]{1,60})")
PERSON_NAME_RE = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")
NEXT_STEP_RE = re.compile(r"\b(next step|next phase|next task|next round|follow[- ]?up)\b", re.I)
TIME_ROLES = {
    "occurred_at",
    "mentioned_at",
    "updated_at",
    "planned_for",
    "deadline_at",
    "valid_from",
    "started_at",
    "completed_at",
    "finalized_at",
    "current_after",
}
START_PHASE_RE = re.compile(
    r"\b(start(?:ed|ing)?|begin(?:s|ning)?|began|initiat(?:e|ed|ing)|kick(?:ed)? off|launch(?:ed|ing)?|take on|taking on)\b",
    re.I,
)
COMPLETE_PHASE_RE = re.compile(
    r"\b(completed|completion|concluded|finished|finali[sz](?:ed|ation)|delivered|released|uploaded|published|deployed|merged|passed|closed)\b|ready for (?:delivery|release|handover|go-live)",
    re.I,
)
FUTURE_OR_PLAN_RE = re.compile(
    r"\b(will|can|plan(?:ned)? to|expect(?:ed)? to|tomorrow|next week|next day|due|deadline|before|after|prior to|need to|needs to|should|must|to be|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\bto\s+(?:start|begin|complete|finish|finali[sz]e|deliver|release|upload)\b",
    re.I,
)
RELATIVE_TIME_RE = re.compile(
    r"\b(today|tomorrow|yesterday|next day|next week|this afternoon|this morning|this evening|tonight)\b",
    re.I,
)
WEEKDAY_RE = re.compile(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
EFFORT_METRIC_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(person[- ]days?|man[- ]days?|workdays?|working days?|days?)\b",
    re.I,
)
EFFORT_CONTEXT_RE = re.compile(
    r"\b(effort|spent|invested|take|took|takes|last(?:ed)?|duration|workload|work hours|planned|estimated|actual|in total|combined|collectively)\b",
    re.I,
)
TIME_SOURCE_PRIORITY = {
    "explicit_text_time": 1.0,
    "relative_text_time": 0.85,
    "phase_from_event_time": 0.65,
    "source_event_fallback": 0.25,
}

STATEFUL_TERMS = (
    "accounting",
    "adjust",
    "approve",
    "approved",
    "asset",
    "assign",
    "block",
    "blocked",
    "blocker",
    "boundary",
    "change",
    "changed",
    "coding",
    "complete",
    "completed",
    "concluded",
    "concurrent",
    "configure",
    "configured",
    "constraint",
    "cpu",
    "deadline",
    "decide",
    "decided",
    "decision",
    "delay",
    "delayed",
    "deliver",
    "delivered",
    "deploy",
    "deployed",
    "design",
    "develop",
    "developed",
    "developing",
    "development",
    "due",
    "field",
    "final",
    "finish",
    "finished",
    "fix",
    "fixed",
    "go-live",
    "going online",
    "include",
    "integrate",
    "launch",
    "launched",
    "issue",
    "milestone",
    "merge",
    "merged",
    "must",
    "need",
    "needs",
    "optimize",
    "optimized",
    "owner",
    "phase",
    "plan",
    "planned",
    "ready",
    "release",
    "released",
    "replace",
    "requirement",
    "responsible",
    "risk",
    "scope",
    "should",
    "sql",
    "start",
    "started",
    "starting",
    "status",
    "stress test",
    "submit",
    "submitted",
    "target",
    "update",
    "updated",
    "will",
)

UPDATE_TERMS = (
    "adjust",
    "change",
    "changed",
    "correct",
    "final",
    "instead",
    "latest",
    "no longer",
    "optimize",
    "optimized",
    "replace",
    "revised",
    "switch",
    "update",
    "updated",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an offline STS graph for one EverMemBench topic.")
    parser.add_argument("--data-root", default=str(DATA_DIR))
    parser.add_argument("--topic", default="01")
    parser.add_argument("--output-dir", default=str(GRAPH_OUTPUT_DIR / "evermembench_topic_graph_v1"))
    parser.add_argument("--claim-mode", choices=("llm", "heuristic", "none"), default="heuristic")
    parser.add_argument("--resolver-mode", choices=("llm", "heuristic"), default="heuristic")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None, help="Optional model override, e.g. deepseek-v4-pro.")
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.evermembench_graph_builder.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--message-chunk-size", type=int, default=16)
    parser.add_argument("--claim-workers", type=int, default=1, help="Parallel LLM workers for claim extraction chunks.")
    parser.add_argument("--resolver-workers", type=int, default=1, help="Parallel LLM workers for state resolver buckets.")
    parser.add_argument(
        "--llm-event-filter",
        choices=("stateful", "all"),
        default="stateful",
        help="Events sent to LLM claim extraction. All dialogue events are still preserved as Event nodes.",
    )
    parser.add_argument("--max-claims-per-event", type=int, default=2)
    parser.add_argument("--resolver-candidate-limit", type=int, default=24)
    parser.add_argument(
        "--resolver-bucket-limit",
        type=int,
        default=0,
        help="Debug/smoke limit for LLM resolver calls; 0 means all eligible buckets.",
    )
    parser.add_argument("--event-limit", type=int, default=0, help="Debug limit only; 0 builds the full topic.")
    return parser.parse_args()


def safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "unknown"


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def node_id(node: Mapping[str, Any]) -> str:
    node_type = str(node.get("node_type") or "")
    if node_type == "Episode/Event":
        return str(node.get("event_id") or "")
    if node_type == "Claim":
        return str(node.get("claim_id") or "")
    if node_type == "StateFacet":
        return str(node.get("facet_id") or node.get("state_facet_id") or "")
    if node_type == "Entity/Scope":
        return str(node.get("scope_id") or node.get("entity_id") or "")
    if node_type == "Time":
        return str(node.get("time_id") or "")
    return ""


def scope_id(topic_id: str, scope_type: str, value: str) -> str:
    return f"scope::{scope_type}::{safe_part(topic_id)}::{safe_part(value)}"


def project_scope_id(topic_id: str) -> str:
    return scope_id(topic_id, "project", topic_id)


def group_scope_id(topic_id: str, group: str) -> str:
    return scope_id(topic_id, "group", group)


def person_scope_id(topic_id: str, person: str) -> str:
    return scope_id(topic_id, "person", person)


def subject_entity_id(topic_id: str, subject: str) -> str:
    return f"entity::subject::{safe_part(topic_id)}::{safe_part(subject)}::{short_hash(subject)}"


def time_id(time_role: str, value: str) -> str:
    return f"time::{safe_part(time_role)}::{safe_part(value)}"


def scope_node(topic_id: str, scope_type: str, value: str, label: str) -> Dict[str, Any]:
    return {
        "node_type": "Entity/Scope",
        "scope_id": scope_id(topic_id, scope_type, value),
        "topic_id": topic_id,
        "scope_type": scope_type,
        "label": label,
        "role": "scope",
    }


TASK_OBJECT_STOP_LABELS = {
    "current status",
    "data",
    "follow up",
    "group",
    "project",
    "requirement",
    "requirements",
    "state",
    "status",
    "system",
    "task",
    "work",
}
TASK_OBJECT_HINT_RE = re.compile(
    r"\b("
    r"adaptation|alarm|analysis|api|architecture|bar chart|chart|cockpit|dashboard|database|design|document|"
    r"factor|function|guide|interface|interview|logic|manual|message queue|modbus|monitoring|operation|"
    r"page|homepage|home page|workbench|center|module|ui|scaffold|performance|loading|optimization|testing|test cases?|"
    r"compatibility|strategy|recruitment|activation|flowchart|metric|alert|release|"
    r"platform|product requirement|report|selection|specification|template|verification"
    r")\b",
    re.I,
)
TASK_OBJECT_SUBJECT_HINT_RE = re.compile(
    r"\b("
    r"adapter|backend|component|connector|consumer|engine|etl|flow|frontend|job|module|notification|"
    r"pipeline|process|processor|queue|reminder|runbook|service|workflow"
    r")\b",
    re.I,
)
TASK_OBJECT_GENERIC_PREFIX_RE = re.compile(r"^(?:about|for|in|on|regarding|the|a|an)\s+", re.I)
TASK_OBJECT_SUBJECT_REJECT_RE = re.compile(
    r"^(?:speaker|person):|^(?:state object|current status|follow up|group|project|requirements?|state|status|system|task|work)$",
    re.I,
)
NON_PERSON_NAME_TOKENS = {
    "American",
    "Backend",
    "Buyer",
    "Company",
    "Department",
    "Frontend",
    "Health",
    "Management",
    "Project",
    "System",
}


def normalize_task_object_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n'\"`.,:;!?()[]{}")
    text = TASK_OBJECT_GENERIC_PREFIX_RE.sub("", text).strip(" \t\r\n'\"`.,:;!?()[]{}")
    if len(text) > 140:
        text = re.split(r"\b(?:and|but|while|because|so that|with)\b|[.;]", text, maxsplit=1, flags=re.I)[0]
        text = text.strip(" \t\r\n'\"`.,:;!?()[]{}")
    lowered = text.lower()
    if not text or lowered in TASK_OBJECT_STOP_LABELS:
        return ""
    if len(text) < 4:
        return ""
    if not TASK_OBJECT_HINT_RE.search(text):
        return ""
    return text[:140]


def normalize_subject_task_object_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n'\"`.,:;!?()[]{}")
    text = TASK_OBJECT_GENERIC_PREFIX_RE.sub("", text).strip(" \t\r\n'\"`.,:;!?()[]{}")
    lowered = text.lower()
    if not text or lowered in TASK_OBJECT_STOP_LABELS or TASK_OBJECT_SUBJECT_REJECT_RE.search(text):
        return ""
    if len(text) < 4 or len(text) > 140:
        return ""
    terms = re.findall(r"[A-Za-z0-9]+", lowered)
    if len(terms) < 2:
        return ""
    if not (TASK_OBJECT_HINT_RE.search(text) or TASK_OBJECT_SUBJECT_HINT_RE.search(text)):
        return ""
    return text[:140]


def task_object_scope_id(topic_id: str, label: str) -> str:
    normalized = normalize_task_object_label(label) or str(label or "").strip()
    return f"scope::task_object::{safe_part(topic_id)}::{safe_part(normalized[:72])}::{short_hash(normalized.lower())}"


def task_object_scope_node(topic_id: str, label: str, source: str) -> Dict[str, Any]:
    return {
        "node_type": "Entity/Scope",
        "scope_id": task_object_scope_id(topic_id, label),
        "topic_id": topic_id,
        "scope_type": "task_object",
        "label": label,
        "value": label,
        "role": "scope",
        "extraction_source": source,
    }


def claim_task_object_labels(claim: Mapping[str, Any]) -> List[Dict[str, str]]:
    candidates: List[Tuple[str, object]] = [
        ("scope_hint", claim.get("scope_hint")),
        ("subject", claim.get("subject")),
        ("subject_fallback", claim.get("subject")),
        ("object", claim.get("object")),
        ("value", claim.get("value")),
    ]
    labels: List[Dict[str, str]] = []
    seen: set[str] = set()
    for source, value in candidates:
        if source == "subject_fallback":
            label = normalize_subject_task_object_label(value)
        else:
            label = normalize_task_object_label(value)
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append({"label": label, "source": source})
        if len(labels) >= 3:
            break
    return labels


def likely_person_name(value: str) -> bool:
    tokens = [token for token in str(value or "").split() if token]
    if len(tokens) != 2:
        return False
    if any(token in NON_PERSON_NAME_TOKENS for token in tokens):
        return False
    return all(re.fullmatch(r"[A-Z][a-z]+", token) for token in tokens)


def extract_person_names(text: object) -> List[str]:
    names: List[str] = []
    seen: set[str] = set()
    for match in PERSON_NAME_RE.finditer(str(text or "")):
        name = " ".join(match.group(0).split())
        key = name.lower()
        if key in seen or not likely_person_name(name):
            continue
        seen.add(key)
        names.append(name)
    return names


def materialize_claim_task_objects(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    claim: Dict[str, Any],
    event: EverMemEvent,
) -> List[str]:
    scope_ids: List[str] = []
    labels: List[str] = []
    for item in claim_task_object_labels(claim):
        label = item["label"]
        scope_identifier = task_object_scope_id(event.topic_id, label)
        add_node(nodes, task_object_scope_node(event.topic_id, label, item["source"]))
        add_edge(
            edges,
            "IN_SCOPE",
            event.event_id,
            scope_identifier,
            reason=f"claim task_object from {item['source']}",
        )
        add_edge(
            edges,
            "MENTIONS",
            event.event_id,
            scope_identifier,
            reason=f"claim task_object from {item['source']}",
        )
        scope_ids.append(scope_identifier)
        labels.append(label)
    if scope_ids:
        claim["task_object_scope_ids"] = scope_ids
        claim["task_object_labels"] = labels
    return scope_ids


def materialize_claim_responsibility_edges(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    claim: Mapping[str, Any],
    event: EverMemEvent,
) -> int:
    if str(claim.get("facet_key") or "").lower() != "owner":
        return 0
    task_scope_ids = [str(scope_id) for scope_id in claim.get("task_object_scope_ids", []) or [] if scope_id]
    if not task_scope_ids:
        return 0
    person_names = extract_person_names(" ".join(str(claim.get(key) or "") for key in ("object", "value")))
    added = 0
    for person_name in person_names:
        person_id = person_scope_id(event.topic_id, person_name)
        add_node(nodes, scope_node(event.topic_id, "person", person_name, f"PersonScope({person_name})"))
        for task_scope_id in task_scope_ids:
            add_edge(
                edges,
                "RESPONSIBLE_FOR",
                person_id,
                task_scope_id,
                reason="owner claim materialized as person-task responsibility",
                source_claim_id=claim.get("claim_id"),
                source_event_id=event.event_id,
            )
            added += 1
    return added


def materialize_state_task_object_links(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    claims: Mapping[str, Mapping[str, Any]],
) -> int:
    added = 0
    for state_id, state in list(nodes.items()):
        if str(state.get("node_type") or "") != "StateFacet":
            continue
        linked_scope_ids: set[str] = set()
        for claim_id in state.get("support_claim_ids", []) or []:
            claim = claims.get(str(claim_id), {})
            for scope_identifier in claim.get("task_object_scope_ids", []) or []:
                scope_text = str(scope_identifier)
                if scope_text and scope_text in nodes:
                    linked_scope_ids.add(scope_text)
        for scope_identifier in sorted(linked_scope_ids):
            add_edge(
                edges,
                "CURRENT_STATE_OF",
                state_id,
                scope_identifier,
                reason="facet grounded to support claim task object",
            )
            added += 1
    return added


def subject_node(topic_id: str, subject: str) -> Dict[str, Any]:
    return {
        "node_type": "Entity/Scope",
        "entity_id": subject_entity_id(topic_id, subject),
        "topic_id": topic_id,
        "kind": "subject",
        "value": subject,
        "role": "entity",
    }


def sentence_candidates(text: str) -> List[str]:
    sentences = [" ".join(part.split()) for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
    if not sentences and text.strip():
        return [" ".join(text.split())]
    return sentences


def tokens(text: object) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def token_support_score(value: object, source: object) -> float:
    value_text = str(value or "").strip().lower()
    source_text = str(source or "").lower()
    if value_text and value_text in source_text:
        return 1.0
    if value_text and PERCENT_RE.search(value_text) and PERCENT_RE.search(source_text):
        return 1.0
    value_tokens = [token for token in tokens(value) if len(token) > 2]
    if not value_tokens:
        return 1.0 if value_text else 0.0
    source_tokens = set(tokens(source))
    if not source_tokens:
        return 0.0
    hits = sum(1 for token in value_tokens if token in source_tokens)
    return hits / max(1, len(value_tokens))


EVENT_START_TASK_PATTERNS = (
    re.compile(
        r"\b(?:i'?m|i am|we'?re|we are)\s+(?:also\s+)?(?:officially\s+)?starting\s+"
        r"(?:a\s+new\s+task\s+here[:,]?\s+)?(?:to\s+|on\s+|with\s+)?(?P<task>[^.!?]{6,240})",
        re.I,
    ),
    re.compile(
        r"\b(?:i'?ve|i have|we'?ve|we have)\s+(?:also\s+)?started\s+(?:on\s+)?(?P<task>[^.!?]{6,240})",
        re.I,
    ),
    re.compile(
        r"\bstarting\s+today,\s+(?:i'?m|i am|we'?re|we are|i'?ll|i will|we'?ll|we will)\s+"
        r"(?:be\s+)?(?P<task>[^.!?]{6,240})",
        re.I,
    ),
    re.compile(
        r"\b(?P<task>[^.!?]{6,200}?)\s+(?:starts?|begins?)\s+today\b",
        re.I,
    ),
    re.compile(
        r"\b(?P<task>[^.!?]{6,200}?)\s+(?:has|have)\s+officially\s+begun\b",
        re.I,
    ),
)
EVENT_COMPLETION_TASK_PATTERNS = (
    re.compile(
        r"\b(?:task\s+)?[\"'\\[](?P<task>[^\"'\\]]{6,200})[\"'\\]]\s+"
        r"(?:has\s+been|is|was)\s+(?:successfully\s+)?(?:complete|completed|finished|done|closed)\b",
        re.I,
    ),
    re.compile(
        r"\b(?P<task>[^.!?]{6,240}?)\s+(?:has|have|had)\s+(?:also\s+)?been\s+(?:fully\s+|successfully\s+)?"
        r"(?:completed|finished|developed|tested|delivered|released|uploaded|published|deployed|merged|concluded|set\s+up|drawn)\b",
        re.I,
    ),
    re.compile(
        r"\b(?P<task>[^.!?]{6,240}?)\s+(?:is|are|was|were)\s+(?:now\s+|also\s+)?"
        r"(?:all\s+)?(?:complete|completed|finished|done|closed|ready|ready for testing|ready for release)\b",
        re.I,
    ),
    re.compile(
        r"\b(?P<task>[^.!?]{6,240}?)\s+(?:can|could)\s+be\s+closed\b",
        re.I,
    ),
    re.compile(
        r"\b(?:successful\s+completion|completion)\s+of\s+(?P<task>[^.!?]{6,220})",
        re.I,
    ),
)
EVENT_TASK_TRAILING_SPLIT_RE = re.compile(
    r"\s+(?:today|tomorrow|this morning|this afternoon|this evening|tonight|next week|"
    r"first\b|then\b|and then\b|however\b|but\b|so\b|please\b|could you\b|do you\b|"
    r"which\b|what\b|who\b|where\b|when\b)|\s+@",
    re.I,
)
EVENT_TASK_LEADING_RE = re.compile(
    r"^(?:"
    r"good\s+(?:morning|afternoon|evening|friday)\s+(?:everyone|all)[:,]?\s+|"
    r"reporting\s+to\s+everyone[:,]?\s+|"
    r"another\s+even\s+more\s+important\s+thing\s+is\s+that\s+|"
    r"all\s+members[:,]?\s+|"
    r"the\s+|a\s+|an\s+|"
    r"new\s+task\s+|new\s+project\s+|"
    r"task\s+|tasks?\s+|"
    r"today'?s\s+(?:main\s+)?task\s+(?:is\s+)?(?:to\s+)?|"
    r"my\s+(?:main\s+)?task\s+(?:is\s+)?(?:to\s+)?|"
    r"our\s+(?:main\s+)?task\s+(?:is\s+)?(?:to\s+)?|"
    r"(?:development|design|testing|configuration|implementation|analysis|optimization|recruitment|activation)\s+(?:of|for)\s+|"
    r"(?:be\s+)?responsible\s+for\s+|"
    r"working\s+on\s+|work\s+on\s+|"
    r"(?:to\s+)?(?:develop|build|implement|write|writing|draw|drawing|design|designing|analyze|analyzing|"
    r"optimi[sz]e|optimizing|configure|configuring|test|testing|update|updating|connect|connecting|integrate|"
    r"integrating|review|reviewing|recruit|recruiting|complete|completing)\s+"
    r")",
    re.I,
)
EVENT_TASK_GENERIC_RE = re.compile(
    r"^(?:it|this|that|today|tomorrow|work|task|project|system)$|"
    r"\b(?:all|both|several|these|those|today'?s)\s+(?:tasks|work|preparations)\b|"
    r"\b(?:deadline tasks|all tasks|all preparations)\b",
    re.I,
)
TASK_TOKEN_STOP_WORDS = {
    "and",
    "are",
    "for",
    "from",
    "has",
    "have",
    "into",
    "our",
    "the",
    "this",
    "that",
    "today",
    "with",
    "will",
    "work",
}


def clean_event_task_phrase(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\[(?:task\s+completed|completed|done)\]\s*", " ", text, flags=re.I)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"@(?:all|everyone|all members)\b", " ", text, flags=re.I)
    text = re.sub(r"@[A-Z][A-Za-z_-]+(?:\s+[A-Z][A-Za-z_-]+)?", " ", text)
    text = re.split(r"\s+@", text, maxsplit=1)[0]
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n'\"`.,:;!?()[]{}")
    text = re.sub(r"^[A-Z][a-z]+ [A-Z][a-z]+\s+(?=(?:the|a|an)\s+)", "", text, flags=re.I)
    text = re.sub(r"^(?:final|initial|preliminary)\s+(?:version|draft)\s+of\s+", "", text, flags=re.I)
    for _ in range(3):
        new_text = EVENT_TASK_LEADING_RE.sub("", text).strip(" \t\r\n'\"`.,:;!?()[]{}")
        if new_text == text:
            break
        text = new_text
    text = EVENT_TASK_TRAILING_SPLIT_RE.split(text, maxsplit=1)[0]
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n'\"`.,:;!?()[]{}")
    if len(text) > 180:
        text = re.split(r"\b(?:and|while|because|so that|with)\b|[;:]", text, maxsplit=1, flags=re.I)[0]
        text = text.strip(" \t\r\n'\"`.,:;!?()[]{}")
    return text[:180]


def task_phrase_token_set(value: object) -> set[str]:
    return {token for token in tokens(value) if len(token) > 2 and token not in TASK_TOKEN_STOP_WORDS}


def is_specific_event_task_phrase(value: object) -> bool:
    text = clean_event_task_phrase(value)
    if not text or len(text) < 6 or EVENT_TASK_GENERIC_RE.search(text):
        return False
    if len(task_phrase_token_set(text)) < 2:
        return False
    return True


def lifecycle_task_mentions(event: EverMemEvent, phase_role: str) -> List[Tuple[str, str]]:
    patterns = EVENT_START_TASK_PATTERNS if phase_role == "started" else EVENT_COMPLETION_TASK_PATTERNS
    mentions: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for sentence in sentence_candidates(event.text):
        for pattern in patterns:
            for match in pattern.finditer(sentence):
                task = clean_event_task_phrase(match.group("task"))
                if not is_specific_event_task_phrase(task):
                    continue
                key = task.lower()
                if key in seen:
                    continue
                seen.add(key)
                mentions.append((task, sentence[:800]))
    return mentions


def lifecycle_claim_exists(claims: Sequence[Mapping[str, Any]], task: str, phase_role: str) -> bool:
    task_tokens = task_phrase_token_set(task)
    if not task_tokens:
        return False
    expected_time_role = phase_time_role(phase_role)
    for claim in claims:
        claim_phase = str(claim.get("phase_role") or "")
        claim_time_role = str(claim.get("time_role") or "")
        if claim_phase != phase_role and claim_time_role != expected_time_role:
            continue
        claim_tokens = task_phrase_token_set(claim_grounding_text(claim))
        if not claim_tokens:
            continue
        if len(task_tokens & claim_tokens) / max(1, len(task_tokens)) >= 0.65:
            return True
    return False


def next_event_claim_number(claims: Sequence[Mapping[str, Any]]) -> int:
    max_number = 0
    for claim in claims:
        match = re.search(r"::(\d+)$", str(claim.get("claim_id") or ""))
        if match:
            max_number = max(max_number, int(match.group(1)))
    return max(max_number, len(claims)) + 1


def make_event_lifecycle_claim(
    event: EverMemEvent,
    task: str,
    phase_role: str,
    sentence: str,
    claim_number: int,
) -> Dict[str, Any]:
    phase_label = "started" if phase_role == "started" else "completed"
    claim = {
        "node_type": "Claim",
        "claim_id": f"claim::{event.event_id}::{claim_number}",
        "topic_id": event.topic_id,
        "source_event_id": event.event_id,
        "scope_id": group_scope_id(event.topic_id, event.group),
        "subject": task[:160],
        "predicate": "status",
        "object": sentence[:800],
        "facet_key": "status",
        "value": f"{task} {phase_label}"[:800],
        "scope_hint": task[:160],
        "confidence": 0.82 if phase_role == "completed" else 0.78,
        "time_role": phase_time_role(phase_role),
        "phase_role": phase_role,
        "event_sort_key": list(event.sort_key),
        "extraction_method": f"event_endpoint_{phase_role}_fallback_v1",
    }
    return enrich_claim_annotations(claim, event)


def augment_event_lifecycle_claims(event: EverMemEvent, event_claims: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    claims = [dict(claim) for claim in event_claims]
    claim_number = next_event_claim_number(claims)
    for phase_role in ("started", "completed"):
        for task, sentence in lifecycle_task_mentions(event, phase_role):
            if lifecycle_claim_exists(claims, task, phase_role):
                continue
            claims.append(make_event_lifecycle_claim(event, task, phase_role, sentence, claim_number))
            claim_number += 1
            break
    return claims


def chunks(items: Sequence[EverMemEvent], size: int) -> List[Sequence[EverMemEvent]]:
    chunk_size = max(1, size)
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def is_stateful_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    if ISO_DATE_RE.search(sentence) or PERCENT_RE.search(sentence):
        return True
    return any(term in lowered for term in STATEFUL_TERMS)


def infer_facet_key(sentence: str) -> str:
    lowered = sentence.lower()
    if PERCENT_RE.search(sentence) or any(term in lowered for term in ("cpu", "latency", "throughput", "concurrent", "stress test")):
        return "metric"
    if any(term in lowered for term in ("deadline", "due", "eod", "end of day")):
        return "deadline"
    if any(term in lowered for term in ("owner", "responsible", "assign", "lead")):
        return "owner"
    if any(term in lowered for term in ("risk", "block", "blocked", "blocker", "issue")):
        return "risk"
    if any(term in lowered for term in ("scope", "include", "exclude", "boundary")):
        return "scope"
    if any(term in lowered for term in ("approve", "approved", "reject", "rejected", "decide", "decided", "decision", "agreed")):
        return "decision"
    if any(
        term in lowered
        for term in ("start", "started", "starting", "begin", "began", "complete", "completed", "finished", "ready", "status", "progress")
    ):
        return "status"
    if NEXT_STEP_RE.search(sentence) or any(
        term in lowered for term in ("will", "need", "needs", "must", "should", "submit", "schedule", "draft")
    ):
        return "next_step"
    if any(term in lowered for term in ("prefer", "style", "format")):
        return "preference"
    return "state"


def infer_phase_role(sentence: str, facet_key: str) -> Optional[str]:
    lowered = sentence.lower()
    if "starting at" in lowered or "start-stop" in lowered:
        return None
    if COMPLETE_PHASE_RE.search(sentence) and not FUTURE_OR_PLAN_RE.search(sentence):
        if re.search(r"\b(finali[sz](?:e|ed|ation)|final version|final report)\b", sentence, re.I):
            return "finalized"
        return "completed"
    if START_PHASE_RE.search(sentence) and not FUTURE_OR_PLAN_RE.search(sentence):
        return "started"
    if START_PHASE_RE.search(sentence):
        return "planned_start"
    return None


def phase_time_role(phase_role: Optional[str]) -> Optional[str]:
    if phase_role == "started":
        return "started_at"
    if phase_role == "completed":
        return "completed_at"
    if phase_role == "finalized":
        return "finalized_at"
    if phase_role == "planned_start":
        return "planned_for"
    return None


def normalize_time_role(value: object) -> Optional[str]:
    text = str(value or "").strip()
    if text in {"", "null", "None"}:
        return None
    return text if text in TIME_ROLES else None


def parse_event_datetime(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:width], fmt)
        except ValueError:
            continue
    return None


def date_value_from_day(day: datetime, event: EverMemEvent) -> str:
    event_dt = parse_event_datetime(event.occurred_at)
    if event_dt is not None:
        return f"{day.date().isoformat()} {event_dt.time().strftime('%H:%M:%S')}"
    return day.date().isoformat()


def resolve_relative_time_value(text: str, event: EverMemEvent) -> Optional[str]:
    event_dt = parse_event_datetime(event.occurred_at)
    if event_dt is None:
        return None
    lowered = text.lower()
    if "yesterday" in lowered:
        return date_value_from_day(event_dt - timedelta(days=1), event)
    if "tomorrow" in lowered or "next day" in lowered:
        return date_value_from_day(event_dt + timedelta(days=1), event)
    if "next week" in lowered:
        return date_value_from_day(event_dt + timedelta(days=7), event)
    if any(term in lowered for term in ("today", "this afternoon", "this morning", "this evening", "tonight")):
        return event.occurred_at
    weekday_names = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    match = WEEKDAY_RE.search(text)
    if match:
        target = weekday_names[match.group(2).lower()]
        delta = (target - event_dt.weekday()) % 7
        if match.group(1) or delta == 0:
            delta = delta or 7
        return date_value_from_day(event_dt + timedelta(days=delta), event)
    return None


def claim_grounding_text(claim: Mapping[str, Any]) -> str:
    return " ".join(
        str(part)
        for part in (
            claim.get("subject"),
            claim.get("predicate"),
            claim.get("object"),
            claim.get("facet_key"),
            claim.get("value"),
            claim.get("scope_hint"),
        )
        if part not in {None, ""}
    )


def infer_claim_time_annotation(claim: Mapping[str, Any], event: EverMemEvent) -> Optional[Dict[str, Any]]:
    time_role_value = normalize_time_role(claim.get("time_role"))
    if not time_role_value:
        return None
    text = claim_grounding_text(claim)
    explicit_date = ISO_DATE_RE.search(text)
    if explicit_date:
        source = "explicit_text_time"
        value = explicit_date.group(0)
    elif RELATIVE_TIME_RE.search(text) or WEEKDAY_RE.search(text):
        source = "relative_text_time"
        value = resolve_relative_time_value(text, event) or event.occurred_at
    elif claim.get("phase_role") in {"started", "completed", "finalized", "planned_start"} or time_role_value in {
        "started_at",
        "completed_at",
        "finalized_at",
    }:
        source = "phase_from_event_time"
        value = event.occurred_at
    else:
        source = "source_event_fallback"
        value = event.occurred_at
    return {
        "time_role": time_role_value,
        "time_value": value,
        "time_value_source": source,
        "time_explicitness_score": TIME_SOURCE_PRIORITY[source],
    }


def infer_effort_metric(text: str, facet_key: str) -> Optional[Dict[str, Any]]:
    match = EFFORT_METRIC_RE.search(text)
    if not match:
        return None
    unit_text = match.group(2).lower().replace(" ", "-")
    if unit_text.startswith("person") or unit_text.startswith("man"):
        metric_type = "person_days"
        unit = "person-days"
    elif unit_text in {"workday", "workdays", "working-day", "working-days"}:
        metric_type = "workdays"
        unit = "workdays"
    else:
        if facet_key != "metric" and not EFFORT_CONTEXT_RE.search(text):
            return None
        metric_type = "duration_days"
        unit = "days"
    lowered = text.lower()
    if any(term in lowered for term in ("actual", "spent", "invested")):
        effort_kind = "actual"
    elif any(term in lowered for term in ("planned", "estimated", "plan")):
        effort_kind = "planned"
    else:
        effort_kind = "duration"
    value_num = float(match.group(1))
    return {
        "metric_type": metric_type,
        "metric_unit": unit,
        "metric_value_num": value_num,
        "metric_value_text": match.group(0),
        "metric_kind": effort_kind,
        "metric_source": "claim_text_numeric_unit",
    }


def enrich_claim_annotations(claim: Dict[str, Any], event: EverMemEvent) -> Dict[str, Any]:
    metric = infer_effort_metric(claim_grounding_text(claim), str(claim.get("facet_key") or ""))
    if metric:
        claim.update(metric)
    time_annotation = infer_claim_time_annotation(claim, event)
    if time_annotation:
        claim.update(time_annotation)
    return claim


def infer_subject(sentence: str, event: EverMemEvent) -> str:
    lowered = sentence.lower()
    subject_patterns = (
        ("data submission api", "data_submission_api"),
        ("submission api", "data_submission_api"),
        ("sql", "sql_optimization"),
        ("stress test", "stress_test"),
        ("concurrent user", "stress_test"),
        ("cpu", "stress_test"),
        ("project charter", "project_charter"),
        ("scope statement", "project_charter"),
        ("fixed asset", "fixed_asset_ledger"),
        ("asset management", "asset_management"),
        ("scope 1", "emission_scope"),
        ("scope 2", "emission_scope"),
        ("scope 3", "emission_scope"),
        ("carbon emission", "carbon_emission_platform"),
        ("api", "api"),
        ("database", "database"),
        ("dashboard", "dashboard"),
        ("report", "reporting"),
        ("requirement", "requirements"),
        ("risk", "risk"),
        ("milestone", "milestone"),
        ("project", "project"),
    )
    for needle, subject in subject_patterns:
        if needle in lowered:
            return subject
    mentions = MENTION_RE.findall(sentence)
    if mentions:
        return "person:" + " ".join(mentions[0].split())
    return "speaker:" + (event.speaker or "unknown")


def infer_time_role(sentence: str, facet_key: str) -> Optional[str]:
    lowered = sentence.lower()
    if facet_key == "deadline" or any(term in lowered for term in ("deadline", "due", "eod", "end of day")):
        return "deadline_at"
    inferred_phase = infer_phase_role(sentence, facet_key)
    inferred_phase_time = phase_time_role(inferred_phase)
    if inferred_phase_time:
        return inferred_phase_time
    if any(term in lowered for term in ("planned", "schedule", "tomorrow", "next week")):
        return "planned_for"
    if any(term in lowered for term in ("updated", "changed", "final", "latest", "optimized")):
        return "updated_at"
    if ISO_DATE_RE.search(sentence):
        return "mentioned_at"
    return None


def relation_signal(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(term in lowered for term in UPDATE_TERMS)


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def shard_cache_path(base_cache_path: Path, stage: str, shard_name: str) -> Path:
    shard_dir = base_cache_path.with_suffix("")
    shard_dir = shard_dir.parent / f"{shard_dir.name}_shards" / stage
    shard_dir.mkdir(parents=True, exist_ok=True)
    return shard_dir / f"{safe_part(shard_name)}.json"


def make_sharded_client(runtime: LLMRuntimeConfig, stage: str, shard_name: str) -> LLMClient:
    return LLMClient(
        provider=runtime.provider,
        model=runtime.model,
        api_key=runtime.api_key,
        api_base=runtime.api_base,
        cache_path=shard_cache_path(runtime.cache_path, stage, shard_name),
        use_cache=runtime.use_cache,
    )


def extract_claims(event: EverMemEvent, max_claims_per_event: int) -> List[Dict[str, Any]]:
    if max_claims_per_event <= 0:
        return []
    claims: List[Dict[str, Any]] = []
    for sentence in sentence_candidates(event.text):
        if len(sentence) < 12 or not is_stateful_sentence(sentence):
            continue
        claim_number = len(claims) + 1
        facet_key = infer_facet_key(sentence)
        subject = infer_subject(sentence, event)
        phase_role = infer_phase_role(sentence, facet_key)
        time_role = infer_time_role(sentence, facet_key)
        confidence = 0.72 if relation_signal(sentence) or PERCENT_RE.search(sentence) else 0.58
        claim = {
            "node_type": "Claim",
            "claim_id": f"claim::{event.event_id}::{claim_number}",
            "topic_id": event.topic_id,
            "source_event_id": event.event_id,
            "scope_id": group_scope_id(event.topic_id, event.group),
            "subject": subject,
            "predicate": facet_key,
            "object": sentence[:800],
            "facet_key": facet_key,
            "value": sentence[:800],
            "confidence": confidence,
            "time_role": time_role,
            "phase_role": phase_role,
            "event_sort_key": list(event.sort_key),
            "extraction_method": "heuristic_sentence_v1",
        }
        claims.append(enrich_claim_annotations(claim, event))
        if len(claims) >= max_claims_per_event:
            break
    return claims


def llm_visible_event(event: EverMemEvent) -> Dict[str, Any]:
    return {
        "event_id": event.event_id,
        "topic_id": event.topic_id,
        "date": event.date,
        "group": event.group,
        "message_index": event.message_index,
        "speaker": event.speaker,
        "time": event.time,
        "text": event.text,
    }


def llm_claim_extraction_system_prompt() -> str:
    return (
        "Extract EverMemBench STS Claims from dialogue Events. Use only given Events; no QA, answers, options, "
        "or evidence labels. Output JSON only, no reasoning."
    )


def llm_claim_extraction_user_prompt(
    topic_id: str,
    events: Sequence[EverMemEvent],
    chunk_index: int,
    chunk_count: int,
    max_claims_per_event: int,
) -> str:
    payload = {
        "topic_id": topic_id,
        "stage": "offline_claim_extraction",
        "chunk_index": chunk_index,
        "visible_event_ids": [event.event_id for event in events],
        "visible_events": [llm_visible_event(event) for event in events],
        "task": (
            "Extract at most max_claims_per_event atomic state claims per event. Keep only durable state: owner, "
            "deadline, status, decision, constraint, metric, scope, risk, preference, next_step. Treat concrete task "
            "lifecycle announcements as durable state: if a speaker says they start/begin/officially start/have started "
            "work on a concrete task, extract a status claim with subject=that task, value=started, "
            "phase_role=started, time_role=started_at. If a task is completed/closed/released/uploaded/published, "
            "extract subject=that task, value=completed, phase_role=completed, time_role=completed_at. Do not skip "
            "first-person task start announcements as chit-chat. Skip chit-chat/news that has no durable task state."
        ),
        "facet_keys": "deadline|owner|status|next_step|preference|role|skill|style|constraint|metric|scope|decision|risk|link|state",
        "time_roles": "occurred_at|mentioned_at|updated_at|planned_for|deadline_at|valid_from|started_at|completed_at|finalized_at|null",
        "max_claims_per_event": max_claims_per_event,
        "output_schema": {
            "claims": [
                {
                    "event_id": "exact visible id",
                    "subject": "state object",
                    "predicate": "short predicate",
                    "object": "text-grounded atomic value",
                    "facet_key": "facet key",
                    "value": "grounded value",
                    "scope_hint": "",
                    "time_role": None,
                    "phase_role": "started|completed|finalized|planned_start|null",
                    "confidence": 0.8,
                }
            ],
            "rejected": [],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_llm_claims(
    raw: Mapping[str, Any],
    events: Sequence[EverMemEvent],
    per_event_counts: Dict[str, int],
    max_claims_per_event: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    events_by_id = {event.event_id: event for event in events}
    accepted: List[Dict[str, Any]] = []
    dropped_invalid = 0
    dropped_unsupported = 0
    dropped_over_limit = 0
    claims = raw.get("claims", [])
    if not isinstance(claims, list):
        claims = []
    for item in claims:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("event_id") or "")
        event = events_by_id.get(event_id)
        if event is None:
            dropped_invalid += 1
            continue
        if per_event_counts.get(event_id, 0) >= max_claims_per_event:
            dropped_over_limit += 1
            continue
        value = " ".join(str(item.get("value") or item.get("object") or "").split())
        if not value or token_support_score(value, event.text) < 0.25:
            dropped_unsupported += 1
            continue
        per_event_counts[event_id] = per_event_counts.get(event_id, 0) + 1
        facet_key = str(item.get("facet_key") or infer_facet_key(value) or "state").strip() or "state"
        subject = str(item.get("subject") or infer_subject(value, event)).strip() or infer_subject(value, event)
        phase_role = str(item.get("phase_role") or "").strip() or infer_phase_role(value, facet_key)
        if phase_role in {"", "null", "None"}:
            phase_role = None
        time_role = normalize_time_role(item.get("time_role")) or phase_time_role(phase_role) or infer_time_role(value, facet_key)
        claim = {
            "node_type": "Claim",
            "claim_id": f"claim::{event.event_id}::{per_event_counts[event_id]}",
            "topic_id": event.topic_id,
            "source_event_id": event.event_id,
            "scope_id": group_scope_id(event.topic_id, event.group),
            "subject": subject[:160],
            "predicate": str(item.get("predicate") or facet_key)[:120],
            "object": str(item.get("object") or value)[:800],
            "facet_key": facet_key[:80],
            "value": value[:800],
            "scope_hint": str(item.get("scope_hint") or "")[:160],
            "confidence": float(item.get("confidence") or 0.0),
            "time_role": time_role,
            "phase_role": phase_role,
            "event_sort_key": list(event.sort_key),
            "extraction_method": "llm_offline_claim_extraction",
        }
        accepted.append(enrich_claim_annotations(claim, event))
    validation = {
        "visible_event_count": len(events),
        "accepted_claim_count": len(accepted),
        "dropped_invalid_event_id_count": dropped_invalid,
        "dropped_unsupported_count": dropped_unsupported,
        "dropped_over_limit_count": dropped_over_limit,
    }
    return accepted, validation


def extract_llm_claims(
    client: LLMClient,
    topic_id: str,
    events: Sequence[EverMemEvent],
    message_chunk_size: int,
    max_claims_per_event: int,
    runtime: Optional[LLMRuntimeConfig] = None,
    workers: int = 1,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    claims: List[Dict[str, Any]] = []
    validations: List[Dict[str, Any]] = []
    event_chunks = chunks(events, message_chunk_size)

    def run_chunk(chunk_index: int, event_chunk: Sequence[EverMemEvent]) -> Tuple[int, List[Dict[str, Any]], Dict[str, Any]]:
        chunk_client = client
        if workers > 1:
            if runtime is None:
                raise ValueError("parallel claim extraction requires LLMRuntimeConfig")
            first_id = event_chunk[0].event_id if event_chunk else "empty"
            last_id = event_chunk[-1].event_id if event_chunk else "empty"
            chunk_client = make_sharded_client(runtime, "claim_extraction", f"{topic_id}_{chunk_index:05d}_{short_hash(first_id + last_id)}")
        raw = chunk_client.complete_json(
            llm_claim_extraction_system_prompt(),
            llm_claim_extraction_user_prompt(topic_id, event_chunk, chunk_index, len(event_chunks), max_claims_per_event),
        )
        chunk_claims, validation = normalize_llm_claims(raw, event_chunk, {}, max_claims_per_event)
        validation["chunk_index"] = chunk_index
        return chunk_index, chunk_claims, validation

    if workers <= 1:
        for chunk_index, event_chunk in enumerate(event_chunks, start=1):
            print(f"  LLM claim extraction chunk {chunk_index}/{len(event_chunks)} events={len(event_chunk)}", flush=True)
            _, chunk_claims, validation = run_chunk(chunk_index, event_chunk)
            claims.extend(chunk_claims)
            validations.append(validation)
            print(
                f"  chunk {chunk_index}/{len(event_chunks)} accepted={validation['accepted_claim_count']} "
                f"dropped_invalid={validation['dropped_invalid_event_id_count']} "
                f"dropped_unsupported={validation['dropped_unsupported_count']}",
                flush=True,
            )
        return claims, validations

    results: Dict[int, Tuple[List[Dict[str, Any]], Dict[str, Any]]] = {}
    max_workers = max(1, workers)
    print(f"  LLM claim extraction parallel workers={max_workers} chunks={len(event_chunks)}", flush=True)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_chunk, chunk_index, event_chunk): chunk_index
            for chunk_index, event_chunk in enumerate(event_chunks, start=1)
        }
        for future in as_completed(futures):
            chunk_index, chunk_claims, validation = future.result()
            results[chunk_index] = (chunk_claims, validation)
            print(
                f"  chunk {chunk_index}/{len(event_chunks)} accepted={validation['accepted_claim_count']} "
                f"dropped_invalid={validation['dropped_invalid_event_id_count']} "
                f"dropped_unsupported={validation['dropped_unsupported_count']}",
                flush=True,
            )
    for chunk_index in sorted(results):
        chunk_claims, validation = results[chunk_index]
        claims.extend(chunk_claims)
        validations.append(validation)
    return claims, validations


def event_has_stateful_signal(event: EverMemEvent) -> bool:
    return any(is_stateful_sentence(sentence) for sentence in sentence_candidates(event.text))


def select_events_for_llm_claims(events: Sequence[EverMemEvent], llm_event_filter: str) -> List[EverMemEvent]:
    if llm_event_filter == "all":
        return list(events)
    return [event for event in events if event_has_stateful_signal(event)]


def add_node(nodes: Dict[str, Dict[str, Any]], node: Dict[str, Any]) -> None:
    identifier = node_id(node)
    if not identifier:
        raise ValueError(f"node has no id: {node}")
    nodes.setdefault(identifier, node)


def add_edge(edges: List[Dict[str, Any]], edge_type: str, source: str, target: str, **payload: Any) -> None:
    edge = {"type": edge_type, "from": source, "to": target}
    edge.update({key: value for key, value in payload.items() if value is not None})
    edges.append(edge)


def add_time_node(nodes: Dict[str, Dict[str, Any]], topic_id: str, role: str, value: str) -> str:
    time_node_id = time_id(role, value)
    add_node(
        nodes,
        {
            "node_type": "Time",
            "time_id": time_node_id,
            "topic_id": topic_id,
            "time_role": role,
            "value": value,
        },
    )
    return time_node_id


def materialize_claim_time(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    claim: Mapping[str, Any],
    event: EverMemEvent,
) -> None:
    time_role_value = normalize_time_role(claim.get("time_role"))
    if not time_role_value:
        return
    annotation = infer_claim_time_annotation(claim, event)
    time_value = str((annotation or {}).get("time_value") or event.occurred_at)
    time_value_source = str((annotation or {}).get("time_value_source") or "source_event_fallback")
    time_explicitness_score = float((annotation or {}).get("time_explicitness_score") or TIME_SOURCE_PRIORITY["source_event_fallback"])
    time_node_id = add_time_node(nodes, event.topic_id, time_role_value, time_value)
    add_edge(
        edges,
        "HAS_TIME",
        str(claim["claim_id"]),
        time_node_id,
        reason=f"claim time_role materialized from {time_value_source}",
        time_role=time_role_value,
        phase_role=claim.get("phase_role"),
        source_event_id=event.event_id,
        time_value_source=time_value_source,
        time_explicitness_score=time_explicitness_score,
    )


def dedupe_edges(edges: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for edge in edges:
        key = (
            str(edge.get("type") or ""),
            str(edge.get("from") or ""),
            str(edge.get("to") or ""),
            json.dumps(edge.get("evidence_event_ids", []), ensure_ascii=False, sort_keys=True),
            str(edge.get("time_role") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(edge))
    return deduped


def build_base_graph(
    events: Sequence[EverMemEvent],
    claim_mode: str,
    max_claims_per_event: int,
    llm_claims: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    claims: List[Dict[str, Any]] = []
    llm_claims_by_event: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for claim in llm_claims or []:
        llm_claims_by_event[str(claim.get("source_event_id") or "")].append(dict(claim))

    for event in events:
        add_node(nodes, event.visible_event())
        add_node(nodes, scope_node(event.topic_id, "project", event.topic_id, f"ProjectScope({event.topic_id})"))
        add_node(nodes, scope_node(event.topic_id, "group", event.group, f"GroupScope({event.topic_id}, {event.group})"))
        add_node(nodes, scope_node(event.topic_id, "person", event.speaker, f"PersonScope({event.speaker})"))
        event_time_id = add_time_node(nodes, event.topic_id, "occurred_at", event.occurred_at)
        add_edge(edges, "IN_SCOPE", event.event_id, project_scope_id(event.topic_id), reason="topic corpus boundary")
        add_edge(edges, "IN_SCOPE", event.event_id, group_scope_id(event.topic_id, event.group), reason="dialogue group")
        add_edge(edges, "IN_SCOPE", event.event_id, person_scope_id(event.topic_id, event.speaker), reason="speaker scope")
        add_edge(edges, "MENTIONS", event.event_id, person_scope_id(event.topic_id, event.speaker), reason="speaker")
        add_edge(edges, "OCCURRED_AT", event.event_id, event_time_id, reason="event occurrence time")

        if claim_mode == "llm":
            event_claims = llm_claims_by_event.get(event.event_id, [])
        elif claim_mode == "heuristic":
            event_claims = extract_claims(event, max_claims_per_event)
        else:
            event_claims = []
        if claim_mode in {"llm", "heuristic"}:
            event_claims = augment_event_lifecycle_claims(event, event_claims)
        for claim in event_claims:
            claims.append(claim)
            materialize_claim_task_objects(nodes, edges, claim, event)
            materialize_claim_responsibility_edges(nodes, edges, claim, event)
            add_node(nodes, claim)
            add_node(nodes, subject_node(event.topic_id, str(claim["subject"])))
            extraction_method = str(claim.get("extraction_method") or f"{claim_mode}_claim_extraction")
            add_edge(edges, "ASSERTS", event.event_id, str(claim["claim_id"]), reason=extraction_method)
            add_edge(edges, "MENTIONS", event.event_id, subject_entity_id(event.topic_id, str(claim["subject"])), reason="claim subject")
            materialize_claim_time(nodes, edges, claim, event)
    return nodes, edges, claims


def claim_bucket_key(claim: Mapping[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(claim.get("topic_id") or ""),
        str(claim.get("scope_id") or ""),
        str(claim.get("subject") or ""),
        str(claim.get("facet_key") or ""),
    )


def sort_claims_for_state(claims: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return sorted((dict(claim) for claim in claims), key=lambda item: tuple(item.get("event_sort_key") or []))


def resolver_claim_payload(claim: Mapping[str, Any], events_by_id: Mapping[str, EverMemEvent]) -> Dict[str, Any]:
    event_id = str(claim.get("source_event_id") or "")
    event = events_by_id.get(event_id)
    return {
        "claim_id": claim.get("claim_id"),
        "source_event_id": event_id,
        "event_time": event.occurred_at if event else "",
        "speaker": event.speaker if event else "",
        "subject": claim.get("subject"),
        "facet_key": claim.get("facet_key"),
        "value": claim.get("value"),
        "time_role": claim.get("time_role"),
    }


def llm_resolver_system_prompt() -> str:
    return (
        "Resolve one EverMemBench STS state bucket. Use only given Claims and Event metadata; no QA, answers, "
        "options, gold evidence, or outside knowledge. Output JSON only, no reasoning."
    )


def llm_resolver_user_prompt(
    bucket_key: Tuple[str, str, str, str],
    claims: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, EverMemEvent],
    candidate_limit: int,
) -> str:
    topic_id, scope, subject, facet_key = bucket_key
    ordered = sort_claims_for_state(claims)
    if candidate_limit > 0 and len(ordered) > candidate_limit:
        ordered = ordered[-candidate_limit:]
    payload = {
        "stage": "offline_statefacet_resolution",
        "bucket": {"topic_id": topic_id, "scope_id": scope, "subject": subject, "facet_key": facet_key},
        "policy": "Pick current state. Explicit update/correction wins; later same-bucket claim may supersede older; mark ambiguous if unresolved. Do not invent.",
        "candidate_claim_count": len(claims),
        "candidate_limit_used": candidate_limit if candidate_limit > 0 else None,
        "candidate_claims": [resolver_claim_payload(claim, events_by_id) for claim in ordered],
        "output_schema": {
            "status": "current|ambiguous",
            "state_value": "grounded current value",
            "support_claim_ids": ["claim id(s) supporting the StateFacet"],
            "current_after_event_id": "source event id after which this value is current",
            "relations": [
                {
                    "type": "CORRECTS|SUPERSEDES|CONFLICTS_WITH",
                    "from": "claim id",
                    "to": "claim id",
                    "reason": "why relation holds",
                }
            ],
            "resolver_reason": "brief",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_resolver_output(
    raw: Mapping[str, Any],
    ordered_claims: Sequence[Dict[str, Any]],
    events_by_id: Mapping[str, EverMemEvent],
) -> Dict[str, Any]:
    claims_by_id = {str(claim.get("claim_id") or ""): claim for claim in ordered_claims}
    latest = ordered_claims[-1]
    support_claim_ids = [
        str(claim_id)
        for claim_id in raw.get("support_claim_ids", [])
        if str(claim_id) in claims_by_id
    ] if isinstance(raw.get("support_claim_ids"), list) else []
    if not support_claim_ids:
        support_claim_ids = [str(latest.get("claim_id"))]
    support_event_ids = [
        str(claims_by_id[claim_id].get("source_event_id") or "")
        for claim_id in support_claim_ids
        if claims_by_id[claim_id].get("source_event_id")
    ]
    current_after_event_id = str(raw.get("current_after_event_id") or support_event_ids[-1] if support_event_ids else "")
    if current_after_event_id not in events_by_id and support_event_ids:
        current_after_event_id = support_event_ids[-1]
    state_value = " ".join(str(raw.get("state_value") or "").split())
    if not state_value:
        state_value = str(claims_by_id[support_claim_ids[-1]].get("value") or "")
    relations: List[Dict[str, Any]] = []
    raw_relations = raw.get("relations", [])
    if isinstance(raw_relations, list):
        for item in raw_relations:
            if not isinstance(item, dict):
                continue
            relation_type = str(item.get("type") or "").upper()
            source = str(item.get("from") or "")
            target = str(item.get("to") or "")
            if relation_type not in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}:
                continue
            if source not in claims_by_id or target not in claims_by_id or source == target:
                continue
            relations.append(
                {
                    "type": relation_type,
                    "from": source,
                    "to": target,
                    "reason": str(item.get("reason") or "llm_resolver"),
                    "evidence_event_ids": [claims_by_id[source].get("source_event_id")],
                }
            )
    return {
        "status": str(raw.get("status") or "current") if str(raw.get("status") or "") in {"current", "ambiguous"} else "current",
        "state_value": state_value[:1000],
        "support_claim_ids": support_claim_ids,
        "support_event_ids": support_event_ids,
        "current_after_event_id": current_after_event_id,
        "relations": relations,
        "resolver_reason": str(raw.get("resolver_reason") or "llm current-state resolver")[:500],
    }


def resolve_bucket_with_llm(
    client: LLMClient,
    bucket_key: Tuple[str, str, str, str],
    ordered_claims: Sequence[Dict[str, Any]],
    events_by_id: Mapping[str, EverMemEvent],
    candidate_limit: int,
) -> Dict[str, Any]:
    raw = client.complete_json(
        llm_resolver_system_prompt(),
        llm_resolver_user_prompt(bucket_key, ordered_claims, events_by_id, candidate_limit),
    )
    return normalize_resolver_output(raw, ordered_claims, events_by_id)


def resolve_bucket_heuristic(ordered_claims: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    current = ordered_claims[-1]
    relations: List[Dict[str, Any]] = []
    if len(ordered_claims) >= 2 and relation_signal(str(current.get("value") or "")):
        previous = ordered_claims[-2]
        relations.append(
            {
                "type": "SUPERSEDES",
                "from": str(current.get("claim_id")),
                "to": str(previous.get("claim_id")),
                "reason": "later claim has explicit update/correction signal in same state bucket",
                "evidence_event_ids": [current.get("source_event_id")],
            }
        )
    return {
        "status": "current",
        "state_value": str(current.get("value") or "")[:1000],
        "support_claim_ids": [str(current.get("claim_id"))],
        "support_event_ids": [str(current.get("source_event_id"))],
        "current_after_event_id": str(current.get("source_event_id") or ""),
        "relations": relations,
        "resolver_reason": "heuristic current-state baseline: latest stateful claim in the same topic/scope/subject/facet bucket",
    }


def build_state_facets(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    claims: Sequence[Dict[str, Any]],
    events_by_id: Mapping[str, EverMemEvent],
    resolver_mode: str,
    client: Optional[LLMClient],
    runtime: Optional[LLMRuntimeConfig],
    resolver_candidate_limit: int,
    resolver_bucket_limit: int,
    resolver_workers: int,
) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        grouped[claim_bucket_key(claim)].append(claim)

    sorted_buckets = [(bucket_key, sort_claims_for_state(bucket)) for bucket_key, bucket in sorted(grouped.items())]
    llm_bucket_keys: List[Tuple[str, str, str, str]] = []
    for bucket_key, ordered in sorted_buckets:
        if resolver_mode == "llm" and len(ordered) >= 2:
            if resolver_bucket_limit > 0 and len(llm_bucket_keys) >= resolver_bucket_limit:
                break
            llm_bucket_keys.append(bucket_key)
    llm_bucket_set = set(llm_bucket_keys)
    resolved_by_bucket: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    def run_resolver(index: int, bucket_key: Tuple[str, str, str, str], ordered: Sequence[Dict[str, Any]]) -> Tuple[Tuple[str, str, str, str], Dict[str, Any]]:
        resolver_client = client
        if resolver_workers > 1:
            if runtime is None:
                raise ValueError("parallel resolver requires LLMRuntimeConfig")
            resolver_client = make_sharded_client(
                runtime,
                "state_resolver",
                f"{bucket_key[0]}_{index:05d}_{short_hash('|'.join(bucket_key))}",
            )
        if resolver_client is None:
            raise ValueError("LLM resolver requires an LLM client")
        return bucket_key, resolve_bucket_with_llm(resolver_client, bucket_key, ordered, events_by_id, resolver_candidate_limit)

    if llm_bucket_keys:
        ordered_by_key = {bucket_key: ordered for bucket_key, ordered in sorted_buckets}
        if resolver_workers <= 1:
            for index, bucket_key in enumerate(llm_bucket_keys, start=1):
                print(f"  LLM resolver bucket {index}/{len(llm_bucket_keys)}", flush=True)
                key, resolved = run_resolver(index, bucket_key, ordered_by_key[bucket_key])
                resolved_by_bucket[key] = resolved
        else:
            print(f"  LLM resolver parallel workers={resolver_workers} buckets={len(llm_bucket_keys)}", flush=True)
            with ThreadPoolExecutor(max_workers=max(1, resolver_workers)) as executor:
                futures = {
                    executor.submit(run_resolver, index, bucket_key, ordered_by_key[bucket_key]): bucket_key
                    for index, bucket_key in enumerate(llm_bucket_keys, start=1)
                }
                completed = 0
                for future in as_completed(futures):
                    key, resolved = future.result()
                    resolved_by_bucket[key] = resolved
                    completed += 1
                    print(f"  resolver bucket {completed}/{len(llm_bucket_keys)} done", flush=True)

    facets: List[Dict[str, Any]] = []
    for bucket_key, ordered in sorted_buckets:
        topic_id, scope, subject, facet_key = bucket_key
        use_llm = bucket_key in llm_bucket_set and bucket_key in resolved_by_bucket
        if use_llm:
            resolved = resolved_by_bucket[bucket_key]
        else:
            resolved = resolve_bucket_heuristic(ordered)
        current_after_event_id = str(resolved.get("current_after_event_id") or "")
        event = events_by_id.get(current_after_event_id)
        current_after = event.occurred_at if event else ""
        bucket_hash = short_hash("|".join((topic_id, scope, subject, facet_key)))
        facet_id = (
            f"sf::{safe_part(topic_id)}::{bucket_hash}::"
            f"{safe_part(scope)}::{safe_part(subject)}::{safe_part(facet_key)}"
        )
        facet = {
            "node_type": "StateFacet",
            "facet_id": facet_id,
            "state_facet_id": facet_id,
            "topic_id": topic_id,
            "scope_id": scope,
            "subject": subject,
            "facet_key": facet_key,
            "value": resolved.get("state_value"),
            "status": resolved.get("status"),
            "current_after": current_after,
            "support_claim_ids": resolved.get("support_claim_ids", []),
            "support_event_ids": resolved.get("support_event_ids", []),
            "resolver_reason": resolved.get("resolver_reason"),
            "resolver_mode": "llm" if use_llm else "heuristic",
        }
        ordered_by_claim_id = {str(claim.get("claim_id") or ""): claim for claim in ordered}
        metric_claims = [
            ordered_by_claim_id[str(claim_id)]
            for claim_id in resolved.get("support_claim_ids", [])
            if str(claim_id) in ordered_by_claim_id and ordered_by_claim_id[str(claim_id)].get("metric_type")
        ]
        if metric_claims:
            metric_claim = metric_claims[-1]
            facet.update(
                {
                    "metric_type": metric_claim.get("metric_type"),
                    "metric_unit": metric_claim.get("metric_unit"),
                    "metric_value_num": metric_claim.get("metric_value_num"),
                    "metric_value_text": metric_claim.get("metric_value_text"),
                    "metric_kind": metric_claim.get("metric_kind"),
                    "metric_source": metric_claim.get("metric_source"),
                }
            )
        facets.append(facet)
        add_node(nodes, facet)
        current_after_time_id = add_time_node(nodes, topic_id, "current_after", current_after)
        for claim_id in resolved.get("support_claim_ids", []):
            add_edge(edges, "SUPPORTS", str(claim_id), facet_id, reason="current supporting claim")
        add_edge(edges, "CURRENT_STATE_OF", facet_id, scope, reason="facet resolved under group scope")
        add_edge(edges, "CURRENT_AFTER", facet_id, current_after_time_id, reason="latest support event time")
        for relation in resolved.get("relations", []):
            add_edge(
                edges,
                str(relation.get("type")),
                str(relation.get("from")),
                str(relation.get("to")),
                reason=relation.get("reason"),
                evidence_event_ids=relation.get("evidence_event_ids"),
            )
    return facets


def validate_graph(nodes: Mapping[str, Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> List[str]:
    warnings: List[str] = []
    node_types_by_id = {identifier: str(node.get("node_type") or "") for identifier, node in nodes.items()}
    for identifier, node in nodes.items():
        node_type = str(node.get("node_type") or "")
        if node_type not in NODE_TYPES:
            warnings.append(f"unsupported_node_type:{identifier}:{node_type}")
    seen_edges = set()
    for index, edge in enumerate(edges):
        edge_type = str(edge.get("type") or "")
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if edge_type not in EDGE_TYPES:
            warnings.append(f"unsupported_edge_type:{index}:{edge_type}")
            continue
        if source not in node_types_by_id or target not in node_types_by_id:
            warnings.append(f"edge_missing_endpoint:{index}:{edge_type}:{source}->{target}")
            continue
        expected = EDGE_ENDPOINT_TYPES[edge_type]
        actual = (node_types_by_id[source], node_types_by_id[target])
        if actual != expected:
            warnings.append(f"edge_endpoint_type_mismatch:{index}:{edge_type}:{actual[0]}->{actual[1]}")
        edge_key = (edge_type, source, target, json.dumps(edge.get("evidence_event_ids", []), sort_keys=True))
        if edge_key in seen_edges:
            warnings.append(f"duplicate_edge:{index}:{edge_type}:{source}->{target}")
        seen_edges.add(edge_key)
    forbidden_fields = {"A", "R", "answer", "options", "gold_evidence"}
    for identifier, node in nodes.items():
        leaked = sorted(forbidden_fields & set(node.keys()))
        if leaked:
            warnings.append(f"forbidden_gold_field:{identifier}:{','.join(leaked)}")
    return warnings


def build_topic_graph(
    topic_id: str,
    data_root: Path,
    claim_mode: str,
    resolver_mode: str,
    max_claims_per_event: int,
    event_limit: int,
    client: Optional[LLMClient],
    runtime: Optional[LLMRuntimeConfig],
    provider: Optional[str],
    model: Optional[str],
    message_chunk_size: int,
    llm_event_filter: str,
    claim_workers: int,
    resolver_candidate_limit: int,
    resolver_bucket_limit: int,
    resolver_workers: int,
) -> Dict[str, Any]:
    events = load_topic_events(topic_id, data_root, event_limit=event_limit)
    llm_validations: List[Dict[str, Any]] = []
    llm_claims: Optional[List[Dict[str, Any]]] = None
    llm_events = select_events_for_llm_claims(events, llm_event_filter) if claim_mode == "llm" else []
    if claim_mode == "llm":
        if client is None:
            raise ValueError("--claim-mode llm requires an LLM client")
        llm_claims, llm_validations = extract_llm_claims(
            client,
            topic_id,
            llm_events,
            message_chunk_size,
            max_claims_per_event,
            runtime=runtime,
            workers=claim_workers,
        )
    if resolver_mode == "llm" and client is None:
        raise ValueError("--resolver-mode llm requires an LLM client")
    nodes, edges, claims = build_base_graph(events, claim_mode, max_claims_per_event, llm_claims=llm_claims)
    facets = build_state_facets(
        nodes,
        edges,
        claims,
        {event.event_id: event for event in events},
        resolver_mode=resolver_mode,
        client=client,
        runtime=runtime,
        resolver_candidate_limit=resolver_candidate_limit,
        resolver_bucket_limit=resolver_bucket_limit,
        resolver_workers=resolver_workers,
    )
    state_task_object_link_count = materialize_state_task_object_links(
        nodes,
        edges,
        {str(claim.get("claim_id") or ""): claim for claim in claims},
    )
    edges = dedupe_edges(edges)
    warnings = validate_graph(nodes, edges)
    node_rows = sorted(nodes.values(), key=lambda item: (str(item.get("node_type") or ""), node_id(item)))
    edge_rows = sorted(edges, key=lambda item: (str(item.get("type") or ""), str(item.get("from") or ""), str(item.get("to") or "")))
    llm_resolved_facet_count = sum(1 for facet in facets if facet.get("resolver_mode") == "llm")
    summary = {
        "topic_id": topic_id,
        "event_count": len(events),
        "claim_count": len(claims),
        "state_facet_count": len(facets),
        "llm_claim_extraction_event_filter": llm_event_filter if claim_mode == "llm" else None,
        "llm_claim_extraction_event_count": len(llm_events),
        "llm_claim_extraction_chunks": len(llm_validations),
        "llm_claim_extraction_accepted": sum(int(item.get("accepted_claim_count", 0)) for item in llm_validations),
        "llm_resolved_state_facet_count": llm_resolved_facet_count,
        "claim_workers": claim_workers,
        "resolver_workers": resolver_workers,
        "node_count": len(node_rows),
        "edge_count": len(edge_rows),
        "node_counts": dict(Counter(str(node.get("node_type") or "") for node in node_rows)),
        "edge_counts": dict(Counter(str(edge.get("type") or "") for edge in edge_rows)),
        "task_object_scope_count": sum(
            1
            for node in node_rows
            if node.get("node_type") == "Entity/Scope" and node.get("scope_type") == "task_object"
        ),
        "state_task_object_link_count": state_task_object_link_count,
        "responsibility_link_count": sum(1 for edge in edge_rows if edge.get("type") == "RESPONSIBLE_FOR"),
        "claim_facets": dict(Counter(str(claim.get("facet_key") or "") for claim in claims).most_common()),
        "claim_extraction_methods": dict(Counter(str(claim.get("extraction_method") or "") for claim in claims).most_common()),
        "claim_time_value_sources": dict(Counter(str(claim.get("time_value_source") or "None") for claim in claims).most_common()),
        "claim_metric_types": dict(Counter(str(claim.get("metric_type") or "None") for claim in claims).most_common()),
        "claim_metric_units": dict(Counter(str(claim.get("metric_unit") or "None") for claim in claims).most_common()),
        "top_subjects": dict(Counter(str(claim.get("subject") or "") for claim in claims).most_common(20)),
        "warnings": warnings,
    }
    manifest = {
        "benchmark": "EverMemBench",
        "topic_id": topic_id,
        "schema_version": "evermembench-sts-topic-graph-v6-endpoint-lifecycle",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(data_root),
        "source_files": [str(data_root / topic_id / "dialogue.json")],
        "leakage_policy": {
            "graph_build_inputs": ["dialogue.json"],
            "qa_loaded": False,
            "gold_fields_loaded": [],
            "notes": "This builder does not read qa_*.json, A, R, options, or evidence spans.",
        },
        "claim_mode": claim_mode,
        "resolver_mode": resolver_mode,
        "provider": provider,
        "model": model,
        "max_claims_per_event": max_claims_per_event,
        "message_chunk_size": message_chunk_size,
        "llm_event_filter": llm_event_filter,
        "claim_workers": claim_workers,
        "resolver_workers": resolver_workers,
        "resolver_candidate_limit": resolver_candidate_limit,
        "resolver_bucket_limit": resolver_bucket_limit,
        "event_limit": event_limit,
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
        "edge_endpoint_types": {edge: list(types) for edge, types in EDGE_ENDPOINT_TYPES.items()},
        "summary": summary,
    }
    return {"manifest": manifest, "summary": summary, "nodes": node_rows, "edges": edge_rows, "events": [asdict(event) for event in events]}


def write_topic_graph(output_dir: Path, topic_id: str, graph: Mapping[str, Any]) -> Path:
    topic_dir = output_dir / safe_part(topic_id)
    if topic_dir.exists():
        shutil.rmtree(topic_dir)
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "manifest.json").write_text(json_dump(graph["manifest"]), encoding="utf-8")
    (topic_dir / "graph_summary.json").write_text(json_dump(graph["summary"]), encoding="utf-8")
    write_jsonl(topic_dir / "nodes.jsonl", graph["nodes"])
    write_jsonl(topic_dir / "edges.jsonl", graph["edges"])
    return topic_dir


def main() -> int:
    args = parse_args()
    client: Optional[LLMClient] = None
    runtime: Optional[LLMRuntimeConfig] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    needs_llm = args.claim_mode == "llm" or args.resolver_mode == "llm"
    if needs_llm:
        load_dotenv()
        if args.max_tokens:
            os.environ["LLM_MAX_TOKENS"] = str(args.max_tokens)
        api_key, model, api_base = provider_config(args.provider)
        if args.model:
            model = args.model
        provider = args.provider
        client = LLMClient(
            provider=args.provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            cache_path=Path(args.cache),
            use_cache=not args.no_cache,
        )
        runtime = LLMRuntimeConfig(
            provider=args.provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            cache_path=Path(args.cache),
            use_cache=not args.no_cache,
        )
    try:
        graph = build_topic_graph(
            topic_id=args.topic,
            data_root=Path(args.data_root),
            claim_mode=args.claim_mode,
            resolver_mode=args.resolver_mode,
            max_claims_per_event=args.max_claims_per_event,
            event_limit=args.event_limit,
            client=client,
            runtime=runtime,
            provider=provider,
            model=model,
            message_chunk_size=args.message_chunk_size,
            llm_event_filter=args.llm_event_filter,
            claim_workers=args.claim_workers,
            resolver_candidate_limit=args.resolver_candidate_limit,
            resolver_bucket_limit=args.resolver_bucket_limit,
            resolver_workers=args.resolver_workers,
        )
    except LLMRequestError as exc:
        print("\nLLM request failed during EverMemBench graph build.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("\nEverMemBench graph build failed.", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    topic_dir = write_topic_graph(Path(args.output_dir), args.topic, graph)
    summary = graph["summary"]
    print("EverMemBench topic graph")
    print(f"topic={args.topic} output_dir={topic_dir}")
    if needs_llm:
        print(f"provider={provider} model={model}")
    print(
        f"events={summary['event_count']} claims={summary['claim_count']} "
        f"state_facets={summary['state_facet_count']} nodes={summary['node_count']} edges={summary['edge_count']}"
    )
    if needs_llm:
        print(
            f"llm_claim_chunks={summary['llm_claim_extraction_chunks']} "
            f"llm_resolved_state_facets={summary['llm_resolved_state_facet_count']}"
        )
    print(f"warnings={len(summary['warnings'])}")
    if summary["warnings"]:
        for warning in summary["warnings"][:10]:
            print(f"warning: {warning}")
    return 0 if not summary["warnings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

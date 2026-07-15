from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


BASELINE_DIR = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = BASELINE_DIR.parent
PROJECT_DIR = BENCHMARK_DIR.parents[2]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from common.loader import DATA_PATH, DialogTurn, dialog_sort_key, load_sample  # noqa: E402
from pipeline.external.paths import EXTERNAL_CACHE_DIR, EXTERNAL_GRAPH_DIR  # noqa: E402
from pipeline.external.state_merge import (  # noqa: E402
    STATE_MERGE_DECISIONS,
    StateMergeAdapter,
    fold_state_claims as fold_state_claims_generic,
)
from pipeline.external.sts_v2.schema import SCHEMA_VERSION  # noqa: E402


NODE_TYPES = ("Episode/Event", "Claim", "StateFacet", "Entity/Scope", "Time")
GRAPH_SCHEMA_V1 = "locomo-qa-sample-sts-graph-v1"
GRAPH_SCHEMA_V2 = SCHEMA_VERSION
GRAPH_SCHEMAS = ("v1", "v2")
TIME_ROLES = (
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
)
CURRENT_AFTER_TIME_ROLES = {
    "occurred_at",
    "updated_at",
    "valid_from",
    "started_at",
    "completed_at",
    "finalized_at",
    "current_after",
}
EMPTY_TIME_VALUES = {
    "",
    "empty",
    "n/a",
    "na",
    "none",
    "not mentioned",
    "not specified",
    "null",
    "unknown",
}
PAST_TIME_EXPRESSION_RE = re.compile(
    r"\b(?:ago|earlier|last\s+(?:day|night|week|month|year|mon(?:day)?|tues?(?:day)?|"
    r"wednes(?:day)?|thurs?(?:day)?|fri(?:day)?|satur(?:day)?|sun(?:day)?)|previous(?:ly)?|yesterday)\b",
    re.IGNORECASE,
)
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
}
FACET_KEYS = {
    "activity",
    "date",
    "education",
    "event",
    "family",
    "health",
    "identity",
    "location",
    "occupation",
    "plan",
    "place",
    "possession",
    "preference",
    "relationship",
    "status",
    "time",
    "travel",
    "work",
    "other",
}
V2_PERSISTENT_STATE_FACETS = frozenset(
    {
        "education",
        "family",
        "health",
        "identity",
        "location",
        "occupation",
        "place",
        "possession",
        "preference",
        "relationship",
        "status",
        "work",
    }
)
V2_NON_STATE_TIME_ROLES = frozenset(
    {
        "completed_at",
        "deadline_at",
        "finalized_at",
        "occurred_at",
        "planned_for",
    }
)
V2_ACTIVITY_STATE_BOUNDARY_ROLES = frozenset({"started_at", "updated_at", "valid_from"})
V2_STATE_DOMAIN_ALIASES = {"work": "occupation"}
V2_SINGLE_SLOT_DIMENSIONS = {
    "location": "residence",
    "occupation": "primary",
}
V2_OBJECT_SCOPED_STATE_DOMAINS = frozenset(
    {
        "activity",
        "education",
        "family",
        "health",
        "identity",
        "place",
        "possession",
        "preference",
        "relationship",
        "status",
    }
)
V2_GENERIC_STATE_TARGETS_BY_DOMAIN = {
    "activity": frozenset({"activity", "current_activity"}),
    "education": frozenset({"education", "educational_status"}),
    "family": frozenset({"family", "family_relationship", "family_status"}),
    "health": frozenset({"health", "condition", "health_condition", "medical_condition"}),
    "identity": frozenset({"identity", "attribute", "personal_attribute"}),
    "place": frozenset({"place", "location"}),
    "possession": frozenset({"possession", "possessions", "belonging", "belongings"}),
    "preference": frozenset({"preference", "preferences", "interest", "interests"}),
    "relationship": frozenset({"relationship", "relationship_status"}),
    "status": frozenset({"status", "current_status"}),
}
V2_RESIDENCE_STATE_RE = re.compile(
    r"\b(?:home|live|lives|lived|living|move|moved|moving|reside|resides|resided|residing)\b",
    re.I,
)
V2_PAST_ONLY_STATE_RE = re.compile(r"\b(?:formerly|previously|used\s+to)\b", re.I)
V2_CURRENT_STATE_CUE_RE = re.compile(r"\b(?:currently|no\s+longer|now|still)\b", re.I)
FACT_TYPES = {"state", "event"}
TEMPORAL_STATUSES = {"ongoing", "bounded", "prospective", "timeless", "unknown"}
CLAIM_INTENTS = {"none", "planned", "desired", "proposed"}
CLAIM_CERTAINTIES = {"certain", "uncertain"}
CLAIM_POLARITIES = {"positive", "negative"}
CURRENT_STATE_TEMPORAL_STATUSES = {"ongoing", "timeless"}


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    model: str
    api_key: str
    api_base: str
    cache_path: Path
    use_cache: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one offline LoCoMo sample-level STS graph.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument(
        "--graph-schema",
        choices=GRAPH_SCHEMAS,
        default="v2",
        help="v2 is the active lightweight ordered state fold; v1 is legacy.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Defaults to a schema-specific directory.",
    )
    parser.add_argument("--claim-mode", choices=("llm", "none"), default="llm")
    parser.add_argument("--resolver-mode", choices=("llm", "none"), default="llm")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None, help="Optional model override, e.g. deepseek-v4-flash.")
    parser.add_argument(
        "--cache",
        default=None,
        help="Defaults to a schema-specific cache so incompatible prompt schemas cannot share responses.",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--message-chunk-size", type=int, default=16)
    parser.add_argument("--claim-workers", type=int, default=4, help="Parallel LLM workers for claim extraction chunks.")
    parser.add_argument("--resolver-workers", type=int, default=4, help="Parallel LLM workers for relation/state buckets.")
    parser.add_argument(
        "--resolver-candidate-limit",
        type=int,
        default=24,
        help=(
            "Candidate cap for the v2 active-cluster fold or the v1 relation resolver."
        ),
    )
    parser.add_argument(
        "--max-claims-per-turn",
        type=int,
        default=None,
        help="Defaults to 2 Claims per turn.",
    )
    parser.add_argument("--event-limit", type=int, default=0, help="Debug limit only; 0 builds the full sample.")
    return parser.parse_args()


def default_output_dir(graph_schema: str) -> Path:
    if graph_schema == "v2":
        return EXTERNAL_GRAPH_DIR / "locomo_qa_sample_graph_v2_state_merge"
    return EXTERNAL_GRAPH_DIR / "locomo_qa_sample_graph_v1"


def default_cache_path(graph_schema: str) -> Path:
    if graph_schema == "v2":
        return EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_graph_builder.v2_state_merge.json"
    return EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_graph_builder.json"


def ensure_output_manifest_compatible(
    output_dir: Path,
    sample_id: str,
    expected_schema: str,
) -> None:
    sample_dir = output_dir / safe_part(sample_id)
    if not sample_dir.exists():
        return
    manifest_path = sample_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"refusing to replace existing graph directory without manifest: {sample_dir}")
    existing = json.loads(manifest_path.read_text())
    existing_sample_id = str(existing.get("sample_id") or "")
    if existing_sample_id != sample_id:
        raise ValueError(
            f"refusing sample-conflicting overwrite at {sample_dir}: "
            f"existing={existing_sample_id or 'unknown'} requested={sample_id}"
        )
    existing_schema = str(existing.get("schema_version") or "")
    if existing_schema != expected_schema:
        raise ValueError(
            f"refusing schema-conflicting overwrite at {sample_dir}: "
            f"existing={existing_schema or 'unknown'} requested={expected_schema}"
        )


def ensure_output_schema_compatible(output_dir: Path, sample_id: str, graph_schema: str) -> None:
    ensure_output_manifest_compatible(
        output_dir,
        sample_id,
        graph_schema_version(graph_schema),
    )


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def short_hash(value: object, length: int = 10) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:length]


def safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "unknown"


def cache_shard_root(base_cache_path: Path) -> Path:
    shard_dir = base_cache_path.with_suffix("")
    return shard_dir.parent / f"{shard_dir.name}_shards"


def shard_cache_path(base_cache_path: Path, stage: str, shard_name: str) -> Path:
    shard_dir = cache_shard_root(base_cache_path) / stage
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


def add_node(nodes: Dict[str, Dict[str, Any]], node: Dict[str, Any]) -> None:
    identifier = node_id(node)
    if not identifier:
        raise ValueError(f"node has no id: {node}")
    nodes.setdefault(identifier, node)


def add_edge(edges: List[Dict[str, Any]], edge_type: str, source: str, target: str, **payload: Any) -> None:
    edge = {"type": edge_type, "from": source, "to": target}
    edge.update({key: value for key, value in payload.items() if value is not None})
    edges.append(edge)


def time_id(role: str, value: str, anchor_value: str = "") -> str:
    fingerprint = value if not anchor_value else f"{value}|anchor={anchor_value}"
    return f"time::{safe_part(role)}::{safe_part(value)}::{short_hash(fingerprint)}"


def normalize_time_role(value: object) -> str:
    role = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "claim_time": "mentioned_at",
        "date": "occurred_at",
        "deadline": "deadline_at",
        "due_at": "deadline_at",
        "finish_at": "completed_at",
        "finished_at": "completed_at",
        "plan_for": "planned_for",
        "session_date_time": "occurred_at",
        "start_at": "started_at",
    }
    role = aliases.get(role, role)
    return role if role in TIME_ROLES else ""




def normalize_claim_time_role(role_value: object, time_value: object) -> str:
    role = normalize_time_role(role_value)
    normalized_time = normalize_time_value(time_value)
    if role == "planned_for" and PAST_TIME_EXPRESSION_RE.search(normalized_time):
        return "occurred_at"
    return role










def exact_occurrence_starts(text: str, span: str) -> List[int]:
    starts: List[int] = []
    search_start = 0
    while span:
        occurrence_start = text.find(span, search_start)
        if occurrence_start < 0:
            break
        starts.append(occurrence_start)
        search_start = occurrence_start + max(1, len(span))
    return starts


def exact_time_occurrence_starts(text: str, span: str) -> List[int]:
    """Return case-sensitive, complete time-expression occurrences."""
    starts: List[int] = []
    for occurrence_start in exact_occurrence_starts(text, span):
        occurrence_end = occurrence_start + len(span)
        previous = text[occurrence_start - 1] if occurrence_start else ""
        following = text[occurrence_end] if occurrence_end < len(text) else ""
        if previous.isalnum() or following.isalnum():
            continue
        if span[0].isdigit() and previous in "-/:":
            continue
        if span[-1].isdigit() and following in "-/:":
            continue
        starts.append(occurrence_start)
    return starts




















def graph_schema_version(graph_schema: str) -> str:
    return GRAPH_SCHEMA_V2 if graph_schema == "v2" else GRAPH_SCHEMA_V1


def uses_role_aware_time(graph_schema: str) -> bool:
    return graph_schema == "v2"


def add_time_node(
    nodes: Dict[str, Dict[str, Any]],
    role: str,
    value: str,
    sample_id: str,
    **payload: Any,
) -> str:
    anchor_value = str(payload.get("anchor_value") or "")
    identifier = time_id(role, value, anchor_value)
    node = {
        "node_type": "Time",
        "time_id": identifier,
        "sample_id": sample_id,
        "time_role": role,
        "value": value,
    }
    node.update({key: item for key, item in payload.items() if item is not None and item != ""})
    add_node(
        nodes,
        node,
    )
    return identifier


def scope_id(sample_id: str, scope_type: str, value: str) -> str:
    return f"scope::{safe_part(scope_type)}::{safe_part(sample_id)}::{safe_part(value[:80])}::{short_hash(value.lower())}"


def scope_node(sample_id: str, scope_type: str, value: str, label: Optional[str] = None) -> Dict[str, Any]:
    return {
        "node_type": "Entity/Scope",
        "scope_id": scope_id(sample_id, scope_type, value),
        "sample_id": sample_id,
        "scope_type": scope_type,
        "label": label or value,
        "value": value,
        "role": "scope",
    }


def event_text(turn: DialogTurn) -> str:
    parts = [f"{turn.speaker}: {turn.text}"]
    if turn.image_caption:
        parts.append(f"Image caption: {turn.image_caption}")
    if turn.image_query:
        parts.append(f"Image search query: {turn.image_query}")
    return "\n".join(parts)


def turn_prompt_block(
    turns: Sequence[DialogTurn],
    *,
    target_dialog_ids: Optional[Sequence[str]] = None,
) -> str:
    target_ids = None if target_dialog_ids is None else {str(dialog_id) for dialog_id in target_dialog_ids}
    blocks: List[str] = []
    for turn in turns:
        role_attribute = ""
        if target_ids is not None:
            role = "target" if turn.dia_id in target_ids else "context_only"
            role_attribute = f' role="{role}"'
        blocks.append(
            "\n".join(
                [
                    f'<dialog id="{turn.dia_id}" session_id="{turn.session_id}" date="{turn.session_date_time}" speaker="{turn.speaker}"{role_attribute}>',
                    turn.text,
                    f"Image caption: {turn.image_caption}" if turn.image_caption else "",
                    f"Image search query: {turn.image_query}" if turn.image_query else "",
                    "</dialog>",
                ]
            ).replace("\n\n", "\n")
        )
    return "\n\n".join(blocks)


def chunked(items: Sequence[DialogTurn], size: int) -> Iterable[Sequence[DialogTurn]]:
    for start in range(0, len(items), max(1, size)):
        yield items[start : start + max(1, size)]


def claim_system_prompt(graph_schema: str) -> str:
    prompt = (
        "You extract graph-ready memory claims from LoCoMo personal conversations. "
        "Use only the provided dialog turns, session dates, speakers, and text metadata. "
        "Do not use QA answers, evidence labels, or outside benchmark metadata. "
        "Resolve first-person pronouns to the speaker name when the subject is clear. "
        "Keep claims faithful, atomic, and useful for later single-hop, multi-hop, temporal, and open-domain QA. "
    )
    if uses_role_aware_time(graph_schema):
        prompt += (
            "When a claim contains an explicit or relative time expression, preserve that expression and classify its "
            "semantic time role. Copy time_value as an exact case-sensitive contiguous span from evidence_span. Do not "
            "invent a time or infer one from QA fields. "
        )
    return prompt + "Return strict JSON only."


def claim_time_roles(graph_schema: str) -> Tuple[str, ...]:
    return TIME_ROLES


def time_role_prompt(graph_schema: str) -> str:
    return (
        "For time_role use exactly one of: "
        + ", ".join(claim_time_roles(graph_schema))
        + ". Use occurred_at for an event that happened then; planned_for for an intended future event; "
        "deadline_at for a due date; valid_from for a state beginning then; started_at/completed_at/finalized_at "
        "for lifecycle boundaries; updated_at for an explicit update. Use mentioned_at only when the expression "
        "describes when something was mentioned rather than when it happened. If no time expression supports the "
        "claim, return empty strings for both time_role and time_value. Keep every expression verbatim, including case "
        "and punctuation."
    )


def claim_user_prompt(
    sample_id: str,
    turns: Sequence[DialogTurn],
    max_claims_per_turn: int,
    graph_schema: str,
    *,
    target_dialog_ids: Optional[Sequence[str]] = None,
) -> str:
    claim_limit_instruction = f"Max claims per dialog turn: {max_claims_per_turn}"
    temporal_instructions = f"{time_role_prompt(graph_schema)}\n\n" if uses_role_aware_time(graph_schema) else ""
    time_role_field = (
        f'"time_role": "{"|".join(claim_time_roles(graph_schema))}|empty", '
        if uses_role_aware_time(graph_schema)
        else ""
    )
    target_instruction = ""
    if target_dialog_ids is not None:
        requested_target_ids = {str(dialog_id) for dialog_id in target_dialog_ids}
        ordered_target_ids = [turn.dia_id for turn in turns if turn.dia_id in requested_target_ids]
        context_only_ids = [turn.dia_id for turn in turns if turn.dia_id not in requested_target_ids]
        target_instruction = (
            f"Target dialog IDs: {json.dumps(ordered_target_ids, ensure_ascii=False)}\n"
            f"Context-only dialog IDs: {json.dumps(context_only_ids, ensure_ascii=False)}\n"
            "Extract Claims only for Target dialog IDs. Context-only dialogs may be used only to resolve references "
            "and chronology. Do not emit or repair a Claim for a context-only dialog; every returned dialog_id must "
            "be one of the Target dialog IDs.\n\n"
        )
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Sample ID: {sample_id}\n"
        f"{claim_limit_instruction}\n\n"
        f"{target_instruction}"
        "Extract compact memory claims from these dialog turns. Skip greetings, filler, and unsupported inferences. "
        "For open-domain clues, store the conversation clue itself, not the outside-knowledge answer. "
        "Use facet_key from this set when possible: "
        f"{', '.join(sorted(FACET_KEYS))}.\n\n"
        f"{temporal_instructions}"
        f"{turn_prompt_block(turns, target_dialog_ids=target_dialog_ids)}\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"claims\": ["
        "{"
        "\"dialog_id\": \"D1:1\", "
        "\"subject\": \"person, place, activity, object, or relation\", "
        f'"facet_key": "{"|".join(sorted(FACET_KEYS))}", '
        "\"value\": \"faithful short fact\", "
        f"{time_role_field}"
        "\"time_value\": \"explicit or relative time expression, or empty string\", "
        "\"scope_labels\": [\"optional topic labels such as pottery, camping, LGBTQ support group\"], "
        "\"confidence\": 0.0"
        "}"
        "]"
        "}"
    )


def normalize_label(value: object, fallback: str = "") -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = text.strip(" \t\r\n'\"`.,:;!?()[]{}")
    return text[:180] or fallback


def normalize_time_value(value: object) -> str:
    exact_value = str(value or "").strip()[:180]
    sentinel_key = normalize_label(exact_value).casefold()
    return "" if sentinel_key in EMPTY_TIME_VALUES else exact_value


def normalize_facet(value: object) -> str:
    facet = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return facet if facet in FACET_KEYS else "other"


def v2_claim_is_persistent_state(claim: Mapping[str, Any]) -> bool:
    """Keep v2 StateFacets high precision without adding another LLM-owned field."""
    facet_key = normalize_facet(claim.get("facet_key"))
    time_role = normalize_claim_time_role(claim.get("time_role"), claim.get("time_value"))
    if time_role in V2_NON_STATE_TIME_ROLES:
        return False
    claim_value = str(claim.get("value") or "")
    if V2_PAST_ONLY_STATE_RE.search(claim_value) and not V2_CURRENT_STATE_CUE_RE.search(claim_value):
        return False
    if facet_key in V2_PERSISTENT_STATE_FACETS:
        return True
    return facet_key == "activity" and time_role in V2_ACTIVITY_STATE_BOUNDARY_ROLES


def normalize_v2_state_component(value: object, fallback: str = "") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    return normalized[:100] or fallback


def assign_v2_subject_keys(claims: Sequence[Dict[str, Any]]) -> None:
    """Assign only high-precision, sample-local Subject aliases; ambiguous names stay split."""

    raw_labels: Dict[str, List[str]] = {}
    base_keys: Dict[str, str] = {}
    simple_name_keys: set[str] = set()
    for claim in claims:
        raw_subject = normalize_label(claim.get("subject"), fallback=normalize_label(claim.get("speaker")))
        if raw_subject.casefold() in {"i", "me", "my", "myself"}:
            raw_subject = normalize_label(claim.get("speaker"), fallback=raw_subject)
        possessive_match = re.fullmatch(r"([A-Za-z][A-Za-z'-]*)['’]s", raw_subject)
        if possessive_match:
            raw_subject = possessive_match.group(1)
        key = normalize_v2_state_component(raw_subject)
        base_keys[str(claim.get("claim_id") or id(claim))] = key
        raw_labels.setdefault(key, []).append(raw_subject)
        if (
            not re.search(r"['’]s\b", raw_subject, flags=re.IGNORECASE)
            and re.fullmatch(r"[A-Za-z][A-Za-z'-]*(?: [A-Za-z][A-Za-z'-]*){0,3}", raw_subject)
        ):
            simple_name_keys.add(key)

    alias_targets: Dict[str, str] = {}
    for short_key in simple_name_keys:
        if "_" in short_key:
            continue
        matches = sorted(
            full_key
            for full_key in simple_name_keys
            if full_key != short_key and full_key.split("_", 1)[0] == short_key
        )
        if len(matches) == 1:
            alias_targets[short_key] = matches[0]

    canonical_labels: Dict[str, str] = {}
    for key, labels in raw_labels.items():
        canonical_key = alias_targets.get(key, key)
        candidates = [*raw_labels.get(canonical_key, []), *labels]
        canonical_labels[canonical_key] = max(candidates, key=lambda label: (len(label), label.casefold()))

    for claim in claims:
        claim_identifier = str(claim.get("claim_id") or id(claim))
        base_key = base_keys[claim_identifier]
        subject_key = alias_targets.get(base_key, base_key)
        claim["subject_key"] = subject_key
        claim["canonical_subject"] = canonical_labels.get(subject_key, normalize_label(claim.get("subject")))


def v2_state_domain(claim: Mapping[str, Any]) -> str:
    raw_domain = normalize_facet(claim.get("facet_key"))
    if raw_domain == "place" and V2_RESIDENCE_STATE_RE.search(str(claim.get("value") or "")):
        return "location"
    return V2_STATE_DOMAIN_ALIASES.get(raw_domain, raw_domain)


def v2_state_dimension_payload(
    *,
    state_domain: str,
    slot_type: str,
    state_target: str,
    dimension_source: str,
    reason: str,
) -> Dict[str, str]:
    normalized_target = normalize_v2_state_component(state_target)
    if slot_type == "single":
        normalized_target = V2_SINGLE_SLOT_DIMENSIONS.get(state_domain, normalized_target or "primary")
    if slot_type not in {"single", "object_scoped"}:
        raise ValueError(f"invalid v2 slot_type: {slot_type!r}")
    if not state_domain or not normalized_target:
        raise ValueError("v2 state dimension requires non-empty domain and target")
    return {
        "state_domain": state_domain,
        "slot_type": slot_type,
        "state_target": normalized_target,
        "state_dimension": f"{state_domain}:{normalized_target}",
        "dimension_source": dimension_source,
        "dimension_reason": normalize_label(reason),
    }


def v2_state_dimension_seed(claim: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """Resolve code-owned single slots and grounded one-topic dimensions without an LLM call."""

    state_domain = v2_state_domain(claim)
    if state_domain in V2_SINGLE_SLOT_DIMENSIONS:
        return v2_state_dimension_payload(
            state_domain=state_domain,
            slot_type="single",
            state_target=V2_SINGLE_SLOT_DIMENSIONS[state_domain],
            dimension_source="deterministic_single_slot",
            reason="schema-owned single state slot",
        )
    scope_labels = normalize_scope_labels(claim.get("scope_labels"))
    normalized_targets = list(
        dict.fromkeys(normalize_v2_state_component(label) for label in scope_labels if normalize_v2_state_component(label))
    )
    if state_domain in V2_OBJECT_SCOPED_STATE_DOMAINS and len(normalized_targets) == 1:
        return v2_state_dimension_payload(
            state_domain=state_domain,
            slot_type="object_scoped",
            state_target=normalized_targets[0],
            dimension_source="deterministic_single_scope",
            reason="one normalized topic scope identifies the tracked target",
        )
    return None


def v2_dimension_system_prompt() -> str:
    return (
        "You identify the stable target of one persistent memory Claim. Read only this Claim and its source metadata. "
        "Do not use QA fields, benchmark answers, or outside facts. Return slot_type=single only when the Claim tracks "
        "one replaceable slot; otherwise return object_scoped and a short canonical target. The target names what is "
        "being tracked, not its current value. Return strict JSON only."
    )


def v2_dimension_user_prompt(claim: Mapping[str, Any]) -> str:
    claim_payload = {
        "claim_id": claim.get("claim_id"),
        "dialog_id": claim.get("dialog_id"),
        "subject": claim.get("canonical_subject") or claim.get("subject"),
        "facet_key": claim.get("facet_key"),
        "value": claim.get("value"),
        "scope_labels": claim.get("scope_labels", []),
    }
    return (
        "Resolve exactly this one Claim:\n"
        f"{json.dumps(claim_payload, ensure_ascii=False, indent=2)}\n\n"
        "Return: {\"slot_type\": \"single|object_scoped\", \"state_target\": \"short target\", "
        "\"reason\": \"short evidence-grounded explanation\"}."
    )


def normalize_v2_dimension_resolution(
    raw: Mapping[str, Any],
    claim: Mapping[str, Any],
) -> Dict[str, str]:
    state_domain = v2_state_domain(claim)
    slot_type = str(raw.get("slot_type") or "").strip().casefold()
    state_target = normalize_v2_state_component(raw.get("state_target"))
    reason = normalize_label(raw.get("reason"))
    if not reason:
        raise ValueError("v2 state dimension resolver requires a non-empty reason")
    if state_domain in V2_SINGLE_SLOT_DIMENSIONS:
        if slot_type != "single":
            raise ValueError(f"v2 {state_domain} Claim requires slot_type=single")
        state_target = V2_SINGLE_SLOT_DIMENSIONS[state_domain]
    else:
        if slot_type != "object_scoped" or not state_target:
            raise ValueError(f"v2 {state_domain} Claim requires an object_scoped target")
    return v2_state_dimension_payload(
        state_domain=state_domain,
        slot_type=slot_type,
        state_target=state_target,
        dimension_source="llm_single_claim",
        reason=reason,
    )


def v2_state_target_is_generic(claim: Mapping[str, Any], state_target: object) -> bool:
    """Detect targets that merely repeat the owner and coarse state domain."""

    target_key = normalize_v2_state_component(state_target)
    state_domain = v2_state_domain(claim)
    facet_key = normalize_facet(claim.get("facet_key"))
    coarse_keys = {
        key
        for key in (
            state_domain,
            facet_key,
            *V2_GENERIC_STATE_TARGETS_BY_DOMAIN.get(state_domain, ()),
        )
        if key
    }
    if target_key in coarse_keys:
        return True
    owner_keys = {
        normalize_v2_state_component(claim.get(field))
        for field in ("subject_key", "canonical_subject", "subject")
    }
    owner_keys.discard("")
    owner_relative_targets = {target_key}
    for owner_key in owner_keys:
        for prefix in (f"{owner_key}_s_", f"{owner_key}_"):
            if target_key.startswith(prefix):
                owner_relative_targets.add(target_key[len(prefix) :])
    return bool(owner_relative_targets & coarse_keys)


def v2_claim_local_dimension(claim: Mapping[str, Any]) -> Dict[str, str]:
    """Abstain from cross-Claim merging when the tracked target is unresolved."""

    claim_fingerprint = str(claim.get("claim_id") or "") or json.dumps(
        {
            "dialog_id": claim.get("dialog_id"),
            "subject": claim.get("subject"),
            "facet_key": claim.get("facet_key"),
            "value": claim.get("value"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    value_key = normalize_v2_state_component(claim.get("value"), fallback="unresolved")[:56]
    state_target = f"claim_local_{value_key}_{short_hash(claim_fingerprint)[:8]}"
    return v2_state_dimension_payload(
        state_domain=v2_state_domain(claim),
        slot_type="object_scoped",
        state_target=state_target,
        dimension_source="deterministic_claim_local_abstention",
        reason="the resolved target repeated only the owner and coarse domain, so cross-Claim merging abstained",
    )


def resolve_v2_state_dimension(client: LLMClient, claim: Mapping[str, Any]) -> Dict[str, str]:
    seed = v2_state_dimension_seed(claim)
    if seed is not None:
        return seed
    resolved = complete_json_semantically_validated(
        client,
        v2_dimension_system_prompt(),
        v2_dimension_user_prompt(claim),
        lambda raw: normalize_v2_dimension_resolution(raw, claim),
        stage=f"v2 state dimension {claim.get('claim_id')}",
        repair_instruction="Return one object-scoped target for this Claim only.",
    )
    if v2_state_target_is_generic(claim, resolved["state_target"]):
        return v2_claim_local_dimension(claim)
    return resolved


def normalize_v2_merge_decision(
    raw: Mapping[str, Any],
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> Dict[str, Any]:
    decision = str(raw.get("decision") or "").strip().upper()
    winner = str(raw.get("winner") or "none").strip().lower()
    reason = normalize_label(raw.get("reason"))
    if decision not in STATE_MERGE_DECISIONS:
        raise ValueError(f"invalid v2 state merge decision: {decision!r}")
    if (
        decision == "DIFFERENT_TARGET"
        and str(existing.get("slot_type") or "") == "single"
        and str(incoming.get("slot_type") or "") == "single"
        and str(existing.get("state_dimension") or "") == str(incoming.get("state_dimension") or "")
    ):
        raise ValueError("DIFFERENT_TARGET is invalid inside one code-owned single state slot")
    if decision in {"SUPERSEDES", "CORRECTS"}:
        if winner not in {"existing", "incoming"}:
            raise ValueError(f"{decision} requires winner=existing|incoming")
    elif winner != "none":
        raise ValueError(f"{decision} requires winner=none")
    if not reason:
        raise ValueError("v2 state merge decision requires a non-empty reason")
    raw_evidence = raw.get("evidence_event_ids", [])
    if not isinstance(raw_evidence, list):
        raise ValueError("v2 state merge evidence_event_ids must be a list")
    endpoint_event_ids = {
        str(existing.get("source_event_id") or existing.get("dialog_id") or ""),
        str(incoming.get("source_event_id") or incoming.get("dialog_id") or ""),
    }
    evidence_event_ids = list(dict.fromkeys(str(item) for item in raw_evidence if str(item)))
    if not evidence_event_ids or any(item not in endpoint_event_ids for item in evidence_event_ids):
        raise ValueError("v2 state merge evidence must come from the two endpoint Claims")
    existing_dialog_id = str(existing.get("dialog_id") or "")
    incoming_dialog_id = str(incoming.get("dialog_id") or "")
    if (
        decision in {"SUPERSEDES", "CORRECTS"}
        and existing_dialog_id != incoming_dialog_id
        and dialog_sort_key(incoming_dialog_id) > dialog_sort_key(existing_dialog_id)
        and winner != "incoming"
    ):
        raise ValueError(f"v2 cross-dialog {decision} must select the later incoming Claim")
    return {
        "decision": decision,
        "winner": winner,
        "reason": reason,
        "evidence_event_ids": evidence_event_ids,
    }


def v2_merge_system_prompt() -> str:
    return (
        "You compare exactly two persistent memory Claims from one coarse state domain. Decide whether they are "
        "compatible support for one atomic target, different targets, a lifecycle replacement, an explicit correction, "
        "or an unresolved conflict. Increased detail, progress, or commitment is COMPATIBLE unless the old state is no "
        "longer true. DIFFERENT_TARGET is forbidden when both Claims use the same code-owned single slot. "
        "Use only endpoint evidence and return strict JSON."
    )


def v2_merge_user_prompt(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> str:
    def row(claim: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "claim_id": claim.get("claim_id"),
            "dialog_id": claim.get("dialog_id"),
            "subject": claim.get("canonical_subject") or claim.get("subject"),
            "state_domain": claim.get("state_domain"),
            "slot_type": claim.get("slot_type"),
            "state_dimension_hint": claim.get("state_dimension"),
            "value": claim.get("value"),
        }

    same_dialog = str(existing.get("dialog_id") or "") == str(incoming.get("dialog_id") or "")
    order_note = (
        "The Claims share one dialog; list order does not prove clause chronology."
        if same_dialog
        else "The incoming Claim is from a later dialog than the existing Claim."
    )
    return (
        f"{order_note}\nExisting Claim:\n{json.dumps(row(existing), ensure_ascii=False, indent=2)}\n\n"
        f"Incoming Claim:\n{json.dumps(row(incoming), ensure_ascii=False, indent=2)}\n\n"
        "Return {\"decision\": \"COMPATIBLE|DIFFERENT_TARGET|SUPERSEDES|CORRECTS|CONFLICTS_WITH\", "
        "\"winner\": \"existing|incoming|none\", \"reason\": \"short reason\", "
        "\"evidence_event_ids\": [\"endpoint dialog id\"]}. Use winner only for SUPERSEDES or CORRECTS."
    )


def resolve_v2_merge_decision(
    client: LLMClient,
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> Dict[str, Any]:
    return complete_json_semantically_validated(
        client,
        v2_merge_system_prompt(),
        v2_merge_user_prompt(existing, incoming),
        lambda raw: normalize_v2_merge_decision(raw, existing, incoming),
        stage=f"v2 state merge {existing.get('claim_id')}->{incoming.get('claim_id')}",
        repair_instruction="Return one of the five decisions; do not guess a lifecycle relation when targets differ.",
    )


def fold_v2_state_claims(
    claims: Sequence[Mapping[str, Any]],
    decide: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    *,
    candidate_limit: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    adapter = StateMergeAdapter(
        eligible=lambda _claim: True,
        owner_key=lambda claim: str(claim.get("subject_key") or ""),
        domain_key=lambda claim: str(claim.get("state_domain") or ""),
        dimension_key=lambda claim: str(claim.get("state_dimension") or ""),
        chronology_key=lambda claim: tuple(dialog_sort_key(str(claim.get("dialog_id") or ""))),
        lifecycle_winner_is_valid=lambda existing, incoming, winner: (
            dialog_sort_key(str(existing.get("dialog_id") or ""))
            == dialog_sort_key(str(incoming.get("dialog_id") or ""))
            or winner == "incoming"
        ),
    )
    clusters, relations = fold_state_claims_generic(
        claims,
        adapter,
        decide,
        candidate_limit=candidate_limit,
    )
    claims_by_id = {str(claim.get("claim_id") or ""): claim for claim in claims}
    enriched: List[Dict[str, Any]] = []
    for cluster in clusters:
        primary = claims_by_id[str(cluster["primary_claim_id"])]
        enriched.append(
            {
                "subject_key": cluster["owner_key"],
                "canonical_subject": str(primary.get("canonical_subject") or primary.get("subject") or ""),
                "state_domain": cluster["domain_key"],
                "state_target": str(primary.get("state_target") or ""),
                "state_dimension": cluster["dimension_key"],
                "primary_claim_id": cluster["primary_claim_id"],
                "support_claim_ids": cluster["support_claim_ids"],
                "status": cluster["status"],
            }
        )
    return enriched, relations


def resolve_v2_state_clusters(
    claims: Sequence[Dict[str, Any]],
    *,
    client: Optional[LLMClient],
    candidate_limit: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve LoCoMo state identities, then run the benchmark-agnostic fold."""

    assign_v2_subject_keys(claims)
    persistent_claims = [claim for claim in claims if v2_claim_is_persistent_state(claim)]
    for claim in persistent_claims:
        dimension = v2_state_dimension_seed(claim)
        if dimension is None:
            if client is None:
                raise ValueError(
                    "v2 state dimension is unresolved; use --resolver-mode llm for the focused one-Claim fallback"
                )
            dimension = resolve_v2_state_dimension(client, claim)
        claim.update(dimension)

    def decide(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Mapping[str, Any]:
        if client is None:
            raise ValueError(
                "v2 has multiple Claims for one state dimension; use --resolver-mode llm for pairwise folding"
            )
        return resolve_v2_merge_decision(client, existing, incoming)

    clusters, relations = fold_v2_state_claims(
        persistent_claims,
        decide,
        candidate_limit=candidate_limit,
    )
    return persistent_claims, clusters, relations


def materialize_v2_state_facets(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    sample_id: str,
    claims: Sequence[Mapping[str, Any]],
    clusters: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Materialize the deterministic output of the ordered state fold."""

    claims_by_id = {str(claim.get("claim_id") or ""): claim for claim in claims}
    facets: List[Dict[str, Any]] = []
    for cluster in clusters:
        primary_claim_id = str(cluster.get("primary_claim_id") or "")
        raw_support_claim_ids = cluster.get("support_claim_ids", [])
        support_claim_ids = (
            list(dict.fromkeys(str(claim_id) for claim_id in raw_support_claim_ids if str(claim_id)))
            if isinstance(raw_support_claim_ids, list)
            else []
        )
        if primary_claim_id not in support_claim_ids:
            raise ValueError(f"v2 StateFacet primary Claim is not declared as support: {primary_claim_id!r}")
        unknown_claim_ids = [claim_id for claim_id in support_claim_ids if claim_id not in claims_by_id]
        if unknown_claim_ids:
            raise ValueError(f"v2 StateFacet has unknown support Claims: {unknown_claim_ids}")
        primary = claims_by_id[primary_claim_id]
        subject_key = str(cluster.get("subject_key") or "")
        canonical_subject = str(cluster.get("canonical_subject") or primary.get("canonical_subject") or "")
        state_domain = str(cluster.get("state_domain") or "")
        state_target = str(cluster.get("state_target") or "")
        state_dimension = str(cluster.get("state_dimension") or "")
        status = str(cluster.get("status") or "")
        if not all((subject_key, canonical_subject, state_domain, state_target, state_dimension)):
            raise ValueError(f"v2 StateFacet is missing stable identity fields: {primary_claim_id!r}")
        if state_dimension != f"{state_domain}:{state_target}":
            raise ValueError(f"v2 StateFacet has inconsistent state_dimension: {state_dimension!r}")
        if status not in {"current", "historical", "ambiguous"}:
            raise ValueError(f"v2 StateFacet has invalid status: {status!r}")

        support_event_ids = list(
            dict.fromkeys(str(claims_by_id[claim_id].get("source_event_id") or "") for claim_id in support_claim_ids)
        )
        if any(not event_id for event_id in support_event_ids):
            raise ValueError("v2 StateFacet support Claim is missing source_event_id")
        source_event = nodes.get(str(primary.get("source_event_id") or ""), {})
        time_anchor = str(primary.get("time_anchor") or source_event.get("occurred_at") or "")
        time_value = str(primary.get("time_value") or "")
        time_role = str(primary.get("time_role") or "")
        current_after = time_value if time_value and time_role in CURRENT_AFTER_TIME_ROLES else time_anchor
        if not current_after:
            raise ValueError(f"v2 StateFacet primary Claim is missing a report time: {primary_claim_id!r}")

        subject_scope = scope_node(sample_id, "entity", subject_key, canonical_subject)
        add_node(nodes, subject_scope)
        scope_rows: List[Dict[str, Any]] = [subject_scope]
        topic_labels = list(
            dict.fromkeys(
                [
                    *(str(label) for claim_id in support_claim_ids for label in normalize_scope_labels(claims_by_id[claim_id].get("scope_labels"))),
                    *([] if state_target in {"primary", "residence"} else [state_target.replace("_", " ")]),
                ]
            )
        )
        for label in topic_labels:
            scope_rows.append(scope_node(sample_id, "topic", label, label))
        for scope in scope_rows:
            add_node(nodes, scope)
        scope_ids = list(dict.fromkeys(node_id(scope) for scope in scope_rows))

        state_identity = "|".join((subject_key, state_dimension, primary_claim_id))
        facet_id = f"state::{safe_part(sample_id)}::v2::{short_hash(state_identity, 16)}"
        facet = {
            "node_type": "StateFacet",
            "facet_id": facet_id,
            "sample_id": sample_id,
            "subject": canonical_subject,
            "canonical_subject": canonical_subject,
            "subject_key": subject_key,
            "facet_key": primary.get("facet_key"),
            "state_domain": state_domain,
            "slot_type": primary.get("slot_type"),
            "state_target": state_target,
            "state_dimension": state_dimension,
            "dimension_source": primary.get("dimension_source"),
            "dimension_reason": primary.get("dimension_reason"),
            "value": primary.get("value"),
            "fact_type": "state",
            "temporal_status": "ongoing",
            "intent": "none",
            "status": status,
            "primary_claim_id": primary_claim_id,
            "support_claim_ids": support_claim_ids,
            "support_event_ids": support_event_ids,
            "current_after": current_after,
            "reported_at": time_anchor,
            "time_role": time_role,
            "time_value": time_value,
            "time_anchor": time_anchor,
            "scope_ids": scope_ids,
            "graph_text": (
                f"{canonical_subject} {state_dimension} status={status}: {primary.get('value', '')}"
            ),
        }
        add_node(nodes, facet)
        facets.append(facet)
        for claim_id in support_claim_ids:
            add_edge(edges, "SUPPORTS", claim_id, facet_id, reason="v2 folded state support")
        support_time = add_time_node(
            nodes,
            "current_after",
            current_after,
            sample_id,
            anchor_value=time_anchor,
        )
        add_edge(edges, "CURRENT_AFTER", facet_id, support_time, reason="v2 folded state known after source report")
        for scope_identifier in scope_ids:
            add_edge(edges, "CURRENT_STATE_OF", facet_id, scope_identifier, reason="v2 stable state identity")
    return facets


def normalize_state_slot(value: object, fallback: str = "other") -> str:
    slot = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slot[:80] or fallback


def normalize_semantic_enum(value: object, allowed: set[str], fallback: str = "") -> str:
    normalized = re.sub(r"[^a-z]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized if normalized in allowed else fallback


def normalize_fact_type(value: object, fallback: str = "") -> str:
    return normalize_semantic_enum(value, FACT_TYPES, fallback)


def normalize_temporal_status(value: object, fallback: str = "") -> str:
    return normalize_semantic_enum(value, TEMPORAL_STATUSES, fallback)


def normalize_intent(value: object, fallback: str = "") -> str:
    return normalize_semantic_enum(value, CLAIM_INTENTS, fallback)


def normalize_certainty(value: object, fallback: str = "") -> str:
    return normalize_semantic_enum(value, CLAIM_CERTAINTIES, fallback)


def normalize_polarity(value: object, fallback: str = "") -> str:
    return normalize_semantic_enum(value, CLAIM_POLARITIES, fallback)


















def normalized_evidence_text(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()












def complete_json_semantically_validated(
    client: LLMClient,
    system_prompt: str,
    user_prompt: str,
    validator: Callable[[Mapping[str, Any]], Any],
    *,
    stage: str,
    repair_instruction: str = "",
) -> Any:
    """Retry parsed-but-invalid LLM output with a new cache key, then return only validated data."""
    semantic_retries = max(0, int(os.environ.get("LLM_SEMANTIC_RETRIES", "2")))
    last_error: Optional[ValueError] = None
    for attempt in range(semantic_retries + 1):
        attempt_prompt = user_prompt
        if attempt:
            error_text = normalize_label(last_error, fallback="semantic validation failed")[:240]
            attempt_prompt += (
                f"\n\nCorrection attempt {attempt}/{semantic_retries}. The prior JSON failed semantic validation: "
                f"{error_text}. Return a complete corrected JSON object; do not omit required assignments."
            )
            if repair_instruction:
                attempt_prompt += f" {repair_instruction}"
        raw = client.complete_json(system_prompt, attempt_prompt)
        try:
            return validator(raw)
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"{stage} failed semantic validation after {semantic_retries + 1} attempts: {last_error}")








def dedupe_extracted_claims(claims: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[Tuple[str, ...]] = set()
    deduped: List[Dict[str, Any]] = []
    for claim in claims:
        key = (
            str(claim.get("dialog_id") or ""),
            normalize_bucket_key(claim.get("canonical_subject") or claim.get("subject")),
            normalize_bucket_key(claim.get("state_object") or claim.get("subject")),
            normalize_state_slot(claim.get("state_slot"), fallback=normalize_facet(claim.get("facet_key"))),
            normalized_evidence_text(claim.get("value")),
            normalized_evidence_text(claim.get("answer_span")),
            str(claim.get("fact_type") or ""),
            str(claim.get("temporal_status") or ""),
            str(claim.get("intent") or ""),
            str(claim.get("certainty") or ""),
            str(claim.get("polarity") or ""),
            str(claim.get("time_role") or "").strip(),
            normalized_evidence_text(
                claim.get("normalized_time_value") or claim.get("time_value")
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(claim))
    return deduped


def normalize_scope_labels(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    labels: List[str] = []
    seen = set()
    for item in value:
        label = normalize_label(item)
        key = label.lower()
        if not label or key in seen:
            continue
        seen.add(key)
        labels.append(label)
        if len(labels) >= 4:
            break
    return labels








def extract_claims_for_chunk(
    client: LLMClient,
    sample_id: str,
    turns: Sequence[DialogTurn],
    max_claims_per_turn: int,
    graph_schema: str,
    rejection_diagnostics: Optional[List[Dict[str, Any]]] = None,
    *,
    target_dialog_ids: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    visible_dialog_ids = [turn.dia_id for turn in turns]
    visible_dialog_id_set = set(visible_dialog_ids)
    if len(visible_dialog_id_set) != len(visible_dialog_ids):
        raise ValueError("claim extraction requires unique visible dialog IDs")
    if target_dialog_ids is None:
        prompt_target_dialog_ids = None
        allowed_dialog_ids = visible_dialog_id_set
    else:
        requested_target_ids = [str(dialog_id) for dialog_id in target_dialog_ids]
        requested_target_id_set = set(requested_target_ids)
        if not requested_target_ids or len(requested_target_id_set) != len(requested_target_ids):
            raise ValueError("claim extraction requires unique non-empty target dialog IDs")
        unknown_target_ids = requested_target_id_set - visible_dialog_id_set
        if unknown_target_ids:
            raise ValueError(f"claim extraction target dialog IDs are not visible: {sorted(unknown_target_ids)}")
        prompt_target_dialog_ids = [
            dialog_id for dialog_id in visible_dialog_ids if dialog_id in requested_target_id_set
        ]
        allowed_dialog_ids = set(prompt_target_dialog_ids)
    raw = client.complete_json(
        claim_system_prompt(graph_schema),
        claim_user_prompt(
            sample_id,
            turns,
            max_claims_per_turn,
            graph_schema,
            target_dialog_ids=prompt_target_dialog_ids,
        ),
    )
    raw_items = raw.get("claims")
    raw_claims: List[Any] = raw_items if isinstance(raw_items, list) else []
    claims: List[Dict[str, Any]] = []
    claim_count_by_dialog: Counter[str] = Counter()
    rejection_counts: Counter[str] = Counter()
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            rejection_counts["not_object"] += 1
            continue
        dialog_id = normalize_label(raw_claim.get("dialog_id"))
        if dialog_id not in allowed_dialog_ids:
            rejection_counts["unknown_dialog_id"] += 1
            continue
        if max_claims_per_turn > 0 and claim_count_by_dialog[dialog_id] >= max_claims_per_turn:
            rejection_counts["claim_limit"] += 1
            continue
        subject = normalize_label(raw_claim.get("subject"))
        value = normalize_label(raw_claim.get("value"))
        if not subject or not value:
            rejection_counts["missing_subject_or_value"] += 1
            continue
        claim_count_by_dialog[dialog_id] += 1
        claim = {
            "dialog_id": dialog_id,
            "subject": subject,
            "facet_key": normalize_facet(raw_claim.get("facet_key")),
            "value": value,
            "time_value": normalize_time_value(raw_claim.get("time_value")),
            "scope_labels": normalize_scope_labels(raw_claim.get("scope_labels")),
            "confidence": raw_claim.get("confidence"),
            "extraction_method": "llm_offline_claim_extraction",
        }
        if uses_role_aware_time(graph_schema):
            claim["time_role"] = normalize_claim_time_role(raw_claim.get("time_role"), claim["time_value"])
            if claim["time_value"] and not claim["time_role"]:
                claim["time_role"] = "occurred_at"
            if claim["time_role"] and not claim["time_value"]:
                claim["time_role"] = ""
        claims.append(claim)
    if rejection_diagnostics is not None and rejection_counts:
        rejection_diagnostics.append(
            {
                "dialog_ids": sorted(allowed_dialog_ids, key=dialog_sort_key),
                "raw_claim_count": len(raw_claims),
                "accepted_claim_count": len(claims),
                "rejection_counts": dict(sorted(rejection_counts.items())),
            }
        )
    return dedupe_extracted_claims(claims)


def extract_llm_claims(
    *,
    client: LLMClient,
    runtime: Optional[LLMRuntimeConfig],
    sample_id: str,
    turns: Sequence[DialogTurn],
    message_chunk_size: int,
    max_claims_per_turn: int,
    workers: int,
    graph_schema: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    turn_chunks = list(chunked(turns, message_chunk_size))

    def run_chunk(chunk_index: int, turn_chunk: Sequence[DialogTurn]) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]:
        chunk_client = client
        if workers > 1:
            if runtime is None:
                raise ValueError("parallel claim extraction requires LLMRuntimeConfig")
            first_id = turn_chunk[0].dia_id if turn_chunk else "empty"
            last_id = turn_chunk[-1].dia_id if turn_chunk else "empty"
            shard_name = f"{sample_id}_{chunk_index:05d}_{short_hash(first_id + last_id)}"
            chunk_client = make_sharded_client(runtime, "claim_extraction", shard_name)
        diagnostics: List[Dict[str, Any]] = []
        try:
            claims = extract_claims_for_chunk(
                chunk_client,
                sample_id,
                turn_chunk,
                max_claims_per_turn,
                graph_schema,
                diagnostics,
            )
            return chunk_index, claims, diagnostics
        except LLMRequestError as exc:
            if not exc.payload_split_recoverable or len(turn_chunk) <= 1:
                raise

        midpoint = len(turn_chunk) // 2
        left_targets = turn_chunk[:midpoint]
        right_targets = turn_chunk[midpoint:]
        split_specs = (
            ("1", left_targets, turn_chunk[: midpoint + 1]),
            ("2", right_targets, turn_chunk[midpoint - 1 :]),
        )
        print(
            f"[locomo-graph] payload response failed for claim chunk {chunk_index}; "
            f"one-level split {len(turn_chunk)} targets into {len(left_targets)}+{len(right_targets)} "
            "with one adjacent context-only turn per child",
            flush=True,
        )
        combined_claims: List[Dict[str, Any]] = []
        combined_diagnostics: List[Dict[str, Any]] = []
        for split_label, target_turns, visible_turns in split_specs:
            split_client = chunk_client
            if runtime is not None:
                target_ids = [turn.dia_id for turn in target_turns]
                visible_ids = [turn.dia_id for turn in visible_turns]
                split_fingerprint = "|".join((*target_ids, "context", *visible_ids))
                shard_name = (
                    f"{sample_id}_{chunk_index:05d}_split_{split_label}_"
                    f"{short_hash(split_fingerprint)}"
                )
                split_client = make_sharded_client(runtime, "claim_extraction", shard_name)
            split_diagnostics: List[Dict[str, Any]] = []
            split_claims = extract_claims_for_chunk(
                split_client,
                sample_id,
                visible_turns,
                max_claims_per_turn,
                graph_schema,
                split_diagnostics,
                target_dialog_ids=[turn.dia_id for turn in target_turns],
            )
            combined_claims.extend(split_claims)
            combined_diagnostics.extend(split_diagnostics)
        return chunk_index, dedupe_extracted_claims(combined_claims), combined_diagnostics

    if workers <= 1:
        claims: List[Dict[str, Any]] = []
        diagnostics: List[Dict[str, Any]] = []
        for chunk_index, turn_chunk in enumerate(turn_chunks, start=1):
            first_id = turn_chunk[0].dia_id if turn_chunk else ""
            last_id = turn_chunk[-1].dia_id if turn_chunk else ""
            print(f"[locomo-graph] extracting claims chunk {chunk_index}/{len(turn_chunks)} {first_id}-{last_id}", flush=True)
            _chunk_index, chunk_claims, chunk_diagnostics = run_chunk(chunk_index, turn_chunk)
            claims.extend(chunk_claims)
            diagnostics.extend(chunk_diagnostics)
            print(f"[locomo-graph] chunk {chunk_index}/{len(turn_chunks)} accepted={len(chunk_claims)}", flush=True)
        return dedupe_extracted_claims(claims), diagnostics

    print(f"[locomo-graph] parallel claim extraction workers={workers} chunks={len(turn_chunks)}", flush=True)
    results: Dict[int, List[Dict[str, Any]]] = {}
    diagnostic_results: Dict[int, List[Dict[str, Any]]] = {}
    indexed_chunks = list(enumerate(turn_chunks, start=1))
    next_chunk_position = 0
    in_flight: Dict[Any, int] = {}
    fatal_error: Optional[BaseException] = None
    executor = ThreadPoolExecutor(max_workers=max(1, workers))

    def submit_next_chunk() -> bool:
        nonlocal next_chunk_position
        if next_chunk_position >= len(indexed_chunks):
            return False
        chunk_index, turn_chunk = indexed_chunks[next_chunk_position]
        next_chunk_position += 1
        in_flight[executor.submit(run_chunk, chunk_index, turn_chunk)] = chunk_index
        return True

    try:
        for _ in range(min(max(1, workers), len(indexed_chunks))):
            submit_next_chunk()
        while in_flight:
            completed, _pending = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            failed = sorted(
                (
                    (in_flight[future], future)
                    for future in completed
                    if future.exception() is not None
                ),
                key=lambda item: item[0],
            )
            if failed:
                fatal_error = failed[0][1].exception()
                for future in in_flight:
                    future.cancel()
                break
            for future in sorted(completed, key=lambda item: in_flight[item]):
                in_flight.pop(future)
                chunk_index, chunk_claims, chunk_diagnostics = future.result()
                results[chunk_index] = chunk_claims
                diagnostic_results[chunk_index] = chunk_diagnostics
                print(
                    f"[locomo-graph] chunk {chunk_index}/{len(turn_chunks)} accepted={len(chunk_claims)}",
                    flush=True,
                )
            for _ in range(len(completed)):
                if not submit_next_chunk():
                    break
    finally:
        executor.shutdown(wait=True, cancel_futures=fatal_error is not None)
    if fatal_error is not None:
        raise fatal_error
    claims = []
    diagnostics = []
    for chunk_index in sorted(results):
        claims.extend(results[chunk_index])
        diagnostics.extend(diagnostic_results.get(chunk_index, []))
    return dedupe_extracted_claims(claims), diagnostics


def materialize_base_event(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    sample_id: str,
    turn: DialogTurn,
    graph_schema: str,
) -> None:
    event_id = turn.dia_id
    add_node(
        nodes,
        {
            "node_type": "Episode/Event",
            "event_id": event_id,
            "sample_id": sample_id,
            "dialog_id": turn.dia_id,
            "session_id": turn.session_id,
            "session_index": turn.session_index,
            "occurred_at": turn.session_date_time,
            "speaker": turn.speaker,
            "text": turn.text,
            "image_caption": turn.image_caption,
            "image_query": turn.image_query,
            "graph_text": event_text(turn),
        },
    )
    sample_scope = scope_node(sample_id, "sample", sample_id, f"Sample({sample_id})")
    session_scope = scope_node(sample_id, "session", turn.session_id, f"Session({turn.session_id})")
    speaker_scope = scope_node(sample_id, "speaker", turn.speaker, f"Speaker({turn.speaker})")
    for scope in (sample_scope, session_scope, speaker_scope):
        add_node(nodes, scope)
        identifier = node_id(scope)
        add_edge(edges, "IN_SCOPE", event_id, identifier, reason=f"dialog turn in {scope['scope_type']} scope")
        add_edge(edges, "MENTIONS", event_id, identifier, reason=f"dialog turn mentions {scope['scope_type']}")
    occurred_role = "occurred_at" if uses_role_aware_time(graph_schema) else "session_date_time"
    occurred_time = add_time_node(
        nodes,
        occurred_role,
        turn.session_date_time,
        sample_id,
        source_field="session_date_time" if uses_role_aware_time(graph_schema) else None,
    )
    add_edge(edges, "OCCURRED_AT", event_id, occurred_time, reason="LoCoMo session date_time")


def materialize_claim(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    sample_id: str,
    turn_by_id: Mapping[str, DialogTurn],
    raw_claim: Mapping[str, Any],
    claim_index: int,
    graph_schema: str,
) -> Optional[Dict[str, Any]]:
    dialog_id = str(raw_claim.get("dialog_id") or "")
    turn = turn_by_id.get(dialog_id)
    if turn is None:
        return None
    subject = normalize_label(raw_claim.get("subject"), fallback=turn.speaker)
    facet_key = normalize_facet(raw_claim.get("facet_key"))
    value = normalize_label(raw_claim.get("value"))
    if not subject or not value:
        return None
    fingerprint = json.dumps(
        {"dialog_id": dialog_id, "subject": subject, "facet_key": facet_key, "value": value},
        ensure_ascii=False,
        sort_keys=True,
    )
    claim_id = f"claim::{safe_part(sample_id)}::{safe_part(dialog_id)}::{claim_index:05d}::{short_hash(fingerprint)}"
    claim_node = {
        "node_type": "Claim",
        "claim_id": claim_id,
        "sample_id": sample_id,
        "source_event_id": dialog_id,
        "dialog_id": dialog_id,
        "session_id": turn.session_id,
        "speaker": turn.speaker,
        "subject": subject,
        "facet_key": facet_key,
        "value": value,
        "time_value": normalize_time_value(raw_claim.get("time_value")),
        "scope_labels": normalize_scope_labels(raw_claim.get("scope_labels")),
        "confidence": raw_claim.get("confidence"),
        "extraction_method": raw_claim.get("extraction_method", "llm_offline_claim_extraction"),
        "graph_text": f"{subject} {facet_key}: {value}",
    }
    if uses_role_aware_time(graph_schema):
        claim_node["time_role"] = normalize_claim_time_role(raw_claim.get("time_role"), claim_node["time_value"])
        claim_node["time_anchor"] = turn.session_date_time
    add_node(nodes, claim_node)
    add_edge(edges, "ASSERTS", dialog_id, claim_id, reason="dialog turn asserts extracted memory claim")

    subject_scope = scope_node(sample_id, "entity", subject, subject)
    add_node(nodes, subject_scope)
    subject_scope_id = node_id(subject_scope)
    add_edge(edges, "MENTIONS", dialog_id, subject_scope_id, reason="claim subject")
    add_edge(edges, "IN_SCOPE", dialog_id, subject_scope_id, reason="claim subject")

    topic_scope_ids: List[str] = []
    for label in claim_node["scope_labels"]:
        topic_scope = scope_node(sample_id, "topic", str(label), str(label))
        add_node(nodes, topic_scope)
        topic_scope_id = node_id(topic_scope)
        topic_scope_ids.append(topic_scope_id)
        add_edge(edges, "MENTIONS", dialog_id, topic_scope_id, reason="claim topic label")
        add_edge(edges, "IN_SCOPE", dialog_id, topic_scope_id, reason="claim topic label")

    materializes_state_facet = graph_schema == "v1"
    time_value = str(claim_node.get("time_value") or "").strip()
    time_role = str(claim_node.get("time_role") or "").strip()
    if uses_role_aware_time(graph_schema):
        if time_value:
            time_role = time_role or "occurred_at"
            claim_node["time_role"] = time_role
            claim_time = add_time_node(
                nodes,
                time_role,
                time_value,
                sample_id,
                anchor_value=turn.session_date_time,
                value_kind="relative_or_explicit_expression",
            )
            add_edge(
                edges,
                "HAS_TIME",
                claim_id,
                claim_time,
                reason="claim extracted role-aware time expression",
                time_role=time_role,
                source_event_id=dialog_id,
            )
        if materializes_state_facet:
            current_after_value = time_value if time_value and time_role in CURRENT_AFTER_TIME_ROLES else turn.session_date_time
            support_time = add_time_node(
                nodes,
                "current_after",
                current_after_value,
                sample_id,
                anchor_value=turn.session_date_time,
            )
    else:
        support_time = add_time_node(
            nodes,
            "claim_time" if time_value else "session_date_time",
            time_value or turn.session_date_time,
            sample_id,
        )
        if time_value:
            add_edge(edges, "HAS_TIME", claim_id, support_time, reason="claim extracted time expression")
        current_after_value = time_value or turn.session_date_time

    if not materializes_state_facet:
        return claim_node

    facet_id = (
        f"state::{safe_part(sample_id)}::{safe_part(subject[:60])}::"
        f"{safe_part(facet_key)}::{claim_index:05d}::{short_hash(fingerprint)}"
    )
    state_node = {
        "node_type": "StateFacet",
        "facet_id": facet_id,
        "sample_id": sample_id,
        "subject": subject,
        "facet_key": facet_key,
        "value": value,
        "support_claim_ids": [claim_id],
        "support_event_ids": [dialog_id],
        "current_after": current_after_value,
        "scope_ids": [subject_scope_id] + topic_scope_ids,
        "graph_text": f"{subject} {facet_key}: {value}",
    }
    if uses_role_aware_time(graph_schema):
        state_node.update(
            {
                "time_role": time_role,
                "time_value": time_value,
                "time_anchor": turn.session_date_time,
            }
        )
    add_node(nodes, state_node)
    add_edge(edges, "SUPPORTS", claim_id, facet_id, reason="claim supports state facet")
    add_edge(
        edges,
        "CURRENT_AFTER",
        facet_id,
        support_time,
        reason="state facet support time",
        source_time_role=(time_role or "occurred_at") if uses_role_aware_time(graph_schema) else None,
    )
    add_edge(edges, "CURRENT_STATE_OF", facet_id, subject_scope_id, reason="state facet subject")
    for topic_scope_id in topic_scope_ids:
        add_edge(edges, "CURRENT_STATE_OF", facet_id, topic_scope_id, reason="state facet topic")
    return claim_node


def relation_system_prompt() -> str:
    return (
        "You resolve relations among graph Claims extracted from one LoCoMo personal conversation. "
        "Use only the provided claims and their source dialog IDs/dates. "
        "Add a relation only when two claims about the same subject and facet are genuinely incompatible, "
        "or when a later claim explicitly updates, replaces, or corrects an earlier claim. "
        "Do not infer benchmark answers and do not use QA evidence. Return strict JSON only."
    )


def relation_user_prompt(
    sample_id: str,
    bucket_index: int,
    claims: Sequence[Mapping[str, Any]],
    graph_schema: str,
) -> str:
    claim_rows = []
    for claim in claims:
        row = {
            "claim_id": claim.get("claim_id"),
            "dialog_id": claim.get("dialog_id"),
            "session_id": claim.get("session_id"),
            "speaker": claim.get("speaker"),
            "subject": claim.get("subject"),
            "facet_key": claim.get("facet_key"),
            "value": claim.get("value"),
            "time_value": claim.get("time_value"),
        }
        if uses_role_aware_time(graph_schema):
            row["time_role"] = claim.get("time_role")
            row["time_anchor"] = claim.get("time_anchor")
        claim_rows.append(row)
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Sample ID: {sample_id}\n"
        f"Resolver bucket: {bucket_index}\n\n"
        "Claims are listed in source-dialog order. Claims from the same dialog have no guaranteed clause order; "
        "use their content rather than list position to determine direction. Decide whether one claim corrects, supersedes, "
        "or conflicts with an earlier claim.\n\n"
        "Relation definitions:\n"
        "- CORRECTS: a later claim explicitly says an earlier claim was wrong or fixes it.\n"
        "- SUPERSEDES: a later claim replaces an earlier state, plan, preference, location, relationship, or status.\n"
        "- CONFLICTS_WITH: two claims cannot both be true, but the dialog does not clearly establish replacement/correction.\n"
        "- none: claims are compatible, repeated, about different aspects, or too weakly related.\n\n"
        "Direction policy: for CORRECTS and SUPERSEDES, from_claim_id must be the later/correcting claim and "
        "to_claim_id the earlier/old claim. For CONFLICTS_WITH, prefer later claim -> earlier claim when order is clear.\n\n"
        "Claims:\n"
        f"{json.dumps(claim_rows, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"relations\": ["
        "{"
        "\"type\": \"CORRECTS|SUPERSEDES|CONFLICTS_WITH\", "
        "\"from_claim_id\": \"claim id\", "
        "\"to_claim_id\": \"claim id\", "
        "\"reason\": \"short evidence-grounded reason\", "
        "\"evidence_dialog_ids\": [\"D1:1\"]"
        "}"
        "]"
        "}"
    )


def normalize_bucket_key(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(text.split())


def relation_buckets(
    claims: Sequence[Mapping[str, Any]],
    candidate_limit: int,
    graph_schema: str = "v1",
) -> List[List[Mapping[str, Any]]]:
    if graph_schema == "v2":
        raise ValueError("v2 state relations are produced only by fold_v2_state_claims")
    grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for claim in claims:
        subject_key = normalize_bucket_key(claim.get("subject"))
        facet_key = normalize_facet(claim.get("facet_key"))
        if not subject_key:
            continue
        grouped.setdefault((subject_key, facet_key), []).append(claim)

    buckets: List[List[Mapping[str, Any]]] = []
    limit = max(2, candidate_limit)
    overlap = min(4, max(0, limit // 4))
    step = max(1, limit - overlap)
    for group_claims in grouped.values():
        ordered = sorted(group_claims, key=lambda item: dialog_sort_key(str(item.get("dialog_id") or "")))
        if len(ordered) < 2:
            continue
        if len(ordered) <= limit:
            buckets.append(ordered)
            continue
        for start in range(0, len(ordered), step):
            window = ordered[start : start + limit]
            if len(window) >= 2:
                buckets.append(window)
            if start + limit >= len(ordered):
                break
    return buckets




def normalize_relations(
    raw: Mapping[str, Any],
    claims: Sequence[Mapping[str, Any]],
    *,
    strict_evidence: bool = False,
    graph_schema: str = "v1",
) -> List[Dict[str, Any]]:
    claims_by_id = {str(claim.get("claim_id") or ""): claim for claim in claims}
    claim_ids = set(claims_by_id)
    source_event_ids = {
        str(claim.get("source_event_id") or claim.get("dialog_id") or "")
        for claim in claims
        if claim.get("source_event_id") or claim.get("dialog_id")
    }
    if strict_evidence and "relations" not in raw:
        raise ValueError("strict relation resolver must return relations as a list")
    relations = raw.get("relations", [])
    if not isinstance(relations, list):
        if strict_evidence:
            raise ValueError("strict relation resolver must return relations as a list")
        return []
    accepted: List[Dict[str, Any]] = []
    seen = set()
    relation_type_by_pair: Dict[Tuple[str, str], str] = {}
    for relation in relations:
        if not isinstance(relation, dict):
            if strict_evidence:
                raise ValueError("strict relation resolver returned a non-object relation")
            continue
        relation_type = str(relation.get("type") or "").strip().upper()
        if relation_type not in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}:
            if strict_evidence:
                raise ValueError(f"strict relation resolver returned invalid relation type: {relation_type!r}")
            continue
        source = str(relation.get("from_claim_id") or relation.get("from") or "").strip()
        target = str(relation.get("to_claim_id") or relation.get("to") or "").strip()
        if not source or not target or source == target:
            if strict_evidence:
                raise ValueError(f"strict relation resolver returned invalid endpoints: {source!r}->{target!r}")
            continue
        if source not in claim_ids or target not in claim_ids:
            if strict_evidence:
                raise ValueError(f"strict relation resolver returned unknown endpoints: {source!r}->{target!r}")
            continue
        if strict_evidence and relation_type in {"CORRECTS", "SUPERSEDES"}:
            source_dialog_id = str(claims_by_id[source].get("dialog_id") or "")
            target_dialog_id = str(claims_by_id[target].get("dialog_id") or "")
            source_order = dialog_sort_key(source_dialog_id)
            target_order = dialog_sort_key(target_dialog_id)
            direction_is_valid = source_order > target_order
            if source_dialog_id == target_dialog_id:
                direction_is_valid = True
            if not direction_is_valid:
                raise ValueError(
                    f"strict relation resolver reversed {relation_type} direction: {source_dialog_id}->{target_dialog_id}"
                )
        reason = normalize_label(relation.get("reason"))
        if strict_evidence and not reason:
            raise ValueError("strict relation resolver must return a non-empty evidence-grounded reason")
        evidence_dialog_ids = []
        raw_evidence = relation.get("evidence_dialog_ids", [])
        if isinstance(raw_evidence, list):
            raw_evidence_ids = [str(item) for item in raw_evidence]
            endpoint_event_ids = {
                str(claims_by_id[claim_id].get("source_event_id") or claims_by_id[claim_id].get("dialog_id") or "")
                for claim_id in (source, target)
            }
            invalid_evidence_ids = [item for item in raw_evidence_ids if item not in source_event_ids]
            if strict_evidence and invalid_evidence_ids:
                raise ValueError(f"strict relation resolver returned evidence outside input Claims: {invalid_evidence_ids}")
            unrelated_evidence_ids = [item for item in raw_evidence_ids if item not in endpoint_event_ids]
            if strict_evidence and unrelated_evidence_ids:
                raise ValueError(f"strict relation resolver returned evidence outside relation endpoints: {unrelated_evidence_ids}")
            evidence_dialog_ids = [item for item in raw_evidence_ids if item in source_event_ids]
        elif strict_evidence:
            raise ValueError("strict relation resolver must return evidence_dialog_ids as a list")
        if strict_evidence and not evidence_dialog_ids:
            raise ValueError("strict relation resolver must return at least one endpoint evidence_dialog_id")
        if strict_evidence:
            unordered_pair = tuple(sorted((source, target)))
            prior_relation_type = relation_type_by_pair.setdefault(unordered_pair, relation_type)
            if prior_relation_type != relation_type:
                raise ValueError(
                    "strict relation resolver returned mutually exclusive relation types for "
                    f"{unordered_pair[0]!r}<->{unordered_pair[1]!r}: "
                    f"{prior_relation_type!r} and {relation_type!r}"
                )
        key = (relation_type, source, target)
        if relation_type == "CONFLICTS_WITH":
            key = (relation_type, *sorted((source, target)))
        if key in seen:
            continue
        seen.add(key)
        accepted.append(
            {
                "type": relation_type,
                "from": source,
                "to": target,
                "reason": reason,
                "evidence_event_ids": evidence_dialog_ids,
            }
        )
    return accepted


def resolve_relation_bucket(
    client: LLMClient,
    sample_id: str,
    bucket_index: int,
    claims: Sequence[Mapping[str, Any]],
    graph_schema: str,
) -> Tuple[int, List[Dict[str, Any]]]:
    if graph_schema == "v2":
        raise ValueError("v2 state relations are produced only by fold_v2_state_claims")
    system_prompt = relation_system_prompt()
    user_prompt = relation_user_prompt(sample_id, bucket_index, claims, graph_schema)
    raw = client.complete_json(system_prompt, user_prompt)
    return bucket_index, normalize_relations(raw, claims, graph_schema=graph_schema)


def resolve_claim_relations(
    *,
    client: LLMClient,
    runtime: Optional[LLMRuntimeConfig],
    sample_id: str,
    claims: Sequence[Mapping[str, Any]],
    candidate_limit: int,
    workers: int,
    graph_schema: str,
) -> List[Dict[str, Any]]:
    if graph_schema == "v2":
        raise ValueError("v2 state relations are produced only by fold_v2_state_claims")
    buckets = relation_buckets(claims, candidate_limit, graph_schema)
    if not buckets:
        return []

    def run_bucket(bucket_index: int, bucket_claims: Sequence[Mapping[str, Any]]) -> Tuple[int, List[Dict[str, Any]]]:
        bucket_client = client
        if workers > 1:
            if runtime is None:
                raise ValueError("parallel relation resolver requires LLMRuntimeConfig")
            claim_ids = "|".join(str(claim.get("claim_id") or "") for claim in bucket_claims)
            bucket_client = make_sharded_client(runtime, "relation_resolver", f"{sample_id}_{bucket_index:05d}_{short_hash(claim_ids)}")
        return resolve_relation_bucket(bucket_client, sample_id, bucket_index, bucket_claims, graph_schema)

    if workers <= 1:
        relations: List[Dict[str, Any]] = []
        for bucket_index, bucket_claims in enumerate(buckets, start=1):
            print(f"[locomo-graph] resolving relations bucket {bucket_index}/{len(buckets)} claims={len(bucket_claims)}", flush=True)
            _bucket_index, bucket_relations = run_bucket(bucket_index, bucket_claims)
            relations.extend(bucket_relations)
            print(f"[locomo-graph] bucket {bucket_index}/{len(buckets)} relations={len(bucket_relations)}", flush=True)
        return dedupe_relations(relations)

    print(f"[locomo-graph] parallel relation resolver workers={workers} buckets={len(buckets)}", flush=True)
    results: Dict[int, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(run_bucket, bucket_index, bucket_claims): bucket_index
            for bucket_index, bucket_claims in enumerate(buckets, start=1)
        }
        for future in as_completed(futures):
            bucket_index, bucket_relations = future.result()
            results[bucket_index] = bucket_relations
            print(f"[locomo-graph] bucket {bucket_index}/{len(buckets)} relations={len(bucket_relations)}", flush=True)
    relations = []
    for bucket_index in sorted(results):
        relations.extend(results[bucket_index])
    return dedupe_relations(relations)






































































































def dedupe_relations(relations: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique: List[Dict[str, Any]] = []
    for relation in relations:
        relation_type = str(relation.get("type") or "")
        source = str(relation.get("from") or "")
        target = str(relation.get("to") or "")
        key: Tuple[str, str, str]
        if relation_type == "CONFLICTS_WITH":
            ordered = sorted((source, target))
            key = (relation_type, ordered[0], ordered[1])
        else:
            key = (relation_type, source, target)
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(relation))
    return unique


def dedupe_edges(edges: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique: List[Dict[str, Any]] = []
    for edge in edges:
        key = (
            str(edge.get("type") or ""),
            str(edge.get("from") or ""),
            str(edge.get("to") or ""),
            json.dumps({k: v for k, v in edge.items() if k not in {"type", "from", "to"}}, ensure_ascii=False, sort_keys=True),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(edge))
    return unique


def validate_graph(
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    graph_schema: str = "v1",
) -> List[str]:
    warnings: List[str] = []
    node_types_by_id = {identifier: str(node.get("node_type") or "") for identifier, node in nodes.items()}
    support_edges = {
        (str(edge.get("from") or ""), str(edge.get("to") or ""))
        for edge in edges
        if str(edge.get("type") or "") == "SUPPORTS"
    }
    declared_support_edges: set[Tuple[str, str]] = set()
    if graph_schema == "v2":
        for state_id, node in nodes.items():
            if str(node.get("node_type") or "") != "StateFacet":
                continue
            raw_support_claim_ids = node.get("support_claim_ids")
            if isinstance(raw_support_claim_ids, list):
                declared_support_edges.update((str(claim_id), state_id) for claim_id in raw_support_claim_ids)
    validated_support_edges = (
        support_edges & declared_support_edges
        if graph_schema == "v2"
        else support_edges
    )
    current_state_edges = {
        (str(edge.get("from") or ""), str(edge.get("to") or ""))
        for edge in edges
        if str(edge.get("type") or "") == "CURRENT_STATE_OF"
    }
    asserts_sources_by_claim: Dict[str, List[str]] = {}
    occurred_targets_by_event: Dict[str, List[str]] = {}
    has_time_targets_by_claim: Dict[str, List[str]] = {}
    current_after_targets_by_state: Dict[str, List[str]] = {}
    state_ids_by_support_claim: Dict[str, List[str]] = {}
    relation_neighbors: Dict[str, set[str]] = {}
    relation_types_by_pair: Dict[Tuple[str, str], set[str]] = {}
    relation_types_by_unordered_pair: Dict[Tuple[str, str], set[str]] = {}
    for edge in edges:
        edge_type = str(edge.get("type") or "")
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if edge_type == "ASSERTS":
            asserts_sources_by_claim.setdefault(target, []).append(source)
        elif edge_type == "OCCURRED_AT":
            occurred_targets_by_event.setdefault(source, []).append(target)
        elif edge_type == "HAS_TIME":
            has_time_targets_by_claim.setdefault(source, []).append(target)
        elif edge_type == "CURRENT_AFTER":
            current_after_targets_by_state.setdefault(source, []).append(target)
        elif edge_type in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}:
            relation_neighbors.setdefault(source, set()).add(target)
            relation_neighbors.setdefault(target, set()).add(source)
            relation_types_by_pair.setdefault((source, target), set()).add(edge_type)
            relation_types_by_unordered_pair.setdefault(tuple(sorted((source, target))), set()).add(edge_type)
    for source, target in validated_support_edges:
        state_ids_by_support_claim.setdefault(source, []).append(target)
    v2_lifecycle_target_claim_ids = {
        str(edge.get("to") or "")
        for edge in edges
        if str(edge.get("type") or "") in {"CORRECTS", "SUPERSEDES"}
    }
    v2_historical_state_ids = {
        state_id
        for claim_id in v2_lifecycle_target_claim_ids
        for state_id in state_ids_by_support_claim.get(claim_id, [])
    }
    v2_active_conflicting_state_ids: set[str] = set()
    if graph_schema == "v2":
        for edge in edges:
            if str(edge.get("type") or "") != "CONFLICTS_WITH":
                continue
            source_claim_id = str(edge.get("from") or "")
            target_claim_id = str(edge.get("to") or "")
            for source_state_id in state_ids_by_support_claim.get(source_claim_id, []):
                for target_state_id in state_ids_by_support_claim.get(target_claim_id, []):
                    if source_state_id == target_state_id:
                        warnings.append(
                            f"v2_state_internal_conflict:{source_state_id}:{source_claim_id}:{target_claim_id}"
                        )
                    elif (
                        source_state_id not in v2_historical_state_ids
                        and target_state_id not in v2_historical_state_ids
                    ):
                        v2_active_conflicting_state_ids.update((source_state_id, target_state_id))
    if graph_schema == "v2":
        for source, target in sorted(support_edges - declared_support_edges):
            warnings.append(f"state_support_edge_undeclared:{target}:{source}")
        for pair, relation_types in sorted(relation_types_by_unordered_pair.items()):
            if len(relation_types) > 1:
                warnings.append(
                    f"relation_pair_type_conflict:{pair[0]}:{pair[1]}:{','.join(sorted(relation_types))}"
                )
    if graph_schema == "v2":
        active_single_states_by_dimension: Dict[Tuple[str, str], List[str]] = {}
        for state_id, state in nodes.items():
            if (
                str(state.get("node_type") or "") == "StateFacet"
                and str(state.get("slot_type") or "") == "single"
                and state_id not in v2_historical_state_ids
            ):
                bucket = (
                    str(state.get("subject_key") or ""),
                    str(state.get("state_dimension") or ""),
                )
                active_single_states_by_dimension.setdefault(bucket, []).append(state_id)
        for bucket, state_ids in active_single_states_by_dimension.items():
            if len(state_ids) > 1 and any(
                state_id not in v2_active_conflicting_state_ids for state_id in state_ids
            ):
                warnings.append(
                    f"v2_single_slot_active_count:{bucket[0]}:{bucket[1]}:{len(state_ids)}"
                )
    claims_reachable_from_state = set(state_ids_by_support_claim)
    reachability_frontier = list(claims_reachable_from_state)
    while reachability_frontier:
        claim_id = reachability_frontier.pop()
        for neighbor in relation_neighbors.get(claim_id, set()):
            if neighbor not in claims_reachable_from_state:
                claims_reachable_from_state.add(neighbor)
                reachability_frontier.append(neighbor)
    for identifier, node in nodes.items():
        node_type = str(node.get("node_type") or "")
        internal_identifier = node_id(node)
        if not internal_identifier or internal_identifier != identifier:
            warnings.append(f"node_id_invalid:{identifier}:{internal_identifier}")
        if node_type not in NODE_TYPES:
            warnings.append(f"unsupported_node_type:{identifier}:{node_type}")
        if uses_role_aware_time(graph_schema) and node_type == "Time":
            time_role = str(node.get("time_role") or "")
            if time_role not in TIME_ROLES:
                warnings.append(f"unsupported_time_role:{identifier}:{time_role}")
        if uses_role_aware_time(graph_schema) and node_type == "Claim":
            time_value = str(node.get("time_value") or "")
            time_role = str(node.get("time_role") or "")
            allowed_claim_roles = TIME_ROLES
            if time_role and time_role not in allowed_claim_roles:
                warnings.append(f"claim_time_role_unsupported:{identifier}:{time_role}")
            if time_value and not time_role:
                warnings.append(f"claim_time_role_missing:{identifier}:{time_value}")
            if time_role and not time_value:
                warnings.append(f"claim_time_value_missing:{identifier}:{time_role}")
        if graph_schema == "v2" and node_type == "Claim":
            supporting_state_ids = list(dict.fromkeys(state_ids_by_support_claim.get(identifier, [])))
            if v2_claim_is_persistent_state(node):
                for field in (
                    "canonical_subject",
                    "subject_key",
                    "state_domain",
                    "slot_type",
                    "state_target",
                    "state_dimension",
                    "dimension_source",
                    "dimension_reason",
                ):
                    if not str(node.get(field) or "").strip():
                        warnings.append(f"v2_claim_state_field_missing:{identifier}:{field}")
                state_domain = str(node.get("state_domain") or "")
                state_target = str(node.get("state_target") or "")
                if state_domain and state_domain != v2_state_domain(node):
                    warnings.append(f"v2_claim_state_domain_mismatch:{identifier}:{state_domain}")
                if state_domain and state_target and str(node.get("state_dimension") or "") != f"{state_domain}:{state_target}":
                    warnings.append(f"v2_claim_state_dimension_mismatch:{identifier}:{node.get('state_dimension')}")
                if str(node.get("slot_type") or "") not in {"single", "object_scoped"}:
                    warnings.append(f"v2_claim_slot_type_invalid:{identifier}:{node.get('slot_type')}")
                if len(supporting_state_ids) != 1:
                    warnings.append(f"v2_claim_state_support_count:{identifier}:{len(supporting_state_ids)}")
            elif supporting_state_ids:
                warnings.append(f"v2_nonpersistent_claim_supports_state:{identifier}")
        if graph_schema == "v2" and node_type == "StateFacet":
            expected_semantics = {
                "fact_type": "state",
                "temporal_status": "ongoing",
                "intent": "none",
            }
            for field, expected_value in expected_semantics.items():
                if str(node.get(field) or "") != expected_value:
                    warnings.append(f"v2_state_{field}_invalid:{identifier}:{node.get(field)}")
            status = str(node.get("status") or "")
            if status not in {"current", "historical", "ambiguous"}:
                warnings.append(f"v2_state_status_invalid:{identifier}:{status}")
            raw_support_claim_ids = node.get("support_claim_ids")
            if not isinstance(raw_support_claim_ids, list):
                warnings.append(f"v2_state_support_not_list:{identifier}")
                support_claim_ids: List[str] = []
            else:
                support_claim_ids = [str(claim_id) for claim_id in raw_support_claim_ids]
            if not support_claim_ids:
                warnings.append(f"v2_state_support_missing:{identifier}")
            if len(support_claim_ids) != len(set(support_claim_ids)):
                warnings.append(f"v2_state_support_duplicate:{identifier}")
            for claim_id in support_claim_ids:
                if node_types_by_id.get(claim_id) != "Claim":
                    warnings.append(f"v2_state_support_invalid:{identifier}:{claim_id}")
                elif (claim_id, identifier) not in support_edges:
                    warnings.append(f"v2_state_support_edge_missing:{identifier}:{claim_id}")
            expected_support_event_ids = list(
                dict.fromkeys(
                    str(nodes.get(claim_id, {}).get("source_event_id") or "")
                    for claim_id in support_claim_ids
                    if node_types_by_id.get(claim_id) == "Claim"
                )
            )
            expected_support_event_ids = [event_id for event_id in expected_support_event_ids if event_id]
            raw_support_event_ids = node.get("support_event_ids")
            support_event_ids = (
                [str(event_id) for event_id in raw_support_event_ids]
                if isinstance(raw_support_event_ids, list)
                else []
            )
            if not isinstance(raw_support_event_ids, list):
                warnings.append(f"v2_state_support_events_not_list:{identifier}")
            if support_event_ids != expected_support_event_ids:
                warnings.append(
                    f"v2_state_support_events_mismatch:{identifier}:{support_event_ids}:expected={expected_support_event_ids}"
                )
            for event_id in support_event_ids:
                if node_types_by_id.get(event_id) != "Episode/Event":
                    warnings.append(f"v2_state_support_event_invalid:{identifier}:{event_id}")

            primary_claim_id = str(node.get("primary_claim_id") or "")
            primary_claim = nodes.get(primary_claim_id, {})
            if node_types_by_id.get(primary_claim_id) != "Claim":
                warnings.append(f"v2_state_primary_invalid:{identifier}:{primary_claim_id}")
            if primary_claim_id not in support_claim_ids:
                warnings.append(f"v2_state_primary_not_supported:{identifier}:{primary_claim_id}")
            for field in (
                "subject_key",
                "canonical_subject",
                "state_domain",
                "slot_type",
                "state_target",
                "state_dimension",
                "dimension_source",
                "dimension_reason",
            ):
                if not str(node.get(field) or "").strip():
                    warnings.append(f"v2_state_identity_field_missing:{identifier}:{field}")
                if primary_claim and node.get(field) != primary_claim.get(field):
                    warnings.append(f"v2_state_primary_field_mismatch:{identifier}:{primary_claim_id}:{field}")
            state_domain = str(node.get("state_domain") or "")
            state_target = str(node.get("state_target") or "")
            if state_domain and state_target and str(node.get("state_dimension") or "") != f"{state_domain}:{state_target}":
                warnings.append(f"v2_state_dimension_mismatch:{identifier}:{node.get('state_dimension')}")
            if primary_claim and str(node.get("subject") or "") != str(primary_claim.get("canonical_subject") or ""):
                warnings.append(f"v2_state_primary_field_mismatch:{identifier}:{primary_claim_id}:subject")
            if primary_claim and node.get("value") != primary_claim.get("value"):
                warnings.append(f"v2_state_primary_field_mismatch:{identifier}:{primary_claim_id}:value")
            for support_claim_id in support_claim_ids:
                support_claim = nodes.get(support_claim_id, {})
                for field in ("subject_key", "state_domain", "state_dimension"):
                    if support_claim and support_claim.get(field) != node.get(field):
                        warnings.append(
                            f"v2_state_support_identity_mismatch:{identifier}:{support_claim_id}:{field}"
                        )

            expected_status = "current"
            if identifier in v2_historical_state_ids:
                expected_status = "historical"
            elif identifier in v2_active_conflicting_state_ids:
                expected_status = "ambiguous"
            if status != expected_status:
                warnings.append(
                    f"v2_state_status_relation_mismatch:{identifier}:{status}:expected={expected_status}"
                )

            current_after_targets = current_after_targets_by_state.get(identifier, [])
            if len(current_after_targets) != 1:
                warnings.append(f"v2_state_current_after_count:{identifier}:{len(current_after_targets)}")
            for time_identifier in current_after_targets:
                time_node = nodes.get(time_identifier, {})
                if str(time_node.get("time_role") or "") != "current_after":
                    warnings.append(f"v2_state_current_after_role_invalid:{identifier}:{time_identifier}")
                if str(time_node.get("value") or "") != str(node.get("current_after") or ""):
                    warnings.append(f"v2_state_current_after_value_mismatch:{identifier}:{time_identifier}")
            raw_scope_ids = node.get("scope_ids")
            scope_ids = [str(scope_identifier) for scope_identifier in raw_scope_ids] if isinstance(raw_scope_ids, list) else []
            if not scope_ids:
                warnings.append(f"v2_state_scope_missing:{identifier}")
            for scope_identifier in scope_ids:
                if node_types_by_id.get(scope_identifier) != "Entity/Scope":
                    warnings.append(f"v2_state_scope_invalid:{identifier}:{scope_identifier}")
                elif (identifier, scope_identifier) not in current_state_edges:
                    warnings.append(f"v2_state_scope_edge_missing:{identifier}:{scope_identifier}")
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
        if uses_role_aware_time(graph_schema) and edge_type == "HAS_TIME" and target in nodes:
            edge_role = str(edge.get("time_role") or "")
            target_role = str(nodes[target].get("time_role") or "")
            if edge_role != target_role:
                warnings.append(f"has_time_role_mismatch:{index}:{edge_role}:{target_role}")
        if graph_schema == "v2" and edge_type in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}:
            if not normalize_label(edge.get("reason")):
                warnings.append(f"relation_reason_missing:{index}:{edge_type}")
            evidence_event_ids = [str(item) for item in edge.get("evidence_event_ids", []) or []]
            if not evidence_event_ids:
                warnings.append(f"relation_evidence_missing:{index}:{edge_type}")
            endpoint_event_ids = {
                str(nodes.get(claim_id, {}).get("source_event_id") or "")
                for claim_id in (source, target)
            }
            for evidence_event_id in evidence_event_ids:
                if node_types_by_id.get(str(evidence_event_id)) != "Episode/Event":
                    warnings.append(f"relation_evidence_event_missing:{index}:{evidence_event_id}")
                elif evidence_event_id not in endpoint_event_ids:
                    warnings.append(f"relation_evidence_not_endpoint:{index}:{evidence_event_id}")
            if edge_type in {"CORRECTS", "SUPERSEDES"}:
                source_dialog_id = str(nodes.get(source, {}).get("dialog_id") or "")
                target_dialog_id = str(nodes.get(target, {}).get("dialog_id") or "")
                source_order = dialog_sort_key(source_dialog_id)
                target_order = dialog_sort_key(target_dialog_id)
                direction_is_valid = source_order > target_order or source_dialog_id == target_dialog_id
                if not direction_is_valid:
                    warnings.append(f"relation_direction_invalid:{index}:{edge_type}:{source_dialog_id}->{target_dialog_id}")
            source_claim = nodes.get(source, {})
            target_claim = nodes.get(target, {})
            if (
                str(source_claim.get("subject_key") or "") != str(target_claim.get("subject_key") or "")
                or str(source_claim.get("state_domain") or "") != str(target_claim.get("state_domain") or "")
                or str(source_claim.get("state_dimension") or "") != str(target_claim.get("state_dimension") or "")
            ):
                warnings.append(f"v2_relation_state_dimension_mismatch:{index}:{source}->{target}")
    forbidden_fields = {"A", "R", "answer", "options", "gold_evidence", "evidence"}
    for identifier, node in nodes.items():
        leaked = sorted(forbidden_fields & set(node.keys()))
        if leaked:
            warnings.append(f"forbidden_gold_field:{identifier}:{','.join(leaked)}")
    return warnings


def recompute_graph_summary(
    sample_id: str,
    node_rows: Sequence[Mapping[str, Any]],
    edge_rows: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
    base: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    summary = dict(base or {})
    events = [node for node in node_rows if node.get("node_type") == "Episode/Event"]
    claims = [node for node in node_rows if node.get("node_type") == "Claim"]
    states = [node for node in node_rows if node.get("node_type") == "StateFacet"]
    relation_edges = [
        edge
        for edge in edge_rows
        if str(edge.get("type") or "") in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}
    ]
    summary.update(
        {
            "sample_id": sample_id,
            "session_count": len({str(event.get("session_id") or "") for event in events if event.get("session_id")}),
            "event_count": len(events),
            "claim_count": len(claims),
            "state_facet_count": len(states),
            "node_count": len(node_rows),
            "edge_count": len(edge_rows),
            "node_counts": dict(Counter(str(node.get("node_type") or "") for node in node_rows).most_common()),
            "edge_counts": dict(Counter(str(edge.get("type") or "") for edge in edge_rows).most_common()),
            "claim_facets": dict(Counter(str(claim.get("facet_key") or "") for claim in claims).most_common()),
            "claim_extraction_methods": dict(
                Counter(str(claim.get("extraction_method") or "") for claim in claims).most_common()
            ),
            "claim_time_roles": dict(
                Counter(str(claim.get("time_role") or "none") for claim in claims).most_common()
            ),
            "claim_fact_types": dict(
                Counter(str(claim.get("fact_type") or "none") for claim in claims).most_common()
            ),
            "claim_temporal_statuses": dict(
                Counter(str(claim.get("temporal_status") or "none") for claim in claims).most_common()
            ),
            "current_state_reviews": dict(
                Counter(str(claim.get("current_state_review") or "not_reviewed") for claim in claims).most_common()
            ),
            "time_node_roles": dict(
                Counter(
                    str(node.get("time_role") or "")
                    for node in node_rows
                    if node.get("node_type") == "Time"
                ).most_common()
            ),
            "relation_edge_count": len(relation_edges),
            "relation_edge_types": dict(
                Counter(str(edge.get("type") or "") for edge in relation_edges).most_common()
            ),
            "top_subjects": dict(Counter(str(claim.get("subject") or "") for claim in claims).most_common(20)),
            "warnings": list(warnings),
        }
    )
    summary.setdefault("claim_rejection_diagnostics", [])
    return summary


def build_sample_graph(
    *,
    data_path: Path,
    sample_id: str,
    claim_mode: str,
    resolver_mode: str,
    client: Optional[LLMClient],
    runtime: Optional[LLMRuntimeConfig],
    provider: Optional[str],
    model: Optional[str],
    max_tokens: int,
    message_chunk_size: int,
    claim_workers: int,
    resolver_workers: int,
    resolver_candidate_limit: int,
    max_claims_per_turn: int,
    event_limit: int,
    graph_schema: str = "v1",
) -> Dict[str, Any]:
    sample = load_sample(data_path, sample_id)
    turns = list(sample.turns[:event_limit] if event_limit else sample.turns)
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    for turn in turns:
        materialize_base_event(nodes, edges, sample.sample_id, turn, graph_schema)

    raw_claims: List[Dict[str, Any]] = []
    claim_rejection_diagnostics: List[Dict[str, Any]] = []
    if claim_mode == "llm":
        if client is None:
            raise ValueError("claim_mode=llm requires an LLM client")
        extracted_claims, claim_rejection_diagnostics = extract_llm_claims(
            client=client,
            runtime=runtime,
            sample_id=sample.sample_id,
            turns=turns,
            message_chunk_size=message_chunk_size,
            max_claims_per_turn=max_claims_per_turn,
            workers=claim_workers,
            graph_schema=graph_schema,
        )
        raw_claims.extend(extracted_claims)

    turn_by_id = {turn.dia_id: turn for turn in turns}
    claims: List[Dict[str, Any]] = []
    for index, raw_claim in enumerate(raw_claims, start=1):
        claim = materialize_claim(
            nodes,
            edges,
            sample.sample_id,
            turn_by_id,
            raw_claim,
            index,
            graph_schema,
        )
        if claim is not None:
            claims.append(claim)

    relations: List[Dict[str, Any]] = []
    if graph_schema == "v2" and claims:
        persistent_claims, state_clusters, relations = resolve_v2_state_clusters(
            claims,
            client=client if resolver_mode == "llm" else None,
            candidate_limit=resolver_candidate_limit,
        )
        materialize_v2_state_facets(
            nodes,
            edges,
            sample.sample_id,
            persistent_claims,
            state_clusters,
        )
        for relation in relations:
            add_edge(
                edges,
                str(relation["type"]),
                str(relation["from"]),
                str(relation["to"]),
                reason=relation.get("reason"),
                evidence_event_ids=relation.get("evidence_event_ids"),
            )
    elif resolver_mode == "llm" and claims:
        if client is None:
            raise ValueError("resolver_mode=llm requires an LLM client")
        relations = resolve_claim_relations(
            client=client,
            runtime=runtime,
            sample_id=sample.sample_id,
            claims=claims,
            candidate_limit=resolver_candidate_limit,
            workers=resolver_workers,
            graph_schema=graph_schema,
        )
        for relation in relations:
            add_edge(
                edges,
                str(relation["type"]),
                str(relation["from"]),
                str(relation["to"]),
                reason=relation.get("reason"),
                evidence_event_ids=relation.get("evidence_event_ids"),
            )

    edge_rows = dedupe_edges(edges)
    node_rows = sorted(nodes.values(), key=lambda node: (str(node.get("node_type") or ""), node_id(node)))
    warnings = validate_graph(nodes, edge_rows, graph_schema)
    summary = recompute_graph_summary(
        sample.sample_id,
        node_rows,
        edge_rows,
        warnings,
        {"claim_rejection_diagnostics": claim_rejection_diagnostics},
    )
    manifest = {
        "benchmark": "LoCoMo QA",
        "sample_id": sample.sample_id,
        "schema_version": graph_schema_version(graph_schema),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_fields": ["sample_id", "conversation.session_*", "conversation.session_*_date_time"],
        "input_provenance": {
            "data_path": str(data_path),
            "data_sha256": file_sha256(data_path),
            "graph_builder_path": str(Path(__file__).resolve()),
            "graph_builder_sha256": file_sha256(Path(__file__).resolve()),
            "cache_path": str(runtime.cache_path) if runtime is not None else None,
            "cache_shard_root": (
                str(cache_shard_root(runtime.cache_path))
                if runtime is not None
                else None
            ),
            "use_cache": bool(runtime.use_cache) if runtime is not None else False,
        },
        "leakage_policy": {
            "graph_build_inputs": ["locomo10.json:sample.conversation"],
            "qa_fields_accessed": False,
            "gold_fields_used": [],
            "ignored_fields": ["qa", "answer", "evidence", "event_summary", "observation", "session_summary"],
            "notes": (
                "The release JSON is deserialized as one file, but QA fields are never accessed or passed "
                "to graph prompts; only sample_id and conversation are used."
            ),
        },
        "claim_mode": claim_mode,
        "resolver_mode": resolver_mode,
        "provider": provider,
        "model": model,
        "max_tokens": max_tokens,
        "message_chunk_size": message_chunk_size,
        "claim_workers": claim_workers,
        "resolver_workers": resolver_workers,
        "resolver_candidate_limit": resolver_candidate_limit,
        "resolver_candidate_limit_scope": (
            "ordered_state_fold_active_cluster_limit" if graph_schema == "v2" else "relation_resolver"
        ),
        "state_resolution": (
            {
                "mode": "ordered_state_fold",
                "adapter": "locomo_persistent_state",
                "sequence_key": ["subject_key", "state_domain"],
                "dimension_key": "state_dimension",
                "query_evidence_policy": "primary_claim_plus_relation_witnesses",
                "ordering": "dialog_sort_key_then_source_claim_order",
                "same_dialog_policy": "source list order is not lifecycle evidence; the two-Claim decision owns the winner",
                "deterministic_steps": [
                    "persistent-state eligibility",
                    "unambiguous Subject aliasing",
                    "single-slot and one-scope dimension routing",
                    "claim-local abstention for unresolved generic state targets",
                    "cluster merge, status, lineage, and StateFacet materialization",
                ],
                "llm_steps": [
                    "one-Claim target fallback when deterministic dimension routing abstains",
                    "two-Claim lifecycle decision against the latest representative of each active cluster",
                ],
                "pair_decisions": sorted(STATE_MERGE_DECISIONS),
                "cluster_coherence_policy": "incoming Claims compare only with each active cluster's latest representative",
                "candidate_limit_policy": "fail_if_active_clusters_exceed_limit; never silently truncate",
            }
            if graph_schema == "v2"
            else None
        ),
        "max_claims_per_turn": max_claims_per_turn,
        "event_limit": event_limit,
        "temporal_semantics": {
            "mode": "role_aware" if uses_role_aware_time(graph_schema) else "legacy",
            "time_roles": list(TIME_ROLES) if uses_role_aware_time(graph_schema) else ["session_date_time", "claim_time"],
            "claim_time_roles": (
                list(claim_time_roles(graph_schema))
                if uses_role_aware_time(graph_schema)
                else ["claim_time"]
            ),
            "relative_time_policy": (
                "Preserve the source expression and anchor it to the source session date_time."
                if uses_role_aware_time(graph_schema)
                else "Legacy claim_time value."
            ),
            "time_role_policy": (
                "preserve role-aware Claim time; persistent-state eligibility excludes bounded and prospective roles; StateFacet current_after is code-owned"
                if graph_schema == "v2"
                else "legacy schema policy"
            ),
        },
        "claim_semantics": {
            "mode": "stable_dimension_state_fold_v2" if graph_schema == "v2" else "subject_facet_value",
            "fields": (
                [
                        "subject",
                        "canonical_subject",
                        "subject_key",
                        "facet_key",
                        "state_domain",
                        "slot_type",
                        "state_target",
                        "state_dimension",
                        "value",
                ]
                if graph_schema == "v2"
                else ["subject", "facet_key", "value"]
            ),
            "state_policy": (
                "persistent-state and time-role eligibility gate; code-owned Subject aliases and high-confidence state dimensions; focused one-Claim target fallback only when unresolved; ordered pairwise fold inside one stable dimension; deterministic multi-support StateFacets and lifecycle lineage"
                if graph_schema == "v2"
                else "one StateFacet per Claim"
            ),
            "identity_policy": (
                "sample-local exact labels plus unambiguous short-name/full-name aliases; possessive and family labels remain separate"
                if graph_schema == "v2"
                else "legacy subject/facet labels"
            ),
            "repair_policy": "legacy extraction response handling",
        },
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
        "edge_endpoint_types": {edge: list(types) for edge, types in EDGE_ENDPOINT_TYPES.items()},
        "summary": summary,
    }
    return {"manifest": manifest, "summary": summary, "nodes": node_rows, "edges": edge_rows}


def write_sample_graph(output_dir: Path, sample_id: str, graph: Mapping[str, Any]) -> Path:
    schema_version = str(graph.get("manifest", {}).get("schema_version") or "")
    graph_to_write = dict(graph)
    sample_dir = output_dir / safe_part(sample_id)
    ensure_output_manifest_compatible(output_dir, sample_id, schema_version)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{safe_part(sample_id)}.tmp-", dir=output_dir))
    backup_dir: Optional[Path] = None
    try:
        (temporary_dir / "manifest.json").write_text(
            json_dump(graph_to_write["manifest"]),
            encoding="utf-8",
        )
        (temporary_dir / "graph_summary.json").write_text(
            json_dump(graph_to_write["summary"]),
            encoding="utf-8",
        )
        write_jsonl(temporary_dir / "nodes.jsonl", graph_to_write["nodes"])
        write_jsonl(temporary_dir / "edges.jsonl", graph_to_write["edges"])
        if sample_dir.exists():
            backup_dir = Path(tempfile.mkdtemp(prefix=f".{safe_part(sample_id)}.backup-", dir=output_dir))
            backup_dir.rmdir()
            sample_dir.rename(backup_dir)
        try:
            temporary_dir.rename(sample_dir)
        except Exception:
            if backup_dir is not None and backup_dir.exists() and not sample_dir.exists():
                backup_dir.rename(sample_dir)
            raise
        if backup_dir is not None:
            shutil.rmtree(backup_dir)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
    return sample_dir


def main() -> int:
    args = parse_args()
    max_claims_per_turn = args.max_claims_per_turn if args.max_claims_per_turn is not None else 2
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(args.graph_schema)
    cache_path = Path(args.cache) if args.cache else default_cache_path(args.graph_schema)
    if uses_role_aware_time(args.graph_schema) and output_dir.name.lower().endswith("_v1"):
        print(
            f"Refusing to write a role-aware graph into a v1-labelled directory: {output_dir}",
            file=sys.stderr,
        )
        return 2
    try:
        ensure_output_schema_compatible(output_dir, args.sample_id, args.graph_schema)
    except ValueError as exc:
        print(f"Output safety check failed: {exc}", file=sys.stderr)
        return 2
    client: Optional[LLMClient] = None
    runtime: Optional[LLMRuntimeConfig] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    needs_llm = args.claim_mode == "llm" or args.resolver_mode == "llm"
    if needs_llm:
        load_dotenv()
        if args.max_tokens:
            os.environ["LLM_MAX_TOKENS"] = str(args.max_tokens)
        try:
            api_key, model, api_base = provider_config(args.provider)
        except RuntimeError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            return 2
        if args.model:
            model = args.model
        provider = args.provider
        client = LLMClient(
            provider=args.provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            cache_path=cache_path,
            use_cache=not args.no_cache,
        )
        runtime = LLMRuntimeConfig(
            provider=args.provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            cache_path=cache_path,
            use_cache=not args.no_cache,
        )
    try:
        graph = build_sample_graph(
            data_path=Path(args.data),
            sample_id=args.sample_id,
            claim_mode=args.claim_mode,
            resolver_mode=args.resolver_mode,
            client=client,
            runtime=runtime,
            provider=provider,
            model=model,
            max_tokens=args.max_tokens,
            message_chunk_size=args.message_chunk_size,
            claim_workers=args.claim_workers,
            resolver_workers=args.resolver_workers,
            resolver_candidate_limit=args.resolver_candidate_limit,
            max_claims_per_turn=max_claims_per_turn,
            event_limit=args.event_limit,
            graph_schema=args.graph_schema,
        )
    except LLMRequestError as exc:
        print("\nLLM request failed during LoCoMo graph build.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("\nLoCoMo graph build failed.", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    summary = graph["summary"]
    if args.graph_schema == "v2" and summary["warnings"]:
        print(
            f"\nLoCoMo {args.graph_schema} graph validation failed; existing output was not modified.",
            file=sys.stderr,
        )
        for warning in summary["warnings"][:20]:
            print(f"- {warning}", file=sys.stderr)
        return 1
    sample_dir = write_sample_graph(output_dir, args.sample_id, graph)
    print("LoCoMo QA sample graph")
    print(
        f"sample_id={args.sample_id} schema={graph['manifest']['schema_version']} "
        f"output_dir={sample_dir}"
    )
    print(
        "stats "
        f"events={summary['event_count']} claims={summary['claim_count']} "
        f"state_facets={summary['state_facet_count']} nodes={summary['node_count']} "
        f"edges={summary['edge_count']} warnings={len(summary['warnings'])}"
    )
    if summary["warnings"]:
        print("warnings:")
        for warning in summary["warnings"][:20]:
            print(f"- {warning}")
    return 0 if not summary["warnings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

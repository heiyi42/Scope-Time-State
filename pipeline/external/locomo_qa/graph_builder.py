from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.locomo_qa.loader import DATA_PATH, DialogTurn, dialog_sort_key, load_sample  # noqa: E402
from pipeline.external.paths import EXTERNAL_CACHE_DIR, EXTERNAL_GRAPH_DIR  # noqa: E402


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
    parser.add_argument("--output-dir", default=str(EXTERNAL_GRAPH_DIR / "locomo_qa_sample_graph_v1"))
    parser.add_argument("--claim-mode", choices=("llm", "none"), default="llm")
    parser.add_argument("--resolver-mode", choices=("llm", "none"), default="llm")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None, help="Optional model override, e.g. deepseek-v4-flash.")
    parser.add_argument("--cache", default=str(EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_graph_builder.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--message-chunk-size", type=int, default=16)
    parser.add_argument("--claim-workers", type=int, default=4, help="Parallel LLM workers for claim extraction chunks.")
    parser.add_argument("--resolver-workers", type=int, default=4, help="Parallel LLM workers for claim relation buckets.")
    parser.add_argument("--resolver-candidate-limit", type=int, default=24)
    parser.add_argument("--max-claims-per-turn", type=int, default=2)
    parser.add_argument("--event-limit", type=int, default=0, help="Debug limit only; 0 builds the full sample.")
    return parser.parse_args()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def short_hash(value: object, length: int = 10) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:length]


def safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "unknown"


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


def time_id(role: str, value: str) -> str:
    return f"time::{safe_part(role)}::{safe_part(value)}::{short_hash(value)}"


def add_time_node(nodes: Dict[str, Dict[str, Any]], role: str, value: str, sample_id: str) -> str:
    identifier = time_id(role, value)
    add_node(
        nodes,
        {
            "node_type": "Time",
            "time_id": identifier,
            "sample_id": sample_id,
            "time_role": role,
            "value": value,
        },
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


def turn_prompt_block(turns: Sequence[DialogTurn]) -> str:
    blocks: List[str] = []
    for turn in turns:
        blocks.append(
            "\n".join(
                [
                    f'<dialog id="{turn.dia_id}" session_id="{turn.session_id}" date="{turn.session_date_time}" speaker="{turn.speaker}">',
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


def claim_system_prompt() -> str:
    return (
        "You extract graph-ready memory claims from LoCoMo personal conversations. "
        "Use only the provided dialog turns, session dates, speakers, and text metadata. "
        "Do not use QA answers, evidence labels, or outside benchmark metadata. "
        "Resolve first-person pronouns to the speaker name when the subject is clear. "
        "Keep claims faithful, atomic, and useful for later single-hop, multi-hop, temporal, and open-domain QA. "
        "Return strict JSON only."
    )


def claim_user_prompt(sample_id: str, turns: Sequence[DialogTurn], max_claims_per_turn: int) -> str:
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Sample ID: {sample_id}\n"
        f"Max claims per dialog turn: {max_claims_per_turn}\n\n"
        "Extract compact memory claims from these dialog turns. Skip greetings, filler, and unsupported inferences. "
        "For open-domain clues, store the conversation clue itself, not the outside-knowledge answer. "
        "Use facet_key from this set when possible: "
        f"{', '.join(sorted(FACET_KEYS))}.\n\n"
        f"{turn_prompt_block(turns)}\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"claims\": ["
        "{"
        "\"dialog_id\": \"D1:1\", "
        "\"subject\": \"person, place, activity, object, or relation\", "
        "\"facet_key\": \"identity|relationship|activity|preference|place|plan|event|date|status|health|work|education|family|other\", "
        "\"value\": \"faithful short fact from the dialog\", "
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


def normalize_facet(value: object) -> str:
    facet = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return facet if facet in FACET_KEYS else "other"


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
) -> List[Dict[str, Any]]:
    raw = client.complete_json(claim_system_prompt(), claim_user_prompt(sample_id, turns, max_claims_per_turn))
    raw_claims = raw.get("claims", [])
    if not isinstance(raw_claims, list):
        return []
    allowed_dialog_ids = {turn.dia_id for turn in turns}
    claims: List[Dict[str, Any]] = []
    claim_count_by_dialog: Counter[str] = Counter()
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            continue
        dialog_id = normalize_label(raw_claim.get("dialog_id"))
        if dialog_id not in allowed_dialog_ids:
            continue
        if claim_count_by_dialog[dialog_id] >= max_claims_per_turn:
            continue
        subject = normalize_label(raw_claim.get("subject"))
        value = normalize_label(raw_claim.get("value"))
        if not subject or not value:
            continue
        claim_count_by_dialog[dialog_id] += 1
        claims.append(
            {
                "dialog_id": dialog_id,
                "subject": subject,
                "facet_key": normalize_facet(raw_claim.get("facet_key")),
                "value": value,
                "time_value": normalize_label(raw_claim.get("time_value")),
                "scope_labels": normalize_scope_labels(raw_claim.get("scope_labels")),
                "confidence": raw_claim.get("confidence"),
                "extraction_method": "llm_offline_claim_extraction",
            }
        )
    return claims


def extract_llm_claims(
    *,
    client: LLMClient,
    runtime: Optional[LLMRuntimeConfig],
    sample_id: str,
    turns: Sequence[DialogTurn],
    message_chunk_size: int,
    max_claims_per_turn: int,
    workers: int,
) -> List[Dict[str, Any]]:
    turn_chunks = list(chunked(turns, message_chunk_size))

    def run_chunk(chunk_index: int, turn_chunk: Sequence[DialogTurn]) -> Tuple[int, List[Dict[str, Any]]]:
        chunk_client = client
        if workers > 1:
            if runtime is None:
                raise ValueError("parallel claim extraction requires LLMRuntimeConfig")
            first_id = turn_chunk[0].dia_id if turn_chunk else "empty"
            last_id = turn_chunk[-1].dia_id if turn_chunk else "empty"
            shard_name = f"{sample_id}_{chunk_index:05d}_{short_hash(first_id + last_id)}"
            chunk_client = make_sharded_client(runtime, "claim_extraction", shard_name)
        claims = extract_claims_for_chunk(chunk_client, sample_id, turn_chunk, max_claims_per_turn)
        return chunk_index, claims

    if workers <= 1:
        claims: List[Dict[str, Any]] = []
        for chunk_index, turn_chunk in enumerate(turn_chunks, start=1):
            first_id = turn_chunk[0].dia_id if turn_chunk else ""
            last_id = turn_chunk[-1].dia_id if turn_chunk else ""
            print(f"[locomo-graph] extracting claims chunk {chunk_index}/{len(turn_chunks)} {first_id}-{last_id}", flush=True)
            _chunk_index, chunk_claims = run_chunk(chunk_index, turn_chunk)
            claims.extend(chunk_claims)
            print(f"[locomo-graph] chunk {chunk_index}/{len(turn_chunks)} accepted={len(chunk_claims)}", flush=True)
        return claims

    print(f"[locomo-graph] parallel claim extraction workers={workers} chunks={len(turn_chunks)}", flush=True)
    results: Dict[int, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(run_chunk, chunk_index, turn_chunk): chunk_index
            for chunk_index, turn_chunk in enumerate(turn_chunks, start=1)
        }
        for future in as_completed(futures):
            chunk_index, chunk_claims = future.result()
            results[chunk_index] = chunk_claims
            print(f"[locomo-graph] chunk {chunk_index}/{len(turn_chunks)} accepted={len(chunk_claims)}", flush=True)
    claims = []
    for chunk_index in sorted(results):
        claims.extend(results[chunk_index])
    return claims


def materialize_base_event(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    sample_id: str,
    turn: DialogTurn,
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
    occurred_time = add_time_node(nodes, "session_date_time", turn.session_date_time, sample_id)
    add_edge(edges, "OCCURRED_AT", event_id, occurred_time, reason="LoCoMo session date_time")


def materialize_claim(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    sample_id: str,
    turn_by_id: Mapping[str, DialogTurn],
    raw_claim: Mapping[str, Any],
    claim_index: int,
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
        "time_value": normalize_label(raw_claim.get("time_value")),
        "scope_labels": normalize_scope_labels(raw_claim.get("scope_labels")),
        "confidence": raw_claim.get("confidence"),
        "extraction_method": raw_claim.get("extraction_method", "llm_offline_claim_extraction"),
        "graph_text": f"{subject} {facet_key}: {value}",
    }
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

    time_value = str(claim_node.get("time_value") or "").strip()
    support_time = add_time_node(nodes, "claim_time" if time_value else "session_date_time", time_value or turn.session_date_time, sample_id)
    if time_value:
        add_edge(edges, "HAS_TIME", claim_id, support_time, reason="claim extracted time expression")

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
        "current_after": time_value or turn.session_date_time,
        "scope_ids": [subject_scope_id] + topic_scope_ids,
        "graph_text": f"{subject} {facet_key}: {value}",
    }
    add_node(nodes, state_node)
    add_edge(edges, "SUPPORTS", claim_id, facet_id, reason="claim supports state facet")
    add_edge(edges, "CURRENT_AFTER", facet_id, support_time, reason="state facet support time")
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


def relation_user_prompt(sample_id: str, bucket_index: int, claims: Sequence[Mapping[str, Any]]) -> str:
    claim_rows = []
    for claim in claims:
        claim_rows.append(
            {
                "claim_id": claim.get("claim_id"),
                "dialog_id": claim.get("dialog_id"),
                "session_id": claim.get("session_id"),
                "speaker": claim.get("speaker"),
                "subject": claim.get("subject"),
                "facet_key": claim.get("facet_key"),
                "value": claim.get("value"),
                "time_value": claim.get("time_value"),
            }
        )
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Sample ID: {sample_id}\n"
        f"Resolver bucket: {bucket_index}\n\n"
        "Claims are listed in source dialog order. Decide whether any later claim corrects, supersedes, "
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


def relation_buckets(claims: Sequence[Mapping[str, Any]], candidate_limit: int) -> List[List[Mapping[str, Any]]]:
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


def normalize_relations(raw: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    claim_ids = {str(claim.get("claim_id") or "") for claim in claims}
    relations = raw.get("relations", [])
    if not isinstance(relations, list):
        return []
    accepted: List[Dict[str, Any]] = []
    seen = set()
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("type") or "").strip().upper()
        if relation_type not in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}:
            continue
        source = str(relation.get("from_claim_id") or relation.get("from") or "").strip()
        target = str(relation.get("to_claim_id") or relation.get("to") or "").strip()
        if not source or not target or source == target:
            continue
        if source not in claim_ids or target not in claim_ids:
            continue
        evidence_dialog_ids = []
        raw_evidence = relation.get("evidence_dialog_ids", [])
        if isinstance(raw_evidence, list):
            evidence_dialog_ids = [str(item) for item in raw_evidence if re.fullmatch(r"D\d+:\d+", str(item))]
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
                "reason": normalize_label(relation.get("reason")),
                "evidence_event_ids": evidence_dialog_ids,
            }
        )
    return accepted


def resolve_relation_bucket(
    client: LLMClient,
    sample_id: str,
    bucket_index: int,
    claims: Sequence[Mapping[str, Any]],
) -> Tuple[int, List[Dict[str, Any]]]:
    raw = client.complete_json(relation_system_prompt(), relation_user_prompt(sample_id, bucket_index, claims))
    return bucket_index, normalize_relations(raw, claims)


def resolve_claim_relations(
    *,
    client: LLMClient,
    runtime: Optional[LLMRuntimeConfig],
    sample_id: str,
    claims: Sequence[Mapping[str, Any]],
    candidate_limit: int,
    workers: int,
) -> List[Dict[str, Any]]:
    buckets = relation_buckets(claims, candidate_limit)
    if not buckets:
        return []

    def run_bucket(bucket_index: int, bucket_claims: Sequence[Mapping[str, Any]]) -> Tuple[int, List[Dict[str, Any]]]:
        bucket_client = client
        if workers > 1:
            if runtime is None:
                raise ValueError("parallel relation resolver requires LLMRuntimeConfig")
            claim_ids = "|".join(str(claim.get("claim_id") or "") for claim in bucket_claims)
            bucket_client = make_sharded_client(runtime, "relation_resolver", f"{sample_id}_{bucket_index:05d}_{short_hash(claim_ids)}")
        return resolve_relation_bucket(bucket_client, sample_id, bucket_index, bucket_claims)

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


def validate_graph(nodes: Mapping[str, Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> List[str]:
    warnings: List[str] = []
    node_types_by_id = {identifier: str(node.get("node_type") or "") for identifier, node in nodes.items()}
    for identifier, node in nodes.items():
        node_type = str(node.get("node_type") or "")
        if node_type not in NODE_TYPES:
            warnings.append(f"unsupported_node_type:{identifier}:{node_type}")
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
    forbidden_fields = {"A", "R", "answer", "options", "gold_evidence", "evidence"}
    for identifier, node in nodes.items():
        leaked = sorted(forbidden_fields & set(node.keys()))
        if leaked:
            warnings.append(f"forbidden_gold_field:{identifier}:{','.join(leaked)}")
    return warnings


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
    message_chunk_size: int,
    claim_workers: int,
    resolver_workers: int,
    resolver_candidate_limit: int,
    max_claims_per_turn: int,
    event_limit: int,
) -> Dict[str, Any]:
    sample = load_sample(data_path, sample_id)
    turns = list(sample.turns[:event_limit] if event_limit else sample.turns)
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    for turn in turns:
        materialize_base_event(nodes, edges, sample.sample_id, turn)

    raw_claims: List[Dict[str, Any]] = []
    if claim_mode == "llm":
        if client is None:
            raise ValueError("claim_mode=llm requires an LLM client")
        raw_claims.extend(
            extract_llm_claims(
                client=client,
                runtime=runtime,
                sample_id=sample.sample_id,
                turns=turns,
                message_chunk_size=message_chunk_size,
                max_claims_per_turn=max_claims_per_turn,
                workers=claim_workers,
            )
        )

    turn_by_id = {turn.dia_id: turn for turn in turns}
    claims: List[Dict[str, Any]] = []
    for index, raw_claim in enumerate(raw_claims, start=1):
        claim = materialize_claim(nodes, edges, sample.sample_id, turn_by_id, raw_claim, index)
        if claim is not None:
            claims.append(claim)

    relations: List[Dict[str, Any]] = []
    if resolver_mode == "llm" and claims:
        if client is None:
            raise ValueError("resolver_mode=llm requires an LLM client")
        relations = resolve_claim_relations(
            client=client,
            runtime=runtime,
            sample_id=sample.sample_id,
            claims=claims,
            candidate_limit=resolver_candidate_limit,
            workers=resolver_workers,
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
    warnings = validate_graph(nodes, edge_rows)
    summary = {
        "sample_id": sample.sample_id,
        "session_count": len({turn.session_id for turn in turns}),
        "event_count": len(turns),
        "claim_count": len(claims),
        "state_facet_count": sum(1 for node in node_rows if node.get("node_type") == "StateFacet"),
        "node_count": len(node_rows),
        "edge_count": len(edge_rows),
        "node_counts": dict(Counter(str(node.get("node_type") or "") for node in node_rows).most_common()),
        "edge_counts": dict(Counter(str(edge.get("type") or "") for edge in edge_rows).most_common()),
        "claim_facets": dict(Counter(str(claim.get("facet_key") or "") for claim in claims).most_common()),
        "claim_extraction_methods": dict(Counter(str(claim.get("extraction_method") or "") for claim in claims).most_common()),
        "relation_edge_count": len(relations),
        "relation_edge_types": dict(Counter(str(relation.get("type") or "") for relation in relations).most_common()),
        "top_subjects": dict(Counter(str(claim.get("subject") or "") for claim in claims).most_common(20)),
        "warnings": warnings,
    }
    manifest = {
        "benchmark": "LoCoMo QA",
        "sample_id": sample.sample_id,
        "schema_version": "locomo-qa-sample-sts-graph-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_path": str(data_path),
        "source_fields": ["sample_id", "conversation.session_*", "conversation.session_*_date_time"],
        "leakage_policy": {
            "graph_build_inputs": ["locomo10.json:sample.conversation"],
            "qa_fields_accessed": False,
            "gold_fields_loaded": [],
            "ignored_fields": ["qa", "answer", "evidence", "event_summary", "observation", "session_summary"],
            "notes": "The LoCoMo release colocates QA with conversation in locomo10.json; this builder only accesses sample_id and conversation fields.",
        },
        "claim_mode": claim_mode,
        "resolver_mode": resolver_mode,
        "provider": provider,
        "model": model,
        "message_chunk_size": message_chunk_size,
        "claim_workers": claim_workers,
        "resolver_workers": resolver_workers,
        "resolver_candidate_limit": resolver_candidate_limit,
        "max_claims_per_turn": max_claims_per_turn,
        "event_limit": event_limit,
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
        "edge_endpoint_types": {edge: list(types) for edge, types in EDGE_ENDPOINT_TYPES.items()},
        "summary": summary,
    }
    return {"manifest": manifest, "summary": summary, "nodes": node_rows, "edges": edge_rows}


def write_sample_graph(output_dir: Path, sample_id: str, graph: Mapping[str, Any]) -> Path:
    sample_dir = output_dir / safe_part(sample_id)
    if sample_dir.exists():
        shutil.rmtree(sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "manifest.json").write_text(json_dump(graph["manifest"]), encoding="utf-8")
    (sample_dir / "graph_summary.json").write_text(json_dump(graph["summary"]), encoding="utf-8")
    write_jsonl(sample_dir / "nodes.jsonl", graph["nodes"])
    write_jsonl(sample_dir / "edges.jsonl", graph["edges"])
    return sample_dir


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
        graph = build_sample_graph(
            data_path=Path(args.data),
            sample_id=args.sample_id,
            claim_mode=args.claim_mode,
            resolver_mode=args.resolver_mode,
            client=client,
            runtime=runtime,
            provider=provider,
            model=model,
            message_chunk_size=args.message_chunk_size,
            claim_workers=args.claim_workers,
            resolver_workers=args.resolver_workers,
            resolver_candidate_limit=args.resolver_candidate_limit,
            max_claims_per_turn=args.max_claims_per_turn,
            event_limit=args.event_limit,
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
    sample_dir = write_sample_graph(Path(args.output_dir), args.sample_id, graph)
    summary = graph["summary"]
    print("LoCoMo QA sample graph")
    print(f"sample_id={args.sample_id} output_dir={sample_dir}")
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

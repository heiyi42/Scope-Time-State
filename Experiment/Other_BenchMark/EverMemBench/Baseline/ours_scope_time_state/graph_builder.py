from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[5]
BASELINE_DIR = Path(__file__).resolve().parents[1]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config
from ours_scope_time_state.loader import CACHE_DIR, DATA_DIR, GRAPH_OUTPUT_DIR, EverMemEvent, load_topic_events
from pipeline.external.state_merge import STATE_MERGE_DECISIONS, StateMergeAdapter, fold_state_claims
from pipeline.external.sts_v2.schema import EDGE_ENDPOINT_TYPES, EDGE_TYPES, NODE_TYPES, SCHEMA_VERSION


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    model: str
    api_key: str
    api_base: str
    cache_path: Path
    use_cache: bool


STATE_FACETS = {
    "constraint", "deadline", "decision", "link", "metric", "next_step", "owner",
    "preference", "priority", "risk", "role", "scope", "skill", "state", "status", "style",
}
TIME_ROLES = {
    "occurred_at", "mentioned_at", "updated_at", "planned_for", "deadline_at",
    "valid_from", "started_at", "completed_at", "finalized_at",
}
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
STATEFUL_RE = re.compile(
    r"\b(owner|responsible|deadline|due|status|state|decision|constraint|risk|priority|"
    r"prefer|next step|plan|role|skill|metric|percent|completed|finished|started|updated|now)\b",
    re.I,
)
UPDATE_RE = re.compile(r"\b(now|updated?|changed?|replaced?|corrected?|instead|no longer|currently)\b", re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one EverMemBench topic with the shared STS v2 graph contract.")
    parser.add_argument("--data-root", default=str(DATA_DIR))
    parser.add_argument("--topic", default="01")
    parser.add_argument("--output-dir", default=str(GRAPH_OUTPUT_DIR / "evermembench_topic_graph_v2_state_merge"))
    parser.add_argument("--claim-mode", choices=("llm", "heuristic", "none"), default="llm")
    parser.add_argument("--resolver-mode", choices=("llm", "heuristic"), default="llm")
    parser.add_argument("--provider", choices=("openai", "deepseek", "local"), default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.evermembench_graph_builder.v2_state_merge.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--message-chunk-size", type=int, default=16)
    parser.add_argument("--claim-workers", type=int, default=1)
    parser.add_argument("--resolver-workers", type=int, default=1)
    parser.add_argument("--llm-event-filter", choices=("stateful", "all"), default="stateful")
    parser.add_argument("--max-claims-per-event", type=int, default=2)
    parser.add_argument("--resolver-candidate-limit", type=int, default=24)
    parser.add_argument("--resolver-bucket-limit", type=int, default=0, help="Deprecated smoke option; must be 0.")
    parser.add_argument("--event-limit", type=int, default=0)
    return parser.parse_args()


def safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "unknown"


def normalized_component(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def short_hash(value: object, length: int = 12) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:length]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def node_id(node: Mapping[str, Any]) -> str:
    node_type = str(node.get("node_type") or "")
    keys = {
        "Episode/Event": "event_id", "Claim": "claim_id", "StateFacet": "facet_id",
        "Entity/Scope": "scope_id", "Time": "time_id",
    }
    return str(node.get(keys.get(node_type, "")) or node.get("entity_id") or "")


def add_node(nodes: Dict[str, Dict[str, Any]], node: Mapping[str, Any]) -> None:
    identifier = node_id(node)
    if not identifier:
        raise ValueError(f"graph node has no identifier: {node}")
    existing = nodes.get(identifier)
    if existing is not None and existing != dict(node):
        raise ValueError(f"graph node id collision: {identifier}")
    nodes[identifier] = dict(node)


def add_edge(edges: List[Dict[str, Any]], edge_type: str, source: str, target: str, **payload: Any) -> None:
    row = {"type": edge_type, "from": source, "to": target}
    row.update({key: value for key, value in payload.items() if value not in (None, "", [])})
    edges.append(row)


def dedupe_edges(edges: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for edge in edges:
        key = json.dumps(dict(edge), sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(dict(edge))
    return result


def scope_id(topic_id: str, scope_type: str, value: str) -> str:
    return f"scope::{scope_type}::{safe_part(topic_id)}::{safe_part(value)}"


def scope_node(topic_id: str, scope_type: str, value: str) -> Dict[str, Any]:
    return {
        "node_type": "Entity/Scope", "scope_id": scope_id(topic_id, scope_type, value),
        "topic_id": topic_id, "scope_type": scope_type, "label": value, "value": value, "role": "scope",
    }


def subject_scope_id(topic_id: str, subject_key: str) -> str:
    return scope_id(topic_id, "entity", subject_key)


def time_id(topic_id: str, time_role: str, value: str) -> str:
    return f"time::{safe_part(topic_id)}::{safe_part(time_role)}::{short_hash(value)}"


def add_time_node(nodes: Dict[str, Dict[str, Any]], topic_id: str, role: str, value: str) -> str:
    identifier = time_id(topic_id, role, value)
    add_node(nodes, {"node_type": "Time", "time_id": identifier, "topic_id": topic_id, "time_role": role, "value": value})
    return identifier


def infer_facet(text: str) -> str:
    lowered = text.lower()
    for facet in sorted(STATE_FACETS):
        if facet.replace("_", " ") in lowered:
            return facet
    if "due" in lowered:
        return "deadline"
    if "responsible" in lowered:
        return "owner"
    return "status"


def infer_subject(text: str, event: EverMemEvent) -> str:
    match = re.match(r"\s*([A-Z][A-Za-z0-9 _-]{1,80}?)\s+(?:is|are|has|have|will|should|must)\b", text)
    return " ".join(match.group(1).split()) if match else (event.speaker or event.group)


def heuristic_claims(event: EverMemEvent, limit: int) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for sentence in (" ".join(part.split()) for part in SENTENCE_SPLIT_RE.split(event.text) if part.strip()):
        if not STATEFUL_RE.search(sentence):
            continue
        facet = infer_facet(sentence)
        claims.append(
            normalize_claim(
                event,
                {
                    "subject": infer_subject(sentence, event), "predicate": facet,
                    "facet_key": facet, "value": sentence, "object": sentence,
                    "time_role": "updated_at" if UPDATE_RE.search(sentence) else "mentioned_at",
                    "confidence": 0.6,
                },
                len(claims) + 1,
                "heuristic_sentence_v2",
            )
        )
        if len(claims) >= limit:
            break
    return claims


def normalize_claim(
    event: EverMemEvent,
    raw: Mapping[str, Any],
    claim_number: int,
    extraction_method: str,
) -> Dict[str, Any]:
    subject = " ".join(str(raw.get("subject") or event.speaker or event.group).split())
    facet = normalized_component(raw.get("facet_key") or raw.get("predicate") or "state") or "state"
    predicate = normalized_component(raw.get("predicate") or facet) or facet
    value = " ".join(str(raw.get("value") or raw.get("object") or "").split())
    subject_key = normalized_component(subject)
    state_target = normalized_component(raw.get("state_target") or predicate) or predicate
    return {
        "node_type": "Claim",
        "claim_id": f"claim::{event.event_id}::{claim_number}",
        "topic_id": event.topic_id,
        "source_event_id": event.event_id,
        "scope_id": scope_id(event.topic_id, "group", event.group),
        "subject": subject,
        "canonical_subject": subject,
        "subject_key": subject_key,
        "predicate": predicate,
        "object": value,
        "facet_key": facet,
        "state_domain": facet,
        "state_target": state_target,
        "state_dimension": f"{facet}:{state_target}",
        "slot_type": "single",
        "value": value[:1000],
        "confidence": float(raw.get("confidence") or 0.0),
        "time_role": str(raw.get("time_role") or "mentioned_at"),
        "time_value": str(raw.get("time_value") or ""),
        "event_sort_key": list(event.sort_key),
        "extraction_method": extraction_method,
    }


def claim_prompt(topic_id: str, events: Sequence[EverMemEvent], limit: int) -> str:
    return json.dumps(
        {
            "stage": "shared_sts_v2_claim_extraction",
            "topic_id": topic_id,
            "visible_events": [event.visible_event() for event in events],
            "task": "Extract atomic durable state Claims only. Do not use QA, answers, options, task labels, or gold evidence.",
            "max_claims_per_event": limit,
            "fields": ["event_id", "subject", "predicate", "facet_key", "state_target", "value", "time_role", "time_value", "confidence"],
        },
        ensure_ascii=False,
        indent=2,
    )


def extract_llm_claims(
    client: LLMClient,
    topic_id: str,
    events: Sequence[EverMemEvent],
    chunk_size: int,
    limit: int,
    workers: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    chunks = [events[index:index + chunk_size] for index in range(0, len(events), chunk_size)]

    def run(index: int, chunk: Sequence[EverMemEvent]) -> Tuple[int, List[Dict[str, Any]], Dict[str, Any]]:
        raw = client.complete_json(
            "Extract shared Scope-Time-State v2 Claims from visible dialogue. Output JSON only.",
            claim_prompt(topic_id, chunk, limit),
        )
        by_id = {event.event_id: event for event in chunk}
        counts: DefaultDict[str, int] = defaultdict(int)
        accepted: List[Dict[str, Any]] = []
        dropped = 0
        for item in raw.get("claims", []) if isinstance(raw.get("claims"), list) else []:
            if not isinstance(item, dict):
                dropped += 1
                continue
            event = by_id.get(str(item.get("event_id") or ""))
            if event is None or counts[event.event_id] >= limit:
                dropped += 1
                continue
            value = " ".join(str(item.get("value") or item.get("object") or "").split())
            if not value:
                dropped += 1
                continue
            counts[event.event_id] += 1
            accepted.append(normalize_claim(event, item, counts[event.event_id], "llm_shared_sts_v2"))
        return index, accepted, {"chunk_index": index, "accepted_claim_count": len(accepted), "dropped_count": dropped}

    results: Dict[int, Tuple[List[Dict[str, Any]], Dict[str, Any]]] = {}
    if workers <= 1:
        for index, chunk in enumerate(chunks, 1):
            _, claims, validation = run(index, chunk)
            results[index] = (claims, validation)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run, index, chunk): index for index, chunk in enumerate(chunks, 1)}
            for future in as_completed(futures):
                index, claims, validation = future.result()
                results[index] = (claims, validation)
    claims: List[Dict[str, Any]] = []
    validations: List[Dict[str, Any]] = []
    for index in sorted(results):
        claims.extend(results[index][0])
        validations.append(results[index][1])
    return claims, validations


def materialize_events(
    events: Sequence[EverMemEvent],
    claims: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    claims_by_event: DefaultDict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for claim in claims:
        claims_by_event[str(claim.get("source_event_id") or "")].append(claim)
    for event in events:
        add_node(nodes, event.visible_event())
        for scope_type, value in (("project", event.topic_id), ("group", event.group), ("person", event.speaker)):
            scope = scope_node(event.topic_id, scope_type, value)
            add_node(nodes, scope)
            add_edge(edges, "IN_SCOPE", event.event_id, node_id(scope), reason=f"source {scope_type} scope")
        add_edge(edges, "MENTIONS", event.event_id, scope_id(event.topic_id, "person", event.speaker), reason="speaker")
        occurred = add_time_node(nodes, event.topic_id, "occurred_at", event.occurred_at)
        add_edge(edges, "OCCURRED_AT", event.event_id, occurred, reason="visible source timestamp")
        for claim in claims_by_event[event.event_id]:
            add_node(nodes, claim)
            add_edge(edges, "ASSERTS", event.event_id, str(claim["claim_id"]), reason=str(claim["extraction_method"]))
            subject_scope = scope_node(event.topic_id, "entity", str(claim["subject_key"]))
            add_node(nodes, subject_scope)
            add_edge(edges, "MENTIONS", event.event_id, node_id(subject_scope), reason="Claim subject")
            time_value = str(claim.get("time_value") or "")
            if time_value:
                claim_time = add_time_node(nodes, event.topic_id, str(claim.get("time_role") or "mentioned_at"), time_value)
                add_edge(edges, "HAS_TIME", str(claim["claim_id"]), claim_time, time_role=claim.get("time_role"), source_event_id=event.event_id)
    return nodes, edges


def merge_decider(
    resolver_mode: str,
    client: Optional[LLMClient],
) -> Any:
    def decide(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
        evidence = [str(existing.get("source_event_id") or ""), str(incoming.get("source_event_id") or "")]
        old_value = " ".join(str(existing.get("value") or "").lower().split())
        new_value = " ".join(str(incoming.get("value") or "").lower().split())
        if resolver_mode != "llm":
            if old_value == new_value:
                return {"decision": "COMPATIBLE", "winner": "none", "reason": "same normalized value", "evidence_event_ids": evidence}
            return {"decision": "SUPERSEDES", "winner": "incoming", "reason": "later visible Claim updates the stable state dimension", "evidence_event_ids": evidence}
        if client is None:
            raise ValueError("resolver_mode=llm requires an LLM client")
        raw = client.complete_json(
            "Resolve two Claims in one STS v2 state dimension. Use only the endpoints. Output JSON only.",
            json.dumps(
                {
                    "existing": dict(existing), "incoming": dict(incoming),
                    "allowed_decisions": sorted(STATE_MERGE_DECISIONS),
                    "output": {"decision": "...", "winner": "incoming|none", "reason": "...", "evidence_event_ids": evidence},
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        result = dict(raw)
        decision = str(result.get("decision") or "").upper()
        result["winner"] = "incoming" if decision in {"SUPERSEDES", "CORRECTS"} else "none"
        result["evidence_event_ids"] = evidence
        return result
    return decide


def materialize_state_facets(
    topic_id: str,
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    claims: Sequence[Dict[str, Any]],
    events_by_id: Mapping[str, EverMemEvent],
    resolver_mode: str,
    client: Optional[LLMClient],
    candidate_limit: int,
) -> List[Dict[str, Any]]:
    adapter = StateMergeAdapter(
        eligible=lambda claim: bool(claim.get("subject_key") and claim.get("state_dimension")),
        owner_key=lambda claim: str(claim.get("subject_key") or ""),
        domain_key=lambda claim: str(claim.get("state_domain") or ""),
        dimension_key=lambda claim: str(claim.get("state_dimension") or ""),
        chronology_key=lambda claim: tuple(claim.get("event_sort_key") or ()),
        lifecycle_winner_is_valid=lambda _old, _new, winner: winner == "incoming",
    )
    clusters, relations = fold_state_claims(claims, adapter, merge_decider(resolver_mode, client), candidate_limit=candidate_limit)
    claims_by_id = {str(claim["claim_id"]): claim for claim in claims}
    facets: List[Dict[str, Any]] = []
    for cluster in clusters:
        primary_id = str(cluster["primary_claim_id"])
        support_ids = list(dict.fromkeys(str(value) for value in cluster["support_claim_ids"]))
        if primary_id not in support_ids:
            raise ValueError(f"StateFacet primary Claim missing from support: {primary_id}")
        primary = claims_by_id[primary_id]
        event = events_by_id[str(primary["source_event_id"])]
        support_events = list(dict.fromkeys(str(claims_by_id[value]["source_event_id"]) for value in support_ids))
        facet_id = f"state::{safe_part(topic_id)}::v2::{short_hash('|'.join((str(cluster['owner_key']), str(cluster['dimension_key']), primary_id)), 16)}"
        owner_scope = subject_scope_id(topic_id, str(cluster["owner_key"]))
        facet = {
            "node_type": "StateFacet", "facet_id": facet_id, "topic_id": topic_id,
            "subject": primary["canonical_subject"], "canonical_subject": primary["canonical_subject"],
            "subject_key": cluster["owner_key"], "facet_key": primary["facet_key"],
            "state_domain": cluster["domain_key"], "state_target": primary["state_target"],
            "state_dimension": cluster["dimension_key"], "slot_type": primary["slot_type"],
            "value": primary["value"], "status": cluster["status"],
            "primary_claim_id": primary_id, "support_claim_ids": support_ids,
            "support_event_ids": support_events, "current_after": event.occurred_at,
            "reported_at": event.occurred_at, "scope_ids": [primary["scope_id"], owner_scope],
        }
        add_node(nodes, facet)
        facets.append(facet)
        for claim_id in support_ids:
            add_edge(edges, "SUPPORTS", claim_id, facet_id, reason="v2 folded state support")
        current_after = add_time_node(nodes, topic_id, "current_after", event.occurred_at)
        add_edge(edges, "CURRENT_AFTER", facet_id, current_after, reason="primary Claim report time")
        for scope in facet["scope_ids"]:
            add_edge(edges, "CURRENT_STATE_OF", facet_id, scope, reason="stable state identity")
    for relation in relations:
        add_edge(edges, str(relation["type"]), str(relation["from"]), str(relation["to"]), reason=relation["reason"], evidence_event_ids=relation["evidence_event_ids"])
    return facets


def validate_graph(nodes: Mapping[str, Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> List[str]:
    warnings: List[str] = []
    node_types = {identifier: str(node.get("node_type") or "") for identifier, node in nodes.items()}
    forbidden = {"qa", "answer", "options", "gold", "evidence", "task_label"}
    for identifier, node in nodes.items():
        if node_types[identifier] not in NODE_TYPES:
            warnings.append(f"unsupported_node_type:{identifier}:{node_types[identifier]}")
        leaked = sorted(forbidden & set(node))
        if leaked:
            warnings.append(f"forbidden_gold_field:{identifier}:{','.join(leaked)}")
        if node_types[identifier] == "StateFacet":
            primary = str(node.get("primary_claim_id") or "")
            supports = [str(value) for value in node.get("support_claim_ids", [])]
            if not primary or primary not in supports:
                warnings.append(f"invalid_state_primary:{identifier}")
    for index, edge in enumerate(edges):
        edge_type = str(edge.get("type") or "")
        source, target = str(edge.get("from") or ""), str(edge.get("to") or "")
        if edge_type not in EDGE_TYPES:
            warnings.append(f"unsupported_edge_type:{index}:{edge_type}")
            continue
        if source not in node_types or target not in node_types:
            warnings.append(f"edge_missing_endpoint:{index}:{edge_type}:{source}->{target}")
            continue
        if (node_types[source], node_types[target]) != EDGE_ENDPOINT_TYPES[edge_type]:
            warnings.append(f"edge_endpoint_type_mismatch:{index}:{edge_type}:{node_types[source]}->{node_types[target]}")
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
    del runtime, resolver_workers
    if resolver_bucket_limit:
        raise ValueError("resolver_bucket_limit is removed; the shared v2 fold never truncates state buckets")
    events = load_topic_events(topic_id, data_root, event_limit=event_limit)
    selected_events = events if llm_event_filter == "all" else [event for event in events if STATEFUL_RE.search(event.text)]
    validations: List[Dict[str, Any]] = []
    if claim_mode == "llm":
        if client is None:
            raise ValueError("claim_mode=llm requires an LLM client")
        claims, validations = extract_llm_claims(client, topic_id, selected_events, message_chunk_size, max_claims_per_event, claim_workers)
    elif claim_mode == "heuristic":
        claims = [claim for event in events for claim in heuristic_claims(event, max_claims_per_event)]
    else:
        claims = []
    nodes, edges = materialize_events(events, claims)
    facets = materialize_state_facets(topic_id, nodes, edges, claims, {event.event_id: event for event in events}, resolver_mode, client, resolver_candidate_limit) if claims else []
    edges = dedupe_edges(edges)
    warnings = validate_graph(nodes, edges)
    if warnings:
        raise ValueError(f"unified STS v2 graph validation failed: {warnings[:10]}")
    node_rows = sorted(nodes.values(), key=lambda item: (str(item.get("node_type") or ""), node_id(item)))
    edge_rows = sorted(edges, key=lambda item: (str(item.get("type") or ""), str(item.get("from") or ""), str(item.get("to") or "")))
    summary = {
        "topic_id": topic_id, "event_count": len(events), "claim_count": len(claims),
        "state_facet_count": len(facets), "node_count": len(node_rows), "edge_count": len(edge_rows),
        "node_counts": dict(Counter(str(node.get("node_type") or "") for node in node_rows)),
        "edge_counts": dict(Counter(str(edge.get("type") or "") for edge in edge_rows)),
        "claim_facets": dict(Counter(str(claim.get("facet_key") or "") for claim in claims)),
        "claim_extraction_methods": dict(Counter(str(claim.get("extraction_method") or "") for claim in claims)),
        "llm_claim_extraction_chunks": len(validations),
        "llm_claim_extraction_accepted": sum(int(row.get("accepted_claim_count", 0)) for row in validations),
        "warnings": warnings,
    }
    dialogue_path = data_root / topic_id / "dialogue.json"
    manifest = {
        "benchmark": "EverMemBench", "dataset": "evermembench", "topic_id": topic_id,
        "schema_version": SCHEMA_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files": [str(dialogue_path)],
        "input_provenance": {"dialogue_sha256": file_sha256(dialogue_path)},
        "leakage_policy": {
            "graph_build_inputs": ["dialogue.json"], "qa_loaded": False,
            "gold_fields_loaded": [], "gold_fields_used": [],
            "notes": "The shared v2 adapter reads dialogue.json only and never opens qa_*.json.",
        },
        "claim_mode": claim_mode, "resolver_mode": resolver_mode, "provider": provider, "model": model,
        "message_chunk_size": message_chunk_size, "max_claims_per_event": max_claims_per_event,
        "claim_workers": claim_workers, "resolver_candidate_limit": resolver_candidate_limit,
        "event_limit": event_limit, "node_types": list(NODE_TYPES), "edge_types": list(EDGE_TYPES),
        "edge_endpoint_types": {key: list(value) for key, value in EDGE_ENDPOINT_TYPES.items()},
        "state_resolution": {
            "mode": "ordered_state_fold", "owner_key": "subject_key",
            "dimension_key": "state_dimension", "pair_decisions": sorted(STATE_MERGE_DECISIONS),
            "candidate_limit_policy": "fail_never_truncate",
        },
        "summary": summary,
    }
    return {"manifest": manifest, "summary": summary, "nodes": node_rows, "edges": edge_rows, "events": [asdict(event) for event in events]}


def write_topic_graph(output_dir: Path, topic_id: str, graph: Mapping[str, Any]) -> Path:
    topic_dir = output_dir / safe_part(topic_id)
    if topic_dir.exists():
        manifest_path = topic_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"refusing to replace graph without manifest: {topic_dir}")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(existing.get("schema_version") or "") != SCHEMA_VERSION:
            raise ValueError(f"refusing to replace incompatible graph schema at {topic_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{safe_part(topic_id)}.tmp-", dir=output_dir))
    backup: Optional[Path] = None
    try:
        (temporary / "manifest.json").write_text(json_dump(graph["manifest"]), encoding="utf-8")
        (temporary / "graph_summary.json").write_text(json_dump(graph["summary"]), encoding="utf-8")
        write_jsonl(temporary / "nodes.jsonl", graph["nodes"])
        write_jsonl(temporary / "edges.jsonl", graph["edges"])
        if topic_dir.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{safe_part(topic_id)}.backup-", dir=output_dir))
            backup.rmdir()
            topic_dir.rename(backup)
        temporary.rename(topic_dir)
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if backup is not None and backup.exists() and not topic_dir.exists():
            backup.rename(topic_dir)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return topic_dir


def main() -> int:
    args = parse_args()
    client: Optional[LLMClient] = None
    runtime: Optional[LLMRuntimeConfig] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    if args.claim_mode == "llm" or args.resolver_mode == "llm":
        load_dotenv()
        os.environ["LLM_MAX_TOKENS"] = str(args.max_tokens)
        api_key, model, api_base = provider_config(args.provider)
        model = args.model or model
        provider = args.provider
        client = LLMClient(provider=args.provider, model=model, api_key=api_key, api_base=api_base, cache_path=Path(args.cache), use_cache=not args.no_cache)
        runtime = LLMRuntimeConfig(args.provider, model, api_key, api_base, Path(args.cache), not args.no_cache)
    try:
        graph = build_topic_graph(
            args.topic, Path(args.data_root), args.claim_mode, args.resolver_mode,
            args.max_claims_per_event, args.event_limit, client, runtime, provider, model,
            args.message_chunk_size, args.llm_event_filter, args.claim_workers,
            args.resolver_candidate_limit, args.resolver_bucket_limit, args.resolver_workers,
        )
        topic_dir = write_topic_graph(Path(args.output_dir), args.topic, graph)
    except (LLMRequestError, ValueError) as exc:
        print(f"EverMemBench unified STS v2 build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(graph["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {topic_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

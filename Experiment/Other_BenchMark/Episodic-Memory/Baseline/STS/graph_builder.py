"""EPBench extraction and Scope-Time-State v2 graph materialization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping, Protocol, Sequence

from pipeline.external.state_merge import STATE_MERGE_DECISIONS, StateMergeAdapter, fold_state_claims
from pipeline.external.sts_v2.schema import EDGE_ENDPOINT_TYPES, NODE_TYPES, SCHEMA_VERSION
from pipeline.external.temporal_grounding import parse_anchor_datetime

from .config import MAX_CLAIMS_PER_CHAPTER, MESSAGE_CHUNK_SIZE, RESOLVER_CANDIDATE_LIMIT
from .loader import Chapter


ALLOWED_CLAIM_PREDICATES = {
    "episodic_action",
    "lives_in",
    "works_at",
    "member_of",
    "has_status",
    "prefers",
}
SCOPE_FIELDS = {
    "locations": "location",
    "entities": "entity",
    "event_types": "event_type",
}


class JsonClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Mapping[str, Any]: ...


def _compact(text: object) -> str:
    return " ".join(str(text or "").split())


def _stable_id(prefix: str, *parts: object) -> str:
    normalized = "\x1f".join(_compact(part).casefold() for part in parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}::{digest}"


def require_span(chapter: Chapter, span: object) -> str:
    evidence = _compact(span)
    source = _compact(chapter.text)
    if not evidence or evidence.casefold() not in source.casefold():
        raise ValueError(f"chapter {chapter.chapter_id}: evidence_span not found")
    return evidence


def _normalize_mentions(chapter: Chapter, raw: object, *, allow_role: bool) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"chapter {chapter.chapter_id}: extraction field must be a list")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError(f"chapter {chapter.chapter_id}: extraction item must be an object")
        value = _compact(item.get("value"))
        evidence = require_span(chapter, item.get("evidence_span"))
        if not value:
            raise ValueError(f"chapter {chapter.chapter_id}: extraction value is empty")
        role = _compact(item.get("role")) if allow_role else ""
        key = (value.casefold(), role.casefold())
        if key in seen:
            continue
        seen.add(key)
        row = {"value": value, "evidence_span": evidence}
        if allow_role:
            row["role"] = role or "mentioned"
        rows.append(row)
    return rows


def normalize_extraction(
    chapter: Chapter,
    raw: Mapping[str, Any],
    *,
    max_claims_per_chapter: int = MAX_CLAIMS_PER_CHAPTER,
) -> dict[str, Any]:
    if int(raw.get("chapter_id", -1)) != chapter.chapter_id:
        raise ValueError(f"chapter {chapter.chapter_id}: response chapter_id mismatch")
    summary = _compact(raw.get("concise_summary"))
    if not summary:
        raise ValueError(f"chapter {chapter.chapter_id}: concise_summary is empty")
    record: dict[str, Any] = {
        "chapter_id": chapter.chapter_id,
        "concise_summary": summary,
        "dates": _normalize_mentions(chapter, raw.get("dates"), allow_role=False),
        "locations": _normalize_mentions(chapter, raw.get("locations"), allow_role=False),
        "entities": _normalize_mentions(chapter, raw.get("entities"), allow_role=True),
        "event_types": _normalize_mentions(chapter, raw.get("event_types"), allow_role=False),
        "claims": [],
    }
    raw_claims = raw.get("claims")
    if not isinstance(raw_claims, list):
        raise ValueError(f"chapter {chapter.chapter_id}: claims must be a list")
    if len(raw_claims) > max_claims_per_chapter:
        raise ValueError(f"chapter {chapter.chapter_id}: too many claims")
    for claim in raw_claims:
        if not isinstance(claim, Mapping):
            raise ValueError(f"chapter {chapter.chapter_id}: claim must be an object")
        predicate = _compact(claim.get("predicate")).lower()
        if predicate not in ALLOWED_CLAIM_PREDICATES:
            raise ValueError(f"chapter {chapter.chapter_id}: unsupported claim predicate {predicate!r}")
        subject = _compact(claim.get("subject"))
        value = _compact(claim.get("value"))
        if not subject or not value:
            raise ValueError(f"chapter {chapter.chapter_id}: claim subject/value is empty")
        record["claims"].append(
            {
                "subject": subject,
                "predicate": predicate,
                "value": value,
                "evidence_span": require_span(chapter, claim.get("evidence_span")),
            }
        )
    return record


EXTRACTION_SYSTEM_PROMPT = """Extract EPBench chapters into this exact STS v2 JSON shape:
{
  "chapters": [{
    "chapter_id": 1,
    "concise_summary": "short chapter summary",
    "dates": [{"value": "date", "evidence_span": "exact source substring"}],
    "locations": [{"value": "place", "evidence_span": "exact source substring"}],
    "entities": [{"value": "entity", "role": "primary|participant|organization|mentioned", "evidence_span": "exact source substring"}],
    "event_types": [{"value": "event type", "evidence_span": "exact source substring"}],
    "claims": [{"subject": "entity", "predicate": "allowed predicate", "value": "atomic value", "evidence_span": "exact source substring"}]
  }]
}
Return exactly one object per visible chapter_id. Never return bare strings inside these lists.
Never rename value to name or omit subject/value from a Claim. Every evidence_span must be copied
verbatim from its own chapter. Allowed Claim predicates are episodic_action, lives_in, works_at,
member_of, has_status, and prefers. Use [] when no grounded item exists. Do not infer unstated facts."""


def _extract_chunk(
    chapters: Sequence[Chapter],
    client: JsonClient,
    max_claims_per_chapter: int,
) -> list[dict[str, Any]]:
    visible = "\n\n".join(f"<chapter id={row.chapter_id}>\n{row.text}\n</chapter>" for row in chapters)
    prompt = f"Maximum claims per chapter: {max_claims_per_chapter}.\n\n{visible}"
    last_error: Exception | None = None
    for attempt in range(2):
        user_prompt = prompt if attempt == 0 else f"Repair the prior invalid response. {last_error}\n\n{prompt}"
        raw = client.complete_json(EXTRACTION_SYSTEM_PROMPT, user_prompt)
        try:
            rows = raw.get("chapters")
            if not isinstance(rows, list):
                raise ValueError("response chapters must be a list")
            by_id: dict[int, Mapping[str, Any]] = {}
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("response chapter must be an object")
                chapter_id = int(row.get("chapter_id", -1))
                if chapter_id in by_id:
                    raise ValueError(f"duplicate response chapter_id {chapter_id}")
                by_id[chapter_id] = row
            expected = [chapter.chapter_id for chapter in chapters]
            if sorted(by_id) != sorted(expected):
                raise ValueError(f"response chapter IDs must be exactly {expected}")
            return [
                normalize_extraction(chapter, by_id[chapter.chapter_id], max_claims_per_chapter=max_claims_per_chapter)
                for chapter in chapters
            ]
        except (TypeError, ValueError) as exc:
            last_error = exc
    raise ValueError(f"invalid extraction after one repair: {last_error}")


def extract_chapter_records(
    chapters: Sequence[Chapter],
    client: JsonClient,
    message_chunk_size: int = MESSAGE_CHUNK_SIZE,
    max_claims_per_chapter: int = MAX_CLAIMS_PER_CHAPTER,
    workers: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if message_chunk_size < 1 or workers < 1:
        raise ValueError("message_chunk_size and workers must be positive")
    chunks = [list(chapters[start : start + message_chunk_size]) for start in range(0, len(chapters), message_chunk_size)]
    if workers == 1:
        groups = [_extract_chunk(chunk, client, max_claims_per_chapter) for chunk in chunks]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            groups = list(executor.map(lambda chunk: _extract_chunk(chunk, client, max_claims_per_chapter), chunks))
    records = [record for group in groups for record in group]
    traces = [{"chapter_id": row["chapter_id"], "status": "extracted"} for row in records]
    return records, traces


def compact_event_card(record: Mapping[str, Any]) -> str:
    parts = [str(record["concise_summary"])]
    for label, key in (("date", "dates"), ("location", "locations"), ("entity", "entities"), ("event type", "event_types")):
        values = [str(item["value"]) for item in record.get(key, [])]
        if values:
            parts.append(f"{label}: {', '.join(values)}")
    return " | ".join(parts)


def _scope_id(scope_type: str, value: str) -> str:
    return _stable_id("scope", scope_type, value)


def normalized_component(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _compact(value).casefold()).strip("-") or "unknown"


SINGLE_STATE_DIMENSIONS = {
    "lives_in": ("location", "residence"),
    "works_at": ("employment", "primary"),
    "has_status": ("status", "primary"),
}


def eligible_state_identity(claim: Mapping[str, Any]) -> dict[str, str] | None:
    predicate = str(claim.get("predicate") or "")
    if predicate == "episodic_action":
        return None
    if predicate in SINGLE_STATE_DIMENSIONS:
        domain, target = SINGLE_STATE_DIMENSIONS[predicate]
    elif predicate in {"member_of", "prefers"}:
        domain, target = predicate, normalized_component(claim.get("value"))
    else:
        return None
    return {
        "state_domain": domain,
        "state_target": target,
        "state_dimension": f"{domain}:{target}",
    }


def _base_graph(chapters: Sequence[Chapter], records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    record_by_id = {int(record["chapter_id"]): record for record in records}
    if set(record_by_id) != {chapter.chapter_id for chapter in chapters}:
        raise ValueError("extraction records must cover every supplied chapter exactly once")
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []

    book_scope_id = _scope_id("book", "EPBench Long Book")
    nodes[book_scope_id] = {
        "node_id": book_scope_id,
        "node_type": "Entity/Scope",
        "scope_type": "book",
        "value": "EPBench Long Book",
        "graph_text": "EPBench Long Book",
    }
    for chapter in chapters:
        record = record_by_id[chapter.chapter_id]
        event_id = f"epbench::chapter::{chapter.chapter_id}"
        nodes[event_id] = {
            "node_id": event_id,
            "event_id": event_id,
            "node_type": "Episode/Event",
            "chapter_id": chapter.chapter_id,
            "raw_text": chapter.text,
            "graph_text": compact_event_card(record),
            "event_summary": record["concise_summary"],
        }
        edges.append({"type": "IN_SCOPE", "from": event_id, "to": book_scope_id})

        scope_ids_by_value: dict[str, str] = {}
        for field, scope_type in SCOPE_FIELDS.items():
            for mention in record.get(field, []):
                value = str(mention["value"])
                scope_id = _scope_id(scope_type, value)
                scope_ids_by_value[value.casefold()] = scope_id
                nodes.setdefault(
                    scope_id,
                    {
                        "node_id": scope_id,
                        "node_type": "Entity/Scope",
                        "scope_type": scope_type,
                        "value": value,
                        "graph_text": f"{scope_type}: {value}",
                    },
                )
                edge = {
                    "type": "IN_SCOPE" if scope_type in {"entity", "event_type"} else "MENTIONS",
                    "from": event_id,
                    "to": scope_id,
                    "evidence_span": mention["evidence_span"],
                }
                if scope_type == "entity":
                    edge["role"] = mention.get("role", "mentioned")
                edges.append(edge)

        time_ids: list[str] = []
        for date in record.get("dates", []):
            value = str(date["value"])
            time_id = _stable_id("time", value)
            time_ids.append(time_id)
            nodes.setdefault(
                time_id,
                {
                    "node_id": time_id,
                    "node_type": "Time",
                    "value": value,
                    "graph_text": value,
                },
            )
            edges.append(
                {"type": "OCCURRED_AT", "from": event_id, "to": time_id, "evidence_span": date["evidence_span"]}
            )

        for claim_index, raw_claim in enumerate(record.get("claims", [])):
            claim_id = _stable_id("claim", event_id, claim_index, raw_claim["subject"], raw_claim["predicate"], raw_claim["value"])
            owner_scope_id = scope_ids_by_value.get(str(raw_claim["subject"]).casefold())
            if owner_scope_id is None:
                owner_scope_id = _scope_id("entity", str(raw_claim["subject"]))
                nodes.setdefault(
                    owner_scope_id,
                    {
                        "node_id": owner_scope_id,
                        "node_type": "Entity/Scope",
                        "scope_type": "entity",
                        "value": raw_claim["subject"],
                        "graph_text": f"entity: {raw_claim['subject']}",
                    },
                )
                edges.append({"type": "IN_SCOPE", "from": event_id, "to": owner_scope_id, "role": "claim_subject"})
            claim = {
                "node_id": claim_id,
                "claim_id": claim_id,
                "node_type": "Claim",
                "source_event_id": event_id,
                "chapter_id": chapter.chapter_id,
                "owner_scope_id": owner_scope_id,
                "subject": raw_claim["subject"],
                "predicate": raw_claim["predicate"],
                "value": raw_claim["value"],
                "evidence_span": raw_claim["evidence_span"],
                "graph_text": f"{raw_claim['subject']} {raw_claim['predicate']} {raw_claim['value']}",
                "time_ids": list(time_ids),
            }
            state_identity = eligible_state_identity(claim)
            if state_identity:
                claim.update(state_identity)
            time_value = str(record.get("dates", [{}])[0].get("value") or "") if record.get("dates") else ""
            parsed_time = parse_anchor_datetime(time_value)
            claim["event_sort_key"] = (
                parsed_time.isoformat() if parsed_time else "9999-12-31T23:59:59",
                chapter.chapter_id,
            )
            nodes[claim_id] = claim
            claims.append(claim)
            edges.append({"type": "ASSERTS", "from": event_id, "to": claim_id})
            edges.extend({"type": "HAS_TIME", "from": claim_id, "to": time_id} for time_id in time_ids)
    return list(nodes.values()), edges, claims


def _merge_decider(client: JsonClient | None):
    def decide(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
        evidence = [str(existing["source_event_id"]), str(incoming["source_event_id"])]
        if client is None:
            if _compact(existing.get("value")).casefold() == _compact(incoming.get("value")).casefold():
                return {
                    "decision": "COMPATIBLE",
                    "winner": "none",
                    "reason": "same normalized state value",
                    "evidence_event_ids": evidence,
                }
            return {
                "decision": "SUPERSEDES",
                "winner": "incoming",
                "reason": "later chapter updates the same persistent state dimension",
                "evidence_event_ids": evidence,
            }
        raw = dict(
            client.complete_json(
                "Resolve two endpoint Claims in one STS v2 state dimension. Use only the supplied endpoints and output JSON.",
                json.dumps(
                    {
                        "existing": dict(existing),
                        "incoming": dict(incoming),
                        "allowed_decisions": sorted(STATE_MERGE_DECISIONS),
                        "required_output": {
                            "decision": "allowed decision",
                            "winner": "existing|incoming|none",
                            "reason": "grounded reason",
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        )
        raw["decision"] = _compact(raw.get("decision")).upper()
        if raw["decision"] in {"SUPERSEDES", "CORRECTS"} and raw.get("winner") not in {"existing", "incoming"}:
            raw["winner"] = "incoming"
        if raw["decision"] not in {"SUPERSEDES", "CORRECTS"}:
            raw["winner"] = "none"
        raw["evidence_event_ids"] = evidence
        return raw

    return decide


def materialize_state_facets(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    claims: Sequence[dict[str, Any]],
    clusters: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims_by_id = {str(claim["claim_id"]): claim for claim in claims}
    facets: list[dict[str, Any]] = []
    for cluster in clusters:
        primary_id = str(cluster["primary_claim_id"])
        support_ids = list(dict.fromkeys(str(value) for value in cluster["support_claim_ids"]))
        if primary_id not in support_ids:
            raise ValueError(f"StateFacet primary Claim missing from support: {primary_id}")
        primary = claims_by_id[primary_id]
        facet_id = _stable_id(
            "state",
            cluster["owner_key"],
            cluster["dimension_key"],
            primary_id,
        )
        support_event_ids = list(
            dict.fromkeys(str(claims_by_id[claim_id]["source_event_id"]) for claim_id in support_ids)
        )
        facet = {
            "node_id": facet_id,
            "facet_id": facet_id,
            "node_type": "StateFacet",
            "subject": primary["subject"],
            "state_domain": cluster["domain_key"],
            "state_target": primary["state_target"],
            "state_dimension": cluster["dimension_key"],
            "value": primary["value"],
            "status": cluster["status"],
            "primary_claim_id": primary_id,
            "support_claim_ids": support_ids,
            "support_event_ids": support_event_ids,
            "owner_scope_id": primary["owner_scope_id"],
            "graph_text": f"{primary['subject']} {primary['state_domain']} {primary['value']}",
        }
        nodes[facet_id] = facet
        facets.append(facet)
        edges.extend({"type": "SUPPORTS", "from": claim_id, "to": facet_id} for claim_id in support_ids)
        if primary.get("time_ids"):
            edges.append({"type": "CURRENT_AFTER", "from": facet_id, "to": primary["time_ids"][0]})
        edges.append({"type": "CURRENT_STATE_OF", "from": facet_id, "to": primary["owner_scope_id"]})
    return facets


def validate_graph(
    nodes: Mapping[str, Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]
) -> list[str]:
    warnings: list[str] = []
    node_types = {node_id: str(node.get("node_type") or "") for node_id, node in nodes.items()}
    for node_id, node_type in node_types.items():
        if node_type not in NODE_TYPES:
            warnings.append(f"unsupported_node_type:{node_id}:{node_type}")
    for index, edge in enumerate(edges):
        edge_type = str(edge.get("type") or "")
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        expected = EDGE_ENDPOINT_TYPES.get(edge_type)
        if expected is None:
            warnings.append(f"unsupported_edge_type:{index}:{edge_type}")
        elif source not in node_types or target not in node_types:
            warnings.append(f"edge_missing_endpoint:{index}:{edge_type}:{source}->{target}")
        elif (node_types[source], node_types[target]) != expected:
            warnings.append(
                f"edge_endpoint_type_mismatch:{index}:{edge_type}:{node_types[source]}->{node_types[target]}"
            )
    return warnings


def build_graph(
    chapters: Sequence[Chapter],
    extraction_records: Sequence[Mapping[str, Any]],
    merge_client: JsonClient | None = None,
    resolver_candidate_limit: int = RESOLVER_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    normalized = [
        normalize_extraction(chapter, record)
        for chapter, record in zip(chapters, extraction_records, strict=True)
    ]
    node_rows, edges, claims = _base_graph(chapters, normalized)
    nodes = {str(node["node_id"]): node for node in node_rows}
    adapter = StateMergeAdapter(
        eligible=lambda claim: bool(claim.get("state_dimension")),
        owner_key=lambda claim: str(claim.get("owner_scope_id") or ""),
        domain_key=lambda claim: str(claim.get("state_domain") or ""),
        dimension_key=lambda claim: str(claim.get("state_dimension") or ""),
        chronology_key=lambda claim: tuple(claim.get("event_sort_key") or ()),
        lifecycle_winner_is_valid=lambda old, new, winner: (
            tuple(new.get("event_sort_key") or ()) >= tuple(old.get("event_sort_key") or ())
            if winner == "incoming"
            else tuple(old.get("event_sort_key") or ()) >= tuple(new.get("event_sort_key") or ())
        ),
    )
    clusters, relations = fold_state_claims(
        claims,
        adapter,
        _merge_decider(merge_client),
        candidate_limit=resolver_candidate_limit,
    )
    materialize_state_facets(nodes, edges, claims, clusters)
    for relation in relations:
        if relation["type"] in {"SUPERSEDES", "CORRECTS", "CONFLICTS_WITH"}:
            edges.append(dict(relation))
    warnings = validate_graph(nodes, edges)
    graph = {
        "schema_version": SCHEMA_VERSION,
        "nodes": list(nodes.values()),
        "edges": edges,
        "warnings": warnings,
        "manifest": {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "leakage_policy": {"graph_build_inputs": ["book.json"], "qa_loaded": False},
        },
    }
    graph["manifest"]["summary"] = {
        "node_counts": {
            node_type: sum(node["node_type"] == node_type for node in graph["nodes"])
            for node_type in NODE_TYPES
        },
        "edge_counts": {
            edge_type: sum(edge["type"] == edge_type for edge in graph["edges"])
            for edge_type in EDGE_ENDPOINT_TYPES
        },
        "warnings": list(warnings),
    }
    return graph


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_graph(output_dir: Path, graph: Mapping[str, Any]) -> Path:
    root = Path(output_dir)
    target = root / "book1"
    existing_manifest = target / "manifest.json"
    if existing_manifest.is_file():
        existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        if existing.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("incompatible existing graph manifest")
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".book1-staging-", dir=root))
    backup = root / ".book1-backup"
    try:
        with (staging / "nodes.jsonl").open("w", encoding="utf-8") as handle:
            for node in graph["nodes"]:
                handle.write(json.dumps(node, ensure_ascii=False, separators=(",", ":")) + "\n")
        with (staging / "edges.jsonl").open("w", encoding="utf-8") as handle:
            for edge in graph["edges"]:
                handle.write(json.dumps(edge, ensure_ascii=False, separators=(",", ":")) + "\n")
        _write_json(staging / "manifest.json", graph["manifest"])
        _write_json(
            staging / "graph.json",
            {
                "schema_version": graph["schema_version"],
                "nodes": graph["nodes"],
                "edges": graph["edges"],
                "warnings": graph.get("warnings", []),
            },
        )
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            os.replace(target, backup)
        os.replace(staging, target)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    return target


__all__ = [
    "ALLOWED_CLAIM_PREDICATES",
    "build_graph",
    "compact_event_card",
    "extract_chapter_records",
    "eligible_state_identity",
    "materialize_state_facets",
    "normalize_extraction",
    "require_span",
    "validate_graph",
    "write_graph",
]

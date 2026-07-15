"""EPBench extraction and Scope-Time-State v2 graph materialization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, Sequence

from pipeline.external.sts_v2.schema import SCHEMA_VERSION

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


EXTRACTION_SYSTEM_PROMPT = """Extract an EPBench chapter into the fixed STS v2 JSON contract.
Return {\"chapters\": [...]} with exactly one item per visible chapter_id. Each item must contain
chapter_id, concise_summary, dates, locations, entities, event_types, and claims. Every extracted
item and claim must include a verbatim evidence_span from its own chapter. Entity items also include
role (primary, participant, organization, or mentioned). Claim predicates are restricted to:
episodic_action, lives_in, works_at, member_of, has_status, prefers. Do not infer facts not stated."""


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
            nodes[claim_id] = claim
            claims.append(claim)
            edges.append({"type": "ASSERTS", "from": event_id, "to": claim_id})
            edges.extend({"type": "HAS_TIME", "from": claim_id, "to": time_id} for time_id in time_ids)
    return list(nodes.values()), edges, claims


def build_graph(
    chapters: Sequence[Chapter],
    extraction_records: Sequence[Mapping[str, Any]],
    merge_client: JsonClient | None = None,
    resolver_candidate_limit: int = RESOLVER_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    del merge_client, resolver_candidate_limit
    normalized = [
        normalize_extraction(chapter, record)
        for chapter, record in zip(chapters, extraction_records, strict=True)
    ]
    nodes, edges, _claims = _base_graph(chapters, normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": nodes,
        "edges": edges,
        "warnings": [],
        "manifest": {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "leakage_policy": {"graph_build_inputs": ["book.json"], "qa_loaded": False},
        },
    }


__all__ = [
    "ALLOWED_CLAIM_PREDICATES",
    "build_graph",
    "compact_event_card",
    "extract_chapter_records",
    "normalize_extraction",
    "require_span",
]

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sts.extraction.epbench_event_extractor import (
    EPBenchEventExtractor,
    generate_json,
)
from sts.extraction.state_extractor import StateExtractor
from sts.prompts.epbench_claim_prompts import EPBENCH_CLAIM_EXTRACTION_PROMPT
from sts.prompts.epbench_event_prompts import EPBENCH_EVENT_EXTRACTION_PROMPT
from sts.prompts.epbench_scope_prompts import (
    EPBENCH_EVENT_ROLE_WEIGHT_PROMPT,
    EPBENCH_SCOPE_CREATE_PROMPT,
    EPBENCH_SCOPE_MATCH_PROMPT,
    EPBENCH_SCOPE_UPDATE_PROMPT,
)
from sts.prompts.state_prompt import STATE_CHRONOLOGICAL_SUMMARY_PROMPT
from sts.state.builder import StateThreadBuilder
from sts.state.config import StateThreadConfig
from sts.state.embedding_adapter import CachedEmbeddingService
from sts.state.persistence import attach_states
from sts.adapters.epbench.scope_retriever import (
    FEATURE_VERSION as SCOPE_RETRIEVAL_FEATURE_VERSION,
    ScopeEmbeddingRetriever,
    event_theme_text,
)
from sts.graph.schema import (
    EventClaimRelation,
    ClaimNode,
    ScopeEventRelation,
    EventNode,
    STSGraph,
    ScopeNode,
)
from sts.graph.types import Claim, Event, RawDataType, Scope
from sts.config import ExperimentConfig
from sts.utils.datetime_utils import from_iso_format

from .loader import load_book_chapters


SCHEMA_VERSION = "sts_epbench_v1"
CLAIM_TYPES = {"event", "time", "location", "entity", "detail", "relation", "causal"}
EVENT_ROLES = {
    "initiating", "developing", "climax", "concluding", "recurring",
    "background", "key_moment", "transition",
}
SCOPE_TYPES = {"event_thread", "recurring_activity", "shared_situation"}


def _status(message: str) -> None:
    print(f"[STS-EPBench] {message}", flush=True)


def _progress(stage: str, completed: int, total: int, message: str = "") -> None:
    percent = 100.0 if total == 0 else completed * 100.0 / total
    suffix = f" | {message}" if message else ""
    _status(f"{stage}: {completed}/{total} ({percent:.1f}%){suffix}")


def _required_text(output: dict, field: str) -> str:
    value = output.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Scope output requires non-empty {field}")
    return value.strip()


def _required_string_list(output: dict, field: str) -> list[str]:
    value = output.get(field)
    if not isinstance(value, list):
        raise ValueError(f"Scope output field {field} must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _required_scope_type(output: dict) -> str:
    value = output.get("scope_type")
    if value not in SCOPE_TYPES:
        raise ValueError(f"Unsupported scope_type: {value!r}")
    return value


@dataclass(frozen=True)
class WeakEventScopeRelation:
    event_id: str
    scope_id: str
    weight: float


@dataclass
class LowWeightRepoolStats:
    threshold: float
    weak_relations: int = 0
    detached_relations: int = 0
    rematched_relations: int = 0
    created_scopes: int = 0
    retained_elsewhere: int = 0
    deleted_empty_scopes: int = 0


@dataclass
class ScopeBuildResult:
    scopes: list[Scope]
    roles: dict[str, dict[str, str]]
    weights: dict[str, dict[str, float]]
    repool_stats: LowWeightRepoolStats


def _accumulate_repool_stats(
    total: LowWeightRepoolStats,
    update: LowWeightRepoolStats,
) -> None:
    for field in (
        "weak_relations",
        "detached_relations",
        "rematched_relations",
        "created_scopes",
        "retained_elsewhere",
        "deleted_empty_scopes",
    ):
        setattr(total, field, getattr(total, field) + getattr(update, field))


def collect_weak_event_scope_relations(
    scopes: list[Scope],
    weights: dict[str, dict[str, float]],
    threshold: float,
) -> list[WeakEventScopeRelation]:
    weak = []
    for scope in scopes:
        scope_weights = weights.get(scope.scope_id)
        if scope_weights is None:
            raise RuntimeError(f"Missing Event weights for Scope {scope.scope_id}")
        if set(scope.event_ids) != set(scope_weights):
            raise RuntimeError(
                f"Scope/weight membership mismatch for {scope.scope_id}"
            )
        for event_id in scope.event_ids:
            weight = float(scope_weights[event_id])
            if weight < threshold:
                weak.append(
                    WeakEventScopeRelation(event_id, scope.scope_id, weight)
                )
    return weak


def validate_event_scope_integrity(
    scopes: list[Scope],
    roles: dict[str, dict[str, str]],
    weights: dict[str, dict[str, float]],
    event_ids: list[str],
) -> None:
    memberships = {event_id: 0 for event_id in event_ids}
    for scope in scopes:
        expected = set(scope.event_ids)
        if expected != set(roles.get(scope.scope_id, {})):
            raise RuntimeError(f"Scope/role membership mismatch for {scope.scope_id}")
        if expected != set(weights.get(scope.scope_id, {})):
            raise RuntimeError(f"Scope/weight membership mismatch for {scope.scope_id}")
        for event_id in expected:
            if event_id not in memberships:
                raise RuntimeError(
                    f"Scope {scope.scope_id} references unknown Event {event_id}"
                )
            memberships[event_id] += 1
    orphaned = [event_id for event_id, count in memberships.items() if count == 0]
    if orphaned:
        raise RuntimeError(f"Low-weight repool orphaned Events: {orphaned}")


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _event_from_dict(data: dict) -> Event:
    timestamp = from_iso_format(data["timestamp"]) if data.get("timestamp") else None
    raw_type = data.get("type")
    return Event(
        event_id=data["event_id"],
        user_id_list=data.get("user_id_list", []),
        original_data=data["original_data"],
        timestamp=timestamp,
        summary=data["summary"],
        participants=data.get("participants", []),
        type=RawDataType(raw_type) if raw_type else None,
        keywords=data.get("keywords", []),
        subject=data.get("subject"),
        event_description=data.get("event_description"),
        book_id=data.get("book_id"),
        chapter_idx=data.get("chapter_idx"),
        event_time_text=data.get("event_time_text"),
        entities=data.get("entities", []),
        locations=data.get("locations", []),
        event_type=data.get("event_type"),
        extraction_confidence=data.get("extraction_confidence", 0.8),
        metadata=data.get("metadata", {}),
    )


def _scope_from_dict(data: dict) -> Scope:
    def parse(value):
        return from_iso_format(value) if value else None

    return Scope(
        scope_id=data["scope_id"],
        title=data["title"],
        summary=data["summary"],
        event_ids=data["event_ids"],
        timestamp=parse(data.get("timestamp")),
        user_id_list=data.get("user_id_list", []),
        participants=data.get("participants", []),
        keywords=data.get("keywords", []),
        key_entities=data.get("key_entities", []),
        key_locations=data.get("key_locations", []),
        event_types=data.get("event_types", []),
        time_start=parse(data.get("time_start")),
        time_end=parse(data.get("time_end")),
        scope_type=data.get("scope_type"),
        metadata=data.get("metadata", {}),
    )


def _claim_from_dict(data: dict) -> Claim:
    return Claim(
        claim_id=data["claim_id"],
        content=data["content"],
        event_ids=data["event_ids"],
        scope_id=data["scope_id"],
        state_id=data.get("state_id"),
        confidence=data.get("confidence", 0.8),
        temporal=data.get("temporal"),
        spatial=data.get("spatial"),
        keywords=data.get("keywords", []),
        query_patterns=data.get("query_patterns", []),
        timestamp=from_iso_format(data["timestamp"]) if data.get("timestamp") else None,
        claim_type=data.get("claim_type"),
        entities=data.get("entities", []),
        evidence=data.get("evidence"),
        metadata=data.get("metadata", {}),
    )


class _AsyncEmbeddingBridge:
    """Expose EPBench's async embedding client to the synchronous STS builder."""

    def __init__(self, provider, loop: asyncio.AbstractEventLoop):
        self.provider = provider
        self.loop = loop
        self.model_name = str(provider.model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        future = asyncio.run_coroutine_threadsafe(
            self.provider.embed(texts),
            self.loop,
        )
        return future.result()


def _build_state_payload(
    claims: list[Claim],
    events: list[Event],
    embedding_backend,
    cache_path: Path,
) -> dict:
    builder = StateThreadBuilder(
        CachedEmbeddingService(embedding_backend, cache_path),
        StateThreadConfig(min_claim_confidence=0.0),
    )
    events_by_id = {event.event_id: event for event in events}
    claims_by_scope: dict[str, list[Claim]] = {}
    for claim in claims:
        claims_by_scope.setdefault(claim.scope_id, []).append(claim)
    scope_results = [
        builder.build_scope(scope_id, scope_claims, events_by_id)
        for scope_id, scope_claims in sorted(claims_by_scope.items())
    ]
    assignments = {
        claim.claim_id: claim.state_id
        for claim in claims
    }
    payload = {
        "schema_version": "sts-state-build-v1",
        "embedding_model": embedding_backend.model_name,
        "config": builder.config.to_dict(),
        "scope_results": [result.to_dict() for result in scope_results],
        "claim_state_assignments": assignments,
        "summary": {
            "scope_count": len(scope_results),
            "input_claim_count": len(claims),
            "state_count": sum(
                len(result.states) for result in scope_results
            ),
            "assigned_claim_count": sum(
                result.diagnostics["assigned_claim_count"]
                for result in scope_results
            ),
            "pending_claim_count": sum(
                result.diagnostics["pending_claim_count"]
                for result in scope_results
            ),
            "untimed_claim_count": sum(
                result.diagnostics["untimed_claim_count"]
                for result in scope_results
            ),
        },
    }
    if any(state_id is None for state_id in assignments.values()):
        raise RuntimeError(
            "EPBench QA graph requires every Claim to belong to a State"
        )
    return payload


def _event_display(event: Event) -> str:
    return "\n".join(
        [
            f"Event ID: {event.event_id}",
            f"Chapter index: {event.chapter_idx}",
            f"Event time: {event.event_time_text or 'unknown'}",
            f"Entities: {', '.join(event.entities or [])}",
            f"Locations: {', '.join(event.locations or [])}",
            f"Event type: {event.event_type or 'unknown'}",
            f"Title: {event.subject or ''}",
            f"Summary: {event.summary}",
            f"Keywords: {', '.join(event.keywords or [])}",
            f"Detailed Event: {event.event_description or ''}",
        ]
    )


def _scope_display(scope: Scope) -> str:
    start = scope.time_start.isoformat() if scope.time_start else "unknown"
    end = scope.time_end.isoformat() if scope.time_end else "unknown"
    return "\n".join(
        [
            f"Scope ID: {scope.scope_id}",
            f"Title: {scope.title}",
            f"Summary: {scope.summary}",
            f"Event count: {len(scope.event_ids)}",
            f"Event IDs: {', '.join(scope.event_ids)}",
            f"Key entities: {', '.join(scope.key_entities or [])}",
            f"Key locations: {', '.join(scope.key_locations or [])}",
            f"Event types: {', '.join(scope.event_types or [])}",
            f"Time range: {start} to {end}",
            f"Keywords: {', '.join(scope.keywords or [])}",
        ]
    )


def _scope_times(events: list[Event]) -> tuple[datetime | None, datetime | None]:
    values = [event.timestamp for event in events if event.timestamp is not None]
    return (min(values), max(values)) if values else (None, None)


class EPBenchGraphBuilder:
    def __init__(
        self,
        llm_provider,
        embedding_provider=None,
        concurrency: int = 8,
        scope_candidate_top_k: int = 10,
        *,
        enable_low_weight_repool: bool = ExperimentConfig.enable_low_weight_repool,
        event_scope_weight_threshold: float = ExperimentConfig.event_scope_weight_threshold,
        shuffle_scope_events: bool = ExperimentConfig.shuffle_scope_events,
        scope_event_shuffle_seed: int = ExperimentConfig.scope_event_shuffle_seed,
    ):
        self.llm = llm_provider
        self.embedding_provider = embedding_provider
        self.concurrency = max(1, concurrency)
        self.scope_candidate_top_k = max(1, scope_candidate_top_k)
        self.scope_retriever: ScopeEmbeddingRetriever | None = None
        self.enable_low_weight_repool = enable_low_weight_repool
        self.event_scope_weight_threshold = float(event_scope_weight_threshold)
        self.shuffle_scope_events = bool(shuffle_scope_events)
        self.scope_event_shuffle_seed = int(scope_event_shuffle_seed)
        self._scope_order_rank: dict[str, int] = {}
        if not 0.0 <= self.event_scope_weight_threshold <= 1.0:
            raise ValueError("Event-Scope weight threshold must be in [0, 1]")
        model = str(getattr(llm_provider, "model", "unknown"))
        embedding_model = str(
            getattr(embedding_provider, "model_name", "missing")
        )
        self.event_signature = hashlib.sha256(
            "\n".join(
                [SCHEMA_VERSION, model, EPBENCH_EVENT_EXTRACTION_PROMPT]
            ).encode()
        ).hexdigest()
        self.scope_signature = hashlib.sha256(
            "\n".join(
                [
                    SCHEMA_VERSION,
                    model,
                    self.event_signature,
                    EPBENCH_SCOPE_CREATE_PROMPT,
                    EPBENCH_SCOPE_MATCH_PROMPT,
                    EPBENCH_SCOPE_UPDATE_PROMPT,
                    EPBENCH_EVENT_ROLE_WEIGHT_PROMPT,
                    str(self.enable_low_weight_repool),
                    str(self.event_scope_weight_threshold),
                    str(self.shuffle_scope_events),
                    str(self.scope_event_shuffle_seed),
                    SCOPE_RETRIEVAL_FEATURE_VERSION,
                    embedding_model,
                    str(self.scope_candidate_top_k),
                ]
            ).encode()
        ).hexdigest()
        self.claim_signature = hashlib.sha256(
            "\n".join(
                [
                    SCHEMA_VERSION,
                    model,
                    self.scope_signature,
                    EPBENCH_CLAIM_EXTRACTION_PROMPT,
                ]
            ).encode()
        ).hexdigest()
        self.state_config = StateThreadConfig(min_claim_confidence=0.0)
        self.state_signature = hashlib.sha256(
            "\n".join(
                [
                    SCHEMA_VERSION,
                    model,
                    embedding_model,
                    self.claim_signature,
                    json.dumps(
                        self.state_config.to_dict(),
                        sort_keys=True,
                    ),
                    STATE_CHRONOLOGICAL_SUMMARY_PROMPT,
                ]
            ).encode()
        ).hexdigest()
        signature_input = "\n".join(
            [
                SCHEMA_VERSION,
                model,
                self.event_signature,
                self.scope_signature,
                self.claim_signature,
                self.state_signature,
            ]
        )
        self.build_signature = hashlib.sha256(signature_input.encode()).hexdigest()

    async def _events(
        self, data_folder: Path, book_id: str, cache_dir: Path, limit: int | None
    ) -> list[Event]:
        chapters = load_book_chapters(data_folder)
        if limit is not None:
            chapters = chapters[:limit]
        requested_chapter_indices = {chapter.chapter_idx for chapter in chapters}
        cache = cache_dir / "events.json"
        existing = {}
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            current_checkpoint = (
                payload.get("schema_version") == SCHEMA_VERSION
                and payload.get("event_signature") == self.event_signature
            )
            if current_checkpoint:
                existing = {
                    item["chapter_idx"]: _event_from_dict(item)
                    for item in payload.get("events", [])
                    if (
                        item.get("book_id") == book_id
                        and item.get("chapter_idx") in requested_chapter_indices
                    )
                }
        _progress(
            "1/4 Event extraction",
            len(existing),
            len(chapters),
            "checkpoint restored" if existing else "starting",
        )
        semaphore = asyncio.Semaphore(self.concurrency)
        save_lock = asyncio.Lock()
        extractor = EPBenchEventExtractor(self.llm)

        async def one(chapter):
            if chapter.chapter_idx in existing:
                return existing[chapter.chapter_idx]
            async with semaphore:
                event = await extractor.extract_event(
                    book_id, chapter.chapter_idx, chapter.text
                )
            async with save_lock:
                existing[chapter.chapter_idx] = event
                _atomic_json(
                    cache,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "event_signature": self.event_signature,
                        "build_signature": self.build_signature,
                        "dataset": "epbench",
                        "extraction_model": str(
                            getattr(self.llm, "model", "unknown")
                        ),
                        "events": [
                            value.to_dict()
                            for _, value in sorted(existing.items())
                        ],
                    },
                )
                _progress(
                    "1/4 Event extraction",
                    len(existing),
                    len(chapters),
                    f"chapter={chapter.chapter_idx} checkpoint saved",
                )
            return event

        events = await asyncio.gather(*(one(chapter) for chapter in chapters))
        if len(events) != len(chapters) or len({e.chapter_idx for e in events}) != len(chapters):
            raise RuntimeError("EPBench invariant failed: one unique Event per chapter")
        _atomic_json(
            cache,
            {"schema_version": SCHEMA_VERSION,
             "event_signature": self.event_signature,
             "build_signature": self.build_signature, "dataset": "epbench",
             "extraction_model": str(getattr(self.llm, "model", "unknown")),
             "events": [event.to_dict() for event in events]},
        )
        _progress("1/4 Event extraction", len(events), len(chapters), "complete")
        return events

    async def _match_scopes(self, event: Event, scopes: list[Scope]) -> list[str]:
        if self.scope_retriever is None:
            raise RuntimeError(
                "Scope embedding retriever is not configured"
            )
        ranked = await self.scope_retriever.top_k(
            event,
            scopes,
            self.scope_candidate_top_k,
        )
        candidates = [scope for scope, _ in ranked]
        _status(
            "2/4 Scope embedding candidates: "
            f"event={event.event_id}; "
            + ", ".join(
                f"{scope.scope_id}={score:.4f}"
                for scope, score in ranked
            )
        )
        aliases = {
            f"scope_{index + 1}": scope.scope_id
            for index, scope in enumerate(candidates)
        }
        scope_text = "\n\n".join(
            "\n".join(
                [
                    f"Scope ID: {alias}",
                    f"Title: {scope.title}",
                    f"Summary: {scope.summary}",
                ]
            )
            for alias, scope in zip(aliases, candidates)
        )
        output = await generate_json(
            self.llm,
            EPBENCH_SCOPE_MATCH_PROMPT.format(
                event=event_theme_text(event),
                scopes=scope_text,
            )
        )
        rows = output.get("results")
        if not isinstance(rows, list):
            raise ValueError("Scope match output requires a results list")
        matched = []
        seen = set()
        for item in rows:
            scope_alias = item.get("scope_id")
            if scope_alias not in aliases or scope_alias in seen:
                raise ValueError(
                    f"Invalid or duplicate Scope match ID: {scope_alias!r}"
                )
            seen.add(scope_alias)
            if not isinstance(item.get("match"), bool):
                raise ValueError("Scope match must be a boolean")
            confidence = float(
                item.get(
                    "confidence",
                    1.0 if item["match"] else 0.0,
                )
            )
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("Scope match confidence must be in [0, 1]")
            raw_basis = item.get("matched_basis")
            if raw_basis is None:
                matched_basis = []
            elif isinstance(raw_basis, str):
                matched_basis = (
                    [raw_basis.strip()] if raw_basis.strip() else []
                )
            elif isinstance(raw_basis, list):
                matched_basis = [
                    str(value).strip()
                    for value in raw_basis
                    if str(value).strip()
                ]
            else:
                matched_basis = [str(raw_basis).strip()]
            if item["match"] is True:
                matched.append(aliases[scope_alias])
                _status(
                    "2/4 Scope match accepted: "
                    f"event={event.event_id}; "
                    f"scope={aliases[scope_alias]}; "
                    f"confidence={confidence:.3f}; "
                    f"basis={' | '.join(matched_basis) or 'same theme'}"
                )
        if seen != set(aliases):
            raise ValueError(
                f"Missing Scope match decisions: {sorted(set(aliases) - seen)}"
            )
        return matched

    async def _generate_scope_output(
        self,
        prompt: str,
        operation: str,
    ) -> dict:
        validation_error: Exception | None = None
        for attempt in range(1, 4):
            current_prompt = prompt
            if validation_error is not None:
                current_prompt += (
                    "\n\n# CORRECTION REQUIRED\n"
                    f"The previous {operation} output failed validation: "
                    f"{validation_error}\n"
                    "Return one complete JSON object containing every required "
                    "field: title, summary, keywords, key_entities, "
                    "key_locations, event_types, and scope_type. Do not stop "
                    "before the closing brace."
                )
            try:
                output = await generate_json(
                    self.llm,
                    current_prompt,
                    attempts=1,
                )
                _required_text(output, "title")
                _required_text(output, "summary")
                for field in (
                    "keywords",
                    "key_entities",
                    "key_locations",
                    "event_types",
                ):
                    _required_string_list(output, field)
                _required_scope_type(output)
                return output
            except (KeyError, TypeError, ValueError) as error:
                validation_error = error
                if attempt < 3:
                    _status(
                        "2/4 Scope output validation retry: "
                        f"operation={operation}; attempt={attempt + 1}/3; "
                        f"error={error}"
                    )
        raise ValueError(
            f"{operation} output failed validation after 3 attempts: "
            f"{validation_error}"
        ) from validation_error

    async def _new_scope(self, event: Event, ordinal: int) -> Scope:
        output = await self._generate_scope_output(
            EPBENCH_SCOPE_CREATE_PROMPT.format(event=_event_display(event)),
            "create",
        )
        start, end = _scope_times([event])
        return Scope(
            scope_id=f"scope_{ordinal:04d}",
            title=_required_text(output, "title"),
            summary=_required_text(output, "summary"),
            event_ids=[event.event_id],
            timestamp=end,
            user_id_list=[],
            participants=event.entities,
            keywords=_required_string_list(output, "keywords"),
            key_entities=_required_string_list(output, "key_entities"),
            key_locations=_required_string_list(output, "key_locations"),
            event_types=_required_string_list(output, "event_types"),
            time_start=start,
            time_end=end,
            scope_type=_required_scope_type(output),
            metadata={"dataset": "epbench"},
        )

    async def _update_scope(
        self, scope: Scope, event: Event, events_by_id: dict[str, Event]
    ) -> Scope:
        output = await self._generate_scope_output(
            EPBENCH_SCOPE_UPDATE_PROMPT.format(
                scope=_scope_display(scope), event=_event_display(event)
            ),
            "update",
        )
        event_ids = list(dict.fromkeys([*scope.event_ids, event.event_id]))
        events = [events_by_id[event_id] for event_id in event_ids]
        start, end = _scope_times(events)
        return Scope(
            scope_id=scope.scope_id,
            title=_required_text(output, "title"),
            summary=_required_text(output, "summary"),
            event_ids=event_ids,
            timestamp=end,
            user_id_list=[],
            participants=list(dict.fromkeys(entity for e in events for entity in (e.entities or []))),
            keywords=_required_string_list(output, "keywords"),
            key_entities=_required_string_list(output, "key_entities"),
            key_locations=_required_string_list(output, "key_locations"),
            event_types=_required_string_list(output, "event_types"),
            time_start=start,
            time_end=end,
            scope_type=_required_scope_type(output),
            metadata={"dataset": "epbench"},
        )

    async def _rebuild_scope(
        self,
        scope: Scope,
        events: list[Event],
    ) -> Scope:
        output = await self._generate_scope_output(
            EPBENCH_SCOPE_CREATE_PROMPT.format(
                event="\n\n".join(_event_display(event) for event in events)
            ),
            "rebuild",
        )
        start, end = _scope_times(events)
        return Scope(
            scope_id=scope.scope_id,
            title=_required_text(output, "title"),
            summary=_required_text(output, "summary"),
            event_ids=[event.event_id for event in events],
            timestamp=end,
            user_id_list=[],
            participants=list(
                dict.fromkeys(
                    entity for event in events for entity in (event.entities or [])
                )
            ),
            keywords=_required_string_list(output, "keywords"),
            key_entities=_required_string_list(output, "key_entities"),
            key_locations=_required_string_list(output, "key_locations"),
            event_types=_required_string_list(output, "event_types"),
            time_start=start,
            time_end=end,
            scope_type=_required_scope_type(output),
            metadata={"dataset": "epbench"},
        )

    async def _assign_event_roles_weights(
        self,
        scope: Scope,
        events_by_id: dict[str, Event],
    ) -> tuple[dict[str, str], dict[str, float]]:
        events = [events_by_id[event_id] for event_id in scope.event_ids]
        aliases = {
            f"event_{index + 1}": event.event_id
            for index, event in enumerate(events)
        }
        events_text = "\n\n".join(
            _event_display(event).replace(event.event_id, alias, 1)
            for alias, event in zip(aliases, events)
        )
        prompt = EPBENCH_EVENT_ROLE_WEIGHT_PROMPT.format(
            scope=_scope_display(scope),
            events=events_text,
        )
        validation_error: Exception | None = None
        for attempt in range(1, 4):
            current_prompt = prompt
            if validation_error is not None:
                current_prompt += (
                    "\n\n# CORRECTION REQUIRED\n"
                    f"The previous output failed validation: {validation_error}\n"
                    f"Return exactly {len(aliases)} `event_roles` rows, one for "
                    f"each of these IDs: {', '.join(aliases)}. Do not omit, "
                    "duplicate, rename, or add any Event ID."
                )
            output = await generate_json(
                self.llm,
                current_prompt,
            )
            try:
                return self._parse_event_roles_weights(
                    output,
                    scope,
                    aliases,
                )
            except (KeyError, TypeError, ValueError) as error:
                validation_error = error
                if attempt < 3:
                    _status(
                        "2/4 Scope role/weight validation retry: "
                        f"scope={scope.scope_id}; attempt={attempt + 1}/3; "
                        f"error={error}"
                    )
        raise ValueError(
            "Event role/weight assignment failed validation after 3 "
            f"attempts for {scope.scope_id}: {validation_error}"
        ) from validation_error

    @staticmethod
    def _parse_event_roles_weights(
        output: dict,
        scope: Scope,
        aliases: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, float]]:
        rows = output.get("event_roles") or []
        if not isinstance(rows, list):
            raise ValueError("Event role output must be a list")
        try:
            coherence = float(output.get("coherence_score"))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Event role output requires a numeric coherence_score"
            ) from error
        if not 0.0 <= coherence <= 1.0:
            raise ValueError("coherence_score must be in [0, 1]")
        if not isinstance(output.get("reasoning"), str):
            raise ValueError("Event role output requires reasoning")
        roles: dict[str, str] = {}
        weights: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Every Event role row must be an object")
            alias = row.get("event_id")
            event_id = aliases.get(alias)
            if event_id is None or event_id in roles:
                raise ValueError(
                    f"Invalid or duplicate Event role ID: {alias!r}"
                )
            role = str(row.get("role") or "developing")
            if role not in EVENT_ROLES:
                raise ValueError(f"Unsupported Event role: {role}")
            try:
                weight = float(row.get("weight", 0.5))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Event weight must be numeric for {alias}"
                ) from error
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"Event weight must be in [0, 1]: {weight}")
            if not isinstance(row.get("rationale"), str) or not row[
                "rationale"
            ].strip():
                raise ValueError("Every Event role requires a rationale")
            roles[event_id] = role
            weights[event_id] = weight
        missing_aliases = [
            alias
            for alias, event_id in aliases.items()
            if event_id not in roles
        ]
        if missing_aliases:
            raise ValueError(
                f"Missing Event role/weight assignments: {missing_aliases}"
            )
        return (
            {event_id: roles[event_id] for event_id in scope.event_ids},
            {event_id: weights[event_id] for event_id in scope.event_ids},
        )

    async def _repool_low_weight_events(
        self,
        scopes: list[Scope],
        events_by_id: dict[str, Event],
        roles: dict[str, dict[str, str]],
        weights: dict[str, dict[str, float]],
    ) -> ScopeBuildResult:
        stats = LowWeightRepoolStats(self.event_scope_weight_threshold)
        if not self.enable_low_weight_repool:
            validate_event_scope_integrity(
                scopes, roles, weights, list(events_by_id)
            )
            return ScopeBuildResult(scopes, roles, weights, stats)

        rejected_scopes: dict[str, set[str]] = {}
        terminal_scope_by_event: dict[str, str] = {}
        next_scope_ordinal = max(
            (
                int(scope.scope_id.removeprefix("scope_"))
                for scope in scopes
                if scope.scope_id.removeprefix("scope_").isdigit()
            ),
            default=0,
        ) + 1

        while True:
            weak = collect_weak_event_scope_relations(
                scopes, weights, self.event_scope_weight_threshold
            )
            weak = [
                relation
                for relation in weak
                if terminal_scope_by_event.get(relation.event_id)
                != relation.scope_id
            ]
            if not weak:
                break
            relation = min(
                weak,
                key=lambda item: (
                    self._scope_order_rank.get(item.event_id, len(events_by_id)),
                    item.scope_id,
                ),
            )
            _status(
                "3/4 Low-weight repool: detaching "
                f"{relation.event_id} from {relation.scope_id} "
                f"(weight={relation.weight:.3f}, "
                f"threshold={self.event_scope_weight_threshold:.3f})"
            )
            stats.weak_relations += 1
            stats.detached_relations += 1
            rejected_scopes.setdefault(relation.event_id, set()).add(
                relation.scope_id
            )

            source = next(
                scope for scope in scopes if scope.scope_id == relation.scope_id
            )
            source.event_ids = [
                event_id
                for event_id in source.event_ids
                if event_id != relation.event_id
            ]
            roles[relation.scope_id].pop(relation.event_id, None)
            weights[relation.scope_id].pop(relation.event_id, None)
            if source.event_ids:
                source = await self._rebuild_scope(
                    source,
                    [events_by_id[event_id] for event_id in source.event_ids],
                )
                source_index = next(
                    index
                    for index, scope in enumerate(scopes)
                    if scope.scope_id == source.scope_id
                )
                scopes[source_index] = source
                (
                    roles[source.scope_id],
                    weights[source.scope_id],
                ) = await self._assign_event_roles_weights(
                    source, events_by_id
                )
            else:
                scopes = [
                    scope for scope in scopes if scope.scope_id != source.scope_id
                ]
                roles.pop(source.scope_id, None)
                weights.pop(source.scope_id, None)
                stats.deleted_empty_scopes += 1

            event = events_by_id[relation.event_id]
            candidates = [
                scope
                for scope in scopes
                if (
                    scope.scope_id
                    not in rejected_scopes.get(event.event_id, set())
                    and event.event_id not in scope.event_ids
                )
            ]
            matched_ids = (
                list(dict.fromkeys(await self._match_scopes(event, candidates)))
                if candidates
                else []
            )
            changed_scope_ids = []
            for scope_id in matched_ids:
                index = next(
                    index
                    for index, scope in enumerate(scopes)
                    if scope.scope_id == scope_id
                )
                scopes[index] = await self._update_scope(
                    scopes[index], event, events_by_id
                )
                (
                    roles[scope_id],
                    weights[scope_id],
                ) = await self._assign_event_roles_weights(
                    scopes[index], events_by_id
                )
                changed_scope_ids.append(scope_id)
                stats.rematched_relations += 1

            if changed_scope_ids:
                _status(
                    "3/4 Low-weight repool: rematched "
                    f"{event.event_id} -> {', '.join(changed_scope_ids)}"
                )
                continue
            if any(event.event_id in scope.event_ids for scope in scopes):
                stats.retained_elsewhere += 1
                _status(
                    "3/4 Low-weight repool: retained "
                    f"{event.event_id} in another existing Scope"
                )
                continue

            terminal = await self._new_scope(event, next_scope_ordinal)
            next_scope_ordinal += 1
            scopes.append(terminal)
            roles[terminal.scope_id] = {event.event_id: "key_moment"}
            weights[terminal.scope_id] = {event.event_id: 1.0}
            terminal_scope_by_event[event.event_id] = terminal.scope_id
            stats.created_scopes += 1
            _status(
                "3/4 Low-weight repool: created terminal Scope "
                f"{terminal.scope_id} for {event.event_id}"
            )

        validate_event_scope_integrity(
            scopes, roles, weights, list(events_by_id)
        )
        _status(
            "3/4 Low-weight repool complete: "
            f"weak={stats.weak_relations}, detached={stats.detached_relations}, "
            f"rematched={stats.rematched_relations}, "
            f"created_scopes={stats.created_scopes}, "
            f"deleted_empty_scopes={stats.deleted_empty_scopes}"
        )
        return ScopeBuildResult(scopes, roles, weights, stats)

    async def _scopes(
        self, events: list[Event], cache_dir: Path
    ) -> ScopeBuildResult:
        cache = cache_dir / "scopes.json"
        if self.embedding_provider is None:
            raise RuntimeError(
                "Scope construction requires an embedding provider"
            )
        self.scope_retriever = ScopeEmbeddingRetriever(
            self.embedding_provider,
            cache_dir / "scope_embedding_cache.json",
        )
        scope_events = list(events)
        if self.shuffle_scope_events:
            random.Random(self.scope_event_shuffle_seed).shuffle(scope_events)
        requested_ids = [event.event_id for event in scope_events]
        self._scope_order_rank = {
            event_id: index for index, event_id in enumerate(requested_ids)
        }
        events_by_id = {event.event_id: event for event in events}
        processed_ids: list[str] = []
        scope_map: dict[str, Scope] = {}
        roles: dict[str, dict[str, str]] = {}
        weights: dict[str, dict[str, float]] = {}
        pending_repool_ids: list[str] = []
        completed_repool_ids: set[str] = set()
        rejected_scopes_by_event: dict[str, set[str]] = {}
        terminal_scope_by_event: dict[str, str] = {}
        repool_stats = LowWeightRepoolStats(
            threshold=self.event_scope_weight_threshold
        )
        next_scope_ordinal = 1

        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            cached_processed = payload.get("processed_event_ids", [])
            if (
                payload.get("schema_version") == SCHEMA_VERSION
                and payload.get("scope_signature") == self.scope_signature
                and cached_processed == requested_ids[:len(cached_processed)]
            ):
                processed_ids = cached_processed
                scope_map = {
                    scope.scope_id: scope
                    for scope in (
                        _scope_from_dict(item) for item in payload["scopes"]
                    )
                }
                roles = {
                    scope_id: {
                        event_id: str(role)
                        for event_id, role in scope_roles.items()
                    }
                    for scope_id, scope_roles in payload.get("roles", {}).items()
                }
                weights = {
                    scope_id: {
                        event_id: float(weight)
                        for event_id, weight in scope_weights.items()
                    }
                    for scope_id, scope_weights in payload.get("weights", {}).items()
                }
                pending_repool_ids = [
                    event_id
                    for event_id in payload.get("pending_repool_event_ids", [])
                    if event_id in events_by_id
                ]
                completed_repool_ids = set(
                    payload.get("completed_repool_event_ids", [])
                )
                rejected_scopes_by_event = {
                    event_id: set(scope_ids)
                    for event_id, scope_ids in payload.get(
                        "rejected_scopes_by_event", {}
                    ).items()
                }
                terminal_scope_by_event = {
                    str(event_id): str(scope_id)
                    for event_id, scope_id in payload.get(
                        "terminal_scope_by_event", {}
                    ).items()
                }
                repool_stats = LowWeightRepoolStats(
                    **payload.get(
                        "repool_stats",
                        {"threshold": self.event_scope_weight_threshold},
                    )
                )
                next_scope_ordinal = int(
                    payload.get("next_scope_ordinal", 1)
                )
                if (
                    payload.get("phase") == "complete"
                    and processed_ids == requested_ids
                ):
                    validate_event_scope_integrity(
                        list(scope_map.values()), roles, weights, requested_ids
                    )
                    _progress(
                        "2/4 Scope construction",
                        len(processed_ids),
                        len(requested_ids),
                        f"complete checkpoint restored; scopes={len(scope_map)}",
                    )
                    _status(
                        "3/4 Low-weight repool: restored from complete checkpoint "
                        f"(detached={repool_stats.detached_relations}, "
                        f"rematched={repool_stats.rematched_relations}, "
                        f"created_scopes={repool_stats.created_scopes})"
                    )
                    return ScopeBuildResult(
                        list(scope_map.values()),
                        roles,
                        weights,
                        repool_stats,
                    )

        if scope_map and next_scope_ordinal == 1:
            next_scope_ordinal = (
                max(
                    (
                        int(scope_id.removeprefix("scope_"))
                        for scope_id in scope_map
                        if scope_id.removeprefix("scope_").isdigit()
                    ),
                    default=0,
                )
                + 1
            )

        pending_events = deque(
            (events_by_id[event_id], False)
            for event_id in requested_ids[len(processed_ids):]
        )
        pending_events.extend(
            (events_by_id[event_id], True)
            for event_id in pending_repool_ids
        )
        queued_repool_ids = set(pending_repool_ids)

        if self.shuffle_scope_events:
            _status(
                "2/4 Scope construction order: seeded shuffle enabled "
                f"(seed={self.scope_event_shuffle_seed})"
            )
            _status(
                "2/4 Scope shuffled Event order: "
                + " -> ".join(requested_ids)
            )
        else:
            _status("2/4 Scope construction order: source chapter order")
        _progress(
            "2/4 Scope construction",
            len(processed_ids),
            len(requested_ids),
            (
                f"checkpoint restored; scopes={len(scope_map)}; "
                f"pending_repool={len(pending_repool_ids)}"
                if processed_ids or pending_repool_ids
                else "starting"
            ),
        )

        async def assign_scope(scope_id: str) -> None:
            roles[scope_id], weights[scope_id] = (
                await self._assign_event_roles_weights(
                    scope_map[scope_id], events_by_id
                )
            )

        async def create_scope(event: Event, *, terminal: bool) -> str:
            nonlocal next_scope_ordinal
            scope = await self._new_scope(event, next_scope_ordinal)
            next_scope_ordinal += 1
            scope_map[scope.scope_id] = scope
            if terminal:
                roles[scope.scope_id] = {event.event_id: "key_moment"}
                weights[scope.scope_id] = {event.event_id: 1.0}
                terminal_scope_by_event[event.event_id] = scope.scope_id
            else:
                await assign_scope(scope.scope_id)
            return scope.scope_id

        async def rebuild_scope(scope_id: str) -> bool:
            scope = scope_map[scope_id]
            if not scope.event_ids:
                scope_map.pop(scope_id)
                roles.pop(scope_id, None)
                weights.pop(scope_id, None)
                repool_stats.deleted_empty_scopes += 1
                return False
            scope_map[scope_id] = await self._rebuild_scope(
                scope,
                [events_by_id[event_id] for event_id in scope.event_ids],
            )
            await assign_scope(scope_id)
            return True

        async def detach_weak_relations_and_enqueue(
            scope_ids_to_check: set[str],
        ) -> None:
            if not self.enable_low_weight_repool:
                return
            scopes_to_check = set(scope_ids_to_check)
            while scopes_to_check:
                current_scope_ids = {
                    scope_id
                    for scope_id in scopes_to_check
                    if scope_id in scope_map
                }
                if not current_scope_ids:
                    return
                current_scopes = [
                    scope
                    for scope_id, scope in scope_map.items()
                    if scope_id in current_scope_ids
                ]
                weak_relations = collect_weak_event_scope_relations(
                    current_scopes,
                    weights,
                    self.event_scope_weight_threshold,
                )
                weak_relations = [
                    relation
                    for relation in weak_relations
                    if terminal_scope_by_event.get(relation.event_id)
                    != relation.scope_id
                ]
                if not weak_relations:
                    return

                affected_scope_ids: set[str] = set()
                events_requiring_terminal_scope: set[str] = set()
                for relation in weak_relations:
                    scope = scope_map[relation.scope_id]
                    scope.event_ids = [
                        event_id
                        for event_id in scope.event_ids
                        if event_id != relation.event_id
                    ]
                    roles[relation.scope_id].pop(relation.event_id, None)
                    weights[relation.scope_id].pop(relation.event_id, None)
                    rejected_scopes_by_event.setdefault(
                        relation.event_id, set()
                    ).add(relation.scope_id)
                    affected_scope_ids.add(relation.scope_id)
                    repool_stats.weak_relations += 1
                    repool_stats.detached_relations += 1

                    if relation.event_id in completed_repool_ids:
                        if relation.event_id not in terminal_scope_by_event:
                            events_requiring_terminal_scope.add(
                                relation.event_id
                            )
                    elif relation.event_id not in queued_repool_ids:
                        pending_events.append(
                            (events_by_id[relation.event_id], True)
                        )
                        queued_repool_ids.add(relation.event_id)
                        _status(
                            "3/4 Low-weight repool queued at tail: "
                            f"event={relation.event_id}; "
                            f"scope={relation.scope_id}; "
                            f"weight={relation.weight:.3f}; "
                            f"threshold={self.event_scope_weight_threshold:.3f}"
                        )

                for event_id in sorted(
                    events_requiring_terminal_scope,
                    key=lambda value: self._scope_order_rank.get(
                        value, len(requested_ids)
                    ),
                ):
                    scope_id = await create_scope(
                        events_by_id[event_id], terminal=True
                    )
                    repool_stats.created_scopes += 1
                    _status(
                        "3/4 Low-weight repool created terminal Scope: "
                        f"event={event_id}; scope={scope_id}"
                    )

                rebuilt_scope_ids = set()
                for scope_id in sorted(affected_scope_ids):
                    if await rebuild_scope(scope_id):
                        rebuilt_scope_ids.add(scope_id)
                scopes_to_check = rebuilt_scope_ids

        async def process_original_event(event: Event) -> tuple[set[str], int]:
            current_scopes = list(scope_map.values())
            matched_ids = (
                list(dict.fromkeys(await self._match_scopes(event, current_scopes)))
                if current_scopes
                else []
            )
            changed_scope_ids: set[str] = set()
            if not matched_ids:
                changed_scope_ids.add(
                    await create_scope(event, terminal=False)
                )
            else:
                for scope_id in matched_ids:
                    if scope_id not in scope_map:
                        continue
                    scope_map[scope_id] = await self._update_scope(
                        scope_map[scope_id], event, events_by_id
                    )
                    await assign_scope(scope_id)
                    changed_scope_ids.add(scope_id)
            processed_ids.append(event.event_id)
            return changed_scope_ids, len(matched_ids)

        async def process_repool_event(event: Event) -> set[str]:
            rejected = rejected_scopes_by_event.get(event.event_id, set())
            candidates = [
                scope
                for scope_id, scope in scope_map.items()
                if scope_id not in rejected
            ]
            matched_ids = list(
                dict.fromkeys(
                    await self._match_scopes(event, candidates)
                )
            ) if candidates else []
            changed_scope_ids: set[str] = set()
            for scope_id in matched_ids:
                if (
                    scope_id not in scope_map
                    or event.event_id in scope_map[scope_id].event_ids
                ):
                    continue
                scope_map[scope_id] = await self._update_scope(
                    scope_map[scope_id], event, events_by_id
                )
                await assign_scope(scope_id)
                changed_scope_ids.add(scope_id)
                repool_stats.rematched_relations += 1
            if changed_scope_ids:
                return changed_scope_ids
            if any(
                event.event_id in scope.event_ids
                for scope in scope_map.values()
            ):
                repool_stats.retained_elsewhere += 1
                return set()
            changed_scope_ids.add(
                await create_scope(event, terminal=False)
            )
            repool_stats.created_scopes += 1
            return changed_scope_ids

        def save_checkpoint(phase: str) -> None:
            queued_in_order = [
                event.event_id
                for event, is_repool in pending_events
                if is_repool
            ]
            _atomic_json(
                cache,
                {
                    "schema_version": SCHEMA_VERSION,
                    "scope_signature": self.scope_signature,
                    "build_signature": self.build_signature,
                    "phase": phase,
                    "processed_event_ids": processed_ids,
                    "scopes": [
                        scope.to_dict() for scope in scope_map.values()
                    ],
                    "roles": roles,
                    "weights": weights,
                    "pending_repool_event_ids": queued_in_order,
                    "completed_repool_event_ids": sorted(
                        completed_repool_ids
                    ),
                    "rejected_scopes_by_event": {
                        event_id: sorted(scope_ids)
                        for event_id, scope_ids
                        in rejected_scopes_by_event.items()
                    },
                    "terminal_scope_by_event": terminal_scope_by_event,
                    "next_scope_ordinal": next_scope_ordinal,
                    "repool_stats": asdict(repool_stats),
                },
            )

        while pending_events:
            event, is_repool = pending_events.popleft()
            if is_repool:
                queued_repool_ids.discard(event.event_id)
                completed_repool_ids.add(event.event_id)
                changed_scope_ids = await process_repool_event(event)
                await detach_weak_relations_and_enqueue(changed_scope_ids)
                save_checkpoint("repool")
                _status(
                    "3/4 Low-weight repool processed: "
                    f"event={event.event_id}; "
                    f"changed_scopes={len(changed_scope_ids)}; "
                    f"pending={sum(1 for _, flag in pending_events if flag)}"
                )
            else:
                changed_scope_ids, matched_count = (
                    await process_original_event(event)
                )
                await detach_weak_relations_and_enqueue(changed_scope_ids)
                save_checkpoint("initial")
                _progress(
                    "2/4 Scope construction",
                    len(processed_ids),
                    len(requested_ids),
                    f"event={event.event_id}; matched={matched_count}; "
                    f"weighted_scopes={len(changed_scope_ids)}; "
                    f"scopes={len(scope_map)}; "
                    f"pending_repool={sum(1 for _, flag in pending_events if flag)}; "
                    "checkpoint saved",
                )

        validate_event_scope_integrity(
            list(scope_map.values()),
            roles,
            weights,
            requested_ids,
        )
        safety_result = await self._repool_low_weight_events(
            list(scope_map.values()),
            events_by_id,
            roles,
            weights,
        )
        _accumulate_repool_stats(
            repool_stats, safety_result.repool_stats
        )
        scope_map = {
            scope.scope_id: scope for scope in safety_result.scopes
        }
        roles = safety_result.roles
        weights = safety_result.weights
        validate_event_scope_integrity(
            list(scope_map.values()),
            roles,
            weights,
            requested_ids,
        )
        _atomic_json(
            cache,
            {
                "schema_version": SCHEMA_VERSION,
                "scope_signature": self.scope_signature,
                "build_signature": self.build_signature,
                "phase": "complete",
                "processed_event_ids": requested_ids,
                "scopes": [
                    scope.to_dict() for scope in scope_map.values()
                ],
                "roles": roles,
                "weights": weights,
                "pending_repool_event_ids": [],
                "completed_repool_event_ids": sorted(
                    completed_repool_ids
                ),
                "rejected_scopes_by_event": {
                    event_id: sorted(scope_ids)
                    for event_id, scope_ids
                    in rejected_scopes_by_event.items()
                },
                "terminal_scope_by_event": terminal_scope_by_event,
                "next_scope_ordinal": next_scope_ordinal,
                "repool_stats": asdict(repool_stats),
            },
        )
        _status(
            "3/4 Low-weight repool complete: "
            f"weak={repool_stats.weak_relations}, "
            f"detached={repool_stats.detached_relations}, "
            f"rematched={repool_stats.rematched_relations}, "
            f"created_scopes={repool_stats.created_scopes}, "
            f"deleted_empty_scopes={repool_stats.deleted_empty_scopes}"
        )
        return ScopeBuildResult(
            list(scope_map.values()), roles, weights, repool_stats
        )

    @staticmethod
    def _parse_claim_output(
        output: dict,
        event: Event,
        scope: Scope,
    ) -> list[Claim]:
        raw_claims = output.get("claims")
        if not isinstance(raw_claims, list) or not raw_claims:
            raise ValueError(
                f"No Claim list returned for {event.event_id}"
            )
        if not isinstance(output.get("reasoning"), str):
            raise ValueError("Claim extraction requires reasoning")
        claims = []
        raw_claim_ids = set()
        for ordinal, item in enumerate(raw_claims, 1):
            if not isinstance(item, dict):
                raise ValueError("Every Claim must be a JSON object")
            raw_claim_id = item.get("claim_id")
            if (
                not isinstance(raw_claim_id, str)
                or not raw_claim_id.strip()
                or raw_claim_id in raw_claim_ids
            ):
                raise ValueError("Claim IDs must be non-empty and unique")
            raw_claim_ids.add(raw_claim_id)
            if not isinstance(item.get("content"), str) or not item[
                "content"
            ].strip():
                raise ValueError("Every Claim requires non-empty content")
            raw_ids = item.get("event_ids") or []
            if raw_ids != [event.event_id]:
                raise ValueError(
                    "Claim provenance must be exactly "
                    f"[{event.event_id!r}], got {raw_ids!r}"
                )
            claim_type = str(item.get("claim_type") or "detail")
            if claim_type not in CLAIM_TYPES:
                raise ValueError(f"Unsupported claim_type: {claim_type}")
            for field in ("entities", "keywords", "query_patterns"):
                if not isinstance(item.get(field), list):
                    raise ValueError(f"Claim field {field} must be a list")
            if not isinstance(item.get("evidence"), str) or not item[
                "evidence"
            ].strip():
                raise ValueError("Every Claim requires grounded evidence")
            temporal = item.get("temporal")
            if isinstance(temporal, list):
                temporal = ", ".join(str(value) for value in temporal) or None
            elif temporal is not None and not isinstance(temporal, str):
                raise ValueError("Claim temporal must be a string or null")
            spatial = item.get("spatial")
            if isinstance(spatial, list):
                spatial = ", ".join(str(value) for value in spatial) or None
            elif spatial is not None and not isinstance(spatial, str):
                raise ValueError("Claim spatial must be a string or null")
            try:
                confidence = min(
                    1.0, max(0.0, float(item.get("confidence", 0.8)))
                )
            except (TypeError, ValueError) as error:
                raise ValueError("Claim confidence must be numeric") from error
            digest = hashlib.sha1(
                f"{event.event_id}:{ordinal}:{item.get('content', '')}".encode()
            ).hexdigest()[:16]
            claims.append(
                Claim(
                    claim_id=f"claim_{digest}",
                    content=item["content"].strip(),
                    event_ids=[event.event_id],
                    scope_id=scope.scope_id,
                    confidence=confidence,
                    temporal=temporal,
                    spatial=spatial,
                    keywords=[str(v) for v in item["keywords"]],
                    query_patterns=[str(v) for v in item["query_patterns"]],
                    timestamp=event.timestamp,
                    claim_type=claim_type,
                    entities=[str(v) for v in item["entities"]],
                    evidence=item["evidence"].strip(),
                    metadata={"dataset": "epbench"},
                )
            )
        if not claims or any(not claim.content for claim in claims):
            raise ValueError(f"No valid Claims extracted for {event.event_id}")
        return claims

    async def _claims(
        self, events: list[Event], scopes: list[Scope], cache_dir: Path
    ) -> list[Claim]:
        cache = cache_dir / "claims.json"
        requested_ids = [event.event_id for event in events]
        scope_signature = hashlib.sha256(
            json.dumps(
                [scope.to_dict() for scope in scopes],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing_by_event: dict[str, list[Claim]] = {}
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            if (
                payload.get("schema_version") == SCHEMA_VERSION
                and payload.get("claim_signature") == self.claim_signature
                and payload.get("scope_signature") == scope_signature
            ):
                for item in payload.get("claims", []):
                    claim = _claim_from_dict(item)
                    if (
                        len(claim.event_ids) == 1
                        and claim.event_ids[0] in requested_ids
                        and claim.claim_type in CLAIM_TYPES
                    ):
                        existing_by_event.setdefault(claim.event_ids[0], []).append(claim)
        _progress(
            "4/4 Claim extraction",
            len(existing_by_event),
            len(events),
            "checkpoint restored" if existing_by_event else "starting",
        )

        event_scope: dict[str, Scope] = {}
        for scope in scopes:
            for event_id in scope.event_ids:
                event_scope.setdefault(event_id, scope)
        semaphore = asyncio.Semaphore(self.concurrency)
        save_lock = asyncio.Lock()

        async def one(event: Event) -> list[Claim]:
            if event.event_id in existing_by_event:
                return existing_by_event[event.event_id]
            scope = event_scope[event.event_id]
            prompt = EPBENCH_CLAIM_EXTRACTION_PROMPT.format(
                scope_context=_scope_display(scope),
                event_id=event.event_id,
                event_time=event.event_time_text or "unknown",
                event_entities=", ".join(event.entities or []),
                event_locations=", ".join(event.locations or []),
                event_type=event.event_type or "unknown",
                event_content=event.event_description or event.summary,
            )
            validation_error: Exception | None = None
            claims: list[Claim] | None = None
            for attempt in range(1, 4):
                current_prompt = prompt
                if validation_error is not None:
                    current_prompt += (
                        "\n\n# CORRECTION REQUIRED\n"
                        "The previous Claim output failed validation: "
                        f"{validation_error}\n"
                        "Return a complete JSON object. Every `claim_type` must "
                        "be exactly one single value from: event, time, "
                        "location, entity, detail, relation, causal. Never join "
                        "types with `|`, `/`, commas, or any other separator. "
                        f"Every `event_ids` must be exactly "
                        f"[\"{event.event_id}\"]."
                    )
                try:
                    async with semaphore:
                        output = await generate_json(
                            self.llm,
                            current_prompt,
                            attempts=1,
                        )
                    claims = self._parse_claim_output(
                        output,
                        event,
                        scope,
                    )
                    break
                except (KeyError, TypeError, ValueError) as error:
                    validation_error = error
                    if attempt < 3:
                        _status(
                            "4/4 Claim output validation retry: "
                            f"event={event.event_id}; "
                            f"attempt={attempt + 1}/3; error={error}"
                        )
            if claims is None:
                raise ValueError(
                    "Claim output failed validation after 3 attempts for "
                    f"{event.event_id}: {validation_error}"
                ) from validation_error
            async with save_lock:
                existing_by_event[event.event_id] = claims
                _atomic_json(
                    cache,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "claim_signature": self.claim_signature,
                        "build_signature": self.build_signature,
                        "scope_signature": scope_signature,
                        "processed_event_ids": sorted(existing_by_event),
                        "claims": [
                            claim.to_dict()
                            for event_id in sorted(existing_by_event)
                            for claim in existing_by_event[event_id]
                        ],
                    },
                )
                _progress(
                    "4/4 Claim extraction",
                    len(existing_by_event),
                    len(events),
                    f"event={event.event_id}; checkpoint saved",
                )
            return claims

        claims = [claim for group in await asyncio.gather(*(one(event) for event in events)) for claim in group]
        _progress(
            "4/4 Claim extraction",
            len(events),
            len(events),
            f"complete; claims={len(claims)}",
        )
        return claims

    async def _states(
        self,
        claims: list[Claim],
        events: list[Event],
        cache_dir: Path,
    ) -> dict:
        cache = cache_dir / "states.json"
        claim_ids = {claim.claim_id for claim in claims}
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            assignments = payload.get("claim_state_assignments", {})
            if (
                payload.get("state_signature") == self.state_signature
                and set(assignments) == claim_ids
                and all(assignments.values())
            ):
                for claim in claims:
                    claim.state_id = assignments[claim.claim_id]
                _status(
                    "5/5 State threading: checkpoint restored; "
                    f"states={payload['summary']['state_count']}"
                )
                return payload

        _status(
            "5/5 State threading: building STS Claim threads and "
            "TimeGroups"
        )
        loop = asyncio.get_running_loop()
        embedding_backend = _AsyncEmbeddingBridge(
            self.embedding_provider,
            loop,
        )
        payload = await asyncio.to_thread(
            _build_state_payload,
            claims,
            events,
            embedding_backend,
            cache_dir / "state_thread_embeddings.json",
        )
        claims_by_id = {claim.claim_id: claim for claim in claims}
        payload = await StateExtractor(
            self.llm,
            max_concurrency=self.concurrency,
        ).extract(payload, claims_by_id)
        payload["state_signature"] = self.state_signature
        _atomic_json(cache, payload)
        _status(
            "5/5 State threading: complete; "
            f"states={payload['summary']['state_count']}; "
            f"assigned_claims={payload['summary']['assigned_claim_count']}"
        )
        return payload

    def _graph(
        self,
        events: list[Event],
        scopes: list[Scope],
        claims: list[Claim],
        scope_roles: dict[str, dict[str, str]],
        scope_weights: dict[str, dict[str, float]],
    ) -> STSGraph:
        graph = STSGraph()
        claims_by_event: dict[str, list[Claim]] = {}
        for claim in claims:
            claims_by_event.setdefault(claim.event_ids[0], []).append(claim)
        scopes_by_event: dict[str, list[Scope]] = {}
        for scope in scopes:
            for event_id in scope.event_ids:
                scopes_by_event.setdefault(event_id, []).append(scope)

        for claim in claims:
            edge_id = f"event_claim_relation_{claim.event_ids[0]}"
            graph.claims[claim.claim_id] = ClaimNode.from_claim(
                claim, {edge_id: claim.claim_type or "detail"}
            )
        for event in events:
            edge_id = f"event_claim_relation_{event.event_id}"
            event_claims = claims_by_event.get(event.event_id, [])
            graph.event_claim_relations[edge_id] = EventClaimRelation(
                id=edge_id,
                relation={c.claim_id: c.claim_type or "detail" for c in event_claims},
                weights={c.claim_id: c.confidence for c in event_claims},
                event_node_id=event.event_id,
                extraction_confidence=min((c.confidence for c in event_claims), default=0.8),
            )
            scope_edges = {
                f"scope_event_relation_{scope.scope_id}": scope_roles[
                    scope.scope_id
                ][event.event_id]
                for scope in scopes_by_event.get(event.event_id, [])
            }
            graph.events[event.event_id] = EventNode.from_event(event, edge_id, scope_edges)
        for scope in scopes:
            edge_id = f"scope_event_relation_{scope.scope_id}"
            graph.scope_event_relations[edge_id] = ScopeEventRelation(
                id=edge_id,
                relation=scope_roles[scope.scope_id],
                weights=scope_weights[scope.scope_id],
                scope_node_id=scope.scope_id,
                coherence_score=1.0 if len(scope.event_ids) == 1 else 0.8,
            )
            graph.scopes[scope.scope_id] = ScopeNode.from_scope(scope, edge_id)
        return graph

    async def build(
        self,
        data_folder: str | Path,
        output_dir: str | Path,
        *,
        book_id: str = "book1",
        limit: int | None = None,
    ) -> Path:
        data_folder = Path(data_folder)
        output_dir = Path(output_dir)
        cache_dir = output_dir / "cache" / SCHEMA_VERSION
        _status(
            "build starting: "
            f"model={getattr(self.llm, 'model', 'unknown')}, "
            f"concurrency={self.concurrency}, "
            f"low_weight_repool={self.enable_low_weight_repool}, "
            f"threshold={self.event_scope_weight_threshold:.3f}, "
            f"scope_event_shuffle={self.shuffle_scope_events}, "
            f"shuffle_seed={self.scope_event_shuffle_seed}, "
            f"scope_candidate_top_k={self.scope_candidate_top_k}, "
            f"embedding_model={getattr(self.embedding_provider, 'model_name', 'missing')}"
        )
        _status(f"source={data_folder.resolve()}")
        _status(f"output={output_dir.resolve()}")
        events = await self._events(data_folder, book_id, cache_dir, limit)
        scope_result = await self._scopes(events, cache_dir)
        scopes = scope_result.scopes
        claims = await self._claims(events, scopes, cache_dir)
        if any(len(claim.event_ids) != 1 for claim in claims):
            raise RuntimeError("EPBench Claim provenance invariant failed")
        state_payload = await self._states(
            claims,
            events,
            cache_dir,
        )
        graph = self._graph(
            events,
            scopes,
            claims,
            scope_result.roles,
            scope_result.weights,
        )
        output_path = output_dir / "graph.json"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "dataset": "epbench",
            "mode": "strict",
            "build_signature": self.build_signature,
            "event_signature": self.event_signature,
            "scope_signature": self.scope_signature,
            "claim_signature": self.claim_signature,
            "state_signature": self.state_signature,
            "extraction_model": str(getattr(self.llm, "model", "unknown")),
            "book_id": book_id,
            "source": str(data_folder.resolve()),
            "low_weight_repool": asdict(scope_result.repool_stats),
            **attach_states(graph.to_dict(), state_payload),
        }
        _atomic_json(output_path, payload)
        _status(
            "graph complete: "
            f"events={len(events)}, scopes={len(scopes)}, "
            f"claims={len(claims)}, "
            f"states={state_payload['summary']['state_count']}"
        )
        _status(f"graph saved: {output_path.resolve()}")
        return output_path

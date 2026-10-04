"""
STSGraph Extraction (Scope-based Claim Extraction)

Features:
1. Read event files
2. Use scope_extractor to extract scopes and event relations (first)
3. Use claim_extractor to extract claims and claim relations based on scopes (second)
4. Thread Claims into STS States
5. Use relation_extractor to build the base graph
6. Attach State -> Claim structure and save

Data flow:
events → scopes → claims → STS states → Claim evidence links → save
"""

import json
import sys
import asyncio
import random
from collections import deque
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TimeElapsedColumn, TimeRemainingColumn
)
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sts.utils.datetime_utils import from_iso_format, to_iso_format
from sts.providers.base import LLMProvider
from sts.graph.types import Event, RawDataType, Claim, Scope
from sts.extraction.claim_extractor import (
    ClaimExtractor,
    ClaimExtractResult,
    EventClaimRelationExtractResult
)
from sts.extraction.scope_extractor import (
    ScopeExtractor,
    ScopeExtractRequest,
    ScopeExtractResult,
    ScopeEventRelationExtractResult,
    LowWeightRepoolStats,
    collect_weak_event_scope_relations,
    validate_event_scope_integrity,
)
from sts.extraction.relation_extractor import STSGraphBuilder
from sts.extraction.state_extractor import StateExtractor
from sts.state import StateThreadBuilder, StateThreadConfig
from sts.state.embedding_adapter import CachedEmbeddingService
from sts.state.persistence import attach_states
from sts.graph.schema import STSGraph, EventClaimRelation, ScopeEventRelation

from sts.config import ExperimentConfig
import dataclasses

console = Console()

# Extraction failure retry configuration
MAX_EXTRACTION_RETRIES = 100


class ScopeExtractorType:
    """Scope extractor type"""
    LLM = "llm"
    RETRIEVAL = "retrieval"


def order_events_for_scope_extraction(
    events: List[Event],
    *,
    shuffle: bool,
    seed: int,
) -> List[Event]:
    """Return a reproducible Scope-building order without mutating Events."""

    ordered_events = list(events)
    if shuffle:
        random.Random(seed).shuffle(ordered_events)
    return ordered_events


def serialize_to_json(obj):
    """Recursively serialize an object to a JSON-compatible dictionary"""
    if obj is None:
        return None
    elif isinstance(obj, datetime):
        return to_iso_format(obj)
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result = {}
        for field in dataclasses.fields(obj):
            value = getattr(obj, field.name)
            result[field.name] = serialize_to_json(value)
        return result
    elif hasattr(obj, 'model_dump'):
        try:
            return obj.model_dump(mode='json')
        except:
            dumped = obj.model_dump()
            return serialize_to_json(dumped)
    elif hasattr(obj, 'to_dict'):
        return obj.to_dict()
    elif isinstance(obj, dict):
        return {k: serialize_to_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [serialize_to_json(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    else:
        return str(obj)


# ==================== Claim Result Save/Load ====================

def save_claim_results(
    conv_id: str,
    claim_results: List[ClaimExtractResult],
    event_claim_relation_results: List[EventClaimRelationExtractResult],
    save_dir: Path
) -> None:
    """
    Save claim extraction results

    Args:
        conv_id: Conversation ID
        claim_results: List of claim extraction results (one per scope)
        event_claim_relation_results: List of claim relation extraction results
        save_dir: Save directory
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    output_file = save_dir / f"claims_conv_{conv_id}.json"

    data = {
        "claim_results": [serialize_to_json(r) for r in claim_results],
        "event_claim_relation_results": [serialize_to_json(r) for r in event_claim_relation_results]
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_state_payload(
    claim_results: List[ClaimExtractResult],
    events: List[Event],
    embedding_provider,
    cache_path: Path,
) -> dict:
    """Build Claim-derived States without introducing State-to-Event edges."""
    if embedding_provider is None:
        raise RuntimeError("STS State construction requires embeddings")
    builder = StateThreadBuilder(
        CachedEmbeddingService(embedding_provider, cache_path),
        StateThreadConfig(min_claim_confidence=0.0),
    )
    events_by_id = {event.event_id: event for event in events}
    scope_results = [
        builder.build_scope(
            claim_result.scope_id,
            claim_result.claims,
            events_by_id,
        )
        for claim_result in claim_results
    ]
    assignments = {
        claim.claim_id: claim.state_id
        for claim_result in claim_results
        for claim in claim_result.claims
    }
    payload = {
        "schema_version": "sts-state-build-v1",
        "embedding_model": embedding_provider.model_name,
        "config": builder.config.to_dict(),
        "scope_results": [
            result.to_dict() for result in scope_results
        ],
        "claim_state_assignments": assignments,
        "summary": {
            "scope_count": len(scope_results),
            "input_claim_count": len(assignments),
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
            "QA graph requires every Claim to belong to a State"
        )
    return payload


def save_state_payload(
    conv_id: str,
    payload: dict,
    states_dir: Path,
) -> None:
    states_dir.mkdir(parents=True, exist_ok=True)
    output = states_dir / f"states_conv_{conv_id}.json"
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def reconstruct_claim(data: dict) -> Claim:
    """Reconstruct a Claim object from a dictionary"""
    timestamp = None
    if data.get('timestamp'):
        try:
            timestamp = from_iso_format(data['timestamp'])
        except:
            pass

    # Handle spatial field: LLM may return a list, need to convert to string
    spatial = data.get('spatial')
    if isinstance(spatial, list):
        spatial = ', '.join(str(s) for s in spatial) if spatial else None

    # Handle temporal field: LLM may return a list, need to convert to string
    temporal = data.get('temporal')
    if isinstance(temporal, list):
        temporal = ', '.join(str(t) for t in temporal) if temporal else None

    return Claim(
        claim_id=data['claim_id'],
        content=data['content'],
        event_ids=data.get('event_ids', []),
        scope_id=data.get('scope_id', ''),
        confidence=data.get('confidence', 0.8),
        temporal=temporal,
        spatial=spatial,
        keywords=data.get('keywords', []),
        query_patterns=data.get('query_patterns', []),
        timestamp=timestamp
    )


def reconstruct_event_claim_relation(data: dict) -> EventClaimRelation:
    """Reconstruct a EventClaimRelation object from a dictionary"""
    created_at = None
    if data.get('created_at'):
        try:
            created_at = from_iso_format(data['created_at'])
        except:
            pass

    return EventClaimRelation(
        id=data['id'],
        relation=data.get('relation', {}),
        weights=data.get('weights'),
        event_node_id=data.get('event_node_id', ''),
        created_at=created_at,
        extraction_confidence=data.get('extraction_confidence', 0.8)
    )


def load_claim_results(
    conv_id: str,
    save_dir: Path
) -> Optional[tuple[List[ClaimExtractResult], List[EventClaimRelationExtractResult]]]:
    """
    Load claim extraction results

    Args:
        conv_id: Conversation ID
        save_dir: Save directory

    Returns:
        (list of claim extraction results, list of claim relation extraction results) or None
    """
    input_file = save_dir / f"claims_conv_{conv_id}.json"

    if not input_file.exists():
        return None

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Rebuild ClaimExtractResult list
        claim_results = []
        for item in data['claim_results']:
            claims = [reconstruct_claim(e) for e in item.get('claims', [])]
            result = ClaimExtractResult(
                scope_id=item['scope_id'],
                claims=claims,
                reasoning=item.get('reasoning', '')
            )
            claim_results.append(result)

        # Rebuild EventClaimRelationExtractResult list
        event_claim_relation_results = []
        for item in data['event_claim_relation_results']:
            event_claim_relation = None
            if item.get('event_claim_relation'):
                event_claim_relation = reconstruct_event_claim_relation(item['event_claim_relation'])

            result = EventClaimRelationExtractResult(
                scope_id=item['scope_id'],
                event_id=item['event_id'],
                event_claim_relation=event_claim_relation,
                role_assignment_result=None
            )
            event_claim_relation_results.append(result)

        return (claim_results, event_claim_relation_results)

    except Exception as e:
        console.print(f"[yellow][!] Failed to load claim results: {e}[/yellow]")
        import traceback
        traceback.print_exc()
        return None


# ==================== Token Statistics Save/Load ====================

def save_token_stats(
    conv_id: str,
    scope_token_stats: Optional[Dict],
    claim_token_stats: Optional[Dict],
    state_token_stats: Optional[Dict],
    save_dir: Path
) -> None:
    """
    Save token usage statistics

    Note: The total field will be calculated collectively after retrieval ends; it is not calculated here.

    Args:
        conv_id: Conversation ID
        scope_token_stats: Token statistics for scope extraction
        claim_token_stats: Token statistics for claim extraction
        state_token_stats: Token statistics for State summary extraction
        save_dir: Save directory
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    output_file = save_dir / f"token_stats_conv_{conv_id}.json"

    # Note: total is not calculated here; it will be calculated collectively after retrieval ends
    data = {
        "conv_id": conv_id,
        "scope_extraction": scope_token_stats,
        "claim_extraction": claim_token_stats,
        "state_extraction": state_token_stats,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_token_stats(conv_id: str, save_dir: Path) -> Optional[Dict]:
    """Load token statistics"""
    input_file = save_dir / f"token_stats_conv_{conv_id}.json"

    if not input_file.exists():
        return None

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ==================== Scope Result Save/Load ====================

def save_scope_results(
    conv_id: str,
    scope_result: Optional[ScopeExtractResult],
    scope_event_relation_results: List[ScopeEventRelationExtractResult],
    save_dir: Path
) -> None:
    """Save scope extraction results"""
    save_dir.mkdir(parents=True, exist_ok=True)
    output_file = save_dir / f"scopes_conv_{conv_id}.json"

    data = {
        "scope_result": serialize_to_json(scope_result),
        "scope_event_relation_results": [serialize_to_json(r) for r in scope_event_relation_results]
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def reconstruct_scope(data: dict) -> Scope:
    """Reconstruct a Scope object from a dictionary"""
    timestamp = None
    if data.get('timestamp'):
        try:
            timestamp = from_iso_format(data['timestamp'])
        except:
            pass

    return Scope(
        scope_id=data['scope_id'],
        title=data['title'],
        summary=data['summary'],
        event_ids=data.get('event_ids', []),
        timestamp=timestamp,
        user_id_list=data.get('user_id_list', []),
        participants=data.get('participants', []),
        keywords=data.get('keywords', []),
    )


def reconstruct_scope_event_relation(data: dict) -> ScopeEventRelation:
    """Reconstruct an ScopeEventRelation object from a dictionary"""
    created_at = None
    if data.get('created_at'):
        try:
            created_at = from_iso_format(data['created_at'])
        except:
            pass

    return ScopeEventRelation(
        id=data['id'],
        relation=data.get('relation', {}),
        weights=data.get('weights'),
        scope_node_id=data.get('scope_node_id', ''),
        created_at=created_at,
        coherence_score=data.get('coherence_score', 0.8)
    )


def load_scope_results(
    conv_id: str,
    save_dir: Path
) -> Optional[tuple[Optional[ScopeExtractResult], List[ScopeEventRelationExtractResult]]]:
    """Load scope extraction results"""
    input_file = save_dir / f"scopes_conv_{conv_id}.json"

    if not input_file.exists():
        return None

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        scope_result = None
        if data['scope_result']:
            scopes = [reconstruct_scope(s) for s in data['scope_result']['scopes']]
            scope_result = ScopeExtractResult(
                scopes=scopes,
                action=data['scope_result'].get('action', 'create_new'),
                similar_scope_result=None
            )

        scope_event_relation_results = []
        for item in data['scope_event_relation_results']:
            scope_event_relation = None
            if item['scope_event_relation']:
                scope_event_relation = reconstruct_scope_event_relation(item['scope_event_relation'])

            result = ScopeEventRelationExtractResult(
                scope_id=item['scope_id'],
                scope_event_relation=scope_event_relation,
                role_weight_result=None
            )
            scope_event_relation_results.append(result)

        return (scope_result, scope_event_relation_results)

    except Exception as e:
        console.print(f"[yellow][!] Failed to load scope results: {e}[/yellow]")
        import traceback
        traceback.print_exc()
        return None


def load_events_from_json(file_path: str) -> List[Event]:
    """Load a list of Events from a JSON file"""
    with open(file_path, "r", encoding="utf-8") as f:
        event_dicts = json.load(f)

    events = []
    for event_dict in event_dicts:
        if "timestamp" in event_dict and event_dict["timestamp"]:
            ts = event_dict["timestamp"]
            if isinstance(ts, str):
                event_dict["timestamp"] = from_iso_format(ts)
            elif isinstance(ts, (int, float)):
                event_dict["timestamp"] = datetime.fromtimestamp(ts)

        if "type" in event_dict and event_dict["type"]:
            try:
                event_dict["type"] = RawDataType(event_dict["type"])
            except ValueError:
                event_dict["type"] = RawDataType.CONVERSATION


        event = Event(**event_dict)
        events.append(event)

    return events


# ==================== Scope Extraction ====================

async def extract_scopes_for_events(
    events: List[Event],
    llm_provider: LLMProvider,
    extractor_type: str = ScopeExtractorType.LLM,
    embedding_provider=None,
    progress: Optional[Progress] = None,
    task_id: Optional[int] = None
) -> tuple[Optional[ScopeExtractResult], List[ScopeEventRelationExtractResult]]:
    """
    Extract scopes and event relations for a list of Events

    Args:
        events: List of Events
        llm_provider: LLM provider
        extractor_type: Scope extractor type
        embedding_provider: Embedding provider
        progress: Progress bar object
        task_id: Progress task ID

    Returns:
        (scope extraction result, list of event relation extraction results)
    """
    if not events:
        return None, []

    console.print("  [*] Using LLM-based scope matching (ScopeExtractor)")
    scope_extractor = ScopeExtractor(
        llm_provider=llm_provider,
        scope_match_batch_size=10,
    )

    scope_map: Dict[str, Scope] = {}
    relation_map: Dict[str, ScopeEventRelationExtractResult] = {}
    events_by_id = {event.event_id: event for event in events}
    scope_input_events = order_events_for_scope_extraction(
        events,
        shuffle=ExperimentConfig.shuffle_scope_events,
        seed=ExperimentConfig.scope_event_shuffle_seed,
    )
    if ExperimentConfig.shuffle_scope_events:
        console.print(
            "  [*] Event processing order shuffled before Scope construction "
            f"(seed={ExperimentConfig.scope_event_shuffle_seed})"
        )
        console.print(
            "  [dim]   └─ "
            + " -> ".join(event.event_id for event in scope_input_events)
            + "[/dim]"
        )
    pending_events = deque((event, False) for event in scope_input_events)
    rejected_scopes_by_event: Dict[str, set[str]] = {}
    queued_repool_event_ids: set[str] = set()
    completed_repool_event_ids: set[str] = set()
    terminal_scope_by_event: Dict[str, str] = {}
    repool_stats = LowWeightRepoolStats(
        threshold=ExperimentConfig.event_scope_weight_threshold
    )
    original_events_processed = 0
    processed_original_event_ids: List[str] = []

    async def rebuild_scope(scope_id: str) -> bool:
        scope = scope_map[scope_id]
        if not scope.event_ids:
            scope_map.pop(scope_id)
            relation_map.pop(scope_id, None)
            repool_stats.deleted_empty_scopes += 1
            return False
        remaining_events = [
            events_by_id[event_id] for event_id in scope.event_ids
        ]
        rebuilt = await scope_extractor._rebuild_existing_scope(
            scope, remaining_events
        )
        scope_map[scope_id] = rebuilt
        relation_map[scope_id] = await scope_extractor._build_scope_event_relation(
            rebuilt, remaining_events
        )
        return True

    async def detach_weak_relations_and_enqueue(
        scope_ids_to_check: set[str],
    ) -> None:
        if not ExperimentConfig.enable_low_weight_repool:
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
            weak_relations = collect_weak_event_scope_relations(
                {
                    scope_id: scope_map[scope_id]
                    for scope_id in current_scope_ids
                },
                {
                    scope_id: relation_map[scope_id]
                    for scope_id in current_scope_ids
                },
                ExperimentConfig.event_scope_weight_threshold,
            )
            weak_relations = [
                relation
                for relation in weak_relations
                if terminal_scope_by_event.get(relation.event_id)
                != relation.scope_id
            ]
            if not weak_relations:
                return

            affected_scope_ids = set()
            events_requiring_terminal_scope = set()
            for weak_relation in weak_relations:
                scope = scope_map[weak_relation.scope_id]
                scope.event_ids = [
                    event_id
                    for event_id in scope.event_ids
                    if event_id != weak_relation.event_id
                ]
                scope_relation = relation_map[
                    weak_relation.scope_id
                ].scope_event_relation
                if scope_relation is None:
                    raise RuntimeError(
                        "Missing ScopeEventRelation for Scope "
                        f"{weak_relation.scope_id}"
                    )
                scope_relation.relation.pop(weak_relation.event_id, None)
                if scope_relation.weights is not None:
                    scope_relation.weights.pop(weak_relation.event_id, None)

                rejected_scopes_by_event.setdefault(
                    weak_relation.event_id, set()
                ).add(weak_relation.scope_id)
                affected_scope_ids.add(weak_relation.scope_id)
                repool_stats.weak_relations += 1
                repool_stats.detached_relations += 1

                if weak_relation.event_id in completed_repool_event_ids:
                    if weak_relation.event_id not in terminal_scope_by_event:
                        events_requiring_terminal_scope.add(
                            weak_relation.event_id
                        )
                elif weak_relation.event_id not in queued_repool_event_ids:
                    pending_events.append(
                        (events_by_id[weak_relation.event_id], True)
                    )
                    queued_repool_event_ids.add(weak_relation.event_id)
                    console.print(
                        "  [yellow]↩ Low-weight Event queued at tail: "
                        f"{weak_relation.event_id} "
                        f"({weak_relation.weight:.3f} < "
                        f"{ExperimentConfig.event_scope_weight_threshold})"
                        "[/yellow]"
                    )

            for event_id in sorted(events_requiring_terminal_scope):
                event = events_by_id[event_id]
                terminal_scope = await scope_extractor._extract_new_scope([event])
                if terminal_scope is None:
                    raise RuntimeError(
                        f"Failed to create terminal Scope for {event_id}"
                    )
                scope_map[terminal_scope.scope_id] = terminal_scope
                relation_map[terminal_scope.scope_id] = (
                    await scope_extractor._build_scope_event_relation(
                        terminal_scope, [event]
                    )
                )
                terminal_scope_by_event[event_id] = terminal_scope.scope_id
                repool_stats.created_scopes += 1

            rebuilt_scope_ids = set()
            for scope_id in sorted(affected_scope_ids):
                if await rebuild_scope(scope_id):
                    rebuilt_scope_ids.add(scope_id)
            scopes_to_check = rebuilt_scope_ids

    async def process_repool_event(event: Event) -> set[str]:
        rejected = rejected_scopes_by_event.get(event.event_id, set())
        candidates = [
            scope
            for scope_id, scope in scope_map.items()
            if scope_id not in rejected
        ]
        matched_scope_ids = list(
            dict.fromkeys(
                await scope_extractor._llm_match_scopes(event, candidates)
            )
        )
        changed_scope_ids = set()
        for scope_id in matched_scope_ids:
            if (
                scope_id not in scope_map
                or event.event_id in scope_map[scope_id].event_ids
            ):
                continue
            updated = await scope_extractor._update_existing_scope(
                scope_map[scope_id], event
            )
            if updated is None:
                raise RuntimeError(
                    f"Scope update failed while repooling {event.event_id}"
                )
            scope_map[scope_id] = updated
            scope_events = [
                events_by_id[event_id] for event_id in updated.event_ids
            ]
            relation_map[scope_id] = (
                await scope_extractor._build_scope_event_relation(
                    updated, scope_events
                )
            )
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

        new_scope = await scope_extractor._extract_new_scope([event])
        if new_scope is None:
            raise RuntimeError(
                f"Scope creation failed while repooling {event.event_id}"
            )
        scope_map[new_scope.scope_id] = new_scope
        relation_map[new_scope.scope_id] = (
            await scope_extractor._build_scope_event_relation(
                new_scope, [event]
            )
        )
        repool_stats.created_scopes += 1
        return {new_scope.scope_id}

    while pending_events:
        new_event, is_repool = pending_events.popleft()
        if is_repool:
            queued_repool_event_ids.discard(new_event.event_id)
            completed_repool_event_ids.add(new_event.event_id)
        else:
            original_events_processed += 1

        retry_count = 0
        while True:
            try:
                if is_repool:
                    changed_scope_ids = await process_repool_event(new_event)
                else:
                    request = ScopeExtractRequest(
                        history_event_list=[
                            events_by_id[event_id]
                            for event_id in processed_original_event_ids
                        ],
                        new_event=new_event,
                        existing_scopes=list(scope_map.values()),
                    )
                    scope_result, relation_results = (
                        await scope_extractor.extract_scope(request)
                    )
                    changed_scope_ids = set()
                    if scope_result:
                        for scope in scope_result.scopes:
                            scope_map[scope.scope_id] = scope
                            changed_scope_ids.add(scope.scope_id)
                    for result in relation_results:
                        if result.scope_event_relation:
                            relation_map[result.scope_id] = result
                    processed_original_event_ids.append(new_event.event_id)
                await detach_weak_relations_and_enqueue(changed_scope_ids)
                break
            except Exception as error:
                retry_count += 1
                if retry_count >= MAX_EXTRACTION_RETRIES:
                    raise RuntimeError(
                        "Scope extraction failed after "
                        f"{MAX_EXTRACTION_RETRIES} attempts for "
                        f"{new_event.event_id} (repool={is_repool})"
                    ) from error
                console.print(
                    "[yellow][!] Scope extraction failed "
                    f"(event={new_event.event_id}, repool={is_repool}, "
                    f"retry {retry_count}/{MAX_EXTRACTION_RETRIES}): "
                    f"{error}[/yellow]"
                )

        if progress and task_id is not None:
            progress.update(
                task_id,
                completed=max(0, original_events_processed - 1),
            )

    validate_event_scope_integrity(
        scope_map,
        relation_map,
        [event.event_id for event in events],
    )
    if ExperimentConfig.enable_low_weight_repool:
        console.print(
            "  [+] Low-weight Event-Scope repool complete: "
            f"threshold={repool_stats.threshold}, "
            f"weak={repool_stats.weak_relations}, "
            f"detached={repool_stats.detached_relations}, "
            f"rematched={repool_stats.rematched_relations}, "
            f"created={repool_stats.created_scopes}, "
            f"retained_elsewhere={repool_stats.retained_elsewhere}, "
            f"deleted_empty={repool_stats.deleted_empty_scopes}"
        )

    return ScopeExtractResult(
        scopes=list(scope_map.values()),
        action="merged",
    ), list(relation_map.values())


# ==================== Scope-based Claim Extraction ====================

async def extract_claims_for_scopes(
    scopes: List[Scope],
    events: List[Event],
    llm_provider: LLMProvider,
    progress: Optional[Progress] = None,
    task_id: Optional[int] = None
) -> tuple[List[ClaimExtractResult], List[EventClaimRelationExtractResult]]:
    """
    Extract claims based on scopes

    Args:
        scopes: List of scopes
        events: List of all Events
        llm_provider: LLM provider
        progress: Progress bar object
        task_id: Progress task ID

    Returns:
        (list of claim extraction results, list of claim relation extraction results)
    """
    claim_extractor = ClaimExtractor(llm_provider=llm_provider)

    # Build event_id -> Event mapping
    event_map: Dict[str, Event] = {mc.event_id: mc for mc in events}

    claim_results = []
    event_claim_relation_results = []

    for idx, scope in enumerate(scopes):
        if progress and task_id is not None:
            progress.update(task_id, completed=idx)

        # Get events associated with this scope
        scope_events = [
            event_map[mc_id]
            for mc_id in scope.event_ids
            if mc_id in event_map
        ]

        if not scope_events:
            console.print(f"  [yellow][!] Scope {scope.scope_id} has no associated events, skipping[/yellow]")
            continue

        # Claim extraction retry logic
        retry_count = 0
        success = False

        while retry_count < MAX_EXTRACTION_RETRIES and not success:
            try:
                # Extract claims based on scopes and associated events
                claim_result, relation_result_list = await claim_extractor.extract_claims(
                    scope=scope,
                    events=scope_events
                )

                if claim_result:
                    claim_results.append(claim_result)
                if relation_result_list:
                    event_claim_relation_results.extend(relation_result_list)

                success = True

            except Exception as e:
                retry_count += 1
                if retry_count < MAX_EXTRACTION_RETRIES:
                    console.print(f"[yellow][!] Scope {scope.scope_id} claim extraction failed (retry {retry_count}/{MAX_EXTRACTION_RETRIES}): {e}[/yellow]")
                else:
                    console.print(f"[red][X] Scope {scope.scope_id} claim extraction failed, max retries reached: {e}[/red]")
                    break

    if progress and task_id is not None:
        progress.update(task_id, completed=len(scopes))

    return claim_results, event_claim_relation_results


# ==================== Process Single Conversation ====================

async def process_single_conversation(
    conv_id: str,
    events_file: Path,
    save_dir: Path,
    llm_provider: LLMProvider,
    extractor_type: str = ScopeExtractorType.LLM,
    embedding_provider=None,
    progress: Optional[Progress] = None,
    conv_task_id: Optional[int] = None,
    skip_existing: bool = True,
    claims_dir: Optional[Path] = None,
    scopes_dir: Optional[Path] = None,
    states_dir: Optional[Path] = None,
) -> Optional[STSGraph]:
    """
    Process graph extraction for a single conversation (new pipeline: scopes first, then claims)

    Args:
        conv_id: Conversation ID
        events_file: Event JSON file path
        save_dir: Save directory (graphs/)
        llm_provider: LLM provider
        extractor_type: Scope extractor type
        embedding_provider: Embedding provider
        progress: Progress bar object
        conv_task_id: Conversation task ID
        skip_existing: Whether to skip existing graph files
        claims_dir: Claim results save directory
        scopes_dir: Scope results save directory

    Returns:
        The constructed graph object
    """
    try:
        output_file = save_dir / f"graph_conv_{conv_id}.json"
        console.print(f"  [dim]Conversation {conv_id}: checking path {output_file}[/dim]")

        if skip_existing and output_file.exists():
            try:
                with open(output_file, "r", encoding="utf-8") as f:
                    graph_dict = json.load(f)
                if graph_dict.get("states"):
                    console.print(
                        f"  [cyan][√] Conversation {conv_id}: "
                        "STS-ready graph already exists, skipping[/cyan]"
                    )
                    if progress and conv_task_id is not None:
                        progress.update(
                            conv_task_id,
                            description=f"[cyan]Conversation {conv_id}[/cyan]",
                            status="[cyan]exists[/cyan]",
                            completed=1,
                        )
                    return STSGraph.from_dict(graph_dict)
                console.print(
                    f"  [yellow][!] Conversation {conv_id}: existing "
                    "graph has no STS States; rebuilding from caches"
                    "[/yellow]"
                )
            except Exception as e:
                console.print(f"  [yellow][!] Conversation {conv_id}: failed to load existing graph: {e}, will reprocess[/yellow]")

        if progress and conv_task_id is not None:
            progress.update(conv_task_id, description=f"[cyan]Conversation {conv_id}[/cyan]", status="loading data")

        # Step 1: Load Events
        events = load_events_from_json(str(events_file))
        console.print(f"  [+] Conversation {conv_id}: loaded {len(events)} Events")

        if not events:
            console.print(f"  [yellow][!] Conversation {conv_id}: no Events, skipping[/yellow]")
            return None

        # Step 2: Extract scopes (first)
        if progress and conv_task_id is not None:
            progress.update(conv_task_id, status="checking scope cache", total=1, completed=0)

        # Scope extraction token statistics
        scope_token_stats = None

        cached_scopes = None
        if scopes_dir and scopes_dir.exists():
            scope_cache_file = scopes_dir / f"scopes_conv_{conv_id}.json"
            if scope_cache_file.exists():
                console.print(f"  [cyan]✓ Found scope cache file: {scope_cache_file.name}[/cyan]")
                try:
                    cached_scopes = load_scope_results(conv_id, scopes_dir)
                    if cached_scopes is not None:
                        console.print("  [green]✓ Scope cache loaded successfully[/green]")
                except Exception as e:
                    console.print(f"  [yellow]⚠ Scope cache loading error: {e}, will re-extract[/yellow]")
                    cached_scopes = None

        if cached_scopes is not None:
            console.print(
                f"  [cyan][√] Conversation {conv_id}: "
                "using cached scope results[/cyan]"
            )
            scope_result, scope_event_relation_results = cached_scopes
            num_scopes = len(scope_result.scopes) if scope_result else 0
            console.print(f"  [cyan]   └─ Number of scopes: {num_scopes}[/cyan]")
        else:
            if progress and conv_task_id is not None:
                progress.update(conv_task_id, status="extract scope", total=len(events) - 1, completed=0)

            console.print(f"  [yellow]→ Conversation {conv_id}: starting scope extraction...[/yellow]")
            try:
                # Reset statistics, record accumulated values before scope extraction
                llm_provider.reset_accumulated_stats()

                scope_result, scope_event_relation_results = await extract_scopes_for_events(
                    events=events,
                    llm_provider=llm_provider,
                    extractor_type=extractor_type,
                    embedding_provider=embedding_provider,
                    progress=progress,
                    task_id=conv_task_id
                )

                # Get token statistics for scope extraction
                scope_token_stats = llm_provider.get_accumulated_stats()
                if scope_token_stats:
                    console.print(f"  [dim]   └─ Scope extraction Token: prompt={scope_token_stats['prompt_tokens']:,}, "
                                  f"completion={scope_token_stats['completion_tokens']:,}, "
                                  f"total={scope_token_stats['total_tokens']:,}[/dim]")

                num_scopes = len(scope_result.scopes) if scope_result else 0
                console.print(f"  [+] Conversation {conv_id}: extracted {num_scopes} scopes")
            except Exception as scope_extract_error:
                console.print(f"[red][-] Conversation {conv_id}: scope extraction failed: {scope_extract_error}[/red]")
                import traceback
                traceback.print_exc()
                raise

            if scopes_dir:
                save_scope_results(conv_id, scope_result, scope_event_relation_results, scopes_dir)
                console.print(f"  [+] Conversation {conv_id}: saved scope results to scopes/")

        # Step 3: Extract claims based on scopes (second)
        if progress and conv_task_id is not None:
            progress.update(conv_task_id, status="checking claim cache", total=1, completed=0)

        # Claim extraction token statistics
        claim_token_stats = None

        cached_claims = None
        if claims_dir and claims_dir.exists():
            claim_cache_file = claims_dir / f"claims_conv_{conv_id}.json"
            if claim_cache_file.exists():
                console.print(f"  [cyan]✓ Found claim cache file: {claim_cache_file.name}[/cyan]")
                try:
                    cached_claims = load_claim_results(conv_id, claims_dir)
                    if cached_claims is not None:
                        console.print("  [green]✓ Claim cache loaded successfully[/green]")
                except Exception as e:
                    console.print(f"  [yellow]⚠ Claim cache loading error: {e}, will re-extract[/yellow]")
                    cached_claims = None

        if cached_claims is not None:
            console.print(
                f"  [cyan][√] Conversation {conv_id}: "
                "using cached claim results[/cyan]"
            )
            claim_results, event_claim_relation_results = cached_claims
        else:
            # Get scope list
            scopes = scope_result.scopes if scope_result else []

            if not scopes:
                console.print(f"  [yellow][!] Conversation {conv_id}: no scopes, skipping claim extraction[/yellow]")
                claim_results = []
                event_claim_relation_results = []
            else:
                if progress and conv_task_id is not None:
                    progress.update(conv_task_id, status="extract claim", total=len(scopes), completed=0)

                console.print(f"  [yellow]→ Conversation {conv_id}: extracting claims based on {len(scopes)} scopes...[/yellow]")

                # Reset statistics, record accumulated values before claim extraction
                llm_provider.reset_accumulated_stats()

                claim_results, event_claim_relation_results = await extract_claims_for_scopes(
                    scopes=scopes,
                    events=events,
                    llm_provider=llm_provider,
                    progress=progress,
                    task_id=conv_task_id
                )

                # Get token statistics for claim extraction
                claim_token_stats = llm_provider.get_accumulated_stats()
                if claim_token_stats:
                    console.print(f"  [dim]   └─ Claim extraction Token: prompt={claim_token_stats['prompt_tokens']:,}, "
                                  f"completion={claim_token_stats['completion_tokens']:,}, "
                                  f"total={claim_token_stats['total_tokens']:,}[/dim]")

                # Count claims
                total_claims = sum(len(r.claims) for r in claim_results)
                if total_claims > 0:
                    console.print(f"  [+] Conversation {conv_id}: extracted {total_claims} claims")
                else:
                    console.print(f"  [red][-] Conversation {conv_id}: claim extraction returned 0 claims[/red]")
                    if progress and conv_task_id is not None:
                        progress.update(conv_task_id, status="[yellow]claims=0[/yellow]")

            if claims_dir:
                save_claim_results(conv_id, claim_results, event_claim_relation_results, claims_dir)
                console.print(f"  [+] Conversation {conv_id}: saved claim results to claims/")

        # Step 4: Build graph
        if progress and conv_task_id is not None:
            progress.update(
                conv_task_id,
                status="threading Claims into States",
                total=1,
                completed=0,
            )

        resolved_states_dir = states_dir or save_dir.parent / "states"
        state_payload = await asyncio.to_thread(
            build_state_payload,
            claim_results,
            events,
            embedding_provider,
            resolved_states_dir
            / f"state_embedding_cache_conv_{conv_id}.json",
        )
        claims_by_id = {
            claim.claim_id: claim
            for claim_result in claim_results
            for claim in claim_result.claims
        }
        llm_provider.reset_accumulated_stats()
        state_payload = await StateExtractor(
            llm_provider,
            max_concurrency=ExperimentConfig.max_concurrent_requests,
        ).extract(state_payload, claims_by_id)
        state_token_stats = llm_provider.get_accumulated_stats()
        if state_token_stats:
            console.print(
                "  [dim]   └─ State extraction Token: "
                f"prompt={state_token_stats['prompt_tokens']:,}, "
                f"completion={state_token_stats['completion_tokens']:,}, "
                f"total={state_token_stats['total_tokens']:,}[/dim]"
            )
        save_state_payload(
            conv_id, state_payload, resolved_states_dir
        )
        console.print(
            f"  [+] Conversation {conv_id}: built "
            f"{state_payload['summary']['state_count']} STS States from "
            f"{state_payload['summary']['assigned_claim_count']} Claims"
        )

        # Step 5: Build graph
        if progress and conv_task_id is not None:
            progress.update(
                conv_task_id,
                status="building graph",
                total=1,
                completed=0,
            )

        relation_extractor = STSGraphBuilder()
        graph = relation_extractor.build_graph(
            events=events,
            claim_results=claim_results,
            event_claim_relation_results=event_claim_relation_results,
            scope_extract_result=scope_result,
            scope_event_relation_results=scope_event_relation_results
        )

        stats = graph.get_stats()
        console.print(f"  [+] Conversation {conv_id}: built graph - {stats}")

        # Step 6: Save graph
        if progress and conv_task_id is not None:
            progress.update(conv_task_id, status="saving graph", completed=1)

        graph_dict = attach_states(
            graph.to_dict(), state_payload
        )
        output_file = save_dir / f"graph_conv_{conv_id}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(graph_dict, f, ensure_ascii=False, indent=2)

        console.print(f"  [+] Conversation {conv_id}: saved graph to {output_file.name}")

        # Step 7: Save token statistics (if available)
        if scope_token_stats or claim_token_stats or state_token_stats:
            token_stats_dir = save_dir.parent / "token_stats"
            save_token_stats(
                conv_id,
                scope_token_stats,
                claim_token_stats,
                state_token_stats,
                token_stats_dir,
            )

            # Calculate total token count
            total_prompt = sum(
                (stats or {}).get("prompt_tokens", 0)
                for stats in (
                    scope_token_stats,
                    claim_token_stats,
                    state_token_stats,
                )
            )
            total_completion = sum(
                (stats or {}).get("completion_tokens", 0)
                for stats in (
                    scope_token_stats,
                    claim_token_stats,
                    state_token_stats,
                )
            )
            total_tokens = total_prompt + total_completion
            console.print(f"  [dim]   └─ Total Token: prompt={total_prompt:,}, completion={total_completion:,}, total={total_tokens:,}[/dim]")

        if progress and conv_task_id is not None:
            total_claims = sum(len(r.claims) for r in claim_results) if claim_results else 0
            if total_claims > 0:
                progress.update(conv_task_id, status="[green]done[/green]", completed=1)
            else:
                progress.update(conv_task_id, status="[yellow]done (claims=0)[/yellow]", completed=1)

        return graph

    except Exception as e:
        console.print(f"[red][-] Conversation {conv_id} processing failed: {e}[/red]")
        if progress and conv_task_id is not None:
            progress.update(conv_task_id, status="[red]failed[/red]")
        import traceback
        traceback.print_exc()
        return None


async def process_conversation_with_semaphore(
    semaphore: asyncio.Semaphore,
    conv_id: str,
    events_file: Path,
    save_dir: Path,
    llm_provider: LLMProvider,
    extractor_type: str = ScopeExtractorType.LLM,
    embedding_provider=None,
    progress: Optional[Progress] = None,
    conv_task_id: Optional[int] = None,
    skip_existing: bool = True,
    claims_dir: Optional[Path] = None,
    scopes_dir: Optional[Path] = None,
    states_dir: Optional[Path] = None,
) -> tuple[str, Optional[STSGraph]]:
    """Conversation processing with semaphore-controlled concurrency"""
    async with semaphore:
        if progress and conv_task_id is not None:
            progress.start_task(conv_task_id)

        graph = await process_single_conversation(
            conv_id=conv_id,
            events_file=events_file,
            save_dir=save_dir,
            llm_provider=llm_provider,
            extractor_type=extractor_type,
            embedding_provider=embedding_provider,
            progress=progress,
            conv_task_id=conv_task_id,
            skip_existing=skip_existing,
            claims_dir=claims_dir,
            scopes_dir=scopes_dir,
            states_dir=states_dir,
        )

        return (conv_id, graph)


async def main():
    """Main function: batch process graph extraction for all conversations"""
    config = ExperimentConfig()

    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]STS graph construction[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")

    # Configure scope extractor type
    extractor_type = ScopeExtractorType.RETRIEVAL

    # Configure paths
    events_dir = config.events_dir()
    graph_dir = config.graph_dir()
    claims_dir = config.claims_dir()
    scopes_dir = config.scopes_dir()
    states_dir = config.states_dir()
    token_stats_dir = config.token_stats_dir()

    # Create directories
    graph_dir.mkdir(parents=True, exist_ok=True)
    claims_dir.mkdir(parents=True, exist_ok=True)
    scopes_dir.mkdir(parents=True, exist_ok=True)
    states_dir.mkdir(parents=True, exist_ok=True)
    token_stats_dir.mkdir(parents=True, exist_ok=True)

    # Concurrency configuration
    max_concurrent_tasks = 10
    skip_existing = True

    console.print(f"[bold]Experiment name:[/bold] {config.experiment_name}")
    console.print(f"[bold]Scope extractor type:[/bold] {extractor_type}")
    console.print(f"[bold]Number of conversations:[/bold] {config.num_conv}")
    console.print(f"[bold]Concurrency:[/bold] {max_concurrent_tasks}")
    console.print(f"[bold]Skip existing:[/bold] {'Yes' if skip_existing else 'No'}")
    console.print("[bold]Pipeline:[/bold] event → scope → claim → graph\n")

    # Initialize LLM Provider (with statistics enabled)
    llm_config = config.llm_config[config.llm_service].copy()
    provider_type = llm_config.pop('llm_provider', 'openai')
    llm_config['enable_stats'] = True  # Enable token statistics
    llm_provider = LLMProvider(provider_type=provider_type, **llm_config)

    # Initialize Embedding Provider
    embedding_provider = None
    if extractor_type == ScopeExtractorType.RETRIEVAL:
        try:
            from sts.providers.embeddings import EmbeddingProvider
            embedding_config = config.embedding_config
            embedding_provider = EmbeddingProvider(
                base_url=embedding_config["base_url"],
                model_name=embedding_config["model_name"],
                api_key=embedding_config.get("api_key", ""),
            )
            console.print(
                "[green][OK][/green] Embedding Provider initialized successfully\n"
            )
        except Exception as e:
            console.print(f"[red][X] Failed to initialize Embedding Provider: {e}[/red]")
            console.print(
                "[yellow][!] Falling back to LLM version[/yellow]\n"
            )
            extractor_type = ScopeExtractorType.LLM

    # Display final configuration
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]Final Configuration[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print(f"[bold]Scope extractor type:[/bold] {extractor_type}")
    console.print(f"[bold]Event directory:[/bold] {events_dir}")
    console.print(f"[bold]STSGraph save directory:[/bold] {graph_dir}")
    console.print(f"[bold]Scope cache directory:[/bold] {scopes_dir}")
    console.print(f"[bold]Claim cache directory:[/bold] {claims_dir}")
    console.print(f"[bold]State cache directory:[/bold] {states_dir}")
    console.print(f"[bold]Token statistics directory:[/bold] {token_stats_dir}")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")

    # Collect all conversation files
    conv_files = []
    for i in range(config.num_conv):
        event_file = events_dir / f"event_list_conv_{i}.json"
        if event_file.exists():
            conv_files.append((str(i), event_file))
        else:
            console.print(f"[yellow][!] File not found: {event_file}[/yellow]")

    if not conv_files:
        console.print("[red][-] No Event files found[/red]")
        return

    console.print(f"[green][OK][/green] Found {len(conv_files)} conversation files\n")

    # Create semaphore
    semaphore = asyncio.Semaphore(max_concurrent_tasks)

    # Create progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.completed:>3}/{task.total:<3}"),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("•"),
        TextColumn("[bold]{task.fields[status]}"),
        console=console,
        transient=False
    ) as progress:

        tasks = []
        for conv_id, event_file in conv_files:
            task_id = progress.add_task(
                f"[cyan]Conversation {conv_id}[/cyan]",
                total=1,
                status="waiting",
                start=False
            )
            tasks.append((conv_id, event_file, task_id))

        coroutines = [
            process_conversation_with_semaphore(
                semaphore=semaphore,
                conv_id=conv_id,
                events_file=event_file,
                save_dir=graph_dir,
                llm_provider=llm_provider,
                extractor_type=extractor_type,
                embedding_provider=embedding_provider,
                progress=progress,
                conv_task_id=task_id,
                skip_existing=skip_existing,
                claims_dir=claims_dir,
                scopes_dir=scopes_dir,
                states_dir=states_dir,
            )
            for conv_id, event_file, task_id in tasks
        ]

        results = await asyncio.gather(*coroutines, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                conv_id = tasks[i][0]
                console.print(f"[red][-] Conversation {conv_id} processing error: {result}[/red]")
                processed_results.append((conv_id, None))
            else:
                processed_results.append(result)

    # Summarize results
    successful = sum(1 for _, hg in processed_results if hg is not None)
    failed = len(processed_results) - successful

    # Aggregate Token statistics
    total_token_summary = {
        'scope_extraction': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'call_count': 0, 'total_duration': 0.0},
        'claim_extraction': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'call_count': 0, 'total_duration': 0.0},
        'total': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'call_count': 0, 'total_duration': 0.0}
    }

    # Read all token statistics files
    for conv_id, _ in processed_results:
        token_stats = load_token_stats(conv_id, token_stats_dir)
        if token_stats:
            for stage in ['scope_extraction', 'claim_extraction']:
                if token_stats.get(stage):
                    for key in ['prompt_tokens', 'completion_tokens', 'total_tokens', 'call_count']:
                        total_token_summary[stage][key] += token_stats[stage].get(key, 0)
                        total_token_summary['total'][key] += token_stats[stage].get(key, 0)
                    # Accumulate total_duration
                    total_token_summary[stage]['total_duration'] += token_stats[stage].get('total_duration', 0.0)
                    total_token_summary['total']['total_duration'] += token_stats[stage].get('total_duration', 0.0)

    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]Processing Complete[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")
    console.print(f"[bold green][OK] Succeeded:[/bold green] {successful}/{len(processed_results)} conversations")
    if failed > 0:
        console.print(f"[bold red][X] Failed:[/bold red] {failed}/{len(processed_results)} conversations")

    # Print Token statistics summary
    if total_token_summary['total']['total_tokens'] > 0:
        console.print("\n[bold yellow]Token Usage Summary:[/bold yellow]")
        console.print(f"  Scope extraction: prompt={total_token_summary['scope_extraction']['prompt_tokens']:,}, "
                      f"completion={total_token_summary['scope_extraction']['completion_tokens']:,}, "
                      f"total={total_token_summary['scope_extraction']['total_tokens']:,}, "
                      f"calls={total_token_summary['scope_extraction']['call_count']}")
        console.print(f"  Claim extraction: prompt={total_token_summary['claim_extraction']['prompt_tokens']:,}, "
                      f"completion={total_token_summary['claim_extraction']['completion_tokens']:,}, "
                      f"total={total_token_summary['claim_extraction']['total_tokens']:,}, "
                      f"calls={total_token_summary['claim_extraction']['call_count']}")
        console.print(f"  [bold]Total: prompt={total_token_summary['total']['prompt_tokens']:,}, "
                      f"completion={total_token_summary['total']['completion_tokens']:,}, "
                      f"total={total_token_summary['total']['total_tokens']:,}, "
                      f"calls={total_token_summary['total']['call_count']}[/bold]")

        # Save summary statistics
        summary_file = token_stats_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump({
                "experiment_name": config.experiment_name,
                "num_conversations": len(processed_results),
                "successful": successful,
                "failed": failed,
                "token_usage": total_token_summary
            }, f, ensure_ascii=False, indent=2)
        console.print(f"\n[dim]Token statistics summary saved to: {summary_file}[/dim]")

    console.print(f"\n[bold]STSGraphs saved at:[/bold] {graph_dir}\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

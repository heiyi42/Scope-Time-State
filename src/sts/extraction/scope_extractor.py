"""
Scope Extractor (Retrieval-based) - Four-stage extraction pipeline

Core concept: A scope represents "the same scenario", not a simple similarity aggregation.

Step 1: Event similarity detection (retrieval-based)
- Uses retrieval algorithms (BM25/Embedding) to find historical events similar to the new event
- Output: List of similar events (with scores)

Step 2: Scope similarity detection (retrieval-based)
- Uses retrieval algorithms to find existing scopes related to the new event
- Output: List of similar scopes (with scores)

Step 3: Scope extraction/update (using LLM)
- Case 1: No similar events -> Create a new scope
- Case 2.1: Similar events found, no similar scopes -> Create a new scope
- Case 2.2: Similar events found, similar scopes found -> Update the scope

Step 4: Event role and weight assignment (using LLM)
- Assign roles and importance weights to each event in the scope
- Build event relation (ScopeEventRelation)
"""

import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass

try:
    import json_repair
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False

from sts.utils.logger import get_logger
from sts.providers.base import LLMProvider
from sts.graph.types import Event, Scope
from sts.graph.schema import ScopeEventRelation, EventRole
from sts.prompts.scope_prompts import (
    SCOPE_EXTRACTION_PROMPT,
    SCOPE_UPDATE_PROMPT,
    EVENT_ROLE_WEIGHT_ASSIGNMENT_PROMPT,
    SCOPE_MATCH_PROMPT
)

logger = get_logger(__name__)


@dataclass
class SimilarEvent:
    """Similar event information"""
    event_id: str
    similarity_score: float  # Similarity score (0.0-1.0)
    reasoning: str  # Reason for similarity (retrieval method name)


@dataclass
class SimilarScope:
    """Similar scope information"""
    scope_id: str
    similarity_score: float  # Similarity score (0.0-1.0)
    reasoning: str  # Reason for similarity (retrieval method name)


@dataclass
class SimilarEventResult:
    """Step 1 output: Event similarity detection result"""
    has_similar: bool  # Whether there are similar events
    similar_events: List[SimilarEvent]  # List of similar events
    reasoning: str  # Overall reasoning explanation

    def get_event_ids(self) -> List[str]:
        """Get list of similar event IDs"""
        return [mc.event_id for mc in self.similar_events]


@dataclass
class SimilarScopeResult:
    """Step 2 output: Scope similarity detection result"""
    has_similar: bool  # Whether there are similar scopes
    similar_scopes: List[SimilarScope]  # List of similar scopes
    reasoning: str  # Overall reasoning explanation

    def get_scope_ids(self) -> List[str]:
        """Get list of similar scope IDs"""
        return [s.scope_id for s in self.similar_scopes]


@dataclass
class ScopeExtractRequest:
    """Scope extraction request"""
    history_event_list: List[Event]
    new_event: Event
    existing_scopes: Optional[List[Scope]] = None


@dataclass
class ScopeExtractResult:
    """Scope extraction result (Step 3 output)"""
    scopes: List[Scope]  # List of scopes
    action: str  # "create_new", "update_existing"

    # Step 1 result: Event similarity detection (retrieval)
    similar_event_result: Optional[SimilarEventResult] = None

    # Step 2 result: Scope similarity detection
    similar_scope_result: Optional[SimilarScopeResult] = None


@dataclass
class EventRoleWeightAssignmentResult:
    """Step 4 output: Event role and weight assignment result"""
    event_roles: Dict[str, EventRole]  # event_id -> role
    event_weights: Dict[str, float]  # event_id -> weight
    coherence_score: float  # Scope coherence score
    reasoning: str


@dataclass
class ScopeEventRelationExtractResult:
    """Event relation extraction final result"""
    scope_id: str
    scope_event_relation: Optional[ScopeEventRelation]  # Event relation, None when extraction fails

    # Step result
    role_weight_result: Optional[EventRoleWeightAssignmentResult] = None

    # Statistics
    event_count: int = 0

    def __post_init__(self):
        """Compute statistics"""
        # Event count is calculated from the number of connections in the relation
        if self.scope_event_relation:
            self.event_count = len(self.scope_event_relation.relation)
        else:
            self.event_count = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            "scope_id": self.scope_id,
            "event_count": self.event_count,
            "scope_event_relation": self.scope_event_relation.model_dump() if self.scope_event_relation else None
        }


@dataclass(frozen=True)
class WeakEventScopeRelation:
    """An Event-Scope membership rejected using its raw LLM weight."""

    event_id: str
    scope_id: str
    weight: float


@dataclass
class LowWeightRepoolStats:
    """Summary of low-weight Event-to-Scope reassignment."""

    threshold: float
    weak_relations: int = 0
    detached_relations: int = 0
    rematched_relations: int = 0
    created_scopes: int = 0
    retained_elsewhere: int = 0
    deleted_empty_scopes: int = 0


def collect_weak_event_scope_relations(
    scopes_by_id: Dict[str, Scope],
    relations_by_scope_id: Dict[str, ScopeEventRelationExtractResult],
    threshold: float,
) -> List[WeakEventScopeRelation]:
    """Collect raw Event-Scope weights strictly below ``threshold``."""

    weak_relations = []
    for scope_id, scope in scopes_by_id.items():
        result = relations_by_scope_id.get(scope_id)
        if result is None or result.scope_event_relation is None:
            raise RuntimeError(f"Missing ScopeEventRelation for Scope {scope_id}")
        weights = result.scope_event_relation.weights or {}
        for event_id in scope.event_ids:
            if event_id not in weights:
                raise RuntimeError(
                    f"Missing raw Event-Scope weight for {event_id} -> {scope_id}"
                )
            weight = float(weights[event_id])
            if weight < threshold:
                weak_relations.append(
                    WeakEventScopeRelation(event_id, scope_id, weight)
                )
    return weak_relations


def validate_event_scope_integrity(
    scopes_by_id: Dict[str, Scope],
    relations_by_scope_id: Dict[str, ScopeEventRelationExtractResult],
    event_ids: List[str],
) -> None:
    """Require exact Scope/Relation membership and no orphan Event."""

    membership_count = {event_id: 0 for event_id in event_ids}
    for scope_id, scope in scopes_by_id.items():
        result = relations_by_scope_id.get(scope_id)
        if result is None or result.scope_event_relation is None:
            raise RuntimeError(f"Missing ScopeEventRelation for Scope {scope_id}")
        relation = result.scope_event_relation
        scope_event_ids = set(scope.event_ids)
        relation_event_ids = set(relation.relation)
        weight_event_ids = set(relation.weights or {})
        if scope_event_ids != relation_event_ids or scope_event_ids != weight_event_ids:
            raise RuntimeError(
                f"Event-Scope integrity mismatch for {scope_id}: "
                f"scope={sorted(scope_event_ids)}, "
                f"relation={sorted(relation_event_ids)}, "
                f"weights={sorted(weight_event_ids)}"
            )
        for event_id in scope_event_ids:
            if event_id not in membership_count:
                raise RuntimeError(
                    f"Scope {scope_id} references unknown Event {event_id}"
                )
            membership_count[event_id] += 1

    orphan_event_ids = [
        event_id for event_id, count in membership_count.items() if count == 0
    ]
    if orphan_event_ids:
        raise RuntimeError(
            f"Low-weight repool orphaned Events: {sorted(orphan_event_ids)}"
        )


class ScopeExtractor:
    """
    Scope Extractor — Four-stage extraction pipeline using retrieval-augmented scope detection.
    """

    def __init__(
        self,
        llm_provider=LLMProvider,
        scope_match_batch_size: int = 10,  # Max scopes per LLM matching call
    ):
        """
        Initialize the scope extractor (LLM-based matching)

        Args:
            llm_provider: LLM provider
            scope_match_batch_size: Max number of scopes per LLM matching call (batched if more)
        """
        self.llm_provider = llm_provider
        self.scope_match_batch_size = scope_match_batch_size

    def _format_event_display(self, event: Event, simple_id: str = None) -> str:
        """Format a single event (for LLM display). If simple_id provided, use it instead of UUID."""
        lines = []
        lines.append(f"Event ID: {simple_id if simple_id else event.event_id}")

        if event.participants:
            lines.append(f"Participants: {', '.join(event.participants)}")

        if event.subject:
            lines.append(f"Content: {event.subject}")
        elif event.summary:
            lines.append(f"Content: {event.summary}")

        if event.timestamp:
            lines.append(f"Timestamp: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

        if event.keywords:
            keywords_display = ', '.join(event.keywords[:8])
            lines.append(f"Keywords: {keywords_display}")

        if event.event_description:
            lines.append(f"Event: {event.event_description}")

        return "\n".join(lines)

    def _format_event_list(self, event_list: List[Event], use_simple_ids: bool = False) -> str:
        """Format a list of events. If use_simple_ids, show event_1/event_2 instead of UUIDs."""
        return "\n\n".join([
            f"--- Event {i+1} ---\n{self._format_event_display(mc, simple_id=f'event_{i+1}' if use_simple_ids else None)}"
            for i, mc in enumerate(event_list)
        ])

    def _format_scope_display(self, scope: Scope) -> str:
        """Format a single scope (for LLM display)"""
        lines = []
        lines.append(f"Scope ID: {scope.scope_id}")
        lines.append(f"Title: {scope.title}")

        if scope.timestamp:
            lines.append(f"Last Updated: {scope.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

        if scope.participants:
            lines.append(f"Participants: {', '.join(scope.participants)}")

        lines.append(f"Summary: {scope.summary}")

        event_count = len(scope.event_ids)
        lines.append(f"Event Count: {event_count}")
        if event_count > 0:
            if event_count <= 5:
                lines.append(f"Event IDs: {', '.join(scope.event_ids)}")
            else:
                first_five = ', '.join(scope.event_ids[:5])
                lines.append(f"Event IDs (first 5): {first_five}, ... (+{event_count - 5} more)")

        if scope.keywords:
            lines.append(f"Keywords: {', '.join(scope.keywords)}")

        return "\n".join(lines)

    def _format_scope_list(self, scope_list: List[Scope]) -> str:
        """Format a list of scopes"""
        return "\n\n".join([
            f"--- Scope {i+1} ---\n{self._format_scope_display(s)}"
            for i, s in enumerate(scope_list)
        ])

    def _validate_new_scope_extraction(self, data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate the correctness of new scope extraction results"""
        errors = []

        if "title" not in data:
            errors.append("Missing required field 'title'")
        elif not data.get("title"):
            errors.append("Field 'title' cannot be empty")

        if "summary" not in data:
            errors.append("Missing required field 'summary'")
        elif not data.get("summary"):
            errors.append("Field 'summary' cannot be empty")

        if "keywords" in data and not isinstance(data.get("keywords"), list):
            errors.append("Field 'keywords' must be a list")

        return len(errors) == 0, errors

    async def _extract_new_scope(
        self,
        event_list: List[Event]
    ) -> Optional[Scope]:
        """
        Step 3: Create a new scope (with retry mechanism)
        """
        events_text = self._format_event_list(event_list)

        logger.info(f"[Step3] Creating new scope - event count: {len(event_list)}")

        prompt = SCOPE_EXTRACTION_PROMPT.format(
            events=events_text,
            event_count=len(event_list)
        )

        print("\n" + "="*80)
        print("[Step 3] LLM Input - Create New Scope")
        print("="*80)
        max_display_length = 1000
        if len(prompt) > max_display_length:
            print(prompt[:max_display_length])
            print(f"\n... (truncated, total length: {len(prompt)} characters)")
        else:
            print(prompt)
        print("="*80)

        attempt = 0
        last_feedback = None

        while True:
            try:
                attempt += 1

                # Build current prompt: original prompt + optional validation feedback
                if last_feedback:
                    current_prompt = prompt + f"\n\n[IMPORTANT] Previous attempt failed with the following errors, please fix:\n{last_feedback}"
                else:
                    current_prompt = prompt

                resp = await self.llm_provider.generate(
                    current_prompt,
                    response_format={"type": "json_object"}
                )

                print("\n" + "="*80)
                print(f"[Step 3] LLM Output (attempt {attempt})")
                print("="*80)
                print(resp)
                print("="*80)

                # JSON mode should guarantee valid JSON; use json_repair as fallback
                try:
                    data = json.loads(resp)
                except json.JSONDecodeError:
                    if HAS_JSON_REPAIR:
                        data = json_repair.loads(resp)
                    else:
                        raise

                is_valid, validation_errors = self._validate_new_scope_extraction(data)

                if not is_valid:
                    error_msg = "New scope extraction validation errors:\n" + "\n".join(validation_errors)
                    raise ValueError(error_msg)

                import uuid
                scope_id_val = f"scope_{str(uuid.uuid4())}"

                event_ids = [mc.event_id for mc in event_list]

                user_id_set = set()
                participant_set = set()
                for mc in event_list:
                    user_id_set.update(mc.user_id_list)
                    if mc.participants:
                        participant_set.update(mc.participants)

                last_event = event_list[-1]
                timestamp = last_event.timestamp
                if isinstance(timestamp, int):
                    timestamp = datetime.fromtimestamp(timestamp)
                elif isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

                scope = Scope(
                    scope_id=scope_id_val,
                    title=data.get("title", ""),
                    summary=data.get("summary", ""),
                    event_ids=event_ids,
                    timestamp=timestamp,
                    user_id_list=list(user_id_set),
                    participants=list(participant_set) if participant_set else None,
                    keywords=data.get("keywords", [])
                )

                logger.info(f"[Step3] Created new scope: {scope.title} (attempt {attempt})")
                print(f"  ✓ New scope extraction validation passed (attempt {attempt})")

                return scope

            except (json.JSONDecodeError, ValueError, Exception) as e:
                print(f"  Attempt {attempt} failed: {type(e).__name__}")
                print(f"  Error details: {str(e)}")

                if isinstance(e, json.JSONDecodeError):
                    last_feedback = "JSON parsing failed. Please provide valid JSON format with the following structure:\n{\n  \"title\": \"...\",\n  \"summary\": \"...\",\n  \"keywords\": [...]\n}"
                elif isinstance(e, ValueError) and "validation errors" in str(e):
                    last_feedback = str(e) + "\n\nPlease ensure:\n1. 'title' is present and not empty\n2. 'summary' is present and not empty\n3. 'keywords' is optional but must be a list if provided"
                else:
                    last_feedback = f"Processing error: {str(e)}\n\nPlease check the output format and retry."

    async def _rebuild_existing_scope(
        self,
        scope: Scope,
        events: List[Event],
    ) -> Scope:
        """Regenerate a Scope after weak Event memberships are detached."""

        rebuilt = await self._extract_new_scope(events)
        if rebuilt is None:
            raise RuntimeError(f"Failed to rebuild Scope {scope.scope_id}")
        rebuilt.scope_id = scope.scope_id
        return rebuilt

    def _validate_scope_update(self, data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate the correctness of scope update results"""
        errors = []

        if "title" not in data:
            errors.append("Missing required field 'title'")
        elif not data.get("title"):
            errors.append("Field 'title' cannot be empty")

        if "summary" not in data:
            errors.append("Missing required field 'summary'")
        elif not data.get("summary"):
            errors.append("Field 'summary' cannot be empty")

        if "keywords" in data and not isinstance(data.get("keywords"), list):
            errors.append("Field 'keywords' must be a list")

        return len(errors) == 0, errors

    async def _update_existing_scope(
        self,
        scope: Scope,
        new_event: Event
    ) -> Optional[Scope]:
        """Step 3: Update an existing scope (with retry mechanism)"""
        scope_text = self._format_scope_display(scope)
        event_text = self._format_event_display(new_event)

        logger.info(f"[Step3] Updating scope: {scope.scope_id}")

        prompt = SCOPE_UPDATE_PROMPT.format(
            existing_scope=scope_text,
            new_event=event_text
        )

        print("\n" + "="*80)
        print(f"[Step 3] LLM Input - Update Scope {scope.scope_id}")
        print("="*80)
        max_display_length = 1000
        if len(prompt) > max_display_length:
            print(prompt[:max_display_length])
            print(f"\n... (truncated, total length: {len(prompt)} characters)")
        else:
            print(prompt)
        print("="*80)

        attempt = 0
        last_feedback = None

        while True:
            try:
                attempt += 1

                # Build current prompt: original prompt + optional validation feedback
                if last_feedback:
                    current_prompt = prompt + f"\n\n[IMPORTANT] Previous attempt failed with the following errors, please fix:\n{last_feedback}"
                else:
                    current_prompt = prompt

                resp = await self.llm_provider.generate(
                    current_prompt,
                    response_format={"type": "json_object"}
                )

                print("\n" + "="*80)
                print(f"[Step 3] LLM Output - Scope {scope.scope_id} (attempt {attempt})")
                print("="*80)
                print(resp)
                print("="*80)

                # JSON mode should guarantee valid JSON; use json_repair as fallback
                try:
                    data = json.loads(resp)
                except json.JSONDecodeError:
                    if HAS_JSON_REPAIR:
                        data = json_repair.loads(resp)
                    else:
                        raise

                is_valid, validation_errors = self._validate_scope_update(data)

                if not is_valid:
                    error_msg = "Scope update validation errors:\n" + "\n".join(validation_errors)
                    raise ValueError(error_msg)

                updated_event_ids = scope.event_ids.copy()
                if new_event.event_id not in updated_event_ids:
                    updated_event_ids.append(new_event.event_id)

                user_id_set = set(scope.user_id_list)
                user_id_set.update(new_event.user_id_list)

                participant_set = set(scope.participants) if scope.participants else set()
                if new_event.participants:
                    participant_set.update(new_event.participants)

                timestamp = new_event.timestamp
                if isinstance(timestamp, int):
                    timestamp = datetime.fromtimestamp(timestamp)
                elif isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

                updated_scope = Scope(
                    scope_id=scope.scope_id,
                    title=data.get("title", scope.title),
                    summary=data.get("summary", scope.summary),
                    event_ids=updated_event_ids,
                    timestamp=timestamp,
                    user_id_list=list(user_id_set),
                    participants=list(participant_set) if participant_set else None,
                    keywords=data.get("keywords", scope.keywords)
                )

                logger.info(f"[Step3] Updated scope: {updated_scope.title} (attempt {attempt})")
                print(f"  ✓ Scope update validation passed (attempt {attempt})")

                return updated_scope

            except (json.JSONDecodeError, ValueError, Exception) as e:
                print(f"  Attempt {attempt} failed: {type(e).__name__}")
                print(f"  Error details: {str(e)}")

                if isinstance(e, json.JSONDecodeError):
                    last_feedback = "JSON parsing failed. Please provide valid JSON format with the following structure:\n{\n  \"title\": \"...\",\n  \"summary\": \"...\",\n  \"keywords\": [...]\n}"
                elif isinstance(e, ValueError) and "validation errors" in str(e):
                    last_feedback = str(e) + "\n\nPlease ensure:\n1. 'title' is present and not empty\n2. 'summary' is present and not empty\n3. 'keywords' is optional but must be a list if provided"
                else:
                    last_feedback = f"Processing error: {str(e)}\n\nPlease check the output format and retry."

    async def _build_scope_event_relation(
        self,
        scope: Scope,
        events: List[Event]
    ) -> ScopeEventRelationExtractResult:
        """Build event relation (includes Step 4)"""
        if not events:
            logger.warning("[Step4] No events, returning empty relation")
            return ScopeEventRelationExtractResult(
                scope_id=scope.scope_id,
                scope_event_relation=None
            )

        role_weight_result = await self._assign_event_roles_and_weights(scope, events)

        scope_uuid = scope.scope_id.replace("scope_", "") if scope.scope_id.startswith("scope_") else scope.scope_id
        relation_id = f"scope_event_relation_{scope_uuid}"

        relation_map = {}
        weights_map = {}

        for ep in events:
            event_id = ep.event_id
            role = role_weight_result.event_roles.get(event_id, EventRole.DEVELOPING)
            weight = role_weight_result.event_weights.get(event_id, 0.5)

            relation_map[event_id] = role.value
            weights_map[event_id] = weight

        scope_event_relation = ScopeEventRelation(
            id=relation_id,
            relation=relation_map,
            weights=weights_map,
            scope_node_id=scope.scope_id,
            created_at=datetime.now(),
            coherence_score=role_weight_result.coherence_score
        )

        relation_result = ScopeEventRelationExtractResult(
            scope_id=scope.scope_id,
            scope_event_relation=scope_event_relation,
            role_weight_result=role_weight_result
        )

        logger.info(f"[Step4] Completed relation construction - event count: {len(events)}, relation ID: {relation_id}")

        return relation_result

    def _validate_event_role_weight_assignment(
        self,
        data: Dict[str, Any],
        events: List[Event]
    ) -> tuple[bool, List[str]]:
        """Validate the correctness of event role and weight assignment results"""
        errors = []

        if "event_roles" not in data:
            errors.append("Missing required field 'event_roles'")
            return False, errors

        if "coherence_score" not in data:
            errors.append("Missing required field 'coherence_score'")

        if "reasoning" not in data:
            errors.append("Missing required field 'reasoning'")

        event_roles_list = data.get("event_roles", [])

        if not isinstance(event_roles_list, list):
            errors.append("'event_roles' must be a list")
            return False, errors

        event_ids = {mc.event_id for mc in events}
        valid_roles = {role.value for role in EventRole}

        assigned_event_ids = set()
        for i, item in enumerate(event_roles_list):
            if not isinstance(item, dict):
                errors.append(f"Event role assignment #{i+1} must be a dict")
                continue

            event_id = item.get("event_id", "")
            if not event_id:
                errors.append(f"Event role assignment #{i+1} missing 'event_id'")
                continue

            assigned_event_ids.add(event_id)

            if event_id not in event_ids:
                errors.append(f"event_id '{event_id}' not in scope's events (bidirectional link validation failed)")

            role = item.get("role", "")
            if not role:
                errors.append(f"Event '{event_id}' missing 'role' field")
            elif role not in valid_roles:
                errors.append(f"Event '{event_id}' has invalid role '{role}'. Valid roles: {', '.join(valid_roles)}")

            weight = item.get("weight")
            if weight is None:
                errors.append(f"Event '{event_id}' missing 'weight' field")
            else:
                try:
                    weight_float = float(weight)
                    if not (0.0 <= weight_float <= 1.0):
                        errors.append(f"Event '{event_id}' weight {weight_float} must be in [0.0, 1.0]")
                except (ValueError, TypeError):
                    errors.append(f"Event '{event_id}' weight '{weight}' must be numeric")

        missing_event_ids = event_ids - assigned_event_ids
        if missing_event_ids:
            errors.append(f"Following events missing role/weight assignment (bidirectional link incomplete): {', '.join(missing_event_ids)}")

        coherence_score = data.get("coherence_score")
        if coherence_score is not None:
            try:
                score_float = float(coherence_score)
                if not (0.0 <= score_float <= 1.0):
                    errors.append(f"coherence_score {score_float} must be in [0.0, 1.0]")
            except (ValueError, TypeError):
                errors.append(f"coherence_score '{coherence_score}' must be numeric")

        return len(errors) == 0, errors

    async def _assign_event_roles_and_weights(
        self,
        scope: Scope,
        events: List[Event]
    ) -> EventRoleWeightAssignmentResult:
        """Step 4: Event role and weight assignment (with retry mechanism)"""
        logger.info(f"[Step4] Starting event role and weight assignment - event count: {len(events)}")

        # Build simple_id <-> real_id mapping to avoid LLM copying long UUIDs
        simple_to_real = {f"event_{i+1}": ep.event_id for i, ep in enumerate(events)}

        scope_text = self._format_scope_display(scope)
        events_text = self._format_event_list(events, use_simple_ids=True)

        prompt = EVENT_ROLE_WEIGHT_ASSIGNMENT_PROMPT.format(
            scope_content=scope_text,
            events=events_text
        )

        print("\n" + "="*80)
        print("[Step 4] LLM Input - Event Role and Weight Assignment")
        print("="*80)
        max_display_length = 1000
        if len(prompt) > max_display_length:
            print(prompt[:max_display_length])
            print(f"\n... (truncated, total length: {len(prompt)} characters)")
        else:
            print(prompt)
        print("="*80)

        attempt = 0
        last_feedback = None

        while True:
            try:
                attempt += 1

                # Build current prompt: original prompt + optional validation feedback
                if last_feedback:
                    current_prompt = prompt + f"\n\n[IMPORTANT] Previous attempt failed with the following errors, please fix:\n{last_feedback}"
                else:
                    current_prompt = prompt

                resp = await self.llm_provider.generate(
                    current_prompt,
                    response_format={"type": "json_object"}
                )

                print("\n" + "="*80)
                print(f"[Step 4] LLM Output (attempt {attempt})")
                print("="*80)
                print(resp)
                print("="*80)

                # JSON mode should guarantee valid JSON; use json_repair as fallback
                try:
                    data = json.loads(resp)
                except json.JSONDecodeError:
                    if HAS_JSON_REPAIR:
                        data = json_repair.loads(resp)
                    else:
                        raise

                event_roles = {}
                event_weights = {}

                invalid_ids = []
                for item in data.get("event_roles", []):
                    simple_id = item.get("event_id", "")
                    # Map simple_id (event_1, event_2, ...) back to real UUID
                    real_id = simple_to_real.get(simple_id)
                    if not real_id:
                        invalid_ids.append(simple_id)
                        continue
                    role_str = item.get("role", "developing")
                    weight = item.get("weight", 0.5)

                    try:
                        role = EventRole(role_str)
                    except ValueError:
                        logger.warning(f"[Step4] Unknown role type: {role_str}, using default value developing")
                        role = EventRole.DEVELOPING

                    event_roles[real_id] = role
                    event_weights[real_id] = float(weight)

                # Strict validation: all events must be assigned, no invalid IDs
                errors = []
                if invalid_ids:
                    errors.append(f"Invalid event IDs: {', '.join(invalid_ids)}. Valid IDs are: {', '.join(simple_to_real.keys())}")
                missing = [f"event_{i+1}" for i, ep in enumerate(events) if ep.event_id not in event_roles]
                if missing:
                    errors.append(f"Missing role/weight assignment for: {', '.join(missing)}")
                if errors:
                    raise ValueError("Event role/weight assignment validation errors:\n" + "\n".join(errors))

                coherence_score = float(data.get("coherence_score", 0.8))
                reasoning = data.get("reasoning", "")

                logger.info(f"[Step4] Completed role and weight assignment - {len(event_roles)} events (attempt {attempt})")
                print(f"  ✓ Event role/weight assignment validation passed (including bidirectional link verification) (attempt {attempt})")

                return EventRoleWeightAssignmentResult(
                    event_roles=event_roles,
                    event_weights=event_weights,
                    coherence_score=coherence_score,
                    reasoning=reasoning
                )

            except (json.JSONDecodeError, ValueError, Exception) as e:
                print(f"  Attempt {attempt} failed: {type(e).__name__}")
                print(f"  Error details: {str(e)}")

                valid_roles_str = ', '.join([role.value for role in EventRole])
                if isinstance(e, json.JSONDecodeError):
                    last_feedback = "JSON parsing failed. Please provide valid JSON format with the following structure:\n{\n  \"event_roles\": [...],\n  \"coherence_score\": 0.0-1.0,\n  \"reasoning\": \"...\"\n}"
                elif isinstance(e, ValueError) and "validation errors" in str(e):
                    last_feedback = str(e) + f"\n\nPlease ensure:\n1. 'event_roles' is a list\n2. Must assign roles/weights to all events (bidirectional link integrity)\n3. Each item contains: event_id, role, weight\n4. role must be one of: {valid_roles_str}\n5. weight must be in [0.0, 1.0]\n6. coherence_score must be in [0.0, 1.0]\n\nEvent IDs that need assignment: {', '.join(simple_to_real.keys())}"
                else:
                    last_feedback = f"Processing error: {str(e)}\n\nPlease check the output format and retry."

    async def _llm_match_scopes_batch(
        self,
        event: Event,
        scopes_batch: List[Scope],
        batch_id_offset: int = 0
    ) -> List[str]:
        """Match an event against a batch of scopes using LLM.

        Returns list of matched scope_ids.
        """
        ep_subject = event.subject or ""
        ep_summary = event.summary or ""

        # Build scopes text with simple IDs
        scope_lines = []
        simple_to_real = {}
        for i, t in enumerate(scopes_batch):
            simple_id = f"scope_{batch_id_offset + i + 1}"
            simple_to_real[simple_id] = t.scope_id
            scope_lines.append(f"- {simple_id}: {t.title}\n  Summary: {t.summary}")

        scopes_text = "\n".join(scope_lines)

        prompt = SCOPE_MATCH_PROMPT.format(
            event_subject=ep_subject,
            event_summary=ep_summary,
            num_scopes=len(scopes_batch),
            scopes_text=scopes_text
        )

        resp = await self.llm_provider.generate(prompt, response_format={"type": "json_object"})

        try:
            data = json.loads(resp)
        except json.JSONDecodeError:
            if HAS_JSON_REPAIR:
                data = json_repair.loads(resp)
            else:
                raise

        matched_ids = []
        for item in data.get("results", []):
            if item.get("match") is True:
                simple_id = item.get("scope_id", "")
                real_id = simple_to_real.get(simple_id)
                if real_id:
                    matched_ids.append(real_id)
        return matched_ids

    async def _llm_match_scopes(
        self,
        event: Event,
        existing_scopes: List[Scope]
    ) -> List[str]:
        """Match an event against all existing scopes using LLM, with batching.

        Returns list of matched scope_ids.
        """
        batch_size = self.scope_match_batch_size
        all_matched_ids = []

        for i in range(0, len(existing_scopes), batch_size):
            batch = existing_scopes[i:i + batch_size]
            matched = await self._llm_match_scopes_batch(event, batch, batch_id_offset=i)
            all_matched_ids.extend(matched)

        return all_matched_ids

    async def extract_scope(
        self,
        request: ScopeExtractRequest
    ) -> tuple[Optional[ScopeExtractResult], List[ScopeEventRelationExtractResult]]:
        """
        Scope extraction pipeline: LLM-based scope matching → create or update.

        Args:
            request: Scope extraction request

        Returns:
            (ScopeExtractResult, List[ScopeEventRelationExtractResult]) tuple
        """
        logger.info("[ScopeExtractor] Starting scope extraction")

        # No existing scopes → create new
        if not request.existing_scopes:
            logger.info("No existing scopes, creating a new scope")
            scope = await self._extract_new_scope([request.new_event])
            if scope:
                scope_result = ScopeExtractResult(
                    scopes=[scope],
                    action="create_new",
                    similar_event_result=None,
                    similar_scope_result=None
                )
                relation = await self._build_scope_event_relation(
                    scope=scope, events=[request.new_event]
                )
                return scope_result, [relation]
            return None, []

        # LLM-based matching against existing scopes
        matched_scope_ids = await self._llm_match_scopes(
            event=request.new_event,
            existing_scopes=request.existing_scopes
        )
        logger.info(f"LLM matched {len(matched_scope_ids)} scopes: {matched_scope_ids}")
        print(f"  [Scope Match] Event matched {len(matched_scope_ids)}/{len(request.existing_scopes)} scopes")

        # No match → create new scope
        if not matched_scope_ids:
            logger.info("No matching scopes, creating a new scope")
            scope = await self._extract_new_scope([request.new_event])
            if scope:
                scope_result = ScopeExtractResult(
                    scopes=[scope],
                    action="create_new",
                    similar_event_result=None,
                    similar_scope_result=None
                )
                relation = await self._build_scope_event_relation(
                    scope=scope, events=[request.new_event]
                )
                return scope_result, [relation]
            return None, []

        # Matched → update all matched scopes
        matched_scopes = [t for t in request.existing_scopes if t.scope_id in matched_scope_ids]
        logger.info(f"Updating {len(matched_scopes)} matched scopes")

        updated_scopes = []
        for scope_to_update in matched_scopes:
            updated_scope = await self._update_existing_scope(
                scope=scope_to_update,
                new_event=request.new_event
            )
            if updated_scope:
                updated_scopes.append(updated_scope)
                logger.info(f"  Updated scope: {updated_scope.title}")

        if updated_scopes:
            scope_result = ScopeExtractResult(
                scopes=updated_scopes,
                action="update_existing",
                similar_event_result=None,
                similar_scope_result=None
            )

            relation_results = []
            for scope in updated_scopes:
                scope_events = [
                    mc for mc in request.history_event_list
                    if mc.event_id in scope.event_ids
                ]
                if request.new_event.event_id in scope.event_ids:
                    if request.new_event.event_id not in [mc.event_id for mc in scope_events]:
                        scope_events.append(request.new_event)

                relation = await self._build_scope_event_relation(
                    scope=scope, events=scope_events
                )
                relation_results.append(relation)

            return scope_result, relation_results

        return None, []

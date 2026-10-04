"""
Scope-based Claim Extractor - Two-stage Extraction Pipeline

Step 1: Claim Extraction
- Extract key claims from a Scope and its associated Events
- Each claim is a complete statement that can directly answer user queries
- Supports cross-event information merging
- Output: Claim list

Step 2: Role and Weight Assignment
- Assign roles and importance weights to each claim within the scope
- Build claim relations (EventClaimRelation), connecting claims to events
- Output: Claim relations

Methods:
- extract_claims(): Execute the complete two-stage pipeline
  Returns: (ClaimExtractResult, EventClaimRelationExtractResult)
"""

import json
import uuid
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

# Approach 3.1: Use json_repair library for JSON repair
try:
    import json_repair
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False
    print("Warning: json_repair library is not installed. Standard json parsing will be used. Install with: pip install json-repair")

from sts.utils.logger import get_logger
from sts.providers.base import LLMProvider
from sts.graph.types import Claim, Event, Scope
from sts.graph.schema import EventClaimRelation, ClaimRole
from sts.prompts.claim_prompts import (
    CLAIM_EXTRACTION_PROMPT,
    CLAIM_ROLE_ASSIGNMENT_PROMPT
)

logger = get_logger(__name__)


@dataclass
class ClaimExtractResult:
    """Claim extraction result"""
    scope_id: str
    claims: List[Claim]
    reasoning: str = ""

    def __post_init__(self):
        """Compute statistics"""
        self.claim_count = len(self.claims)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            "scope_id": self.scope_id,
            "claim_count": self.claim_count,
            "claims": [claim.to_dict() for claim in self.claims],
            "reasoning": self.reasoning
        }

    def get_claims_as_text(self) -> List[str]:
        """Get text representations of all claims"""
        return [claim.to_text() for claim in self.claims]


@dataclass
class RoleAssignmentResult:
    """Role assignment result"""
    claim_roles: Dict[str, ClaimRole]  # claim_id -> role
    claim_weights: Dict[str, float]     # claim_id -> weight
    extraction_confidence: float
    reasoning: str


@dataclass
class EventClaimRelationExtractResult:
    """Claim relation extraction result"""
    scope_id: str
    event_id: str
    event_claim_relation: Optional[EventClaimRelation]

    role_assignment_result: Optional[RoleAssignmentResult] = None
    claim_count: int = 0

    def __post_init__(self):
        """Compute statistics"""
        if self.event_claim_relation:
            self.claim_count = len(self.event_claim_relation.relation)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            "scope_id": self.scope_id,
            "event_id": self.event_id,
            "claim_count": self.claim_count,
            "event_claim_relation": self.event_claim_relation.model_dump() if self.event_claim_relation else None
        }


class ClaimExtractor:
    """
    Scope-based Claim Extractor - Two-stage Extraction Pipeline

    Design Goals:
    1. Extract claims from scopes and associated events that can directly answer user queries
    2. Each claim is a complete statement containing sufficient context information
    3. Support cross-event information merging (multiple events under the same scope may describe the same claim)
    4. Assign roles and weights to claims, and build relation connections

    Usage:
    - extract_claims(): Two-stage pipeline, returns claim list and claim relations
      Returns: (ClaimExtractResult, List[EventClaimRelationExtractResult])
    """

    def __init__(self, llm_provider=LLMProvider, **llm_kwargs):
        """Initialize the claim extractor"""
        self.llm_provider = llm_provider
        self.llm_kwargs = llm_kwargs

    def _format_scope_context(self, scope: Scope) -> Tuple[str, str, str]:
        """
        Format scope context

        Args:
            scope: Scope object

        Returns:
            (scope_id, scope_title, scope_summary)
        """
        return scope.scope_id, scope.title, scope.summary

    def _format_events_content(self, events: List[Event]) -> str:
        """
        Format event list content

        Args:
            events: List of Events

        Returns:
            Formatted text
        """
        lines = []

        for i, event in enumerate(events):
            lines.append(f"--- Event {i+1} (ID: event_{i+1}) ---")

            # Subject
            if event.subject:
                lines.append(f"Subject: {event.subject}")

            # Summary
            if event.summary:
                lines.append(f"Summary: {event.summary}")

            # Episodic memory
            if event.event_description:
                lines.append(f"Event: {event.event_description}")

            # Keywords
            if event.keywords:
                lines.append(f"Keywords: {', '.join(event.keywords)}")

            # Original data
            if event.original_data:
                lines.append("Original Content:")
                for j, data in enumerate(event.original_data):
                    if isinstance(data, dict):
                        if 'content' in data and 'speaker_name' in data:
                            lines.append(f"  [{j+1}] {data.get('speaker_name', 'Unknown')}: {data.get('content', '')}")
                        elif 'text' in data:
                            lines.append(f"  [{j+1}] {data.get('text', '')}")
                        else:
                            lines.append(f"  [{j+1}] {json.dumps(data, ensure_ascii=False)}")
                    else:
                        lines.append(f"  [{j+1}] {data}")

            lines.append("")  # Blank line separator

        return "\n".join(lines)

    def _format_claims(self, claims: List[Claim]) -> str:
        """
        Format claim list as text

        Args:
            claims: List of claims

        Returns:
            Formatted text
        """
        lines = []
        for i, claim in enumerate(claims):
            lines.append(f"--- Claim {i+1} ---")
            lines.append(f"ID: {claim.claim_id}")
            lines.append(f"Content: {claim.content}")
            lines.append(f"Event IDs: {', '.join(claim.event_ids)}")
            lines.append(f"Confidence: {claim.confidence}")
            if claim.temporal:
                lines.append(f"Temporal: {claim.temporal}")
            if claim.spatial:
                lines.append(f"Spatial: {claim.spatial}")
            if claim.keywords:
                lines.append(f"Keywords: {', '.join(claim.keywords)}")
            if claim.query_patterns:
                lines.append(f"Query Patterns: {claim.query_patterns}")
            lines.append("")
        return "\n".join(lines)

    def _get_reference_time(self, events: List[Event]) -> str:
        """
        Get reference time (use the latest event timestamp)

        Args:
            events: List of Events

        Returns:
            Reference time string
        """
        if not events:
            return "Not specified"

        # Find the latest timestamp
        latest_timestamp = None
        for event in events:
            if event.timestamp:
                if latest_timestamp is None or event.timestamp > latest_timestamp:
                    latest_timestamp = event.timestamp

        if latest_timestamp:
            if isinstance(latest_timestamp, datetime):
                return latest_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            return str(latest_timestamp)

        return "Not specified"

    def _validate_claim_extraction(
        self,
        data: Dict[str, Any],
        valid_event_ids: set
    ) -> Tuple[bool, List[str]]:
        """
        Validate the correctness of claim extraction results

        Args:
            data: JSON data returned by the LLM
            valid_event_ids: Set of valid event IDs

        Returns:
            (is_valid, error_list)
        """
        errors = []

        # Check required fields
        if "claims" not in data:
            errors.append("Missing required field 'claims'")
            return False, errors

        claims = data.get("claims", [])

        # Check if claims is a list
        if not isinstance(claims, list):
            errors.append("'claims' must be a list type")
            return False, errors

        # Check that at least one claim was extracted
        if len(claims) == 0:
            errors.append("At least one claim must be extracted")
            return False, errors

        # Check required fields for each claim
        claim_ids = set()
        for i, claim in enumerate(claims):
            if not isinstance(claim, dict):
                errors.append(f"Claim #{i+1} must be a dict type")
                continue

            # Check required fields
            required_fields = ["claim_id", "content", "event_ids"]
            for field in required_fields:
                if field not in claim:
                    errors.append(f"Claim #{i+1} is missing required field '{field}'")
                elif not claim[field]:
                    errors.append(f"Claim #{i+1} field '{field}' cannot be empty")

            # Check claim_id uniqueness
            claim_id = claim.get("claim_id", "")
            if claim_id in claim_ids:
                errors.append(f"Claim ID '{claim_id}' is duplicated")
            claim_ids.add(claim_id)

            # Check if event_ids are valid
            event_ids_list = claim.get("event_ids", [])
            if not isinstance(event_ids_list, list):
                errors.append(f"Claim '{claim_id}' 'event_ids' must be a list type")
            else:
                for ep_id in event_ids_list:
                    if ep_id not in valid_event_ids:
                        errors.append(f"Claim '{claim_id}' references non-existent event '{ep_id}'")

            # Check optional field types
            if "keywords" in claim and claim["keywords"] is not None:
                if not isinstance(claim["keywords"], list):
                    errors.append(f"Claim '{claim_id}' 'keywords' must be a list type")

            if "query_patterns" in claim and claim["query_patterns"] is not None:
                if not isinstance(claim["query_patterns"], list):
                    errors.append(f"Claim '{claim_id}' 'query_patterns' must be a list type")

        return len(errors) == 0, errors

    async def _extract_claims_stage(
        self,
        scope: Scope,
        events: List[Event]
    ) -> ClaimExtractResult:
        """
        Step 1: Claim extraction (with retry mechanism)

        Args:
            scope: Scope object
            events: Associated Event list

        Returns:
            Claim extraction result
        """
        logger.info(f"[Step1] Starting claim extraction - Scope: {scope.scope_id}, Events: {len(events)}")

        scope_id, scope_title, scope_summary = self._format_scope_context(scope)
        events_content = self._format_events_content(events)
        reference_time = self._get_reference_time(events)
        # Build simple_id <-> real_id mapping
        simple_to_real = {f"event_{i+1}": ep.event_id for i, ep in enumerate(events)}
        valid_event_ids = set(simple_to_real.keys())  # Validate against simple IDs

        prompt = CLAIM_EXTRACTION_PROMPT.format(
            scope_id=scope_id,
            scope_title=scope_title,
            scope_summary=scope_summary,
            events_content=events_content,
            reference_time=reference_time
        )

        # Print initial input (with length limit)
        print("\n" + "="*80)
        print("[Step 1] LLM Input - Claim Extraction")
        print("="*80)
        max_display_length = 1500
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

                # Enable JSON Mode, forcing LLM to return valid JSON
                resp = await self.llm_provider.generate(
                    current_prompt,
                    response_format={"type": "json_object"}
                )

                # Print output
                print("\n" + "="*80)
                print(f"[Step 1] LLM Output (attempt {attempt})")
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

                # Validate output correctness
                is_valid, validation_errors = self._validate_claim_extraction(data, valid_event_ids)

                if not is_valid:
                    error_msg = "Claim extraction validation errors:\n" + "\n".join(validation_errors)
                    raise ValueError(error_msg)

                # Validation passed, parse claim list
                claims = []
                for item in data.get("claims", []):
                    # Generate UUID-format claim_id
                    claim_id_val = f"claim_{str(uuid.uuid4())}"

                    # Handle spatial field: LLM may return a list, needs conversion to string
                    spatial = item.get("spatial")
                    if isinstance(spatial, list):
                        spatial = ', '.join(str(s) for s in spatial) if spatial else None

                    # Handle temporal field: LLM may return a list, needs conversion to string
                    temporal = item.get("temporal")
                    if isinstance(temporal, list):
                        temporal = ', '.join(str(t) for t in temporal) if temporal else None

                    # Map simple event IDs back to real UUIDs
                    raw_event_ids = item.get("event_ids", [])
                    real_event_ids = [simple_to_real.get(eid, eid) for eid in raw_event_ids]

                    claim = Claim(
                        claim_id=claim_id_val,
                        content=item.get("content", ""),
                        event_ids=real_event_ids,
                        scope_id=scope_id,
                        confidence=item.get("confidence", 0.8),
                        temporal=temporal,
                        spatial=spatial,
                        keywords=item.get("keywords", []),
                        query_patterns=item.get("query_patterns", []),
                        timestamp=datetime.now()
                    )
                    claims.append(claim)

                reasoning = data.get("reasoning", "")

                logger.info(f"[Step1] Extracted {len(claims)} claims (attempt {attempt})")
                print(f"  OK: Claim extraction validation passed (attempt {attempt})")

                return ClaimExtractResult(
                    scope_id=scope_id,
                    claims=claims,
                    reasoning=reasoning
                )

            except (json.JSONDecodeError, ValueError, Exception) as e:
                print(f"  Attempt {attempt} failed: {type(e).__name__}")
                print(f"  Error details: {str(e)}")

                # Record feedback for next attempt (injected into original prompt, not accumulated)
                if isinstance(e, json.JSONDecodeError):
                    last_feedback = "JSON parsing failed. Please provide valid JSON format."
                elif isinstance(e, ValueError) and "validation errors" in str(e):
                    last_feedback = str(e) + f"\n\nAvailable event IDs: {', '.join(valid_event_ids)}"
                else:
                    last_feedback = f"Processing error: {str(e)}\n\nPlease check the output format and retry."

    def _validate_claim_role_assignment(
        self,
        data: Dict[str, Any],
        claims: List[Claim]
    ) -> Tuple[bool, List[str]]:
        """
        Validate the correctness of role assignment results

        Args:
            data: JSON data returned by the LLM
            claims: List of claims

        Returns:
            (is_valid, error_list)
        """
        errors = []

        # Check required fields
        if "claim_roles" not in data:
            errors.append("Missing required field 'claim_roles'")
            return False, errors

        # extraction_confidence is optional, defaults to 0.8 in parsing

        claim_roles_list = data.get("claim_roles", [])

        if not isinstance(claim_roles_list, list):
            errors.append("'claim_roles' must be a list type")
            return False, errors

        # Build claim ID set
        claim_ids = {claim.claim_id for claim in claims}

        # Valid role enum values
        valid_roles = {role.value for role in ClaimRole}

        # Check each role assignment
        assigned_claim_ids = set()
        for i, item in enumerate(claim_roles_list):
            if not isinstance(item, dict):
                errors.append(f"Role assignment item #{i+1} must be a dict type")
                continue

            claim_id = item.get("claim_id", "")
            if not claim_id:
                errors.append(f"Role assignment item #{i+1} is missing 'claim_id'")
                continue

            assigned_claim_ids.add(claim_id)

            # Check role field
            role = item.get("role", "")
            if not role:
                errors.append(f"Claim '{claim_id}' is missing 'role' field")
            elif role not in valid_roles:
                errors.append(f"Claim '{claim_id}' has invalid role '{role}'. Valid roles: {', '.join(valid_roles)}")

            # Check weight field (optional, defaults to 0.5 in parsing)
            weight = item.get("weight")
            if weight is not None:
                try:
                    weight_float = float(weight)
                    if not (0.0 <= weight_float <= 1.0):
                        errors.append(f"Claim '{claim_id}' weight must be in the range [0.0, 1.0]")
                except (ValueError, TypeError):
                    errors.append(f"Claim '{claim_id}' weight must be a numeric type")

        unknown_claim_ids = assigned_claim_ids - claim_ids
        missing_claim_ids = claim_ids - assigned_claim_ids
        if unknown_claim_ids:
            errors.append(
                "Role assignments reference unknown Claims: "
                + ", ".join(sorted(unknown_claim_ids))
            )
        if missing_claim_ids:
            errors.append(
                "Role assignments are missing Claims: "
                + ", ".join(sorted(missing_claim_ids))
            )

        # Check extraction_confidence
        extraction_confidence = data.get("extraction_confidence")
        if extraction_confidence is not None:
            try:
                confidence_float = float(extraction_confidence)
                if not (0.0 <= confidence_float <= 1.0):
                    errors.append("extraction_confidence must be in the range [0.0, 1.0]")
            except (ValueError, TypeError):
                errors.append("extraction_confidence must be a numeric type")

        return len(errors) == 0, errors

    async def _assign_claim_roles_stage(
        self,
        scope: Scope,
        claims: List[Claim]
    ) -> RoleAssignmentResult:
        """
        Step 2: Role assignment (with retry mechanism)

        Args:
            scope: Scope object
            claims: List of claims

        Returns:
            Role assignment result
        """
        logger.info(f"[Step2] Starting role assignment - Claim count: {len(claims)}")

        scope_id, scope_title, scope_summary = self._format_scope_context(scope)
        claims_text = self._format_claims(claims)

        prompt = CLAIM_ROLE_ASSIGNMENT_PROMPT.format(
            scope_id=scope_id,
            scope_title=scope_title,
            scope_summary=scope_summary,
            claims=claims_text
        )

        # Print initial input
        print("\n" + "="*80)
        print("[Step 2] LLM Input - Role Assignment")
        print("="*80)
        max_display_length = 1500
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

                # Enable JSON Mode, forcing LLM to return valid JSON
                resp = await self.llm_provider.generate(
                    current_prompt,
                    response_format={"type": "json_object"}
                )

                print("\n" + "="*80)
                print(f"[Step 2] LLM Output (attempt {attempt})")
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

                is_valid, validation_errors = self._validate_claim_role_assignment(data, claims)

                if not is_valid:
                    error_msg = "Role assignment validation errors:\n" + "\n".join(validation_errors)
                    raise ValueError(error_msg)

                # Parse roles and weights
                # Build mapping from LLM-returned claim_id to actual claim_id
                llm_id_to_actual = {}
                for i, claim in enumerate(claims):
                    llm_id = f"claim_{i+1}"  # LLM typically returns claim_1, claim_2, ...
                    llm_id_to_actual[llm_id] = claim.claim_id

                claim_roles = {}
                claim_weights = {}

                for item in data.get("claim_roles", []):
                    llm_claim_id = item.get("claim_id", "")
                    # Convert to actual claim_id
                    actual_claim_id = llm_id_to_actual.get(llm_claim_id, llm_claim_id)

                    role_str = item.get("role", "detail")
                    weight = item.get("weight", 0.5)

                    try:
                        role = ClaimRole(role_str)
                    except ValueError:
                        logger.warning(f"[Step2] Unknown role type: {role_str}, using default value 'detail'")
                        role = ClaimRole.DETAIL

                    claim_roles[actual_claim_id] = role
                    claim_weights[actual_claim_id] = float(weight)

                extraction_confidence = float(data.get("extraction_confidence", 0.8))
                reasoning = data.get("reasoning", "")

                logger.info(f"[Step2] Completed role assignment - {len(claim_roles)} claims (attempt {attempt})")
                print(f"  OK: Role assignment validation passed (attempt {attempt})")

                return RoleAssignmentResult(
                    claim_roles=claim_roles,
                    claim_weights=claim_weights,
                    extraction_confidence=extraction_confidence,
                    reasoning=reasoning
                )

            except (json.JSONDecodeError, ValueError, Exception) as e:
                print(f"  Attempt {attempt} failed: {type(e).__name__}")
                print(f"  Error details: {str(e)}")

                valid_roles_str = ', '.join([role.value for role in ClaimRole])
                if isinstance(e, json.JSONDecodeError):
                    last_feedback = "JSON parsing failed. Please provide valid JSON format."
                elif isinstance(e, ValueError) and "validation errors" in str(e):
                    last_feedback = str(e) + f"\n\nValid roles: {valid_roles_str}"
                else:
                    last_feedback = f"Processing error: {str(e)}\n\nPlease check the output format and retry."

    def _build_event_claim_relations(
        self,
        scope: Scope,
        claims: List[Claim],
        role_result: RoleAssignmentResult
    ) -> List[EventClaimRelationExtractResult]:
        """
        Build claim relations (one relation per event)

        Args:
            scope: Scope object
            claims: List of claims
            role_result: Role assignment result

        Returns:
            List of claim relation results
        """
        relation_results = []

        # Build one relation for each event
        for event_id in scope.event_ids:
            # Find claims associated with this event
            related_claims = [
                claim for claim in claims
                if event_id in claim.event_ids
            ]

            if not related_claims:
                continue

            # Build role mapping and weight mapping
            relation_map = {}
            weights_map = {}

            for claim in related_claims:
                claim_id = claim.claim_id
                role = role_result.claim_roles.get(claim_id, ClaimRole.DETAIL)
                weight = role_result.claim_weights.get(claim_id, 0.5)

                relation_map[claim_id] = role.value
                weights_map[claim_id] = weight

            # Generate relation ID
            relation_id = f"event_claim_relation_{event_id}"

            # Create claim relation
            event_claim_relation = EventClaimRelation(
                id=relation_id,
                relation=relation_map,
                weights=weights_map,
                event_node_id=event_id,
                created_at=datetime.now(),
                extraction_confidence=role_result.extraction_confidence
            )

            relation_result = EventClaimRelationExtractResult(
                scope_id=scope.scope_id,
                event_id=event_id,
                event_claim_relation=event_claim_relation,
                role_assignment_result=role_result
            )

            relation_results.append(relation_result)

        return relation_results

    async def extract_claims(
        self,
        scope: Scope,
        events: List[Event]
    ) -> Tuple[Optional[ClaimExtractResult], List[EventClaimRelationExtractResult]]:
        """
        Two-stage claim extraction pipeline

        Args:
            scope: Scope object
            events: Associated Event list

        Returns:
            (ClaimExtractResult, List[EventClaimRelationExtractResult]) tuple
        """
        logger.info(f"[ClaimExtractor] Starting two-stage claim extraction - Scope: {scope.scope_id}")

        # ========== Step 1: Claim Extraction ==========
        claim_result = await self._extract_claims_stage(scope, events)

        if not claim_result.claims:
            logger.warning("[ClaimExtractor] No claims were extracted")
            return claim_result, []

        # ========== Step 2: Role Assignment ==========
        role_result = await self._assign_claim_roles_stage(scope, claim_result.claims)

        # ========== Build Claim Relations ==========
        relation_results = self._build_event_claim_relations(
            scope, claim_result.claims, role_result
        )

        logger.info(f"[ClaimExtractor] Extraction complete - Claims: {claim_result.claim_count}, Relations: {len(relation_results)}")

        return claim_result, relation_results

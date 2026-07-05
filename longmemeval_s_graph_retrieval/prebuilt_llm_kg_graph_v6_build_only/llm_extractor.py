from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Protocol, Sequence


class JsonLLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Return a parsed JSON object from an LLM call."""


class QuestionIndependentGraphExtractor:
    """v2-compatible extractor that never conditions on the benchmark question."""

    def __init__(self, client: JsonLLMClient, max_previous_claims: int = 60, max_state_claims: int = 180) -> None:
        if max_previous_claims < 0:
            raise ValueError("max_previous_claims must be >= 0")
        if max_state_claims < 1:
            raise ValueError("max_state_claims must be >= 1")
        self.client = client
        self.max_previous_claims = max_previous_claims
        self.max_state_claims = max_state_claims

    def extract_batch(
        self,
        batch_events: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str,
        question_date: str,
        previous_claims: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        del question, question_type, question_date
        previous_tail = list(previous_claims)[-self.max_previous_claims :]
        return self.client.complete_json(
            self._system_prompt(),
            self._user_prompt(batch_events, previous_tail),
        )

    def extract_state_facets(
        self,
        claims: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str,
        question_date: str,
    ) -> Dict[str, Any]:
        del question, question_type, question_date
        return self.client.complete_json(
            self._state_system_prompt(),
            self._state_user_prompt(list(claims)[-self.max_state_claims :]),
        )

    def _system_prompt(self) -> str:
        return (
            "You are the question-independent graph construction stage of a long-term memory system. "
            "Extract v2-compatible graph claims from the provided historical event batch only. "
            "You are not given any benchmark question, answer, question type, or gold evidence. "
            "Extract durable atomic claims that could be useful for future memory retrieval: user facts, "
            "preferences, plans, decisions, recommendations, dates, quantities, locations, updates, "
            "corrections, negations, and completed or pending actions. "
            "Use previous_claims only to create corrects/supersedes/conflicts relations. "
            "Do not infer final answers for unseen questions. Do not invent unsupported facts. "
            "Return strict JSON only."
        )

    def _user_prompt(
        self,
        batch_events: Sequence[Mapping[str, Any]],
        previous_claims: Sequence[Mapping[str, Any]],
    ) -> str:
        payload = {
            "task": "Build a question-independent v2-compatible memory graph from batch_events.",
            "batch_events": list(batch_events),
            "previous_claims": list(previous_claims),
            "instructions": [
                "Extract claims only from batch_events.",
                "A claim must be atomic, grounded, and potentially useful for future memory questions.",
                "Use event_id exactly as provided.",
                "entity_labels should name concrete entities, people, places, items, values, projects, or topics.",
                "scope_labels should name the stable memory domain such as preference, profile, health, travel, project, schedule, purchase, recommendation, temporal_event, or knowledge_update.",
                "Most claims should have is_current=false; global state reconciliation will decide current facets later.",
                "Set is_current=true only when the current batch directly states a durable current preference, fact, constraint, plan, or final updated value.",
                "When is_current=true, include state_facet with a general name and value. Do not make the facet specific to any unseen question.",
                "Create supersedes when a later claim replaces an older claim.",
                "Create corrects when a claim explicitly fixes an earlier mistaken claim.",
                "Create conflicts only for unresolved logical conflicts.",
                "Relation source must be the newer/current claim and target must be the older/rejected claim.",
                "For previous targets, use target_claim_id copied from previous_claims.claim_id.",
            ],
            "return_schema": {
                "claims": [
                    {
                        "claim_ref": "local id such as c1",
                        "event_id": "event:<session_id>:<turn_index>",
                        "claim": "atomic grounded claim text",
                        "entity_labels": ["..."],
                        "scope_labels": ["..."],
                        "is_current": True,
                        "state_facet": {"name": "general facet name", "value": "current value"},
                    }
                ],
                "relations": [
                    {
                        "source_claim_ref": "new/current local claim_ref when source is in this batch",
                        "source_claim_id": "optional existing claim_id if source was previous",
                        "target_claim_ref": "old local claim_ref when target is in this batch",
                        "target_claim_id": "old previous claim_id when target is in previous_claims",
                        "type": "supersedes|corrects|conflicts",
                        "reason": "short reason",
                    }
                ],
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _state_system_prompt(self) -> str:
        return (
            "You are the question-independent state reconciliation stage of a long-term memory graph. "
            "Given extracted historical claims, identify durable current State Facets and stale or contradicted claims. "
            "Do not answer any benchmark question and do not optimize for any unseen query. "
            "Return strict JSON only."
        )

    def _state_user_prompt(self, claims: Sequence[Mapping[str, Any]]) -> str:
        payload = {
            "task": "Reconcile question-independent claims into current general state facets.",
            "claims": list(claims),
            "instructions": [
                "Use only the listed claims.",
                "Create state_facets for current durable facts, preferences, constraints, plans, decisions, dates, quantities, and final updated values.",
                "Facet names must be general memory fields, not tailored to a question.",
                "Prefer later claims when they explicitly update, correct, or supersede earlier claims.",
                "Keep stale or contradicted claims in rejected_claims rather than deleting them.",
                "Every state_facet must cite support_claim_ids copied exactly from claims.claim_id.",
                "Every rejected_claim must cite claim_id and rejected_by_claim_id copied exactly from claims.claim_id.",
                "If no durable current facets are supported, return empty state_facets and enough_evidence=false.",
            ],
            "return_schema": {
                "state_facets": [
                    {
                        "name": "general facet name",
                        "value": "current value or durable memory item",
                        "support_claim_ids": ["claim id copied exactly from claims"],
                    }
                ],
                "rejected_claims": [
                    {
                        "claim_id": "old/stale/contradicted claim id",
                        "rejected_by_claim_id": "new/current claim id",
                        "reason": "stale|contradicted|unsupported",
                    }
                ],
                "relations": [
                    {
                        "source_claim_id": "new/current claim id",
                        "target_claim_id": "old/stale/contradicted claim id",
                        "type": "supersedes|corrects|conflicts",
                        "reason": "short reason",
                    }
                ],
                "enough_evidence": True,
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Protocol, Sequence


class JsonLLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Return a parsed JSON object from an LLM call."""


class LLMGraphExtractor:
    """LLM batch extractor for task-semantics local graph construction.

    This extractor turns event batches into Claim nodes, State Facet candidates,
    and relation edges. It is intentionally independent from provider setup; use
    the existing project `LLMClient` or any object implementing `complete_json`.
    """

    def __init__(self, client: JsonLLMClient, max_previous_claims: int = 40) -> None:
        if max_previous_claims < 0:
            raise ValueError("max_previous_claims must be >= 0")
        self.client = client
        self.max_previous_claims = max_previous_claims

    def extract_batch(
        self,
        batch_events: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str,
        question_date: str,
        previous_claims: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        previous_tail = list(previous_claims)[-self.max_previous_claims :]
        return self.client.complete_json(
            self._system_prompt(),
            self._user_prompt(batch_events, question, question_type, question_date, previous_tail),
        )

    def extract_state_facets(
        self,
        claims: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str,
        question_date: str,
    ) -> Dict[str, Any]:
        """Reconcile all extracted claims into final current facets.

        This second pass is the important semantic step for the method. Batch
        extraction finds grounded claims; this pass decides which claims support
        the final State_packet and which claims are stale or contradicted.
        """

        return self.client.complete_json(
            self._state_system_prompt(),
            self._state_user_prompt(claims, question, question_type, question_date),
        )

    def _system_prompt(self) -> str:
        return (
            "You are the graph-construction stage of a Scope-Time-State memory pipeline. "
            "Build a local task-semantics graph from the provided event batch only. "
            "Extract only task-relevant unambiguous atomic claims, entity/scope labels, "
            "and relation edges between claims. "
            "Use previous_claims only to create corrects/supersedes/conflicts relations; "
            "do not invent claims not grounded in the current batch events. "
            "Do not extract generic assistant chatter, greetings, or irrelevant facts. "
            "Return strict JSON only."
        )

    def _user_prompt(
        self,
        batch_events: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str,
        question_date: str,
        previous_claims: Sequence[Mapping[str, Any]],
    ) -> str:
        payload = {
            "question": question,
            "question_type": question_type,
            "question_date": question_date,
            "batch_events": list(batch_events),
            "previous_claims": list(previous_claims),
            "instructions": [
                "Extract claims only from batch_events.",
                "A claim must be atomic, unambiguous, and directly useful for answering the question or rejecting stale/contradicted evidence.",
                "Use event_id exactly as provided.",
                "entity_labels should name concrete entities, objects, people, places, values, or topics.",
                "scope_labels should name the task/state domain, such as preference, location, degree, project, health_constraint, temporal_event, or knowledge_update.",
                "Most claims should have is_current=false; a later reconcile pass decides final current state.",
                "Only set is_current=true when the batch itself contains direct final evidence for the question.",
                "For is_current=true claims, include state_facet with name and value.",
                "Create supersedes when a later claim replaces an older claim.",
                "Create corrects when a claim explicitly fixes an earlier mistaken claim, especially within the same session.",
                "Create conflicts only when claims are unresolved logical conflicts.",
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
                        "state_facet": {"name": "...", "value": "..."},
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
            "You are the state reconciliation stage of a Scope-Time-State memory pipeline. "
            "Given extracted claims from BM25 candidate sessions, construct the final current-state facets "
            "needed to answer the question. Identify stale or contradicted claims and link them to the "
            "current claim that rejects them. Return strict JSON only."
        )

    def _state_user_prompt(
        self,
        claims: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str,
        question_date: str,
    ) -> str:
        payload = {
            "question": question,
            "question_type": question_type,
            "question_date": question_date,
            "claims": list(claims)[-120:],
            "instructions": [
                "Use only the listed claims.",
                "Select the smallest set of claims that directly supports the answer.",
                "For knowledge-update questions, prefer later claims that supersede earlier claims.",
                "For preference questions, preserve user preference, setup, constraints, and the concrete session evidence.",
                "For multi-session questions, keep every distinct contributing unit needed for count/list/synthesis.",
                "For temporal questions, keep all dated events needed for date/order calculation.",
                "Do not create facets from irrelevant topical distractors.",
                "If evidence is insufficient, return empty state_facets and enough_evidence=false.",
                "Every state_facet must cite support_claim_ids copied exactly from claims.claim_id.",
                "Every rejected_claim must cite claim_id and rejected_by_claim_id copied exactly from claims.claim_id.",
            ],
            "return_schema": {
                "state_facets": [
                    {
                        "name": "facet name",
                        "value": "current value or contributing unit",
                        "support_claim_ids": ["claim id copied exactly from claims"],
                    }
                ],
                "rejected_claims": [
                    {
                        "claim_id": "old/stale/contradicted claim id",
                        "rejected_by_claim_id": "new/current claim id",
                        "reason": "stale|contradicted|unsupported|irrelevant",
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

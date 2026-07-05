from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

import networkx as nx

from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import (
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_EVENT_IN_SCOPE,
    EDGE_EVENT_MENTIONS_ENTITY,
    EDGE_FACET_SUPPORTED_BY_CLAIM,
    NODE_CLAIM,
    NODE_ENTITY_SCOPE,
    NODE_EVENT,
    NODE_STATE_FACET,
)

from .scope_retriever import ScopeFirstGraphRetriever


class JsonLLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        ...


class LLMScopeSelectionError(RuntimeError):
    pass


class LLMScopeSelectorGraphRetriever(ScopeFirstGraphRetriever):
    """V7.5: replace v7.0 scope ranking with LLM semantic scope selection."""

    def __init__(
        self,
        scope_client: JsonLLMClient,
        top_scopes: int = 8,
        top_entities: int = 8,
        max_events_per_scope: int = 160,
        max_claims: int = 48,
        max_sessions: int = 20,
        max_evidence: int = 20,
        neighbor_window: int = 2,
        relation_depth: int = 1,
        lexical_fallback_events: int = 12,
        scope_profile_events: int = 20,
        scope_profile_claims: int = 40,
        scope_profile_entities: int = 30,
        scope_profile_facets: int = 20,
        scope_profile_event_tokens: int = 60,
        scope_profile_claim_tokens: int = 50,
        scope_profile_facet_tokens: int = 30,
        scope_fallback: str = "error",
    ) -> None:
        super().__init__(
            top_scopes=top_scopes,
            top_entities=top_entities,
            max_events_per_scope=max_events_per_scope,
            max_claims=max_claims,
            max_sessions=max_sessions,
            max_evidence=max_evidence,
            neighbor_window=neighbor_window,
            relation_depth=relation_depth,
            lexical_fallback_events=lexical_fallback_events,
        )
        if scope_fallback not in {"error", "v7"}:
            raise ValueError("scope_fallback must be 'error' or 'v7'")
        self.scope_client = scope_client
        self.scope_profile_events = scope_profile_events
        self.scope_profile_claims = scope_profile_claims
        self.scope_profile_entities = scope_profile_entities
        self.scope_profile_facets = scope_profile_facets
        self.scope_profile_event_tokens = scope_profile_event_tokens
        self.scope_profile_claim_tokens = scope_profile_claim_tokens
        self.scope_profile_facet_tokens = scope_profile_facet_tokens
        self.scope_fallback = scope_fallback
        self._last_scope_ranker = "llm_scope_neighborhood"
        self._last_scope_selection: Dict[str, Any] = {}

    def retrieve_state_packet(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        question_type: str = "",
        question_date: str = "",
    ) -> Dict[str, Any]:
        packet = super().retrieve_state_packet(graph, question, question_type, question_date)
        packet["retrieval_strategy"] = "v7_5_llm_scope_first_expand"
        packet["scope_ranker"] = self._last_scope_ranker
        packet["llm_scope_selection"] = self._last_scope_selection
        return packet

    def rank_scope_nodes(self, graph: nx.MultiDiGraph, question: str, question_type: str) -> Dict[str, float]:
        candidates = self.scope_candidates(graph)
        if not candidates:
            return {}
        try:
            raw = self.scope_client.complete_json(
                llm_scope_selector_system_prompt(),
                llm_scope_selector_user_prompt(question, question_type, self.top_scopes, candidates),
            )
            scope_scores, audit = self.parse_scope_selection(raw, candidates)
        except Exception as exc:
            if self.scope_fallback == "v7":
                self._last_scope_ranker = "llm_scope_neighborhood_fallback_v7"
                self._last_scope_selection = {"error": str(exc), "fallback": "v7"}
                return super().rank_scope_nodes(graph, question, question_type)
            raise LLMScopeSelectionError(f"LLM scope selection failed: {exc}") from exc
        self._last_scope_ranker = "llm_scope_neighborhood"
        self._last_scope_selection = audit
        return scope_scores

    def scope_candidates(self, graph: nx.MultiDiGraph) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") != NODE_ENTITY_SCOPE or data.get("subtype") != "scope":
                continue
            scope_id = str(node_id)
            event_ids = self.event_ids_for_scope(graph, scope_id)[: self.scope_profile_events]
            entity_labels: List[str] = []
            claims: List[Dict[str, str]] = []
            facets: List[Dict[str, str]] = []
            events: List[Dict[str, str]] = []
            for event_id in event_ids:
                event_data = graph.nodes[event_id]
                events.append(
                    {
                        "date": str(event_data.get("date", "")),
                        "role": str(event_data.get("role", "")),
                        "text": self.truncated_text(str(event_data.get("text", "")), self.scope_profile_event_tokens),
                    }
                )
                entity_labels.extend(self.entity_labels_for_event(graph, event_id))
                remaining_claims = self.scope_profile_claims - len(claims)
                if remaining_claims > 0:
                    event_claims = self.claim_views_for_event(graph, event_id, remaining_claims)
                    claims.extend(event_claims)
                    remaining_facets = self.scope_profile_facets - len(facets)
                    if remaining_facets > 0:
                        facets.extend(self.facet_views_for_claims(graph, [item["node_id"] for item in event_claims], remaining_facets))

            candidates.append(
                {
                    "node_id": scope_id,
                    "label": str(data.get("label", "")),
                    "degree": int(graph.degree(scope_id)),
                    "nearby_entities": self._ordered_unique(entity_labels)[: self.scope_profile_entities],
                    "nearby_events": events,
                    "nearby_claims": claims[: self.scope_profile_claims],
                    "nearby_state_facets": facets[: self.scope_profile_facets],
                }
            )
        candidates.sort(key=lambda item: (str(item.get("label", "")), str(item.get("node_id", ""))))
        return candidates

    def parse_scope_selection(
        self,
        raw: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
        candidate_ids = {str(item.get("node_id", "")) for item in candidates}
        raw_items = raw.get("selected_scopes")
        if not isinstance(raw_items, list):
            raise ValueError("missing selected_scopes list")
        selected: List[Dict[str, Any]] = []
        seen = set()
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            node_id = str(item.get("node_id", ""))
            if node_id not in candidate_ids or node_id in seen:
                continue
            seen.add(node_id)
            score = self.normalized_llm_score(item.get("score"))
            selected.append(
                {
                    "node_id": node_id,
                    "score": score,
                    "reason": str(item.get("reason", ""))[:500],
                }
            )
        if not selected:
            raise ValueError("LLM selected no valid scope ids")
        selected.sort(key=lambda item: (-float(item["score"]), str(item["node_id"])))
        selected = selected[: self.top_scopes]
        scope_scores = {
            str(item["node_id"]): (10.0 * float(item["score"])) + (0.01 * (self.top_scopes - index))
            for index, item in enumerate(selected)
        }
        return scope_scores, {"selected_scopes": selected, "raw": json_safe_for_audit(raw)}

    def normalized_llm_score(self, value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.5
        return min(max(score, 0.0), 1.0)

    def event_ids_for_scope(self, graph: nx.MultiDiGraph, scope_id: str) -> List[str]:
        event_ids: List[str] = []
        for source, _, _, data in graph.in_edges(scope_id, keys=True, data=True):
            if data.get("edge_type") != EDGE_EVENT_IN_SCOPE:
                continue
            if graph.nodes[source].get("node_type") == NODE_EVENT:
                event_ids.append(str(source))
        return sorted(
            self._ordered_unique(event_ids),
            key=lambda event_id: (-int(graph.nodes[event_id].get("sort_key", 0)), event_id),
        )

    def entity_labels_for_event(self, graph: nx.MultiDiGraph, event_id: str) -> List[str]:
        labels: List[str] = []
        for _, target, _, data in graph.out_edges(event_id, keys=True, data=True):
            if data.get("edge_type") != EDGE_EVENT_MENTIONS_ENTITY:
                continue
            target_data = graph.nodes[target]
            if target_data.get("node_type") == NODE_ENTITY_SCOPE:
                labels.append(str(target_data.get("label", "")))
        return labels

    def claim_views_for_event(self, graph: nx.MultiDiGraph, event_id: str, limit: int) -> List[Dict[str, str]]:
        claims: List[Tuple[int, str, Dict[str, str]]] = []
        for source, _, _, data in graph.in_edges(event_id, keys=True, data=True):
            if data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            claim_data: Mapping[str, Any] = graph.nodes[source]
            if claim_data.get("node_type") != NODE_CLAIM:
                continue
            claim_id = str(source)
            claims.append(
                (
                    int(claim_data.get("sort_key", 0)),
                    claim_id,
                    {
                        "node_id": claim_id,
                        "date": str(claim_data.get("date", "")),
                        "role": str(claim_data.get("role", "")),
                        "text": self.truncated_text(str(claim_data.get("text", "")), self.scope_profile_claim_tokens),
                    },
                )
            )
        claims.sort(key=lambda item: (-item[0], item[1]))
        return [item for _, _, item in claims[:limit]]

    def facet_views_for_claims(self, graph: nx.MultiDiGraph, claim_ids: Sequence[str], limit: int) -> List[Dict[str, str]]:
        claim_set = set(claim_ids)
        facets: List[Tuple[str, Dict[str, str]]] = []
        for source, target, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                continue
            if str(target) not in claim_set:
                continue
            facet_data = graph.nodes[source]
            if facet_data.get("node_type") != NODE_STATE_FACET:
                continue
            facet_id = str(source)
            facets.append(
                (
                    facet_id,
                    {
                        "node_id": facet_id,
                        "name": str(facet_data.get("name", "")),
                        "value": self.truncated_text(str(facet_data.get("value", "")), self.scope_profile_facet_tokens),
                    },
                )
            )
        facets.sort(key=lambda item: item[0])
        return [item for _, item in facets[:limit]]

    def truncated_text(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        return " ".join(self._tokens(text, keep_stopwords=True)[:max_tokens])


def llm_scope_selector_system_prompt() -> str:
    return (
        "You are a semantic scope selector for a graph retrieval system. "
        "Select the scope nodes whose graph-neighborhood evidence is most relevant to answering the question. "
        "Use only candidate node_ids provided by the user. Do not invent node_ids. "
        "Return strict JSON only."
    )


def llm_scope_selector_user_prompt(
    question: str,
    question_type: str,
    top_scopes: int,
    candidates: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "question": question,
        "question_type": question_type,
        "instructions": [
            "Choose up to top_scopes scope candidates that are semantically most relevant to the question.",
            "Use nearby_events, nearby_claims, nearby_state_facets, and nearby_entities as graph context.",
            "question_type is metadata only; do not choose a scope solely because its label sounds like the task type.",
            "node_id values must come from candidate_scopes.",
            "Return JSON with selected_scopes: [{node_id, score, reason}]. Scores must be between 0 and 1.",
        ],
        "top_scopes": top_scopes,
        "candidate_scopes": list(candidates),
        "output_schema": {
            "selected_scopes": [
                {
                    "node_id": "one candidate node_id",
                    "score": 0.0,
                    "reason": "short semantic reason",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def json_safe_for_audit(value: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return {"unserializable": str(value)}

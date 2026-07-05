from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import networkx as nx

from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import (
    EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
    EDGE_CLAIM_CORRECTS_CLAIM,
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_CLAIM_SUPERSEDES_CLAIM,
    EDGE_EVENT_IN_SCOPE,
    EDGE_EVENT_MENTIONS_ENTITY,
    EDGE_FACET_CURRENT_AFTER_TIME,
    EDGE_FACET_SUPPORTED_BY_CLAIM,
    NODE_CLAIM,
    NODE_ENTITY_SCOPE,
    NODE_EVENT,
    NODE_STATE_FACET,
)
from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_retriever import (
    REJECTION_REASON_BY_EDGE,
    StatePacketGraphRetriever,
)


STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "am",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "but",
    "by",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}


QUESTION_TYPE_SCOPE_HINTS = {
    "knowledge-update": {
        "knowledge_update",
        "update",
        "status",
        "correction",
        "current",
        "changed",
    },
    "multi-session": {
        "multi_session_synthesis",
        "multi_session",
        "activity",
        "event",
        "project",
        "task",
    },
    "single-session-assistant": {
        "assistant_memory",
        "assistant",
        "recommendation",
        "instruction",
        "suggestion",
    },
    "single-session-preference": {
        "preference_grounding",
        "preference",
        "constraint",
        "like",
        "dislike",
        "prefer",
    },
    "single-session-user": {
        "user_fact",
        "profile",
        "personal_info",
        "identity",
        "background",
    },
    "temporal-reasoning": {
        "temporal_reasoning",
        "temporal_event",
        "date",
        "schedule",
        "time",
        "order",
    },
}


class ScopeFirstGraphRetriever:
    """Pipeline-aligned graph retriever.

    v2 starts from current State Facets. This retriever starts from question
    scope/entity signals, traces to Events and Claims, resolves update edges,
    then selects current facets and evidence. It falls back to the v2 retriever
    when scope-first retrieval cannot produce a complete State_packet.
    """

    def __init__(self, fallback: Optional[StatePacketGraphRetriever] = None) -> None:
        self.fallback = fallback or StatePacketGraphRetriever()

    def retrieve_state_packet(self, graph: nx.MultiDiGraph, question: str, question_type: str = "") -> Dict[str, Any]:
        target_terms = self._target_terms(question, question_type)
        scope_nodes = self._matched_scope_entity_nodes(graph, target_terms)
        if not scope_nodes:
            return self._fallback_packet(graph, "fallback:no_scope_match")

        event_ids = self._events_for_scope_nodes(graph, scope_nodes)
        if not event_ids:
            return self._fallback_packet(graph, "fallback:no_scope_events")

        claim_ids = self._claims_for_events(graph, event_ids)
        if not claim_ids:
            return self._fallback_packet(graph, "fallback:no_scope_claims")

        closure_claim_ids = self._claim_update_closure(graph, claim_ids)
        invalidated_claim_ids = self._invalidated_claim_ids(graph)
        active_claim_ids = [
            claim_id for claim_id in closure_claim_ids
            if claim_id not in invalidated_claim_ids and self._is_scope_relevant_claim(graph, claim_id, target_terms)
        ]
        if not active_claim_ids:
            active_claim_ids = [claim_id for claim_id in closure_claim_ids if claim_id not in invalidated_claim_ids]
        if not active_claim_ids:
            return self._fallback_packet(graph, "fallback:no_active_claims")

        latest_time_node = self._latest_time_node(graph)
        facet_ids = self._facets_for_claims(graph, active_claim_ids, latest_time_node, invalidated_claim_ids)
        if not facet_ids:
            return self._fallback_packet(graph, "fallback:no_scope_facets")

        state_facets = [
            self._state_facet_view(graph, facet_id, invalidated_claim_ids)
            for facet_id in facet_ids
        ]
        state_facets = [item for item in state_facets if item is not None]
        if not state_facets:
            return self._fallback_packet(graph, "fallback:no_state_facet_view")

        selected_claims = self._claims_for_facets(graph, facet_ids)
        selected_claims = [claim_id for claim_id in selected_claims if claim_id not in invalidated_claim_ids]
        if not selected_claims:
            selected_claims = active_claim_ids

        rejected_claims = self._rejected_claims_from_active_claims(graph, selected_claims)
        evidence_snippets = self._evidence_snippets(graph, selected_claims, rejected_claims)
        if not evidence_snippets:
            return self._fallback_packet(graph, "fallback:no_evidence")

        relevant_session_ids = self._ordered_unique(
            str(item["session_id"])
            for item in evidence_snippets
            if item.get("session_id")
        )
        return {
            "relevant_session_ids": relevant_session_ids,
            "evidence_snippets": evidence_snippets,
            "state_facets": state_facets,
            "rejected_claims": [
                {
                    "claim": item["claim"],
                    "reason": item["reason"],
                    "support_session_ids": item["support_session_ids"],
                }
                for item in rejected_claims
            ],
            "enough_evidence": True,
            "retrieval_strategy": "scope_first",
            "matched_scope_node_count": len(scope_nodes),
            "scope_relevant_claim_count": len(closure_claim_ids),
        }

    def _fallback_packet(self, graph: nx.MultiDiGraph, reason: str) -> Dict[str, Any]:
        packet = self.fallback.retrieve_state_packet(graph)
        packet["retrieval_strategy"] = "state_first_fallback"
        packet["fallback_reason"] = reason
        return packet

    def _target_terms(self, question: str, question_type: str) -> Set[str]:
        terms = set(QUESTION_TYPE_SCOPE_HINTS.get(question_type, set()))
        terms.update(self._tokens(question, limit=24))
        return {self._normalize(term) for term in terms if self._normalize(term)}

    def _matched_scope_entity_nodes(self, graph: nx.MultiDiGraph, target_terms: Set[str]) -> List[str]:
        matches: List[Tuple[int, str]] = []
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") != NODE_ENTITY_SCOPE:
                continue
            label = self._normalize(str(data.get("label") or ""))
            subtype = self._normalize(str(data.get("subtype") or ""))
            node_terms = set(self._tokens(label.replace("_", " "), limit=12))
            score = 0
            if label in target_terms:
                score += 4
            if subtype == "scope" and node_terms.intersection(target_terms):
                score += 3
            if subtype == "entity" and node_terms.intersection(target_terms):
                score += 2
            if any(term and (term in label or label in term) for term in target_terms):
                score += 1
            if score > 0:
                matches.append((score, str(node_id)))
        matches.sort(key=lambda item: (-item[0], item[1]))
        return self._ordered_unique(node_id for _, node_id in matches)

    def _events_for_scope_nodes(self, graph: nx.MultiDiGraph, scope_nodes: Sequence[str]) -> List[str]:
        event_ids: List[str] = []
        allowed_edges = {EDGE_EVENT_IN_SCOPE, EDGE_EVENT_MENTIONS_ENTITY}
        for scope_node in scope_nodes:
            if not graph.has_node(scope_node):
                continue
            for source, _, _, data in graph.in_edges(scope_node, keys=True, data=True):
                if data.get("edge_type") not in allowed_edges:
                    continue
                if graph.nodes[source].get("node_type") != NODE_EVENT:
                    continue
                event_ids.append(str(source))
        return self._ordered_unique(event_ids)

    def _claims_for_events(self, graph: nx.MultiDiGraph, event_ids: Sequence[str]) -> List[str]:
        event_set = set(event_ids)
        claim_ids: List[str] = []
        for claim_id, event_id, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            if str(event_id) not in event_set:
                continue
            if graph.nodes[claim_id].get("node_type") != NODE_CLAIM:
                continue
            claim_ids.append(str(claim_id))
        return self._ordered_unique(claim_ids)

    def _claim_update_closure(self, graph: nx.MultiDiGraph, claim_ids: Sequence[str]) -> List[str]:
        relation_edges = {
            EDGE_CLAIM_SUPERSEDES_CLAIM,
            EDGE_CLAIM_CORRECTS_CLAIM,
            EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
        }
        seen = set(str(claim_id) for claim_id in claim_ids)
        queue = list(seen)
        while queue:
            claim_id = queue.pop(0)
            for source, target, _, data in graph.out_edges(claim_id, keys=True, data=True):
                if data.get("edge_type") not in relation_edges:
                    continue
                for neighbor in (source, target):
                    neighbor = str(neighbor)
                    if neighbor not in seen and graph.nodes[neighbor].get("node_type") == NODE_CLAIM:
                        seen.add(neighbor)
                        queue.append(neighbor)
            for source, target, _, data in graph.in_edges(claim_id, keys=True, data=True):
                if data.get("edge_type") not in relation_edges:
                    continue
                for neighbor in (source, target):
                    neighbor = str(neighbor)
                    if neighbor not in seen and graph.nodes[neighbor].get("node_type") == NODE_CLAIM:
                        seen.add(neighbor)
                        queue.append(neighbor)
        return self._sort_claims(graph, seen)

    def _facets_for_claims(
        self,
        graph: nx.MultiDiGraph,
        claim_ids: Sequence[str],
        latest_time_node: Optional[str],
        invalidated_claim_ids: Set[str],
    ) -> List[str]:
        claim_set = set(claim_ids)
        facet_ids: List[str] = []
        for facet_id, claim_id, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                continue
            if str(claim_id) not in claim_set:
                continue
            if graph.nodes[facet_id].get("node_type") != NODE_STATE_FACET:
                continue
            if latest_time_node is not None and not self._facet_points_to_time(graph, str(facet_id), latest_time_node):
                continue
            supported_claims = self._claims_for_facets(graph, [str(facet_id)])
            if supported_claims and all(claim_id in invalidated_claim_ids for claim_id in supported_claims):
                continue
            facet_ids.append(str(facet_id))
        return sorted(self._ordered_unique(facet_ids), key=lambda item: str(graph.nodes[item].get("name", "")))

    def _facet_points_to_time(self, graph: nx.MultiDiGraph, facet_id: str, latest_time_node: str) -> bool:
        for _, target, _, data in graph.out_edges(facet_id, keys=True, data=True):
            if str(target) == latest_time_node and data.get("edge_type") == EDGE_FACET_CURRENT_AFTER_TIME:
                return True
        return False

    def _latest_time_node(self, graph: nx.MultiDiGraph) -> Optional[str]:
        graph_latest = graph.graph.get("latest_time_node")
        if graph_latest and graph.has_node(graph_latest):
            return str(graph_latest)
        time_nodes = [
            (node_id, data)
            for node_id, data in graph.nodes(data=True)
            if data.get("node_type") == "Time"
        ]
        if not time_nodes:
            return None
        time_nodes.sort(key=lambda item: int(item[1].get("sort_key", 0)), reverse=True)
        return str(time_nodes[0][0])

    def _invalidated_claim_ids(self, graph: nx.MultiDiGraph) -> Set[str]:
        invalidated: Set[str] = set()
        for _, target, data in graph.edges(data=True):
            if data.get("edge_type") in {EDGE_CLAIM_SUPERSEDES_CLAIM, EDGE_CLAIM_CORRECTS_CLAIM}:
                invalidated.add(str(target))
        return invalidated

    def _is_scope_relevant_claim(self, graph: nx.MultiDiGraph, claim_id: str, target_terms: Set[str]) -> bool:
        data = graph.nodes[claim_id]
        labels = set()
        for key in ("scope_labels", "entity_labels", "terms"):
            value = data.get(key)
            if isinstance(value, str):
                labels.add(self._normalize(value))
            elif isinstance(value, Iterable):
                labels.update(self._normalize(str(item)) for item in value)
        text_terms = set(self._tokens(str(data.get("text") or ""), limit=24))
        return bool(labels.intersection(target_terms) or text_terms.intersection(target_terms))

    def _claims_for_facets(self, graph: nx.MultiDiGraph, facet_ids: Sequence[str]) -> List[str]:
        claim_ids: List[str] = []
        for facet_id in facet_ids:
            for _, target, _, data in graph.out_edges(facet_id, keys=True, data=True):
                if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                    continue
                if graph.nodes[target].get("node_type") != NODE_CLAIM:
                    continue
                claim_ids.append(str(target))
        return self._ordered_unique(claim_ids)

    def _state_facet_view(
        self,
        graph: nx.MultiDiGraph,
        facet_id: str,
        invalidated_claim_ids: Set[str],
    ) -> Optional[Dict[str, Any]]:
        data = graph.nodes[facet_id]
        supported_claims = [
            claim_id
            for claim_id in self._claims_for_facets(graph, [facet_id])
            if claim_id not in invalidated_claim_ids
        ]
        support_session_ids: List[str] = []
        for claim_id in supported_claims:
            support_session_ids.extend(self._support_session_ids_for_claim(graph, claim_id))
        support_session_ids = self._ordered_unique(support_session_ids)
        if not support_session_ids:
            return None
        return {
            "name": str(data.get("name", "task_state")),
            "value": str(data.get("value", "")),
            "support_session_ids": support_session_ids,
        }

    def _rejected_claims_from_active_claims(
        self,
        graph: nx.MultiDiGraph,
        active_claim_ids: Sequence[str],
    ) -> List[Dict[str, Any]]:
        rejected: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str]] = set()
        for active_claim_id in active_claim_ids:
            stack: List[Tuple[str, int]] = [(active_claim_id, 0)]
            while stack:
                source_claim_id, depth = stack.pop()
                if depth > 8:
                    continue
                for _, old_claim_id, _, edge_data in graph.out_edges(source_claim_id, keys=True, data=True):
                    edge_type = edge_data.get("edge_type")
                    if edge_type not in REJECTION_REASON_BY_EDGE:
                        continue
                    if graph.nodes[old_claim_id].get("node_type") != NODE_CLAIM:
                        continue
                    reason = REJECTION_REASON_BY_EDGE[str(edge_type)]
                    key = (str(old_claim_id), reason)
                    if key in seen:
                        continue
                    seen.add(key)
                    support_session_ids = self._ordered_unique(
                        self._support_session_ids_for_claim(graph, str(old_claim_id))
                        + self._support_session_ids_for_claim(graph, str(active_claim_id))
                    )
                    rejected.append(
                        {
                            "claim_id": str(old_claim_id),
                            "claim": str(graph.nodes[old_claim_id].get("text", "")),
                            "reason": reason,
                            "support_session_ids": support_session_ids,
                            "active_claim_id": str(active_claim_id),
                            "edge_type": str(edge_type),
                        }
                    )
                    stack.append((str(old_claim_id), depth + 1))
        return rejected

    def _evidence_snippets(
        self,
        graph: nx.MultiDiGraph,
        active_claim_ids: Sequence[str],
        rejected_claims: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        claim_roles: List[Tuple[str, str]] = [(claim_id, "supports scope-relevant state facet") for claim_id in active_claim_ids]
        claim_roles.extend(
            (str(item["claim_id"]), f"supports rejected claim ({item['reason']})")
            for item in rejected_claims
            if item.get("claim_id")
        )

        snippets: List[Dict[str, Any]] = []
        seen_events: Set[str] = set()
        for claim_id, why_relevant in claim_roles:
            for event_id in self._event_ids_for_claim(graph, claim_id):
                if event_id in seen_events:
                    continue
                seen_events.add(event_id)
                event_data = graph.nodes[event_id]
                if event_data.get("node_type") != NODE_EVENT:
                    continue
                snippets.append(
                    {
                        "session_id": str(event_data.get("session_id", "")),
                        "date": str(event_data.get("date", "")),
                        "role": str(event_data.get("role", "unknown")),
                        "content": str(event_data.get("text", "")),
                        "why_relevant": why_relevant,
                    }
                )
        snippets.sort(key=lambda item: (item.get("date", ""), item.get("session_id", ""), item.get("role", "")))
        return snippets

    def _event_ids_for_claim(self, graph: nx.MultiDiGraph, claim_id: str) -> List[str]:
        event_ids: List[str] = []
        if not graph.has_node(claim_id):
            return event_ids
        for _, target, _, data in graph.out_edges(claim_id, keys=True, data=True):
            if data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            if graph.nodes[target].get("node_type") != NODE_EVENT:
                continue
            event_ids.append(str(target))
        return self._ordered_unique(event_ids)

    def _support_session_ids_for_claim(self, graph: nx.MultiDiGraph, claim_id: str) -> List[str]:
        session_ids: List[str] = []
        for event_id in self._event_ids_for_claim(graph, claim_id):
            session_id = graph.nodes[event_id].get("session_id")
            if session_id:
                session_ids.append(str(session_id))
        return self._ordered_unique(session_ids)

    def _sort_claims(self, graph: nx.MultiDiGraph, claim_ids: Iterable[str]) -> List[str]:
        return sorted(
            self._ordered_unique(claim_ids),
            key=lambda claim_id: (
                int(graph.nodes[claim_id].get("sort_key", 0)),
                str(graph.nodes[claim_id].get("session_id", "")),
                str(claim_id),
            ),
        )

    def _tokens(self, text: str, limit: int = 16) -> List[str]:
        terms: List[str] = []
        seen: Set[str] = set()
        for term in re.findall(r"[a-zA-Z0-9_']+", text.lower()):
            term = self._normalize(term)
            if len(term) <= 2 or term in STOPWORDS or term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= limit:
                break
        return terms

    def _normalize(self, value: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
        value = re.sub(r"_+", "_", value).strip("_")
        return value

    def _ordered_unique(self, values: Iterable[Any]) -> List[str]:
        seen: Set[str] = set()
        ordered: List[str] = []
        for value in values:
            item = str(value)
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered


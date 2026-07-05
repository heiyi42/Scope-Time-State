from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

import networkx as nx

from .scope_retriever import (
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_EVENT_IN_SCOPE,
    EDGE_EVENT_MENTIONS_ENTITY,
    NODE_CLAIM,
    NODE_ENTITY_SCOPE,
    NODE_EVENT,
    ScopeFirstGraphRetriever,
)


class BM25ScopeProfileGraphRetriever(ScopeFirstGraphRetriever):
    """V10.1 baseline: rank scope nodes with BM25 over graph-derived scope profiles."""

    def __init__(
        self,
        top_scopes: int = 8,
        top_entities: int = 8,
        max_events_per_scope: int = 160,
        max_claims: int = 48,
        max_sessions: int = 20,
        max_evidence: int = 20,
        neighbor_window: int = 2,
        relation_depth: int = 1,
        lexical_fallback_events: int = 12,
        scope_profile_events: int = 5,
        scope_profile_claims: int = 10,
        scope_profile_event_tokens: int = 80,
        scope_profile_claim_tokens: int = 60,
        scope_label_weight: int = 3,
        entity_label_weight: int = 2,
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
        self.scope_profile_events = scope_profile_events
        self.scope_profile_claims = scope_profile_claims
        self.scope_profile_event_tokens = scope_profile_event_tokens
        self.scope_profile_claim_tokens = scope_profile_claim_tokens
        self.scope_label_weight = scope_label_weight
        self.entity_label_weight = entity_label_weight
        self._last_scope_ranker = "bm25_scope_profile"

    def retrieve_state_packet(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        question_type: str = "",
        question_date: str = "",
    ) -> Dict[str, Any]:
        packet = super().retrieve_state_packet(graph, question, question_type, question_date)
        packet["retrieval_strategy"] = "v10_1_bm25_scope_first_expand"
        packet["scope_ranker"] = self._last_scope_ranker
        return packet

    def rank_scope_nodes(self, graph: nx.MultiDiGraph, question: str, question_type: str) -> Dict[str, float]:
        query_terms = self._query_terms(question)
        docs = self.scope_profile_docs(graph)
        scores = self._rank_text_docs(docs, query_terms, self.top_scopes)
        if scores:
            self._last_scope_ranker = "bm25_scope_profile"
            return scores
        self._last_scope_ranker = "bm25_scope_profile_fallback_scope_first"
        return super().rank_scope_nodes(graph, question, question_type)

    def scope_profile_docs(self, graph: nx.MultiDiGraph) -> List[Tuple[str, str]]:
        docs: List[Tuple[str, str]] = []
        for scope_id, scope_data in graph.nodes(data=True):
            if scope_data.get("node_type") != NODE_ENTITY_SCOPE or scope_data.get("subtype") != "scope":
                continue
            scope_id = str(scope_id)
            parts: List[str] = []
            label = str(scope_data.get("label", ""))
            parts.extend([label] * self.scope_label_weight)

            event_ids = self.event_ids_for_scope(graph, scope_id)
            entity_labels: List[str] = []
            claim_texts: List[str] = []
            for event_id in event_ids[: self.scope_profile_events]:
                event_data = graph.nodes[event_id]
                event_text = f"{event_data.get('role', '')} {event_data.get('date', '')} {event_data.get('text', '')}"
                parts.append(self.truncated_text(event_text, self.scope_profile_event_tokens))
                entity_labels.extend(self.entity_labels_for_event(graph, event_id))
                remaining_claims = self.scope_profile_claims - len(claim_texts)
                if remaining_claims > 0:
                    claim_texts.extend(self.claim_texts_for_event(graph, event_id, remaining_claims))

            for label in self._ordered_unique(entity_labels):
                parts.extend([label] * self.entity_label_weight)
            parts.extend(claim_texts[: self.scope_profile_claims])
            docs.append((scope_id, " ".join(part for part in parts if part)))
        return docs

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

    def claim_texts_for_event(self, graph: nx.MultiDiGraph, event_id: str, limit: int) -> List[str]:
        claims: List[Tuple[int, str, str]] = []
        for source, _, _, data in graph.in_edges(event_id, keys=True, data=True):
            if data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            claim_data: Mapping[str, Any] = graph.nodes[source]
            if claim_data.get("node_type") != NODE_CLAIM:
                continue
            claim_id = str(source)
            text = self.truncated_text(self._claim_text(claim_data), self.scope_profile_claim_tokens)
            claims.append((int(claim_data.get("sort_key", 0)), claim_id, text))
        claims.sort(key=lambda item: (-item[0], item[1]))
        return [text for _, _, text in claims[:limit]]

    def truncated_text(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        return " ".join(self._tokens(text, keep_stopwords=False)[:max_tokens])

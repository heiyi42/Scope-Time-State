from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import networkx as nx

from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import (
    EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
    EDGE_CLAIM_CORRECTS_CLAIM,
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_CLAIM_SUPERSEDES_CLAIM,
    EDGE_FACET_CURRENT_AFTER_TIME,
    EDGE_FACET_SUPPORTED_BY_CLAIM,
    NODE_CLAIM,
    NODE_EVENT,
    NODE_STATE_FACET,
)

from .scope_retriever import ScopeFirstGraphRetriever


REJECTION_REASON_BY_EDGE = {
    EDGE_CLAIM_SUPERSEDES_CLAIM: "stale",
    EDGE_CLAIM_CORRECTS_CLAIM: "contradicted",
    EDGE_CLAIM_CONFLICTS_WITH_CLAIM: "contradicted",
}


class ScopeTimeStateGraphRetriever(ScopeFirstGraphRetriever):
    """V7.2: keep V7.0 scope ranking, then traverse Time -> State -> Claim."""

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
        max_state_facets: int = 24,
        fallback_claims: int = 16,
        temporal_event_keep: int = 32,
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
        self.max_state_facets = max_state_facets
        self.fallback_claims = fallback_claims
        self.temporal_event_keep = temporal_event_keep

    def retrieve_state_packet(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        question_type: str = "",
        question_date: str = "",
    ) -> Dict[str, Any]:
        del question_date
        query_terms = self._query_terms(question)
        scope_scores = self.rank_scope_nodes(graph, question, question_type)
        entity_scores = self.rank_entity_nodes(graph, query_terms)
        scoped_events = self.expand_scope_events(graph, scope_scores)
        entity_events = self.expand_entity_events(graph, entity_scores)
        fallback_events = self.rank_event_nodes(graph, query_terms, self.lexical_fallback_events)

        candidate_event_scores: Dict[str, float] = defaultdict(float)
        for event_id, score in scoped_events.items():
            candidate_event_scores[event_id] += float(score)
        for event_id, score in entity_events.items():
            candidate_event_scores[event_id] += 0.7 * float(score)
        for event_id, score in fallback_events.items():
            candidate_event_scores[event_id] += 0.5 * float(score)

        candidate_claim_scores = self.expand_claims_from_events(
            graph,
            candidate_event_scores,
            query_terms,
            question_type,
        )
        invalidated_claim_ids = self.invalidated_claim_ids(graph)
        latest_time_node = self.latest_time_node(graph)
        selected_facet_scores = self.select_state_facets(
            graph,
            candidate_claim_scores,
            candidate_event_scores,
            query_terms,
            latest_time_node,
            invalidated_claim_ids,
            question_type,
        )
        active_claim_scores = self.claims_for_state_facets(
            graph,
            selected_facet_scores,
            candidate_claim_scores,
            invalidated_claim_ids,
            question_type,
        )

        if self.requires_temporal_events(question_type, query_terms):
            active_claim_scores = self.add_temporal_claims(
                graph,
                active_claim_scores,
                candidate_claim_scores,
                candidate_event_scores,
                invalidated_claim_ids,
            )
        if self.requires_multi_evidence(question_type):
            active_claim_scores = self.add_fallback_claims(
                active_claim_scores,
                candidate_claim_scores,
                invalidated_claim_ids,
                self.fallback_claims,
            )
        if not active_claim_scores:
            active_claim_scores = self.add_fallback_claims(
                active_claim_scores,
                candidate_claim_scores,
                invalidated_claim_ids,
                self.max_claims,
            )

        relation_claim_scores = self.expand_claim_relations(graph, active_claim_scores)
        ranked_claims = [
            claim_id
            for claim_id, _ in sorted(
                relation_claim_scores.items(),
                key=lambda item: (-item[1], self._claim_sort_key(graph, item[0])),
            )
        ][: self.max_claims]
        rejected_claims = self.rejected_claims_for_active_claims(graph, ranked_claims)
        ranked_events = self.events_for_claims(graph, ranked_claims)
        ranked_events = self.with_neighbor_events(graph, ranked_events)
        evidence_snippets = self.state_evidence_snippets(
            graph,
            ranked_events,
            relation_claim_scores,
            candidate_event_scores,
        )
        relevant_session_ids = self.rank_sessions(graph, evidence_snippets, relation_claim_scores, candidate_event_scores)

        matched_scopes = [
            self.scope_view(graph, scope_id, score)
            for scope_id, score in sorted(scope_scores.items(), key=lambda item: (-item[1], item[0]))[: self.top_scopes]
        ]
        matched_entities = [
            self.entity_view(graph, entity_id, score)
            for entity_id, score in sorted(entity_scores.items(), key=lambda item: (-item[1], item[0]))[: self.top_entities]
        ]
        state_facets = [
            self.state_facet_view(graph, facet_id, score, invalidated_claim_ids)
            for facet_id, score in sorted(selected_facet_scores.items(), key=lambda item: (-item[1], item[0]))[
                : self.max_state_facets
            ]
        ]
        state_facets = [item for item in state_facets if item is not None]
        return {
            "relevant_session_ids": relevant_session_ids[: self.max_sessions],
            "evidence_snippets": evidence_snippets[: self.max_evidence],
            "state_facets": state_facets,
            "rejected_claims": rejected_claims,
            "enough_evidence": bool(evidence_snippets),
            "retrieval_strategy": "v7_2_scope_time_state",
            "matched_scopes": matched_scopes,
            "matched_entities": matched_entities,
            "time_anchor": self.time_view(graph, latest_time_node),
            "scoped_node_counts": {
                "scopes": len(scope_scores),
                "entities": len(entity_scores),
                "candidate_events": len(candidate_event_scores),
                "candidate_claims": len(candidate_claim_scores),
                "state_facets": len(selected_facet_scores),
                "claims": len(relation_claim_scores),
                "sessions": len(relevant_session_ids),
            },
        }

    def latest_time_node(self, graph: nx.MultiDiGraph) -> Optional[str]:
        graph_latest = graph.graph.get("latest_time_node")
        if graph_latest and graph.has_node(graph_latest):
            return str(graph_latest)
        time_nodes = [(node_id, data) for node_id, data in graph.nodes(data=True) if data.get("node_type") == "Time"]
        if not time_nodes:
            return None
        time_nodes.sort(key=lambda item: int(item[1].get("sort_key", 0)), reverse=True)
        return str(time_nodes[0][0])

    def select_state_facets(
        self,
        graph: nx.MultiDiGraph,
        candidate_claim_scores: Mapping[str, float],
        candidate_event_scores: Mapping[str, float],
        query_terms: Sequence[str],
        latest_time_node: Optional[str],
        invalidated_claim_ids: Set[str],
        question_type: str,
    ) -> Dict[str, float]:
        del candidate_event_scores
        query_set = set(query_terms)
        candidate_claim_set = set(candidate_claim_scores)
        facet_scores: Dict[str, float] = defaultdict(float)
        for facet_id, claim_id, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                continue
            facet_id = str(facet_id)
            claim_id = str(claim_id)
            if not graph.has_node(facet_id) or not graph.has_node(claim_id):
                continue
            if graph.nodes[facet_id].get("node_type") != NODE_STATE_FACET:
                continue
            if graph.nodes[claim_id].get("node_type") != NODE_CLAIM:
                continue
            if claim_id in invalidated_claim_ids and self.prefers_current_state(question_type):
                continue
            if claim_id not in candidate_claim_set:
                continue
            if latest_time_node and not self.facet_current_after_time(graph, facet_id, latest_time_node):
                continue
            facet_data = graph.nodes[facet_id]
            text = f"{facet_data.get('name', '')} {facet_data.get('value', '')} {self._claim_text(graph.nodes[claim_id])}"
            terms = set(self._tokens(text, keep_stopwords=False))
            score = float(candidate_claim_scores[claim_id])
            score += 0.7 * len(terms & query_set)
            if self.prefers_current_state(question_type):
                score += 1.0
            if self.requires_temporal_events(question_type, query_terms):
                score += 0.4 * self.claim_time_score(graph, claim_id)
            facet_scores[facet_id] += score
        ranked = sorted(facet_scores.items(), key=lambda item: (-item[1], item[0]))
        return dict(ranked[: self.max_state_facets])

    def claims_for_state_facets(
        self,
        graph: nx.MultiDiGraph,
        facet_scores: Mapping[str, float],
        candidate_claim_scores: Mapping[str, float],
        invalidated_claim_ids: Set[str],
        question_type: str,
    ) -> Dict[str, float]:
        claim_scores: Dict[str, float] = defaultdict(float)
        for facet_id, facet_score in facet_scores.items():
            for _, claim_id, _, data in graph.out_edges(facet_id, keys=True, data=True):
                if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                    continue
                claim_id = str(claim_id)
                if graph.nodes[claim_id].get("node_type") != NODE_CLAIM:
                    continue
                if claim_id in invalidated_claim_ids and self.prefers_current_state(question_type):
                    continue
                base = float(candidate_claim_scores.get(claim_id, 0.0))
                claim_scores[claim_id] += float(facet_score) + base
        return dict(claim_scores)

    def add_temporal_claims(
        self,
        graph: nx.MultiDiGraph,
        active_claim_scores: Mapping[str, float],
        candidate_claim_scores: Mapping[str, float],
        candidate_event_scores: Mapping[str, float],
        invalidated_claim_ids: Set[str],
    ) -> Dict[str, float]:
        scores: Dict[str, float] = defaultdict(float, {str(k): float(v) for k, v in active_claim_scores.items()})
        ranked_events = sorted(
            candidate_event_scores.items(),
            key=lambda item: (-self.event_time_score(graph, item[0]), -item[1], item[0]),
        )[: self.temporal_event_keep]
        keep_events = {event_id for event_id, _ in ranked_events}
        for claim_id, event_id, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            claim_id = str(claim_id)
            event_id = str(event_id)
            if claim_id in invalidated_claim_ids:
                continue
            if event_id not in keep_events:
                continue
            scores[claim_id] += float(candidate_claim_scores.get(claim_id, 0.0)) + 0.5 * float(candidate_event_scores[event_id])
        return dict(scores)

    def add_fallback_claims(
        self,
        active_claim_scores: Mapping[str, float],
        candidate_claim_scores: Mapping[str, float],
        invalidated_claim_ids: Set[str],
        limit: int,
    ) -> Dict[str, float]:
        scores: Dict[str, float] = defaultdict(float, {str(k): float(v) for k, v in active_claim_scores.items()})
        ranked = sorted(candidate_claim_scores.items(), key=lambda item: (-item[1], item[0]))
        for claim_id, score in ranked:
            if len(scores) >= limit:
                break
            if claim_id in invalidated_claim_ids:
                continue
            scores[str(claim_id)] += 0.6 * float(score)
        return dict(scores)

    def state_evidence_snippets(
        self,
        graph: nx.MultiDiGraph,
        event_ids: Sequence[str],
        claim_scores: Mapping[str, float],
        event_scores: Mapping[str, float],
    ) -> List[Dict[str, Any]]:
        event_claim_score: Dict[str, float] = defaultdict(float)
        event_claim_role: Dict[str, str] = {}
        for claim_id, claim_score in claim_scores.items():
            for event_id in self.events_for_claims(graph, [claim_id]):
                event_claim_score[event_id] += float(claim_score)
                event_claim_role.setdefault(event_id, "supports selected state/claim")
        snippets: List[Tuple[float, Dict[str, Any]]] = []
        seen: Set[str] = set()
        for event_id in event_ids:
            if event_id in seen or not graph.has_node(event_id):
                continue
            seen.add(event_id)
            data = graph.nodes[event_id]
            if data.get("node_type") != NODE_EVENT:
                continue
            score = float(event_scores.get(event_id, 0.0)) + float(event_claim_score.get(event_id, 0.0))
            snippets.append(
                (
                    score,
                    {
                        "session_id": str(data.get("session_id", "")),
                        "date": str(data.get("date", "")),
                        "role": str(data.get("role", "unknown")),
                        "content": str(data.get("text", "")),
                        "why_relevant": event_claim_role.get(event_id, "near selected state/claim"),
                        "scope_score": score,
                    },
                )
            )
        snippets.sort(key=lambda item: (-item[0], item[1].get("date", ""), item[1].get("session_id", "")))
        return [item for _, item in snippets]

    def state_facet_view(
        self,
        graph: nx.MultiDiGraph,
        facet_id: str,
        score: float,
        invalidated_claim_ids: Set[str],
    ) -> Optional[Dict[str, Any]]:
        data = graph.nodes[facet_id]
        support_claim_ids = [
            claim_id
            for claim_id in self.claim_ids_for_facet(graph, facet_id)
            if claim_id not in invalidated_claim_ids
        ]
        support_session_ids: List[str] = []
        for claim_id in support_claim_ids:
            support_session_ids.extend(self._support_session_ids_for_claim(graph, claim_id))
        support_session_ids = self._ordered_unique(support_session_ids)
        if not support_session_ids:
            return None
        return {
            "name": str(data.get("name", "task_state")),
            "value": str(data.get("value", "")),
            "support_session_ids": support_session_ids,
            "score": float(score),
        }

    def claim_ids_for_facet(self, graph: nx.MultiDiGraph, facet_id: str) -> List[str]:
        claim_ids: List[str] = []
        for _, claim_id, _, data in graph.out_edges(facet_id, keys=True, data=True):
            if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                continue
            if graph.nodes[claim_id].get("node_type") == NODE_CLAIM:
                claim_ids.append(str(claim_id))
        return self._ordered_unique(claim_ids)

    def facet_current_after_time(self, graph: nx.MultiDiGraph, facet_id: str, time_id: str) -> bool:
        for _, target, _, data in graph.out_edges(facet_id, keys=True, data=True):
            if data.get("edge_type") == EDGE_FACET_CURRENT_AFTER_TIME and str(target) == str(time_id):
                return True
        return False

    def invalidated_claim_ids(self, graph: nx.MultiDiGraph) -> Set[str]:
        invalidated: Set[str] = set()
        for _, target, data in graph.edges(data=True):
            if data.get("edge_type") in {EDGE_CLAIM_SUPERSEDES_CLAIM, EDGE_CLAIM_CORRECTS_CLAIM}:
                invalidated.add(str(target))
        return invalidated

    def claim_time_score(self, graph: nx.MultiDiGraph, claim_id: str) -> float:
        scores = [self.event_time_score(graph, event_id) for event_id in self.events_for_claims(graph, [claim_id])]
        return max(scores) if scores else 0.0

    def event_time_score(self, graph: nx.MultiDiGraph, event_id: str) -> float:
        if not graph.has_node(event_id):
            return 0.0
        data = graph.nodes[event_id]
        sort_key = int(data.get("sort_key", 0))
        if sort_key <= 0:
            return 0.0
        return min(sort_key / 1_000_000_000.0, 2.0)

    def time_view(self, graph: nx.MultiDiGraph, time_id: Optional[str]) -> Dict[str, Any]:
        if not time_id or not graph.has_node(time_id):
            return {}
        data = graph.nodes[time_id]
        return {
            "node_id": str(time_id),
            "label": str(data.get("label", "")),
            "sort_key": int(data.get("sort_key", 0)),
            "time_role": str(data.get("time_role", "")),
        }

    def prefers_current_state(self, question_type: str) -> bool:
        return question_type in {
            "knowledge-update",
            "single-session-preference",
            "single-session-user",
            "single-session-assistant",
        }

    def requires_temporal_events(self, question_type: str, query_terms: Sequence[str]) -> bool:
        if question_type == "temporal-reasoning":
            return True
        temporal_terms = {"when", "before", "after", "days", "weeks", "months", "recent", "latest"}
        return bool(set(query_terms) & temporal_terms)

    def requires_multi_evidence(self, question_type: str) -> bool:
        return question_type == "multi-session"

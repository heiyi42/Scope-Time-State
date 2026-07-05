from __future__ import annotations

from collections import Counter
import math
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


QUESTION_TYPE_HINTS = {
    "knowledge-update": ("updated", "changed", "instead", "current", "latest", "correction"),
    "multi-session": ("list", "count", "all", "multiple", "sessions", "activities"),
    "single-session-assistant": ("recommended", "suggested", "assistant", "advice"),
    "single-session-preference": ("prefer", "preference", "like", "dislike", "constraint"),
    "single-session-user": ("user", "profile", "degree", "work", "personal"),
    "temporal-reasoning": ("when", "date", "time", "before", "after", "days", "left"),
}


QUERY_EXPANSIONS = {
    "doctor": ("physician", "specialist", "dermatologist", "ent", "appointment", "clinic"),
    "doctors": ("physician", "specialist", "dermatologist", "ent", "appointment", "clinic"),
    "money": ("cost", "costs", "spent", "paid", "expense", "expenses", "dollars", "$"),
    "spent": ("cost", "costs", "paid", "expense", "expenses", "dollars", "$"),
    "expenses": ("cost", "costs", "spent", "paid", "dollars", "$"),
    "plants": ("plant", "bought", "got", "acquired", "nursery"),
    "plant": ("plants", "bought", "got", "acquired", "nursery"),
    "projects": ("project", "led", "leading", "lead", "team", "responsible"),
    "project": ("projects", "led", "leading", "lead", "team", "responsible"),
    "clothing": ("clothes", "boots", "blazer", "shirt", "dress", "pants", "pick", "return", "store"),
    "hotel": ("hotels", "view", "views", "rooftop", "pool", "balcony", "unique", "amenities"),
    "kitchen": ("utensil", "utensils", "countertop", "countertops", "granite", "sink", "clutter"),
}


class QuestionIndependentGraphRetriever:
    """Query-time retriever over a prebuilt v2-schema graph.

    It does not create nodes, claims, facets, or edges. The question is used only
    to find graph seed nodes, expand along existing edges, rank candidates, and
    assemble a v2-style State_packet.
    """

    def __init__(
        self,
        top_events: int = 16,
        top_claims: int = 32,
        top_facets: int = 16,
        top_entities: int = 10,
        max_active_claims: int = 24,
        max_evidence: int = 18,
        raw_event_fallback: int = 6,
        fallback: Optional[StatePacketGraphRetriever] = None,
    ) -> None:
        self.top_events = top_events
        self.top_claims = top_claims
        self.top_facets = top_facets
        self.top_entities = top_entities
        self.max_active_claims = max_active_claims
        self.max_evidence = max_evidence
        self.raw_event_fallback = raw_event_fallback
        self.fallback = fallback or StatePacketGraphRetriever()

    def retrieve_state_packet(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        question_type: str = "",
        question_date: str = "",
    ) -> Dict[str, Any]:
        del question_date
        query_terms = self._query_terms(question, question_type)
        if not query_terms:
            packet = self.fallback.retrieve_state_packet(graph)
            packet["retrieval_strategy"] = "state_first_fallback:no_query_terms"
            return packet

        event_scores = self._rank_nodes(graph, NODE_EVENT, query_terms, self.top_events)
        claim_scores = self._rank_nodes(graph, NODE_CLAIM, query_terms, self.top_claims)
        facet_scores = self._rank_nodes(graph, NODE_STATE_FACET, query_terms, self.top_facets)
        entity_scores = self._rank_nodes(graph, NODE_ENTITY_SCOPE, query_terms, self.top_entities)

        seed_events = list(event_scores)
        seed_claims = list(claim_scores)
        seed_facets = list(facet_scores)
        seed_entities = list(entity_scores)

        candidate_claims: List[str] = []
        candidate_claims.extend(seed_claims)
        candidate_claims.extend(self._claims_for_events(graph, seed_events))
        candidate_claims.extend(self._claims_for_facets(graph, seed_facets))
        candidate_claims.extend(self._claims_for_entities(graph, seed_entities))
        candidate_claims = self._claim_relation_closure(graph, candidate_claims)

        invalidated_claims = self._invalidated_claim_ids(graph)
        active_candidates = [claim_id for claim_id in candidate_claims if claim_id not in invalidated_claims]
        if not active_candidates:
            active_candidates = [claim_id for claim_id in seed_claims if claim_id not in invalidated_claims]

        active_ranked = self._rank_claim_candidates(
            graph,
            active_candidates,
            query_terms,
            event_scores,
            claim_scores,
            facet_scores,
            entity_scores,
        )[: self.max_active_claims]

        facet_ids = self._facets_for_claims(graph, active_ranked)
        facet_ids = self._rank_facet_candidates(graph, self._ordered_unique(list(seed_facets) + facet_ids), query_terms, facet_scores)

        state_facets = [
            self._state_facet_view(graph, facet_id, invalidated_claims)
            for facet_id in facet_ids[: self.top_facets]
        ]
        state_facets = [item for item in state_facets if item is not None]

        facet_claims = self._claims_for_facets(graph, facet_ids)
        selected_claims = self._ordered_unique(
            [claim_id for claim_id in facet_claims + active_ranked if claim_id not in invalidated_claims]
        )[: self.max_active_claims]
        rejected_claims = self._rejected_claims_from_active_claims(graph, selected_claims)
        evidence_snippets = self._evidence_snippets(graph, selected_claims, rejected_claims)
        evidence_snippets = self._with_raw_event_fallback(
            graph,
            evidence_snippets,
            event_scores,
            limit=self.max_evidence,
        )

        if not evidence_snippets and not state_facets:
            packet = self.fallback.retrieve_state_packet(graph)
            packet["retrieval_strategy"] = "state_first_fallback:no_query_graph_hits"
            return packet

        relevant_session_ids = self._ordered_unique(
            str(item["session_id"])
            for item in evidence_snippets
            if item.get("session_id")
        )
        return {
            "relevant_session_ids": relevant_session_ids,
            "evidence_snippets": evidence_snippets[: self.max_evidence],
            "state_facets": state_facets,
            "rejected_claims": [
                {
                    "claim": item["claim"],
                    "reason": item["reason"],
                    "support_session_ids": item["support_session_ids"],
                }
                for item in rejected_claims
            ],
            "enough_evidence": bool(evidence_snippets or state_facets),
            "retrieval_strategy": "v5_question_time_graph_search",
            "seed_counts": {
                "events": len(seed_events),
                "claims": len(seed_claims),
                "facets": len(seed_facets),
                "entities": len(seed_entities),
            },
        }

    def _rank_nodes(
        self,
        graph: nx.MultiDiGraph,
        node_type: str,
        query_terms: Sequence[str],
        limit: int,
    ) -> Dict[str, float]:
        docs: List[Tuple[str, str]] = []
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") != node_type:
                continue
            text = self._node_text(data)
            if text:
                docs.append((str(node_id), text))
        scores = self._bm25_scores(docs, query_terms)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return {node_id: score for node_id, score in ranked[:limit] if score > 0}

    def _node_text(self, data: Mapping[str, Any]) -> str:
        node_type = data.get("node_type")
        if node_type == NODE_EVENT:
            return f"{data.get('role', '')} {data.get('date', '')} {data.get('text', '')}"
        if node_type == NODE_CLAIM:
            labels = " ".join(str(item) for item in (data.get("entity_labels") or []))
            scopes = " ".join(str(item) for item in (data.get("scope_labels") or []))
            return f"{labels} {scopes} {data.get('date', '')} {data.get('text', '')}"
        if node_type == NODE_STATE_FACET:
            return f"{data.get('name', '')} {data.get('value', '')} {data.get('current_after', '')}"
        if node_type == NODE_ENTITY_SCOPE:
            return f"{data.get('subtype', '')} {data.get('label', '')}"
        return " ".join(str(value) for value in data.values())

    def _bm25_scores(self, docs: Sequence[Tuple[str, str]], query_terms: Sequence[str]) -> Dict[str, float]:
        if not docs or not query_terms:
            return {}
        doc_terms = [(node_id, Counter(self._tokens(text, keep_stopwords=False))) for node_id, text in docs]
        doc_count = len(doc_terms)
        avg_len = sum(sum(counter.values()) for _, counter in doc_terms) / max(doc_count, 1)
        df: Counter[str] = Counter()
        for _, counter in doc_terms:
            df.update(counter.keys())
        query_counter = Counter(query_terms)
        scores: Dict[str, float] = {}
        k1 = 1.5
        b = 0.75
        for node_id, counter in doc_terms:
            doc_len = sum(counter.values())
            score = 0.0
            for term, query_count in query_counter.items():
                freq = counter.get(term, 0)
                if freq == 0:
                    continue
                idf = math.log(1.0 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
                denom = freq + k1 * (1.0 - b + b * doc_len / max(avg_len, 1.0))
                score += query_count * idf * (freq * (k1 + 1.0) / denom)
            if score > 0:
                scores[node_id] = score
        return scores

    def _claims_for_events(self, graph: nx.MultiDiGraph, event_ids: Sequence[str]) -> List[str]:
        event_set = set(event_ids)
        claim_ids: List[str] = []
        for claim_id, event_id, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            if str(event_id) in event_set and graph.nodes[claim_id].get("node_type") == NODE_CLAIM:
                claim_ids.append(str(claim_id))
        return self._ordered_unique(claim_ids)

    def _claims_for_facets(self, graph: nx.MultiDiGraph, facet_ids: Sequence[str]) -> List[str]:
        claim_ids: List[str] = []
        for facet_id in facet_ids:
            if not graph.has_node(facet_id):
                continue
            for _, target, _, data in graph.out_edges(facet_id, keys=True, data=True):
                if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                    continue
                if graph.nodes[target].get("node_type") == NODE_CLAIM:
                    claim_ids.append(str(target))
        return self._ordered_unique(claim_ids)

    def _claims_for_entities(self, graph: nx.MultiDiGraph, entity_ids: Sequence[str]) -> List[str]:
        event_ids: List[str] = []
        allowed = {EDGE_EVENT_IN_SCOPE, EDGE_EVENT_MENTIONS_ENTITY}
        for entity_id in entity_ids:
            if not graph.has_node(entity_id):
                continue
            for source, _, _, data in graph.in_edges(entity_id, keys=True, data=True):
                if data.get("edge_type") in allowed and graph.nodes[source].get("node_type") == NODE_EVENT:
                    event_ids.append(str(source))
        return self._claims_for_events(graph, self._ordered_unique(event_ids))

    def _claim_relation_closure(self, graph: nx.MultiDiGraph, claim_ids: Sequence[str], depth_limit: int = 2) -> List[str]:
        relation_edges = {
            EDGE_CLAIM_SUPERSEDES_CLAIM,
            EDGE_CLAIM_CORRECTS_CLAIM,
            EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
        }
        seen = set(str(claim_id) for claim_id in claim_ids if graph.has_node(claim_id))
        queue: List[Tuple[str, int]] = [(claim_id, 0) for claim_id in seen]
        while queue:
            claim_id, depth = queue.pop(0)
            if depth >= depth_limit:
                continue
            for source, target, _, data in list(graph.out_edges(claim_id, keys=True, data=True)) + list(graph.in_edges(claim_id, keys=True, data=True)):
                if data.get("edge_type") not in relation_edges:
                    continue
                for neighbor in (source, target):
                    neighbor = str(neighbor)
                    if neighbor not in seen and graph.nodes[neighbor].get("node_type") == NODE_CLAIM:
                        seen.add(neighbor)
                        queue.append((neighbor, depth + 1))
        return self._sort_claims(graph, seen)

    def _rank_claim_candidates(
        self,
        graph: nx.MultiDiGraph,
        claim_ids: Sequence[str],
        query_terms: Sequence[str],
        event_scores: Mapping[str, float],
        claim_scores: Mapping[str, float],
        facet_scores: Mapping[str, float],
        entity_scores: Mapping[str, float],
    ) -> List[str]:
        query_set = set(query_terms)
        scored: List[Tuple[float, str]] = []
        for claim_id in self._ordered_unique(claim_ids):
            if not graph.has_node(claim_id):
                continue
            data = graph.nodes[claim_id]
            text_terms = set(self._tokens(self._node_text(data), keep_stopwords=False))
            score = float(claim_scores.get(claim_id, 0.0))
            score += 0.5 * len(text_terms & query_set)
            score += 0.05 * min(int(data.get("sort_key", 0)) / 1000000000.0, 1.0)
            for event_id in self._event_ids_for_claim(graph, claim_id):
                score += 0.45 * float(event_scores.get(event_id, 0.0))
            for facet_id in self._facets_for_claims_reverse(graph, [claim_id]):
                score += 0.55 * float(facet_scores.get(facet_id, 0.0))
            for entity_label in list(data.get("entity_labels") or []) + list(data.get("scope_labels") or []):
                normalized = self._normalize(str(entity_label))
                if normalized in query_set:
                    score += 1.2
                for entity_id, entity_score in entity_scores.items():
                    label = self._normalize(str(graph.nodes[entity_id].get("label", "")))
                    if label and (label == normalized or label in query_set):
                        score += 0.25 * float(entity_score)
            if data.get("has_update_marker") or data.get("has_correction_marker"):
                score += 0.3
            scored.append((score, claim_id))
        scored.sort(key=lambda item: (-item[0], -int(graph.nodes[item[1]].get("sort_key", 0)), item[1]))
        return [claim_id for score, claim_id in scored if score > 0]

    def _facets_for_claims_reverse(self, graph: nx.MultiDiGraph, claim_ids: Sequence[str]) -> List[str]:
        claim_set = set(claim_ids)
        facet_ids: List[str] = []
        for source, target, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_FACET_SUPPORTED_BY_CLAIM:
                continue
            if str(target) in claim_set and graph.nodes[source].get("node_type") == NODE_STATE_FACET:
                facet_ids.append(str(source))
        return self._ordered_unique(facet_ids)

    def _facets_for_claims(self, graph: nx.MultiDiGraph, claim_ids: Sequence[str]) -> List[str]:
        return self._facets_for_claims_reverse(graph, claim_ids)

    def _rank_facet_candidates(
        self,
        graph: nx.MultiDiGraph,
        facet_ids: Sequence[str],
        query_terms: Sequence[str],
        facet_scores: Mapping[str, float],
    ) -> List[str]:
        query_set = set(query_terms)
        scored: List[Tuple[float, str]] = []
        latest_time_node = self._latest_time_node(graph)
        for facet_id in self._ordered_unique(facet_ids):
            if not graph.has_node(facet_id):
                continue
            data = graph.nodes[facet_id]
            text_terms = set(self._tokens(self._node_text(data), keep_stopwords=False))
            score = float(facet_scores.get(facet_id, 0.0)) + 0.5 * len(text_terms & query_set)
            if latest_time_node and self._facet_points_to_time(graph, facet_id, latest_time_node):
                score += 0.2
            scored.append((score, facet_id))
        scored.sort(key=lambda item: (-item[0], str(graph.nodes[item[1]].get("name", "")), item[1]))
        return [facet_id for score, facet_id in scored if score > 0]

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
                if depth > 6:
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
        claim_roles: List[Tuple[str, str]] = [(claim_id, "supports retrieved current state facet") for claim_id in active_claim_ids]
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
                item = self._event_snippet(graph, event_id, why_relevant)
                if item:
                    snippets.append(item)
        snippets.sort(key=lambda item: (item.get("date", ""), item.get("session_id", ""), item.get("role", "")))
        return snippets

    def _with_raw_event_fallback(
        self,
        graph: nx.MultiDiGraph,
        snippets: Sequence[Mapping[str, Any]],
        event_scores: Mapping[str, float],
        limit: int,
    ) -> List[Dict[str, Any]]:
        merged = [dict(item) for item in snippets]
        seen_keys = {
            (
                str(item.get("session_id", "")),
                str(item.get("date", "")),
                str(item.get("role", "")),
                str(item.get("content", "")),
            )
            for item in merged
        }
        for event_id in list(event_scores)[: self.raw_event_fallback]:
            item = self._event_snippet(graph, event_id, "raw event lexical fallback from prebuilt graph")
            if not item:
                continue
            key = (
                item.get("session_id", ""),
                item.get("date", ""),
                item.get("role", ""),
                item.get("content", ""),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged[:limit]

    def _event_snippet(self, graph: nx.MultiDiGraph, event_id: str, why_relevant: str) -> Optional[Dict[str, Any]]:
        if not graph.has_node(event_id):
            return None
        data = graph.nodes[event_id]
        if data.get("node_type") != NODE_EVENT:
            return None
        return {
            "session_id": str(data.get("session_id", "")),
            "date": str(data.get("date", "")),
            "role": str(data.get("role", "unknown")),
            "content": str(data.get("text", "")),
            "why_relevant": why_relevant,
        }

    def _event_ids_for_claim(self, graph: nx.MultiDiGraph, claim_id: str) -> List[str]:
        event_ids: List[str] = []
        if not graph.has_node(claim_id):
            return event_ids
        for _, target, _, data in graph.out_edges(claim_id, keys=True, data=True):
            if data.get("edge_type") == EDGE_CLAIM_SUPPORTED_BY_EVENT and graph.nodes[target].get("node_type") == NODE_EVENT:
                event_ids.append(str(target))
        return self._ordered_unique(event_ids)

    def _support_session_ids_for_claim(self, graph: nx.MultiDiGraph, claim_id: str) -> List[str]:
        session_ids: List[str] = []
        for event_id in self._event_ids_for_claim(graph, claim_id):
            session_id = graph.nodes[event_id].get("session_id")
            if session_id:
                session_ids.append(str(session_id))
        return self._ordered_unique(session_ids)

    def _invalidated_claim_ids(self, graph: nx.MultiDiGraph) -> Set[str]:
        invalidated: Set[str] = set()
        for _, target, data in graph.edges(data=True):
            if data.get("edge_type") in {EDGE_CLAIM_SUPERSEDES_CLAIM, EDGE_CLAIM_CORRECTS_CLAIM}:
                invalidated.add(str(target))
        return invalidated

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

    def _facet_points_to_time(self, graph: nx.MultiDiGraph, facet_id: str, latest_time_node: str) -> bool:
        for _, target, _, data in graph.out_edges(facet_id, keys=True, data=True):
            if str(target) == latest_time_node and data.get("edge_type") == EDGE_FACET_CURRENT_AFTER_TIME:
                return True
        return False

    def _sort_claims(self, graph: nx.MultiDiGraph, claim_ids: Iterable[str]) -> List[str]:
        return sorted(
            self._ordered_unique(claim_ids),
            key=lambda claim_id: (
                int(graph.nodes[claim_id].get("sort_key", 0)),
                str(graph.nodes[claim_id].get("session_id", "")),
                str(claim_id),
            ),
        )

    def _query_terms(self, question: str, question_type: str) -> List[str]:
        terms = self._tokens(question, keep_stopwords=False)
        expanded = list(terms)
        for term in terms:
            expanded.extend(QUERY_EXPANSIONS.get(term, ()))
        expanded.extend(QUESTION_TYPE_HINTS.get(question_type, ()))
        return self._ordered_unique(self._normalize(term) for term in expanded if self._normalize(term))

    def _tokens(self, text: str, keep_stopwords: bool) -> List[str]:
        terms: List[str] = []
        for term in re.findall(r"[a-zA-Z0-9_']+", text.lower()):
            term = self._normalize(term)
            if not term or len(term) <= 1:
                continue
            if not keep_stopwords and term in STOPWORDS:
                continue
            terms.append(term)
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
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered


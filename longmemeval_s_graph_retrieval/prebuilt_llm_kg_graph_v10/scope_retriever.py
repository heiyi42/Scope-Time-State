from __future__ import annotations

from collections import Counter, defaultdict
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
    NODE_CLAIM,
    NODE_ENTITY_SCOPE,
    NODE_EVENT,
    NODE_STATE_FACET,
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


QUESTION_TYPE_SCOPE_PRIORS = {
    "knowledge-update": {
        "knowledge_update": 2.8,
        "current_state": 2.4,
        "preference": 0.8,
        "profile": 0.8,
    },
    "multi-session": {
        "temporal_event": 1.4,
        "knowledge_update": 1.0,
        "profile": 0.8,
        "recommendation": 0.6,
    },
    "single-session-assistant": {
        "recommendation": 2.8,
        "knowledge_update": 1.0,
        "temporal_event": 0.4,
    },
    "single-session-preference": {
        "preference": 3.0,
        "profile": 1.0,
        "knowledge_update": 0.8,
        "current_state": 0.8,
    },
    "single-session-user": {
        "profile": 2.4,
        "preference": 1.0,
        "knowledge_update": 0.8,
    },
    "temporal-reasoning": {
        "temporal": 2.8,
        "temporal_event": 2.8,
        "knowledge_update": 1.0,
        "profile": 0.6,
    },
}


QUERY_SCOPE_HINTS = {
    "prefer": ("preference", "current_state"),
    "preference": ("preference", "current_state"),
    "favorite": ("preference",),
    "like": ("preference",),
    "dislike": ("preference",),
    "currently": ("current_state", "knowledge_update"),
    "current": ("current_state", "knowledge_update"),
    "now": ("current_state", "knowledge_update"),
    "latest": ("knowledge_update", "current_state"),
    "recent": ("knowledge_update", "current_state", "temporal_event"),
    "changed": ("knowledge_update", "current_state"),
    "updated": ("knowledge_update", "current_state"),
    "instead": ("knowledge_update",),
    "recommend": ("recommendation",),
    "recommended": ("recommendation",),
    "suggest": ("recommendation",),
    "suggested": ("recommendation",),
    "advice": ("recommendation",),
    "when": ("temporal", "temporal_event"),
    "before": ("temporal", "temporal_event"),
    "after": ("temporal", "temporal_event"),
    "days": ("temporal", "temporal_event"),
    "weeks": ("temporal", "temporal_event"),
    "months": ("temporal", "temporal_event"),
    "where": ("profile", "location", "knowledge_update"),
    "move": ("profile", "location", "knowledge_update"),
    "moved": ("profile", "location", "knowledge_update"),
    "relocation": ("profile", "location", "knowledge_update"),
    "job": ("profile",),
    "degree": ("profile",),
    "commute": ("profile",),
    "family": ("profile",),
}


class ScopeFirstGraphRetriever:
    """Retrieve by matching scope nodes first, then expanding the scoped subgraph."""

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
    ) -> None:
        self.top_scopes = top_scopes
        self.top_entities = top_entities
        self.max_events_per_scope = max_events_per_scope
        self.max_claims = max_claims
        self.max_sessions = max_sessions
        self.max_evidence = max_evidence
        self.neighbor_window = neighbor_window
        self.relation_depth = relation_depth
        self.lexical_fallback_events = lexical_fallback_events

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

        event_scores: Dict[str, float] = defaultdict(float)
        for event_id, source_score in scoped_events.items():
            event_scores[event_id] += source_score
        for event_id, source_score in entity_events.items():
            event_scores[event_id] += 0.7 * source_score
        for event_id, lexical_score in fallback_events.items():
            event_scores[event_id] += 0.5 * lexical_score

        claim_scores = self.expand_claims_from_events(graph, event_scores, query_terms, question_type)
        claim_scores = self.expand_claim_relations(graph, claim_scores)
        ranked_claims = [claim_id for claim_id, _ in sorted(claim_scores.items(), key=lambda item: (-item[1], self._claim_sort_key(graph, item[0])))][
            : self.max_claims
        ]
        ranked_events = self.events_for_claims(graph, ranked_claims)
        ranked_events.extend(event_scores.keys())
        ranked_events = self.with_neighbor_events(graph, ranked_events)
        evidence_snippets = self.evidence_snippets(graph, ranked_events, claim_scores, event_scores)
        relevant_session_ids = self.rank_sessions(graph, evidence_snippets, claim_scores, event_scores)

        matched_scopes = [
            self.scope_view(graph, scope_id, score)
            for scope_id, score in sorted(scope_scores.items(), key=lambda item: (-item[1], item[0]))[: self.top_scopes]
        ]
        matched_entities = [
            self.entity_view(graph, entity_id, score)
            for entity_id, score in sorted(entity_scores.items(), key=lambda item: (-item[1], item[0]))[: self.top_entities]
        ]
        return {
            "relevant_session_ids": relevant_session_ids[: self.max_sessions],
            "evidence_snippets": evidence_snippets[: self.max_evidence],
            "state_facets": [],
            "rejected_claims": self.rejected_claims_for_active_claims(graph, ranked_claims),
            "enough_evidence": bool(evidence_snippets),
            "retrieval_strategy": "scope_first_expand",
            "matched_scopes": matched_scopes,
            "matched_entities": matched_entities,
            "scoped_node_counts": {
                "scopes": len(scope_scores),
                "entities": len(entity_scores),
                "events": len(event_scores),
                "claims": len(claim_scores),
                "sessions": len(relevant_session_ids),
            },
        }

    def rank_scope_nodes(self, graph: nx.MultiDiGraph, question: str, question_type: str) -> Dict[str, float]:
        query_terms = self._query_terms(question)
        query_scope_hints = self._query_scope_hints(query_terms)
        priors = QUESTION_TYPE_SCOPE_PRIORS.get(question_type, {})
        scores: List[Tuple[str, float]] = []
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") != NODE_ENTITY_SCOPE or data.get("subtype") != "scope":
                continue
            label = self._normalize(str(data.get("label", "")))
            label_terms = self._split_label(label)
            score = 0.0
            score += 3.0 if label in query_scope_hints else 0.0
            score += 1.2 * len(set(label_terms) & set(query_terms))
            score += float(priors.get(label, 0.0))
            score += 0.08 * math.log1p(graph.degree(node_id))
            if not score and label in {"profile", "preference", "knowledge_update", "recommendation", "temporal_event"}:
                score += 0.1
            if score > 0:
                scores.append((str(node_id), score))
        scores.sort(key=lambda item: (-item[1], item[0]))
        return dict(scores[: self.top_scopes])

    def rank_entity_nodes(self, graph: nx.MultiDiGraph, query_terms: Sequence[str]) -> Dict[str, float]:
        scores: List[Tuple[str, float]] = []
        query_set = set(query_terms)
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") != NODE_ENTITY_SCOPE or data.get("subtype") != "entity":
                continue
            label = self._normalize(str(data.get("label", "")))
            label_terms = self._split_label(label)
            overlap = len(set(label_terms) & query_set)
            if not overlap and label not in query_set:
                continue
            score = 2.0 * overlap + (1.0 if label in query_set else 0.0) + 0.05 * math.log1p(graph.degree(node_id))
            scores.append((str(node_id), score))
        scores.sort(key=lambda item: (-item[1], item[0]))
        return dict(scores[: self.top_entities])

    def rank_event_nodes(self, graph: nx.MultiDiGraph, query_terms: Sequence[str], limit: int) -> Dict[str, float]:
        docs = []
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") == NODE_EVENT:
                text = f"{data.get('role', '')} {data.get('date', '')} {data.get('text', '')}"
                docs.append((str(node_id), text))
        return self._rank_text_docs(docs, query_terms, limit)

    def expand_scope_events(self, graph: nx.MultiDiGraph, scope_scores: Mapping[str, float]) -> Dict[str, float]:
        events: Dict[str, float] = defaultdict(float)
        for scope_id, score in scope_scores.items():
            count = 0
            for source, _, _, data in graph.in_edges(scope_id, keys=True, data=True):
                if data.get("edge_type") != EDGE_EVENT_IN_SCOPE:
                    continue
                if graph.nodes[source].get("node_type") != NODE_EVENT:
                    continue
                events[str(source)] += float(score)
                count += 1
                if count >= self.max_events_per_scope:
                    break
        return dict(events)

    def expand_entity_events(self, graph: nx.MultiDiGraph, entity_scores: Mapping[str, float]) -> Dict[str, float]:
        events: Dict[str, float] = defaultdict(float)
        for entity_id, score in entity_scores.items():
            for source, _, _, data in graph.in_edges(entity_id, keys=True, data=True):
                if data.get("edge_type") != EDGE_EVENT_MENTIONS_ENTITY:
                    continue
                if graph.nodes[source].get("node_type") == NODE_EVENT:
                    events[str(source)] += float(score)
        return dict(events)

    def expand_claims_from_events(
        self,
        graph: nx.MultiDiGraph,
        event_scores: Mapping[str, float],
        query_terms: Sequence[str],
        question_type: str,
    ) -> Dict[str, float]:
        event_set = set(event_scores)
        query_set = set(query_terms)
        claim_scores: Dict[str, float] = defaultdict(float)
        role_bonus = {
            "single-session-assistant": {"assistant": 0.6},
            "single-session-user": {"user": 0.5},
            "single-session-preference": {"user": 0.4},
        }.get(question_type, {})
        for claim_id, event_id, _, edge_data in graph.edges(keys=True, data=True):
            if edge_data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            event_id = str(event_id)
            if event_id not in event_set:
                continue
            claim_data = graph.nodes[claim_id]
            if claim_data.get("node_type") != NODE_CLAIM:
                continue
            text = self._claim_text(claim_data)
            terms = set(self._tokens(text, keep_stopwords=False))
            score = float(event_scores[event_id])
            score += 0.8 * len(terms & query_set)
            for label in list(claim_data.get("entity_labels") or []) + list(claim_data.get("scope_labels") or []):
                if self._normalize(str(label)) in query_set:
                    score += 1.0
            if claim_data.get("has_update_marker") or claim_data.get("has_correction_marker"):
                score += 0.3
            score += float(role_bonus.get(str(claim_data.get("role", "")), 0.0))
            score += 0.05 * min(max(int(claim_data.get("sort_key", 0)), 0) / 1_000_000_000.0, 1.0)
            claim_scores[str(claim_id)] += score
        return dict(claim_scores)

    def expand_claim_relations(self, graph: nx.MultiDiGraph, claim_scores: Mapping[str, float]) -> Dict[str, float]:
        relation_edges = {
            EDGE_CLAIM_SUPERSEDES_CLAIM,
            EDGE_CLAIM_CORRECTS_CLAIM,
            EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
        }
        expanded: Dict[str, float] = defaultdict(float, {str(k): float(v) for k, v in claim_scores.items()})
        frontier = [(str(claim_id), float(score), 0) for claim_id, score in claim_scores.items()]
        seen = {claim_id for claim_id, _, _ in frontier}
        while frontier:
            claim_id, score, depth = frontier.pop(0)
            if depth >= self.relation_depth:
                continue
            edges = list(graph.out_edges(claim_id, keys=True, data=True)) + list(graph.in_edges(claim_id, keys=True, data=True))
            for source, target, _, data in edges:
                if data.get("edge_type") not in relation_edges:
                    continue
                for neighbor in (source, target):
                    neighbor = str(neighbor)
                    if neighbor == claim_id or graph.nodes[neighbor].get("node_type") != NODE_CLAIM:
                        continue
                    expanded[neighbor] += 0.65 * score
                    if neighbor not in seen:
                        seen.add(neighbor)
                        frontier.append((neighbor, 0.65 * score, depth + 1))
        return dict(expanded)

    def events_for_claims(self, graph: nx.MultiDiGraph, claim_ids: Sequence[str]) -> List[str]:
        event_ids: List[str] = []
        for claim_id in claim_ids:
            if not graph.has_node(claim_id):
                continue
            for _, target, _, data in graph.out_edges(claim_id, keys=True, data=True):
                if data.get("edge_type") == EDGE_CLAIM_SUPPORTED_BY_EVENT and graph.nodes[target].get("node_type") == NODE_EVENT:
                    event_ids.append(str(target))
        return self._ordered_unique(event_ids)

    def with_neighbor_events(self, graph: nx.MultiDiGraph, event_ids: Sequence[str]) -> List[str]:
        by_session: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
        wanted = set(str(event_id) for event_id in event_ids)
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") != NODE_EVENT:
                continue
            by_session[str(data.get("session_id", ""))].append((int(data.get("sort_key", 0)), str(node_id)))
        for values in by_session.values():
            values.sort()
        expanded: List[str] = []
        for session_events in by_session.values():
            id_to_index = {event_id: index for index, (_, event_id) in enumerate(session_events)}
            for event_id in list(wanted):
                if event_id not in id_to_index:
                    continue
                index = id_to_index[event_id]
                start = max(0, index - self.neighbor_window)
                end = min(len(session_events), index + self.neighbor_window + 1)
                expanded.extend(event for _, event in session_events[start:end])
        return self._ordered_unique(list(event_ids) + expanded)

    def evidence_snippets(
        self,
        graph: nx.MultiDiGraph,
        event_ids: Sequence[str],
        claim_scores: Mapping[str, float],
        event_scores: Mapping[str, float],
    ) -> List[Dict[str, Any]]:
        event_claim_score: Dict[str, float] = defaultdict(float)
        for claim_id, claim_score in claim_scores.items():
            for event_id in self.events_for_claims(graph, [claim_id]):
                event_claim_score[event_id] += float(claim_score)
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
                        "why_relevant": "scope-first expansion",
                        "scope_score": score,
                    },
                )
            )
        snippets.sort(key=lambda item: (-item[0], item[1].get("date", ""), item[1].get("session_id", "")))
        return [item for _, item in snippets]

    def rank_sessions(
        self,
        graph: nx.MultiDiGraph,
        evidence_snippets: Sequence[Mapping[str, Any]],
        claim_scores: Mapping[str, float],
        event_scores: Mapping[str, float],
    ) -> List[str]:
        del graph, claim_scores, event_scores
        scores: Dict[str, float] = defaultdict(float)
        for rank, item in enumerate(evidence_snippets):
            session_id = str(item.get("session_id", ""))
            if not session_id:
                continue
            scores[session_id] += float(item.get("scope_score", 0.0)) + 1.0 / (rank + 1)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [session_id for session_id, _ in ranked]

    def rejected_claims_for_active_claims(self, graph: nx.MultiDiGraph, claim_ids: Sequence[str]) -> List[Dict[str, Any]]:
        reason_by_edge = {
            EDGE_CLAIM_SUPERSEDES_CLAIM: "stale",
            EDGE_CLAIM_CORRECTS_CLAIM: "contradicted",
            EDGE_CLAIM_CONFLICTS_WITH_CLAIM: "contradicted",
        }
        rejected: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for claim_id in claim_ids:
            if not graph.has_node(claim_id):
                continue
            for _, target, _, data in graph.out_edges(claim_id, keys=True, data=True):
                edge_type = data.get("edge_type")
                if edge_type not in reason_by_edge or graph.nodes[target].get("node_type") != NODE_CLAIM:
                    continue
                target = str(target)
                if target in seen:
                    continue
                seen.add(target)
                rejected.append(
                    {
                        "claim": str(graph.nodes[target].get("text", "")),
                        "reason": reason_by_edge[str(edge_type)],
                        "support_session_ids": self._support_session_ids_for_claim(graph, target),
                    }
                )
        return rejected

    def scope_view(self, graph: nx.MultiDiGraph, scope_id: str, score: float) -> Dict[str, Any]:
        data = graph.nodes[scope_id]
        return {
            "node_id": scope_id,
            "label": str(data.get("label", "")),
            "score": score,
            "degree": int(graph.degree(scope_id)),
        }

    def entity_view(self, graph: nx.MultiDiGraph, entity_id: str, score: float) -> Dict[str, Any]:
        data = graph.nodes[entity_id]
        return {
            "node_id": entity_id,
            "label": str(data.get("label", "")),
            "score": score,
            "degree": int(graph.degree(entity_id)),
        }

    def _support_session_ids_for_claim(self, graph: nx.MultiDiGraph, claim_id: str) -> List[str]:
        session_ids: List[str] = []
        for event_id in self.events_for_claims(graph, [claim_id]):
            session_id = graph.nodes[event_id].get("session_id")
            if session_id:
                session_ids.append(str(session_id))
        return self._ordered_unique(session_ids)

    def _claim_sort_key(self, graph: nx.MultiDiGraph, claim_id: str) -> Tuple[int, str]:
        if not graph.has_node(claim_id):
            return (0, claim_id)
        return (-int(graph.nodes[claim_id].get("sort_key", 0)), claim_id)

    def _claim_text(self, data: Mapping[str, Any]) -> str:
        labels = " ".join(str(item) for item in data.get("entity_labels") or [])
        scopes = " ".join(str(item) for item in data.get("scope_labels") or [])
        return f"{labels} {scopes} {data.get('date', '')} {data.get('role', '')} {data.get('text', '')}"

    def _query_scope_hints(self, query_terms: Sequence[str]) -> Set[str]:
        hints: Set[str] = set()
        for term in query_terms:
            hints.update(QUERY_SCOPE_HINTS.get(term, ()))
        return hints

    def _query_terms(self, question: str) -> List[str]:
        return self._ordered_unique(self._tokens(question, keep_stopwords=False))

    def _rank_text_docs(self, docs: Sequence[Tuple[str, str]], query_terms: Sequence[str], limit: int) -> Dict[str, float]:
        if not docs or not query_terms or limit <= 0:
            return {}
        doc_terms = [(doc_id, Counter(self._tokens(text, keep_stopwords=False))) for doc_id, text in docs]
        doc_count = len(doc_terms)
        avg_len = sum(sum(counter.values()) for _, counter in doc_terms) / max(doc_count, 1)
        df: Counter[str] = Counter()
        for _, counter in doc_terms:
            df.update(counter.keys())
        query_counter = Counter(query_terms)
        scores: Dict[str, float] = {}
        k1 = 1.5
        b = 0.75
        for doc_id, counter in doc_terms:
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
                scores[doc_id] = score
        return dict(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit])

    def _split_label(self, label: str) -> List[str]:
        return [part for part in label.split("_") if part]

    def _tokens(self, text: str, keep_stopwords: bool) -> List[str]:
        terms: List[str] = []
        for term in re.findall(r"[a-zA-Z0-9_']+", text.lower()):
            normalized = self._normalize(term)
            if not normalized or len(normalized) <= 1:
                continue
            if not keep_stopwords and normalized in STOPWORDS:
                continue
            terms.append(normalized)
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


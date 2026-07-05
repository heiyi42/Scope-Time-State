from __future__ import annotations

from collections import Counter, defaultdict
import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple
import weakref

import networkx as nx

from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import (
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_EVENT_IN_SCOPE,
    EDGE_EVENT_MENTIONS_ENTITY,
    NODE_CLAIM,
    NODE_ENTITY_SCOPE,
    NODE_EVENT,
)

from .scope_retriever import QUESTION_TYPE_SCOPE_PRIORS, ScopeFirstGraphRetriever


class ScopeProfileGraphRetriever(ScopeFirstGraphRetriever):
    """V7.1-clean: improve only scope ranking using graph-derived profiles and IDF."""

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
        scope_profile_events: int = 120,
        scope_profile_terms: int = 32,
        scope_idf_weight: float = 0.25,
        scope_profile_weight: float = 1.0,
        scope_prior_weight: float = 0.35,
        scope_keep_ratio: float = 0.55,
        min_scopes: int = 1,
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
        self.scope_profile_terms = scope_profile_terms
        self.scope_idf_weight = scope_idf_weight
        self.scope_profile_weight = scope_profile_weight
        self.scope_prior_weight = scope_prior_weight
        self.scope_keep_ratio = scope_keep_ratio
        self.min_scopes = min_scopes
        self._profile_cache: weakref.WeakKeyDictionary[nx.MultiDiGraph, Dict[str, Dict[str, Any]]] = weakref.WeakKeyDictionary()

    def retrieve_state_packet(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        question_type: str = "",
        question_date: str = "",
    ) -> Dict[str, Any]:
        packet = super().retrieve_state_packet(graph, question, question_type, question_date)
        packet["retrieval_strategy"] = "v7_1_scope_profile_idf"
        return packet

    def rank_scope_nodes(self, graph: nx.MultiDiGraph, question: str, question_type: str) -> Dict[str, float]:
        query_terms = self._expanded_query_terms(self._query_terms(question))
        priors = QUESTION_TYPE_SCOPE_PRIORS.get(question_type, {})
        profiles = self.scope_profiles(graph)
        query_term_idf = self._query_term_scope_idf(profiles, query_terms)
        scored: List[Tuple[str, float]] = []
        for scope_id, profile in profiles.items():
            label = str(profile["label"])
            label_terms = set(self._split_label(label))
            profile_terms = profile["term_counts"]
            label_overlap = len(label_terms & set(query_terms))
            profile_score = self._profile_match_score(profile_terms, query_terms, query_term_idf)
            lexical_support = profile_score + label_overlap
            if lexical_support <= 0:
                continue
            prior_score = float(priors.get(label, 0.0))
            idf = float(profile["idf"])
            support_gate = min(1.0, lexical_support)
            coverage = self._query_coverage(profile_terms, query_terms)
            score = (
                1.6 * label_overlap
                + self.scope_profile_weight * profile_score
                + 0.35 * coverage
                + self.scope_prior_weight * prior_score * support_gate
                + self.scope_idf_weight * idf * support_gate
            )
            scored.append((scope_id, score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        if not scored:
            return {}
        best = scored[0][1]
        threshold = best * self.scope_keep_ratio
        kept = [(scope_id, score) for scope_id, score in scored if score >= threshold]
        if len(kept) < self.min_scopes:
            kept = scored[: self.min_scopes]
        return dict(kept[: self.top_scopes])

    def scope_view(self, graph: nx.MultiDiGraph, scope_id: str, score: float) -> Dict[str, Any]:
        data = graph.nodes[scope_id]
        profile = self.scope_profiles(graph).get(scope_id, {})
        return {
            "node_id": scope_id,
            "label": str(data.get("label", "")),
            "score": score,
            "degree": int(graph.degree(scope_id)),
            "scope_idf": float(profile.get("idf", 0.0)),
            "event_count": int(profile.get("event_count", 0)),
            "profile_terms": [term for term, _ in profile.get("top_terms", [])[:10]],
        }

    def scope_profiles(self, graph: nx.MultiDiGraph) -> Dict[str, Dict[str, Any]]:
        cached = self._profile_cache.get(graph)
        if cached is not None:
            return cached

        total_events = sum(1 for _, data in graph.nodes(data=True) if data.get("node_type") == NODE_EVENT)
        event_claims = self._event_claims(graph)
        event_entities = self._event_entities(graph)
        profiles: Dict[str, Dict[str, Any]] = {}
        for scope_id, data in graph.nodes(data=True):
            if data.get("node_type") != NODE_ENTITY_SCOPE or data.get("subtype") != "scope":
                continue
            event_ids = self._events_for_scope(graph, str(scope_id))
            term_counts: Counter[str] = Counter()
            label = self._normalize(str(data.get("label", "")))
            term_counts.update(self._split_label(label))
            sampled_events = self._sample_event_ids(event_ids, self.scope_profile_events)
            for event_id in sampled_events:
                event_data = graph.nodes[event_id]
                term_counts.update(self._tokens(str(event_data.get("text", "")), keep_stopwords=False))
                for entity_label in event_entities.get(event_id, []):
                    term_counts.update(self._split_label(entity_label))
                for claim_id in event_claims.get(event_id, []):
                    claim_data = graph.nodes[claim_id]
                    term_counts.update(self._tokens(str(claim_data.get("text", "")), keep_stopwords=False))
                    for label_item in claim_data.get("entity_labels") or []:
                        term_counts.update(self._split_label(self._normalize(str(label_item))))
            top_terms = term_counts.most_common(self.scope_profile_terms)
            idf = math.log((1.0 + total_events) / (1.0 + len(event_ids))) if total_events else 0.0
            profiles[str(scope_id)] = {
                "label": label,
                "event_count": len(event_ids),
                "idf": idf,
                "term_counts": term_counts,
                "top_terms": top_terms,
            }
        self._profile_cache[graph] = profiles
        return profiles

    def _events_for_scope(self, graph: nx.MultiDiGraph, scope_id: str) -> List[str]:
        events: List[Tuple[int, str]] = []
        for source, _, _, data in graph.in_edges(scope_id, keys=True, data=True):
            if data.get("edge_type") != EDGE_EVENT_IN_SCOPE:
                continue
            if graph.nodes[source].get("node_type") != NODE_EVENT:
                continue
            events.append((int(graph.nodes[source].get("sort_key", 0)), str(source)))
        events.sort(reverse=True)
        return [event_id for _, event_id in events]

    def _sample_event_ids(self, event_ids: Sequence[str], limit: int) -> List[str]:
        if len(event_ids) <= limit:
            return list(event_ids)
        if limit <= 1:
            return [event_ids[0]]
        step = (len(event_ids) - 1) / float(limit - 1)
        selected = [event_ids[round(index * step)] for index in range(limit)]
        return self._ordered_unique(selected)

    def _event_claims(self, graph: nx.MultiDiGraph) -> Dict[str, List[str]]:
        event_claims: Dict[str, List[str]] = defaultdict(list)
        for claim_id, event_id, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_CLAIM_SUPPORTED_BY_EVENT:
                continue
            if graph.nodes[claim_id].get("node_type") == NODE_CLAIM and graph.nodes[event_id].get("node_type") == NODE_EVENT:
                event_claims[str(event_id)].append(str(claim_id))
        return event_claims

    def _event_entities(self, graph: nx.MultiDiGraph) -> Dict[str, List[str]]:
        event_entities: Dict[str, List[str]] = defaultdict(list)
        for event_id, entity_id, _, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") != EDGE_EVENT_MENTIONS_ENTITY:
                continue
            if graph.nodes[event_id].get("node_type") != NODE_EVENT:
                continue
            entity_data = graph.nodes[entity_id]
            if entity_data.get("node_type") == NODE_ENTITY_SCOPE and entity_data.get("subtype") == "entity":
                event_entities[str(event_id)].append(self._normalize(str(entity_data.get("label", ""))))
        return event_entities

    def _profile_match_score(
        self,
        term_counts: Mapping[str, int],
        query_terms: Sequence[str],
        query_term_idf: Mapping[str, float],
    ) -> float:
        if not term_counts or not query_terms:
            return 0.0
        score = 0.0
        doc_len = sum(int(value) for value in term_counts.values())
        for term, query_count in Counter(query_terms).items():
            freq = int(term_counts.get(term, 0))
            if not freq:
                continue
            tf = freq / (freq + 1.2 + 0.75 * doc_len / max(len(term_counts), 1))
            score += query_count * float(query_term_idf.get(term, 1.0)) * tf
        return score

    def _query_term_scope_idf(
        self,
        profiles: Mapping[str, Mapping[str, Any]],
        query_terms: Sequence[str],
    ) -> Dict[str, float]:
        profile_count = len(profiles)
        idf: Dict[str, float] = {}
        for term in set(query_terms):
            df = sum(1 for profile in profiles.values() if int(profile["term_counts"].get(term, 0)) > 0)
            if df:
                idf[term] = math.log(1.0 + (profile_count - df + 0.5) / (df + 0.5))
        return idf

    def _query_coverage(self, term_counts: Mapping[str, int], query_terms: Sequence[str]) -> float:
        unique_terms = set(query_terms)
        if not unique_terms:
            return 0.0
        matched = sum(1 for term in unique_terms if int(term_counts.get(term, 0)) > 0)
        return matched / len(unique_terms)

    def _expanded_query_terms(self, query_terms: Sequence[str]) -> List[str]:
        expanded: List[str] = []
        for term in query_terms:
            expanded.append(term)
            expanded.extend(self._term_variants(term))
        return self._ordered_unique(expanded)

    def _term_variants(self, term: str) -> List[str]:
        variants: List[str] = []
        if len(term) > 4 and term.endswith("ies"):
            variants.append(term[:-3] + "y")
        if len(term) > 4 and term.endswith("es"):
            variants.append(term[:-2])
        if len(term) > 3 and term.endswith("s"):
            variants.append(term[:-1])
        return variants

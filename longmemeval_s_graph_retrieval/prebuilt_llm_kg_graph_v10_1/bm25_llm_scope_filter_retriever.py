from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Protocol, Sequence, Tuple

import networkx as nx

from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import (
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_FACET_SUPPORTED_BY_CLAIM,
    NODE_CLAIM,
    NODE_STATE_FACET,
)

from .bm25_scope_retriever import BM25ScopeProfileGraphRetriever


class JsonLLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        ...


class BM25LLMScopeFilterError(RuntimeError):
    pass


class BM25LLMScopeFilterGraphRetriever(BM25ScopeProfileGraphRetriever):
    """V10.1: BM25 scope recall followed by conservative LLM semantic denoising."""

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
        scope_profile_events: int = 5,
        scope_profile_claims: int = 10,
        scope_profile_event_tokens: int = 80,
        scope_profile_claim_tokens: int = 60,
        scope_label_weight: int = 3,
        entity_label_weight: int = 2,
        filter_profile_events: int = 4,
        filter_profile_claims: int = 6,
        filter_profile_entities: int = 8,
        filter_profile_facets: int = 4,
        filter_profile_event_tokens: int = 45,
        filter_profile_claim_tokens: int = 45,
        filter_profile_facet_tokens: int = 30,
        min_filtered_scopes: int = 2,
        scope_filter_fallback: str = "bm25",
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
            scope_profile_events=scope_profile_events,
            scope_profile_claims=scope_profile_claims,
            scope_profile_event_tokens=scope_profile_event_tokens,
            scope_profile_claim_tokens=scope_profile_claim_tokens,
            scope_label_weight=scope_label_weight,
            entity_label_weight=entity_label_weight,
        )
        if scope_filter_fallback not in {"bm25", "error"}:
            raise ValueError("scope_filter_fallback must be 'bm25' or 'error'")
        if min_filtered_scopes < 1:
            raise ValueError("min_filtered_scopes must be >= 1")
        self.scope_client = scope_client
        self.filter_profile_events = filter_profile_events
        self.filter_profile_claims = filter_profile_claims
        self.filter_profile_entities = filter_profile_entities
        self.filter_profile_facets = filter_profile_facets
        self.filter_profile_event_tokens = filter_profile_event_tokens
        self.filter_profile_claim_tokens = filter_profile_claim_tokens
        self.filter_profile_facet_tokens = filter_profile_facet_tokens
        self.min_filtered_scopes = min_filtered_scopes
        self.scope_filter_fallback = scope_filter_fallback
        self._last_scope_ranker = "bm25_scope_profile_llm_filter"
        self._last_llm_scope_filter: Dict[str, Any] = {}

    def retrieve_state_packet(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        question_type: str = "",
        question_date: str = "",
    ) -> Dict[str, Any]:
        packet = super().retrieve_state_packet(graph, question, question_type, question_date)
        packet["retrieval_strategy"] = "v10_1_bm25_llm_scope_filter_expand"
        packet["scope_ranker"] = self._last_scope_ranker
        packet["llm_scope_filter"] = self._last_llm_scope_filter
        return packet

    def rank_scope_nodes(self, graph: nx.MultiDiGraph, question: str, question_type: str) -> Dict[str, float]:
        bm25_scores = super().rank_scope_nodes(graph, question, question_type)
        bm25_ranker = self._last_scope_ranker
        if not bm25_scores:
            self._last_scope_ranker = bm25_ranker
            self._last_llm_scope_filter = {
                "mode": "bm25_topk_llm_filter",
                "status": "skipped",
                "reason": "no_bm25_scopes",
            }
            return bm25_scores

        candidates = self.scope_filter_candidates(graph, question, bm25_scores)
        try:
            raw = self.scope_client.complete_json(
                llm_scope_filter_system_prompt(),
                llm_scope_filter_user_prompt(question, question_type, candidates, self.min_filtered_scopes),
            )
            filtered_scores, audit = self.parse_scope_filter(raw, candidates, bm25_scores)
        except Exception as exc:
            if self.scope_filter_fallback == "error":
                raise BM25LLMScopeFilterError(f"LLM scope filter failed: {exc}") from exc
            filtered_scores = dict(bm25_scores)
            audit = self.fallback_audit(candidates, bm25_scores, str(exc))

        self._last_scope_ranker = "bm25_scope_profile_llm_filter"
        self._last_llm_scope_filter = audit
        return filtered_scores

    def scope_filter_candidates(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        bm25_scores: Mapping[str, float],
    ) -> List[Dict[str, Any]]:
        query_terms = self._query_terms(question)
        profile_docs = dict(self.scope_profile_docs(graph))
        candidates: List[Dict[str, Any]] = []
        for rank, (scope_id, score) in enumerate(
            sorted(bm25_scores.items(), key=lambda item: (-item[1], item[0])),
            start=1,
        ):
            if not graph.has_node(scope_id):
                continue
            data = graph.nodes[scope_id]
            event_ids = self.filter_event_ids_for_scope(graph, scope_id, query_terms)
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
                        "text": self.truncated_prompt_text(
                            str(event_data.get("text", "")),
                            self.filter_profile_event_tokens,
                        ),
                    }
                )
                entity_labels.extend(self.entity_labels_for_event(graph, event_id))
                remaining_claims = self.filter_profile_claims - len(claims)
                if remaining_claims > 0:
                    event_claims = self.claim_views_for_event(graph, event_id, remaining_claims)
                    claims.extend(event_claims)
                    remaining_facets = self.filter_profile_facets - len(facets)
                    if remaining_facets > 0:
                        facets.extend(
                            self.facet_views_for_claims(
                                graph,
                                [item["node_id"] for item in event_claims],
                                remaining_facets,
                            )
                        )

            doc_terms = set(self._tokens(profile_docs.get(scope_id, ""), keep_stopwords=False))
            matched_terms = [term for term in query_terms if term in doc_terms]
            candidates.append(
                {
                    "node_id": scope_id,
                    "label": str(data.get("label", "")),
                    "bm25_rank": rank,
                    "bm25_score": round(float(score), 6),
                    "degree": int(graph.degree(scope_id)),
                    "event_count": len(self.event_ids_for_scope(graph, scope_id)),
                    "matched_terms": matched_terms[:12],
                    "nearby_entities": self._ordered_unique(entity_labels)[: self.filter_profile_entities],
                    "nearby_events": events[: self.filter_profile_events],
                    "nearby_claims": claims[: self.filter_profile_claims],
                    "nearby_state_facets": facets[: self.filter_profile_facets],
                }
            )
        return candidates

    def filter_event_ids_for_scope(
        self,
        graph: nx.MultiDiGraph,
        scope_id: str,
        query_terms: Sequence[str],
    ) -> List[str]:
        event_ids = self.event_ids_for_scope(graph, scope_id)
        if not event_ids:
            return []
        docs: List[Tuple[str, str]] = []
        for event_id in event_ids:
            event_data = graph.nodes[event_id]
            docs.append(
                (
                    event_id,
                    f"{event_data.get('role', '')} {event_data.get('date', '')} {event_data.get('text', '')}",
                )
            )
        ranked = list(self._rank_text_docs(docs, query_terms, self.filter_profile_events).keys())
        return self._ordered_unique(ranked + event_ids)[: self.filter_profile_events]

    def parse_scope_filter(
        self,
        raw: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        bm25_scores: Mapping[str, float],
    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
        candidate_by_id = {str(item.get("node_id", "")): item for item in candidates}
        selected_by_id: Dict[str, Dict[str, Any]] = {}
        for item in raw.get("selected_scopes", []):
            node_id, score, reason = self.parse_scope_item(item)
            if node_id in candidate_by_id and node_id not in selected_by_id:
                selected_by_id[node_id] = {
                    "node_id": node_id,
                    "keep_score": score,
                    "reason": reason,
                    "source": "llm",
                }

        rejected = []
        for item in raw.get("rejected_scopes", []):
            node_id, score, reason = self.parse_scope_item(item)
            if node_id in candidate_by_id:
                rejected.append(
                    {
                        "node_id": node_id,
                        "keep_score": score,
                        "reason": reason,
                    }
                )

        ordered_bm25_ids = [
            str(scope_id)
            for scope_id, _ in sorted(bm25_scores.items(), key=lambda item: (-item[1], item[0]))
        ]
        fallback_used = False
        fallback_reason = ""
        backfilled: List[str] = []
        if not selected_by_id:
            fallback_used = True
            fallback_reason = "llm_selected_no_valid_scopes"
            selected_ids = ordered_bm25_ids
        else:
            selected_ids = [scope_id for scope_id in ordered_bm25_ids if scope_id in selected_by_id]
            if len(selected_ids) < self.min_filtered_scopes:
                fallback_used = True
                fallback_reason = "below_min_filtered_scopes"
                for scope_id in ordered_bm25_ids:
                    if len(selected_ids) >= self.min_filtered_scopes:
                        break
                    if scope_id not in selected_ids:
                        selected_ids.append(scope_id)
                        backfilled.append(scope_id)

        filtered_scores = {scope_id: float(bm25_scores[scope_id]) for scope_id in selected_ids}
        selected = []
        for scope_id in selected_ids:
            item = selected_by_id.get(
                scope_id,
                {
                    "node_id": scope_id,
                    "keep_score": None,
                    "reason": "BM25 backfill safeguard",
                    "source": "bm25_backfill",
                },
            )
            scope_card = candidate_by_id.get(scope_id, {})
            selected.append(
                {
                    **item,
                    "bm25_rank": scope_card.get("bm25_rank"),
                    "bm25_score": scope_card.get("bm25_score"),
                    "label": scope_card.get("label"),
                }
            )
        audit = {
            "mode": "bm25_topk_llm_filter",
            "status": "ok",
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "min_filtered_scopes": self.min_filtered_scopes,
            "bm25_candidate_count": len(candidates),
            "selected_scopes": selected,
            "rejected_scopes": rejected,
            "bm25_backfilled_scope_ids": backfilled,
            "candidate_scopes": list(candidates),
            "raw": json_safe_for_audit(raw),
        }
        return filtered_scores, audit

    def parse_scope_item(self, item: Any) -> Tuple[str, Any, str]:
        if isinstance(item, str):
            return item, None, ""
        if not isinstance(item, Mapping):
            return "", None, ""
        node_id = str(item.get("node_id") or item.get("scope_id") or "")
        score = item.get("keep_score", item.get("score", item.get("confidence")))
        reason = str(item.get("reason", ""))[:500]
        return node_id, self.normalized_optional_score(score), reason

    def normalized_optional_score(self, value: Any) -> Any:
        if value is None:
            return None
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        return min(max(score, 0.0), 1.0)

    def fallback_audit(
        self,
        candidates: Sequence[Mapping[str, Any]],
        bm25_scores: Mapping[str, float],
        reason: str,
    ) -> Dict[str, Any]:
        ordered_bm25_ids = [
            str(scope_id)
            for scope_id, _ in sorted(bm25_scores.items(), key=lambda item: (-item[1], item[0]))
        ]
        candidate_by_id = {str(item.get("node_id", "")): item for item in candidates}
        return {
            "mode": "bm25_topk_llm_filter",
            "status": "fallback",
            "fallback_used": True,
            "fallback_reason": reason[:500],
            "selected_scopes": [
                {
                    "node_id": scope_id,
                    "source": "bm25_fallback",
                    "bm25_rank": candidate_by_id.get(scope_id, {}).get("bm25_rank"),
                    "bm25_score": candidate_by_id.get(scope_id, {}).get("bm25_score"),
                    "label": candidate_by_id.get(scope_id, {}).get("label"),
                }
                for scope_id in ordered_bm25_ids
            ],
            "rejected_scopes": [],
            "candidate_scopes": list(candidates),
        }

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
                        "text": self.truncated_prompt_text(
                            str(claim_data.get("text", "")),
                            self.filter_profile_claim_tokens,
                        ),
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
                        "value": self.truncated_prompt_text(
                            str(facet_data.get("value", "")),
                            self.filter_profile_facet_tokens,
                        ),
                    },
                )
            )
        facets.sort(key=lambda item: item[0])
        return [item for _, item in facets[:limit]]

    def truncated_prompt_text(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        return " ".join(self._tokens(text, keep_stopwords=True)[:max_tokens])


def llm_scope_filter_system_prompt() -> str:
    return (
        "You are a conservative semantic denoising component for graph retrieval. "
        "You receive a question and BM25-recalled scope candidates. "
        "Keep every scope that may contain any evidence needed to answer the question, including partial evidence for multi-session questions. "
        "Reject only scopes that are clearly unrelated. "
        "Use only candidate node_ids. Do not answer the question. Return strict JSON only."
    )


def llm_scope_filter_user_prompt(
    question: str,
    question_type: str,
    candidates: Sequence[Mapping[str, Any]],
    min_filtered_scopes: int,
) -> str:
    payload = {
        "question": question,
        "question_type": question_type,
        "task": "Filter noisy BM25 scope candidates before graph expansion.",
        "instructions": [
            "This is a denoising step, not a single-best-scope selection step.",
            "Keep scopes that may contain direct, indirect, or complementary evidence for the question.",
            "For multi-session or temporal questions, keep multiple scopes when they may cover different sessions or time points.",
            "Reject a scope only when its label and graph-neighborhood evidence are clearly unrelated to the question.",
            "If uncertain, keep the scope.",
            "Do not invent node_ids. Use only node_id values from candidate_scopes.",
            "Return at least min_filtered_scopes selected scopes unless all candidates are clearly invalid.",
        ],
        "min_filtered_scopes": min_filtered_scopes,
        "candidate_scopes": list(candidates),
        "output_schema": {
            "selected_scopes": [
                {
                    "node_id": "candidate node_id",
                    "keep_score": 0.0,
                    "reason": "short semantic reason",
                }
            ],
            "rejected_scopes": [
                {
                    "node_id": "candidate node_id",
                    "reason": "short rejection reason",
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def json_safe_for_audit(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return {"unserializable": str(value)}

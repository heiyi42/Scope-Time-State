from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import networkx as nx

from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.scope_first_retriever import (
    ScopeFirstGraphRetriever,
)
from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_retriever import StatePacketGraphRetriever


class RecallGuardGraphRetriever:
    """Scope-first retriever with a state-first recall guard.

    The primary packet is produced by v4 scope-first retrieval. The v2
    state-first packet is used only when the scope-first packet appears
    structurally under-recalled.
    """

    def __init__(
        self,
        evidence_ratio_threshold: float = 0.60,
        facet_ratio_threshold: float = 0.60,
        session_ratio_threshold: float = 0.60,
        scope_first: Optional[ScopeFirstGraphRetriever] = None,
        state_first: Optional[StatePacketGraphRetriever] = None,
    ) -> None:
        self.evidence_ratio_threshold = evidence_ratio_threshold
        self.facet_ratio_threshold = facet_ratio_threshold
        self.session_ratio_threshold = session_ratio_threshold
        self.scope_first = scope_first or ScopeFirstGraphRetriever()
        self.state_first = state_first or StatePacketGraphRetriever()

    def retrieve_state_packet(self, graph: nx.MultiDiGraph, question: str, question_type: str = "") -> Dict[str, Any]:
        scope_packet = self.scope_first.retrieve_state_packet(
            graph,
            question=question,
            question_type=question_type,
        )
        state_packet = self.state_first.retrieve_state_packet(graph)
        guard_reasons = self._guard_reasons(scope_packet, state_packet)
        if not guard_reasons:
            scope_packet["retrieval_strategy"] = "scope_first_recall_guard_not_triggered"
            scope_packet["recall_guard_triggered"] = False
            return scope_packet

        merged = self._merge_packets(scope_packet, state_packet)
        merged["retrieval_strategy"] = "scope_first_with_state_first_recall_guard"
        merged["recall_guard_triggered"] = True
        merged["recall_guard_reasons"] = guard_reasons
        merged["scope_first_counts"] = self._counts(scope_packet)
        merged["state_first_counts"] = self._counts(state_packet)
        return merged

    def _guard_reasons(self, scope_packet: Mapping[str, Any], state_packet: Mapping[str, Any]) -> List[str]:
        reasons: List[str] = []
        if scope_packet.get("retrieval_strategy") == "state_first_fallback":
            reasons.append(str(scope_packet.get("fallback_reason") or "scope_first_fallback"))
        if self._too_small(scope_packet, state_packet, "evidence_snippets", self.evidence_ratio_threshold):
            reasons.append("evidence_under_recalled")
        if self._too_small(scope_packet, state_packet, "state_facets", self.facet_ratio_threshold):
            reasons.append("state_facets_under_recalled")
        if self._too_small(scope_packet, state_packet, "relevant_session_ids", self.session_ratio_threshold):
            reasons.append("sessions_under_recalled")
        return self._ordered_unique(reasons)

    def _too_small(
        self,
        scope_packet: Mapping[str, Any],
        state_packet: Mapping[str, Any],
        key: str,
        threshold: float,
    ) -> bool:
        scope_count = len(scope_packet.get(key) or [])
        state_count = len(state_packet.get(key) or [])
        if state_count <= 0:
            return False
        if scope_count <= 0:
            return True
        return (scope_count / state_count) < threshold

    def _merge_packets(self, scope_packet: Mapping[str, Any], state_packet: Mapping[str, Any]) -> Dict[str, Any]:
        evidence = self._merge_lists(
            scope_packet.get("evidence_snippets") or [],
            state_packet.get("evidence_snippets") or [],
            self._evidence_key,
        )
        facets = self._merge_lists(
            scope_packet.get("state_facets") or [],
            state_packet.get("state_facets") or [],
            self._facet_key,
        )
        rejected = self._merge_lists(
            scope_packet.get("rejected_claims") or [],
            state_packet.get("rejected_claims") or [],
            self._rejected_key,
        )
        relevant_session_ids = self._ordered_unique(
            list(scope_packet.get("relevant_session_ids") or [])
            + list(state_packet.get("relevant_session_ids") or [])
        )
        merged = dict(scope_packet)
        merged.update(
            {
                "relevant_session_ids": relevant_session_ids,
                "evidence_snippets": evidence,
                "state_facets": facets,
                "rejected_claims": rejected,
                "enough_evidence": bool(facets and evidence),
            }
        )
        return merged

    def _merge_lists(
        self,
        primary: Iterable[Mapping[str, Any]],
        supplemental: Iterable[Mapping[str, Any]],
        key_fn: Any,
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for item in list(primary) + list(supplemental):
            key = key_fn(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(item))
        return merged

    def _evidence_key(self, item: Mapping[str, Any]) -> Tuple[str, str, str, str]:
        return (
            str(item.get("session_id", "")),
            str(item.get("date", "")),
            str(item.get("role", "")),
            str(item.get("content", "")),
        )

    def _facet_key(self, item: Mapping[str, Any]) -> Tuple[str, str]:
        return (str(item.get("name", "")), str(item.get("value", "")))

    def _rejected_key(self, item: Mapping[str, Any]) -> Tuple[str, str]:
        return (str(item.get("claim", "")), str(item.get("reason", "")))

    def _counts(self, packet: Mapping[str, Any]) -> Dict[str, int]:
        return {
            "evidence_snippets": len(packet.get("evidence_snippets") or []),
            "state_facets": len(packet.get("state_facets") or []),
            "relevant_session_ids": len(packet.get("relevant_session_ids") or []),
            "rejected_claims": len(packet.get("rejected_claims") or []),
        }

    def _ordered_unique(self, values: Iterable[Any]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for value in values:
            item = str(value)
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered


from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import networkx as nx

from .graph_builder import (
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


REJECTION_REASON_BY_EDGE = {
    EDGE_CLAIM_SUPERSEDES_CLAIM: "stale",
    EDGE_CLAIM_CORRECTS_CLAIM: "contradicted",
    EDGE_CLAIM_CONFLICTS_WITH_CLAIM: "contradicted",
}


class StatePacketGraphRetriever:
    """Topology-driven State_packet retriever for the local task graph."""

    def retrieve_state_packet(self, graph: nx.MultiDiGraph) -> Dict[str, Any]:
        latest_time_node = self._latest_time_node(graph)
        invalidated_claim_ids = self._invalidated_claim_ids(graph)
        active_facet_ids = self._active_facets_for_time(graph, latest_time_node, invalidated_claim_ids)
        active_claim_ids = [
            claim_id
            for claim_id in self._claims_for_facets(graph, active_facet_ids)
            if claim_id not in invalidated_claim_ids
        ]

        state_facets = [
            self._state_facet_view(graph, facet_id, invalidated_claim_ids)
            for facet_id in active_facet_ids
        ]
        state_facets = [item for item in state_facets if item is not None]

        rejected_claims = self._rejected_claims_from_active_claims(graph, active_claim_ids)
        evidence_snippets = self._evidence_snippets(graph, active_claim_ids, rejected_claims)
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
            "enough_evidence": bool(state_facets and evidence_snippets),
        }

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

    def _active_facets_for_time(
        self,
        graph: nx.MultiDiGraph,
        latest_time_node: Optional[str],
        invalidated_claim_ids: Set[str],
    ) -> List[str]:
        if latest_time_node is None:
            return []
        facet_ids: List[str] = []
        for source, _, _, data in graph.in_edges(latest_time_node, keys=True, data=True):
            if data.get("edge_type") != EDGE_FACET_CURRENT_AFTER_TIME:
                continue
            if graph.nodes[source].get("node_type") != NODE_STATE_FACET:
                continue
            supported_claims = self._claims_for_facets(graph, [str(source)])
            if supported_claims and all(claim_id in invalidated_claim_ids for claim_id in supported_claims):
                continue
            facet_ids.append(str(source))
        return self._sort_facets(graph, facet_ids)

    def _sort_facets(self, graph: nx.MultiDiGraph, facet_ids: Sequence[str]) -> List[str]:
        return sorted(
            self._ordered_unique(facet_ids),
            key=lambda facet_id: str(graph.nodes[facet_id].get("name", "")),
        )

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

    def _invalidated_claim_ids(self, graph: nx.MultiDiGraph) -> Set[str]:
        invalidated: Set[str] = set()
        for _, target, data in graph.edges(data=True):
            if data.get("edge_type") in {EDGE_CLAIM_SUPERSEDES_CLAIM, EDGE_CLAIM_CORRECTS_CLAIM}:
                invalidated.add(str(target))
        return invalidated

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
        claim_roles: List[Tuple[str, str]] = [(claim_id, "supports active state facet") for claim_id in active_claim_ids]
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

    def _ordered_unique(self, items: Iterable[str]) -> List[str]:
        seen: Set[str] = set()
        unique: List[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique

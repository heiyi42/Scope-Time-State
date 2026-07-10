from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import string
import sys
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


BASELINE_DIR = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = BASELINE_DIR.parent
PROJECT_DIR = BENCHMARK_DIR.parents[2]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex  # noqa: E402
from pipeline.external.time_role_selection import select_time_roles  # noqa: E402
from common.loader import (  # noqa: E402
    DATA_PATH,
    LoCoMoQAItem,
    dialog_id_to_session_id,
    dialog_sort_key,
    load_sample_qa,
    normalize_dialog_ids,
    ordered_unique,
)
from pipeline.external.paths import EXTERNAL_CACHE_DIR, EXTERNAL_GRAPH_DIR, EXTERNAL_RESULT_DIR  # noqa: E402


SUPPORTED_VARIANTS = (
    "graph_bm25",
    "graph_embedding_event",
    "graph_embedding_scope_event",
    "graph_embedding_scope_event_state",
)
GRAPH_EXPANSIONS = ("auto", "legacy", "relation-aware")
TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")
EMBEDDING_RETRIEVAL_SCORE_WEIGHT = 8.0


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    model: str
    api_key: str
    api_base: str
    cache_path: Path
    use_cache: bool


@dataclass(frozen=True)
class RetrievalResult:
    candidate_dialog_ids: List[str]
    state_lines: List[str]
    relation_lines: List[str]
    context: str
    trace: Dict[str, Any]


class BM25Index:
    def __init__(self, doc_ids: Sequence[str], documents: Sequence[str]) -> None:
        self.doc_ids = list(doc_ids)
        self.documents = list(documents)
        self.doc_terms = [Counter(tokenized(doc)) for doc in self.documents]
        self.doc_count = len(self.doc_terms)
        self.avg_len = sum(sum(counter.values()) for counter in self.doc_terms) / max(self.doc_count, 1)
        self.df: Counter[str] = Counter()
        for counter in self.doc_terms:
            self.df.update(counter.keys())

    def search(self, query: str, top_k: int, allowed_doc_ids: Optional[Iterable[str]] = None) -> List[Tuple[str, float]]:
        if top_k <= 0:
            return []
        allowed = None if allowed_doc_ids is None else {str(item) for item in allowed_doc_ids}
        query_terms = Counter(tokenized(query))
        if not query_terms:
            return []
        scores: List[Tuple[str, float, int]] = []
        k1 = 1.5
        b = 0.75
        for index, counter in enumerate(self.doc_terms):
            doc_id = self.doc_ids[index]
            if allowed is not None and doc_id not in allowed:
                continue
            doc_len = sum(counter.values())
            score = 0.0
            for term, query_count in query_terms.items():
                freq = counter.get(term, 0)
                if freq == 0:
                    continue
                idf = math.log(1.0 + (self.doc_count - self.df[term] + 0.5) / (self.df[term] + 0.5))
                denom = freq + k1 * (1.0 - b + b * doc_len / max(self.avg_len, 1.0))
                score += query_count * idf * (freq * (k1 + 1.0) / denom)
            if score > 0:
                scores.append((doc_id, score, index))
        scores.sort(key=lambda item: (-item[1], item[2]))
        return [(doc_id, score) for doc_id, score, _index in scores[:top_k]]


def hybrid_union_rows(
    bm25_hits: Sequence[Tuple[str, float]],
    embedding_hits: Sequence[Any],
) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for rank, (doc_id, score) in enumerate(bm25_hits, start=1):
        rows[str(doc_id)] = {
            "doc_id": str(doc_id),
            "lexical_score": float(score),
            "lexical_rank": rank,
            "embedding_score": 0.0,
            "embedding_rank": None,
        }
    for rank, hit in enumerate(embedding_hits, start=1):
        doc_id = str(hit.doc_id)
        row = rows.setdefault(
            doc_id,
            {
                "doc_id": doc_id,
                "lexical_score": 0.0,
                "lexical_rank": None,
                "embedding_score": 0.0,
                "embedding_rank": None,
            },
        )
        row["embedding_score"] = max(float(hit.score), 0.0)
        row["embedding_rank"] = rank
    for row in rows.values():
        row["score"] = round(
            float(row["lexical_score"])
            + EMBEDDING_RETRIEVAL_SCORE_WEIGHT * float(row["embedding_score"]),
            6,
        )
        if row["lexical_rank"] is not None and row["embedding_rank"] is not None:
            row["retrieval_source"] = "hybrid"
        elif row["embedding_rank"] is not None:
            row["retrieval_source"] = "embedding"
        else:
            row["retrieval_source"] = "bm25"
    return sorted(
        rows.values(),
        key=lambda row: (
            -float(row["score"]),
            row["lexical_rank"] if row["lexical_rank"] is not None else 10**9,
            row["embedding_rank"] if row["embedding_rank"] is not None else 10**9,
            str(row["doc_id"]),
        ),
    )


class GraphEvidenceIndex:
    def __init__(self, graph_dir: Path) -> None:
        self.graph_dir = graph_dir
        self.manifest: Dict[str, Any] = {}
        self.schema_version = ""
        self.events: Dict[str, Dict[str, Any]] = {}
        self.claims: Dict[str, Dict[str, Any]] = {}
        self.states: Dict[str, Dict[str, Any]] = {}
        self.scopes: Dict[str, Dict[str, Any]] = {}
        self.time_nodes: Dict[str, Dict[str, Any]] = {}
        self.claims_by_event: DefaultDict[str, List[str]] = defaultdict(list)
        self.states_by_claim: DefaultDict[str, List[str]] = defaultdict(list)
        self.scopes_by_event: DefaultDict[str, List[str]] = defaultdict(list)
        self.events_by_scope: DefaultDict[str, List[str]] = defaultdict(list)
        self.scopes_by_state: DefaultDict[str, List[str]] = defaultdict(list)
        self.states_by_scope: DefaultDict[str, List[str]] = defaultdict(list)
        self.relations_by_claim: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.times_by_claim: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.current_time_by_state: Dict[str, str] = {}
        self.occurred_time_by_event: Dict[str, str] = {}
        self.occurred_time_id_by_event: Dict[str, str] = {}
        self._load()
        (
            self.event_doc_ids,
            self.event_documents,
            self.state_doc_ids,
            self.state_documents,
            self.scope_doc_ids,
            self.scope_documents,
        ) = self._build_documents()
        self.doc_ids = self.event_doc_ids + self.state_doc_ids + self.scope_doc_ids
        self.documents = self.event_documents + self.state_documents + self.scope_documents
        self.event_bm25 = BM25Index(self.event_doc_ids, self.event_documents)
        self.state_bm25 = BM25Index(self.state_doc_ids, self.state_documents)
        self.scope_bm25 = BM25Index(self.scope_doc_ids, self.scope_documents)

    @classmethod
    def load(cls, graph_dir: Path) -> "GraphEvidenceIndex":
        return cls(graph_dir)

    def _load(self) -> None:
        manifest_path = self.graph_dir / "manifest.json"
        nodes_path = self.graph_dir / "nodes.jsonl"
        edges_path = self.graph_dir / "edges.jsonl"
        if not nodes_path.exists() or not edges_path.exists():
            raise FileNotFoundError(f"missing graph artifact files under {self.graph_dir}")
        if manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text())
            self.schema_version = str(self.manifest.get("schema_version") or "")
        for line in nodes_path.read_text().splitlines():
            if not line.strip():
                continue
            node = json.loads(line)
            node_type = str(node.get("node_type") or "")
            if node_type == "Episode/Event":
                self.events[str(node.get("event_id"))] = node
            elif node_type == "Claim":
                self.claims[str(node.get("claim_id"))] = node
            elif node_type == "StateFacet":
                self.states[str(node.get("facet_id"))] = node
            elif node_type == "Entity/Scope":
                self.scopes[str(node.get("scope_id") or node.get("entity_id"))] = node
            elif node_type == "Time":
                self.time_nodes[str(node.get("time_id"))] = node
        for line in edges_path.read_text().splitlines():
            if not line.strip():
                continue
            edge = json.loads(line)
            edge_type = str(edge.get("type") or "")
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            if edge_type == "ASSERTS":
                self.claims_by_event[source].append(target)
            elif edge_type == "SUPPORTS":
                self.states_by_claim[source].append(target)
            elif edge_type == "IN_SCOPE" and source in self.events and target in self.scopes:
                self.scopes_by_event[source].append(target)
                self.events_by_scope[target].append(source)
            elif edge_type == "CURRENT_STATE_OF" and source in self.states and target in self.scopes:
                self.scopes_by_state[source].append(target)
                self.states_by_scope[target].append(source)
            elif edge_type == "HAS_TIME" and source in self.claims and target in self.time_nodes:
                time_node = self.time_nodes[target]
                self.times_by_claim[source].append(
                    {
                        "time_role": edge.get("time_role") or time_node.get("time_role"),
                        "value": time_node.get("value"),
                        "time_id": target,
                    }
                )
            elif edge_type == "CURRENT_AFTER" and source in self.states and target in self.time_nodes:
                self.current_time_by_state[source] = str(self.time_nodes[target].get("value") or "")
            elif edge_type == "OCCURRED_AT" and source in self.events and target in self.time_nodes:
                self.occurred_time_by_event[source] = str(self.time_nodes[target].get("value") or "")
                self.occurred_time_id_by_event[source] = target
            elif edge_type in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}:
                self.relations_by_claim[source].append(edge)
                self.relations_by_claim[target].append(edge)

    def _build_documents(self) -> Tuple[List[str], List[str], List[str], List[str], List[str], List[str]]:
        event_doc_ids: List[str] = []
        event_documents: List[str] = []
        for event_id, event in sorted(self.events.items(), key=lambda item: dialog_sort_key(item[0])):
            doc_id = f"event::{event_id}"
            event_doc_ids.append(doc_id)
            event_documents.append(event_document(event))
        state_doc_ids: List[str] = []
        state_documents: List[str] = []
        for state_id, state in sorted(self.states.items()):
            doc_id = f"state::{state_id}"
            state_doc_ids.append(doc_id)
            state_documents.append(state_document(state))
        scope_doc_ids: List[str] = []
        scope_documents: List[str] = []
        for scope_id, scope in sorted(self.scopes.items()):
            doc_id = f"scope::{scope_id}"
            scope_doc_ids.append(doc_id)
            scope_documents.append(scope_document(scope))
        return event_doc_ids, event_documents, state_doc_ids, state_documents, scope_doc_ids, scope_documents

    def _state_time_roles(self, state_id: str) -> List[str]:
        state = self.states.get(state_id, {})
        roles: List[str] = []
        if state.get("current_after") or self.current_time_by_state.get(state_id):
            roles.append("CURRENT_AFTER")
        state_role = str(state.get("time_role") or "")
        if state_role:
            roles.append(state_role)
        for claim_id in state.get("support_claim_ids", []) or []:
            claim = self.claims.get(str(claim_id), {})
            claim_role = str(claim.get("time_role") or "")
            if claim_role:
                roles.append(claim_role)
            for time_item in self.times_by_claim.get(str(claim_id), []):
                time_role = str(time_item.get("time_role") or "")
                if time_role:
                    roles.append(time_role)
        return ordered_unique(roles)

    def _event_time_profile(self, event_id: str) -> Dict[str, Any]:
        event = self.events.get(event_id, {})
        roles: List[str] = []
        time_values: List[str] = []
        time_ids: List[str] = []
        current_state_ids: List[str] = []
        occurred_at = self.occurred_time_by_event.get(event_id) or event.get("occurred_at")
        if occurred_at:
            roles.append("occurred_at")
            time_values.append(str(occurred_at))
        occurred_time_id = self.occurred_time_id_by_event.get(event_id)
        if occurred_time_id:
            time_ids.append(occurred_time_id)
        for claim_id in self.claims_by_event.get(event_id, []):
            claim = self.claims.get(claim_id, {})
            claim_role = str(claim.get("time_role") or "")
            if claim_role:
                roles.append(claim_role)
            claim_time_value = claim.get("time_value")
            if claim_time_value:
                time_values.append(str(claim_time_value))
            for time_item in self.times_by_claim.get(claim_id, []):
                time_role = str(time_item.get("time_role") or "")
                if time_role:
                    roles.append(time_role)
                if time_item.get("value"):
                    time_values.append(str(time_item["value"]))
                if time_item.get("time_id"):
                    time_ids.append(str(time_item["time_id"]))
            for state_id in self.states_by_claim.get(claim_id, []):
                state = self.states.get(state_id, {})
                if state.get("current_after") or self.current_time_by_state.get(state_id):
                    roles.append("CURRENT_AFTER")
                    current_state_ids.append(state_id)
        return {
            "time_roles": ordered_unique(roles),
            "time_values": ordered_unique(time_values),
            "time_ids": ordered_unique(time_ids),
            "current_state_ids": ordered_unique(current_state_ids),
        }

    def _rerank_event_rows(
        self,
        event_rows: Sequence[Mapping[str, Any]],
        time_roles: Sequence[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        requested_roles = {str(role) for role in time_roles if role}
        ranked: List[Dict[str, Any]] = []
        for candidate in event_rows:
            doc_id = str(candidate.get("doc_id") or "")
            if not doc_id.startswith("event::"):
                continue
            event_id = doc_id[len("event::") :]
            profile = self._event_time_profile(event_id)
            matched_roles = sorted(requested_roles.intersection(profile["time_roles"]))
            time_role_score = 0.0
            if requested_roles:
                time_role_score = 2.0 + 0.5 * len(matched_roles) if matched_roles else -0.5
            row = dict(candidate)
            row.update(
                {
                    "event_id": event_id,
                    "base_retrieval_score": round(float(candidate.get("score") or 0.0), 6),
                    "selected_time_roles": sorted(requested_roles),
                    "event_time_roles": profile["time_roles"],
                    "matched_time_roles": matched_roles,
                    "time_role_score": round(time_role_score, 4),
                    "time_values": profile["time_values"],
                    "time_ids": profile["time_ids"],
                    "current_state_ids": profile["current_state_ids"],
                    "score": round(float(candidate.get("score") or 0.0) + time_role_score, 6),
                }
            )
            ranked.append(row)
        ranked.sort(
            key=lambda row: (
                -float(row["score"]),
                row["lexical_rank"] if row.get("lexical_rank") is not None else 10**9,
                row["embedding_rank"] if row.get("embedding_rank") is not None else 10**9,
                str(row["event_id"]),
            )
        )
        return ranked[:limit]

    def _state_validity_score(self, state_id: str) -> Tuple[float, Dict[str, int]]:
        state = self.states.get(state_id, {})
        profile = {"outgoing": 0, "incoming": 0, "conflicts": 0}
        score = 1.5 if state.get("current_after") or self.current_time_by_state.get(state_id) else 0.0
        support_claim_ids = {str(claim_id) for claim_id in state.get("support_claim_ids", []) or []}
        for claim_id in support_claim_ids:
            for edge in self.relations_by_claim.get(claim_id, []):
                edge_type = str(edge.get("type") or "")
                source = str(edge.get("from") or "")
                target = str(edge.get("to") or "")
                if edge_type == "CONFLICTS_WITH":
                    profile["conflicts"] += 1
                    score -= 1.0
                elif source == claim_id:
                    profile["outgoing"] += 1
                    score += 1.5
                elif target == claim_id:
                    profile["incoming"] += 1
                    score -= 2.0
        return score, profile

    def _rerank_state_hits(
        self,
        state_hits: Sequence[Tuple[str, float]],
        time_roles: Sequence[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        requested_roles = {str(role) for role in time_roles if role}
        ranked: List[Dict[str, Any]] = []
        for candidate_rank, (doc_id, base_score) in enumerate(state_hits, start=1):
            if not doc_id.startswith("state::"):
                continue
            state_id = doc_id[len("state::") :]
            if state_id not in self.states:
                continue
            state_roles = self._state_time_roles(state_id)
            validity_score, relation_profile = self._state_validity_score(state_id)
            matched_roles = requested_roles.intersection(state_roles)
            if matched_roles:
                time_role_score = 2.0 + 0.5 * len(matched_roles)
            elif "CURRENT_AFTER" in requested_roles and "CURRENT_AFTER" in state_roles:
                time_role_score = 1.5
            else:
                time_role_score = -0.5 if requested_roles else 0.0
            ranked.append(
                {
                    "doc_id": doc_id,
                    "state_facet_id": state_id,
                    "candidate_rank": candidate_rank,
                    "base_score": round(float(base_score), 6),
                    "validity_score": round(validity_score, 4),
                    "time_role_score": round(time_role_score, 4),
                    "time_roles": state_roles,
                    "current_after": self.states[state_id].get("current_after") or self.current_time_by_state.get(state_id),
                    "relation_profile": relation_profile,
                    "score": round(float(base_score) + validity_score + time_role_score, 6),
                }
            )
        ranked.sort(key=lambda row: (-float(row["score"]), int(row["candidate_rank"]), str(row["state_facet_id"])))
        return ranked[:limit]

    def retrieve(
        self,
        question: str,
        *,
        variant: str,
        top_k: int,
        candidate_k: int,
        scope_top_k: int,
        state_search_k: int,
        max_context_events: int,
        max_state_lines: int,
        embedding_indices: Mapping[str, OpenAIEmbeddingIndex],
        embedding_candidate_k: int,
        scope_types: Sequence[str],
        time_role_client: Any,
        time_role_selector: str,
        graph_expansion: str = "auto",
    ) -> RetrievalResult:
        targets = embedding_targets_for_variant(variant)
        scope_allowed_doc_ids = [
            f"scope::{scope_id}"
            for scope_id, scope in self.scopes.items()
            if not scope_types or str(scope.get("scope_type") or "") in set(scope_types)
        ]
        scope_bm25_hits = self.scope_bm25.search(question, candidate_k, allowed_doc_ids=scope_allowed_doc_ids)
        scope_embedding_hits: Sequence[Any] = []
        if "scope" in targets:
            scope_index = embedding_indices.get("scope")
            if scope_index is None:
                raise ValueError(f"{variant} requires a scope embedding index")
            scope_embedding_hits = scope_index.search(
                question,
                embedding_candidate_k,
                allowed_doc_ids=scope_allowed_doc_ids,
            )
        scope_candidate_rows = hybrid_union_rows(scope_bm25_hits, scope_embedding_hits)
        selected_scope_rows = scope_candidate_rows[:scope_top_k]
        selected_scope_hits = [(str(row["doc_id"]), float(row["score"])) for row in selected_scope_rows]
        routed_scope_ids = [doc_id[len("scope::") :] for doc_id, _score in selected_scope_hits if doc_id.startswith("scope::")]

        allowed_event_doc_ids = self._event_doc_ids_for_scopes(routed_scope_ids)
        event_bm25_hits = self.event_bm25.search(question, candidate_k, allowed_doc_ids=allowed_event_doc_ids)
        event_embedding_hits: Sequence[Any] = []
        if "event" in targets:
            event_index = embedding_indices.get("event")
            if event_index is None:
                raise ValueError(f"{variant} requires an event embedding index")
            event_embedding_hits = event_index.search(
                question,
                embedding_candidate_k,
                allowed_doc_ids=allowed_event_doc_ids,
            )
        event_candidate_rows = hybrid_union_rows(event_bm25_hits, event_embedding_hits)
        time_role_selection = select_time_roles(question, time_role_client, time_role_selector)
        selected_event_rows = self._rerank_event_rows(
            event_candidate_rows,
            time_role_selection["time_roles"],
            top_k,
        )
        selected_event_hits = [(str(row["doc_id"]), float(row["score"])) for row in selected_event_rows]
        seed_event_ids: List[str] = []
        for doc_id, _score in selected_event_hits:
            if not doc_id.startswith("event::"):
                continue
            event_id = doc_id[len("event::") :]
            seed_event_ids.append(event_id)

        allowed_state_doc_ids = self._state_doc_ids_for_scopes(routed_scope_ids)
        state_bm25_hits = self.state_bm25.search(question, max(candidate_k, state_search_k), allowed_doc_ids=allowed_state_doc_ids)
        state_rerank_k = min(max(state_search_k * 4, state_search_k), max(candidate_k, state_search_k))
        state_embedding_hits: Sequence[Any] = []
        if "state" in targets:
            state_index = embedding_indices.get("state")
            if state_index is None:
                raise ValueError(f"{variant} requires a state embedding index")
            state_embedding_hits = state_index.search(
                question,
                embedding_candidate_k,
                allowed_doc_ids=allowed_state_doc_ids,
            )
        state_candidate_rows = hybrid_union_rows(state_bm25_hits, state_embedding_hits)[:state_rerank_k]
        state_candidate_hits = [
            (str(row["doc_id"]), float(row["score"]))
            for row in state_candidate_rows
        ]

        selected_state_rows = self._rerank_state_hits(
            state_candidate_hits,
            time_role_selection["time_roles"],
            state_search_k,
        )
        selected_state_hits = [
            (str(row["doc_id"]), float(row["score"]))
            for row in selected_state_rows
        ]

        selected_state_ids = [
            doc_id[len("state::") :]
            for doc_id, _score in selected_state_hits
            if doc_id.startswith("state::")
        ]
        resolved_expansion = self.resolve_graph_expansion(graph_expansion)
        expansion_trace: Dict[str, Any]
        if resolved_expansion == "relation-aware":
            event_ids, state_ids, relation_lines, expansion_trace = self._expand_relation_aware(
                seed_event_ids,
                selected_state_ids,
                max_context_events=max_context_events,
                max_state_lines=max_state_lines,
            )
        else:
            event_ids = list(seed_event_ids)
            state_ids: List[str] = []
            for event_id in seed_event_ids:
                for claim_id in self.claims_by_event.get(event_id, []):
                    state_ids.extend(self.states_by_claim.get(claim_id, []))
            for state_id in selected_state_ids:
                state_ids.append(state_id)
                state = self.states.get(state_id, {})
                event_ids.extend(str(item) for item in state.get("support_event_ids", []) or [])
            event_ids = ordered_unique(event_ids)
            if max_context_events > 0:
                event_ids = event_ids[:max_context_events]
            state_ids = ordered_unique(state_ids)
            if max_state_lines > 0:
                state_ids = state_ids[:max_state_lines]
            relation_lines = self._relation_lines_for_states(state_ids)
            expansion_trace = {
                "mode": "legacy",
                "seed_event_ids": seed_event_ids,
                "selected_state_ids": state_ids,
                "expanded_event_ids": event_ids,
            }
        state_lines = [format_state_line(self.states[state_id]) for state_id in state_ids if state_id in self.states]
        context = self._context_text(event_ids)
        trace = {
            "graph_schema_version": self.schema_version,
            "pipeline_order": [
                "scope_routing",
                "event_candidate_retrieval",
                "time_role_selection",
                "event_time_rerank",
                "statefacet_validity_selection",
                "graph_expansion",
            ],
            "graph_expansion": expansion_trace,
            "embedding_targets": sorted(targets),
            "scope_routing": {
                "bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in scope_bm25_hits[: min(candidate_k, 20)]],
                "embedding_hits": [{"doc_id": hit.doc_id, "score": hit.score} for hit in scope_embedding_hits[:20]],
                "union_hits": scope_candidate_rows[:20],
                "selected_scope_hits": selected_scope_rows,
                "scope_ids": routed_scope_ids,
            },
            "event_retrieval": {
                "bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in event_bm25_hits[: min(candidate_k, 30)]],
                "embedding_hits": [{"doc_id": hit.doc_id, "score": hit.score} for hit in event_embedding_hits[:30]],
                "pre_time_role_union_hits": event_candidate_rows[:30],
                "selected_event_hits": selected_event_rows,
            },
            "time_role_selection": time_role_selection,
            "state_search": {
                "requested_time_roles": list(time_role_selection["time_roles"]),
                "bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in state_bm25_hits[: min(candidate_k, 30)]],
                "embedding_hits": [{"doc_id": hit.doc_id, "score": hit.score} for hit in state_embedding_hits[:30]],
                "pre_time_role_hits": state_candidate_rows,
                "selected_state_hits": selected_state_rows,
            },
            "selected_state_ids": state_ids,
        }
        return RetrievalResult(
            candidate_dialog_ids=event_ids,
            state_lines=state_lines,
            relation_lines=relation_lines,
            context=context,
            trace=trace,
        )

    def resolve_graph_expansion(self, requested: str) -> str:
        if requested not in GRAPH_EXPANSIONS:
            raise ValueError(f"unsupported graph_expansion={requested}")
        if requested != "auto":
            return requested
        if self.schema_version.startswith("locomo-qa-sample-sts-graph-v2"):
            return "relation-aware"
        return "legacy"

    def _expand_relation_aware(
        self,
        seed_event_ids: Sequence[str],
        selected_state_ids: Sequence[str],
        *,
        max_context_events: int,
        max_state_lines: int,
    ) -> Tuple[List[str], List[str], List[str], Dict[str, Any]]:
        event_ids: List[str] = []
        state_ids: List[str] = []
        event_reasons: DefaultDict[str, List[str]] = defaultdict(list)
        claim_queue: deque[Tuple[str, str]] = deque()
        queued_claims: set[str] = set()
        visited_claims: List[str] = []
        visited_relation_edges: set[Tuple[str, str, str]] = set()
        relation_lines: List[str] = []

        def add_event(event_id: object, reason: str) -> None:
            identifier = str(event_id or "")
            if identifier not in self.events:
                return
            if identifier not in event_ids:
                event_ids.append(identifier)
            if reason not in event_reasons[identifier]:
                event_reasons[identifier].append(reason)

        def enqueue_claim(claim_id: object, reason: str) -> None:
            identifier = str(claim_id or "")
            if identifier not in self.claims or identifier in queued_claims:
                return
            queued_claims.add(identifier)
            claim_queue.append((identifier, reason))

        def add_state(state_id: object, reason: str) -> None:
            identifier = str(state_id or "")
            state = self.states.get(identifier)
            if not state:
                return
            if identifier not in state_ids:
                state_ids.append(identifier)
            for event_id in state.get("support_event_ids", []) or []:
                add_event(event_id, f"{reason}; StateFacet support_event")
            for claim_id in state.get("support_claim_ids", []) or []:
                enqueue_claim(claim_id, f"{reason}; StateFacet support_claim")

        for rank, event_id in enumerate(seed_event_ids, start=1):
            add_event(event_id, f"seed_event_rank={rank}")
            for claim_id in self.claims_by_event.get(str(event_id), []):
                enqueue_claim(claim_id, f"seed_event_rank={rank}; ASSERTS")
        for rank, state_id in enumerate(selected_state_ids, start=1):
            add_state(state_id, f"state_search_rank={rank}")

        while claim_queue:
            claim_id, reason = claim_queue.popleft()
            visited_claims.append(claim_id)
            claim = self.claims[claim_id]
            add_event(claim.get("source_event_id"), f"{reason}; claim source_event")
            for state_id in self.states_by_claim.get(claim_id, []):
                add_state(state_id, f"{reason}; SUPPORTS")
            for edge in self.relations_by_claim.get(claim_id, []):
                edge_key = (
                    str(edge.get("type") or ""),
                    str(edge.get("from") or ""),
                    str(edge.get("to") or ""),
                )
                if edge_key in visited_relation_edges:
                    continue
                visited_relation_edges.add(edge_key)
                relation_lines.append(self._format_relation_edge(edge))
                source = str(edge.get("from") or "")
                target = str(edge.get("to") or "")
                related_claim_id = target if source == claim_id else source
                enqueue_claim(related_claim_id, f"{reason}; {edge.get('type')} related_claim")
                for event_id in edge.get("evidence_event_ids", []) or []:
                    add_event(event_id, f"{reason}; {edge.get('type')} evidence_event")

        if max_context_events > 0:
            event_ids = event_ids[:max_context_events]
        if max_state_lines > 0:
            state_ids = state_ids[:max_state_lines]
        return (
            event_ids,
            state_ids,
            relation_lines[:12],
            {
                "mode": "relation-aware",
                "seed_event_ids": list(seed_event_ids),
                "seed_state_ids": list(selected_state_ids),
                "expanded_event_ids": event_ids,
                "selected_state_ids": state_ids,
                "visited_claim_ids": visited_claims,
                "relation_edge_count": len(visited_relation_edges),
                "event_reasons": {event_id: event_reasons[event_id] for event_id in event_ids},
            },
        )

    def _event_doc_ids_for_scopes(self, scope_ids: Sequence[str]) -> Optional[List[str]]:
        event_ids: List[str] = []
        for scope_id in scope_ids:
            event_ids.extend(self.events_by_scope.get(scope_id, []))
        unique = ordered_unique(event_ids)
        if not unique:
            return None
        return [f"event::{event_id}" for event_id in unique]

    def _state_doc_ids_for_scopes(self, scope_ids: Sequence[str]) -> Optional[List[str]]:
        state_ids: List[str] = []
        for scope_id in scope_ids:
            state_ids.extend(self.states_by_scope.get(scope_id, []))
        unique = ordered_unique(state_ids)
        if not unique:
            return None
        return [f"state::{state_id}" for state_id in unique]

    def _relation_lines_for_states(self, state_ids: Sequence[str]) -> List[str]:
        lines: List[str] = []
        seen = set()
        for state_id in state_ids:
            state = self.states.get(state_id, {})
            for claim_id in state.get("support_claim_ids", []) or []:
                for edge in self.relations_by_claim.get(str(claim_id), []):
                    key = (edge.get("type"), edge.get("from"), edge.get("to"))
                    if key in seen:
                        continue
                    seen.add(key)
                    lines.append(self._format_relation_edge(edge))
        return lines[:8]

    def _format_relation_edge(self, edge: Mapping[str, Any]) -> str:
        source = self.claims.get(str(edge.get("from") or ""), {})
        target = self.claims.get(str(edge.get("to") or ""), {})
        return (
            f"{edge.get('type')}: {claim_summary(source)} -> {claim_summary(target)} "
            f"reason={edge.get('reason', '')}"
        )

    def _context_text(self, event_ids: Sequence[str]) -> str:
        chunks: List[str] = []
        for rank, event_id in enumerate(event_ids, start=1):
            event = self.events.get(event_id)
            if not event:
                continue
            chunks.append(
                "\n".join(
                    [
                        f'<dialog rank="{rank}" id="{event_id}" session_id="{event.get("session_id", "")}" date="{event.get("occurred_at", "")}" speaker="{event.get("speaker", "")}">',
                        str(event.get("text") or ""),
                        f'Image caption: {event.get("image_caption", "")}' if event.get("image_caption") else "",
                        f'Image search query: {event.get("image_query", "")}' if event.get("image_query") else "",
                        "</dialog>",
                    ]
                ).replace("\n\n", "\n")
            )
        return "\n\n".join(chunks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LoCoMo questions against a sample-level STS graph.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument(
        "--graph-dir",
        default=str(EXTERNAL_GRAPH_DIR / "locomo_qa_sample_graph_time_role_relation_v2" / "conv-26"),
    )
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--variants", nargs="+", default=list(SUPPORTED_VARIANTS), choices=SUPPORTED_VARIANTS)
    parser.add_argument(
        "--question-types",
        nargs="+",
        default=[],
        help="Optional task filter, e.g. multi-hop open-domain.",
    )
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--scope-top-k", type=int, default=8)
    parser.add_argument("--scope-types", default="speaker,entity,topic,session")
    parser.add_argument(
        "--state-search-k",
        type=int,
        default=12,
        help="StateFacet candidates before graph expansion; use 16 with max-state-lines=16 for a 16-facet run.",
    )
    parser.add_argument("--candidate-k", type=int, default=80)
    parser.add_argument("--embedding-candidate-k", type=int, default=80)
    parser.add_argument("--max-context-events", type=int, default=24)
    parser.add_argument("--max-state-lines", type=int, default=16)
    parser.add_argument(
        "--time-role-selector",
        choices=("llm", "none"),
        default="llm",
        help="Question-only Time routing after Event candidates for Event and State reranking.",
    )
    parser.add_argument(
        "--graph-expansion",
        choices=GRAPH_EXPANSIONS,
        default="auto",
        help="auto keeps v1 on legacy expansion and enables relation-aware expansion for v2 graphs.",
    )
    parser.add_argument("--answer-workers", type=int, default=4)
    parser.add_argument(
        "--disable-open-domain-mapping",
        action="store_true",
        help="Disable the open-domain post-answer mapping layer.",
    )
    parser.add_argument("--cache", default=str(EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_graph_query.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--embedding-cache", default=str(EXTERNAL_CACHE_DIR / "embedding_cache.locomo_qa_graph_query.json"))
    parser.add_argument("--embedding-base-url", default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", ""))
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument(
        "--output",
        default=str(EXTERNAL_RESULT_DIR / "locomo_qa" / "ours_scope_time_state" / "results_locomo_qa_graph_conv26.json"),
    )
    return parser.parse_args()


def tokenized(text: object) -> List[str]:
    return [canonical_term(term) for term in TOKEN_RE.findall(str(text or "").lower())]


def canonical_term(term: str) -> str:
    if term.endswith("ies") and len(term) > 4:
        return term[:-3] + "y"
    if term.endswith("ing") and len(term) > 5:
        return term[:-3]
    if term.endswith("ed") and len(term) > 4:
        return term[:-2]
    if term.endswith("s") and len(term) > 4:
        return term[:-1]
    return term


def event_document(event: Mapping[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            event.get("dialog_id"),
            event.get("session_id"),
            event.get("occurred_at"),
            event.get("speaker"),
            event.get("text"),
            event.get("image_caption"),
            event.get("image_query"),
        )
    )


def state_document(state: Mapping[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            state.get("subject"),
            state.get("facet_key"),
            state.get("value"),
            state.get("time_role"),
            state.get("time_value"),
            state.get("time_anchor"),
            state.get("current_after"),
            state.get("graph_text"),
        )
    )


def scope_document(scope: Mapping[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            scope.get("scope_type"),
            scope.get("label"),
            scope.get("value"),
        )
    )


def parse_scope_types(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def normalize_question_type(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "multi": "multi-hop",
        "multi-hop-qa": "multi-hop",
        "open": "open-domain",
        "open-domain-knowledge": "open-domain",
        "commonsense": "open-domain",
        "common-sense": "open-domain",
        "single": "single-hop",
        "single-hop-qa": "single-hop",
        "time": "temporal",
        "temporal-reasoning": "temporal",
        "false-premise": "adversarial",
    }
    return aliases.get(normalized, normalized)


def select_rows(
    rows: Sequence[LoCoMoQAItem],
    question_types: Sequence[str],
    limit_cases: int,
    limit_per_type: int,
) -> List[LoCoMoQAItem]:
    selected = list(rows)
    if question_types:
        allowed = {normalize_question_type(item) for item in question_types}
        selected = [row for row in selected if row.question_type in allowed]
    if limit_per_type:
        counts: Counter[str] = Counter()
        limited: List[LoCoMoQAItem] = []
        for row in selected:
            if counts[row.question_type] >= limit_per_type:
                continue
            limited.append(row)
            counts[row.question_type] += 1
        selected = limited
    if limit_cases:
        selected = selected[:limit_cases]
    return selected


def embedding_targets_for_variant(variant: str) -> set[str]:
    if variant == "graph_bm25":
        return set()
    if variant == "graph_embedding_event":
        return {"event"}
    if variant == "graph_embedding_scope_event":
        return {"scope", "event"}
    if variant == "graph_embedding_scope_event_state":
        return {"scope", "event", "state"}
    raise ValueError(f"unsupported variant={variant}")


def format_state_line(state: Mapping[str, Any]) -> str:
    support = ", ".join(str(item) for item in state.get("support_event_ids", []) or [])
    if state.get("time_role") or state.get("time_value"):
        return (
            f"{state.get('subject', '')} {state.get('facet_key', '')}: {state.get('value', '')} "
            f"(current_after={state.get('current_after', '')}; time_role={state.get('time_role', '')}; "
            f"time_value={state.get('time_value', '')}; support={support})"
        )
    return (
        f"{state.get('subject', '')} {state.get('facet_key', '')}: {state.get('value', '')} "
        f"(time={state.get('current_after', '')}; support={support})"
    )


def claim_summary(claim: Mapping[str, Any]) -> str:
    temporal = ""
    if claim.get("time_role") or claim.get("time_value"):
        temporal = f" [{claim.get('time_role', '')}={claim.get('time_value', '')}]"
    return (
        f"{claim.get('dialog_id', '')} {claim.get('subject', '')} "
        f"{claim.get('facet_key', '')}: {claim.get('value', '')}{temporal}"
    )


def answer_system_prompt() -> str:
    return (
        "You answer LoCoMo QA questions using only the provided graph evidence: state facets, relation notes, "
        "dialog turns, session dates, and text metadata from image captions/search queries. "
        "Return strict JSON with keys answer and evidence_dialog_ids. "
        "Keep the answer as a short gold-style phrase, date, name, or comma-separated list. "
        "For false-premise or unavailable information, answer exactly \"No information available\" or "
        "\"Not mentioned in the conversation\". Cite only dialog IDs present in the evidence."
    )


def answer_user_prompt(
    row: LoCoMoQAItem,
    variant: str,
    retrieval: RetrievalResult,
) -> str:
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: {variant}\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Official category: {row.category}\n"
        f"Question type: {row.question_type}\n"
        f"Question: {row.question}\n\n"
        "Graph state facets:\n"
        f"{chr(10).join('- ' + line for line in retrieval.state_lines) or '[none]'}\n\n"
        "Graph relation notes:\n"
        f"{chr(10).join('- ' + line for line in retrieval.relation_lines) or '[none]'}\n\n"
        f"Candidate dialog turns:\n{retrieval.context or '[none]'}\n\n"
        "Answer rules:\n"
        "- Use state facets first, then raw dialog turns to verify wording and dates.\n"
        "- For temporal questions, compute relative dates from session dates when needed.\n"
        "- For open-domain questions, use ordinary commonsense only as a bridge from cited conversation facts.\n"
        "- For multi-answer questions, return the complete requested set as comma-separated short phrases.\n"
        "- If evidence is missing or contradicts the premise, abstain with the exact unavailable phrase.\n\n"
        "Respond as JSON only:\n"
        "{\"answer\": \"...\", \"evidence_dialog_ids\": [\"D1:1\"]}"
    )


def open_domain_mapping_system_prompt() -> str:
    return (
        "You are a lightweight answer mapping layer for LoCoMo open-domain QA. "
        "You receive only the question and the preliminary answer. Normalize the preliminary answer to better match "
        "the question's requested answer type when possible, but do not add new facts. Return strict JSON only."
    )


def open_domain_mapping_user_prompt(row: LoCoMoQAItem, initial_answer: str) -> str:
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Question type: {row.question_type}\n"
        f"Question: {row.question}\n\n"
        f"Preliminary answer: {initial_answer or '[empty]'}\n\n"
        "Rules:\n"
        "- Use only the question and preliminary answer above.\n"
        "- Do not introduce entities, dates, places, reasons, or facts absent from the preliminary answer.\n"
        "- If the question asks yes/no, map a longer answer to exactly Yes or No only when the preliminary answer clearly says so.\n"
        "- If the preliminary answer already matches the requested type, keep it.\n"
        "- If the preliminary answer is unavailable, empty, or incompatible with the question, keep the unavailable answer.\n\n"
        "Return JSON with this schema:\n"
        "{\"mapped_answer\": \"...\", \"changed\": true, \"rationale\": \"short reason\"}"
    )


def normalize_open_domain_mapping(raw: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "mapped_answer": str(raw.get("mapped_answer") or "").strip(),
        "changed": bool(raw.get("changed")),
        "rationale": str(raw.get("rationale") or "").strip(),
    }


def shard_cache_path(base_cache_path: Path, stage: str, shard_name: str) -> Path:
    shard_dir = base_cache_path.with_suffix("")
    shard_dir = shard_dir.parent / f"{shard_dir.name}_shards" / stage
    shard_dir.mkdir(parents=True, exist_ok=True)
    return shard_dir / f"{safe_part(shard_name)}.json"


def safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "unknown"


def short_hash(value: object) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:10]


def make_sharded_client(runtime: LLMRuntimeConfig, stage: str, shard_name: str) -> LLMClient:
    return LLMClient(
        provider=runtime.provider,
        model=runtime.model,
        api_key=runtime.api_key,
        api_base=runtime.api_base,
        cache_path=shard_cache_path(runtime.cache_path, stage, shard_name),
        use_cache=runtime.use_cache,
    )


def normalize_output_dialog_ids(value: object) -> List[str]:
    ids = normalize_dialog_ids(value)
    expanded: List[str] = []
    for item in ids:
        if "," in item:
            expanded.extend(part.strip() for part in item.split(","))
        else:
            expanded.append(item)
    return ordered_unique(item for item in expanded if re.match(r"D\d+:\d+", item))


def recall(selected: Sequence[str], gold: Sequence[str]) -> Optional[float]:
    gold_set = set(gold)
    if not gold_set:
        return None
    return len(gold_set & set(selected)) / len(gold_set)


def precision(selected: Sequence[str], gold: Sequence[str]) -> Optional[float]:
    selected_set = set(selected)
    if not selected_set:
        return None
    return len(selected_set & set(gold)) / len(selected_set)


def f1_from_precision_recall(precision_value: Optional[float], recall_value: Optional[float]) -> Optional[float]:
    if precision_value is None or recall_value is None:
        return None
    if precision_value + recall_value == 0:
        return 0.0
    return 2 * precision_value * recall_value / (precision_value + recall_value)


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 4)


def normalize_answer(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace(",", "")
    lowered = text.lower()
    lowered = lowered.translate(str.maketrans("", "", string.punctuation))
    lowered = re.sub(r"\b(a|an|the|and)\b", " ", lowered)
    return " ".join(lowered.split())


def stem_tokens(tokens: Sequence[str]) -> List[str]:
    try:
        from nltk.stem import PorterStemmer
    except ImportError:
        return list(tokens)
    stemmer = PorterStemmer()
    return [stemmer.stem(token) for token in tokens]


def official_f1_score(prediction: object, ground_truth: object) -> float:
    prediction_tokens = stem_tokens(normalize_answer(prediction).split())
    ground_truth_tokens = stem_tokens(normalize_answer(ground_truth).split())
    if not prediction_tokens or not ground_truth_tokens:
        return 0.0
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision_value = num_same / len(prediction_tokens)
    recall_value = num_same / len(ground_truth_tokens)
    return (2 * precision_value * recall_value) / (precision_value + recall_value)


def official_bleu1_score(prediction: object, ground_truth: object) -> float:
    prediction_tokens = nltk_bleu_tokens(prediction)
    ground_truth_tokens = nltk_bleu_tokens(ground_truth)
    if not prediction_tokens or not ground_truth_tokens:
        return 0.0
    try:
        from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
    except ImportError:
        return manual_bleu1_score(prediction_tokens, ground_truth_tokens)
    return float(
        sentence_bleu(
            [ground_truth_tokens],
            prediction_tokens,
            weights=(1, 0, 0, 0),
            smoothing_function=SmoothingFunction().method1,
        )
    )


def nltk_bleu_tokens(text: object) -> List[str]:
    lowered = str(text or "").lower()
    try:
        import nltk

        return list(nltk.word_tokenize(lowered))
    except (ImportError, LookupError):
        return re.findall(r"\w+|[^\w\s]", lowered, flags=re.UNICODE)


def manual_bleu1_score(prediction_tokens: Sequence[str], ground_truth_tokens: Sequence[str]) -> float:
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    clipped_matches = sum(common.values())
    if clipped_matches == 0:
        return 0.0
    precision_value = clipped_matches / len(prediction_tokens)
    if len(prediction_tokens) > len(ground_truth_tokens):
        return precision_value
    return math.exp(1.0 - (len(ground_truth_tokens) / len(prediction_tokens))) * precision_value


def official_multi_answer_f1(prediction: object, ground_truth: object) -> float:
    predictions = [item.strip() for item in str(prediction).split(",")]
    ground_truths = [item.strip() for item in str(ground_truth).split(",")]
    if not ground_truths:
        return 0.0
    return sum(max(official_f1_score(pred, gold) for pred in predictions) for gold in ground_truths) / len(ground_truths)


def official_style_answer_score(row: LoCoMoQAItem, hypothesis: str) -> float:
    if row.category == 5:
        lowered = hypothesis.lower()
        return 1.0 if "no information available" in lowered or "not mentioned" in lowered else 0.0
    answer = row.answer or ""
    if row.category == 3:
        answer = answer.split(";")[0].strip()
    if row.category == 1:
        return official_multi_answer_f1(hypothesis, answer)
    if row.category in {2, 3, 4}:
        return official_f1_score(hypothesis, answer)
    raise ValueError(f"unsupported LoCoMo category={row.category}")


def exact_match_score(prediction: object, ground_truth: object) -> bool:
    prediction_tokens = set(normalize_answer(prediction).split())
    ground_truth_tokens = set(normalize_answer(ground_truth).split())
    return bool(prediction_tokens) and prediction_tokens == ground_truth_tokens


def summarize(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    by_type: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_type[str(row["question_type"])].append(row)
    by_question_type = {question_type: summarize_flat(type_rows) for question_type, type_rows in sorted(by_type.items())}
    summary = summarize_flat(rows)
    summary["task_averaged_answer_f1"] = mean(metrics["answer_f1"] for metrics in by_question_type.values())
    summary["task_averaged_bleu1"] = mean(metrics["bleu1"] for metrics in by_question_type.values())
    summary["by_question_type"] = by_question_type
    return summary


def summarize_flat(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    return {
        "n_cases": len(rows),
        "answer_f1": mean(float(row["answer_f1"]) for row in rows),
        "bleu1": mean(None if row.get("bleu1") is None else float(row["bleu1"]) for row in rows),
        "exact_match": mean(1.0 if row["exact_match"] else 0.0 for row in rows if row["category"] != 5),
        "candidate_dialog_recall": mean(row["candidate_dialog_recall"] for row in rows),
        "candidate_dialog_precision": mean(row["candidate_dialog_precision"] for row in rows),
        "evidence_dialog_recall": mean(row["evidence_dialog_recall"] for row in rows),
        "evidence_dialog_precision": mean(row["evidence_dialog_precision"] for row in rows),
        "evidence_dialog_f1": mean(row["evidence_dialog_f1"] for row in rows),
    }


def format_metric(value: object) -> str:
    return f"{value:.3f}" if isinstance(value, float) else "n/a"


def run_variant(
    *,
    variant: str,
    rows: Sequence[LoCoMoQAItem],
    graph: GraphEvidenceIndex,
    answer_runtime: LLMRuntimeConfig,
    args: argparse.Namespace,
    embedding_indices: Mapping[str, OpenAIEmbeddingIndex],
) -> Dict[str, object]:
    eval_rows: List[Dict[str, object]] = []

    def run_row(index: int, row: LoCoMoQAItem) -> Tuple[int, Dict[str, object]]:
        time_role_client = make_sharded_client(
            answer_runtime,
            "time_role_selector",
            short_hash(row.question),
        )
        retrieval = graph.retrieve(
            row.question,
            variant=variant,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            scope_top_k=args.scope_top_k,
            state_search_k=args.state_search_k,
            max_context_events=args.max_context_events,
            max_state_lines=args.max_state_lines,
            embedding_indices=embedding_indices,
            embedding_candidate_k=args.embedding_candidate_k,
            scope_types=parse_scope_types(args.scope_types),
            time_role_client=time_role_client,
            time_role_selector=args.time_role_selector,
            graph_expansion=args.graph_expansion,
        )
        retrieval.trace["retrieval_query"] = row.question
        client = make_sharded_client(answer_runtime, f"answer_{variant}", f"{row.question_id}_{short_hash(row.question)}")
        output = client.complete_json(
            answer_system_prompt(),
            answer_user_prompt(row, variant, retrieval),
        )
        initial_hypothesis = str(output.get("answer", "")).strip()
        hypothesis = initial_hypothesis
        open_domain_mapping: Optional[Dict[str, Any]] = None
        if row.question_type == "open-domain" and not args.disable_open_domain_mapping:
            mapping_client = make_sharded_client(
                answer_runtime,
                f"mapping_{variant}",
                f"{row.question_id}_{short_hash(row.question + initial_hypothesis)}",
            )
            mapping_raw = mapping_client.complete_json(
                open_domain_mapping_system_prompt(),
                open_domain_mapping_user_prompt(row, initial_hypothesis),
            )
            open_domain_mapping = normalize_open_domain_mapping(mapping_raw)
            mapped_answer = str(open_domain_mapping.get("mapped_answer") or "").strip()
            if mapped_answer:
                hypothesis = mapped_answer
        evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
        if not evidence_dialog_ids:
            evidence_dialog_ids = list(retrieval.candidate_dialog_ids)
        evidence_precision = precision(evidence_dialog_ids, row.evidence_dialog_ids)
        evidence_recall = recall(evidence_dialog_ids, row.evidence_dialog_ids)
        result = {
            "question_id": row.question_id,
            "sample_id": row.sample_id,
            "qa_index": row.qa_index,
            "category": row.category,
            "question_type": row.question_type,
            "question": row.question,
            "gold_answer": row.answer,
            "initial_hypothesis": initial_hypothesis,
            "hypothesis": hypothesis,
            "candidate_dialog_ids": list(retrieval.candidate_dialog_ids),
            "evidence_dialog_ids": evidence_dialog_ids,
            "gold_evidence_dialog_ids": list(row.evidence_dialog_ids),
            "candidate_dialog_recall": recall(retrieval.candidate_dialog_ids, row.evidence_dialog_ids),
            "candidate_dialog_precision": precision(retrieval.candidate_dialog_ids, row.evidence_dialog_ids),
            "evidence_dialog_recall": evidence_recall,
            "evidence_dialog_precision": evidence_precision,
            "evidence_dialog_f1": f1_from_precision_recall(evidence_precision, evidence_recall),
            "answer_f1": official_style_answer_score(row, hypothesis),
            "bleu1": None if row.category == 5 else official_bleu1_score(hypothesis, row.answer),
            "exact_match": exact_match_score(hypothesis, row.answer) if row.category != 5 else False,
            "retrieval_trace": retrieval.trace,
            "open_domain_mapping": open_domain_mapping,
        }
        return index, result

    if args.answer_workers <= 1:
        for index, row in enumerate(rows, start=1):
            _index, result = run_row(index, row)
            eval_rows.append(result)
            print(f"[{variant}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    else:
        results: Dict[int, Dict[str, object]] = {}
        with ThreadPoolExecutor(max_workers=max(1, args.answer_workers)) as executor:
            futures = {executor.submit(run_row, index, row): index for index, row in enumerate(rows, start=1)}
            for future in as_completed(futures):
                index, result = future.result()
                results[index] = result
                print(f"[{variant}] {index}/{len(rows)} {result['question_id']} {result['question_type']}", flush=True)
        eval_rows = [results[index] for index in sorted(results)]
    return {"variant": variant, "summary": summarize(eval_rows), "rows": eval_rows}


def print_summary(provider: str, model: str, results: Sequence[Dict[str, object]]) -> None:
    print("LoCoMo QA graph benchmark")
    print(f"answer_provider={provider} answer_model={model}")
    print()
    print(f"{'variant':<35} {'n':>4} {'ans_f1':>8} {'task_f1':>8} {'bleu1':>8} {'task_b1':>8} {'exact':>8} {'cand_r':>8} {'cand_p':>8} {'ev_r':>8} {'ev_p':>8} {'ev_f1':>8}")
    print("-" * 140)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<35} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['answer_f1']):>8} "
            f"{format_metric(summary['task_averaged_answer_f1']):>8} "
            f"{format_metric(summary['bleu1']):>8} "
            f"{format_metric(summary['task_averaged_bleu1']):>8} "
            f"{format_metric(summary['exact_match']):>8} "
            f"{format_metric(summary['candidate_dialog_recall']):>8} "
            f"{format_metric(summary['candidate_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_recall']):>8} "
            f"{format_metric(summary['evidence_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_f1']):>8}"
        )


def main() -> int:
    args = parse_args()
    load_dotenv()
    rows = select_rows(
        load_sample_qa(Path(args.data), args.sample_id),
        args.question_types,
        args.limit_cases,
        args.limit_per_type,
    )
    if not rows:
        print("empty selection; check --question-types/--limit-cases/--limit-per-type", file=sys.stderr)
        return 2
    graph = GraphEvidenceIndex.load(Path(args.graph_dir))
    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.model:
        model = args.model
    answer_runtime = LLMRuntimeConfig(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )
    needed_embedding_targets: set[str] = set()
    for variant in args.variants:
        needed_embedding_targets.update(embedding_targets_for_variant(variant))
    embedding_indices: Dict[str, OpenAIEmbeddingIndex] = {}
    embedding_namespace = f"locomo-qa:{Path(args.graph_dir).resolve()}"
    if "event" in needed_embedding_targets:
        embedding_indices["event"] = OpenAIEmbeddingIndex(
            graph.event_doc_ids,
            graph.event_documents,
            model=args.embedding_model,
            cache_path=Path(args.embedding_cache),
            namespace=f"{embedding_namespace}:events",
            batch_size=args.embedding_batch_size,
            base_url=args.embedding_base_url or None,
        )
    if "scope" in needed_embedding_targets:
        embedding_indices["scope"] = OpenAIEmbeddingIndex(
            graph.scope_doc_ids,
            graph.scope_documents,
            model=args.embedding_model,
            cache_path=Path(args.embedding_cache),
            namespace=f"{embedding_namespace}:scopes",
            batch_size=args.embedding_batch_size,
            base_url=args.embedding_base_url or None,
        )
    if "state" in needed_embedding_targets:
        embedding_indices["state"] = OpenAIEmbeddingIndex(
            graph.state_doc_ids,
            graph.state_documents,
            model=args.embedding_model,
            cache_path=Path(args.embedding_cache),
            namespace=f"{embedding_namespace}:states",
            batch_size=args.embedding_batch_size,
            base_url=args.embedding_base_url or None,
        )
    for target, embedding_index in embedding_indices.items():
        print(f"materializing {target} embedding index ({len(embedding_index.doc_ids)} documents)", flush=True)
        embedding_index.embed_documents()
    try:
        results = [
            run_variant(
                variant=variant,
                rows=rows,
                graph=graph,
                answer_runtime=answer_runtime,
                args=args,
                embedding_indices=embedding_indices,
            )
            for variant in args.variants
        ]
    except LLMRequestError as exc:
        print("\nLLM request failed during LoCoMo graph QA.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = {
        "benchmark": "LoCoMo QA graph",
        "sample_id": args.sample_id,
        "data_path": str(Path(args.data)),
        "graph_dir": str(Path(args.graph_dir)),
        "graph_schema_version": graph.schema_version,
        "graph_expansion": graph.resolve_graph_expansion(args.graph_expansion),
        "provider": args.provider,
        "model": model,
        "variants": list(args.variants),
        "question_types": [normalize_question_type(item) for item in args.question_types],
        "top_k": args.top_k,
        "scope_top_k": args.scope_top_k,
        "scope_types": parse_scope_types(args.scope_types),
        "state_search_k": args.state_search_k,
        "time_role_selector": args.time_role_selector,
        "candidate_k": args.candidate_k,
        "embedding_candidate_k": args.embedding_candidate_k,
        "embedding_model": args.embedding_model if needed_embedding_targets else None,
        "open_domain_mapping": not args.disable_open_domain_mapping,
        "max_context_events": args.max_context_events,
        "max_state_lines": args.max_state_lines,
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    for result in results:
        jsonl_path = output_path.with_name(f"{output_path.stem}.{result['variant']}.hypotheses.jsonl")
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in result["rows"]:
                handle.write(
                    json.dumps(
                        {
                            "question_id": row["question_id"],
                            "sample_id": row["sample_id"],
                            "qa_index": row["qa_index"],
                            "category": row["category"],
                            "question_type": row["question_type"],
                            "initial_hypothesis": row.get("initial_hypothesis"),
                            "hypothesis": row["hypothesis"],
                            "open_domain_mapped_answer": (
                                row["open_domain_mapping"].get("mapped_answer")
                                if isinstance(row.get("open_domain_mapping"), Mapping)
                                else None
                            ),
                            "open_domain_mapping_changed": (
                                row["open_domain_mapping"].get("changed")
                                if isinstance(row.get("open_domain_mapping"), Mapping)
                                else None
                            ),
                            "open_domain_mapping_rationale": (
                                row["open_domain_mapping"].get("rationale")
                                if isinstance(row.get("open_domain_mapping"), Mapping)
                                else None
                            ),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    print_summary(args.provider, model, results)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

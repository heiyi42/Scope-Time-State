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
from pipeline.external.temporal_grounding import (  # noqa: E402
    format_temporal_grounding,
    ground_temporal_expressions,
    parse_anchor_datetime,
)
from pipeline.external.time_role_selection import select_time_roles  # noqa: E402
from common.loader import (  # noqa: E402
    DATA_PATH,
    LoCoMoQAItem,
    dialog_sort_key,
    load_sample_qa,
    ordered_unique,
)
from pipeline.external.paths import EXTERNAL_CACHE_DIR, EXTERNAL_GRAPH_DIR, EXTERNAL_RESULT_DIR  # noqa: E402
from pipeline.external.sts_v2.schema import SCHEMA_VERSION  # noqa: E402


ACTIVE_GRAPH_SCHEMA_V2 = SCHEMA_VERSION
LEGACY_GRAPH_SCHEMA_V2 = "locomo-qa-sample-sts-graph-v2-state-merge"
STATE_MERGE_GRAPH_SCHEMAS = frozenset({ACTIVE_GRAPH_SCHEMA_V2, LEGACY_GRAPH_SCHEMA_V2})
SEMANTIC_SCOPE_TYPES = ("speaker", "entity", "topic")
SUPPORTED_VARIANTS = (
    "graph_bm25",
    "graph_embedding_event",
    "graph_embedding_scope_event",
    "graph_embedding_scope_statefacet",
)
GRAPH_EXPANSIONS = ("auto", "legacy", "relation-aware", "scope-coverage")
RETRIEVAL_POLICIES = ("event-rag", "scope-event", "scope-event-time", "sts")
TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")
EMBEDDING_RETRIEVAL_SCORE_WEIGHT = 8.0
TIME_ROLE_MATCH_BOOST = 0.25
RECENCY_RANK_BOOST = 0.2
RRF_K = 60
RRF_OVERLAP_WEIGHT = 0.25
MAX_RETRIEVAL_QUERIES = 4
QUERY_STOP_TERMS = {
    "a", "an", "and", "are", "at", "be", "did", "do", "does", "for", "from",
    "had", "has", "have", "how", "in", "is", "it", "of", "on", "or", "the",
    "their", "them", "they", "to", "was", "were", "what", "when", "where",
    "which", "who", "why", "with",
}
READOUT_OPERATIONS = {"lookup", "enumerate", "count", "intersection", "compare", "boolean", "inference"}
COUNT_UNITS = {"occurrences", "entities", "stated_number", "none"}
GENERIC_REQUESTED_SLOTS = {"", "answer", "object", "short description", "value"}


def temporal_sort_value(value: object) -> str:
    parsed = parse_anchor_datetime(value)
    return parsed.isoformat() if parsed is not None else ""


def subject_identity(node: Mapping[str, Any]) -> str:
    """Project v2 subject fields onto one stable query identity."""
    explicit = str(node.get("canonical_subject_id") or node.get("subject_key") or "").strip()
    if explicit:
        return explicit.casefold()
    return normalize_entity_reference(node.get("canonical_subject") or node.get("subject"))


def state_dimension_identity(node: Mapping[str, Any]) -> str:
    """Return an explicit state grouping key without inferring one from prose."""
    return str(
        node.get("canonical_state_group_id")
        or node.get("state_dimension")
        or ""
    ).strip().casefold()


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
    temporal_lines: List[str]
    claim_lines: List[str]
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


def rrf_union_rows(
    bm25_hits: Sequence[Tuple[str, float]],
    embedding_hits: Sequence[Any],
    *,
    rrf_k: int = RRF_K,
) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for rank, (doc_id, lexical_score) in enumerate(bm25_hits, start=1):
        rows[str(doc_id)] = {
            "doc_id": str(doc_id),
            "lexical_score": float(lexical_score),
            "lexical_rank": rank,
            "embedding_score": 0.0,
            "embedding_rank": None,
            "lexical_rrf": 1.0 / (rrf_k + rank),
            "embedding_rrf": 0.0,
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
                "lexical_rrf": 0.0,
                "embedding_rrf": 0.0,
            },
        )
        row["embedding_score"] = float(hit.score)
        row["embedding_rank"] = rank
        row["embedding_rrf"] = 1.0 / (rrf_k + rank)
    for row in rows.values():
        primary = max(float(row["lexical_rrf"]), float(row["embedding_rrf"]))
        overlap = min(float(row["lexical_rrf"]), float(row["embedding_rrf"]))
        row["score"] = round(primary + RRF_OVERLAP_WEIGHT * overlap, 8)
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


def merge_scored_hits(*groups: Sequence[Tuple[str, float]]) -> List[Tuple[str, float]]:
    scores: Dict[str, float] = {}
    for group in groups:
        for doc_id, score in group:
            identifier = str(doc_id)
            scores[identifier] = max(scores.get(identifier, float("-inf")), float(score))
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def merge_embedding_hits(*groups: Sequence[Any]) -> List[Any]:
    by_id: Dict[str, Any] = {}
    for group in groups:
        for hit in group:
            identifier = str(hit.doc_id)
            previous = by_id.get(identifier)
            if previous is None or float(hit.score) > float(previous.score):
                by_id[identifier] = hit
    return sorted(by_id.values(), key=lambda hit: (-float(hit.score), str(hit.doc_id)))


def bm25_search_queries(
    index: Any,
    queries: Sequence[str],
    limit: int,
    *,
    allowed_doc_ids: Optional[Sequence[str]] = None,
) -> List[Tuple[str, float]]:
    return merge_scored_hits(
        *(index.search(query, limit, allowed_doc_ids=allowed_doc_ids) for query in queries)
    )


def embedding_search_queries(
    index: Any,
    queries: Sequence[str],
    limit: int,
    *,
    allowed_doc_ids: Optional[Sequence[str]] = None,
) -> List[Any]:
    return merge_embedding_hits(
        *(index.search(query, limit, allowed_doc_ids=allowed_doc_ids) for query in queries)
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
        self.event_state_enrichment = False
        self._load()
        (
            self.event_doc_ids,
            self.event_documents,
            self.scope_doc_ids,
            self.scope_documents,
            self.state_doc_ids,
            self.state_documents,
        ) = self._build_documents()
        self.raw_event_documents = [
            event_document(self.events[doc_id[len("event::") :]])
            for doc_id in self.event_doc_ids
        ]
        self.raw_event_bm25 = BM25Index(self.event_doc_ids, self.raw_event_documents)
        self.event_bm25 = BM25Index(self.event_doc_ids, self.event_documents)
        self.scope_bm25 = BM25Index(self.scope_doc_ids, self.scope_documents)
        self.state_bm25 = BM25Index(self.state_doc_ids, self.state_documents)

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
            if self.schema_version and self.schema_version not in {
                "locomo-qa-sample-sts-graph-v1",
                *STATE_MERGE_GRAPH_SCHEMAS,
            }:
                raise ValueError(
                    "incompatible graph schema; rebuild with the shared STS v2 schema: "
                    f"{self.schema_version}"
                )
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
            elif edge_type == "CURRENT_STATE_OF" and source in self.states and target in self.scopes:
                self.scopes_by_state[source].append(target)
                self.states_by_scope[target].append(source)
            elif edge_type == "OCCURRED_AT" and source in self.events and target in self.time_nodes:
                self.occurred_time_by_event[source] = str(self.time_nodes[target].get("value") or "")
                self.occurred_time_id_by_event[source] = target
            elif edge_type in {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}:
                self.relations_by_claim[source].append(edge)
                self.relations_by_claim[target].append(edge)
        self._validate_state_merge_query_contract()

    def _validate_state_merge_query_contract(self) -> None:
        if self.schema_version not in STATE_MERGE_GRAPH_SCHEMAS:
            return
        errors: List[str] = []
        resolution = self.manifest.get("state_resolution")
        if not isinstance(resolution, Mapping):
            errors.append("manifest.state_resolution_missing")
        else:
            if str(resolution.get("mode") or "") != "ordered_state_fold":
                errors.append("manifest.state_resolution.mode")
            if str(resolution.get("dimension_key") or "") != "state_dimension":
                errors.append("manifest.state_resolution.dimension_key")
        for state_id, state in self.states.items():
            for field in ("subject_key", "state_domain", "slot_type", "state_target", "state_dimension"):
                if not str(state.get(field) or "").strip():
                    errors.append(f"{state_id}.{field}")
            slot_type = str(state.get("slot_type") or "")
            if slot_type not in {"single", "object_scoped"}:
                errors.append(f"{state_id}.slot_type={slot_type}")
            status = str(state.get("status") or "")
            if status not in {"current", "ambiguous", "historical"}:
                errors.append(f"{state_id}.status={status}")
            support_claim_ids = ordered_unique(
                str(claim_id)
                for claim_id in state.get("support_claim_ids", []) or []
                if str(claim_id)
            )
            support_event_ids = ordered_unique(
                str(event_id)
                for event_id in state.get("support_event_ids", []) or []
                if str(event_id)
            )
            primary_claim_id = str(state.get("primary_claim_id") or "")
            if not support_claim_ids:
                errors.append(f"{state_id}.support_claim_ids")
            if primary_claim_id not in support_claim_ids:
                errors.append(f"{state_id}.primary_claim_id={primary_claim_id}")
            expected_event_ids: List[str] = []
            for claim_id in support_claim_ids:
                claim = self.claims.get(claim_id)
                if claim is None:
                    errors.append(f"{state_id}.missing_claim={claim_id}")
                    continue
                if state_id not in self.states_by_claim.get(claim_id, []):
                    errors.append(f"{state_id}.missing_support_edge={claim_id}")
                event_id = str(claim.get("source_event_id") or claim.get("dialog_id") or "")
                if event_id:
                    expected_event_ids.append(event_id)
            if support_event_ids != ordered_unique(expected_event_ids):
                errors.append(f"{state_id}.support_event_ids")
        if errors:
            preview = ", ".join(errors[:8])
            remainder = len(errors) - min(len(errors), 8)
            suffix = f" (+{remainder} more)" if remainder else ""
            raise ValueError(f"invalid active v2 state-merge query contract: {preview}{suffix}")

    def _build_documents(self) -> Tuple[List[str], List[str], List[str], List[str], List[str], List[str]]:
        event_doc_ids: List[str] = []
        event_documents: List[str] = []
        for event_id, event in sorted(self.events.items(), key=lambda item: dialog_sort_key(item[0])):
            doc_id = f"event::{event_id}"
            event_doc_ids.append(doc_id)
            event_documents.append(self._enhanced_event_document(event_id, event))
        scope_doc_ids: List[str] = []
        scope_documents: List[str] = []
        for scope_id, scope in sorted(self.scopes.items()):
            if str(scope.get("scope_type") or "") not in SEMANTIC_SCOPE_TYPES:
                continue
            doc_id = f"scope::{scope_id}"
            scope_doc_ids.append(doc_id)
            scope_documents.append(scope_document(scope))
        state_doc_ids: List[str] = []
        state_documents: List[str] = []
        for state_id, state in sorted(self.states.items()):
            state_doc_ids.append(f"state::{state_id}")
            state_documents.append(state_document(state))
        return (
            event_doc_ids,
            event_documents,
            scope_doc_ids,
            scope_documents,
            state_doc_ids,
            state_documents,
        )

    def _enhanced_event_document(self, event_id: str, event: Mapping[str, Any]) -> str:
        claim_text = " ".join(
            str(self.claims.get(claim_id, {}).get("graph_text") or claim_summary(self.claims.get(claim_id, {})))
            for claim_id in self.claims_by_event.get(event_id, [])
            if claim_id in self.claims
        )
        scope_text = " ".join(
            scope_document(self.scopes[scope_id])
            for scope_id in self.scopes_by_event.get(event_id, [])
            if scope_id in self.scopes
        )
        state_text = ""
        if getattr(self, "event_state_enrichment", False):
            state_ids = ordered_unique(
                state_id
                for claim_id in self.claims_by_event.get(event_id, [])
                for state_id in self.states_by_claim.get(claim_id, [])
                if state_id in self.states
            )
            state_text = " ".join(
                " ".join(
                    part
                    for part in (
                        str(self.states[state_id].get("subject") or ""),
                        str(self.states[state_id].get("state_dimension") or self.states[state_id].get("facet_key") or ""),
                        str(self.states[state_id].get("value") or ""),
                        str(self.states[state_id].get("status") or ""),
                    )
                    if part
                )
                for state_id in state_ids
            )
        return " ".join(part for part in (event_document(event), claim_text, scope_text, state_text) if part)

    def set_event_state_enrichment(self, enabled: bool) -> None:
        self.event_state_enrichment = bool(enabled)
        self.event_documents = [
            self._enhanced_event_document(event_id, self.events[event_id])
            for event_id in (doc_id[len("event::") :] for doc_id in self.event_doc_ids)
        ]
        self.event_bm25 = BM25Index(self.event_doc_ids, self.event_documents)

    def _state_primary_claim_id(self, state_id: str) -> str:
        """Return the explicit selected-value Claim or an unambiguous legacy equivalent."""
        state = self.states.get(state_id, {})
        primary_claim_id = str(state.get("primary_claim_id") or "")
        if primary_claim_id:
            return primary_claim_id
        support_claim_ids = ordered_unique(
            str(claim_id)
            for claim_id in state.get("support_claim_ids", []) or []
            if str(claim_id)
        )
        if len(support_claim_ids) == 1:
            return support_claim_ids[0]
        if support_claim_ids:
            return ""
        linked_claim_ids = ordered_unique(
            claim_id
            for claim_id, state_ids in getattr(self, "states_by_claim", {}).items()
            if state_id in state_ids
        )
        return linked_claim_ids[0] if len(linked_claim_ids) == 1 else ""

    def _state_evidence_policy(self) -> str:
        resolution = getattr(self, "manifest", {}).get("state_resolution", {})
        primary_centered = getattr(self, "schema_version", "") in STATE_MERGE_GRAPH_SCHEMAS or (
            isinstance(resolution, Mapping)
            and str(resolution.get("query_evidence_policy") or "")
            == "primary_claim_plus_relation_witnesses"
        )
        return (
            "primary-claim-plus-relation-witnesses"
            if primary_centered
            else "all-supports-legacy"
        )

    def _state_evidence_claim_ids(self, state_id: str) -> List[str]:
        """Project a StateFacet according to its declared proof policy."""
        state = self.states.get(state_id, {})
        support_claim_ids = ordered_unique(
            str(claim_id)
            for claim_id in state.get("support_claim_ids", []) or []
            if str(claim_id) in self.claims
        )
        if self._state_evidence_policy() != "primary-claim-plus-relation-witnesses":
            return support_claim_ids
        primary_claim_id = self._state_primary_claim_id(state_id)
        if not primary_claim_id:
            return support_claim_ids
        relation_witness_ids = [
            claim_id
            for claim_id in support_claim_ids
            if self.relations_by_claim.get(claim_id)
        ]
        cluster_witness_ids = ordered_unique([primary_claim_id, *relation_witness_ids])
        related_endpoint_ids: List[str] = []
        for claim_id in cluster_witness_ids:
            for edge in self.relations_by_claim.get(claim_id, []):
                source = str(edge.get("from") or "")
                target = str(edge.get("to") or "")
                related_claim_id = target if source == claim_id else source
                if related_claim_id in self.claims:
                    related_endpoint_ids.append(related_claim_id)
        return ordered_unique([*cluster_witness_ids, *related_endpoint_ids])

    def _state_is_current(self, state_id: str) -> bool:
        state = self.states.get(state_id, {})
        return (
            str(state.get("fact_type") or "") == "state"
            and str(state.get("temporal_status") or "") in {"ongoing", "timeless"}
            and str(state.get("intent") or "") == "none"
            and str(state.get("status") or "current") == "current"
        )

    def _event_time_profile(self, event_id: str, *, include_state: bool = True) -> Dict[str, Any]:
        event = self.events.get(event_id, {})
        roles: List[str] = []
        time_values: List[str] = []
        time_ids: List[str] = []
        current_state_ids: List[str] = []
        resolved_time_starts: List[str] = []
        resolved_time_ends: List[str] = []
        time_role_sources: List[str] = []
        occurred_at = self.occurred_time_by_event.get(event_id) or event.get("occurred_at")
        if occurred_at:
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
            if claim.get("resolved_time_start"):
                resolved_time_starts.append(str(claim["resolved_time_start"]))
            if claim.get("resolved_time_end"):
                resolved_time_ends.append(str(claim["resolved_time_end"]))
            if claim.get("time_role_source"):
                time_role_sources.append(str(claim["time_role_source"]))
            for time_item in self.times_by_claim.get(claim_id, []):
                time_role = str(time_item.get("time_role") or "")
                if time_role:
                    roles.append(time_role)
                if time_item.get("value"):
                    time_values.append(str(time_item["value"]))
                if time_item.get("time_id"):
                    time_ids.append(str(time_item["time_id"]))
            if include_state:
                for state_id in self.states_by_claim.get(claim_id, []):
                    state = self.states.get(state_id, {})
                    if (
                        self._state_is_current(state_id)
                        and claim_id == self._state_primary_claim_id(state_id)
                        and (state.get("current_after") or self.current_time_by_state.get(state_id))
                    ):
                        roles.append("CURRENT_AFTER")
                        current_state_ids.append(state_id)
        return {
            "time_roles": ordered_unique(roles),
            "time_values": ordered_unique(time_values),
            "time_ids": ordered_unique(time_ids),
            "current_state_ids": ordered_unique(current_state_ids),
            "resolved_time_starts": ordered_unique(resolved_time_starts),
            "resolved_time_ends": ordered_unique(resolved_time_ends),
            "time_role_sources": ordered_unique(time_role_sources),
        }

    def _event_recency_key(
        self,
        event_id: str,
        requested_roles: Sequence[str],
        *,
        include_state: bool = True,
    ) -> Tuple[str, int, Tuple[int, int]]:
        selected_roles = {str(role) for role in requested_roles if role}
        requested = selected_roles - {"CURRENT_AFTER"}
        if selected_roles == {"CURRENT_AFTER"}:
            if include_state:
                current_after_times = [
                    temporal_sort_value(
                        self.states.get(state_id, {}).get("current_after") or self.current_time_by_state.get(state_id)
                    )
                    for claim_id in self.claims_by_event.get(event_id, [])
                    for state_id in self.states_by_claim.get(claim_id, [])
                    if self._state_is_current(state_id) and claim_id == self._state_primary_claim_id(state_id)
                ]
                current_after_times = [value for value in current_after_times if value]
                if current_after_times:
                    return (max(current_after_times), 1, dialog_sort_key(event_id))
            report_time = temporal_sort_value(
                self.events.get(event_id, {}).get("occurred_at") or self.occurred_time_by_event.get(event_id)
            )
            return (report_time, 0 if report_time else -1, dialog_sort_key(event_id))
        fact_times: List[str] = []
        for claim_id in self.claims_by_event.get(event_id, []):
            claim = self.claims.get(claim_id, {})
            claim_role = str(claim.get("time_role") or "")
            if requested and claim_role not in requested:
                continue
            fact_time = temporal_sort_value(claim.get("resolved_time_end") or claim.get("resolved_time_start"))
            if fact_time:
                fact_times.append(fact_time)
        if fact_times:
            return (max(fact_times), 1, dialog_sort_key(event_id))
        report_time = temporal_sort_value(
            self.events.get(event_id, {}).get("occurred_at") or self.occurred_time_by_event.get(event_id)
        )
        return (report_time, 0 if report_time else -1, dialog_sort_key(event_id))

    def _event_routing_time_roles(self, event_id: str, *, include_state: bool = True) -> List[str]:
        """Return semantic roles linked through Claims/Times and, optionally, StateFacets."""
        roles: List[str] = []
        for claim_id in self.claims_by_event.get(event_id, []):
            claim = self.claims.get(claim_id, {})
            claim_role = str(claim.get("time_role") or "")
            if claim_role:
                roles.append(claim_role)
            for time_item in self.times_by_claim.get(claim_id, []):
                time_role = str(time_item.get("time_role") or "")
                if time_role:
                    roles.append(time_role)
            if include_state:
                for state_id in self.states_by_claim.get(claim_id, []):
                    state = self.states.get(state_id, {})
                    if (
                        self._state_is_current(state_id)
                        and claim_id == self._state_primary_claim_id(state_id)
                        and (state.get("current_after") or self.current_time_by_state.get(state_id))
                    ):
                        roles.append("CURRENT_AFTER")
        return ordered_unique(roles)

    def _rerank_event_rows(
        self,
        event_rows: Sequence[Mapping[str, Any]],
        time_roles: Sequence[str],
        limit: int,
        ordering: str = "",
        *,
        include_state: bool = True,
    ) -> List[Dict[str, Any]]:
        requested_roles = {str(role) for role in time_roles if role}
        candidate_event_ids = [
            str(candidate.get("doc_id") or "")[len("event::") :]
            for candidate in event_rows
            if str(candidate.get("doc_id") or "").startswith("event::")
        ]
        chronological = sorted(
            set(candidate_event_ids),
            key=lambda event_id: self._event_recency_key(
                event_id,
                time_roles,
                include_state=include_state,
            ),
        )
        recency_by_event = {
            event_id: (rank / max(1, len(chronological) - 1)) * RECENCY_RANK_BOOST
            for rank, event_id in enumerate(chronological)
        }
        ranked: List[Dict[str, Any]] = []
        for candidate in event_rows:
            doc_id = str(candidate.get("doc_id") or "")
            if not doc_id.startswith("event::"):
                continue
            event_id = doc_id[len("event::") :]
            profile = self._event_time_profile(event_id, include_state=include_state)
            matched_roles = sorted(requested_roles.intersection(profile["time_roles"]))
            time_role_score = TIME_ROLE_MATCH_BOOST if matched_roles else 0.0
            recency_score = recency_by_event.get(event_id, 0.0) if ordering == "newest_first" else 0.0
            row = dict(candidate)
            row.update(
                {
                    "event_id": event_id,
                    "base_retrieval_score": round(float(candidate.get("score") or 0.0), 6),
                    "selected_time_roles": sorted(requested_roles),
                    "event_time_roles": profile["time_roles"],
                    "matched_time_roles": matched_roles,
                    "time_role_score": round(time_role_score, 4),
                    "recency_score": round(recency_score, 4),
                    "time_values": profile["time_values"],
                    "time_ids": profile["time_ids"],
                    "current_state_ids": profile["current_state_ids"],
                    "resolved_time_starts": profile["resolved_time_starts"],
                    "resolved_time_ends": profile["resolved_time_ends"],
                    "time_role_sources": profile["time_role_sources"],
                    "score": round(float(candidate.get("score") or 0.0) + time_role_score + recency_score, 6),
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

    @staticmethod
    def _scope_semantic_key(scope: Mapping[str, Any]) -> Tuple[str, str]:
        return (
            str(scope.get("scope_type") or ""),
            normalize_entity_reference(scope.get("value") or scope.get("label")),
        )

    def resolve_anchor_scope_doc_ids(
        self,
        entities: Sequence[object],
        allowed_scope_types: Sequence[str] = SEMANTIC_SCOPE_TYPES,
    ) -> List[str]:
        """Resolve question-mentioned participants to exact Speaker and atomic Entity Scopes."""
        entity_aliases = ordered_unique(
            normalize_participant_reference(entity)
            for entity in entities
            if normalize_participant_reference(entity)
        )
        speaker_aliases = ordered_unique(
            normalize_participant_reference(scope.get("value") or scope.get("label"))
            for scope in self.scopes.values()
            if str(scope.get("scope_type") or "") == "speaker"
            and normalize_participant_reference(scope.get("value") or scope.get("label"))
        )
        mentioned_speakers = {
            speaker_alias
            for speaker_alias in speaker_aliases
            if any(
                entity_alias == speaker_alias
                or entity_alias.startswith(f"{speaker_alias} ")
                or f" {speaker_alias} " in f" {entity_alias} "
                for entity_alias in entity_aliases
            )
        }
        grouped_scope_ids: DefaultDict[Tuple[str, str], List[str]] = defaultdict(list)
        allowed_type_set = set(allowed_scope_types)
        for scope_id, scope in self.scopes.items():
            scope_type, scope_alias = self._scope_semantic_key(scope)
            if (
                scope_type not in {"speaker", "entity"}
                or scope_type not in allowed_type_set
                or scope_alias not in mentioned_speakers
            ):
                continue
            grouped_scope_ids[(scope_type, scope_alias)].append(str(scope_id))
        return [
            f"scope::{sorted(scope_ids)[0]}"
            for _key, scope_ids in sorted(grouped_scope_ids.items())
        ]

    def _participant_aliases(self) -> List[str]:
        return ordered_unique(
            normalize_participant_reference(scope.get("value") or scope.get("label"))
            for scope in self.scopes.values()
            if str(scope.get("scope_type") or "") == "speaker"
            and normalize_participant_reference(scope.get("value") or scope.get("label"))
        )

    def _participant_mentions(self, values: Sequence[object]) -> List[str]:
        normalized_values = ordered_unique(
            normalize_participant_reference(value)
            for value in values
            if normalize_participant_reference(value)
        )
        return [
            alias
            for alias in self._participant_aliases()
            if any(
                value == alias
                or value.startswith(f"{alias} ")
                or f" {alias} " in f" {value} "
                for value in normalized_values
            )
        ]

    def evaluate_participant_binding(
        self,
        frame: Mapping[str, Any],
        cited_event_ids: Sequence[str],
    ) -> Dict[str, Any]:
        """Conservatively reject cited evidence whose participant owner contradicts the question."""
        binding_values: List[object] = list(frame.get("entities", []) or [])
        for binding in frame.get("required_bindings", []) or []:
            if not isinstance(binding, Mapping):
                continue
            binding_values.extend([binding.get("subject"), binding.get("object")])
        question_participants = self._participant_mentions(binding_values)
        participant_aliases = self._participant_aliases()
        cited_claim_ids = ordered_unique(
            claim_id
            for event_id in cited_event_ids
            for claim_id in self.claims_by_event.get(str(event_id), [])
            if claim_id in self.claims
        )
        evidence_participants: List[str] = []
        for claim_id in cited_claim_ids:
            claim = self.claims[claim_id]
            subject_values = [
                str(claim.get("subject_key") or "").replace("_", " "),
                claim.get("canonical_subject"),
                claim.get("subject"),
            ]
            claim_participants = self._participant_mentions(subject_values)
            if claim_participants:
                evidence_participants.extend(claim_participants)
                continue
            source_event_id = self._claim_source_event_id(claim_id)
            source_event = self.events.get(source_event_id, {})
            evidence_participants.extend(
                alias
                for alias in participant_aliases
                if normalize_participant_reference(source_event.get("speaker")) == alias
            )
        if not cited_claim_ids:
            for event_id in cited_event_ids:
                speaker = normalize_participant_reference(self.events.get(str(event_id), {}).get("speaker"))
                if speaker in participant_aliases:
                    evidence_participants.append(speaker)
        evidence_participants = ordered_unique(evidence_participants)
        if not question_participants or not cited_event_ids or not evidence_participants:
            status = "not_applicable"
            blocked = False
        elif set(question_participants).intersection(evidence_participants):
            status = "supported_participant"
            blocked = False
        else:
            status = "contradicted_participant"
            blocked = True
        return {
            "mode": "participant_owner_overlap",
            "status": status,
            "blocked": blocked,
            "question_participants": question_participants,
            "evidence_participants": evidence_participants,
            "cited_event_ids": ordered_unique(str(event_id) for event_id in cited_event_ids if str(event_id)),
            "cited_claim_ids": cited_claim_ids,
            "uses_task_labels": False,
            "uses_gold": False,
        }

    def retrieve(
        self,
        question: str,
        *,
        retrieval_queries: Sequence[str],
        variant: str,
        top_k: int,
        candidate_k: int,
        scope_top_k: int,
        scope_backoff_k: int,
        max_context_events: int,
        max_state_lines: int,
        embedding_indices: Mapping[str, OpenAIEmbeddingIndex],
        embedding_candidate_k: int,
        scope_types: Sequence[str],
        time_role_client: Any,
        time_role_selector: str,
        event_time_routing: str,
        graph_expansion: str = "auto",
        query_subject_ids: Sequence[str] = (),
        readout_operation: str = "lookup",
        query_entities: Sequence[object] = (),
        scope_anchor_routing: str = "off",
        retrieval_policy: str = "sts",
    ) -> RetrievalResult:
        if retrieval_policy not in RETRIEVAL_POLICIES:
            raise ValueError(f"unsupported retrieval_policy={retrieval_policy}")
        if retrieval_policy != "sts" and variant == "graph_embedding_scope_statefacet":
            raise ValueError(
                "graph_embedding_scope_statefacet is available only for retrieval_policy=sts"
            )
        targets = embedding_targets_for_policy(variant, retrieval_policy)
        queries = ordered_unique([question, *retrieval_queries])[:MAX_RETRIEVAL_QUERIES]
        event_bm25 = self.event_bm25 if retrieval_policy == "sts" else self.raw_event_bm25

        if retrieval_policy == "event-rag":
            event_bm25_hits = bm25_search_queries(event_bm25, queries, candidate_k)
            event_embedding_hits: Sequence[Any] = []
            if "event" in targets:
                event_index = embedding_indices.get("event")
                if event_index is None:
                    raise ValueError(f"{variant} requires an event embedding index")
                event_embedding_hits = embedding_search_queries(
                    event_index,
                    queries,
                    embedding_candidate_k,
                )
            event_candidate_rows = rrf_union_rows(event_bm25_hits, event_embedding_hits)
            selected_event_rows = event_candidate_rows[:top_k]
            seed_event_ids = [
                str(row["doc_id"])[len("event::") :]
                for row in selected_event_rows
                if str(row.get("doc_id") or "").startswith("event::")
            ]
            event_ids, state_ids, expanded_claim_ids, _relation_lines, expansion_trace = (
                self._expand_event_seeds(
                    seed_event_ids,
                    event_candidate_rows=event_candidate_rows,
                    graph_expansion=graph_expansion,
                    max_context_events=max_context_events,
                    max_state_lines=max_state_lines,
                    retrieval_queries=queries,
                    query_subject_ids=query_subject_ids,
                    readout_operation=readout_operation,
                )
            )
            disabled_time = disabled_time_role_selection(time_role_selector)
            trace = {
                "graph_schema_version": self.schema_version,
                "retrieval_policy": retrieval_policy,
                "retrieval_queries": queries,
                "pipeline_order": [
                    "question_semantic_frame",
                    "sample_wide_event_candidate_retrieval",
                    "event_claim_statefacet_graph_expansion",
                ],
                "embedding_targets": sorted(targets),
                "scope_routing": {
                    "mode": "disabled_by_retrieval_policy",
                    "scope_ids": [],
                    "uses_task_labels": False,
                    "uses_gold": False,
                },
                "event_retrieval": {
                    "routing": "sample-wide-events",
                    "routed_scope_ids": [],
                    "time_routing_mode": "disabled",
                    "bm25_hits": [
                        {"doc_id": doc_id, "score": score}
                        for doc_id, score in event_bm25_hits[: min(candidate_k, 30)]
                    ],
                    "embedding_hits": [
                        {"doc_id": hit.doc_id, "score": hit.score}
                        for hit in event_embedding_hits[:30]
                    ],
                    "pre_time_role_union_hits": event_candidate_rows[:30],
                    "selected_event_hits": selected_event_rows,
                },
                "time_role_selection": disabled_time,
                "graph_expansion": expansion_trace,
                "selected_state_ids": state_ids,
                "expanded_claim_ids": expanded_claim_ids,
                "statefacet_access": {
                    "mode": "event-claim-graph-expansion-raw-event-readout",
                    "path": ["Event", "Claim", "StateFacet"],
                    "state_evidence_policy": self._state_evidence_policy(),
                },
                "answer_evidence": {"mode": "raw-events-only"},
            }
            return RetrievalResult(
                candidate_dialog_ids=event_ids,
                temporal_lines=[],
                claim_lines=[],
                state_lines=[],
                relation_lines=[],
                context=self._context_text(event_ids),
                trace=trace,
            )

        scope_allowed_doc_ids = [
            f"scope::{scope_id}"
            for scope_id, scope in self.scopes.items()
            if not scope_types or str(scope.get("scope_type") or "") in set(scope_types)
        ]
        scope_bm25_hits = bm25_search_queries(
            self.scope_bm25,
            queries,
            candidate_k,
            allowed_doc_ids=scope_allowed_doc_ids,
        )
        scope_embedding_hits: Sequence[Any] = []
        if "scope" in targets:
            scope_index = embedding_indices.get("scope")
            if scope_index is None:
                raise ValueError(f"{variant} requires a scope embedding index")
            scope_embedding_hits = embedding_search_queries(
                scope_index,
                queries,
                embedding_candidate_k,
                allowed_doc_ids=scope_allowed_doc_ids,
            )
        scope_candidate_rows = hybrid_union_rows(scope_bm25_hits, scope_embedding_hits)
        if scope_anchor_routing not in {"off", "reserve"}:
            raise ValueError(f"unsupported scope_anchor_routing={scope_anchor_routing}")
        anchor_scope_doc_ids = (
            self.resolve_anchor_scope_doc_ids(query_entities, scope_types)
            if scope_anchor_routing == "reserve"
            else []
        )
        scope_row_by_id = {
            str(row.get("doc_id") or ""): row
            for row in scope_candidate_rows
        }
        anchor_scope_rows: List[Dict[str, Any]] = []
        anchor_scope_keys: set[Tuple[str, str]] = set()
        for doc_id in anchor_scope_doc_ids:
            scope_id = doc_id[len("scope::") :] if doc_id.startswith("scope::") else ""
            scope = self.scopes.get(scope_id, {})
            anchor_scope_keys.add(self._scope_semantic_key(scope))
            row = dict(
                scope_row_by_id.get(
                    doc_id,
                    {
                        "doc_id": doc_id,
                        "lexical_score": 0.0,
                        "embedding_score": 0.0,
                        "score": 0.0,
                        "retrieval_source": "exact-anchor",
                    },
                )
            )
            row["anchor_match"] = True
            anchor_scope_rows.append(row)
        semantic_scope_rows = [
            row
            for row in scope_candidate_rows
            if self._scope_semantic_key(
                self.scopes.get(str(row.get("doc_id") or "")[len("scope::") :], {})
            ) not in anchor_scope_keys
        ]
        selected_scope_rows = [*anchor_scope_rows, *semantic_scope_rows][:scope_top_k]
        selected_scope_hits = [(str(row["doc_id"]), float(row["score"])) for row in selected_scope_rows]
        routed_scope_ids = [doc_id[len("scope::") :] for doc_id, _score in selected_scope_hits if doc_id.startswith("scope::")]
        scope_trace = {
            "anchor_routing": scope_anchor_routing,
            "anchor_source": "question_frame_entities" if scope_anchor_routing == "reserve" else "disabled",
            "anchor_scope_doc_ids": anchor_scope_doc_ids,
            "uses_task_labels": False,
            "uses_gold": False,
            "bm25_hits": [
                {"doc_id": doc_id, "score": score}
                for doc_id, score in scope_bm25_hits[: min(candidate_k, 20)]
            ],
            "embedding_hits": [
                {"doc_id": hit.doc_id, "score": hit.score}
                for hit in scope_embedding_hits[:20]
            ],
            "union_hits": scope_candidate_rows[:20],
            "selected_scope_hits": selected_scope_rows,
            "scope_ids": routed_scope_ids,
            "sample_scope_backoff_k": scope_backoff_k,
        }
        sample_backoff_enabled = scope_backoff_k > 0 and event_time_routing == "rerank"
        if routed_scope_ids:
            event_routing = (
                "routed-scopes-plus-explicit-sample-backoff"
                if sample_backoff_enabled
                else "routed-scopes"
            )
        else:
            event_routing = "explicit-sample-backoff-only" if sample_backoff_enabled else "no-routed-scope"

        time_enabled = retrieval_policy in {"scope-event-time", "sts"}
        time_role_selection = (
            select_time_roles(question, time_role_client, time_role_selector)
            if time_enabled
            else disabled_time_role_selection(time_role_selector)
        )
        if variant == "graph_embedding_scope_statefacet":
            allowed_state_doc_ids = [
                f"state::{state_id}"
                for state_id in ordered_unique(
                    state_id
                    for scope_id in routed_scope_ids
                    for state_id in self.states_by_scope.get(scope_id, [])
                )
            ]
            state_bm25_hits = bm25_search_queries(
                self.state_bm25,
                queries,
                candidate_k,
                allowed_doc_ids=allowed_state_doc_ids,
            )
            state_index = embedding_indices.get("state")
            if state_index is None:
                raise ValueError(f"{variant} requires a StateFacet embedding index")
            state_embedding_hits = embedding_search_queries(
                state_index,
                queries,
                embedding_candidate_k,
                allowed_doc_ids=allowed_state_doc_ids,
            )
            state_candidate_rows = rrf_union_rows(state_bm25_hits, state_embedding_hits)
            selected_state_rows = state_candidate_rows[:top_k]
            seed_state_ids = [
                str(row["doc_id"])[len("state::") :]
                for row in selected_state_rows
                if str(row.get("doc_id") or "").startswith("state::")
            ]
            event_ids, state_ids, relation_lines, expansion_trace = self._expand_relation_aware(
                [],
                seed_state_ids=seed_state_ids,
                max_context_events=max_context_events,
                max_state_lines=max_state_lines,
                retrieval_queries=queries,
                query_subject_ids=query_subject_ids,
                readout_operation=readout_operation,
            )
            event_ids, state_ids, expanded_claim_ids, relation_lines, closure_trace = self._closed_evidence_pack(
                event_ids,
                state_ids,
                max_state_lines=max_state_lines,
                candidate_claim_ids=expansion_trace.get("visited_claim_ids"),
            )
            expansion_trace["evidence_closure"] = closure_trace
            expansion_trace["expanded_event_ids"] = event_ids
            expansion_trace["selected_state_ids"] = state_ids
            expansion_trace["statefacet_origin"] = "scoped-statefacet-direct-retrieval"
            expansion_trace["state_evidence_policy"] = self._state_evidence_policy()
            trace = {
                "graph_schema_version": self.schema_version,
                "retrieval_policy": retrieval_policy,
                "retrieval_queries": queries,
                "pipeline_order": [
                    "question_semantic_frame",
                    "scope_routing",
                    "time_role_selection",
                    "statefacet_candidate_retrieval",
                    "statefacet_claim_event_proof_closure",
                ],
                "graph_expansion": expansion_trace,
                "embedding_targets": sorted(targets),
                "scope_routing": scope_trace,
                "statefacet_retrieval": {
                    "routing": "routed-scopes-only",
                    "routed_scope_ids": routed_scope_ids,
                    "allowed_state_count": len(allowed_state_doc_ids),
                    "bm25_hits": [
                        {"doc_id": doc_id, "score": score}
                        for doc_id, score in state_bm25_hits[: min(candidate_k, 30)]
                    ],
                    "embedding_hits": [
                        {"doc_id": hit.doc_id, "score": hit.score}
                        for hit in state_embedding_hits[:30]
                    ],
                    "pre_selection_union_hits": state_candidate_rows[:30],
                    "selected_state_hits": selected_state_rows,
                    "independent_event_retrieval": False,
                    "sample_event_backoff": False,
                },
                "event_retrieval": {
                    "routing": "proof-closure-only",
                    "selected_event_hits": [],
                    "independent_retrieval": False,
                },
                "time_role_selection": time_role_selection,
                "selected_state_ids": state_ids,
                "expanded_claim_ids": expanded_claim_ids,
                "statefacet_access": {
                    "mode": "scoped-statefacet-direct-retrieval",
                    "path": ["Scope", "StateFacet", "Claim", "Event"],
                    "state_evidence_policy": self._state_evidence_policy(),
                },
            }
            return RetrievalResult(
                candidate_dialog_ids=event_ids,
                temporal_lines=[],
                claim_lines=[format_claim_line(self.claims[claim_id]) for claim_id in expanded_claim_ids],
                state_lines=[format_state_line(self.states[state_id]) for state_id in state_ids],
                relation_lines=relation_lines,
                context=self._context_text(event_ids),
                trace=trace,
            )

        allowed_event_doc_ids = self._event_doc_ids_for_scopes(routed_scope_ids)
        time_routed_event_ids: List[str] = []
        if event_time_routing not in {"rerank", "prefilter"}:
            raise ValueError(f"unsupported event_time_routing={event_time_routing}")
        if event_time_routing == "prefilter" and time_role_selection["time_roles"]:
            requested_roles = set(time_role_selection["time_roles"])
            scoped_event_ids = {
                doc_id[len("event::") :]
                for doc_id in (allowed_event_doc_ids or [])
                if doc_id.startswith("event::")
            }
            time_routed_event_ids = [
                event_id
                for event_id in sorted(scoped_event_ids)
                if requested_roles.intersection(
                    self._event_routing_time_roles(
                        event_id,
                        include_state=retrieval_policy == "sts",
                    )
                )
            ]
            allowed_event_doc_ids = [f"event::{event_id}" for event_id in time_routed_event_ids]
        scoped_event_bm25_hits = bm25_search_queries(
            event_bm25,
            queries,
            candidate_k,
            allowed_doc_ids=allowed_event_doc_ids,
        )
        sample_event_bm25_hits = (
            bm25_search_queries(event_bm25, queries, scope_backoff_k)
            if scope_backoff_k > 0 and event_time_routing == "rerank"
            else []
        )
        event_bm25_hits = merge_scored_hits(scoped_event_bm25_hits, sample_event_bm25_hits)
        event_embedding_hits: Sequence[Any] = []
        sample_event_embedding_hits: Sequence[Any] = []
        if "event" in targets:
            event_index = embedding_indices.get("event")
            if event_index is None:
                raise ValueError(f"{variant} requires an event embedding index")
            scoped_event_embedding_hits = embedding_search_queries(
                event_index,
                queries,
                embedding_candidate_k,
                allowed_doc_ids=allowed_event_doc_ids,
            )
            sample_event_embedding_hits = (
                embedding_search_queries(event_index, queries, scope_backoff_k)
                if scope_backoff_k > 0 and event_time_routing == "rerank"
                else []
            )
            event_embedding_hits = merge_embedding_hits(scoped_event_embedding_hits, sample_event_embedding_hits)
        event_candidate_rows = rrf_union_rows(event_bm25_hits, event_embedding_hits)
        selected_event_rows = (
            self._rerank_event_rows(
                event_candidate_rows,
                time_role_selection["time_roles"],
                top_k,
                str(time_role_selection.get("ordering") or ""),
                include_state=retrieval_policy == "sts",
            )
            if time_enabled
            else [dict(row) for row in event_candidate_rows[:top_k]]
        )
        selected_event_hits = [(str(row["doc_id"]), float(row["score"])) for row in selected_event_rows]
        seed_event_ids: List[str] = []
        for doc_id, _score in selected_event_hits:
            if not doc_id.startswith("event::"):
                continue
            event_id = doc_id[len("event::") :]
            seed_event_ids.append(event_id)

        if retrieval_policy in {"scope-event", "scope-event-time"}:
            event_ids, state_ids, expanded_claim_ids, _relation_lines, expansion_trace = (
                self._expand_event_seeds(
                    seed_event_ids,
                    event_candidate_rows=event_candidate_rows,
                    graph_expansion=graph_expansion,
                    max_context_events=max_context_events,
                    max_state_lines=max_state_lines,
                    retrieval_queries=queries,
                    query_subject_ids=query_subject_ids,
                    readout_operation=readout_operation,
                )
            )
            trace = {
                "graph_schema_version": self.schema_version,
                "retrieval_policy": retrieval_policy,
                "retrieval_queries": queries,
                "pipeline_order": [
                    "question_semantic_frame",
                    "scope_routing",
                    "time_role_selection" if time_enabled else "time_role_selection_disabled",
                    "event_candidate_retrieval",
                    "event_time_rerank" if time_enabled else "event_rank_without_time",
                    "event_claim_statefacet_graph_expansion",
                ],
                "embedding_targets": sorted(targets),
                "scope_routing": scope_trace,
                "event_retrieval": {
                    "routing": event_routing,
                    "routed_scope_ids": routed_scope_ids,
                    "time_routing_mode": event_time_routing if time_enabled else "disabled",
                    "time_prefilter_applied": bool(
                        time_enabled
                        and event_time_routing == "prefilter"
                        and time_role_selection["time_roles"]
                    ),
                    "time_routed_event_count": len(time_routed_event_ids),
                    "time_routed_event_ids": time_routed_event_ids,
                    "scoped_bm25_hits": [
                        {"doc_id": doc_id, "score": score}
                        for doc_id, score in scoped_event_bm25_hits[: min(candidate_k, 30)]
                    ],
                    "sample_scope_bm25_hits": [
                        {"doc_id": doc_id, "score": score}
                        for doc_id, score in sample_event_bm25_hits
                    ],
                    "bm25_hits": [
                        {"doc_id": doc_id, "score": score}
                        for doc_id, score in event_bm25_hits[: min(candidate_k, 30)]
                    ],
                    "embedding_hits": [
                        {"doc_id": hit.doc_id, "score": hit.score}
                        for hit in event_embedding_hits[:30]
                    ],
                    "pre_time_role_union_hits": event_candidate_rows[:30],
                    "selected_event_hits": selected_event_rows,
                },
                "time_role_selection": time_role_selection,
                "graph_expansion": expansion_trace,
                "selected_state_ids": state_ids,
                "expanded_claim_ids": expanded_claim_ids,
                "statefacet_access": {
                    "mode": "event-claim-graph-expansion-raw-event-readout",
                    "path": ["Scope", "Event", "Claim", "StateFacet"],
                    "state_evidence_policy": self._state_evidence_policy(),
                },
                "answer_evidence": {"mode": "raw-events-only"},
            }
            return RetrievalResult(
                candidate_dialog_ids=event_ids,
                temporal_lines=[],
                claim_lines=[],
                state_lines=[],
                relation_lines=[],
                context=self._context_text(event_ids),
                trace=trace,
            )

        event_ids, state_ids, expanded_claim_ids, relation_lines, expansion_trace = self._expand_event_seeds(
            seed_event_ids,
            event_candidate_rows=event_candidate_rows,
            graph_expansion=graph_expansion,
            max_context_events=max_context_events,
            max_state_lines=max_state_lines,
            retrieval_queries=queries,
            query_subject_ids=query_subject_ids,
            readout_operation=readout_operation,
        )
        claim_lines = [format_claim_line(self.claims[claim_id]) for claim_id in expanded_claim_ids]
        state_lines = [format_state_line(self.states[state_id]) for state_id in state_ids if state_id in self.states]
        context = self._context_text(event_ids)
        trace = {
            "graph_schema_version": self.schema_version,
            "retrieval_policy": retrieval_policy,
            "retrieval_queries": queries,
            "pipeline_order": [
                "question_semantic_frame",
                "scope_routing",
                "time_role_selection",
                "event_candidate_retrieval",
                "event_time_rerank",
                "event_claim_statefacet_graph_expansion",
            ],
            "graph_expansion": expansion_trace,
            "embedding_targets": sorted(targets),
            "scope_routing": scope_trace,
            "event_retrieval": {
                "routing": event_routing,
                "routed_scope_ids": routed_scope_ids,
                "time_routing_mode": event_time_routing,
                "time_prefilter_applied": event_time_routing == "prefilter" and bool(time_role_selection["time_roles"]),
                "time_routed_event_count": len(time_routed_event_ids),
                "time_routed_event_ids": time_routed_event_ids,
                "scoped_bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in scoped_event_bm25_hits[: min(candidate_k, 30)]],
                "sample_scope_bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in sample_event_bm25_hits],
                "bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in event_bm25_hits[: min(candidate_k, 30)]],
                "embedding_hits": [{"doc_id": hit.doc_id, "score": hit.score} for hit in event_embedding_hits[:30]],
                "sample_scope_embedding_hits": [{"doc_id": hit.doc_id, "score": hit.score} for hit in sample_event_embedding_hits],
                "pre_time_role_union_hits": event_candidate_rows[:30],
                "selected_event_hits": selected_event_rows,
            },
            "time_role_selection": time_role_selection,
            "selected_state_ids": state_ids,
            "expanded_claim_ids": expanded_claim_ids,
            "statefacet_access": {
                "mode": "event-claim-graph-expansion-only",
                "path": ["Scope", "Event", "Claim", "StateFacet"],
                "state_evidence_policy": self._state_evidence_policy(),
            },
        }
        return RetrievalResult(
            candidate_dialog_ids=event_ids,
            temporal_lines=[],
            claim_lines=claim_lines,
            state_lines=state_lines,
            relation_lines=relation_lines,
            context=context,
            trace=trace,
        )

    def _expand_event_seeds(
        self,
        seed_event_ids: Sequence[str],
        *,
        event_candidate_rows: Sequence[Mapping[str, Any]],
        graph_expansion: str,
        max_context_events: int,
        max_state_lines: int,
        retrieval_queries: Sequence[str],
        query_subject_ids: Sequence[str],
        readout_operation: str,
    ) -> Tuple[List[str], List[str], List[str], List[str], Dict[str, Any]]:
        """Expand Event seeds with the shared graph policy and retain closed proof paths."""
        resolved_expansion = self.resolve_graph_expansion(graph_expansion)
        if resolved_expansion == "scope-coverage":
            event_ids, state_ids, relation_lines, expansion_trace = self._expand_scope_coverage(
                seed_event_ids,
                event_candidate_rows=event_candidate_rows,
                max_context_events=max_context_events,
                max_state_lines=max_state_lines,
                retrieval_queries=retrieval_queries,
            )
        elif resolved_expansion == "relation-aware":
            event_ids, state_ids, relation_lines, expansion_trace = self._expand_relation_aware(
                seed_event_ids,
                max_context_events=max_context_events,
                max_state_lines=max_state_lines,
                retrieval_queries=retrieval_queries,
                query_subject_ids=query_subject_ids,
                readout_operation=readout_operation,
            )
        else:
            event_ids = ordered_unique(seed_event_ids)
            if max_context_events > 0:
                event_ids = event_ids[:max_context_events]
            state_ids = ordered_unique(
                state_id
                for event_id in event_ids
                for claim_id in self.claims_by_event.get(event_id, [])
                for state_id in self.states_by_claim.get(claim_id, [])
            )
            relation_lines = []
            expansion_trace = {
                "mode": "legacy",
                "seed_event_ids": list(seed_event_ids),
                "selected_state_ids": state_ids,
                "expanded_event_ids": event_ids,
            }
        event_ids, state_ids, claim_ids, relation_lines, closure_trace = self._closed_evidence_pack(
            event_ids,
            state_ids,
            max_state_lines=max_state_lines,
            candidate_claim_ids=expansion_trace.get("visited_claim_ids"),
        )
        expanded_claim_set = set(claim_ids)
        expanded_event_set = set(event_ids)
        unreachable_state_ids = [
            state_id
            for state_id in state_ids
            if not self._state_evidence_claim_ids(state_id)
            or not all(
                claim_id in expanded_claim_set
                and self._claim_source_event_id(claim_id) in expanded_event_set
                for claim_id in self._state_evidence_claim_ids(state_id)
            )
        ]
        if unreachable_state_ids:
            raise ValueError(
                "StateFacet graph-expansion invariant failed; facets lack their primary/relation proof path: "
                f"{unreachable_state_ids}"
            )
        expansion_trace.update(
            {
                "evidence_closure": closure_trace,
                "expanded_event_ids": event_ids,
                "selected_state_ids": state_ids,
                "statefacet_origin": "event-claim-graph-expansion",
                "state_evidence_policy": self._state_evidence_policy(),
            }
        )
        return event_ids, state_ids, claim_ids, relation_lines, expansion_trace

    def resolve_graph_expansion(self, requested: str) -> str:
        if requested not in GRAPH_EXPANSIONS:
            raise ValueError(f"unsupported graph_expansion={requested}")
        if requested != "auto":
            return requested
        if self.schema_version in STATE_MERGE_GRAPH_SCHEMAS:
            return "relation-aware"
        return "legacy"

    def _claim_source_event_id(self, claim_id: str) -> str:
        claim = self.claims.get(claim_id, {})
        explicit = str(claim.get("source_event_id") or claim.get("dialog_id") or "")
        if explicit in self.events:
            return explicit
        for event_id, claim_ids in self.claims_by_event.items():
            if claim_id in claim_ids and event_id in self.events:
                return event_id
        return ""

    def _state_required_event_ids(self, state_id: str) -> List[str]:
        evidence_claim_ids = self._state_evidence_claim_ids(state_id)
        required = [self._claim_source_event_id(claim_id) for claim_id in evidence_claim_ids]
        if not evidence_claim_ids:
            required.extend(
                str(event_id)
                for event_id in self.states.get(state_id, {}).get("support_event_ids", []) or []
                if str(event_id)
            )
        return ordered_unique(event_id for event_id in required if event_id)

    def _state_support_is_closed(self, state_id: str, retained_event_ids: set[str]) -> bool:
        required_event_ids = self._state_required_event_ids(state_id)
        if not required_event_ids or not set(required_event_ids).issubset(retained_event_ids):
            return False
        for identifier in self._state_evidence_claim_ids(state_id):
            if identifier not in self.claims or self._claim_source_event_id(identifier) not in retained_event_ids:
                return False
        return True

    def _relation_lines_for_closed_claims(
        self,
        claim_ids: Sequence[str],
        event_ids: Sequence[str],
    ) -> Tuple[List[str], int]:
        retained_claims = set(claim_ids)
        retained_events = set(event_ids)
        seen: set[Tuple[str, str, str]] = set()
        lines: List[str] = []
        dropped = 0
        for claim_id in claim_ids:
            for edge in self.relations_by_claim.get(claim_id, []):
                key = (
                    str(edge.get("type") or ""),
                    str(edge.get("from") or ""),
                    str(edge.get("to") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                evidence_event_ids = {
                    str(event_id)
                    for event_id in edge.get("evidence_event_ids", []) or []
                    if str(event_id)
                }
                if (
                    key[1] not in retained_claims
                    or key[2] not in retained_claims
                    or not evidence_event_ids.issubset(retained_events)
                ):
                    dropped += 1
                    continue
                lines.append(self._format_relation_edge(edge))
        return lines, dropped

    def _claim_relevance_terms(self, claim_id: str) -> set[str]:
        claim = self.claims.get(claim_id, {})
        text = " ".join(
            str(claim.get(field) or "")
            for field in (
                "value",
                "answer_span",
                "state_object",
                "state_slot",
                "facet_key",
                "state_domain",
                "state_target",
                "state_dimension",
                "canonical_object_id",
                "canonical_state_slot",
            )
        )
        return {term for term in tokenized(text) if term not in QUERY_STOP_TERMS}

    def _claim_query_relevance(
        self,
        claim_id: str,
        query_terms: set[str],
        term_document_frequency: Mapping[str, int],
    ) -> float:
        if not query_terms:
            return 0.0
        claim_terms = self._claim_relevance_terms(claim_id)
        document_count = max(len(self.claims), 1)

        def weight(term: str) -> float:
            return math.log((document_count + 1.0) / (float(term_document_frequency.get(term, 0)) + 1.0)) + 1.0

        denominator = sum(weight(term) for term in query_terms)
        if denominator <= 0.0:
            return 0.0
        return sum(weight(term) for term in query_terms.intersection(claim_terms)) / denominator

    def _claim_relation_continuity_key(self, claim_id: str) -> Tuple[str, str, str]:
        claim = self.claims.get(claim_id, {})
        subject_id = subject_identity(claim)
        state_group_id = state_dimension_identity(claim)
        if subject_id and state_group_id:
            return ("state_dimension", subject_id, state_group_id)
        fallback_slot = str(
            claim.get("canonical_state_slot")
            or claim.get("state_slot")
            or claim.get("facet_key")
            or ""
        ).strip().casefold()
        if subject_id and fallback_slot:
            return ("legacy_slot", subject_id, fallback_slot)
        return ("", "", "")

    def resolve_query_subject_ids(self, entities: Sequence[object]) -> List[str]:
        """Resolve explicit Question Frame entities to canonical graph subjects."""
        subject_aliases: DefaultDict[str, set[str]] = defaultdict(set)
        for node in (*self.claims.values(), *self.states.values()):
            subject_id = subject_identity(node)
            if not subject_id:
                continue
            for value in (
                subject_id.replace("_", " "),
                node.get("canonical_subject"),
                node.get("subject"),
            ):
                alias = normalize_entity_reference(value)
                if alias:
                    subject_aliases[alias].add(subject_id)
        resolved: List[str] = []
        for entity in entities:
            matches = subject_aliases.get(normalize_entity_reference(entity), set())
            if len(matches) == 1:
                resolved.extend(matches)
        return ordered_unique(resolved)

    def _claim_matches_query_subjects(self, claim_id: str, query_subject_ids: set[str]) -> bool:
        if not query_subject_ids:
            return True
        subject_id = subject_identity(self.claims.get(claim_id, {}))
        return not subject_id or subject_id in query_subject_ids

    def _state_matches_query_subjects(self, state_id: str, query_subject_ids: set[str]) -> bool:
        if not query_subject_ids:
            return True
        subject_id = subject_identity(self.states.get(state_id, {}))
        return not subject_id or subject_id in query_subject_ids

    def _multi_value_state_siblings(self, state_id: str) -> List[str]:
        state = self.states.get(state_id, {})
        if str(state.get("state_cardinality") or "").strip().lower() != "multi":
            return []
        subject_id = str(state.get("canonical_subject_id") or "").strip().casefold()
        group_id = str(state.get("canonical_state_group_id") or "").strip()
        if not subject_id or not group_id:
            return []
        return [
            sibling_id
            for sibling_id, sibling in self.states.items()
            if sibling_id != state_id
            and str(sibling.get("canonical_subject_id") or "").strip().casefold() == subject_id
            and str(sibling.get("canonical_state_group_id") or "").strip() == group_id
            and str(sibling.get("state_cardinality") or "").strip().lower() == "multi"
            and str(sibling.get("status") or "current").strip().lower() == "current"
        ]

    def _closed_evidence_pack(
        self,
        event_ids: Sequence[str],
        state_ids: Sequence[str],
        *,
        max_state_lines: int = 0,
        candidate_claim_ids: Optional[Sequence[str]] = None,
    ) -> Tuple[List[str], List[str], List[str], List[str], Dict[str, Any]]:
        """Remove graph rows whose supporting source Events were budget-pruned."""
        retained_event_ids = ordered_unique(
            str(event_id) for event_id in event_ids if str(event_id) in self.events
        )
        retained_event_set = set(retained_event_ids)
        candidate_state_ids = ordered_unique(
            str(state_id) for state_id in state_ids if str(state_id) in self.states
        )
        retained_state_ids = [
            state_id
            for state_id in candidate_state_ids
            if self._state_support_is_closed(state_id, retained_event_set)
        ]
        if max_state_lines > 0:
            retained_state_ids = retained_state_ids[:max_state_lines]
        if candidate_claim_ids is None:
            claim_ids = ordered_unique(
                claim_id
                for event_id in retained_event_ids
                for claim_id in self.claims_by_event.get(event_id, [])
                if claim_id in self.claims
            )
        else:
            claim_ids = ordered_unique(
                str(claim_id)
                for claim_id in candidate_claim_ids
                if str(claim_id) in self.claims
                and self._claim_source_event_id(str(claim_id)) in retained_event_set
            )
        claim_ids = ordered_unique(
            [
                *claim_ids,
                *(
                    claim_id
                    for state_id in retained_state_ids
                    for claim_id in self._state_evidence_claim_ids(state_id)
                    if claim_id in self.claims
                    and self._claim_source_event_id(claim_id) in retained_event_set
                ),
            ]
        )
        relation_lines, dropped_relations = self._relation_lines_for_closed_claims(
            claim_ids,
            retained_event_ids,
        )
        return (
            retained_event_ids,
            retained_state_ids,
            claim_ids,
            relation_lines,
            {
                "dropped_state_ids": [
                    state_id for state_id in candidate_state_ids if state_id not in retained_state_ids
                ],
                "dropped_relation_count": dropped_relations,
                "retained_event_ids": retained_event_ids,
                "retained_state_ids": retained_state_ids,
                "retained_claim_ids": claim_ids,
            },
        )

    def _expand_relation_aware(
        self,
        seed_event_ids: Sequence[str],
        *,
        seed_state_ids: Sequence[str] = (),
        max_context_events: int,
        max_state_lines: int,
        retrieval_queries: Sequence[str] = (),
        query_subject_ids: Sequence[str] = (),
        readout_operation: str = "lookup",
    ) -> Tuple[List[str], List[str], List[str], Dict[str, Any]]:
        event_ids: List[str] = []
        state_ids: List[str] = []
        event_reasons: DefaultDict[str, List[str]] = defaultdict(list)
        claim_queue: deque[Tuple[str, str, int, int, float, bool]] = deque()
        queued_claims: set[str] = set()
        visited_claims: List[str] = []
        visited_relation_edges: set[Tuple[str, str, str]] = set()
        relation_lines: List[str] = []
        skipped_relation_claim_ids: List[str] = []
        skipped_relation_edges: List[Dict[str, str]] = []
        max_observed_relation_hops = 0
        state_priority: Dict[str, Dict[str, Any]] = {}
        expanded_group_sibling_ids: List[str] = []
        allowed_subject_ids = {
            str(subject_id).strip().casefold()
            for subject_id in query_subject_ids
            if str(subject_id).strip()
        }
        expand_multi_value_groups = readout_operation in {"enumerate", "count", "intersection"}
        query_terms = {
            term
            for query in retrieval_queries
            for term in tokenized(query)
            if term not in QUERY_STOP_TERMS
        }
        claim_term_document_frequency: Counter[str] = Counter()
        for claim_id in self.claims:
            claim_term_document_frequency.update(self._claim_relevance_terms(claim_id))
        claim_relevance = {
            claim_id: self._claim_query_relevance(
                claim_id,
                query_terms,
                claim_term_document_frequency,
            )
            for claim_id in self.claims
        }

        def add_event(event_id: object, reason: str) -> None:
            identifier = str(event_id or "")
            if identifier not in self.events:
                return
            if identifier not in event_ids:
                event_ids.append(identifier)
            if reason not in event_reasons[identifier]:
                event_reasons[identifier].append(reason)

        def enqueue_claim(
            claim_id: object,
            reason: str,
            *,
            relation_hops: int,
            seed_rank: int,
            relevance: float,
            allow_relations: bool,
        ) -> None:
            identifier = str(claim_id or "")
            if (
                identifier not in self.claims
                or identifier in queued_claims
                or not self._claim_matches_query_subjects(identifier, allowed_subject_ids)
            ):
                return
            queued_claims.add(identifier)
            claim_queue.append(
                (identifier, reason, relation_hops, seed_rank, relevance, allow_relations)
            )

        def add_state(
            state_id: object,
            reason: str,
            *,
            relation_hops: int,
            seed_rank: int,
            relevance: float,
            expand_group: bool = True,
        ) -> None:
            identifier = str(state_id or "")
            state = self.states.get(identifier)
            if not state or not self._state_matches_query_subjects(identifier, allowed_subject_ids):
                return
            if identifier not in state_ids:
                state_ids.append(identifier)
            priority_score = (
                1.0 / (1.0 + 0.25 * max(seed_rank - 1, 0))
                + 0.75 * relevance
                - 0.25 * relation_hops
            )
            current_priority = state_priority.get(identifier)
            if current_priority is None or priority_score > float(current_priority["score"]):
                state_priority[identifier] = {
                    "score": round(priority_score, 6),
                    "seed_rank": seed_rank,
                    "relation_hops": relation_hops,
                    "claim_relevance": round(relevance, 6),
                    "reason": reason,
                }
            for event_id in self._state_required_event_ids(identifier):
                add_event(event_id, f"{reason}; StateFacet required_event")
            for support_claim_id in self._state_evidence_claim_ids(identifier):
                enqueue_claim(
                    support_claim_id,
                    f"{reason}; StateFacet primary_or_relation_witness",
                    relation_hops=relation_hops,
                    seed_rank=seed_rank,
                    relevance=max(relevance, claim_relevance.get(support_claim_id, 0.0)),
                    allow_relations=True,
                )
            if expand_group and expand_multi_value_groups:
                for sibling_id in self._multi_value_state_siblings(identifier):
                    if (
                        sibling_id in state_ids
                        or not self._state_matches_query_subjects(sibling_id, allowed_subject_ids)
                    ):
                        continue
                    expanded_group_sibling_ids.append(sibling_id)
                    sibling_relevance = max(
                        (
                            claim_relevance.get(str(claim_id), 0.0)
                            for claim_id in self.states[sibling_id].get("support_claim_ids", []) or []
                        ),
                        default=0.0,
                    )
                    add_state(
                        sibling_id,
                        f"{reason}; same multi-value state group",
                        relation_hops=relation_hops,
                        seed_rank=seed_rank,
                        relevance=max(relevance, sibling_relevance),
                        expand_group=False,
                    )

        for rank, state_id in enumerate(seed_state_ids, start=1):
            add_state(
                state_id,
                f"seed_state_rank={rank}",
                relation_hops=0,
                seed_rank=rank,
                relevance=1.0 / rank,
            )

        for rank, event_id in enumerate(seed_event_ids, start=1):
            add_event(event_id, f"seed_event_rank={rank}")
            event_claim_ids = [
                claim_id
                for claim_id in self.claims_by_event.get(str(event_id), [])
                if claim_id in self.claims
            ]
            best_relevance = max(
                (claim_relevance.get(claim_id, 0.0) for claim_id in event_claim_ids),
                default=0.0,
            )
            best_claim_ids = {
                claim_id
                for claim_id in event_claim_ids
                if math.isclose(claim_relevance.get(claim_id, 0.0), best_relevance)
            }
            best_state_group_ids = {
                self._claim_relation_continuity_key(claim_id)
                for claim_id in best_claim_ids
                if self._claim_relation_continuity_key(claim_id)[0]
            }
            for claim_id in event_claim_ids:
                relevance = claim_relevance.get(claim_id, 0.0)
                claim_state_group_id = self._claim_relation_continuity_key(claim_id)
                allow_relations = (
                    not query_terms
                    or best_relevance <= 0.0
                    or claim_id in best_claim_ids
                    or (
                        claim_state_group_id[0]
                        and claim_state_group_id in best_state_group_ids
                    )
                )
                enqueue_claim(
                    claim_id,
                    f"seed_event_rank={rank}; ASSERTS",
                    relation_hops=0,
                    seed_rank=rank,
                    relevance=relevance,
                    allow_relations=allow_relations,
                )
        while claim_queue:
            claim_id, reason, relation_hops, seed_rank, relevance, allow_relations = claim_queue.popleft()
            max_observed_relation_hops = max(max_observed_relation_hops, relation_hops)
            visited_claims.append(claim_id)
            claim = self.claims[claim_id]
            add_event(claim.get("source_event_id"), f"{reason}; claim source_event")
            for state_id in self.states_by_claim.get(claim_id, []):
                add_state(
                    state_id,
                    f"{reason}; SUPPORTS",
                    relation_hops=relation_hops,
                    seed_rank=seed_rank,
                    relevance=relevance,
                )
            if not allow_relations:
                if self.relations_by_claim.get(claim_id):
                    skipped_relation_claim_ids.append(claim_id)
                continue
            claim_continuity_key = self._claim_relation_continuity_key(claim_id)
            for edge in self.relations_by_claim.get(claim_id, []):
                edge_key = (
                    str(edge.get("type") or ""),
                    str(edge.get("from") or ""),
                    str(edge.get("to") or ""),
                )
                if edge_key in visited_relation_edges:
                    continue
                source = str(edge.get("from") or "")
                target = str(edge.get("to") or "")
                related_claim_id = target if source == claim_id else source
                related_continuity_key = self._claim_relation_continuity_key(related_claim_id)
                keyed_continuity = bool(claim_continuity_key[0] and related_continuity_key[0])
                if (
                    bool(claim_continuity_key[0]) != bool(related_continuity_key[0])
                    or (keyed_continuity and claim_continuity_key != related_continuity_key)
                ):
                    skipped_relation_edges.append(
                        {
                            "type": str(edge.get("type") or ""),
                            "from": source,
                            "to": target,
                            "reason": "relation_continuity_mismatch",
                        }
                    )
                    continue
                visited_relation_edges.add(edge_key)
                relation_lines.append(self._format_relation_edge(edge))
                related_relevance = claim_relevance.get(related_claim_id, 0.0)
                enqueue_claim(
                    related_claim_id,
                    f"{reason}; {edge.get('type')} related_claim",
                    relation_hops=relation_hops + 1,
                    seed_rank=seed_rank,
                    relevance=max(relevance * 0.7, related_relevance),
                    allow_relations=keyed_continuity,
                )
                for event_id in edge.get("evidence_event_ids", []) or []:
                    add_event(event_id, f"{reason}; {edge.get('type')} evidence_event")

        state_discovery_order = {state_id: index for index, state_id in enumerate(state_ids)}
        state_ids.sort(
            key=lambda state_id: (
                -float(state_priority.get(state_id, {}).get("score", 0.0)),
                state_discovery_order[state_id],
            )
        )
        if max_context_events > 0:
            event_ids = event_ids[:max_context_events]
        event_ids, state_ids, _claim_ids, relation_lines, closure_trace = self._closed_evidence_pack(
            event_ids,
            state_ids,
            max_state_lines=max_state_lines,
            candidate_claim_ids=visited_claims,
        )
        return (
            event_ids,
            state_ids,
            relation_lines,
            {
                "mode": "relation-aware",
                "seed_event_ids": list(seed_event_ids),
                "seed_state_ids": list(seed_state_ids),
                "expanded_event_ids": event_ids,
                "selected_state_ids": state_ids,
                "visited_claim_ids": visited_claims,
                "relation_edge_count": len(visited_relation_edges),
                "relation_expansion_strategy": "query-anchored-state-group-closure",
                "query_subject_ids": sorted(allowed_subject_ids),
                "readout_operation": readout_operation,
                "expanded_group_sibling_ids": ordered_unique(expanded_group_sibling_ids),
                "max_observed_relation_hops": max_observed_relation_hops,
                "skipped_relation_claim_ids": ordered_unique(skipped_relation_claim_ids),
                "skipped_relation_edges": skipped_relation_edges,
                "state_priority": {
                    state_id: state_priority[state_id]
                    for state_id in state_ids
                    if state_id in state_priority
                },
                "event_reasons": {event_id: event_reasons[event_id] for event_id in event_ids},
                "evidence_closure": closure_trace,
            },
        )

    def _expand_scope_coverage(
        self,
        seed_event_ids: Sequence[str],
        *,
        event_candidate_rows: Sequence[Mapping[str, Any]],
        max_context_events: int,
        max_state_lines: int,
        retrieval_queries: Sequence[str] = (),
    ) -> Tuple[List[str], List[str], List[str], Dict[str, Any]]:
        """Add question-ranked, non-redundant Event neighbors from the seed Scopes.

        This is a query-time ablation. It does not retrieve StateFacets directly and
        does not introduce task labels or corpus-specific rules. Existing relation
        expansion remains intact; remaining Event budget is filled with standard MMR
        over the already retrieved BM25/embedding Event candidate pool.
        """
        relation_event_ids, _relation_state_ids, relation_lines, relation_trace = self._expand_relation_aware(
            seed_event_ids,
            max_context_events=0,
            max_state_lines=0,
            retrieval_queries=retrieval_queries,
        )
        event_ids = ordered_unique(relation_event_ids)
        if max_context_events > 0:
            event_ids = event_ids[:max_context_events]

        seed_scope_ids = {
            scope_id
            for event_id in seed_event_ids
            for scope_id in self.scopes_by_event.get(str(event_id), [])
        }
        ranked_candidates: List[Tuple[str, int, float]] = []
        for rank, row in enumerate(event_candidate_rows, start=1):
            doc_id = str(row.get("doc_id") or "")
            if not doc_id.startswith("event::"):
                continue
            event_id = doc_id[len("event::") :]
            if event_id in event_ids or event_id not in self.events:
                continue
            if seed_scope_ids and not seed_scope_ids.intersection(self.scopes_by_event.get(event_id, [])):
                continue
            ranked_candidates.append((event_id, rank, float(row.get("score") or 0.0)))

        candidate_count = len(ranked_candidates)
        candidate_scores = [score for _event_id, _rank, score in ranked_candidates]
        min_candidate_score = min(candidate_scores, default=0.0)
        max_candidate_score = max(candidate_scores, default=0.0)
        token_cache: Dict[str, set[str]] = {}

        def event_tokens(event_id: str) -> set[str]:
            if event_id not in token_cache:
                token_cache[event_id] = set(tokenized(self._enhanced_event_document(event_id, self.events[event_id])))
            return token_cache[event_id]

        def novelty(event_id: str) -> float:
            tokens = event_tokens(event_id)
            if not tokens or not event_ids:
                return 1.0
            max_similarity = 0.0
            for selected_event_id in event_ids:
                selected_tokens = event_tokens(selected_event_id)
                union = tokens | selected_tokens
                similarity = len(tokens & selected_tokens) / len(union) if union else 0.0
                max_similarity = max(max_similarity, similarity)
            return 1.0 - max_similarity

        selected_neighbors: List[Dict[str, Any]] = []
        remaining = list(ranked_candidates)
        while remaining and (max_context_events <= 0 or len(event_ids) < max_context_events):
            scored: List[Tuple[float, float, float, int, str]] = []
            for event_id, rank, raw_score in remaining:
                relevance = (
                    1.0
                    if max_candidate_score <= min_candidate_score
                    else (raw_score - min_candidate_score) / (max_candidate_score - min_candidate_score)
                )
                coverage = novelty(event_id)
                mmr_score = 0.7 * relevance + 0.3 * coverage
                scored.append((mmr_score, relevance, coverage, rank, event_id))
            mmr_score, relevance, coverage, rank, selected_event_id = max(
                scored,
                key=lambda item: (item[0], item[1], item[2], -item[3], item[4]),
            )
            event_ids.append(selected_event_id)
            selected_neighbors.append(
                {
                    "event_id": selected_event_id,
                    "candidate_rank": rank,
                    "relevance": round(relevance, 6),
                    "coverage_novelty": round(coverage, 6),
                    "mmr_score": round(mmr_score, 6),
                }
            )
            remaining = [
                (event_id, item_rank, raw_score)
                for event_id, item_rank, raw_score in remaining
                if event_id != selected_event_id
            ]

        states_per_event: List[List[str]] = []
        for event_id in event_ids:
            states_per_event.append(
                ordered_unique(
                    state_id
                    for claim_id in self.claims_by_event.get(event_id, [])
                    for state_id in self.states_by_claim.get(claim_id, [])
                    if state_id in self.states
                )
            )
        state_ids: List[str] = []
        depth = 0
        while any(depth < len(items) for items in states_per_event):
            for items in states_per_event:
                if depth < len(items):
                    state_ids.append(items[depth])
            state_ids = ordered_unique(state_ids)
            depth += 1

        visited_claim_ids = ordered_unique(
            [
                *relation_trace.get("visited_claim_ids", []),
                *(
                    claim_id
                    for event_id in event_ids
                    for claim_id in self.claims_by_event.get(event_id, [])
                    if claim_id in self.claims
                ),
            ]
        )
        event_ids, state_ids, _claim_ids, relation_lines, closure_trace = self._closed_evidence_pack(
            event_ids,
            state_ids,
            max_state_lines=max_state_lines,
            candidate_claim_ids=visited_claim_ids,
        )

        trace = {
            **relation_trace,
            "mode": "scope-coverage",
            "relation_expanded_event_ids": relation_event_ids,
            "scope_neighbor_candidate_count": candidate_count,
            "selected_scope_neighbors": selected_neighbors,
            "expanded_event_ids": event_ids,
            "selected_state_ids": state_ids,
            "visited_claim_ids": visited_claim_ids,
            "state_selection": "event-rank-round-robin",
            "mmr_relevance_weight": 0.7,
            "mmr_coverage_weight": 0.3,
            "evidence_closure": closure_trace,
        }
        return event_ids, state_ids, relation_lines, trace

    def _event_doc_ids_for_scopes(self, scope_ids: Sequence[str]) -> List[str]:
        event_ids: List[str] = []
        for scope_id in scope_ids:
            event_ids.extend(self.events_by_scope.get(scope_id, []))
        return [f"event::{event_id}" for event_id in ordered_unique(event_ids)]

    def _format_relation_edge(self, edge: Mapping[str, Any]) -> str:
        source = self.claims.get(str(edge.get("from") or ""), {})
        target = self.claims.get(str(edge.get("to") or ""), {})
        return (
            f"{edge.get('type')}: {claim_summary(source)} -> {claim_summary(target)} "
            f"reason={edge.get('reason', '')}"
        )

    def finalize_temporal_readout(
        self,
        retrieval: RetrievalResult,
        *,
        include_state: bool = True,
    ) -> RetrievalResult:
        direct_delivery = (
            retrieval.trace.get("evidence_delivery", {}).get("mode")
            == "direct_graph_expansion"
        )
        requested_time_roles = retrieval.trace.get("time_role_selection", {}).get("time_roles", [])
        temporal_rows = self._legacy_temporal_grounding_rows(
            final_answer_event_ids(retrieval),
            requested_time_roles,
            include_state=include_state,
        )
        mode = "query_time_grounding"
        recalculates_time = True
        input_boundary = [
            "expanded_events" if direct_delivery else "ledger_selected_events",
            "event_text",
            "source_event_timestamp",
        ]
        trace = dict(retrieval.trace)
        pipeline_order = list(trace.get("pipeline_order", []))
        pipeline_order.append("temporal_readout")
        trace["pipeline_order"] = pipeline_order
        trace["temporal_readout"] = {
            "mode": mode,
            "input_boundary": input_boundary,
            "uses_task_labels": False,
            "uses_gold": False,
            "recalculates_time": recalculates_time,
            "state_time_features_enabled": include_state,
            "rows": temporal_rows,
        }
        return RetrievalResult(
            candidate_dialog_ids=list(retrieval.candidate_dialog_ids),
            temporal_lines=[format_temporal_grounding(row, include_resolved=True) for row in temporal_rows],
            claim_lines=list(retrieval.claim_lines),
            state_lines=list(retrieval.state_lines),
            relation_lines=list(retrieval.relation_lines),
            context=retrieval.context,
            trace=trace,
        )

    def apply_evidence_ledger(
        self,
        retrieval: RetrievalResult,
        ledger: Mapping[str, Any],
        *,
        max_claims: int,
        max_states: int,
        max_events: int,
        fallback_events: int,
        attempt: int = 1,
        fallback_on_failure: bool = False,
        accept_partial: bool = False,
        fill_ranked_events: bool = False,
        selection_source: str = "llm_ordered_evidence_units",
        pipeline_stage: str = "claim_evidence_ledger",
    ) -> RetrievalResult:
        claim_limit, state_limit, event_limit, fallback_limit = validate_evidence_ledger_budgets(
            max_claims,
            max_states,
            max_events,
            fallback_events,
        )
        candidate_event_set = set(retrieval.candidate_dialog_ids)
        candidate_claim_set = set(retrieval.trace.get("expanded_claim_ids", []))
        requested_units = [
            dict(unit)
            for unit in ledger.get("selected_units", [])
            if isinstance(unit, Mapping)
        ]
        invalid_requested_units = ordered_unique(
            str(item)
            for item in ledger.get("invalid_requested_units", [])
            if str(item)
        )

        def proof_pack(units: Sequence[Mapping[str, str]]) -> Dict[str, Any]:
            claim_ids: List[str] = []
            state_ids: List[str] = []
            missing_claim_ids: List[str] = []
            for unit in units:
                kind = str(unit.get("kind") or "")
                identifier = str(unit.get("id") or "")
                if kind == "claim":
                    claim_ids.append(identifier)
                elif kind == "state_facet":
                    state_ids.append(identifier)
                    for claim_id in self._state_evidence_claim_ids(identifier):
                        claim_ids.append(claim_id)
                        if claim_id not in self.claims or claim_id not in candidate_claim_set:
                            missing_claim_ids.append(claim_id)
            claim_ids = ordered_unique(
                claim_id
                for claim_id in claim_ids
                if claim_id in self.claims and claim_id in candidate_claim_set
            )
            state_ids = ordered_unique(state_id for state_id in state_ids if state_id in self.states)
            event_ids: List[str] = []
            for claim_id in claim_ids:
                source_event_id = self._claim_source_event_id(claim_id)
                if source_event_id:
                    event_ids.append(source_event_id)
                else:
                    missing_claim_ids.append(claim_id)
            event_ids = ordered_unique(event_ids)
            for state_id in state_ids:
                event_ids.extend(self._state_required_event_ids(state_id))
            event_ids = ordered_unique(event_ids)
            claim_set = set(claim_ids)
            seen_relations: set[Tuple[str, str, str]] = set()
            for claim_id in claim_ids:
                for edge in self.relations_by_claim.get(claim_id, []):
                    edge_key = (
                        str(edge.get("type") or ""),
                        str(edge.get("from") or ""),
                        str(edge.get("to") or ""),
                    )
                    if edge_key in seen_relations:
                        continue
                    seen_relations.add(edge_key)
                    if edge_key[1] in claim_set and edge_key[2] in claim_set:
                        event_ids.extend(
                            str(event_id)
                            for event_id in edge.get("evidence_event_ids", []) or []
                            if str(event_id)
                        )
            event_ids = ordered_unique(event_ids)
            missing_event_ids = [event_id for event_id in event_ids if event_id not in candidate_event_set]
            return {
                "claim_ids": claim_ids,
                "state_ids": state_ids,
                "event_ids": event_ids,
                "missing_claim_ids": ordered_unique(missing_claim_ids),
                "missing_event_ids": missing_event_ids,
            }

        accepted_units: List[Dict[str, str]] = []
        rejected_units: List[Dict[str, Any]] = []
        for unit in requested_units:
            prospective_units = [*accepted_units, dict(unit)]
            prospective_pack = proof_pack(prospective_units)
            over_budget = {
                "claims": max(0, len(prospective_pack["claim_ids"]) - claim_limit),
                "state_facets": max(0, len(prospective_pack["state_ids"]) - state_limit),
                "events": max(0, len(prospective_pack["event_ids"]) - event_limit),
            }
            if (
                prospective_pack["missing_claim_ids"]
                or prospective_pack["missing_event_ids"]
                or any(over_budget.values())
            ):
                rejected_units.append(
                    {
                        **dict(unit),
                        "over_budget": over_budget,
                        "missing_claim_ids": prospective_pack["missing_claim_ids"],
                        "missing_event_ids": prospective_pack["missing_event_ids"],
                    }
                )
                continue
            accepted_units.append(dict(unit))

        if accept_partial:
            selection_valid = not invalid_requested_units and bool(
                accepted_units or (fill_ranked_events and retrieval.candidate_dialog_ids)
            )
        else:
            selection_valid = bool(requested_units) and not invalid_requested_units and not rejected_units
        selected_pack = proof_pack(accepted_units) if selection_valid else {
            "claim_ids": [],
            "state_ids": [],
            "event_ids": [],
            "missing_claim_ids": [],
            "missing_event_ids": [],
        }
        fallback_applied = bool(not selection_valid and fallback_on_failure)
        if fallback_applied:
            selected_event_ids = ordered_unique(retrieval.candidate_dialog_ids[:fallback_limit])[:event_limit]
            selection_status = "fallback_unresolved"
        elif selection_valid:
            selected_event_ids = list(selected_pack["event_ids"])
            if fill_ranked_events:
                selected_event_ids = ordered_unique(
                    [*selected_event_ids, *retrieval.candidate_dialog_ids]
                )[:event_limit]
            selection_status = "deterministic_budgeted" if accept_partial else "valid"
        else:
            selected_event_ids = []
            selection_status = "deterministic_empty" if accept_partial else "repair_required"
        selected_claim_ids = list(selected_pack["claim_ids"]) if selection_valid else []
        selected_state_ids = list(selected_pack["state_ids"]) if selection_valid else []
        relation_lines, dropped_relation_count = self._relation_lines_for_closed_claims(
            selected_claim_ids,
            selected_event_ids,
        )
        trace = dict(retrieval.trace)
        trace["pipeline_order"] = list(trace.get("pipeline_order", [])) + [pipeline_stage]
        trace["evidence_ledger"] = {
            "uses_task_labels": False,
            "uses_gold": False,
            "input_boundary": ["question", "closed_expanded_graph_evidence"],
            "selected_claim_ids": selected_claim_ids,
            "selected_state_ids": selected_state_ids,
            "selected_event_ids": selected_event_ids,
            "requested_units": requested_units,
            "accepted_units": accepted_units,
            "rejected_units": rejected_units,
            "invalid_requested_units": invalid_requested_units,
            "dropped_relation_count": dropped_relation_count,
            "fixed_budgets": {
                "claims": claim_limit,
                "state_facets": state_limit,
                "events": event_limit,
                "fallback_events": fallback_limit,
            },
            "selection_source": selection_source,
            "selection_status": selection_status,
            "repair_required": not selection_valid and not accept_partial,
            "attempt": attempt,
            "fallback_applied": fallback_applied,
            "raw": ledger.get("raw", {}),
        }
        return RetrievalResult(
            candidate_dialog_ids=list(retrieval.candidate_dialog_ids),
            temporal_lines=list(retrieval.temporal_lines),
            claim_lines=[format_claim_line(self.claims[claim_id]) for claim_id in selected_claim_ids],
            state_lines=[format_state_line(self.states[state_id]) for state_id in selected_state_ids],
            relation_lines=relation_lines,
            context=self._context_text(selected_event_ids),
            trace=trace,
        )

    def apply_deterministic_evidence_budget(
        self,
        retrieval: RetrievalResult,
        *,
        max_claims: int,
        max_states: int,
        max_events: int,
        fallback_events: int,
    ) -> RetrievalResult:
        """Budget graph-expanded evidence without an LLM selector or handle protocol."""
        candidate_claim_ids = ordered_unique(
            str(claim_id)
            for claim_id in retrieval.trace.get("expanded_claim_ids", [])
            if str(claim_id) in self.claims
        )
        candidate_state_ids = ordered_unique(
            str(state_id)
            for state_id in retrieval.trace.get("selected_state_ids", [])
            if str(state_id) in self.states
        )
        candidate_claim_set = set(candidate_claim_ids)
        candidate_state_set = set(candidate_state_ids)
        units: List[Dict[str, str]] = []
        seen_units: set[Tuple[str, str]] = set()

        def add_unit(kind: str, identifier: str) -> None:
            key = (kind, identifier)
            if identifier and key not in seen_units:
                seen_units.add(key)
                units.append({"kind": kind, "id": identifier})

        for event_id in retrieval.candidate_dialog_ids:
            for claim_id in self.claims_by_event.get(str(event_id), []):
                if claim_id not in candidate_claim_set:
                    continue
                add_unit("claim", claim_id)
                for state_id in self.states_by_claim.get(claim_id, []):
                    if state_id in candidate_state_set:
                        add_unit("state_facet", state_id)
        for state_id in candidate_state_ids:
            add_unit("state_facet", state_id)
        for claim_id in candidate_claim_ids:
            add_unit("claim", claim_id)

        return self.apply_evidence_ledger(
            retrieval,
            {
                "selected_units": units,
                "invalid_requested_units": [],
                "raw": {"strategy": "event_rank_then_graph_order"},
            },
            max_claims=max_claims,
            max_states=max_states,
            max_events=max_events,
            fallback_events=fallback_events,
            attempt=0,
            fallback_on_failure=False,
            accept_partial=True,
            fill_ranked_events=True,
            selection_source="deterministic_ranked_graph_units",
            pipeline_stage="deterministic_evidence_budget",
        )


    def _legacy_temporal_grounding_rows(
        self,
        event_ids: Sequence[str],
        requested_time_roles: Sequence[str],
        *,
        include_state: bool = True,
    ) -> List[Dict[str, Any]]:
        requested_roles = {str(role) for role in requested_time_roles if role}
        rows: List[Dict[str, Any]] = []
        seen = set()
        for event_rank, event_id in enumerate(event_ids, start=1):
            event = self.events.get(event_id, {})
            anchor_value = event.get("occurred_at")
            profile = self._event_time_profile(event_id, include_state=include_state)
            matched_roles = [role for role in profile["time_roles"] if role in requested_roles]
            event_role = matched_roles[0] if matched_roles else "occurred_at"
            event_text = " ".join(
                str(event.get(key) or "")
                for key in ("text", "image_caption", "image_query")
            )
            sources: List[Tuple[str, object, str, str, Optional[str]]] = [
                (event_text, anchor_value, "event_text", event_role, None)
            ]
            for claim_id in self.claims_by_event.get(event_id, []):
                claim = self.claims.get(claim_id, {})
                time_value = str(claim.get("time_value") or "").strip()
                if not time_value:
                    continue
                sources.append(
                    (
                        time_value,
                        claim.get("time_anchor") or anchor_value,
                        "claim_time_value",
                        str(claim.get("time_role") or event_role),
                        claim_id,
                    )
                )
            for source_text, source_anchor, source_kind, time_role, claim_id in sources:
                for grounding in ground_temporal_expressions(source_text, source_anchor):
                    key = (
                        event_id,
                        str(grounding.get("expression") or "").lower(),
                        grounding.get("anchor_date"),
                        grounding.get("normalized_value"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    row = dict(grounding)
                    row.update(
                        {
                            "event_id": event_id,
                            "event_rank": event_rank,
                            "time_role": time_role,
                            "source": source_kind,
                            "claim_id": claim_id,
                        }
                    )
                    rows.append(row)
        return rows

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


def default_query_graph_dir(sample_id: str) -> Path:
    normalized_sample_id = str(sample_id or "").strip()
    if not normalized_sample_id:
        raise ValueError("sample_id must not be empty")
    return EXTERNAL_GRAPH_DIR / "locomo_qa_sample_graph_v2_state_merge" / safe_part(normalized_sample_id)


def default_query_output_path(
    sample_id: str,
    *,
    provider: str,
    model: str,
    variants: Sequence[str],
    run_config: Optional[Mapping[str, Any]] = None,
) -> Path:
    normalized_sample_id = str(sample_id or "").strip()
    normalized_provider = str(provider or "").strip()
    normalized_model = str(model or "").strip()
    normalized_variants = [str(variant).strip() for variant in variants if str(variant).strip()]
    if not normalized_sample_id:
        raise ValueError("sample_id must not be empty")
    if not normalized_provider or not normalized_model or not normalized_variants:
        raise ValueError("default output path requires provider, model, and at least one variant")
    output_slug = re.sub(r"[^A-Za-z0-9]+", "", normalized_sample_id) or safe_part(normalized_sample_id)
    variant_slug = safe_part("__".join(normalized_variants))
    config_fingerprint = short_hash(
        json.dumps(
            {
                "sample_id": normalized_sample_id,
                "provider": normalized_provider,
                "model": normalized_model,
                "variants": normalized_variants,
                "run_config": dict(run_config or {}),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    )
    return (
        EXTERNAL_RESULT_DIR
        / "locomo_qa"
        / "ours_scope_time_state"
        / (
            f"results_locomo_qa_graph_{output_slug}_{variant_slug}_"
            f"{safe_part(normalized_provider)}_{safe_part(normalized_model)}_cfg{config_fingerprint}.json"
        )
    )


def validate_graph_sample_id(graph: GraphEvidenceIndex, requested_sample_id: str) -> None:
    manifest_sample_id = str(graph.manifest.get("sample_id") or "").strip()
    if not manifest_sample_id:
        raise ValueError("graph manifest is missing sample_id")
    if manifest_sample_id != str(requested_sample_id):
        raise ValueError(
            f"graph/sample mismatch: manifest sample_id={manifest_sample_id!r}, "
            f"requested sample_id={requested_sample_id!r}"
        )


def positive_int_argument(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def nonnegative_int_argument(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def validate_evidence_ledger_budgets(
    max_claims: int,
    max_states: int,
    max_events: int,
    fallback_events: int,
) -> Tuple[int, int, int, int]:
    claim_limit = int(max_claims)
    state_limit = int(max_states)
    event_limit = int(max_events)
    fallback_limit = int(fallback_events)
    if claim_limit <= 0:
        raise ValueError("max_claims must be greater than zero")
    if state_limit <= 0:
        raise ValueError("max_states must be greater than zero")
    if event_limit <= 0:
        raise ValueError("max_events must be greater than zero")
    if fallback_limit < 0:
        raise ValueError("fallback_events must not be negative")
    if fallback_limit > event_limit:
        raise ValueError("fallback_events must not exceed max_events")
    return claim_limit, state_limit, event_limit, fallback_limit


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LoCoMo questions against a sample-level STS graph.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument(
        "--graph-dir",
        default=None,
        help="Graph directory. By default it is derived from --sample-id.",
    )
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["graph_embedding_scope_event"],
        choices=SUPPORTED_VARIANTS,
    )
    parser.add_argument(
        "--retrieval-policy",
        choices=RETRIEVAL_POLICIES,
        default="sts",
        help=(
            "Independent query-time ablation: event-rag disables Scope/Time/State; scope-event adds Scope; "
            "scope-event-time adds question-only Time reranking; sts enables the full Claim/State graph path."
        ),
    )
    parser.add_argument(
        "--question-types",
        nargs="+",
        default=[],
        help="Optional task filter, e.g. multi-hop open-domain.",
    )
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--scope-top-k", type=int, default=10)
    parser.add_argument(
        "--scope-backoff-k",
        type=int,
        default=0,
        help="Optional sample-wide recall ablation; 0 keeps the default chain strictly inside routed Scopes.",
    )
    parser.add_argument(
        "--scope-types",
        default="speaker,entity,topic",
        help="Semantic Scope types to enable from speaker,entity,topic; Session remains graph provenance only.",
    )
    parser.add_argument(
        "--scope-anchor-routing",
        choices=("off", "reserve"),
        default="off",
        help=(
            "Ablation switch: reserve keeps exact question-mentioned participant Speaker/Entity Scopes in the fixed "
            "Scope top-k before filling remaining positions with the normal semantic ranking."
        ),
    )
    parser.add_argument("--candidate-k", type=int, default=80)
    parser.add_argument("--embedding-candidate-k", type=int, default=80)
    parser.add_argument("--max-context-events", type=int, default=24)
    parser.add_argument("--max-state-lines", type=int, default=8)
    parser.add_argument("--max-ledger-claims", type=positive_int_argument, default=12)
    parser.add_argument("--max-ledger-states", type=positive_int_argument, default=8)
    parser.add_argument("--max-ledger-events", type=positive_int_argument, default=8)
    parser.add_argument(
        "--evidence-selector",
        choices=("llm-ledger", "deterministic", "direct"),
        default="llm-ledger",
        help=(
            "llm-ledger uses one constrained LLM selection plus one repair; deterministic skips both calls and "
            "greedily budgets graph-ranked proof bundles; direct passes graph expansion straight to QA without "
            "selection, repacking, repair, fallback, or Ledger budgets."
        ),
    )
    parser.add_argument(
        "--binding-gate",
        choices=("off", "participant"),
        default="off",
        help=(
            "Answer-verification ablation: participant rejects a non-abstaining answer only when its cited graph "
            "Claims belong exclusively to conversation participants different from those named by the question."
        ),
    )
    parser.add_argument(
        "--ledger-fallback-events",
        type=nonnegative_int_argument,
        default=2,
        help="Top-ranked Events retained only when both the initial Ledger selection and its single repair fail.",
    )
    parser.add_argument(
        "--time-role-selector",
        choices=("llm", "llm-compatible", "none"),
        default="llm",
        help=(
            "Question-only Time routing; llm-compatible separately requests primary and compatible evidence roles."
        ),
    )
    parser.add_argument(
        "--event-time-routing",
        choices=("rerank", "prefilter"),
        default="rerank",
        help=(
            "rerank preserves the full scoped candidate pool; prefilter uses question-selected time roles to restrict scoped Events "
            "before BM25 and embedding, while zero selected roles keep all scoped Events."
        ),
    )
    parser.add_argument(
        "--graph-expansion",
        choices=GRAPH_EXPANSIONS,
        default="auto",
        help=(
            "auto keeps v1 on legacy expansion and enables relation-aware expansion for v2 graphs; "
            "scope-coverage is an explicit query-time MMR ablation over Event neighbors in the seed Scopes."
        ),
    )
    parser.add_argument("--answer-workers", type=int, default=4)
    parser.add_argument("--cache", default=str(EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_graph_query.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--embedding-cache", default=str(EXTERNAL_CACHE_DIR / "embedding_cache.locomo_qa_graph_query.json"))
    parser.add_argument("--embedding-base-url", default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", ""))
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument(
        "--event-state-enrichment",
        action="store_true",
        help=(
            "Ablation: append each Event's linked StateFacet subject/facet/value to the Event retrieval document; "
            "this does not add an independent StateFacet retrieval lane."
        ),
    )
    parser.add_argument(
        "--evidence-citation-source",
        choices=("answer", "answer-ledger"),
        default="answer",
        help=(
            "answer reports only valid citations emitted by the answer; answer-ledger also propagates the Ledger's explicit, candidate-whitelisted "
            "Event IDs into final evidence provenance without changing retrieval or answer text."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Result JSON path. By default its filename is derived from sample, variants, provider, resolved model, "
            "and a semantic run-config fingerprint."
        ),
    )
    args = parser.parse_args(argv)
    try:
        validate_evidence_ledger_budgets(
            args.max_ledger_claims,
            args.max_ledger_states,
            args.max_ledger_events,
            args.ledger_fallback_events,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return args


def tokenized(text: object) -> List[str]:
    return [canonical_term(term) for term in TOKEN_RE.findall(str(text or "").lower())]


def normalize_entity_reference(value: object) -> str:
    return " ".join(tokenized(value))


def normalize_participant_reference(value: object) -> str:
    return normalize_entity_reference(
        str(value or "").replace("’s", " ").replace("'s", " ")
    )


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


def scope_document(scope: Mapping[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            scope.get("scope_type"),
            scope.get("label"),
            scope.get("value"),
        )
    )


def state_document(state: Mapping[str, Any]) -> str:
    """Index only resolved StateFacet semantics, never source Claim/Event prose."""
    return " ".join(
        str(part or "")
        for part in (
            state.get("canonical_subject"),
            state.get("subject"),
            state.get("state_domain"),
            state.get("state_target"),
            state.get("state_dimension"),
            state.get("facet_key"),
            state.get("slot_type"),
            state.get("value"),
            state.get("status"),
            state.get("summary"),
            state.get("graph_text"),
        )
    )


def parse_scope_types(value: str) -> List[str]:
    requested = [item.strip() for item in str(value or "").split(",") if item.strip()]
    allowed = set(SEMANTIC_SCOPE_TYPES)
    return [item for item in requested if item in allowed]


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
    if variant == "graph_embedding_scope_statefacet":
        return {"scope", "state"}
    raise ValueError(f"unsupported variant={variant}")


def embedding_targets_for_policy(variant: str, retrieval_policy: str) -> set[str]:
    if retrieval_policy not in RETRIEVAL_POLICIES:
        raise ValueError(f"unsupported retrieval_policy={retrieval_policy}")
    targets = embedding_targets_for_variant(variant)
    if retrieval_policy == "event-rag":
        return targets.intersection({"event"})
    if retrieval_policy in {"scope-event", "scope-event-time"}:
        if variant == "graph_embedding_scope_statefacet":
            raise ValueError(
                "graph_embedding_scope_statefacet is available only for retrieval_policy=sts"
            )
        return targets.intersection({"scope", "event"})
    return targets


def embedding_targets_for_run(
    variants: Sequence[str],
    retrieval_policy: str = "sts",
) -> set[str]:
    targets: set[str] = set()
    for variant in variants:
        targets.update(embedding_targets_for_policy(variant, retrieval_policy))
    return targets


def disabled_time_role_selection(configured_selector: str) -> Dict[str, Any]:
    return {
        "time_applicable": False,
        "time_roles": [],
        "primary_roles": [],
        "compatible_roles": [],
        "ordering": "",
        "source": "disabled_by_retrieval_policy",
        "reason": "Time routing is disabled for this retrieval-policy ablation.",
        "configured_selector": configured_selector,
        "uses_task_labels": False,
        "uses_gold": False,
    }


def format_state_line(state: Mapping[str, Any]) -> str:
    support_claim_ids = [str(item) for item in state.get("support_claim_ids", []) or [] if str(item)]
    support_event_ids = [str(item) for item in state.get("support_event_ids", []) or [] if str(item)]
    primary_claim_id = str(state.get("primary_claim_id") or "")
    primary_event_id = ""
    if primary_claim_id in support_claim_ids:
        primary_index = support_claim_ids.index(primary_claim_id)
        if primary_index < len(support_event_ids):
            primary_event_id = support_event_ids[primary_index]
    metadata = [
        ("subject_key", state.get("subject_key") or state.get("canonical_subject_id")),
        ("dimension", state.get("state_dimension") or state.get("canonical_state_group_id")),
        ("domain", state.get("state_domain")),
        ("target", state.get("state_target")),
        ("slot_type", state.get("slot_type") or state.get("state_cardinality")),
        ("status", state.get("status")),
        ("primary_claim", primary_claim_id),
        ("primary_event", primary_event_id),
        ("support_count", len(support_claim_ids)),
        ("object", state.get("state_object")),
        ("canonical_object_id", state.get("canonical_object_id")),
        ("canonical_slot", state.get("canonical_state_slot")),
        ("value_id", state.get("canonical_state_value_id")),
        ("polarity", state.get("polarity")),
        ("fact_type", state.get("fact_type")),
        ("temporal_status", state.get("temporal_status")),
        ("intent", state.get("intent")),
        ("certainty", state.get("certainty")),
        ("current_after", state.get("current_after")),
        ("time_role", state.get("time_role")),
        ("time_value", state.get("time_value")),
        ("normalized_time", state.get("normalized_time_value")),
        ("resolved_start", state.get("resolved_time_start")),
        ("resolved_end", state.get("resolved_time_end")),
    ]
    metadata_text = "; ".join(f"{key}={value}" for key, value in metadata if value not in (None, ""))
    facet_label = state.get("state_domain") or state.get("facet_key") or "state"
    answer_value = state.get("answer_value")
    answer_text = f" [answer_value={answer_value}]" if answer_value not in (None, "") else ""
    return (
        f"{state.get('subject', '')} {facet_label}: {state.get('value', '')}{answer_text} "
        f"({metadata_text})"
    )


def claim_summary(claim: Mapping[str, Any]) -> str:
    temporal = ""
    if claim.get("time_role") or claim.get("time_value"):
        temporal = (
            f" [{claim.get('time_role', '')}={claim.get('time_value', '')}; "
            f"normalized={claim.get('normalized_time_value', '')}; "
            f"resolved={claim.get('resolved_time_start', '')}..{claim.get('resolved_time_end', '')}]"
        )
    summary = (
        f"{claim.get('dialog_id', '')} {claim.get('subject', '')} "
        f"{claim.get('facet_key', '')}: {claim.get('value', '')}{temporal}"
    )
    metadata = [
        ("canonical_subject", claim.get("canonical_subject")),
        ("subject_key", claim.get("subject_key") or claim.get("canonical_subject_id")),
        ("dimension", claim.get("state_dimension") or claim.get("canonical_state_group_id")),
        ("domain", claim.get("state_domain")),
        ("target", claim.get("state_target")),
        ("slot_type", claim.get("slot_type") or claim.get("state_cardinality")),
        ("object", claim.get("state_object")),
        ("canonical_object_id", claim.get("canonical_object_id")),
        ("canonical_slot", claim.get("canonical_state_slot")),
        ("value_id", claim.get("canonical_state_value_id")),
        ("polarity", claim.get("polarity")),
        ("fact_type", claim.get("fact_type")),
        ("temporal_status", claim.get("temporal_status")),
        ("intent", claim.get("intent")),
        ("certainty", claim.get("certainty")),
        ("answer_span", claim.get("answer_span")),
        ("evidence", claim.get("evidence_span")),
    ]
    metadata_text = "; ".join(f"{key}={value}" for key, value in metadata if value not in (None, ""))
    if metadata_text:
        summary += f" ({metadata_text})"
    return summary


def format_claim_line(claim: Mapping[str, Any], *, relation: str = "candidate") -> str:
    return f"[{relation}] {claim.get('claim_id', '')}: {claim_summary(claim)}"


def question_frame_system_prompt() -> str:
    return (
        "Parse the semantic requirements of a memory question into one universal query frame. Apply the same schema to "
        "every question. Do not answer it, classify a benchmark task, or use outside evidence. Identify named entities, "
        "required factual bindings, the requested value slot, and the minimal operation needed to produce the answer. "
        "Write each required binding relation as a short lowercase snake_case semantic predicate. "
        "required_bindings must include every factual presupposition that has to be true before filling the unknown slot. "
        "Resolve possessive and pronoun roles explicitly: a phrase such as a person's event, trip, object, family action, "
        "or plan creates an actor or owner binding for that named person. Do not place the unknown answer itself into a "
        "required binding; capture the known subject-relation-object premise instead. "
        "Preserve whether the question asks for a current persistent state, a bounded event, a plan, a belief, or a "
        "recollection in the requested slot or binding predicate; never treat those memory kinds as interchangeable. "
        "Use operation lookup for one value, enumerate for all matching values, count for a number, intersection for values "
        "shared by multiple entities, compare for choosing between alternatives, boolean for yes/no, and inference only "
        "when the requested answer is explicitly hypothetical or predictive. A grammatically plural open slot requesting "
        "all matching items or places is enumerate, not lookup. Wording such as both, shared, or in common requires "
        "intersection. Open-ended perfect constructions such as 'what has A painted' or 'where has A camped' request all "
        "matching values and therefore use enumerate. For count, use count_unit occurrences only for repeated "
        "events, visits, or times; otherwise use stated_number. Return strict JSON only."
    )


def question_frame_user_prompt(question: str) -> str:
    return (
        f"Question:\n{question}\n\n"
        "Return JSON only:\n"
        '{"entities":["entity"],"required_bindings":[{"subject":"entity","relation":"relation",'
        '"object":"object"}],"requested_slot":"short description","operation":"lookup",'
        '"count_unit":"none"}'
    )


def normalize_question_frame(raw: Mapping[str, Any]) -> Dict[str, Any]:
    operation = str(raw.get("operation") or "lookup").strip().lower()
    if operation not in READOUT_OPERATIONS:
        operation = "lookup"
    count_unit = str(raw.get("count_unit") or "none").strip().lower()
    if operation == "count":
        if count_unit in {"occurrence", "occurrences", "event", "events", "visit", "visits", "time", "times"}:
            count_unit = "occurrences"
        elif count_unit in {"entity", "entities", "people", "persons", "items"}:
            count_unit = "entities"
        elif count_unit not in COUNT_UNITS:
            count_unit = "stated_number"
    else:
        count_unit = "none"
    raw_entities = raw.get("entities")
    entities = ordered_unique(
        str(entity).strip()
        for entity in (raw_entities if isinstance(raw_entities, Sequence) and not isinstance(raw_entities, (str, bytes)) else [])
        if str(entity).strip()
    )
    bindings: List[Dict[str, str]] = []
    raw_bindings = raw.get("required_bindings")
    if isinstance(raw_bindings, Sequence) and not isinstance(raw_bindings, (str, bytes)):
        for item in raw_bindings:
            if not isinstance(item, Mapping):
                continue
            binding = {
                "subject": str(item.get("subject") or "").strip(),
                "relation": re.sub(
                    r"[^a-z0-9]+",
                    "_",
                    str(item.get("relation") or "").strip().lower(),
                ).strip("_"),
                "object": str(item.get("object") or "").strip(),
            }
            if any(binding.values()):
                bindings.append(binding)
    return {
        "entities": entities,
        "required_bindings": bindings,
        "requested_slot": str(raw.get("requested_slot") or "answer").strip() or "answer",
        "operation": operation,
        "count_unit": count_unit,
    }


def build_retrieval_queries(question: str, frame: Mapping[str, Any]) -> List[str]:
    queries = [str(question).strip()]
    if str(frame.get("operation") or "lookup") not in {"enumerate", "count", "intersection"}:
        return ordered_unique(query for query in queries if query)
    generic_objects = {"", "answer", "entity", "entities", "item", "items", "object", "thing", "things", "value"}
    bindings = frame.get("required_bindings")
    if isinstance(bindings, Sequence) and not isinstance(bindings, (str, bytes)):
        for binding in bindings:
            if not isinstance(binding, Mapping):
                continue
            subject = str(binding.get("subject") or "").strip()
            relation = str(binding.get("relation") or "").replace("_", " ").strip()
            obj = str(binding.get("object") or "").strip()
            parts = [subject, relation]
            if obj.lower() not in generic_objects:
                parts.append(obj)
            atomic_query = " ".join(part for part in parts if part)
            if atomic_query:
                queries.append(atomic_query)
    return ordered_unique(query for query in queries if query)[:MAX_RETRIEVAL_QUERIES]


def compile_grounded_answer(
    frame: Mapping[str, Any],
    raw: Mapping[str, Any],
    allowed_event_ids: Sequence[str],
    temporal_rows: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    raw_values = raw.get("values")
    values = ordered_unique(
        str(value).strip()
        for value in (raw_values if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)) else [])
        if str(value).strip()
    )
    evidence_dialog_ids = [
        event_id
        for event_id in normalize_output_dialog_ids(raw.get("evidence_dialog_ids"))
        if event_id in set(allowed_event_ids)
    ]
    counted_event_ids = [
        event_id
        for event_id in normalize_output_dialog_ids(raw.get("counted_event_ids"))
        if event_id in set(allowed_event_ids)
    ]
    operation = str(frame.get("operation") or "lookup")
    count_unit = str(frame.get("count_unit") or "none")
    requested_slot = " ".join(str(frame.get("requested_slot") or "").strip().lower().split())
    answer = str(raw.get("answer") or "").strip()
    temporal_normalization: Optional[Dict[str, str]] = None
    normalized_answer_key = " ".join(answer.lower().split())
    for row in temporal_rows:
        event_id = str(row.get("event_id") or "")
        expression = str(row.get("expression") or "").strip()
        normalized_value = str(row.get("normalized_value") or "").strip()
        if (
            event_id in evidence_dialog_ids
            and expression
            and normalized_value
            and normalized_answer_key == " ".join(expression.lower().split())
        ):
            answer = normalized_value
            values = [
                normalized_value if " ".join(value.lower().split()) == normalized_answer_key else value
                for value in values
            ]
            temporal_normalization = {
                "event_id": event_id,
                "expression": expression,
                "normalized_value": normalized_value,
            }
            break
    if operation == "lookup" and requested_slot not in GENERIC_REQUESTED_SLOTS and values:
        answer = values[0]
    elif operation == "count" and count_unit == "occurrences" and counted_event_ids:
        answer = str(len(ordered_unique(counted_event_ids)))
    elif operation in {"enumerate", "intersection"} and values:
        answer = ", ".join(values)
    return {
        "answer": answer,
        "values": values,
        "counted_event_ids": ordered_unique(counted_event_ids),
        "evidence_dialog_ids": ordered_unique(evidence_dialog_ids),
        "temporal_normalization": temporal_normalization,
    }


def operation_readout_rule(frame: Mapping[str, Any]) -> str:
    operation = str(frame.get("operation") or "lookup")
    count_unit = str(frame.get("count_unit") or "none")
    if operation == "enumerate":
        return "Return every distinct grounded value in values; do not add topical alternatives."
    if operation == "intersection":
        return "Include a value only if it is independently supported for every required entity."
    if operation == "count" and count_unit == "occurrences":
        return "Put each distinct supporting occurrence Event ID in counted_event_ids; the controller computes the count."
    if operation == "count":
        return "Return the exact grounded number in answer and values; do not count surrounding dialog turns."
    if operation == "compare":
        return "Choose only among the alternatives stated in the question and ground the choice in evidence."
    if operation == "boolean":
        return "Answer the requested yes/no modality directly, preserving uncertainty qualifiers when needed."
    if operation == "inference":
        return "Make only the most conservative conclusion licensed by the grounded evidence."
    return "Return the single most specific grounded value that fills the requested slot."


def evidence_ledger_system_prompt() -> str:
    return (
        "Select an ordered list of Claim and StateFacet evidence units from an already expanded Scope-Time-State candidate "
        "pool. Apply the same relevance and entailment policy to every question. Do not answer the question, classify a "
        "benchmark task, select source Events directly, retrieve new evidence, or invent IDs. The controller will derive "
        "source Events, each StateFacet's primary Claim, and any lifecycle/conflict witnesses deterministically, then enforce budgets on "
        "that complete proof bundle. Put the most important units first. Select every unit needed for the known premises and "
        "requested slot while excluding merely topical or redundant evidence. Prefer an exact Claim for an episodic fact or "
        "its time. Select a StateFacet only when the question needs a resolved persistent-state value, stable dimension, or lifecycle "
        "semantics; do not add it when an already selected Claim fully supports the requested fact. For enumerate, count, or "
        "intersection operations, preserve "
        "all distinct matching evidence. For hypothetical or counterfactual questions, select observed facts needed for "
        "inference without treating the hypothetical condition as a corpus fact. Treat StateFacet status=current as resolved "
        "persistent state, status=historical as non-current provenance, and status=ambiguous as unresolved conflict. "
        "state_dimension is the stable comparison key: slot_type=single values compete inside one dimension, while "
        "slot_type=object_scoped targets are independent and may coexist. The primary Claim is the selected-value proof; "
        "other compatible supports are provenance and should not be selected redundantly. Plans, beliefs, recollections, "
        "and episodic events remain Claims and must not be promoted to current state. For retained factorized graphs, "
        "cardinality=multi may coexist and cardinality=single competes; Opaque group_id is identity metadata only. Return only the "
        "requested strict JSON object."
    )


def evidence_ledger_user_prompt(
    question: str,
    frame: Mapping[str, Any],
    retrieval: RetrievalResult,
    *,
    max_claims: int,
    max_states: int,
    max_events: int,
    repair_feedback: Optional[Mapping[str, Any]] = None,
) -> str:
    claim_rows = [
        f"C{index} | {line}"
        for index, line in enumerate(retrieval.claim_lines, start=1)
    ]
    state_rows = [
        f"S{index} | state_facet_id={state_id} | {line}"
        for index, (state_id, line) in enumerate(
            zip(retrieval.trace.get("selected_state_ids", []), retrieval.state_lines),
            start=1,
        )
    ]
    repair_block = ""
    if repair_feedback:
        repair_block = (
            "The previous selection was invalid or exceeded the complete-proof budgets. Return one corrected full list; "
            "do not merely describe the correction.\n"
            f"Validation feedback:\n{json.dumps(dict(repair_feedback), ensure_ascii=False)}\n\n"
        )
    return (
        f"Question:\n{question}\n\n"
        f"Universal query frame:\n{json.dumps(dict(frame), ensure_ascii=False)}\n\n"
        "Select only the short handles shown below: C1, C2, ... for Claims and S1, S2, ... for StateFacets. "
        "Do not copy the long claim:: or state:: IDs. Do not output Event/dialog IDs. The controller maps each "
        "handle back to its exact candidate-whitelisted graph ID.\n\n"
        "Complete-proof budgets (applied after deterministic closure):\n"
        f"- Claims: {max_claims}\n- StateFacets: {max_states}\n- Events: {max_events}\n"
        "Selecting one StateFacet automatically includes its primary Claim/Event plus any relation witness needed to prove "
        "current, historical, or ambiguous status. Redundant compatible supports remain provenance. Selecting units whose "
        "Claims close a displayed relation can also include that relation's evidence Events. Keep the full derived "
        "bundle within every budget.\n\n"
        f"{repair_block}"
        "For a temporal answer, select the exact time-bearing Claim so its ingest-normalized time can be read out; "
        "do not rely on Event text alone.\n\n"
        "Expanded Claims:\n"
        f"{chr(10).join('- ' + line for line in claim_rows) or '[none]'}\n\n"
        "Expanded StateFacets:\n"
        f"{chr(10).join('- ' + line for line in state_rows) or '[none]'}\n\n"
        "Expanded relation notes:\n"
        f"{chr(10).join('- ' + line for line in retrieval.relation_lines) or '[none]'}\n\n"
        f"Expanded source Events:\n{retrieval.context or '[none]'}\n\n"
        "Return JSON only:\n"
        '{"evidence_units":[{"kind":"claim","id":"C1"},'
        '{"kind":"state_facet","id":"S1"}]}'
    )


def output_dialog_id_tokens(value: object) -> List[str]:
    """Read an exact JSON array of emitted ID tokens without repairing its shape."""
    if not isinstance(value, (list, tuple)):
        return []
    return ordered_unique(
        str(item).strip()
        for item in value
        if item is not None and str(item).strip() not in {"", "null"}
    )


def normalize_evidence_ledger(
    raw: Mapping[str, Any],
    *,
    allowed_claim_ids: Sequence[str],
    allowed_state_ids: Sequence[str],
) -> Dict[str, Any]:
    claim_id_set = set(allowed_claim_ids)
    state_id_set = set(allowed_state_ids)
    claim_handles = {f"C{index}": claim_id for index, claim_id in enumerate(allowed_claim_ids, start=1)}
    state_handles = {f"S{index}": state_id for index, state_id in enumerate(allowed_state_ids, start=1)}
    selected_units: List[Dict[str, str]] = []
    invalid_requested_units: List[str] = []
    unsupported_fields = sorted(set(raw) - {"evidence_units"})
    invalid_requested_units.extend(f"<unsupported_field:{field}>" for field in unsupported_fields)
    raw_units = raw.get("evidence_units")
    if isinstance(raw_units, Sequence) and not isinstance(raw_units, (str, bytes)):
        seen_units: set[Tuple[str, str]] = set()
        for index, item in enumerate(raw_units):
            if not isinstance(item, Mapping):
                invalid_requested_units.append(f"<malformed_unit:{index}>")
                continue
            kind = str(item.get("kind") or "").strip()
            identifier = str(item.get("id") or "").strip()
            if kind == "state":
                kind = "state_facet"
            if kind == "claim" and identifier in claim_handles:
                identifier = claim_handles[identifier]
            elif kind == "state_facet" and identifier in state_handles:
                identifier = state_handles[identifier]
            allowed = claim_id_set if kind == "claim" else state_id_set if kind == "state_facet" else set()
            if set(item) != {"kind", "id"} or not identifier or identifier not in allowed:
                invalid_requested_units.append(f"{kind or '<missing_kind>'}:{identifier or '<missing_id>'}")
                continue
            unit_key = (kind, identifier)
            if unit_key not in seen_units:
                seen_units.add(unit_key)
                selected_units.append({"kind": kind, "id": identifier})
    else:
        invalid_requested_units.append("<missing_or_malformed_evidence_units>")
    return {
        "selected_units": selected_units,
        "invalid_requested_units": ordered_unique(invalid_requested_units),
        "raw": dict(raw),
    }


def final_answer_event_ids(retrieval: RetrievalResult) -> List[str]:
    ledger_trace = retrieval.trace.get("evidence_ledger")
    if isinstance(ledger_trace, Mapping) and "selected_event_ids" in ledger_trace:
        selected = ledger_trace.get("selected_event_ids")
        if isinstance(selected, Sequence) and not isinstance(selected, (str, bytes)):
            return ordered_unique(str(event_id) for event_id in selected if str(event_id))
        return []
    return list(retrieval.candidate_dialog_ids)


def reported_evidence_dialog_ids(
    output: Mapping[str, Any],
    allowed_event_ids: Sequence[str],
    ledger_trace: Mapping[str, Any],
    citation_source: str,
) -> List[str]:
    allowed_event_set = set(allowed_event_ids)
    cited_event_ids = [
        event_id
        for event_id in normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
        if event_id in allowed_event_set
    ]
    if citation_source == "answer-ledger":
        cited_event_ids.extend(
            str(event_id)
            for event_id in ledger_trace.get("selected_event_ids", [])
            if str(event_id) in allowed_event_set
        )
    return ordered_unique(cited_event_ids)


def answer_system_prompt() -> str:
    return (
        "Answer memory questions using only the complete expanded Scope-Time-State evidence pack and its source turns. "
        "Follow the supplied universal query frame and return strict JSON with answer, values, counted_event_ids, and "
        "evidence_dialog_ids. Every value and counted occurrence must be grounded in cited source turns. "
        "Use the same reasoning policy for every question. Direct conclusions and conservative causal or commonsense "
        "inferences are allowed only when they follow from provided evidence; do not introduce unsupported facts or "
        "transfer facts between entities. Return the shortest complete answer span and omit explanations or question "
        "restatement. Answer the requested modality or decision directly instead of substituting a supporting quotation. "
        "Resolve anaphoric, elliptical, or generic references to the most specific named referent available in the evidence; "
        "do not return an unresolved placeholder when its referent is present. "
        "Apply the question's polarity and conditions before answering. For a causal intervention that removes a stated "
        "cause, do not carry the observed outcome over unchanged when the evidence links that cause to the outcome. "
        "When normalized Time evidence resolves a relative expression, never return the unresolved expression; use the "
        "normalized value. "
        "Interpret StateFacet state_dimension, slot_type, status, and relation edges together. Values in one single slot "
        "must honor explicit supersession, correction, or unresolved conflict; object-scoped targets may coexist. Treat "
        "current as resolved, historical as non-current provenance, and ambiguous as uncertain. Use the StateFacet value "
        "and source evidence for user-facing wording; IDs are metadata, not answer text. In retained factorized graphs, "
        "canonical value_id and opaque group_id are identity metadata, not answer text. Do not turn plan, belief, "
        "recollection, or episodic-event Claims into an asserted current state. "
        "Before emitting JSON, silently audit the draft against four universal checks: every entity-role relation is "
        "supported by a compatible evidence chain; every condition, negation, polarity, and modality in the question "
        "is applied; normalized time replaces relative wording; and every distinct supported value requested by the "
        "unknown slot is included without broadening a specific value. Revise the draft if any check fails. "
        "For false-premise or unavailable information, answer exactly \"No information available\" or "
        "\"Not mentioned in the conversation\". Cite only dialog IDs present in the evidence."
    )


def answer_user_prompt(
    row: LoCoMoQAItem,
    retrieval: RetrievalResult,
    frame: Mapping[str, Any],
) -> str:
    temporal_block = ""
    if retrieval.temporal_lines:
        temporal_block = (
            "Time grounding derived from candidate graph evidence:\n"
            f"{chr(10).join('- ' + line for line in retrieval.temporal_lines)}\n\n"
        )
    direct_delivery = (
        retrieval.trace.get("evidence_delivery", {}).get("mode")
        == "direct_graph_expansion"
    )
    evidence_mode = (
        "direct_graph_expansion"
        if direct_delivery
        else str(retrieval.trace.get("evidence_ledger", {}).get("selection_status") or "fallback_unresolved")
    )
    failure_rule = ""
    if evidence_mode == "fallback_unresolved":
        failure_rule = (
            "- The Ledger selector failed twice; answer conservatively and abstain when the fallback Events are "
            "insufficient.\n"
        )
    return (
        f"Question:\n{row.question}\n\n"
        "Universal query frame:\n"
        f"{json.dumps(dict(frame), ensure_ascii=False)}\n\n"
        f"Evidence handling mode:\n{evidence_mode}\n\n"
        "Expanded Claims:\n"
        f"{chr(10).join('- ' + line for line in retrieval.claim_lines) or '[none]'}\n\n"
        f"{temporal_block}"
        "Expanded StateFacets:\n"
        f"{chr(10).join('- ' + line for line in retrieval.state_lines) or '[none]'}\n\n"
        "Expanded relation notes:\n"
        f"{chr(10).join('- ' + line for line in retrieval.relation_lines) or '[none]'}\n\n"
        f"Source dialog turns:\n{retrieval.context or '[none]'}\n\n"
        "Answer rules:\n"
        f"{failure_rule}"
        "- Use only Claims whose entity, relation, and value jointly match the question.\n"
        "- Use StateFacet validity, relation notes, and normalized Time evidence when relevant.\n"
        "- Respect fact_type, temporal_status, intent, certainty, and polarity; current states, historical events, and future intentions are not interchangeable.\n"
        "- Respect StateFacet state_dimension, slot_type, and status: current is resolved, historical is non-current, and ambiguous is uncertain.\n"
        "- Use StateFacet value/source wording in the answer rather than emitting graph IDs.\n"
        f"- Operation rule: {operation_readout_rule(frame)}\n"
        "- Verify the final wording and citations against source dialog turns.\n"
        "- Answer the question's requested modality directly; evidence is the basis, not a substitute for the answer.\n"
        "- Include all distinct supported values that fill the requested unknown slot, but no merely related values.\n"
        "- Return only the shortest complete answer span; do not restate the question or add an explanation.\n"
        "- If evidence is missing or contradicts the premise, abstain with the exact unavailable phrase.\n\n"
        "Respond as JSON only:\n"
        "{\"answer\": \"...\", \"values\": [\"value\"], \"counted_event_ids\": [\"D1:1\"], "
        "\"evidence_dialog_ids\": [\"D1:1\"]}"
    )


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
    return [
        item
        for item in output_dialog_id_tokens(value)
        if re.fullmatch(r"D\d+:\d+", item)
    ]


def recall(selected: Sequence[str], gold: Sequence[str]) -> Optional[float]:
    gold_set = set(gold)
    if not gold_set:
        return None
    return len(gold_set & set(selected)) / len(gold_set)


def precision(selected: Sequence[str], gold: Sequence[str]) -> Optional[float]:
    selected_set = set(selected)
    if not selected_set:
        return 0.0 if gold else None
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
        frame_client = make_sharded_client(
            answer_runtime,
            "question_frame",
            f"{row.question_id}_{short_hash(row.question)}",
        )
        frame_raw = frame_client.complete_json(
            question_frame_system_prompt(),
            question_frame_user_prompt(row.question),
        )
        frame = normalize_question_frame(frame_raw)
        retrieval_queries = build_retrieval_queries(row.question, frame)
        query_subject_ids = graph.resolve_query_subject_ids(frame.get("entities", []))
        time_role_client = make_sharded_client(
            answer_runtime,
            "time_role_selector",
            short_hash(row.question),
        )
        retrieval = graph.retrieve(
            row.question,
            retrieval_queries=retrieval_queries,
            variant=variant,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            scope_top_k=args.scope_top_k,
            scope_backoff_k=args.scope_backoff_k,
            max_context_events=args.max_context_events,
            max_state_lines=args.max_state_lines,
            embedding_indices=embedding_indices,
            embedding_candidate_k=args.embedding_candidate_k,
            scope_types=parse_scope_types(args.scope_types),
            time_role_client=time_role_client,
            time_role_selector=args.time_role_selector,
            event_time_routing=args.event_time_routing,
            graph_expansion=args.graph_expansion,
            query_subject_ids=query_subject_ids,
            readout_operation=str(frame.get("operation") or "lookup"),
            query_entities=frame.get("entities", []),
            scope_anchor_routing=args.scope_anchor_routing,
            retrieval_policy=args.retrieval_policy,
        )
        retrieval.trace["retrieval_query"] = row.question
        retrieval.trace["question_frame"] = {
            **frame,
            "uses_task_labels": False,
            "uses_gold": False,
            "raw": frame_raw,
        }
        retrieved_candidate_dialog_ids = list(retrieval.candidate_dialog_ids)
        expanded_retrieval = retrieval
        if args.evidence_selector == "direct":
            retrieval = expanded_retrieval
            retrieval.trace["evidence_delivery"] = {
                "mode": "direct_graph_expansion",
                "uses_task_labels": False,
                "uses_gold": False,
                "selection_applied": False,
                "repacking_applied": False,
                "ledger_budgets_applied": False,
            }
        elif args.evidence_selector == "deterministic":
            retrieval = graph.apply_deterministic_evidence_budget(
                expanded_retrieval,
                max_claims=args.max_ledger_claims,
                max_states=args.max_ledger_states,
                max_events=args.max_ledger_events,
                fallback_events=args.ledger_fallback_events,
            )
        else:
            ledger_client = make_sharded_client(
                answer_runtime,
                f"evidence_ledger_{variant}",
                f"{row.question_id}_{short_hash(row.question)}",
            )
            ledger_raw = ledger_client.complete_json(
                evidence_ledger_system_prompt(),
                evidence_ledger_user_prompt(
                    row.question,
                    frame,
                    expanded_retrieval,
                    max_claims=args.max_ledger_claims,
                    max_states=args.max_ledger_states,
                    max_events=args.max_ledger_events,
                ),
            )
            ledger = normalize_evidence_ledger(
                ledger_raw,
                allowed_claim_ids=expanded_retrieval.trace.get("expanded_claim_ids", []),
                allowed_state_ids=expanded_retrieval.trace.get("selected_state_ids", []),
            )
            retrieval = graph.apply_evidence_ledger(
                expanded_retrieval,
                ledger,
                max_claims=args.max_ledger_claims,
                max_states=args.max_ledger_states,
                max_events=args.max_ledger_events,
                fallback_events=args.ledger_fallback_events,
                attempt=1,
                fallback_on_failure=False,
            )
            ledger_trace = retrieval.trace.get("evidence_ledger", {})
            if ledger_trace.get("repair_required"):
                repair_client = make_sharded_client(
                    answer_runtime,
                    f"evidence_ledger_repair_{variant}",
                    f"{row.question_id}_{short_hash(row.question)}",
                )
                repair_feedback = {
                    "invalid_requested_units": ledger_trace.get("invalid_requested_units", []),
                    "rejected_units": ledger_trace.get("rejected_units", []),
                    "fixed_budgets": ledger_trace.get("fixed_budgets", {}),
                }
                repair_raw = repair_client.complete_json(
                    evidence_ledger_system_prompt(),
                    evidence_ledger_user_prompt(
                        row.question,
                        frame,
                        expanded_retrieval,
                        max_claims=args.max_ledger_claims,
                        max_states=args.max_ledger_states,
                        max_events=args.max_ledger_events,
                        repair_feedback=repair_feedback,
                    ),
                )
                repaired_ledger = normalize_evidence_ledger(
                    repair_raw,
                    allowed_claim_ids=expanded_retrieval.trace.get("expanded_claim_ids", []),
                    allowed_state_ids=expanded_retrieval.trace.get("selected_state_ids", []),
                )
                retrieval = graph.apply_evidence_ledger(
                    expanded_retrieval,
                    repaired_ledger,
                    max_claims=args.max_ledger_claims,
                    max_states=args.max_ledger_states,
                    max_events=args.max_ledger_events,
                    fallback_events=args.ledger_fallback_events,
                    attempt=2,
                    fallback_on_failure=True,
                )
                retrieval.trace["evidence_ledger"]["initial_attempt"] = ledger_trace
        if args.retrieval_policy in {"scope-event-time", "sts"}:
            retrieval = graph.finalize_temporal_readout(
                retrieval,
                include_state=args.retrieval_policy == "sts",
            )
        else:
            retrieval.trace["temporal_readout"] = {
                "mode": "disabled_by_retrieval_policy",
                "rows": [],
                "uses_task_labels": False,
                "uses_gold": False,
                "recalculates_time": False,
            }
        client = make_sharded_client(answer_runtime, f"answer_{variant}", f"{row.question_id}_{short_hash(row.question)}")
        raw_output = client.complete_json(
            answer_system_prompt(),
            answer_user_prompt(row, retrieval, frame),
        )
        answer_source = "universal_grounded_readout"
        answer_event_ids = final_answer_event_ids(retrieval)
        output = compile_grounded_answer(
            frame,
            raw_output,
            answer_event_ids,
            retrieval.trace.get("temporal_readout", {}).get("rows", []),
        )
        if args.binding_gate == "participant":
            cited_event_ids = [
                event_id
                for event_id in normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
                if event_id in set(answer_event_ids)
            ]
            binding_trace = graph.evaluate_participant_binding(frame, cited_event_ids)
            original_answer = str(output.get("answer") or "").strip()
            already_abstained = any(
                phrase in original_answer.casefold()
                for phrase in ("no information available", "not mentioned")
            )
            override_applied = bool(binding_trace["blocked"] and not already_abstained)
            if override_applied:
                output = {
                    **output,
                    "answer": "Not mentioned in the conversation",
                    "values": [],
                    "counted_event_ids": [],
                }
            retrieval.trace["pipeline_order"] = list(retrieval.trace.get("pipeline_order", [])) + [
                "participant_binding_gate"
            ]
            retrieval.trace["binding_gate"] = {
                **binding_trace,
                "already_abstained": already_abstained,
                "override_applied": override_applied,
                "original_answer": original_answer if override_applied else None,
            }
        else:
            retrieval.trace["binding_gate"] = {
                "mode": "off",
                "status": "disabled",
                "blocked": False,
                "override_applied": False,
                "uses_task_labels": False,
                "uses_gold": False,
            }
        retrieval.trace["answer_decision"] = {
            "source": answer_source,
            "operation": frame["operation"],
            "count_unit": frame["count_unit"],
            "values": output["values"],
            "counted_event_ids": output["counted_event_ids"],
            "temporal_normalization": output["temporal_normalization"],
            "raw": raw_output,
            "uses_task_labels": False,
            "uses_gold": False,
        }
        hypothesis = str(output.get("answer", "")).strip()
        evidence_dialog_ids = reported_evidence_dialog_ids(
            output,
            answer_event_ids,
            retrieval.trace.get("evidence_ledger", {}),
            args.evidence_citation_source,
        )
        evidence_precision = precision(evidence_dialog_ids, row.evidence_dialog_ids)
        evidence_recall = recall(evidence_dialog_ids, row.evidence_dialog_ids)
        ledger_dialog_ids = list(retrieval.trace.get("evidence_ledger", {}).get("selected_event_ids", []))
        result = {
            "question_id": row.question_id,
            "sample_id": row.sample_id,
            "qa_index": row.qa_index,
            "category": row.category,
            "question_type": row.question_type,
            "question": row.question,
            "gold_answer": row.answer,
            "hypothesis": hypothesis,
            "candidate_dialog_ids": retrieved_candidate_dialog_ids,
            "ledger_dialog_ids": ledger_dialog_ids,
            "evidence_dialog_ids": evidence_dialog_ids,
            "gold_evidence_dialog_ids": list(row.evidence_dialog_ids),
            "candidate_dialog_recall": recall(retrieved_candidate_dialog_ids, row.evidence_dialog_ids),
            "candidate_dialog_precision": precision(retrieved_candidate_dialog_ids, row.evidence_dialog_ids),
            "ledger_dialog_recall": recall(ledger_dialog_ids, row.evidence_dialog_ids),
            "ledger_dialog_precision": precision(ledger_dialog_ids, row.evidence_dialog_ids),
            "evidence_dialog_recall": evidence_recall,
            "evidence_dialog_precision": evidence_precision,
            "evidence_dialog_f1": f1_from_precision_recall(evidence_precision, evidence_recall),
            "answer_f1": official_style_answer_score(row, hypothesis),
            "bleu1": None if row.category == 5 else official_bleu1_score(hypothesis, row.answer),
            "exact_match": exact_match_score(hypothesis, row.answer) if row.category != 5 else False,
            "retrieval_trace": retrieval.trace,
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    args.graph_dir = str(Path(args.graph_dir) if args.graph_dir else default_query_graph_dir(args.sample_id))
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
        validate_graph_sample_id(graph, args.sample_id)
    except ValueError as exc:
        print(f"Graph config error: {exc}", file=sys.stderr)
        return 2
    graph.set_event_state_enrichment(args.event_state_enrichment)
    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.model:
        model = args.model
    non_semantic_output_args = {
        "answer_workers",
        "cache",
        "embedding_base_url",
        "embedding_batch_size",
        "embedding_cache",
        "model",
        "no_cache",
        "output",
        "provider",
        "variants",
    }
    output_run_config = {
        key: value
        for key, value in vars(args).items()
        if key not in non_semantic_output_args
    }
    args.output = str(
        Path(args.output)
        if args.output
        else default_query_output_path(
            args.sample_id,
            provider=args.provider,
            model=model,
            variants=args.variants,
            run_config=output_run_config,
        )
    )
    answer_runtime = LLMRuntimeConfig(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )
    needed_embedding_targets = embedding_targets_for_run(
        args.variants,
        args.retrieval_policy,
    )
    embedding_indices: Dict[str, OpenAIEmbeddingIndex] = {}
    raw_event_retrieval = args.retrieval_policy != "sts"
    event_document_version = (
        "raw-event-v1"
        if raw_event_retrieval
        else ("state-enriched-v1" if args.event_state_enrichment else "base")
    )
    embedding_namespace = f"locomo-qa:{Path(args.graph_dir).resolve()}"
    if "event" in needed_embedding_targets:
        embedding_indices["event"] = OpenAIEmbeddingIndex(
            graph.event_doc_ids,
            graph.raw_event_documents if raw_event_retrieval else graph.event_documents,
            model=args.embedding_model,
            cache_path=Path(args.embedding_cache),
            namespace=f"{embedding_namespace}:events:{event_document_version}",
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
            namespace=f"{embedding_namespace}:statefacets:semantic-only-v1",
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
        "graph_expansion": (
            graph.resolve_graph_expansion(args.graph_expansion)
            if args.retrieval_policy == "sts"
            else None
        ),
        "provider": args.provider,
        "model": model,
        "variants": list(args.variants),
        "retrieval_policy": args.retrieval_policy,
        "question_types": [normalize_question_type(item) for item in args.question_types],
        "top_k": args.top_k,
        "scope_top_k": args.scope_top_k,
        "scope_backoff_k": args.scope_backoff_k,
        "scope_types": parse_scope_types(args.scope_types),
        "scope_anchor_routing": args.scope_anchor_routing,
        "binding_gate": args.binding_gate,
        "statefacet_access": (
            "disabled_by_retrieval_policy"
            if args.retrieval_policy != "sts"
            else (
                "scoped-statefacet-direct-retrieval"
                if set(args.variants) == {"graph_embedding_scope_statefacet"}
                else (
                    "event-claim-graph-expansion-only"
                    if "graph_embedding_scope_statefacet" not in args.variants
                    else "variant-specific"
                )
            )
        ),
        "statefacet_access_by_variant": {
            variant: (
                "disabled_by_retrieval_policy"
                if args.retrieval_policy != "sts"
                else (
                    "scoped-statefacet-direct-retrieval"
                    if variant == "graph_embedding_scope_statefacet"
                    else "event-claim-graph-expansion-only"
                )
            )
            for variant in args.variants
        },
        "time_role_selector": args.time_role_selector,
        "time_role_routing_enabled": args.retrieval_policy in {"scope-event-time", "sts"},
        "event_time_routing": args.event_time_routing,
        "candidate_k": args.candidate_k,
        "embedding_candidate_k": args.embedding_candidate_k,
        "embedding_model": args.embedding_model if needed_embedding_targets else None,
        "evidence_selector": args.evidence_selector,
        "evidence_ledger": (
            None
            if args.evidence_selector == "direct"
            else (
                "deterministic_ranked_graph_units_primary_relation_proof_budget"
                if args.evidence_selector == "deterministic"
                else "ordered_units_primary_relation_proof_closure_single_repair"
            )
        ),
        "evidence_delivery": (
            "direct_graph_expansion"
            if args.evidence_selector == "direct"
            else "selected_proof_pack"
        ),
        "evidence_citation_source": args.evidence_citation_source,
        "question_frame": "universal_semantic_frame",
        "grounded_readout": "lookup_enumerate_count_intersection_compare_boolean_inference",
        "event_fusion": "max_rrf_with_overlap_bonus",
        "event_fusion_overlap_weight": RRF_OVERLAP_WEIGHT,
        "event_document_enrichment": (
            ["raw_event_text", "speaker", "source_timestamp", "image_metadata"]
            if raw_event_retrieval
            else (
                ["claim_summaries", "scope_labels", "linked_statefacet_dimension_value_status"]
                if args.event_state_enrichment
                else ["claim_summaries", "scope_labels"]
            )
        ),
        "statefacet_document_fields": [
            "canonical_subject",
            "subject",
            "state_domain",
            "state_target",
            "state_dimension",
            "facet_key",
            "slot_type",
            "value",
            "status",
            "summary",
            "graph_text",
        ],
        "max_context_events": args.max_context_events,
        "max_ledger_claims": None if args.evidence_selector == "direct" else args.max_ledger_claims,
        "max_ledger_states": None if args.evidence_selector == "direct" else args.max_ledger_states,
        "max_ledger_events": None if args.evidence_selector == "direct" else args.max_ledger_events,
        "ledger_fallback_events": None if args.evidence_selector == "direct" else args.ledger_fallback_events,
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
                            "hypothesis": row["hypothesis"],
                            "candidate_dialog_ids": row["candidate_dialog_ids"],
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

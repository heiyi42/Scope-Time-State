"""Hybrid Scope/Event/Claim retrieval over an EPBench STS v2 graph."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Protocol, Sequence

from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex
from pipeline.external.sts_v2.schema import SCHEMA_VERSION
from pipeline.external.temporal_grounding import parse_anchor_datetime
from pipeline.external.time_role_selection import select_time_roles

from .config import (
    CLAIM_CANDIDATE_K,
    EMBEDDING_MODEL,
    EMBEDDING_SCORE_WEIGHT,
    FINAL_CLAIM_K,
    FINAL_CHAPTER_K,
    SCOPE_BACKOFF_K,
    SCOPE_TOP_K,
    SCOPE_TYPE_COVERAGE_WEIGHT,
    STATE_ANCHOR_CLAIM_K,
    TIME_COMPATIBILITY_WEIGHT,
)


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
GENERIC_SCOPE_QUERIES = {
    "entities",
    "events",
    "key events",
    "locations",
    "protagonists",
    "unique locations",
}
CLAIM_RRF_K = 60
CLAIM_RETRIEVAL_POLICIES = (
    "claim",
    "scope-claim",
    "scope-claim-time",
    "scope-claim-time-state",
)


def _tokens(text: object) -> list[str]:
    return TOKEN_RE.findall(str(text or "").casefold())


@dataclass(frozen=True)
class RankedHit:
    doc_id: str
    score: float
    lexical_score: float = 0.0
    embedding_score: float = 0.0
    lexical_rank: int | None = None
    embedding_rank: int | None = None
    retrieval_sources: tuple[str, ...] = ()


class BM25Index:
    def __init__(self, doc_ids: Sequence[str], documents: Sequence[str]) -> None:
        if len(doc_ids) != len(documents):
            raise ValueError("doc_ids and documents must have the same length")
        self.doc_ids = [str(value) for value in doc_ids]
        self.term_frequencies: list[dict[str, int]] = []
        self.lengths: list[int] = []
        document_frequency: dict[str, int] = {}
        for document in documents:
            frequencies: dict[str, int] = {}
            for token in _tokens(document):
                frequencies[token] = frequencies.get(token, 0) + 1
            self.term_frequencies.append(frequencies)
            self.lengths.append(sum(frequencies.values()))
            for token in frequencies:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        self.document_frequency = document_frequency
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1)

    def search(
        self, query: str, top_k: int, allowed_doc_ids: Iterable[str] | None = None
    ) -> list[RankedHit]:
        if top_k <= 0:
            return []
        allowed = None if allowed_doc_ids is None else {str(value) for value in allowed_doc_ids}
        query_tokens = list(dict.fromkeys(_tokens(query)))
        scored: list[RankedHit] = []
        total = len(self.doc_ids)
        for index, doc_id in enumerate(self.doc_ids):
            if allowed is not None and doc_id not in allowed:
                continue
            score = 0.0
            length = self.lengths[index]
            for token in query_tokens:
                frequency = self.term_frequencies[index].get(token, 0)
                if not frequency:
                    continue
                df = self.document_frequency.get(token, 0)
                inverse = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
                denominator = frequency + 1.5 * (1.0 - 0.75 + 0.75 * length / max(self.average_length, 1.0))
                score += inverse * frequency * 2.5 / denominator
            if score > 0.0:
                scored.append(RankedHit(doc_id=doc_id, score=score, lexical_score=score))
        scored.sort(key=lambda row: (-row.score, row.doc_id))
        return scored[:top_k]


class SearchIndex(Protocol):
    def search(self, query: str, top_k: int, allowed_doc_ids: Iterable[str] | None = None): ...


class _EmptyDenseIndex:
    def search(self, _query: str, _top_k: int, allowed_doc_ids=None):
        return []


def hybrid_rank(
    query: str,
    bm25: SearchIndex,
    dense: SearchIndex,
    top_k: int,
    allowed_doc_ids: Iterable[str] | None = None,
) -> list[RankedHit]:
    lexical_rows = bm25.search(query, top_k, allowed_doc_ids=allowed_doc_ids)
    dense_rows = dense.search(query, top_k, allowed_doc_ids=allowed_doc_ids)
    combined: dict[str, dict[str, Any]] = {}
    for rank, row in enumerate(lexical_rows, 1):
        doc_id = str(row.doc_id)
        combined.setdefault(doc_id, {})
        combined[doc_id].update(lexical_score=float(row.score), lexical_rank=rank)
    for rank, row in enumerate(dense_rows, 1):
        doc_id = str(row.doc_id)
        combined.setdefault(doc_id, {})
        combined[doc_id].update(embedding_score=float(row.score), embedding_rank=rank)
    hits: list[RankedHit] = []
    for doc_id, values in combined.items():
        lexical_score = float(values.get("lexical_score", 0.0))
        embedding_score = float(values.get("embedding_score", 0.0))
        sources = tuple(
            name
            for name, present in (
                ("bm25", "lexical_rank" in values),
                ("embedding", "embedding_rank" in values),
            )
            if present
        )
        hits.append(
            RankedHit(
                doc_id=doc_id,
                score=lexical_score + EMBEDDING_SCORE_WEIGHT * max(embedding_score, 0.0),
                lexical_score=lexical_score,
                embedding_score=embedding_score,
                lexical_rank=values.get("lexical_rank"),
                embedding_rank=values.get("embedding_rank"),
                retrieval_sources=sources,
            )
        )
    hits.sort(key=lambda row: (-row.score, row.doc_id))
    return hits[:top_k]


def rrf_rank(
    query: str,
    bm25: SearchIndex,
    dense: SearchIndex,
    top_k: int,
    allowed_doc_ids: Iterable[str] | None = None,
    *,
    rrf_k: int = CLAIM_RRF_K,
) -> list[RankedHit]:
    """Rank the BM25--dense union without mixing incomparable score scales."""
    lexical_rows = bm25.search(query, top_k, allowed_doc_ids=allowed_doc_ids)
    dense_rows = dense.search(query, top_k, allowed_doc_ids=allowed_doc_ids)
    combined: dict[str, dict[str, Any]] = {}
    for rank, row in enumerate(lexical_rows, 1):
        combined.setdefault(str(row.doc_id), {}).update(
            lexical_score=float(row.score), lexical_rank=rank
        )
    for rank, row in enumerate(dense_rows, 1):
        combined.setdefault(str(row.doc_id), {}).update(
            embedding_score=float(row.score), embedding_rank=rank
        )
    hits: list[RankedHit] = []
    for doc_id, values in combined.items():
        lexical_rank = values.get("lexical_rank")
        embedding_rank = values.get("embedding_rank")
        score = sum(
            1.0 / (rrf_k + rank)
            for rank in (lexical_rank, embedding_rank)
            if rank is not None
        )
        hits.append(
            RankedHit(
                doc_id=doc_id,
                score=score,
                lexical_score=float(values.get("lexical_score", 0.0)),
                embedding_score=float(values.get("embedding_score", 0.0)),
                lexical_rank=lexical_rank,
                embedding_rank=embedding_rank,
                retrieval_sources=tuple(
                    name
                    for name, rank in (("bm25", lexical_rank), ("embedding", embedding_rank))
                    if rank is not None
                ),
            )
        )
    hits.sort(key=lambda row: (-row.score, row.doc_id))
    return hits[:top_k]


@dataclass(frozen=True)
class QuestionFrame:
    time_values: list[str] = field(default_factory=list)
    entity_queries: list[str] = field(default_factory=list)
    location_queries: list[str] = field(default_factory=list)
    event_type_queries: list[str] = field(default_factory=list)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(" ".join(str(item).split()) for item in value if str(item).strip()))


def build_question_frame(question: str, client: Any | None) -> QuestionFrame:
    raw: Mapping[str, Any] = {}
    if client is not None:
        raw = client.complete_json(
            "Frame a question for STS retrieval using only explicitly named anchors in the question. Do not infer or expand entities, locations, or event types. Return one JSON object with time_values, entity_queries, location_queries, and event_type_queries.",
            question,
        )
        forbidden = {"answer", "correct_answer", "correct_answer_chapters", "gold", "reference"}
        if forbidden.intersection(raw):
            raise ValueError("question frame contains evaluator-only fields")
    return QuestionFrame(
        time_values=_string_list(raw.get("time_values")),
        entity_queries=_string_list(raw.get("entity_queries")),
        location_queries=_string_list(raw.get("location_queries")),
        event_type_queries=_string_list(raw.get("event_type_queries")),
    )


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = EMBEDDING_MODEL
    cache_dir: Path = Path("embedding_cache")
    batch_size: int = 24
    base_url: str | None = None


@dataclass
class RankedChapter:
    chapter_id: int
    score: float
    occurred_at: str
    matched_scope_types: list[str]
    selected_claim_ids: list[str]
    evidence_spans: list[str]
    raw_text: str
    contributions: list[dict[str, Any]]
    selected_state_ids: list[str] = field(default_factory=list)
    state_evidence: list[str] = field(default_factory=list)
    relation_evidence: list[str] = field(default_factory=list)
    scope_values: dict[str, list[str]] = field(default_factory=dict)
    entity_roles: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    question: str
    frame: QuestionFrame
    ranked_chapters: list[RankedChapter]
    trace: dict[str, Any]
    retrieval_status: str = "grounded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "frame": asdict(self.frame),
            "retrieval_status": self.retrieval_status,
            "ranked_chapters": [asdict(row) for row in self.ranked_chapters],
            "trace": self.trace,
        }


class STSGraphIndex:
    def __init__(self, graph: Mapping[str, Any], embedding_config: EmbeddingConfig | None = None) -> None:
        if graph.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("incompatible STS graph schema")
        self.nodes = {str(node["node_id"]): dict(node) for node in graph.get("nodes", [])}
        self.edges = [dict(edge) for edge in graph.get("edges", [])]
        self.events = {node_id: node for node_id, node in self.nodes.items() if node["node_type"] == "Episode/Event"}
        self.scopes = {node_id: node for node_id, node in self.nodes.items() if node["node_type"] == "Entity/Scope" and node.get("scope_type") != "book"}
        self.claims = {node_id: node for node_id, node in self.nodes.items() if node["node_type"] == "Claim"}
        self.facets = {node_id: node for node_id, node in self.nodes.items() if node["node_type"] == "StateFacet"}
        self.scope_events: dict[str, set[str]] = {scope_id: set() for scope_id in self.scopes}
        self.event_scopes: dict[str, set[str]] = {event_id: set() for event_id in self.events}
        self.event_entity_roles: dict[str, dict[str, set[str]]] = {
            event_id: {} for event_id in self.events
        }
        self.event_claims: dict[str, list[str]] = {event_id: [] for event_id in self.events}
        self.event_times: dict[str, list[str]] = {event_id: [] for event_id in self.events}
        self.claim_facets: dict[str, set[str]] = {claim_id: set() for claim_id in self.claims}
        self.facet_claims: dict[str, set[str]] = {facet_id: set() for facet_id in self.facets}
        self.claim_time_roles: dict[str, set[str]] = {claim_id: set() for claim_id in self.claims}
        self.claim_time_values: dict[str, dict[str, list[str]]] = {
            claim_id: {} for claim_id in self.claims
        }
        for edge in self.edges:
            if edge["type"] in {"IN_SCOPE", "MENTIONS"} and edge["to"] in self.scope_events:
                self.scope_events[edge["to"]].add(str(edge["from"]))
                if edge["from"] in self.event_scopes:
                    self.event_scopes[str(edge["from"])].add(str(edge["to"]))
                    scope = self.scopes[str(edge["to"])]
                    if scope.get("scope_type") == "entity":
                        role = str(edge.get("role") or "mentioned")
                        self.event_entity_roles[str(edge["from"])].setdefault(role, set()).add(
                            str(scope.get("value") or "")
                        )
            elif edge["type"] == "ASSERTS" and edge["from"] in self.event_claims:
                self.event_claims[edge["from"]].append(str(edge["to"]))
            elif edge["type"] == "OCCURRED_AT" and edge["from"] in self.event_times:
                value = self.nodes.get(str(edge["to"]), {}).get("value")
                if value:
                    self.event_times[edge["from"]].append(str(value))
            elif edge["type"] == "HAS_TIME" and edge["from"] in self.claim_time_roles:
                claim_id = str(edge["from"])
                role = str(
                    edge.get("time_role")
                    or self.nodes.get(str(edge.get("to") or ""), {}).get("time_role")
                    or "occurred_at"
                )
                self.claim_time_roles[claim_id].add(role)
                value = str(self.nodes.get(str(edge.get("to") or ""), {}).get("value") or "").strip()
                if value:
                    self.claim_time_values[claim_id].setdefault(role, []).append(value)
            elif edge["type"] == "SUPPORTS" and edge["from"] in self.claim_facets and edge["to"] in self.facet_claims:
                claim_id = str(edge["from"])
                facet_id = str(edge["to"])
                self.claim_facets[claim_id].add(facet_id)
                self.facet_claims[facet_id].add(claim_id)
        for facet_id, facet in self.facets.items():
            primary_claim_id = str(facet.get("primary_claim_id") or "")
            if primary_claim_id in self.claim_time_roles:
                self.claim_time_roles[primary_claim_id].add("CURRENT_AFTER")
        self.claim_documents = {
            claim_id: self._claim_document(claim_id)
            for claim_id in self.claims
        }
        self.scope_bm25 = BM25Index(list(self.scopes), [row.get("graph_text", "") for row in self.scopes.values()])
        self.claim_bm25 = BM25Index(list(self.claims), list(self.claim_documents.values()))
        self.scope_dense, self.claim_dense = self._dense_indexes(embedding_config)

    @classmethod
    def from_graph(cls, graph: Mapping[str, Any], embedding_config: EmbeddingConfig | None = None) -> "STSGraphIndex":
        return cls(graph, embedding_config=embedding_config)

    @classmethod
    def load(cls, graph_dir: Path, embedding_config: EmbeddingConfig | None = None) -> "STSGraphIndex":
        graph_path = Path(graph_dir) / "graph.json"
        if not graph_path.is_file():
            raise FileNotFoundError(f"missing STS graph artifact: {graph_path}")
        return cls(json.loads(graph_path.read_text(encoding="utf-8")), embedding_config=embedding_config)

    def _dense_indexes(self, config: EmbeddingConfig | None):
        if config is None:
            empty = _EmptyDenseIndex()
            return empty, empty
        indexes = []
        for name, rows in (("scope", self.scopes), ("claim", self.claims)):
            documents = (
                [self.claim_documents[node_id] for node_id in rows]
                if name == "claim"
                else [str(row.get("graph_text") or "") for row in rows.values()]
            )
            index = OpenAIEmbeddingIndex(
                list(rows),
                documents,
                model=config.model,
                cache_path=Path(config.cache_dir) / f"{name}.json",
                namespace=(
                    "epbench-sts-v2-claim-scope-time-state-v1"
                    if name == "claim"
                    else f"epbench-sts-v2-{name}"
                ),
                batch_size=config.batch_size,
                base_url=config.base_url,
            )
            index.embed_documents()
            indexes.append(index)
        return tuple(indexes)

    def _claim_document(self, claim_id: str) -> str:
        claim = self.claims[claim_id]
        event_id = str(claim.get("source_event_id") or "")
        event = self.events.get(event_id, {})
        scope_values = [
            str(self.scopes[scope_id].get("value") or "")
            for scope_id in self.event_scopes.get(event_id, set())
            if str(self.scopes[scope_id].get("value") or "")
        ]
        return " | ".join(
            value
            for value in (
                str(claim.get("graph_text") or ""),
                str(event.get("graph_text") or ""),
                " ".join(self.event_times.get(event_id, [])),
                " ".join(scope_values),
                " ".join(sorted(self.claim_time_roles.get(claim_id, set()))),
            )
            if value
        )

    def _state_facets_for_anchor_claims(
        self,
        anchor_claim_ids: Sequence[str],
    ) -> list[str]:
        """Fetch StateFacets directly supported by high-ranked Claim anchors only."""
        discovered_facets: list[str] = []
        for claim_id in dict.fromkeys(str(value) for value in anchor_claim_ids):
            if claim_id not in self.claims:
                continue
            for facet_id in self.claim_facets.get(claim_id, set()):
                if facet_id not in discovered_facets:
                    discovered_facets.append(facet_id)
        return discovered_facets

    def _claim_ids_for_events(self, event_ids: Iterable[str]) -> set[str]:
        selected_events = {str(event_id) for event_id in event_ids}
        return {
            claim_id
            for claim_id, claim in self.claims.items()
            if str(claim.get("source_event_id") or "") in selected_events
        }

    def _filter_claims_by_time_roles(
        self,
        claim_ids: Iterable[str],
        time_roles: Sequence[str],
    ) -> set[str]:
        selected = {str(role) for role in time_roles if str(role)}
        candidates = {str(claim_id) for claim_id in claim_ids if str(claim_id) in self.claims}
        if not selected:
            return candidates
        return {
            claim_id
            for claim_id in candidates
            if selected.intersection(self.claim_time_roles.get(claim_id, set()))
        }

    def _time_role_rank_key(
        self,
        claim_id: str,
        time_roles: Sequence[str],
        ordering: str,
        fallback_rank: int,
    ) -> tuple[int, float, int]:
        """Rank Claims within their selected time-role group using normalized timestamps."""
        role_values = self.claim_time_values.get(claim_id, {})
        for role_rank, role in enumerate(time_roles):
            values = role_values.get(str(role), [])
            timestamps = [
                parsed.timestamp()
                for value in values
                if (parsed := parse_anchor_datetime(value)) is not None
            ]
            if timestamps:
                timestamp = max(timestamps) if ordering == "latest" else min(timestamps)
                return role_rank, -timestamp if ordering == "latest" else timestamp, fallback_rank
            if role in self.claim_time_roles.get(claim_id, set()):
                return role_rank, math.inf, fallback_rank
        return len(time_roles), math.inf, fallback_rank

    def _sort_claim_hits_by_time_roles(
        self,
        claim_hits: Sequence[RankedHit],
        time_roles: Sequence[str],
        ordering: str,
    ) -> list[RankedHit]:
        if ordering not in {"latest", "chronological"} or not time_roles:
            return list(claim_hits)
        original_ranks = {hit.doc_id: rank for rank, hit in enumerate(claim_hits)}
        return sorted(
            claim_hits,
            key=lambda item: self._time_role_rank_key(
                item.doc_id,
                time_roles,
                ordering,
                original_ranks[item.doc_id],
            ),
        )

    def _closed_state_facets(
        self,
        discovered_facet_ids: Sequence[str],
        retained_claim_ids: Sequence[str],
    ) -> list[str]:
        retained = set(retained_claim_ids)
        return [
            facet_id
            for facet_id in dict.fromkeys(discovered_facet_ids)
            if self.facet_claims.get(facet_id)
            and self.facet_claims[facet_id].issubset(retained)
        ]

    def retrieve(
        self,
        question: str,
        frame_client: Any | None,
        scope_top_k: int = SCOPE_TOP_K,
        claim_candidate_k: int = CLAIM_CANDIDATE_K,
        scope_backoff_k: int = SCOPE_BACKOFF_K,
        state_anchor_k: int = STATE_ANCHOR_CLAIM_K,
        final_claim_k: int = FINAL_CLAIM_K,
        final_chapter_k: int = FINAL_CHAPTER_K,
        time_role_selector: str = "llm-top2",
        retrieval_policy: str = "scope-claim-time-state",
    ) -> RetrievalResult:
        if retrieval_policy not in CLAIM_RETRIEVAL_POLICIES:
            raise ValueError(
                f"unknown retrieval policy {retrieval_policy!r}; "
                f"expected one of {', '.join(CLAIM_RETRIEVAL_POLICIES)}"
            )
        use_scope = retrieval_policy != "claim"
        use_time = retrieval_policy in {"scope-claim-time", "scope-claim-time-state"}
        use_state = retrieval_policy == "scope-claim-time-state"
        frame = build_question_frame(question, frame_client)
        if not use_time or frame_client is None or time_role_selector == "none":
            time_selection: dict[str, Any] = {
                "time_applicable": False,
                "time_roles": [],
                "source": "selector_disabled",
                "reason": "Time-role selection is disabled.",
            }
        else:
            time_selection = dict(
                select_time_roles(question, frame_client, time_role_selector)
            )
        selected_time_roles = list(dict.fromkeys(time_selection.get("time_roles", [])))[:2]
        time_selection["time_roles"] = selected_time_roles
        time_selection["selected_role_limit"] = 2
        time_selection["selection_policy"] = "highest_confidence_first"
        time_ordering = {
            "newest_first": "latest",
            "oldest_first": "chronological",
        }.get(str(time_selection.get("ordering") or ""), "none")
        time_selection["ordering"] = time_ordering

        chapter_rows: dict[int, dict[str, Any]] = {}

        def chapter_row(event_id: str) -> dict[str, Any]:
            event = self.events[event_id]
            chapter_id = int(event["chapter_id"])
            return chapter_rows.setdefault(
                chapter_id,
                {
                    "event_id": event_id,
                    "score": 0.0,
                    "scope_types": set(),
                    "claims": set(),
                    "states": set(),
                    "evidence": set(),
                    "state_evidence": set(),
                    "relation_evidence": set(),
                    "temporal_rank": math.inf,
                    "contributions": [],
                },
            )

        scope_queries = {
            "entity": frame.entity_queries,
            "location": frame.location_queries,
            "event_type": frame.event_type_queries,
        }
        reliable_event_sets: list[set[str]] = []
        reliable_scope_ids: set[str] = set()
        routed_scope_ids: set[str] = set()
        scope_hits_by_event: dict[str, list[tuple[str, str, float]]] = {}
        semantic_scope_hits: dict[str, tuple[str, float]] = {}
        active_scope_queries: list[tuple[str, str]] = []
        for scope_type, queries in scope_queries.items() if use_scope else ():
            for query in queries:
                if query.casefold() in GENERIC_SCOPE_QUERIES:
                    continue
                active_scope_queries.append((scope_type, query))
                query_tokens = set(_tokens(query))
                allowed_scope_ids = {
                    scope_id
                    for scope_id, scope in self.scopes.items()
                    if str(scope.get("scope_type") or "") == scope_type
                }
                exact_scope_ids = {
                    scope_id
                    for scope_id, scope in self.scopes.items()
                    if query_tokens
                    and (
                        query_tokens.issubset(set(_tokens(scope.get("value"))))
                        or (
                            len(set(_tokens(scope.get("value")))) >= 2
                            and set(_tokens(scope.get("value"))).issubset(query_tokens)
                        )
                    )
                }
                if any(self.scopes[scope_id].get("scope_type") == "event_type" for scope_id in exact_scope_ids):
                    event_type_scope_ids = {
                        scope_id
                        for scope_id, scope in self.scopes.items()
                        if str(scope.get("scope_type") or "") == "event_type"
                    }
                    exact_scope_ids.update(
                        hit.doc_id
                        for hit in hybrid_rank(
                            query,
                            self.scope_bm25,
                            self.scope_dense,
                            scope_top_k,
                            event_type_scope_ids,
                        )
                        if hit.embedding_score >= 0.65
                    )
                if exact_scope_ids:
                    reliable_scope_ids.update(exact_scope_ids)
                    event_ids = set().union(
                        *(self.scope_events.get(scope_id, set()) for scope_id in exact_scope_ids)
                    )
                    if event_ids:
                        reliable_event_sets.append(event_ids)

                scope_hits = hybrid_rank(
                    query,
                    self.scope_bm25,
                    self.scope_dense,
                    scope_top_k,
                    allowed_scope_ids,
                )
                for hit in scope_hits:
                    actual_scope_type = str(
                        self.scopes[hit.doc_id].get("scope_type") or scope_type
                    )
                    previous = semantic_scope_hits.get(hit.doc_id)
                    if previous is None or float(hit.score) > previous[1]:
                        semantic_scope_hits[hit.doc_id] = (
                            actual_scope_type,
                            float(hit.score),
                        )

        ordered_scope_ids = [
            *sorted(reliable_scope_ids),
            *(
                scope_id
                for scope_id, _row in sorted(
                    semantic_scope_hits.items(),
                    key=lambda item: (-item[1][1], item[0]),
                )
                if scope_id not in reliable_scope_ids
            ),
        ][:scope_top_k]
        routed_scope_ids.update(ordered_scope_ids)
        for scope_id in ordered_scope_ids:
            actual_scope_type, semantic_score = semantic_scope_hits.get(
                scope_id,
                (str(self.scopes[scope_id].get("scope_type") or ""), 1.0),
            )
            for event_id in self.scope_events.get(scope_id, set()):
                scope_hits_by_event.setdefault(event_id, []).append(
                    (scope_id, actual_scope_type, semantic_score)
                )

        reliable_time_values: list[str] = []
        reliable_time_event_sets: list[set[str]] = []
        for query in frame.time_values:
            parsed_query = parse_anchor_datetime(query)
            if parsed_query is None:
                continue
            event_ids = {
                event_id
                for event_id, values in self.event_times.items()
                if any(parse_anchor_datetime(value) == parsed_query for value in values)
            }
            if event_ids:
                reliable_time_values.append(query)
                reliable_event_sets.append(event_ids)
                reliable_time_event_sets.append(event_ids)

        reliable_constrained_event_ids = (
            set.intersection(*reliable_event_sets) if reliable_event_sets else set()
        )
        has_explicit_anchor = bool(active_scope_queries or frame.time_values)
        scope_routed_event_ids = set().union(
            *(self.scope_events.get(scope_id, set()) for scope_id in routed_scope_ids)
        ) if routed_scope_ids else set()
        candidate_event_ids = reliable_constrained_event_ids or scope_routed_event_ids
        scoped_claim_ids = (
            self._claim_ids_for_events(candidate_event_ids) if use_scope else set(self.claims)
        )
        time_filtered_scoped_claim_ids = self._filter_claims_by_time_roles(
            scoped_claim_ids,
            selected_time_roles,
        )
        exact_time_event_ids = (
            set.intersection(*reliable_time_event_sets)
            if reliable_time_event_sets
            else set()
        )
        backoff_base_claim_ids = (
            self._claim_ids_for_events(exact_time_event_ids)
            if use_scope and exact_time_event_ids
            else set(self.claims)
        )
        global_time_filtered_claim_ids = self._filter_claims_by_time_roles(
            backoff_base_claim_ids,
            selected_time_roles,
        )
        backoff_hits = (
            rrf_rank(
                question,
                self.claim_bm25,
                self.claim_dense,
                scope_backoff_k,
                global_time_filtered_claim_ids,
            )
            if use_scope
            else []
        )
        backoff_claim_ids = [hit.doc_id for hit in backoff_hits]
        candidate_claim_ids = set(time_filtered_scoped_claim_ids).union(backoff_claim_ids)
        initial_claim_hits = rrf_rank(
            question,
            self.claim_bm25,
            self.claim_dense,
            claim_candidate_k,
            candidate_claim_ids,
        )
        # Claim ranking is finalized before StateFacet access. State evidence is
        # supplementary: it must never add or rerank Claims.
        claim_hits = initial_claim_hits[:final_claim_k]
        state_anchor_claim_ids = [
            hit.doc_id for hit in claim_hits[: min(state_anchor_k, final_claim_k)]
        ] if use_state else []
        if use_state:
            discovered_facet_ids = self._state_facets_for_anchor_claims(
                state_anchor_claim_ids
            )
        else:
            discovered_facet_ids = []
        claim_hits = self._sort_claim_hits_by_time_roles(
            claim_hits,
            selected_time_roles,
            time_ordering,
        )
        selected_claim_ids = [hit.doc_id for hit in claim_hits]
        selected_facet_ids = self._closed_state_facets(
            discovered_facet_ids,
            selected_claim_ids,
        )

        state_lines = {
            facet_id: str(self.facets[facet_id].get("graph_text") or "").strip()
            for facet_id in selected_facet_ids
        }
        for temporal_rank, hit in enumerate(claim_hits):
            claim = self.claims[hit.doc_id]
            event_id = str(claim["source_event_id"])
            if event_id not in self.events:
                continue
            row = chapter_row(event_id)
            row["score"] += hit.score
            row["claims"].add(hit.doc_id)
            row["temporal_rank"] = min(row["temporal_rank"], temporal_rank)
            for evidence_span in claim.get("evidence_spans", []):
                if evidence_span:
                    row["evidence"].add(str(evidence_span))
            row["contributions"].append({"layer": "claim", "doc_id": hit.doc_id, "score": hit.score})
            for facet_id in self.claim_facets.get(hit.doc_id, set()):
                if facet_id in selected_facet_ids:
                    row["states"].add(facet_id)
                    if state_lines.get(facet_id):
                        row["state_evidence"].add(state_lines[facet_id])

        for row in chapter_rows.values():
            for scope_id, actual_scope_type, scope_score in scope_hits_by_event.get(
                row["event_id"], []
            ):
                row["scope_types"].add(actual_scope_type)
                row["contributions"].append(
                    {
                        "layer": "scope",
                        "scope_type": actual_scope_type,
                        "doc_id": scope_id,
                        "score": scope_score,
                    }
                )

        for row in chapter_rows.values():
            coverage_bonus = len(row["scope_types"]) * SCOPE_TYPE_COVERAGE_WEIGHT
            row["score"] += coverage_bonus
            if coverage_bonus:
                row["contributions"].append({"layer": "scope_type_coverage", "score": coverage_bonus})
            event_times = self.event_times.get(row["event_id"], [])
            if frame.time_values and any(query.casefold() in value.casefold() for query in frame.time_values for value in event_times):
                row["score"] += TIME_COMPATIBILITY_WEIGHT
                row["contributions"].append({"layer": "time", "score": TIME_COMPATIBILITY_WEIGHT})

        ranked: list[RankedChapter] = []
        for chapter_id, row in chapter_rows.items():
            event = self.events[row["event_id"]]
            raw_time = self.event_times.get(row["event_id"], [""])[0] if self.event_times.get(row["event_id"]) else ""
            parsed = parse_anchor_datetime(raw_time)
            occurred_at = parsed.isoformat() if parsed else raw_time
            ranked.append(
                RankedChapter(
                    chapter_id=chapter_id,
                    score=float(row["score"]),
                    occurred_at=occurred_at,
                    matched_scope_types=sorted(row["scope_types"]),
                    selected_claim_ids=sorted(row["claims"]),
                    selected_state_ids=sorted(row["states"]),
                    evidence_spans=sorted(row["evidence"]),
                    state_evidence=sorted(row["state_evidence"]),
                    relation_evidence=sorted(row["relation_evidence"]),
                    raw_text=str(event.get("raw_text") or ""),
                    contributions=row["contributions"],
                    scope_values={
                        scope_type: sorted(
                            str(self.scopes[scope_id].get("value") or "")
                            for scope_id in self.event_scopes.get(row["event_id"], set())
                            if self.scopes[scope_id].get("scope_type") == scope_type
                            and self.scopes[scope_id].get("value")
                        )
                        for scope_type in ("entity", "location", "event_type")
                    },
                    entity_roles={
                        role: sorted(value for value in values if value)
                        for role, values in self.event_entity_roles.get(row["event_id"], {}).items()
                    },
                )
            )
        ranked.sort(key=lambda row: (-row.score, row.chapter_id))
        ranked = ranked[:final_chapter_k]
        if time_ordering in {"latest", "chronological"} and selected_time_roles:
            chapter_temporal_ranks = {
                chapter_id: int(row["temporal_rank"])
                for chapter_id, row in chapter_rows.items()
            }
            ranked.sort(
                key=lambda row: (chapter_temporal_ranks[row.chapter_id], row.chapter_id)
            )
        return RetrievalResult(
            question=question,
            frame=frame,
            ranked_chapters=ranked,
            retrieval_status=(
                "anchor_constrained"
                if reliable_constrained_event_ids
                else "scope_routed"
                if scope_routed_event_ids
                else "scope_backoff"
                if backoff_claim_ids
                else "no_candidates"
            ),
            trace={
                "retrieval_policy": retrieval_policy,
                "scope_top_k": scope_top_k,
                "event_retrieval_mode": "source_event_evidence_only",
                "claim_candidate_k": claim_candidate_k,
                "scope_backoff_k": scope_backoff_k,
                "state_anchor_k": state_anchor_k,
                "final_claim_k": final_claim_k,
                "final_chapter_k": final_chapter_k,
                "claim_retrieval_mode": (
                    "scope_time_hard_filter_bm25_dense_rrf_statefacet_support"
                    if use_state
                    else "global_claim_bm25_dense_rrf"
                    if not use_scope
                    else "scope_claim_time_hard_filter_bm25_dense_rrf"
                    if use_time
                    else "scope_claim_bm25_dense_rrf"
                ),
                "claim_rrf_k": CLAIM_RRF_K,
                "time_role_selection": time_selection,
                "time_hard_filter_applied": bool(selected_time_roles),
                "time_role_sorting": {
                    "applied": bool(selected_time_roles)
                    and time_ordering in {"latest", "chronological"},
                    "ordering": time_ordering,
                    "role_priority": selected_time_roles,
                    "claim_ids": selected_claim_ids,
                },
                "routed_scope_ids": sorted(routed_scope_ids),
                "scope_candidate_claim_count": len(scoped_claim_ids),
                "time_filtered_scope_claim_count": len(time_filtered_scoped_claim_ids),
                "backoff_claim_ids": backoff_claim_ids,
                "state_anchor_claim_ids": state_anchor_claim_ids,
                "claim_reranked_ids": selected_claim_ids,
                "selected_state_ids": selected_facet_ids,
                "selected_relation_edges": [],
                "source_event_ids": sorted(
                    {
                        str(self.claims[claim_id].get("source_event_id") or "")
                        for claim_id in selected_claim_ids
                        if str(self.claims[claim_id].get("source_event_id") or "")
                    }
                ),
                "reliable_scope_ids": sorted(reliable_scope_ids),
                "reliable_time_values": reliable_time_values,
                "exact_time_event_ids": sorted(exact_time_event_ids),
                "constrained_event_ids": sorted(reliable_constrained_event_ids),
                "has_explicit_anchor": has_explicit_anchor,
            },
        )


__all__ = [
    "BM25Index",
    "CLAIM_RETRIEVAL_POLICIES",
    "EmbeddingConfig",
    "QuestionFrame",
    "RankedChapter",
    "RankedHit",
    "RetrievalResult",
    "STSGraphIndex",
    "build_question_frame",
    "hybrid_rank",
    "rrf_rank",
]

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

from .config import (
    CLAIM_CANDIDATE_K,
    EMBEDDING_MODEL,
    EMBEDDING_SCORE_WEIGHT,
    EVENT_CANDIDATE_K,
    FINAL_CHAPTER_K,
    SCOPE_TOP_K,
    SCOPE_TYPE_COVERAGE_WEIGHT,
    TIME_COMPATIBILITY_WEIGHT,
)


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: object) -> list[str]:
    return TOKEN_RE.findall(str(text or "").casefold())


def _grounded_scope_match(query: object, scope_value: object) -> bool:
    query_tokens = _tokens(query)
    scope_tokens = _tokens(scope_value)
    if not query_tokens or not scope_tokens:
        return False
    query_set = set(query_tokens)
    scope_set = set(scope_tokens)
    return query_set.issubset(scope_set)


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


@dataclass(frozen=True)
class QuestionFrame:
    ordering: str = "none"
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
            "Frame a question for STS retrieval using only explicitly named anchors in the question. Do not infer or expand entities, locations, or event types. Return one JSON object with ordering, time_values, entity_queries, location_queries, and event_type_queries.",
            question,
        )
        forbidden = {"answer", "correct_answer", "correct_answer_chapters", "gold", "reference"}
        if forbidden.intersection(raw):
            raise ValueError("question frame contains evaluator-only fields")
    ordering = str(raw.get("ordering") or "none").strip().lower()
    if ordering not in {"none", "latest", "chronological"}:
        ordering = "none"
    normalized_question = question.casefold()
    if re.search(r"\b(latest|most recent|newest)\b", normalized_question):
        ordering = "latest"
    elif re.search(r"\b(chronological|in (?:time )?order)\b", normalized_question):
        ordering = "chronological"
    return QuestionFrame(
        ordering=ordering,
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
        self.scope_events: dict[str, set[str]] = {scope_id: set() for scope_id in self.scopes}
        self.event_claims: dict[str, list[str]] = {event_id: [] for event_id in self.events}
        self.event_times: dict[str, list[str]] = {event_id: [] for event_id in self.events}
        for edge in self.edges:
            if edge["type"] in {"IN_SCOPE", "MENTIONS"} and edge["to"] in self.scope_events:
                self.scope_events[edge["to"]].add(str(edge["from"]))
            elif edge["type"] == "ASSERTS" and edge["from"] in self.event_claims:
                self.event_claims[edge["from"]].append(str(edge["to"]))
            elif edge["type"] == "OCCURRED_AT" and edge["from"] in self.event_times:
                value = self.nodes.get(str(edge["to"]), {}).get("value")
                if value:
                    self.event_times[edge["from"]].append(str(value))
        self.scope_bm25 = BM25Index(list(self.scopes), [row.get("graph_text", "") for row in self.scopes.values()])
        self.event_bm25 = BM25Index(list(self.events), [row.get("graph_text", "") for row in self.events.values()])
        self.claim_bm25 = BM25Index(list(self.claims), [row.get("graph_text", "") for row in self.claims.values()])
        self.scope_dense, self.event_dense, self.claim_dense = self._dense_indexes(embedding_config)

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
            return empty, empty, empty
        indexes = []
        for name, rows in (("scope", self.scopes), ("event", self.events), ("claim", self.claims)):
            index = OpenAIEmbeddingIndex(
                list(rows),
                [str(row.get("graph_text") or "") for row in rows.values()],
                model=config.model,
                cache_path=Path(config.cache_dir) / f"{name}.json",
                namespace=f"epbench-sts-v2-{name}",
                batch_size=config.batch_size,
                base_url=config.base_url,
            )
            index.embed_documents()
            indexes.append(index)
        return tuple(indexes)

    def retrieve(
        self,
        question: str,
        frame_client: Any | None,
        scope_top_k: int = SCOPE_TOP_K,
        event_candidate_k: int = EVENT_CANDIDATE_K,
        claim_candidate_k: int = CLAIM_CANDIDATE_K,
        final_chapter_k: int = FINAL_CHAPTER_K,
    ) -> RetrievalResult:
        frame = build_question_frame(question, frame_client)
        chapter_rows: dict[int, dict[str, Any]] = {}

        def chapter_row(event_id: str) -> dict[str, Any]:
            event = self.events[event_id]
            chapter_id = int(event["chapter_id"])
            return chapter_rows.setdefault(
                chapter_id,
                {"event_id": event_id, "score": 0.0, "scope_types": set(), "claims": set(), "evidence": set(), "contributions": []},
            )

        scope_queries = {
            "entity": frame.entity_queries,
            "location": frame.location_queries,
            "event_type": frame.event_type_queries,
        }
        has_scope_anchors = any(queries for queries in scope_queries.values())
        matched_scope_ids_by_query: dict[tuple[str, str], set[str]] = {}
        grounded_event_sets: list[set[str]] = []
        unmatched_anchors: list[dict[str, str]] = []
        for scope_type, queries in scope_queries.items():
            typed_scopes = {
                scope_id: scope
                for scope_id, scope in self.scopes.items()
                if scope.get("scope_type") == scope_type
            }
            for query in queries:
                matched_scope_ids = {
                    scope_id
                    for scope_id, scope in typed_scopes.items()
                    if _grounded_scope_match(query, scope.get("value"))
                }
                matched_scope_ids_by_query[(scope_type, query)] = matched_scope_ids
                if not matched_scope_ids:
                    unmatched_anchors.append({"scope_type": scope_type, "query": query})
                    continue
                grounded_event_sets.append(
                    set().union(*(self.scope_events.get(scope_id, set()) for scope_id in matched_scope_ids))
                )

        grounded_event_ids: set[str] | None = None
        if has_scope_anchors:
            if unmatched_anchors:
                return RetrievalResult(
                    question=question,
                    frame=frame,
                    ranked_chapters=[],
                    retrieval_status="no_grounded_scope",
                    trace={
                        "scope_top_k": scope_top_k,
                        "event_candidate_k": event_candidate_k,
                        "claim_candidate_k": claim_candidate_k,
                        "final_chapter_k": final_chapter_k,
                        "unmatched_anchors": unmatched_anchors,
                        "grounded_scope_ids": sorted(
                            set().union(*matched_scope_ids_by_query.values())
                            if matched_scope_ids_by_query
                            else set()
                        ),
                    },
                )
            grounded_event_ids = set.intersection(*grounded_event_sets) if grounded_event_sets else set()
            if not grounded_event_ids:
                return RetrievalResult(
                    question=question,
                    frame=frame,
                    ranked_chapters=[],
                    retrieval_status="no_grounded_scope",
                    trace={
                        "scope_top_k": scope_top_k,
                        "event_candidate_k": event_candidate_k,
                        "claim_candidate_k": claim_candidate_k,
                        "final_chapter_k": final_chapter_k,
                        "unmatched_anchors": [],
                        "grounded_scope_ids": sorted(set().union(*matched_scope_ids_by_query.values())),
                        "reason": "grounded anchors do not co-occur in one event",
                    },
                )

        for scope_type, queries in scope_queries.items():
            for query in queries:
                allowed = matched_scope_ids_by_query[(scope_type, query)]
                for hit in hybrid_rank(query, self.scope_bm25, self.scope_dense, scope_top_k, allowed):
                    for event_id in self.scope_events.get(hit.doc_id, set()):
                        if grounded_event_ids is not None and event_id not in grounded_event_ids:
                            continue
                        row = chapter_row(event_id)
                        row["score"] += hit.score
                        row["scope_types"].add(scope_type)
                        row["contributions"].append({"layer": "scope", "scope_type": scope_type, "doc_id": hit.doc_id, "score": hit.score})

        for hit in hybrid_rank(
            question,
            self.event_bm25,
            self.event_dense,
            event_candidate_k,
            grounded_event_ids,
        ):
            row = chapter_row(hit.doc_id)
            row["score"] += hit.score
            row["contributions"].append({"layer": "event", "doc_id": hit.doc_id, "score": hit.score})
        allowed_claim_ids = (
            {
                claim_id
                for claim_id, claim in self.claims.items()
                if str(claim.get("source_event_id")) in grounded_event_ids
            }
            if grounded_event_ids is not None
            else None
        )
        for hit in hybrid_rank(
            question,
            self.claim_bm25,
            self.claim_dense,
            claim_candidate_k,
            allowed_claim_ids,
        ):
            claim = self.claims[hit.doc_id]
            event_id = str(claim["source_event_id"])
            row = chapter_row(event_id)
            row["score"] += hit.score
            row["claims"].add(hit.doc_id)
            if claim.get("evidence_span"):
                row["evidence"].add(str(claim["evidence_span"]))
            row["contributions"].append({"layer": "claim", "doc_id": hit.doc_id, "score": hit.score})

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
                    evidence_spans=sorted(row["evidence"]),
                    raw_text=str(event.get("raw_text") or ""),
                    contributions=row["contributions"],
                )
            )
        ranked.sort(key=lambda row: (-row.score, row.chapter_id))
        ranked = ranked[:final_chapter_k]
        if frame.ordering == "latest":
            ranked.sort(key=lambda row: (row.occurred_at, row.score), reverse=True)
        elif frame.ordering == "chronological":
            ranked.sort(key=lambda row: (row.occurred_at or "9999", -row.score, row.chapter_id))
        return RetrievalResult(
            question=question,
            frame=frame,
            ranked_chapters=ranked,
            retrieval_status=("grounded" if has_scope_anchors else "unanchored"),
            trace={
                "scope_top_k": scope_top_k,
                "event_candidate_k": event_candidate_k,
                "claim_candidate_k": claim_candidate_k,
                "final_chapter_k": final_chapter_k,
                "unmatched_anchors": [],
                "grounded_scope_ids": sorted(
                    set().union(*matched_scope_ids_by_query.values())
                    if matched_scope_ids_by_query
                    else set()
                ),
                "grounded_event_ids": sorted(grounded_event_ids or []),
            },
        )


__all__ = [
    "BM25Index",
    "EmbeddingConfig",
    "QuestionFrame",
    "RankedChapter",
    "RankedHit",
    "RetrievalResult",
    "STSGraphIndex",
    "build_question_frame",
    "hybrid_rank",
]

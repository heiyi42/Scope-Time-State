from __future__ import annotations

from collections.abc import Iterable as ABCIterable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Set, Tuple

import networkx as nx


NODE_EVENT = "Episode/Event"
NODE_CLAIM = "Claim"
NODE_STATE_FACET = "State Facet"
NODE_ENTITY_SCOPE = "Entity/Scope"
NODE_TIME = "Time"

EDGE_EVENT_MENTIONS_ENTITY = "event_mentions_entity"
EDGE_EVENT_IN_SCOPE = "event_in_scope"
EDGE_CLAIM_SUPPORTED_BY_EVENT = "claim_supported_by_event"
EDGE_CLAIM_CORRECTS_CLAIM = "claim_corrects_claim"
EDGE_CLAIM_SUPERSEDES_CLAIM = "claim_supersedes_claim"
EDGE_CLAIM_CONFLICTS_WITH_CLAIM = "claim_conflicts_with_claim"
EDGE_FACET_SUPPORTED_BY_CLAIM = "facet_supported_by_claim"
EDGE_FACET_CURRENT_AFTER_TIME = "facet_current_after_time"

ALLOWED_NODE_TYPES = {
    NODE_EVENT,
    NODE_CLAIM,
    NODE_STATE_FACET,
    NODE_ENTITY_SCOPE,
    NODE_TIME,
}

ALLOWED_EDGE_TYPES = {
    EDGE_EVENT_MENTIONS_ENTITY,
    EDGE_EVENT_IN_SCOPE,
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_CLAIM_CORRECTS_CLAIM,
    EDGE_CLAIM_SUPERSEDES_CLAIM,
    EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
    EDGE_FACET_SUPPORTED_BY_CLAIM,
    EDGE_FACET_CURRENT_AFTER_TIME,
}

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

UPDATE_MARKERS = {
    "actually",
    "changed",
    "instead",
    "moved",
    "new",
    "no longer",
    "now",
    "rather",
    "switched",
    "updated",
}

CORRECTION_MARKERS = {
    "actually",
    "correction",
    "i mean",
    "instead",
    "rather",
    "sorry",
}

NEGATION_MARKERS = {"not", "never", "no longer", "don't", "do not", "isn't", "wasn't", "without"}

QUESTION_TYPE_SCOPES = {
    "knowledge-update": "knowledge_update",
    "multi-session": "multi_session_synthesis",
    "single-session-assistant": "assistant_memory",
    "single-session-preference": "preference_grounding",
    "single-session-user": "user_fact",
    "temporal-reasoning": "temporal_reasoning",
}


@dataclass(frozen=True)
class NormalizedTurn:
    role: str
    content: str


@dataclass(frozen=True)
class NormalizedSession:
    session_id: str
    date: str
    turns: Tuple[NormalizedTurn, ...]
    order: int


class GraphExtractionBackend(Protocol):
    def extract_batch(
        self,
        batch_events: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str,
        question_date: str,
        previous_claims: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        """Extract graph claims and claim relations for one event batch."""


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def normalize_label(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_']+", text.lower())


def important_terms(text: str, limit: int = 12) -> List[str]:
    terms: List[str] = []
    seen: Set[str] = set()
    for term in tokenize(text):
        if len(term) <= 2 or term in STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def parse_sort_key(date_text: str, fallback_order: int) -> Tuple[int, str]:
    match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:.*?(\d{1,2}):(\d{2}))?", date_text)
    if not match:
        return fallback_order, date_text
    year, month, day, hour, minute = match.groups()
    hour = hour or "0"
    minute = minute or "0"
    try:
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
        return int(dt.timestamp()), dt.isoformat(timespec="minutes")
    except ValueError:
        return fallback_order, date_text


def split_claim_sentences(text: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    pieces = re.split(r"(?<=[.!?。！？])\s+|\n+", cleaned)
    claims: List[str] = []
    for piece in pieces:
        piece = piece.strip(" -\t\r\n")
        if len(piece) < 12:
            continue
        claims.append(piece[:800])
        if len(claims) >= 4:
            break
    return claims


def has_any_marker(text: str, markers: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def has_focus_overlap(left: Set[str], right: Set[str]) -> bool:
    return bool(left and right and left.intersection(right))


class TaskSemanticsLocalGraphBuilder:
    """Build a per-question local Scope-Time-State graph from candidate sessions.

    The current implementation is deterministic and local. It exposes a stable
    graph schema so that later iterations can replace heuristic claim extraction
    with an LLM batch extractor without changing retrieval code.
    """

    def __init__(self, batch_size: int = 5, max_facets: int = 12, extractor: Optional["GraphExtractionBackend"] = None) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if max_facets < 1:
            raise ValueError("max_facets must be >= 1")
        self.batch_size = batch_size
        self.max_facets = max_facets
        self.extractor = extractor

    def build(
        self,
        sessions: Sequence[Mapping[str, Any]],
        question: str,
        question_type: str = "",
        question_date: str = "",
    ) -> nx.MultiDiGraph:
        normalized = self._normalize_sessions(sessions)
        normalized = sorted(normalized, key=lambda item: parse_sort_key(item.date, item.order))

        graph = nx.MultiDiGraph()
        graph.graph["schema"] = {
            "node_types": sorted(ALLOWED_NODE_TYPES),
            "edge_types": sorted(ALLOWED_EDGE_TYPES),
            "method": "task_semantics_local_graph",
        }
        graph.graph["question"] = question
        graph.graph["question_type"] = question_type
        graph.graph["question_date"] = question_date

        latest_time_node = self._add_latest_time_node(graph, normalized, question_date)
        graph.graph["latest_time_node"] = latest_time_node

        focus_terms = set(important_terms(question, limit=16))

        if self.extractor is not None:
            claim_order = self._ingest_sessions_with_extractor(
                graph,
                normalized,
                question,
                question_type,
                question_date,
                focus_terms,
                latest_time_node,
            )
            if not self._has_state_facets(graph):
                self._materialize_state_facets(graph, claim_order, focus_terms, latest_time_node)
        else:
            previous_claim_ids: List[str] = []
            claim_order: List[str] = []
            for start in range(0, len(normalized), self.batch_size):
                batch = normalized[start : start + self.batch_size]
                for session in batch:
                    claim_ids = self._ingest_session(graph, session, question, question_type, focus_terms)
                    self._connect_claim_relations(graph, claim_ids, previous_claim_ids)
                    previous_claim_ids.extend(claim_ids)
                    claim_order.extend(claim_ids)
            self._materialize_state_facets(graph, claim_order, focus_terms, latest_time_node)
        return graph

    def _has_state_facets(self, graph: nx.MultiDiGraph) -> bool:
        return any(data.get("node_type") == NODE_STATE_FACET for _, data in graph.nodes(data=True))

    def _ingest_sessions_with_extractor(
        self,
        graph: nx.MultiDiGraph,
        sessions: Sequence[NormalizedSession],
        question: str,
        question_type: str,
        question_date: str,
        focus_terms: Set[str],
        latest_time_node: str,
    ) -> List[str]:
        event_records = self._add_event_nodes_for_extractor(graph, sessions, question, question_type, focus_terms)
        event_by_id = {item["event_id"]: item for item in event_records}
        previous_claims: List[Dict[str, Any]] = []
        claim_order: List[str] = []
        claim_ref_to_id: Dict[str, str] = {}

        for start in range(0, len(event_records), self.batch_size):
            batch_events = event_records[start : start + self.batch_size]
            extraction = self.extractor.extract_batch(
                batch_events=batch_events,
                question=question,
                question_type=question_type,
                question_date=question_date,
                previous_claims=previous_claims[-80:],
            )
            batch_claim_refs: Dict[str, str] = {}
            for index, raw_claim in enumerate(extraction.get("claims") or []):
                if not isinstance(raw_claim, Mapping):
                    continue
                event_id = str(raw_claim.get("event_id", ""))
                if event_id not in event_by_id:
                    continue
                claim_text = str(raw_claim.get("claim") or raw_claim.get("text") or "").strip()
                if not claim_text:
                    continue
                claim_ref = str(raw_claim.get("claim_ref") or raw_claim.get("id") or f"batch_{start}_{index}")
                scope_labels = self._normalized_label_list(raw_claim.get("scope_labels") or raw_claim.get("scopes"))
                entity_labels = self._normalized_label_list(raw_claim.get("entity_labels") or raw_claim.get("entities"))
                if not scope_labels:
                    scope_labels = self._extract_scopes(question, question_type, claim_text)
                if not entity_labels:
                    entity_labels = self._extract_entities(question, claim_text, focus_terms)

                event_record = event_by_id[event_id]
                self._connect_event_semantics(graph, event_id, entity_labels, scope_labels)
                claim_id = stable_id("claim", f"{event_id}:{claim_ref}:{claim_text}")
                claim_terms = set(important_terms(claim_text, limit=16))
                self._add_node(
                    graph,
                    claim_id,
                    NODE_CLAIM,
                    text=claim_text,
                    session_id=event_record["session_id"],
                    event_id=event_id,
                    role=event_record["role"],
                    date=event_record["date"],
                    parsed_date=event_record["parsed_date"],
                    sort_key=int(event_record["sort_key"]) * 10 + index,
                    terms=sorted(claim_terms),
                    entity_labels=entity_labels,
                    scope_labels=scope_labels,
                    has_update_marker=has_any_marker(claim_text, UPDATE_MARKERS),
                    has_correction_marker=has_any_marker(claim_text, CORRECTION_MARKERS),
                    has_negation_marker=has_any_marker(claim_text, NEGATION_MARKERS),
                    source="llm_extractor",
                    claim_ref=claim_ref,
                )
                self._add_edge(graph, claim_id, event_id, EDGE_CLAIM_SUPPORTED_BY_EVENT)
                claim_order.append(claim_id)
                batch_claim_refs[claim_ref] = claim_id
                claim_ref_to_id[claim_ref] = claim_id

                facet = raw_claim.get("state_facet")
                is_current = bool(raw_claim.get("is_current") or raw_claim.get("current") or raw_claim.get("supports_current_state"))
                defer_facet_materialization = hasattr(self.extractor, "extract_state_facets")
                if isinstance(facet, Mapping) and is_current and not defer_facet_materialization:
                    self._materialize_llm_facet(graph, claim_id, facet, latest_time_node)

                previous_claims.append(
                    {
                        "claim_id": claim_id,
                        "claim_ref": claim_ref,
                        "claim": claim_text,
                        "scope_labels": scope_labels,
                        "entity_labels": entity_labels,
                        "session_id": event_record["session_id"],
                        "date": event_record["date"],
                    }
                )

            self._add_extracted_relations(graph, extraction.get("relations") or [], claim_ref_to_id, batch_claim_refs, previous_claims)
        if hasattr(self.extractor, "extract_state_facets"):
            self._materialize_extractor_state_facets(
                graph,
                question,
                question_type,
                question_date,
                previous_claims,
                claim_ref_to_id,
                latest_time_node,
            )
        return claim_order

    def _add_event_nodes_for_extractor(
        self,
        graph: nx.MultiDiGraph,
        sessions: Sequence[NormalizedSession],
        question: str,
        question_type: str,
        focus_terms: Set[str],
    ) -> List[Dict[str, Any]]:
        event_records: List[Dict[str, Any]] = []
        for session in sessions:
            session_sort_key, parsed_date = parse_sort_key(session.date, session.order)
            for turn_index, turn in enumerate(session.turns):
                event_id = f"event:{session.session_id}:{turn_index}"
                sort_key = session_sort_key * 1000 + turn_index
                self._add_node(
                    graph,
                    event_id,
                    NODE_EVENT,
                    session_id=session.session_id,
                    role=turn.role,
                    text=turn.content,
                    date=session.date,
                    parsed_date=parsed_date,
                    sort_key=sort_key,
                )
                event_records.append(
                    {
                        "event_id": event_id,
                        "session_id": session.session_id,
                        "role": turn.role,
                        "text": turn.content,
                        "date": session.date,
                        "parsed_date": parsed_date,
                        "sort_key": sort_key,
                    }
                )
        return event_records

    def _connect_event_semantics(
        self,
        graph: nx.MultiDiGraph,
        event_id: str,
        entity_labels: Sequence[str],
        scope_labels: Sequence[str],
    ) -> None:
        for entity in entity_labels:
            entity_id = stable_id("entity", entity)
            self._add_node(graph, entity_id, NODE_ENTITY_SCOPE, subtype="entity", label=entity)
            self._add_edge(graph, event_id, entity_id, EDGE_EVENT_MENTIONS_ENTITY)
        for scope in scope_labels:
            scope_id = stable_id("scope", scope)
            self._add_node(graph, scope_id, NODE_ENTITY_SCOPE, subtype="scope", label=scope)
            self._add_edge(graph, event_id, scope_id, EDGE_EVENT_IN_SCOPE)

    def _normalized_label_list(self, value: Any) -> List[str]:
        if isinstance(value, str):
            raw_items = [value]
        elif isinstance(value, ABCIterable):
            raw_items = [str(item) for item in value if item not in {None, ""}]
        else:
            raw_items = []
        labels: List[str] = []
        for item in raw_items:
            label = normalize_label(item)
            if label and label not in labels:
                labels.append(label)
        return labels

    def _materialize_llm_facet(
        self,
        graph: nx.MultiDiGraph,
        claim_id: str,
        facet: Mapping[str, Any],
        latest_time_node: str,
    ) -> None:
        name = normalize_label(str(facet.get("name") or "task_state"))
        value = str(facet.get("value") or graph.nodes[claim_id].get("text", ""))
        facet_id = stable_id("facet", f"{name}:{value}:{claim_id}")
        self._add_node(
            graph,
            facet_id,
            NODE_STATE_FACET,
            name=name,
            value=value,
            claim_id=claim_id,
            session_id=graph.nodes[claim_id].get("session_id"),
            current_after=graph.nodes[claim_id].get("parsed_date") or graph.nodes[claim_id].get("date") or "",
            source="llm_extractor",
        )
        self._add_edge(graph, facet_id, claim_id, EDGE_FACET_SUPPORTED_BY_CLAIM)
        self._add_edge(graph, facet_id, latest_time_node, EDGE_FACET_CURRENT_AFTER_TIME)

    def _materialize_extractor_state_facets(
        self,
        graph: nx.MultiDiGraph,
        question: str,
        question_type: str,
        question_date: str,
        previous_claims: Sequence[Mapping[str, Any]],
        claim_ref_to_id: Mapping[str, str],
        latest_time_node: str,
    ) -> None:
        state = self.extractor.extract_state_facets(
            claims=previous_claims,
            question=question,
            question_type=question_type,
            question_date=question_date,
        )
        self._add_extracted_relations(
            graph,
            state.get("relations") or [],
            claim_ref_to_id,
            claim_ref_to_id,
            previous_claims,
        )
        for raw_rejected in state.get("rejected_claims") or []:
            if not isinstance(raw_rejected, Mapping):
                continue
            rejected_id = str(raw_rejected.get("claim_id") or "")
            rejected_by_id = str(raw_rejected.get("rejected_by_claim_id") or raw_rejected.get("active_claim_id") or "")
            if not rejected_id or not rejected_by_id or rejected_id == rejected_by_id:
                continue
            if not graph.has_node(rejected_id) or not graph.has_node(rejected_by_id):
                continue
            reason = normalize_label(str(raw_rejected.get("reason") or "stale"))
            edge_type = EDGE_CLAIM_SUPERSEDES_CLAIM if reason == "stale" else EDGE_CLAIM_CORRECTS_CLAIM
            self._add_edge(
                graph,
                rejected_by_id,
                rejected_id,
                edge_type,
                reason=str(raw_rejected.get("reason") or "llm_rejected_claim"),
            )

        for index, raw_facet in enumerate(state.get("state_facets") or []):
            if not isinstance(raw_facet, Mapping):
                continue
            name = normalize_label(str(raw_facet.get("name") or "task_state"))
            value = str(raw_facet.get("value") or "").strip()
            support_claim_ids = [
                str(item)
                for item in raw_facet.get("support_claim_ids") or raw_facet.get("claim_ids") or []
                if item
            ]
            support_claim_ids = [claim_id for claim_id in support_claim_ids if graph.has_node(claim_id)]
            if not value or not support_claim_ids:
                continue
            facet_id = stable_id("facet", f"final:{index}:{name}:{value}:{','.join(support_claim_ids)}")
            self._add_node(
                graph,
                facet_id,
                NODE_STATE_FACET,
                name=name,
                value=value,
                claim_id=support_claim_ids[0],
                session_id=graph.nodes[support_claim_ids[0]].get("session_id"),
                current_after=graph.nodes[support_claim_ids[0]].get("parsed_date") or graph.nodes[support_claim_ids[0]].get("date") or "",
                source="llm_state_reconcile",
            )
            for claim_id in support_claim_ids:
                self._add_edge(graph, facet_id, claim_id, EDGE_FACET_SUPPORTED_BY_CLAIM)
            self._add_edge(graph, facet_id, latest_time_node, EDGE_FACET_CURRENT_AFTER_TIME)

    def _add_extracted_relations(
        self,
        graph: nx.MultiDiGraph,
        raw_relations: Any,
        claim_ref_to_id: Mapping[str, str],
        batch_claim_refs: Mapping[str, str],
        previous_claims: Sequence[Mapping[str, Any]],
    ) -> None:
        if not isinstance(raw_relations, ABCIterable):
            return
        for relation in raw_relations:
            if not isinstance(relation, Mapping):
                continue
            source = self._resolve_relation_claim_id(relation, "source", claim_ref_to_id, batch_claim_refs, previous_claims)
            target = self._resolve_relation_claim_id(relation, "target", claim_ref_to_id, batch_claim_refs, previous_claims)
            if not source or not target or source == target:
                continue
            relation_type = normalize_label(str(relation.get("type") or relation.get("relation") or ""))
            edge_type = {
                "corrects": EDGE_CLAIM_CORRECTS_CLAIM,
                "correct": EDGE_CLAIM_CORRECTS_CLAIM,
                "supersedes": EDGE_CLAIM_SUPERSEDES_CLAIM,
                "supersede": EDGE_CLAIM_SUPERSEDES_CLAIM,
                "conflicts": EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
                "conflict": EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
            }.get(relation_type)
            if edge_type is None:
                continue
            self._add_edge(
                graph,
                source,
                target,
                edge_type,
                reason=str(relation.get("reason") or "llm_extracted_relation"),
            )

    def _resolve_relation_claim_id(
        self,
        relation: Mapping[str, Any],
        side: str,
        claim_ref_to_id: Mapping[str, str],
        batch_claim_refs: Mapping[str, str],
        previous_claims: Sequence[Mapping[str, Any]],
    ) -> Optional[str]:
        direct_id = relation.get(f"{side}_claim_id")
        if direct_id and direct_id in claim_ref_to_id.values():
            return str(direct_id)
        ref = str(relation.get(f"{side}_claim_ref") or relation.get(f"{side}") or "")
        if ref in claim_ref_to_id:
            return claim_ref_to_id[ref]
        if ref in batch_claim_refs:
            return batch_claim_refs[ref]
        text = str(relation.get(f"{side}_claim") or relation.get(f"{side}_claim_text") or "")
        if text:
            normalized_text = normalize_label(text)[:80]
            for claim in reversed(previous_claims):
                candidate_text = normalize_label(str(claim.get("claim", "")))[:80]
                if normalized_text and (normalized_text in candidate_text or candidate_text in normalized_text):
                    return str(claim.get("claim_id"))
        return None

    def _normalize_sessions(self, sessions: Sequence[Mapping[str, Any]]) -> List[NormalizedSession]:
        normalized: List[NormalizedSession] = []
        for order, raw in enumerate(sessions):
            session_id = str(raw.get("session_id") or raw.get("id") or f"session_{order}")
            date = str(raw.get("date") or raw.get("session_date") or raw.get("created_at") or "")
            raw_turns = raw.get("turns") or raw.get("session") or raw.get("messages") or []
            turns: List[NormalizedTurn] = []
            for raw_turn in raw_turns:
                if isinstance(raw_turn, Mapping):
                    role = str(raw_turn.get("role", "unknown"))
                    content = str(raw_turn.get("content", ""))
                else:
                    role = "unknown"
                    content = str(raw_turn)
                if content.strip():
                    turns.append(NormalizedTurn(role=role, content=content.strip()))
            normalized.append(
                NormalizedSession(
                    session_id=session_id,
                    date=date,
                    turns=tuple(turns),
                    order=order,
                )
            )
        return normalized

    def _add_latest_time_node(
        self,
        graph: nx.MultiDiGraph,
        sessions: Sequence[NormalizedSession],
        question_date: str,
    ) -> str:
        if question_date:
            sort_key, label = parse_sort_key(question_date, len(sessions))
        elif sessions:
            sort_key, label = parse_sort_key(sessions[-1].date, len(sessions))
        else:
            sort_key, label = 0, "unknown"
        node_id = stable_id("time", f"latest:{label}:{sort_key}")
        self._add_node(
            graph,
            node_id,
            NODE_TIME,
            label=label,
            sort_key=sort_key,
            time_role="latest_available",
        )
        return node_id

    def _ingest_session(
        self,
        graph: nx.MultiDiGraph,
        session: NormalizedSession,
        question: str,
        question_type: str,
        focus_terms: Set[str],
    ) -> List[str]:
        session_sort_key, parsed_date = parse_sort_key(session.date, session.order)
        session_claim_ids: List[str] = []
        for turn_index, turn in enumerate(session.turns):
            event_id = f"event:{session.session_id}:{turn_index}"
            self._add_node(
                graph,
                event_id,
                NODE_EVENT,
                session_id=session.session_id,
                role=turn.role,
                text=turn.content,
                date=session.date,
                parsed_date=parsed_date,
                sort_key=session_sort_key * 1000 + turn_index,
            )

            entities = self._extract_entities(question, turn.content, focus_terms)
            scopes = self._extract_scopes(question, question_type, turn.content)
            for entity in entities:
                entity_id = stable_id("entity", entity)
                self._add_node(
                    graph,
                    entity_id,
                    NODE_ENTITY_SCOPE,
                    subtype="entity",
                    label=entity,
                )
                self._add_edge(graph, event_id, entity_id, EDGE_EVENT_MENTIONS_ENTITY)
            for scope in scopes:
                scope_id = stable_id("scope", scope)
                self._add_node(
                    graph,
                    scope_id,
                    NODE_ENTITY_SCOPE,
                    subtype="scope",
                    label=scope,
                )
                self._add_edge(graph, event_id, scope_id, EDGE_EVENT_IN_SCOPE)

            for sentence_index, sentence in enumerate(split_claim_sentences(turn.content)):
                claim_id = stable_id("claim", f"{session.session_id}:{turn_index}:{sentence_index}:{sentence}")
                claim_terms = set(important_terms(sentence, limit=16))
                self._add_node(
                    graph,
                    claim_id,
                    NODE_CLAIM,
                    text=sentence,
                    session_id=session.session_id,
                    event_id=event_id,
                    role=turn.role,
                    date=session.date,
                    parsed_date=parsed_date,
                    sort_key=session_sort_key * 1000 + turn_index * 10 + sentence_index,
                    terms=sorted(claim_terms),
                    entity_labels=sorted(entities),
                    scope_labels=sorted(scopes),
                    has_update_marker=has_any_marker(sentence, UPDATE_MARKERS),
                    has_correction_marker=has_any_marker(sentence, CORRECTION_MARKERS),
                    has_negation_marker=has_any_marker(sentence, NEGATION_MARKERS),
                )
                self._add_edge(graph, claim_id, event_id, EDGE_CLAIM_SUPPORTED_BY_EVENT)
                session_claim_ids.append(claim_id)
        return session_claim_ids

    def _extract_entities(self, question: str, text: str, focus_terms: Set[str]) -> List[str]:
        combined = f"{question} {text}"
        terms = important_terms(combined, limit=20)
        capitalized = re.findall(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b", text)
        entities: List[str] = []
        for term in list(focus_terms) + terms + capitalized:
            label = normalize_label(term)
            if label and label not in entities:
                entities.append(label)
            if len(entities) >= 8:
                break
        return entities or ["general"]

    def _extract_scopes(self, question: str, question_type: str, text: str) -> List[str]:
        scopes: List[str] = []
        if question_type in QUESTION_TYPE_SCOPES:
            scopes.append(QUESTION_TYPE_SCOPES[question_type])
        question_terms = important_terms(question, limit=4)
        if question_terms:
            scopes.append("question_" + "_".join(question_terms[:4]))
        for marker, scope in (
            ("prefer", "preference"),
            ("like", "preference"),
            ("now", "current_state"),
            ("currently", "current_state"),
            ("when", "temporal"),
            ("date", "temporal"),
            ("changed", "knowledge_update"),
            ("switched", "knowledge_update"),
        ):
            if marker in text.lower() or marker in question.lower():
                scopes.append(scope)
        unique: List[str] = []
        for scope in scopes or ["general_memory"]:
            label = normalize_label(scope)
            if label not in unique:
                unique.append(label)
        return unique

    def _connect_claim_relations(
        self,
        graph: nx.MultiDiGraph,
        new_claim_ids: Sequence[str],
        previous_claim_ids: Sequence[str],
    ) -> None:
        for index, new_claim_id in enumerate(new_claim_ids):
            new_data = graph.nodes[new_claim_id]
            earlier_candidates = list(previous_claim_ids) + list(new_claim_ids[:index])
            for old_claim_id in earlier_candidates[-80:]:
                old_data = graph.nodes[old_claim_id]
                if not self._claims_share_focus(new_data, old_data):
                    continue
                same_session = new_data.get("session_id") == old_data.get("session_id")
                if same_session and new_data.get("has_correction_marker"):
                    self._add_edge(
                        graph,
                        new_claim_id,
                        old_claim_id,
                        EDGE_CLAIM_CORRECTS_CLAIM,
                        reason="same_session_correction_marker",
                    )
                    continue
                if not same_session and new_data.get("has_update_marker"):
                    self._add_edge(
                        graph,
                        new_claim_id,
                        old_claim_id,
                        EDGE_CLAIM_SUPERSEDES_CLAIM,
                        reason="later_update_marker_same_focus",
                    )
                    continue
                if (
                    not same_session
                    and not new_data.get("has_update_marker")
                    and not new_data.get("has_correction_marker")
                    and self._claims_conflict(new_data, old_data)
                ):
                    self._add_edge(
                        graph,
                        new_claim_id,
                        old_claim_id,
                        EDGE_CLAIM_CONFLICTS_WITH_CLAIM,
                        reason="negation_mismatch_same_focus",
                    )

    def _claims_share_focus(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        left_scopes = set(left.get("scope_labels") or [])
        right_scopes = set(right.get("scope_labels") or [])
        left_entities = set(left.get("entity_labels") or [])
        right_entities = set(right.get("entity_labels") or [])
        return has_focus_overlap(left_scopes, right_scopes) or has_focus_overlap(left_entities, right_entities)

    def _claims_conflict(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        left_neg = bool(left.get("has_negation_marker"))
        right_neg = bool(right.get("has_negation_marker"))
        return left_neg != right_neg and self._claims_share_focus(left, right)

    def _materialize_state_facets(
        self,
        graph: nx.MultiDiGraph,
        claim_order: Sequence[str],
        focus_terms: Set[str],
        latest_time_node: str,
    ) -> None:
        rejected_claims = self._claims_invalidated_by_relations(graph)
        active_claims = [claim_id for claim_id in claim_order if claim_id not in rejected_claims]
        ranked = sorted(
            active_claims,
            key=lambda claim_id: (
                -self._claim_focus_score(graph.nodes[claim_id], focus_terms),
                -int(graph.nodes[claim_id].get("sort_key", 0)),
            ),
        )
        for claim_id in ranked[: self.max_facets]:
            claim = graph.nodes[claim_id]
            scope_labels = list(claim.get("scope_labels") or ["task_state"])
            facet_name = scope_labels[0] if scope_labels else "task_state"
            facet_value = str(claim.get("text", ""))
            facet_id = stable_id("facet", f"{facet_name}:{facet_value}:{claim_id}")
            self._add_node(
                graph,
                facet_id,
                NODE_STATE_FACET,
                name=facet_name,
                value=facet_value,
                claim_id=claim_id,
                session_id=claim.get("session_id"),
                current_after=claim.get("parsed_date") or claim.get("date") or "",
            )
            self._add_edge(graph, facet_id, claim_id, EDGE_FACET_SUPPORTED_BY_CLAIM)
            self._add_edge(graph, facet_id, latest_time_node, EDGE_FACET_CURRENT_AFTER_TIME)

    def _claims_invalidated_by_relations(self, graph: nx.MultiDiGraph) -> Set[str]:
        invalidated: Set[str] = set()
        for source, target, data in graph.edges(data=True):
            if data.get("edge_type") in {EDGE_CLAIM_CORRECTS_CLAIM, EDGE_CLAIM_SUPERSEDES_CLAIM}:
                invalidated.add(str(target))
        return invalidated

    def _claim_focus_score(self, claim: Mapping[str, Any], focus_terms: Set[str]) -> int:
        claim_terms = set(claim.get("terms") or [])
        score = len(claim_terms.intersection(focus_terms))
        if claim.get("has_update_marker"):
            score += 2
        if claim.get("has_correction_marker"):
            score += 2
        return score

    def _add_node(self, graph: nx.MultiDiGraph, node_id: str, node_type: str, **attrs: Any) -> None:
        if node_type not in ALLOWED_NODE_TYPES:
            raise ValueError(f"unsupported node_type={node_type}")
        if graph.has_node(node_id):
            graph.nodes[node_id].update(attrs)
            return
        graph.add_node(node_id, node_type=node_type, **attrs)

    def _add_edge(
        self,
        graph: nx.MultiDiGraph,
        source: str,
        target: str,
        edge_type: str,
        **attrs: Any,
    ) -> None:
        if edge_type not in ALLOWED_EDGE_TYPES:
            raise ValueError(f"unsupported edge_type={edge_type}")
        graph.add_edge(source, target, edge_type=edge_type, **attrs)

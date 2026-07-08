from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex  # noqa: E402
from pipeline.external.locomo_qa.loader import (  # noqa: E402
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
    "graph_embedding_state_scope_event",
)
TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")


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


class GraphEvidenceIndex:
    def __init__(self, graph_dir: Path) -> None:
        self.graph_dir = graph_dir
        self.events: Dict[str, Dict[str, Any]] = {}
        self.claims: Dict[str, Dict[str, Any]] = {}
        self.states: Dict[str, Dict[str, Any]] = {}
        self.scopes: Dict[str, Dict[str, Any]] = {}
        self.claims_by_event: DefaultDict[str, List[str]] = defaultdict(list)
        self.states_by_claim: DefaultDict[str, List[str]] = defaultdict(list)
        self.scopes_by_event: DefaultDict[str, List[str]] = defaultdict(list)
        self.events_by_scope: DefaultDict[str, List[str]] = defaultdict(list)
        self.scopes_by_state: DefaultDict[str, List[str]] = defaultdict(list)
        self.states_by_scope: DefaultDict[str, List[str]] = defaultdict(list)
        self.relations_by_claim: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
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
        nodes_path = self.graph_dir / "nodes.jsonl"
        edges_path = self.graph_dir / "edges.jsonl"
        if not nodes_path.exists() or not edges_path.exists():
            raise FileNotFoundError(f"missing graph artifact files under {self.graph_dir}")
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
    ) -> RetrievalResult:
        targets = embedding_targets_for_variant(variant)
        scope_allowed_doc_ids = [
            f"scope::{scope_id}"
            for scope_id, scope in self.scopes.items()
            if not scope_types or str(scope.get("scope_type") or "") in set(scope_types)
        ]
        scope_bm25_hits = self.scope_bm25.search(question, candidate_k, allowed_doc_ids=scope_allowed_doc_ids)
        selected_scope_hits = scope_bm25_hits[:scope_top_k]
        scope_embedding_trace: List[Dict[str, Any]] = []
        if "scope" in targets:
            scope_index = embedding_indices.get("scope")
            if scope_index is None:
                raise ValueError(f"{variant} requires a scope embedding index")
            allowed = [doc_id for doc_id, _score in scope_bm25_hits[:embedding_candidate_k]]
            scope_embedding_hits = scope_index.search(question, scope_top_k, allowed_doc_ids=allowed)
            selected_scope_hits = [(hit.doc_id, hit.score) for hit in scope_embedding_hits]
            scope_embedding_trace = [{"doc_id": doc_id, "score": score} for doc_id, score in selected_scope_hits]
        routed_scope_ids = [doc_id[len("scope::") :] for doc_id, _score in selected_scope_hits if doc_id.startswith("scope::")]
        allowed_event_doc_ids = self._event_doc_ids_for_scopes(routed_scope_ids)
        event_bm25_hits = self.event_bm25.search(question, candidate_k, allowed_doc_ids=allowed_event_doc_ids)
        if len(event_bm25_hits) < top_k:
            supplemental = self.event_bm25.search(question, candidate_k)
            event_bm25_hits = merge_hits(event_bm25_hits, supplemental)
        selected_event_hits = event_bm25_hits[:top_k]
        event_embedding_trace: List[Dict[str, Any]] = []
        if "event" in targets:
            event_index = embedding_indices.get("event")
            if event_index is None:
                raise ValueError(f"{variant} requires an event embedding index")
            allowed = [doc_id for doc_id, _score in event_bm25_hits[:embedding_candidate_k]]
            event_embedding_hits = event_index.search(question, top_k, allowed_doc_ids=allowed)
            selected_event_hits = [(hit.doc_id, hit.score) for hit in event_embedding_hits]
            event_embedding_trace = [{"doc_id": doc_id, "score": score} for doc_id, score in selected_event_hits]
        event_ids: List[str] = []
        state_ids: List[str] = []
        for doc_id, _score in selected_event_hits:
            if not doc_id.startswith("event::"):
                continue
            event_id = doc_id[len("event::") :]
            event_ids.append(event_id)
            for claim_id in self.claims_by_event.get(event_id, []):
                state_ids.extend(self.states_by_claim.get(claim_id, []))

        allowed_state_doc_ids = self._state_doc_ids_for_scopes(routed_scope_ids)
        state_bm25_hits = self.state_bm25.search(question, max(candidate_k, state_search_k), allowed_doc_ids=allowed_state_doc_ids)
        if len(state_bm25_hits) < state_search_k:
            supplemental_states = self.state_bm25.search(question, max(candidate_k, state_search_k))
            state_bm25_hits = merge_hits(state_bm25_hits, supplemental_states)
        selected_state_hits = state_bm25_hits[:state_search_k]
        state_embedding_trace: List[Dict[str, Any]] = []
        if "state" in targets:
            state_index = embedding_indices.get("state")
            if state_index is None:
                raise ValueError(f"{variant} requires a state embedding index")
            allowed = [doc_id for doc_id, _score in state_bm25_hits[:embedding_candidate_k]]
            state_embedding_hits = state_index.search(question, state_search_k, allowed_doc_ids=allowed)
            selected_state_hits = [(hit.doc_id, hit.score) for hit in state_embedding_hits]
            state_embedding_trace = [{"doc_id": doc_id, "score": score} for doc_id, score in selected_state_hits]

        for doc_id, _score in selected_state_hits:
            if not doc_id.startswith("state::"):
                continue
            state_id = doc_id[len("state::") :]
            state_ids.append(state_id)
            state = self.states.get(state_id, {})
            event_ids.extend(str(item) for item in state.get("support_event_ids", []) or [])
        event_ids = ordered_unique(event_ids)[:max_context_events]
        state_ids = ordered_unique(state_ids)[:max_state_lines]
        state_lines = [format_state_line(self.states[state_id]) for state_id in state_ids if state_id in self.states]
        relation_lines = self._relation_lines_for_states(state_ids)
        context = self._context_text(event_ids)
        return RetrievalResult(
            candidate_dialog_ids=event_ids,
            state_lines=state_lines,
            relation_lines=relation_lines,
            context=context,
            trace={
                "embedding_targets": sorted(targets),
                "scope_routing": {
                    "bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in scope_bm25_hits[: min(candidate_k, 20)]],
                    "selected_scope_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in selected_scope_hits],
                    "embedding_hits": scope_embedding_trace,
                    "scope_ids": routed_scope_ids,
                },
                "event_retrieval": {
                    "bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in event_bm25_hits[: min(candidate_k, 30)]],
                    "selected_event_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in selected_event_hits],
                    "embedding_hits": event_embedding_trace,
                },
                "state_search": {
                    "bm25_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in state_bm25_hits[: min(candidate_k, 30)]],
                    "selected_state_hits": [{"doc_id": doc_id, "score": score} for doc_id, score in selected_state_hits],
                    "embedding_hits": state_embedding_trace,
                },
                "selected_state_ids": state_ids,
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
                    source = self.claims.get(str(edge.get("from") or ""), {})
                    target = self.claims.get(str(edge.get("to") or ""), {})
                    lines.append(
                        f"{edge.get('type')}: {claim_summary(source)} -> {claim_summary(target)} "
                        f"reason={edge.get('reason', '')}"
                    )
        return lines[:8]

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
    parser.add_argument("--graph-dir", default=str(EXTERNAL_GRAPH_DIR / "locomo_qa_sample_graph_v1" / "conv-26"))
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--judge-model", default="deepseek-v4-flash")
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
    parser.add_argument("--state-search-k", type=int, default=12)
    parser.add_argument("--candidate-k", type=int, default=80)
    parser.add_argument("--embedding-candidate-k", type=int, default=80)
    parser.add_argument("--max-context-events", type=int, default=24)
    parser.add_argument("--max-state-lines", type=int, default=16)
    parser.add_argument("--answer-workers", type=int, default=4)
    parser.add_argument("--cache", default=str(EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_graph_query.json"))
    parser.add_argument("--judge-cache", default=str(EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_graph_query.judge.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--embedding-cache", default=str(EXTERNAL_CACHE_DIR / "embedding_cache.locomo_qa_graph_query.json"))
    parser.add_argument("--embedding-base-url", default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", ""))
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument("--output", default=str(EXTERNAL_RESULT_DIR / "results_locomo_qa_graph_conv26.json"))
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
    if variant == "graph_embedding_state_scope_event":
        return {"state", "scope", "event"}
    raise ValueError(f"unsupported variant={variant}")


def merge_hits(primary: Sequence[Tuple[str, float]], supplemental: Sequence[Tuple[str, float]]) -> List[Tuple[str, float]]:
    seen = set()
    merged: List[Tuple[str, float]] = []
    for doc_id, score in list(primary) + list(supplemental):
        if doc_id in seen:
            continue
        seen.add(doc_id)
        merged.append((doc_id, score))
    return merged


def format_state_line(state: Mapping[str, Any]) -> str:
    support = ", ".join(str(item) for item in state.get("support_event_ids", []) or [])
    return (
        f"{state.get('subject', '')} {state.get('facet_key', '')}: {state.get('value', '')} "
        f"(time={state.get('current_after', '')}; support={support})"
    )


def claim_summary(claim: Mapping[str, Any]) -> str:
    return f"{claim.get('dialog_id', '')} {claim.get('subject', '')} {claim.get('facet_key', '')}: {claim.get('value', '')}"


def answer_system_prompt() -> str:
    return (
        "You answer LoCoMo QA questions using only the provided graph evidence: state facets, relation notes, "
        "dialog turns, session dates, and text metadata from image captions/search queries. "
        "Return strict JSON with keys answer and evidence_dialog_ids. "
        "Keep the answer as a short gold-style phrase, date, name, or comma-separated list. "
        "For false-premise or unavailable information, answer exactly \"No information available\" or "
        "\"Not mentioned in the conversation\". Cite only dialog IDs present in the evidence."
    )


def answer_user_prompt(row: LoCoMoQAItem, variant: str, retrieval: RetrievalResult) -> str:
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


def judge_system_prompt() -> str:
    return (
        "You are an expert grader that determines whether a generated answer to a LoCoMo personal-memory "
        "question matches the gold answer. Return strict JSON only."
    )


def judge_user_prompt(row: LoCoMoQAItem, generated_answer: str) -> str:
    gold_answer = row.answer or ""
    unavailable_gold = row.category == 5
    return (
        "Your task is to label a generated answer as CORRECT or WRONG.\n\n"
        "The question is about a long personal conversation. The gold answer is concise and contains the key information. "
        "Be generous about wording, aliases, list order, and equivalent date formats, but do not accept answers that add "
        "a wrong entity, wrong date, wrong relation, or unsupported alternative.\n\n"
        "For temporal questions, accept equivalent date/month/year expressions. For multi-answer questions, require the "
        "generated answer to include the required set without major extras. For adversarial/unanswerable questions, "
        f"the gold answer should be treated as unavailable={str(unavailable_gold).lower()}; an answer is correct only if it abstains "
        "or states that the information is not available.\n\n"
        f"Question: {row.question}\n"
        f"Gold answer: {gold_answer}\n"
        f"Generated answer: {generated_answer}\n\n"
        "Return JSON with this schema:\n"
        "{\"label\": \"CORRECT|WRONG\", \"rationale\": \"short reason\"}"
    )


def normalize_judge_label(raw: Mapping[str, Any]) -> str:
    label = raw.get("label", "WRONG")
    if isinstance(label, Mapping):
        label = label.get("label", "WRONG")
    normalized = str(label).strip().upper()
    return "CORRECT" if normalized == "CORRECT" else "WRONG"


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
    summary["task_averaged_judge_accuracy"] = mean(metrics["judge_accuracy"] for metrics in by_question_type.values())
    summary["by_question_type"] = by_question_type
    return summary


def summarize_flat(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    return {
        "n_cases": len(rows),
        "answer_f1": mean(float(row["answer_f1"]) for row in rows),
        "judge_accuracy": mean(1.0 if row["judge_is_correct"] else 0.0 for row in rows),
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
    judge_runtime: LLMRuntimeConfig,
    args: argparse.Namespace,
    embedding_indices: Mapping[str, OpenAIEmbeddingIndex],
) -> Dict[str, object]:
    eval_rows: List[Dict[str, object]] = []

    def run_row(index: int, row: LoCoMoQAItem) -> Tuple[int, Dict[str, object]]:
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
        )
        client = make_sharded_client(answer_runtime, f"answer_{variant}", f"{row.question_id}_{short_hash(row.question)}")
        output = client.complete_json(answer_system_prompt(), answer_user_prompt(row, variant, retrieval))
        hypothesis = str(output.get("answer", "")).strip()
        judge_client = make_sharded_client(judge_runtime, f"judge_{variant}", f"{row.question_id}_{short_hash(row.question + hypothesis)}")
        judge_raw = judge_client.complete_json(judge_system_prompt(), judge_user_prompt(row, hypothesis))
        judge_label = normalize_judge_label(judge_raw)
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
            "judge_label": judge_label,
            "judge_is_correct": judge_label == "CORRECT",
            "judge_rationale": judge_raw.get("rationale"),
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


def print_summary(provider: str, model: str, judge_provider: str, judge_model: str, results: Sequence[Dict[str, object]]) -> None:
    print("LoCoMo QA graph benchmark")
    print(f"answer_provider={provider} answer_model={model}")
    print(f"judge_provider={judge_provider} judge_model={judge_model}")
    print()
    print(f"{'variant':<35} {'n':>4} {'judge':>8} {'ans_f1':>8} {'task_j':>8} {'cand_r':>8} {'cand_p':>8} {'ev_r':>8} {'ev_p':>8} {'ev_f1':>8}")
    print("-" * 122)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<35} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['judge_accuracy']):>8} "
            f"{format_metric(summary['answer_f1']):>8} "
            f"{format_metric(summary['task_averaged_judge_accuracy']):>8} "
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
    try:
        judge_api_key, judge_model, judge_api_base = provider_config(args.judge_provider)
    except RuntimeError as exc:
        print(f"Judge config error: {exc}", file=sys.stderr)
        return 2
    if args.judge_model:
        judge_model = args.judge_model
    answer_runtime = LLMRuntimeConfig(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )
    judge_runtime = LLMRuntimeConfig(
        provider=args.judge_provider,
        model=judge_model,
        api_key=judge_api_key,
        api_base=judge_api_base,
        cache_path=Path(args.judge_cache),
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
    try:
        results = [
            run_variant(
                variant=variant,
                rows=rows,
                graph=graph,
                answer_runtime=answer_runtime,
                judge_runtime=judge_runtime,
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
        "provider": args.provider,
        "model": model,
        "judge_provider": args.judge_provider,
        "judge_model": judge_model,
        "variants": list(args.variants),
        "question_types": [normalize_question_type(item) for item in args.question_types],
        "top_k": args.top_k,
        "scope_top_k": args.scope_top_k,
        "scope_types": parse_scope_types(args.scope_types),
        "state_search_k": args.state_search_k,
        "candidate_k": args.candidate_k,
        "embedding_candidate_k": args.embedding_candidate_k,
        "embedding_model": args.embedding_model if needed_embedding_targets else None,
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
                            "hypothesis": row["hypothesis"],
                            "judge_label": row["judge_label"],
                            "judge_rationale": row["judge_rationale"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    print_summary(args.provider, model, args.judge_provider, judge_model, results)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

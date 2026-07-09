from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Any, DefaultDict, Dict, List, Mapping, Optional, Sequence

from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex
from ours_scope_time_state.qa_probe import BM25Index, qa_query_text, read_jsonl


RELATION_EDGE_TYPES = {"SUPERSEDES", "CORRECTS", "CONFLICTS_WITH"}
EMBEDDING_RETRIEVAL_SCORE_WEIGHT = 8.0
TIME_SOURCE_SCORE = {
    "explicit_text_time": 12.0,
    "relative_text_time": 8.0,
    "phase_from_event_time": 5.0,
    "source_event_fallback": -4.0,
    "source_event_occurred_at": -4.0,
}
PERSON_NAME_RE = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")

START_CUE_RE = re.compile(
    r"\b(start(?:ed|ing)?|begin(?:ning)?|began|initiat(?:ed|e|ing)|launched|kicked off)\b|"
    r"\b(first draft|initial draft|prepared .*draft|v0\.1)\b",
    re.I,
)
END_CUE_RE = re.compile(
    r"\b(completed|complete|finished|finali[sz](?:ed|e|ing)|uploaded|released|approved|closed|archived|delivered|done|received and reviewed)\b",
    re.I,
)
STRONG_START_RE = re.compile(
    r"officially start(?:ed|ing)|\bi'?ve started(?: on)?\b|today (?:i'?m|we'?re|we are)?\s*start(?:ing)?|"
    r"starting (?:work on|a )?new|starting work on|"
    r"\b(?:i|we)\s+will\s+start\b.*\btoday\b|"
    r"\bnew (?:task|work item|assignment)\b|first draft|initial draft|prepared .*draft|v0\.1",
    re.I,
)
NON_INITIAL_START_RE = re.compile(
    r"started yesterday|continue|continuing|currently|in progress|being written|progress of|update on .*progress|"
    r"further deepen|preparations? .*started|start importing|can start|"
    r"finali[sz]e revisions?|final version|final stages?|final detail|self-inspection|yesterday|"
    r"going online|go-live|release branch|last friday|last week|incorporating",
    re.I,
)
STRONG_END_RE = re.compile(
    r"task (?:has been |is |was )?completed|officially announce.*completed|fully completed|final .*uploaded|"
    r"complete technical design document.*uploaded|received and reviewed|approve|approved|officially delivered|"
    r"completed all development and testing",
    re.I,
)
NON_FINAL_END_RE = re.compile(
    r"draft|preliminary|80%|remaining|expect|expected|about to|currently|undergoing|ready to be executed|"
    r"by tomorrow|tomorrow|will be|will start|this afternoon|next_step|next step|specific plans?|plans? to|"
    r"progress|started|starting|implementing|officially started|coding today|constraint|architectural decision|"
    r"must include|required|mandatory|synchronizing|newly released",
    re.I,
)
ENDPOINT_STOP_TERMS = {
    "about",
    "after",
    "all",
    "and",
    "are",
    "before",
    "began",
    "begin",
    "completed",
    "concluded",
    "developed",
    "did",
    "does",
    "for",
    "from",
    "group",
    "has",
    "have",
    "how",
    "into",
    "long",
    "project",
    "start",
    "started",
    "status",
    "system",
    "task",
    "take",
    "that",
    "the",
    "their",
    "them",
    "this",
    "today",
    "was",
    "were",
    "what",
    "when",
    "will",
    "with",
}
ENDPOINT_IMPORTANT_TERMS = {
    "aggregate",
    "alarm",
    "async",
    "chart",
    "cockpit",
    "compute",
    "cost",
    "dashboard",
    "database",
    "factor",
    "finance",
    "guide",
    "interface",
    "interview",
    "manual",
    "message",
    "monitor",
    "operation",
    "loading",
    "optimize",
    "performance",
    "center",
    "homepage",
    "leader",
    "queue",
    "region",
    "requirement",
    "strategic",
    "supplier",
    "user",
    "workbench",
    "trigger",
    "verify",
    "write",
}
NON_PERSON_NAME_TOKENS = {
    "American",
    "Backend",
    "Buyer",
    "Company",
    "Department",
    "Frontend",
    "Health",
    "Management",
    "Project",
    "System",
}
EFFORT_METRIC_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(person[- ]days?|man[- ]days?|workdays?|working days?|days?)\b",
    re.I,
)
EFFORT_CONTEXT_RE = re.compile(
    r"\b(effort|spent|invested|take|took|takes|last(?:ed)?|duration|workload|work hours|planned|estimated|actual|in total|combined|collectively)\b",
    re.I,
)


def _parse_iso_day(value: object) -> Optional[date]:
    text = str(value or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _endpoint_term(token: str) -> str:
    token = token.lower().strip("'_")
    if not token:
        return ""
    replacements = {
        "aggregated": "aggregate",
        "aggregating": "aggregate",
        "aggregation": "aggregate",
        "alert": "alarm",
        "alerts": "alarm",
        "analyses": "analysis",
        "async": "async",
        "asynchronous": "async",
        "calculation": "compute",
        "calculations": "compute",
        "calculate": "compute",
        "computed": "compute",
        "computing": "compute",
        "computation": "compute",
        "computations": "compute",
        "diagnostic": "diagnosis",
        "financial": "finance",
        "financing": "finance",
        "homepage": "dashboard",
        "homepages": "dashboard",
        "manual": "guide",
        "manuals": "guide",
        "personal": "user",
        "message": "message",
        "messages": "message",
        "module": "",
        "modules": "",
        "optimisation": "optimize",
        "optimise": "optimize",
        "optimised": "optimize",
        "optimising": "optimize",
        "optimization": "optimize",
        "optimize": "optimize",
        "optimized": "optimize",
        "optimizing": "optimize",
        "material": "report",
        "materials": "report",
        "mq": "message",
        "rabbitmq": "message",
        "received": "receive",
        "receiving": "receive",
        "requirement": "requirement",
        "requirements": "requirement",
        "sent": "send",
        "sending": "send",
        "stakeholder": "interview",
        "stakeholders": "interview",
        "strategic": "strategic",
        "uploaded": "upload",
        "uploading": "upload",
        "writ": "write",
        "write": "write",
        "writes": "write",
        "writing": "write",
        "written": "write",
        "wrote": "write",
    }
    if token in replacements:
        return replacements[token]
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    return replacements.get(token, token)


def _endpoint_terms(text: str) -> List[str]:
    terms: List[str] = []
    for raw_token in re.findall(r"[A-Za-z0-9]+", text.lower()):
        term = _endpoint_term(raw_token)
        if len(term) < 3 or term in ENDPOINT_STOP_TERMS:
            continue
        terms.append(term)
    return terms


def _normalize_person_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _likely_person_name(value: str) -> bool:
    tokens = [token for token in str(value or "").split() if token]
    if len(tokens) != 2:
        return False
    if any(token in NON_PERSON_NAME_TOKENS for token in tokens):
        return False
    return all(re.fullmatch(r"[A-Z][a-z]+", token) for token in tokens)


def _extract_person_names(text: object) -> List[str]:
    names: List[str] = []
    seen: set[str] = set()
    for match in PERSON_NAME_RE.finditer(str(text or "")):
        name = " ".join(match.group(0).split())
        key = _normalize_person_name(name)
        if not key or key in seen or not _likely_person_name(name):
            continue
        seen.add(key)
        names.append(name)
    return names


def _endpoint_content_match_score(query: str, document: str) -> tuple[float, Dict[str, Any]]:
    query_terms = _endpoint_terms(query)
    if not query_terms:
        return 0.0, {"query_terms": [], "matched_terms": [], "missing_terms": []}
    unique_query_terms = list(dict.fromkeys(query_terms))
    doc_terms = set(_endpoint_terms(document))
    matched_terms = [term for term in unique_query_terms if term in doc_terms]
    missing_terms = [term for term in unique_query_terms if term not in doc_terms]
    score = 0.0
    for term in matched_terms:
        score += 5.0 if term in ENDPOINT_IMPORTANT_TERMS else 2.0
    coverage = len(matched_terms) / max(1, len(unique_query_terms))
    score += 10.0 * coverage
    if coverage < 0.20:
        score -= 8.0

    query_set = set(unique_query_terms)
    if "interview" in query_set and "interview" not in doc_terms:
        score -= 14.0
    if {"async", "compute"} <= query_set:
        if {"async", "compute"} <= doc_terms:
            score += 22.0
        elif not ({"async", "compute"} & doc_terms):
            score -= 18.0
    if "guide" in query_set:
        if "guide" in doc_terms:
            score += 16.0
        else:
            score -= 14.0
    if "cost" in query_set:
        if {"cost", "finance"} & doc_terms:
            score += 14.0
        else:
            score -= 10.0
    if "contact" in query_set and "contact" not in doc_terms:
        score -= 18.0
    if {"supplier", "information"} <= query_set and "information" not in doc_terms:
        score -= 12.0
    if {"dashboard", "aggregate", "interface"} & query_set:
        dashboard_matches = len(({"dashboard", "aggregate", "interface"} & query_set) & doc_terms)
        score += 6.0 * dashboard_matches
    if {"user", "center"} <= query_set and len({"user", "center"} & doc_terms) < 2:
        score -= 16.0
    if re.search(r"\bhomepage\b", query, re.I) and not re.search(r"\bhomepage\b", document, re.I):
        score -= 12.0
    if {"loading", "performance", "optimize"} & query_set and not ({"loading", "performance", "optimize"} & doc_terms):
        score -= 18.0
    if "test" not in query_set and re.search(r"\b(integration test|unit tests?|test cases?|test report|use cases?)\b", document, re.I):
        score -= 18.0

    return score, {
        "query_terms": unique_query_terms,
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
        "coverage": coverage,
    }


def _fallback_effort_metric(text: str, facet_key: str) -> Dict[str, Any]:
    match = EFFORT_METRIC_RE.search(text)
    if not match:
        return {}
    unit_text = match.group(2).lower().replace(" ", "-")
    if unit_text.startswith("person") or unit_text.startswith("man"):
        metric_type = "person_days"
        unit = "person-days"
    elif unit_text in {"workday", "workdays", "working-day", "working-days"}:
        metric_type = "workdays"
        unit = "workdays"
    else:
        if facet_key != "metric" and not EFFORT_CONTEXT_RE.search(text):
            return {}
        metric_type = "duration_days"
        unit = "days"
    return {
        "metric_type": metric_type,
        "metric_unit": unit,
        "metric_value_num": float(match.group(1)),
        "metric_value_text": match.group(0),
        "metric_source": "fallback_text_numeric_unit",
    }


@dataclass(frozen=True)
class ExpandedEvidence:
    event_ids: List[str]
    notes_by_event: Dict[str, List[str]]
    seed_event_ids: List[str]
    state_facet_ids: List[str]
    state_summaries: List[str]
    relation_summaries: List[str]
    relation_edge_count: int

    def trace(self) -> Dict[str, Any]:
        return {
            "seed_event_ids": self.seed_event_ids,
            "expanded_event_ids": self.event_ids,
            "state_facet_ids": self.state_facet_ids,
            "state_summaries": self.state_summaries,
            "relation_summaries": self.relation_summaries,
            "relation_edge_count": self.relation_edge_count,
            "notes_by_event": self.notes_by_event,
        }


class STSGraphEvidenceIndex:
    def __init__(self, graph_dir: Path):
        self.graph_dir = graph_dir
        self.events: Dict[str, Dict[str, Any]] = {}
        self.scopes: Dict[str, Dict[str, Any]] = {}
        self.claims: Dict[str, Dict[str, Any]] = {}
        self.state_facets: Dict[str, Dict[str, Any]] = {}
        self.time_nodes: Dict[str, Dict[str, Any]] = {}
        self.person_scope_by_name: Dict[str, str] = {}
        self.person_name_by_scope: Dict[str, str] = {}
        self.scopes_by_event: DefaultDict[str, List[str]] = defaultdict(list)
        self.events_by_scope: DefaultDict[str, List[str]] = defaultdict(list)
        self.responsible_people_by_task_scope: DefaultDict[str, set[str]] = defaultdict(set)
        self.task_scopes_by_responsible_person: DefaultDict[str, set[str]] = defaultdict(set)
        self.claims_by_event: DefaultDict[str, List[str]] = defaultdict(list)
        self.states_by_claim: DefaultDict[str, List[str]] = defaultdict(list)
        self.current_scope_by_state: Dict[str, str] = {}
        self.current_scopes_by_state: DefaultDict[str, List[str]] = defaultdict(list)
        self.current_time_by_state: Dict[str, str] = {}
        self.times_by_claim: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.occurred_time_by_event: Dict[str, str] = {}
        self.occurred_time_id_by_event: Dict[str, str] = {}
        self.relations_by_claim: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._state_index: Optional[BM25Index] = None
        self._state_doc_ids: List[str] = []
        self._state_docs: List[str] = []
        self._scope_index: Optional[BM25Index] = None
        self._scope_doc_ids: List[str] = []
        self._scope_docs: List[str] = []
        self._scope_doc_by_id: Dict[str, str] = {}
        self._temporal_endpoint_index: Optional[BM25Index] = None
        self._temporal_endpoint_doc_ids: List[str] = []
        self._temporal_endpoint_docs: List[str] = []
        self._temporal_endpoint_candidates: Dict[str, Dict[str, Any]] = {}
        self._effort_metric_index: Optional[BM25Index] = None
        self._effort_metric_doc_ids: List[str] = []
        self._effort_metric_docs: List[str] = []
        self._effort_metric_candidates: Dict[str, Dict[str, Any]] = {}
        self._embedding_model: Optional[str] = None
        self._embedding_state_index: Optional[OpenAIEmbeddingIndex] = None
        self._embedding_scope_index: Optional[OpenAIEmbeddingIndex] = None
        self._embedding_temporal_endpoint_index: Optional[OpenAIEmbeddingIndex] = None
        self._embedding_effort_metric_index: Optional[OpenAIEmbeddingIndex] = None
        self._embedding_candidate_k = 32
        self._load()
        self._build_state_index()

    @classmethod
    def load(cls, graph_dir: Path) -> "STSGraphEvidenceIndex":
        return cls(graph_dir)

    def enable_embedding_retrieval(
        self,
        *,
        model: str,
        cache_path: Path,
        namespace: str,
        batch_size: int = 96,
        base_url: Optional[str] = None,
        targets: Optional[set[str]] = None,
        candidate_k: int = 32,
    ) -> None:
        enabled_targets = {"state", "scope", "temporal", "effort"} if targets is None else targets
        self._embedding_model = model
        self._embedding_candidate_k = max(1, int(candidate_k))
        if "state" in enabled_targets:
            self._embedding_state_index = OpenAIEmbeddingIndex(
                self._state_doc_ids,
                self._state_docs,
                model=model,
                cache_path=cache_path,
                namespace=f"{namespace}:state_facets",
                batch_size=batch_size,
                base_url=base_url,
            )
        if "scope" in enabled_targets:
            self._embedding_scope_index = OpenAIEmbeddingIndex(
                self._scope_doc_ids,
                self._scope_docs,
                model=model,
                cache_path=cache_path,
                namespace=f"{namespace}:scopes",
                batch_size=batch_size,
                base_url=base_url,
            )
        if "temporal" in enabled_targets:
            self._embedding_temporal_endpoint_index = OpenAIEmbeddingIndex(
                self._temporal_endpoint_doc_ids,
                self._temporal_endpoint_docs,
                model=model,
                cache_path=cache_path,
                namespace=f"{namespace}:temporal_endpoints",
                batch_size=batch_size,
                base_url=base_url,
            )
        if "effort" in enabled_targets:
            self._embedding_effort_metric_index = OpenAIEmbeddingIndex(
                self._effort_metric_doc_ids,
                self._effort_metric_docs,
                model=model,
                cache_path=cache_path,
                namespace=f"{namespace}:effort_metrics",
                batch_size=batch_size,
                base_url=base_url,
            )

    def _rank_index(
        self,
        bm25_index: Optional[BM25Index],
        embedding_index: Optional[OpenAIEmbeddingIndex],
        query: str,
        top_k: int,
        *,
        allowed_doc_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        if top_k <= 0:
            return []
        allowed = {str(doc_id) for doc_id in allowed_doc_ids or [] if doc_id}
        rows: Dict[str, Dict[str, Any]] = {}
        if bm25_index is not None:
            for rank, hit in enumerate(bm25_index.search(query, top_k), start=1):
                doc_id = str(hit.event_id)
                if allowed and doc_id not in allowed:
                    continue
                rows[doc_id] = {
                    "doc_id": doc_id,
                    "lexical_score": float(hit.score),
                    "lexical_rank": rank,
                    "embedding_score": 0.0,
                    "embedding_rank": None,
                }
        embedding_candidate_ids = list(rows)[: self._embedding_candidate_k]
        if embedding_index is not None and embedding_candidate_ids:
            for rank, hit in enumerate(
                embedding_index.search(
                    query,
                    min(top_k, len(embedding_candidate_ids)),
                    allowed_doc_ids=embedding_candidate_ids,
                    max_candidates=self._embedding_candidate_k,
                ),
                start=1,
            ):
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
                float(row.get("lexical_score") or 0.0)
                + EMBEDDING_RETRIEVAL_SCORE_WEIGHT * float(row.get("embedding_score") or 0.0),
                6,
            )
            if row.get("lexical_rank") is not None and row.get("embedding_rank") is not None:
                row["retrieval_source"] = "hybrid"
            elif row.get("embedding_rank") is not None:
                row["retrieval_source"] = "embedding"
            else:
                row["retrieval_source"] = "bm25"
        ranked = sorted(
            rows.values(),
            key=lambda row: (
                -float(row.get("score") or 0.0),
                row.get("lexical_rank") if row.get("lexical_rank") is not None else 10**9,
                row.get("embedding_rank") if row.get("embedding_rank") is not None else 10**9,
                str(row.get("doc_id") or ""),
            ),
        )
        return ranked[:top_k]

    def _load(self) -> None:
        nodes_path = self.graph_dir / "nodes.jsonl"
        edges_path = self.graph_dir / "edges.jsonl"
        if not nodes_path.exists() or not edges_path.exists():
            raise FileNotFoundError(f"missing graph artifact files under {self.graph_dir}")

        for node in read_jsonl(nodes_path):
            node_type = node.get("node_type")
            if node_type == "Episode/Event":
                self.events[str(node["event_id"])] = node
            elif node_type == "Entity/Scope" and node.get("role") == "scope":
                scope_identifier = str(node["scope_id"])
                self.scopes[scope_identifier] = node
                if str(node.get("scope_type") or "") == "person":
                    label = str(node.get("label") or "")
                    match = re.fullmatch(r"PersonScope\((.+)\)", label)
                    person_name = match.group(1) if match else str(node.get("value") or "")
                    if person_name:
                        key = _normalize_person_name(person_name)
                        self.person_scope_by_name[key] = scope_identifier
                        self.person_name_by_scope[scope_identifier] = " ".join(person_name.split())
            elif node_type == "Claim":
                self.claims[str(node["claim_id"])] = node
            elif node_type == "StateFacet":
                self.state_facets[str(node["state_facet_id"])] = node
            elif node_type == "Time":
                self.time_nodes[str(node["time_id"])] = node

        for edge in read_jsonl(edges_path):
            edge_type = str(edge.get("type") or "")
            source = str(edge.get("from") or "")
            target = str(edge.get("to") or "")
            if edge_type == "ASSERTS":
                self.claims_by_event[source].append(target)
            elif edge_type == "IN_SCOPE" and target in self.scopes:
                self.scopes_by_event[source].append(target)
                self.events_by_scope[target].append(source)
            elif edge_type == "SUPPORTS":
                self.states_by_claim[source].append(target)
            elif edge_type == "CURRENT_STATE_OF":
                if target not in self.current_scopes_by_state[source]:
                    self.current_scopes_by_state[source].append(target)
                target_scope_type = str(self.scopes.get(target, {}).get("scope_type") or "")
                if source not in self.current_scope_by_state or target_scope_type in {"group", "project"}:
                    self.current_scope_by_state[source] = target
            elif edge_type == "CURRENT_AFTER":
                time_node = self.time_nodes.get(target, {})
                self.current_time_by_state[source] = str(time_node.get("value") or target)
            elif edge_type == "HAS_TIME":
                time_node = self.time_nodes.get(target, {})
                self.times_by_claim[source].append(
                    {
                        "time_role": edge.get("time_role") or time_node.get("time_role"),
                        "phase_role": edge.get("phase_role"),
                        "value": time_node.get("value"),
                        "time_id": target,
                        "source_event_id": edge.get("source_event_id"),
                        "time_value_source": edge.get("time_value_source"),
                        "time_explicitness_score": edge.get("time_explicitness_score"),
                    }
                )
            elif edge_type == "OCCURRED_AT":
                time_node = self.time_nodes.get(target, {})
                self.occurred_time_by_event[source] = str(time_node.get("value") or "")
                self.occurred_time_id_by_event[source] = target
            elif edge_type == "RESPONSIBLE_FOR":
                person_name = self.person_name_by_scope.get(source)
                if person_name and target in self.scopes:
                    self._add_responsibility(person_name, target)
            elif edge_type in RELATION_EDGE_TYPES:
                self.relations_by_claim[source].append(edge)
                self.relations_by_claim[target].append(edge)
        self._infer_responsibility_from_claims()

    def _add_responsibility(self, person_name: str, task_scope_id: str) -> None:
        task_scope = self.scopes.get(task_scope_id, {})
        if str(task_scope.get("scope_type") or "") != "task_object":
            return
        normalized = _normalize_person_name(person_name)
        if not normalized:
            return
        display_name = " ".join(str(person_name).split())
        self.responsible_people_by_task_scope[task_scope_id].add(display_name)
        self.task_scopes_by_responsible_person[normalized].add(task_scope_id)

    def _infer_responsibility_from_claims(self) -> None:
        for claim in self.claims.values():
            if str(claim.get("facet_key") or "").lower() != "owner":
                continue
            task_scope_ids = [
                str(scope_id)
                for scope_id in claim.get("task_object_scope_ids", []) or []
                if str(scope_id) in self.scopes
            ]
            if not task_scope_ids:
                continue
            person_names = _extract_person_names(
                " ".join(str(claim.get(key) or "") for key in ("object", "value"))
            )
            for person_name in person_names:
                for task_scope_id in task_scope_ids:
                    self._add_responsibility(person_name, task_scope_id)

    def _claim_text(self, claim_id: str) -> str:
        claim = self.claims.get(claim_id, {})
        return " ".join(
            str(part)
            for part in (
                claim.get("subject"),
                claim.get("predicate"),
                claim.get("object"),
                claim.get("facet_key"),
                claim.get("value"),
                claim.get("scope_hint"),
                claim.get("time_role"),
                claim.get("phase_role"),
                claim.get("time_value_source"),
                claim.get("time_value"),
                " ".join(str(value) for value in claim.get("task_object_labels", []) or []),
                claim.get("metric_type"),
                claim.get("metric_unit"),
                claim.get("metric_value_num"),
                claim.get("metric_value_text"),
                claim.get("metric_kind"),
                " ".join(
                    f"{time.get('time_role')}={time.get('value')} phase={time.get('phase_role') or ''} source={time.get('time_value_source') or ''}"
                    for time in self.times_by_claim.get(claim_id, [])
                ),
            )
            if part not in {None, ""}
        )

    def _event_text(self, event_id: str) -> str:
        event = self.events.get(event_id, {})
        return " ".join(
            str(part)
            for part in (
                event.get("date"),
                self.occurred_time_by_event.get(event_id),
                event.get("group"),
                event.get("speaker"),
                event.get("text"),
            )
            if part not in {None, ""}
        )

    def _state_doc(self, state_id: str) -> str:
        state = self.state_facets[state_id]
        support_claim_ids = [str(value) for value in state.get("support_claim_ids", []) if value]
        support_event_ids = [str(value) for value in state.get("support_event_ids", []) if value]
        parts: List[str] = [
            str(state.get("subject") or ""),
            str(state.get("facet_key") or ""),
            str(state.get("value") or ""),
            str(state.get("status") or ""),
            str(state.get("resolver_reason") or ""),
            str(state.get("current_after") or self.current_time_by_state.get(state_id) or ""),
            str(self.current_scope_by_state.get(state_id) or state.get("scope_id") or ""),
            " ".join(self._state_scope_ids(state_id)),
        ]
        parts.extend(self._claim_text(claim_id) for claim_id in support_claim_ids)
        parts.extend(self._event_text(event_id) for event_id in support_event_ids)
        return " ".join(part for part in parts if part)

    def _build_state_index(self) -> None:
        self._state_doc_ids = sorted(self.state_facets)
        self._state_docs = [self._state_doc(state_id) for state_id in self._state_doc_ids]
        self._state_index = BM25Index(self._state_doc_ids, self._state_docs)
        self._build_scope_index()
        self._build_temporal_endpoint_index()
        self._build_effort_metric_index()

    def _scope_doc(self, scope_id: str) -> str:
        scope = self.scopes[scope_id]
        event_ids = self.events_by_scope.get(scope_id, [])
        scope_type = str(scope.get("scope_type") or "")
        event_limit = 1200 if scope_type in {"group", "project"} else 240
        parts: List[str] = [
            scope_type,
            str(scope.get("label") or ""),
            str(scope.get("value") or ""),
            str(scope.get("scope_id") or ""),
        ]
        for event_id in event_ids[:event_limit]:
            parts.append(self._event_text(event_id))
            for claim_id in self.claims_by_event.get(event_id, [])[:2]:
                parts.append(self._claim_text(claim_id))
        return " ".join(part for part in parts if part)

    def _build_scope_index(self) -> None:
        self._scope_doc_ids = [
            scope_id
            for scope_id, scope in sorted(self.scopes.items())
            if str(scope.get("scope_type") or "") in {"project", "group", "person", "task_object"}
        ]
        self._scope_docs = [self._scope_doc(scope_id) for scope_id in self._scope_doc_ids]
        self._scope_doc_by_id = dict(zip(self._scope_doc_ids, self._scope_docs))
        self._scope_index = BM25Index(self._scope_doc_ids, self._scope_docs)

    def _event_claim_text(self, event_id: str) -> str:
        return " ".join(self._claim_text(claim_id) for claim_id in self.claims_by_event.get(event_id, []))

    def _temporal_candidate_date(self, event_id: str) -> Optional[str]:
        event = self.events.get(event_id, {})
        parsed = _parse_iso_day(event.get("date") or self.occurred_time_by_event.get(event_id))
        return parsed.isoformat() if parsed else None

    def _claim_time_profile(self, claim_id: str, allowed_roles: Sequence[str]) -> Dict[str, Any]:
        allowed = {str(role) for role in allowed_roles if role}
        best: Dict[str, Any] = {}
        best_score = -999.0
        for time_item in self.times_by_claim.get(claim_id, []):
            role = str(time_item.get("time_role") or "")
            if allowed and role not in allowed:
                continue
            source = str(time_item.get("time_value_source") or "")
            explicitness = float(time_item.get("time_explicitness_score") or 0.0)
            score = TIME_SOURCE_SCORE.get(source, 0.0) + explicitness
            if score > best_score:
                best_score = score
                best = dict(time_item)
        return best

    def _start_quality(self, document: str, claim: Optional[Mapping[str, Any]] = None) -> tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        if claim and claim.get("phase_role") == "started":
            score += 7.0
            reasons.append("claim_phase_started")
        if claim and claim.get("time_role") == "planned_for":
            score += 4.0
            reasons.append("claim_planned_for")
        has_strong_start = bool(STRONG_START_RE.search(document))
        if has_strong_start:
            score += 9.0
            reasons.append("strong_start_cue")
        elif START_CUE_RE.search(document):
            score += 2.0
            reasons.append("generic_start_cue")
        if not has_strong_start and NON_INITIAL_START_RE.search(document):
            score -= 12.0
            reasons.append("non_initial_start_penalty")
        return score, reasons

    def _end_quality(self, document: str, claim: Optional[Mapping[str, Any]] = None) -> tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        if claim and claim.get("phase_role") in {"completed", "finalized"}:
            score += 6.0
            reasons.append("claim_phase_end")
        has_strong_end = bool(STRONG_END_RE.search(document))
        if has_strong_end:
            score += 9.0
            reasons.append("strong_end_cue")
        elif END_CUE_RE.search(document):
            score += 2.0
            reasons.append("generic_end_cue")
        if NON_FINAL_END_RE.search(document):
            penalty = 6.0 if has_strong_end else 24.0
            score -= penalty
            reasons.append("non_final_end_penalty")
        return score, reasons

    def _add_temporal_candidate(
        self,
        candidate_id: str,
        endpoint_kind: str,
        event_id: str,
        document: str,
        source: str,
        source_id: str,
        quality_score: float,
        quality_reasons: Sequence[str],
        claim: Optional[Mapping[str, Any]] = None,
        time_profile: Optional[Mapping[str, Any]] = None,
    ) -> None:
        event = self.events.get(event_id)
        if not event:
            return
        time_value = str((time_profile or {}).get("value") or "")
        time_date = _parse_iso_day(time_value)
        event_date_text = time_date.isoformat() if time_date else self._temporal_candidate_date(event_id)
        if not event_date_text:
            return
        time_value_source = (time_profile or {}).get("time_value_source") or (claim.get("time_value_source") if claim else "event_text")
        time_explicitness_score = (time_profile or {}).get("time_explicitness_score")
        if time_explicitness_score is None and claim:
            time_explicitness_score = claim.get("time_explicitness_score")
        time_id = str((time_profile or {}).get("time_id") or "")
        if not time_id and event_id in self.occurred_time_id_by_event:
            time_id = self.occurred_time_id_by_event[event_id]
        candidate = {
            "candidate_id": candidate_id,
            "endpoint_kind": endpoint_kind,
            "source": source,
            "source_id": source_id,
            "event_id": event_id,
            "event_date": event_date_text,
            "group": event.get("group"),
            "speaker": event.get("speaker"),
            "evidence_text": " ".join(document.split())[:700],
            "scope_id": claim.get("scope_id") if claim else None,
            "task_object_scope_ids": list(claim.get("task_object_scope_ids", []) or []) if claim else [],
            "task_object_labels": list(claim.get("task_object_labels", []) or []) if claim else [],
            "subject": claim.get("subject") if claim else None,
            "predicate": claim.get("predicate") if claim else None,
            "object": claim.get("object") if claim else None,
            "value": claim.get("value") if claim else None,
            "facet_key": claim.get("facet_key") if claim else None,
            "time_role": (time_profile or {}).get("time_role") or (claim.get("time_role") if claim else "occurred_at"),
            "phase_role": claim.get("phase_role") if claim else None,
            "time_id": time_id,
            "time_value": time_value or event.get("date"),
            "time_value_source": time_value_source,
            "time_explicitness_score": time_explicitness_score,
            "quality_score": quality_score,
            "quality_reasons": list(quality_reasons),
        }
        self._temporal_endpoint_candidates[candidate_id] = candidate
        self._temporal_endpoint_doc_ids.append(candidate_id)
        self._temporal_endpoint_docs.append(document)

    def _build_temporal_endpoint_index(self) -> None:
        self._temporal_endpoint_candidates = {}
        self._temporal_endpoint_doc_ids = []
        self._temporal_endpoint_docs = []

        for claim_id, claim in sorted(self.claims.items()):
            event_id = str(claim.get("source_event_id") or "")
            event = self.events.get(event_id, {})
            document = " ".join(
                str(part)
                for part in (
                    self._claim_text(claim_id),
                    event.get("date"),
                    event.get("group"),
                    event.get("speaker"),
                    event.get("text"),
                )
                if part not in {None, ""}
            )
            if claim.get("phase_role") == "started" or claim.get("time_role") in {"started_at", "planned_for"}:
                quality_score, quality_reasons = self._start_quality(document, claim)
                time_profile = self._claim_time_profile(claim_id, ["started_at", "planned_for", "occurred_at"])
                self._add_temporal_candidate(
                    f"claim:{claim_id}:start",
                    "start",
                    event_id,
                    document,
                    "claim",
                    claim_id,
                    quality_score,
                    quality_reasons,
                    claim,
                    time_profile,
                )
            if claim.get("phase_role") in {"completed", "finalized"} or claim.get("time_role") in {"completed_at", "finalized_at"}:
                quality_score, quality_reasons = self._end_quality(document, claim)
                time_profile = self._claim_time_profile(claim_id, ["completed_at", "finalized_at", "occurred_at"])
                self._add_temporal_candidate(
                    f"claim:{claim_id}:end",
                    "end",
                    event_id,
                    document,
                    "claim",
                    claim_id,
                    quality_score,
                    quality_reasons,
                    claim,
                    time_profile,
                )

        for event_id, event in sorted(self.events.items()):
            document = " ".join(
                str(part)
                for part in (
                    event.get("date"),
                    event.get("group"),
                    event.get("speaker"),
                    event.get("text"),
                    self._event_claim_text(event_id),
                )
                if part not in {None, ""}
            )
            if START_CUE_RE.search(document) or re.search(r"new .* task", document, re.I):
                quality_score, quality_reasons = self._start_quality(document)
                self._add_temporal_candidate(
                    f"event:{event_id}:start",
                    "start",
                    event_id,
                    document,
                    "event",
                    event_id,
                    quality_score,
                    quality_reasons,
                )
            if END_CUE_RE.search(document):
                quality_score, quality_reasons = self._end_quality(document)
                self._add_temporal_candidate(
                    f"event:{event_id}:end",
                    "end",
                    event_id,
                    document,
                    "event",
                    event_id,
                    quality_score,
                    quality_reasons,
                )

        self._temporal_endpoint_index = BM25Index(self._temporal_endpoint_doc_ids, self._temporal_endpoint_docs)

    def _metric_fields_for_claim(self, claim_id: str) -> Dict[str, Any]:
        claim = self.claims.get(claim_id, {})
        if claim.get("metric_type") and claim.get("metric_value_num") is not None:
            return {
                "metric_type": claim.get("metric_type"),
                "metric_unit": claim.get("metric_unit"),
                "metric_value_num": claim.get("metric_value_num"),
                "metric_value_text": claim.get("metric_value_text"),
                "metric_kind": claim.get("metric_kind"),
                "metric_source": claim.get("metric_source"),
            }
        return _fallback_effort_metric(self._claim_text(claim_id), str(claim.get("facet_key") or ""))

    def _add_effort_metric_candidate(
        self,
        candidate_id: str,
        claim_id: str,
        source: str,
        state_id: Optional[str] = None,
    ) -> None:
        claim = self.claims.get(claim_id, {})
        metric = self._metric_fields_for_claim(claim_id)
        if not claim or not metric:
            return
        event_id = str(claim.get("source_event_id") or "")
        event = self.events.get(event_id, {})
        if not event:
            return
        state = self.state_facets.get(state_id or "", {})
        document = " ".join(
            str(part)
            for part in (
                self._claim_text(claim_id),
                state.get("subject"),
                state.get("facet_key"),
                state.get("value"),
                event.get("date"),
                event.get("group"),
                event.get("speaker"),
                event.get("text"),
            )
            if part not in {None, ""}
        )
        candidate = {
            "candidate_id": candidate_id,
            "source": source,
            "claim_id": claim_id,
            "state_facet_id": state_id,
            "event_id": event_id,
            "event_date": self._temporal_candidate_date(event_id),
            "group": event.get("group"),
            "speaker": event.get("speaker"),
            "scope_id": claim.get("scope_id"),
            "subject": claim.get("subject"),
            "facet_key": claim.get("facet_key"),
            "value": claim.get("value"),
            "evidence_text": " ".join(document.split())[:900],
            **metric,
        }
        self._effort_metric_candidates[candidate_id] = candidate
        self._effort_metric_doc_ids.append(candidate_id)
        self._effort_metric_docs.append(document)

    def _add_effort_event_candidate(self, event_id: str) -> None:
        event = self.events.get(event_id, {})
        if not event:
            return
        metric = _fallback_effort_metric(str(event.get("text") or ""), "metric")
        if not metric:
            return
        document = " ".join(
            str(part)
            for part in (
                event.get("date"),
                event.get("group"),
                event.get("speaker"),
                event.get("text"),
                metric.get("metric_value_text"),
                metric.get("metric_type"),
                metric.get("metric_unit"),
            )
            if part not in {None, ""}
        )
        candidate_id = f"event:{event_id}:metric"
        candidate = {
            "candidate_id": candidate_id,
            "source": "event",
            "claim_id": None,
            "state_facet_id": None,
            "event_id": event_id,
            "event_date": self._temporal_candidate_date(event_id),
            "group": event.get("group"),
            "speaker": event.get("speaker"),
            "scope_id": None,
            "subject": None,
            "facet_key": "metric",
            "value": metric.get("metric_value_text"),
            "evidence_text": " ".join(document.split())[:900],
            **metric,
        }
        self._effort_metric_candidates[candidate_id] = candidate
        self._effort_metric_doc_ids.append(candidate_id)
        self._effort_metric_docs.append(document)

    def _build_effort_metric_index(self) -> None:
        self._effort_metric_candidates = {}
        self._effort_metric_doc_ids = []
        self._effort_metric_docs = []
        for claim_id in sorted(self.claims):
            self._add_effort_metric_candidate(f"claim:{claim_id}:metric", claim_id, "claim")
        for state_id, state in sorted(self.state_facets.items()):
            for claim_id in state.get("support_claim_ids", []) or []:
                claim_id_text = str(claim_id)
                if claim_id_text in self.claims:
                    self._add_effort_metric_candidate(f"state:{state_id}:{claim_id_text}:metric", claim_id_text, "state_facet", state_id)
        for event_id in sorted(self.events):
            self._add_effort_event_candidate(event_id)
        self._effort_metric_index = BM25Index(self._effort_metric_doc_ids, self._effort_metric_docs)

    def rank_effort_metric_candidates(
        self,
        query: str,
        top_k: int,
        scope_ids: Optional[Sequence[str]] = None,
        boost_event_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        if self._effort_metric_index is None or top_k <= 0:
            return []
        allowed_scopes = {str(scope_id) for scope_id in scope_ids or [] if scope_id}
        allowed_events = self.events_for_scopes(list(allowed_scopes)) if allowed_scopes else set()
        boosted_events = {str(event_id) for event_id in boost_event_ids or [] if event_id}
        ranked = self._rank_index(
            self._effort_metric_index,
            self._embedding_effort_metric_index,
            query,
            max(top_k * 20, top_k),
        )
        candidates: List[Dict[str, Any]] = []
        seen_claims: set[str] = set()
        for ranked_candidate in ranked:
            candidate = dict(self._effort_metric_candidates.get(str(ranked_candidate["doc_id"]), {}))
            if not candidate:
                continue
            event_id = str(candidate.get("event_id") or "")
            if allowed_events and event_id not in allowed_events:
                continue
            claim_id = str(candidate.get("claim_id") or "")
            seen_key = claim_id or str(candidate.get("candidate_id") or "")
            if seen_key in seen_claims:
                continue
            seen_claims.add(seen_key)
            content_score, content_trace = _endpoint_content_match_score(query, str(candidate.get("evidence_text") or ""))
            graph_boost = 8.0 if event_id in boosted_events else 0.0
            metric_type = str(candidate.get("metric_type") or "")
            unit_score = 0.0
            lowered_query = query.lower()
            if "person" in lowered_query and metric_type == "person_days":
                unit_score += 8.0
            if "work" in lowered_query and metric_type == "workdays":
                unit_score += 8.0
            if "day" in lowered_query and metric_type == "duration_days":
                unit_score += 2.0
            candidate["bm25_score"] = round(float(ranked_candidate.get("lexical_score") or 0.0), 4)
            candidate["embedding_score"] = round(float(ranked_candidate.get("embedding_score") or 0.0), 6)
            candidate["retrieval_source"] = ranked_candidate.get("retrieval_source")
            candidate["graph_expansion_boost"] = graph_boost
            candidate["content_match_score"] = content_score
            candidate["content_match_trace"] = content_trace
            candidate["unit_score"] = unit_score
            candidate["score"] = float(ranked_candidate.get("score") or 0.0) + content_score + graph_boost + unit_score
            candidates.append(candidate)
        candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("event_id") or "")))
        return candidates[:top_k]

    def rank_temporal_endpoint_candidates(
        self,
        query: str,
        endpoint_kind: str,
        top_k: int,
        scope_ids: Optional[Sequence[str]] = None,
        allowed_time_roles: Optional[Sequence[str]] = None,
        boost_event_ids: Optional[Sequence[str]] = None,
        allowed_event_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        if self._temporal_endpoint_index is None or top_k <= 0:
            return []
        allowed_scopes = {str(scope_id) for scope_id in scope_ids or [] if scope_id}
        if allowed_event_ids is not None:
            allowed_events = {str(event_id) for event_id in allowed_event_ids if event_id}
        else:
            allowed_events = self.events_for_scopes(list(allowed_scopes)) if allowed_scopes else set()
        allowed_roles = {str(role) for role in allowed_time_roles or [] if role}
        boosted_events = {str(event_id) for event_id in boost_event_ids or [] if event_id}
        ranked = self._rank_index(
            self._temporal_endpoint_index,
            self._embedding_temporal_endpoint_index,
            query,
            max(top_k * 12, top_k),
        )
        candidates: List[Dict[str, Any]] = []
        for ranked_candidate in ranked:
            candidate = dict(self._temporal_endpoint_candidates.get(str(ranked_candidate["doc_id"]), {}))
            if not candidate:
                continue
            if candidate.get("endpoint_kind") != endpoint_kind:
                continue
            if allowed_events and str(candidate.get("event_id") or "") not in allowed_events:
                continue
            if allowed_roles and str(candidate.get("time_role") or "occurred_at") not in allowed_roles:
                continue
            content_score, content_trace = _endpoint_content_match_score(
                query,
                str(candidate.get("evidence_text") or ""),
            )
            quality_reasons = {str(reason) for reason in candidate.get("quality_reasons", []) or []}
            query_terms = set(_endpoint_terms(query))
            evidence_text = str(candidate.get("evidence_text") or "")
            allows_draft_completion = (
                endpoint_kind == "end"
                and {"strategy", "report", "guide", "manual", "material"} & query_terms
                and re.search(r"\b(?:draft|preliminary).{0,80}\b(?:completed|uploaded|released)\b", evidence_text, re.I)
            )
            if (
                endpoint_kind == "end"
                and "non_final_end_penalty" in quality_reasons
                and "strong_end_cue" not in quality_reasons
                and not allows_draft_completion
            ):
                content_score *= 0.35
                content_trace = {**content_trace, "non_final_content_scale": 0.35}
            if (
                endpoint_kind == "start"
                and "non_initial_start_penalty" in quality_reasons
                and "strong_start_cue" not in quality_reasons
            ):
                content_score *= 0.45
                content_trace = {**content_trace, "non_initial_content_scale": 0.45}
            candidate["bm25_score"] = round(float(ranked_candidate.get("lexical_score") or 0.0), 4)
            candidate["embedding_score"] = round(float(ranked_candidate.get("embedding_score") or 0.0), 6)
            candidate["retrieval_source"] = ranked_candidate.get("retrieval_source")
            graph_boost = 8.0 if str(candidate.get("event_id") or "") in boosted_events else 0.0
            time_source_score = TIME_SOURCE_SCORE.get(str(candidate.get("time_value_source") or ""), 0.0)
            time_source_score += float(candidate.get("time_explicitness_score") or 0.0)
            semantic_penalty = 0.0
            structured_text = " ".join(
                str(part)
                for part in (
                    candidate.get("subject"),
                    candidate.get("predicate"),
                    candidate.get("object"),
                    candidate.get("value"),
                    " ".join(str(label) for label in candidate.get("task_object_labels", []) or []),
                )
                if part
            )
            structured_terms = set(_endpoint_terms(structured_text))
            evidence_terms = set(_endpoint_terms(evidence_text))
            if (
                str(candidate.get("source") or "") == "claim"
                and {"dashboard", "workbench", "center", "user"} & query_terms
                and not ({"api", "interface", "aggregate"} & query_terms)
                and {"api", "interface", "aggregate"} & structured_terms
            ):
                    semantic_penalty -= 18.0
            if endpoint_kind == "start" and "develop" in query_terms:
                if re.search(
                    r"\b(low[- ]?fidelity|high[- ]?fidelity|wireframes?|IA draft|design draft|"
                    r"component specifications?|preliminary layout|interactive high[- ]?fidelity prototypes?)\b",
                    evidence_text,
                    re.I,
                ):
                    semantic_penalty -= 24.0
                if re.search(r"\bfirst draft\b", evidence_text, re.I) and not re.search(
                    r"\b(?:started on|start(?:ed|ing)? developing|officially start(?:ed|ing))\b",
                    evidence_text,
                    re.I,
                ):
                    semantic_penalty -= 16.0
                if (
                    str(candidate.get("source") or "") == "claim"
                    and not ({"strong_start_cue", "generic_start_cue"} & quality_reasons)
                    and not re.search(
                        r"\b(?:officially start(?:ed|ing)|i'?ve started|started on|"
                        r"start(?:ed|ing)? (?:work|develop|build|implement|test|write)|"
                        r"begin(?:s|ning)? (?:work|develop|build|implement|test|write)|new task)\b",
                        evidence_text,
                        re.I,
                    )
                ):
                    semantic_penalty -= 18.0
                if re.search(
                    r"\b(?:unclear|next week|schedule unclear|final confirmation|suggested|"
                    r"separated from|preference|research information architecture)\b",
                    evidence_text,
                    re.I,
                ):
                    semantic_penalty -= 12.0
                if re.search(
                    r"\b(?:integrating? data display|switch from mock data|yesterday .{0,80} API (?:was )?deployed|"
                    r"joint debugging|connect(?:ing)? it|data display part)\b",
                    evidence_text,
                    re.I,
                ):
                    semantic_penalty -= 24.0
                if "test" not in query_terms and re.search(r"\b(?:testing|regression testing)\b", evidence_text, re.I):
                    semantic_penalty -= 18.0
            if allows_draft_completion:
                semantic_penalty += 30.0
                if "market" in query_terms and "market" in evidence_terms:
                    semantic_penalty += 20.0
            candidate["graph_expansion_boost"] = graph_boost
            candidate["time_source_score"] = round(time_source_score, 4)
            candidate["semantic_penalty"] = round(semantic_penalty, 4)
            candidate["content_match_score"] = content_score
            candidate["content_match_trace"] = content_trace
            candidate["score"] = (
                float(ranked_candidate.get("score") or 0.0)
                + float(candidate.get("quality_score") or 0.0)
                + graph_boost
                + time_source_score
                + content_score
                + semantic_penalty
            )
            candidates.append(candidate)
        candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("event_id") or "")))
        return candidates[:top_k]

    def temporal_endpoint_candidates(
        self,
        endpoint_kind: str,
        allowed_time_roles: Optional[Sequence[str]] = None,
        allowed_event_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        allowed_roles = {str(role) for role in allowed_time_roles or [] if role}
        allowed_events = {str(event_id) for event_id in allowed_event_ids or [] if event_id}
        candidates: List[Dict[str, Any]] = []
        for candidate in self._temporal_endpoint_candidates.values():
            if candidate.get("endpoint_kind") != endpoint_kind:
                continue
            if allowed_roles and str(candidate.get("time_role") or "occurred_at") not in allowed_roles:
                continue
            if allowed_events and str(candidate.get("event_id") or "") not in allowed_events:
                continue
            candidate_copy = dict(candidate)
            time_source_score = TIME_SOURCE_SCORE.get(str(candidate_copy.get("time_value_source") or ""), 0.0)
            time_source_score += float(candidate_copy.get("time_explicitness_score") or 0.0)
            candidate_copy["time_source_score"] = round(time_source_score, 4)
            candidate_copy["score"] = float(candidate_copy.get("quality_score") or 0.0) + time_source_score
            candidates.append(candidate_copy)
        candidates.sort(key=lambda item: (str(item.get("event_date") or ""), -float(item.get("score") or 0.0), str(item.get("event_id") or "")))
        return candidates

    def resolve_temporal_interval(
        self,
        start_query: str,
        end_query: str,
        start_endpoint_kind: str,
        end_endpoint_kind: str,
        top_k: int,
        scope_ids: Optional[Sequence[str]] = None,
        inclusive: bool = True,
        start_time_roles: Optional[Sequence[str]] = None,
        end_time_roles: Optional[Sequence[str]] = None,
        boost_event_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        start_candidates = self.rank_temporal_endpoint_candidates(
            start_query,
            start_endpoint_kind,
            top_k,
            scope_ids,
            allowed_time_roles=start_time_roles,
            boost_event_ids=boost_event_ids,
        )
        end_candidates = self.rank_temporal_endpoint_candidates(
            end_query,
            end_endpoint_kind,
            top_k,
            scope_ids,
            allowed_time_roles=end_time_roles,
            boost_event_ids=boost_event_ids,
        )
        best_pair: Optional[Dict[str, Any]] = None

        for start_candidate in start_candidates:
            start_date = _parse_iso_day(start_candidate.get("event_date"))
            if start_date is None:
                continue
            for end_candidate in end_candidates:
                end_date = _parse_iso_day(end_candidate.get("event_date"))
                if end_date is None or end_date < start_date:
                    continue
                day_delta = (end_date - start_date).days
                computed_days = day_delta + 1 if inclusive else day_delta
                pair_score = float(start_candidate.get("score") or 0.0) + float(end_candidate.get("score") or 0.0)
                if start_candidate.get("group") == end_candidate.get("group"):
                    pair_score += 12.0
                else:
                    pair_score -= 4.0
                if 2 <= computed_days <= 14:
                    pair_score += min(8.0, float(computed_days))
                if computed_days == 1:
                    pair_score -= 3.0
                if computed_days > 21:
                    pair_score -= 10.0
                if start_candidate.get("source") == "claim":
                    pair_score += 1.0
                if end_candidate.get("source") == "claim":
                    pair_score += 1.0
                pair = {
                    "pair_score": pair_score,
                    "start": start_candidate,
                    "end": end_candidate,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "computed_days": computed_days,
                    "inclusive": inclusive,
                }
                if best_pair is None or pair_score > float(best_pair.get("pair_score") or 0.0):
                    best_pair = pair

        return {
            "resolver": "sts_temporal_endpoint_graph",
            "start_query": start_query,
            "end_query": end_query,
            "start_endpoint_kind": start_endpoint_kind,
            "end_endpoint_kind": end_endpoint_kind,
            "top_k": top_k,
            "top_start_candidates": start_candidates[:8],
            "top_end_candidates": end_candidates[:8],
            "selected_pair": best_pair,
            "error": None if best_pair else "no_valid_temporal_pair",
        }

    def route_scopes(self, query: str, top_k: int, scope_types: Sequence[str]) -> List[Dict[str, Any]]:
        allowed_types = {str(value) for value in scope_types}
        if self._scope_index is None or top_k <= 0:
            return []
        candidates: List[Dict[str, Any]] = []
        scope_search_k = max(top_k * 12, top_k, 32)
        ranked_scopes = self._rank_index(
            self._scope_index,
            self._embedding_scope_index,
            query,
            scope_search_k,
        )
        for ranked in ranked_scopes:
            scope_id = str(ranked["doc_id"])
            scope = self.scopes.get(scope_id, {})
            scope_type = str(scope.get("scope_type") or "")
            if allowed_types and scope_type not in allowed_types:
                continue
            label_doc = " ".join(
                str(part)
                for part in (scope_type, scope.get("label"), scope.get("value"), scope.get("scope_id"))
                if part not in {None, ""}
            )
            label_score, label_trace = _endpoint_content_match_score(query, label_doc)
            doc_score, doc_trace = _endpoint_content_match_score(query, self._scope_doc_by_id.get(scope_id, ""))
            if scope_type == "task_object":
                content_score = (2.0 * label_score) + min(doc_score, 8.0)
            elif scope_type in {"group", "project"}:
                content_score = label_score + min(doc_score, 12.0)
            else:
                content_score = label_score + min(doc_score, 6.0)
            score = float(ranked.get("score") or 0.0) + content_score
            candidates.append(
                {
                    "scope_id": scope_id,
                    "scope_type": scope_type,
                    "label": scope.get("label"),
                    "score": score,
                    "lexical_score": round(float(ranked.get("lexical_score") or 0.0), 4),
                    "embedding_score": round(float(ranked.get("embedding_score") or 0.0), 6),
                    "retrieval_source": ranked.get("retrieval_source"),
                    "content_match_score": content_score,
                    "content_match_trace": {
                        "label": label_trace,
                        "document": doc_trace,
                        "label_score": round(label_score, 4),
                        "document_score": round(doc_score, 4),
                    },
                    "event_count": len(self.events_by_scope.get(scope_id, [])),
                }
            )
        if not candidates:
            return []
        candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("scope_id") or "")))
        if "task_object" in allowed_types and top_k > 1:
            by_type: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
            for candidate in candidates:
                by_type[str(candidate.get("scope_type") or "")].append(candidate)
            selected: List[Dict[str, Any]] = []
            selected_ids: set[str] = set()

            def add_candidates(scope_type: str, quota: int) -> None:
                nonlocal selected
                for candidate in by_type.get(scope_type, []):
                    if len(selected) >= top_k or quota <= 0:
                        break
                    scope_id = str(candidate["scope_id"])
                    if scope_id in selected_ids:
                        continue
                    selected.append(candidate)
                    selected_ids.add(scope_id)
                    quota -= 1

            add_candidates("task_object", min(2, top_k))
            if len(selected) < top_k:
                add_candidates("group", 1)
            if len(selected) < top_k:
                add_candidates("person", 1)
            for candidate in candidates:
                if len(selected) >= top_k:
                    break
                scope_id = str(candidate["scope_id"])
                if scope_id not in selected_ids:
                    selected.append(candidate)
                    selected_ids.add(scope_id)
            return selected[:top_k]
        if {"group", "person"}.issubset(allowed_types) and top_k > 1:
            by_type: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
            for candidate in candidates:
                by_type[str(candidate.get("scope_type") or "")].append(candidate)
            selected: List[Dict[str, Any]] = []
            group_quota = min(3, top_k)
            selected.extend(by_type.get("group", [])[:group_quota])
            selected_ids = {str(scope["scope_id"]) for scope in selected}
            for candidate in by_type.get("person", []):
                if len(selected) >= top_k:
                    break
                if str(candidate["scope_id"]) not in selected_ids:
                    selected.append(candidate)
                    selected_ids.add(str(candidate["scope_id"]))
            for candidate in candidates:
                if len(selected) >= top_k:
                    break
                if str(candidate["scope_id"]) not in selected_ids:
                    selected.append(candidate)
                    selected_ids.add(str(candidate["scope_id"]))
            return selected[:top_k]
        return candidates[:top_k]

    def events_for_scopes(self, scope_ids: Sequence[str]) -> set[str]:
        event_ids: set[str] = set()
        for scope_id in scope_ids:
            event_ids.update(self.events_by_scope.get(str(scope_id), []))
        return event_ids

    def candidate_task_object_scope_ids(self, candidate: Mapping[str, Any]) -> List[str]:
        scope_ids = [
            str(scope_id)
            for scope_id in candidate.get("task_object_scope_ids", []) or []
            if str(scope_id) in self.scopes
        ]
        source_id = str(candidate.get("source_id") or "")
        claim = self.claims.get(source_id, {})
        for scope_id in claim.get("task_object_scope_ids", []) or []:
            scope_text = str(scope_id)
            if scope_text in self.scopes and scope_text not in scope_ids:
                scope_ids.append(scope_text)
        return scope_ids

    def candidate_responsible_people(self, candidate: Mapping[str, Any]) -> List[str]:
        people: List[str] = []
        seen: set[str] = set()
        for scope_id in self.candidate_task_object_scope_ids(candidate):
            for person in sorted(self.responsible_people_by_task_scope.get(scope_id, set())):
                key = _normalize_person_name(person)
                if key and key not in seen:
                    seen.add(key)
                    people.append(person)
        speaker = str(candidate.get("speaker") or "").strip()
        if speaker:
            key = _normalize_person_name(speaker)
            if key and key not in seen:
                seen.add(key)
                people.append(speaker)
        return people

    def _state_scope_ids(self, state_id: str) -> List[str]:
        state = self.state_facets.get(state_id, {})
        scope_ids: List[str] = []
        for scope_id in self.current_scopes_by_state.get(state_id, []):
            if scope_id:
                scope_ids.append(str(scope_id))
        fallback = str(self.current_scope_by_state.get(state_id) or state.get("scope_id") or "")
        if fallback:
            scope_ids.append(fallback)
        return list(dict.fromkeys(scope_ids))

    def _state_time_roles(self, state_id: str) -> List[str]:
        roles: List[str] = []
        state = self.state_facets.get(state_id, {})
        if state.get("current_after") or self.current_time_by_state.get(state_id):
            roles.append("CURRENT_AFTER")
        for claim_id in state.get("support_claim_ids", []) or []:
            claim = self.claims.get(str(claim_id), {})
            claim_role = claim.get("time_role")
            if claim_role:
                roles.append(str(claim_role))
            for time_item in self.times_by_claim.get(str(claim_id), []):
                time_role = time_item.get("time_role")
                if time_role:
                    roles.append(str(time_role))
        return list(dict.fromkeys(roles))

    def _state_relation_profile(self, state_id: str) -> Dict[str, Any]:
        profile: Dict[str, Any] = {
            "outgoing_validity_edges": [],
            "incoming_validity_edges": [],
            "conflict_edges": [],
        }
        state = self.state_facets.get(state_id, {})
        support_claims = {str(claim_id) for claim_id in state.get("support_claim_ids", []) or []}
        for claim_id in support_claims:
            for edge in self.relations_by_claim.get(claim_id, []):
                edge_type = str(edge.get("type") or "")
                source = str(edge.get("from") or "")
                target = str(edge.get("to") or "")
                compact_edge = {
                    "type": edge_type,
                    "from": source,
                    "to": target,
                    "evidence_event_ids": list(edge.get("evidence_event_ids") or []),
                    "reason": edge.get("reason"),
                }
                if edge_type == "CONFLICTS_WITH":
                    profile["conflict_edges"].append(compact_edge)
                elif source == claim_id:
                    profile["outgoing_validity_edges"].append(compact_edge)
                elif target == claim_id:
                    profile["incoming_validity_edges"].append(compact_edge)
        return profile

    def select_state_facets(
        self,
        query: str,
        scope_ids: Optional[Sequence[str]],
        time_roles: Optional[Sequence[str]],
        limit: int,
        search_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if self._state_index is None or limit <= 0:
            return []
        allowed_scopes = {str(scope_id) for scope_id in scope_ids or [] if scope_id}
        allowed_time_roles = {str(role) for role in time_roles or [] if role}
        ranked_states = self._rank_index(
            self._state_index,
            self._embedding_state_index,
            query,
            search_k or max(limit * 12, limit),
        )
        selected: List[Dict[str, Any]] = []
        for rank, ranked in enumerate(ranked_states, start=1):
            state_id = str(ranked["doc_id"])
            state = self.state_facets.get(state_id, {})
            state_scope_ids = self._state_scope_ids(state_id)
            state_scope = str(self.current_scope_by_state.get(state_id) or state.get("scope_id") or "")
            if allowed_scopes and not allowed_scopes.intersection(state_scope_ids):
                continue
            status = str(state.get("status") or "")
            state_time_roles = self._state_time_roles(state_id)
            relation_profile = self._state_relation_profile(state_id)
            validity_score = 0.0
            if status == "current":
                validity_score += 3.0
            elif status in {"ambiguous", "conflict_unresolved"}:
                validity_score -= 2.0
            if state.get("current_after") or self.current_time_by_state.get(state_id):
                validity_score += 1.5
            validity_score += 1.5 * len(relation_profile["outgoing_validity_edges"])
            validity_score -= 2.0 * len(relation_profile["incoming_validity_edges"])
            validity_score -= 1.0 * len(relation_profile["conflict_edges"])

            time_role_score = 0.0
            if allowed_time_roles:
                matched_roles = allowed_time_roles.intersection(state_time_roles)
                if matched_roles:
                    time_role_score += 2.0 + 0.5 * len(matched_roles)
                elif "CURRENT_AFTER" in allowed_time_roles and (state.get("current_after") or self.current_time_by_state.get(state_id)):
                    time_role_score += 1.5
                else:
                    time_role_score -= 0.5
            total_score = float(ranked.get("score") or 0.0) + validity_score + time_role_score
            selected.append(
                {
                    "state_facet_id": state_id,
                    "scope_id": state_scope,
                    "scope_ids": state_scope_ids,
                    "rank": rank,
                    "score": round(total_score, 4),
                    "lexical_score": round(float(ranked.get("lexical_score") or 0.0), 4),
                    "embedding_score": round(float(ranked.get("embedding_score") or 0.0), 6),
                    "retrieval_source": ranked.get("retrieval_source"),
                    "validity_score": round(validity_score, 4),
                    "time_role_score": round(time_role_score, 4),
                    "status": status,
                    "time_roles": state_time_roles,
                    "current_after": state.get("current_after") or self.current_time_by_state.get(state_id),
                    "support_event_ids": list(state.get("support_event_ids", []) or []),
                    "support_claim_ids": list(state.get("support_claim_ids", []) or []),
                    "relation_profile": relation_profile,
                    "summary": self.state_summary(state_id),
                }
            )
        selected.sort(key=lambda item: (-float(item["score"]), int(item["rank"]), str(item["state_facet_id"])))
        return selected[:limit]

    def expand(
        self,
        qa_item: Mapping[str, Any],
        seed_event_ids: Sequence[str],
        include_options_in_query: bool,
        state_search_k: int,
        max_context_events: int,
        query_text: Optional[str] = None,
        scope_ids: Optional[Sequence[str]] = None,
    ) -> ExpandedEvidence:
        notes: DefaultDict[str, List[str]] = defaultdict(list)
        ordered_events: List[str] = []
        state_facet_ids: List[str] = []
        relation_summaries: List[str] = []
        visited_claims: set[str] = set()
        visited_relation_edges: set[tuple[str, str, str]] = set()
        relation_edge_count = 0
        allowed_scopes = {str(scope_id) for scope_id in scope_ids or [] if scope_id}
        allowed_events = self.events_for_scopes(list(allowed_scopes)) if allowed_scopes else set()

        def add_event(event_id: object, reason: str) -> None:
            text = str(event_id or "")
            if text not in self.events:
                return
            if allowed_events and text not in allowed_events:
                return
            if text not in ordered_events:
                ordered_events.append(text)
            if reason not in notes[text]:
                notes[text].append(reason)

        def add_state(state_id: object, reason: str) -> None:
            text = str(state_id or "")
            state = self.state_facets.get(text)
            if not state:
                return
            state_scope_ids = self._state_scope_ids(text)
            if allowed_scopes and not allowed_scopes.intersection(state_scope_ids):
                return
            if text not in state_facet_ids:
                state_facet_ids.append(text)
            for event_id in state.get("support_event_ids", []) or []:
                add_event(event_id, f"{reason}; SUPPORTS->StateFacet support_event")
            for claim_id in state.get("support_claim_ids", []) or []:
                add_claim(claim_id, f"{reason}; StateFacet support_claim")

        def add_relation_neighbors(claim_id: str, reason: str) -> None:
            nonlocal relation_edge_count
            for edge in self.relations_by_claim.get(claim_id, []):
                edge_key = (str(edge.get("type") or ""), str(edge.get("from") or ""), str(edge.get("to") or ""))
                if edge_key in visited_relation_edges:
                    continue
                visited_relation_edges.add(edge_key)
                relation_edge_count += 1
                relation_summaries.append(self._relation_summary(edge))
                source = str(edge.get("from") or "")
                target = str(edge.get("to") or "")
                other = target if source == claim_id else source
                add_claim(other, f"{reason}; {edge.get('type')} related_claim")
                for event_id in edge.get("evidence_event_ids", []) or []:
                    add_event(event_id, f"{reason}; {edge.get('type')} evidence_event")

        def add_claim(claim_id: object, reason: str) -> None:
            text = str(claim_id or "")
            claim = self.claims.get(text)
            if not claim:
                return
            if text in visited_claims:
                return
            visited_claims.add(text)
            add_event(claim.get("source_event_id"), f"{reason}; ASSERTS claim_source")
            add_relation_neighbors(text, reason)
            for state_id in self.states_by_claim.get(text, []):
                add_state(state_id, f"{reason}; SUPPORTS StateFacet")

        if self._state_index is not None and state_search_k > 0:
            query = query_text or qa_query_text(qa_item, include_options=include_options_in_query)
            search_k = max(state_search_k * 12, state_search_k)
            added_states = 0
            for rank, ranked_state in enumerate(
                self._rank_index(self._state_index, self._embedding_state_index, query, search_k),
                start=1,
            ):
                before = len(state_facet_ids)
                add_state(
                    ranked_state["doc_id"],
                    f"statefacet_{ranked_state.get('retrieval_source') or 'bm25'}_rank={rank}",
                )
                if len(state_facet_ids) > before:
                    added_states += 1
                if added_states >= state_search_k:
                    break

        for rank, event_id in enumerate(seed_event_ids, start=1):
            add_event(event_id, f"scoped_bm25_seed_rank={rank}")
            for claim_id in self.claims_by_event.get(str(event_id), []):
                add_claim(claim_id, f"scoped_bm25_seed_rank={rank}; ASSERTS")

        if max_context_events > 0:
            ordered_events = ordered_events[:max_context_events]
            notes = defaultdict(list, {event_id: notes[event_id] for event_id in ordered_events})

        return ExpandedEvidence(
            event_ids=ordered_events,
            notes_by_event={event_id: values for event_id, values in notes.items()},
            seed_event_ids=[str(event_id) for event_id in seed_event_ids],
            state_facet_ids=state_facet_ids,
            state_summaries=[self.state_summary(state_id) for state_id in state_facet_ids[:state_search_k + len(seed_event_ids)]],
            relation_summaries=relation_summaries,
            relation_edge_count=relation_edge_count,
        )

    def state_summary(self, state_id: str) -> str:
        state = self.state_facets.get(state_id, {})
        support_events = [str(value) for value in state.get("support_event_ids", []) or [] if value]
        support_claims = [str(value) for value in state.get("support_claim_ids", []) or [] if value]
        support_times = [
            {
                "claim_id": claim_id,
                "times": self.times_by_claim.get(claim_id, []),
            }
            for claim_id in support_claims
            if self.times_by_claim.get(claim_id)
        ]
        current_after = str(state.get("current_after") or self.current_time_by_state.get(state_id) or "")
        scope = str(self.current_scope_by_state.get(state_id) or state.get("scope_id") or "")
        scopes = ",".join(self._state_scope_ids(state_id))
        return (
            f"state_facet_id={state_id}; scope={scope}; scopes={scopes}; CURRENT_AFTER={current_after}; "
            f"subject={state.get('subject')}; facet={state.get('facet_key')}; "
            f"status={state.get('status')}; value={state.get('value')}; "
            f"support_events={support_events}; support_claims={support_claims}; "
            f"support_times={support_times}; "
            f"resolver={state.get('resolver_mode')}: {state.get('resolver_reason')}"
        )

    def _relation_summary(self, edge: Mapping[str, Any]) -> str:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        return (
            f"{edge.get('type')}: from={source} to={target}; "
            f"evidence_event_ids={edge.get('evidence_event_ids')}; reason={edge.get('reason')}; "
            f"from_claim=({self._claim_text(source)}); to_claim=({self._claim_text(target)})"
        )

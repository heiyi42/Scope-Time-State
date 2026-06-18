from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import os
import re
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.mixture import GaussianMixture
except Exception:  # pragma: no cover - deterministic fallback is tested by import.
    np = None
    TfidfVectorizer = None
    GaussianMixture = None

try:
    import spacy
    from dateparser.search import search_dates
except Exception:  # pragma: no cover - regex/intention fallback keeps the baseline runnable.
    spacy = None
    search_dates = None

from ...common import BaselinePromptSpec, event_view, parse_time


TOP_K = 25
MAX_VISIBLE_EVENTS = 25
CONTEXT_TURNS = 4
MAX_UPDATE_CANDIDATES = 12

LLMJSONFn = Callable[[str, str], Dict[str, object]]

EVENT_SEMANTIC_TIME_ROLES = ("planned_for", "deadline_at", "occurred_at", "updated_at", "mentioned_at")

HEURISTIC_REVISION_MARKERS = (
    "纠正",
    "修正",
    "更正",
    "替代",
    "转向",
    "改为",
    "恢复",
    "已解决",
    "修复",
    "不再",
    "取消",
    "废弃",
    "invalid",
    "replace",
    "resolved",
    "fixed",
    "cancel",
)

FUTURE_QUERY_MARKERS = ("下一步", "安排", "计划", "待", "deadline", "due", "next")
CURRENT_QUERY_MARKERS = ("最近", "现在", "当前", "到哪", "怎么样", "latest", "current", "now")
PAST_QUERY_MARKERS = ("之前", "过去", "上次", "历史", "old", "previous", "before")

RELATION_BY_EVENT_TYPE = {
    "paper_reading": "read_related_work",
    "related_work": "has_related_work_risk",
    "idea": "proposed_direction",
    "decision": "decided_state",
    "mention": "mentioned_context",
    "progress": "made_progress",
    "diagnosis": "diagnosed_issue",
    "correction": "corrected_state",
    "plan": "planned_next_step",
    "deadline": "has_deadline",
    "draft": "drafted_artifact",
    "fix": "fixed_issue",
    "issue": "has_issue",
    "experiment": "ran_experiment",
    "execution_log": "logged_execution",
    "feedback": "received_feedback",
    "incident": "had_incident",
    "mitigation": "applied_mitigation",
    "root_cause": "identified_root_cause",
}

STOP_TERMS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "have",
    "has",
    "项目",
    "最近",
    "现在",
    "当前",
    "下一步",
    "问题",
    "什么",
    "怎么",
    "怎么样",
}


@dataclass
class EntityNode:
    name: str
    summary: str
    event_ids: List[str] = field(default_factory=list)


@dataclass
class TemporalFact:
    fact_id: str
    subject: str
    relation: str
    object_text: str
    valid_time: str
    invalid_time: Optional[str]
    source_event_id: str
    operation: str
    supporting_entities: List[str]
    invalidated_by: Optional[str] = None
    extraction_source: str = "heuristic"
    decision_reason: Optional[str] = None


@dataclass
class DurativeMemory:
    memory_id: str
    kind: str
    slice_start: str
    slice_end: str
    cluster_id: int
    summary: str
    entity_names: List[str]
    source_event_ids: List[str]


@dataclass
class QueryTimeConstraint:
    start: Optional[datetime]
    end: Optional[datetime]
    intent: str
    expression: str

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "intent": self.intent,
            "expression": self.expression,
        }


@dataclass
class MemoryCandidate:
    memory_id: str
    kind: str
    text: str
    timestamp: Optional[str]
    source_event_ids: List[str]
    semantic_score: float = 0.0
    temporal_match: int = 0
    tkg_match: int = 0


@dataclass
class TSMIndex:
    events: List[object]
    events_by_id: Dict[str, object]
    entity_nodes: Dict[str, EntityNode]
    temporal_facts: List[TemporalFact]
    durative_memories: List[DurativeMemory]
    fact_event_index: Dict[str, List[str]]
    construction_mode: str
    construction_notes: List[str] = field(default_factory=list)


@dataclass
class ExtractedFact:
    subject: str
    relation: str
    object_text: str
    valid_time: str
    entities: List[str]
    source: str


@dataclass
class ConstructionDecision:
    operation: str
    invalidated_fact_ids: List[str]
    reason: str


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str, limit: int = 120) -> str:
    text = normalize_space(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def contains_any(text: str, markers: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def term_features(text: str) -> Counter[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9_+-]{2,}", lowered)
    cjk_sequences = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    terms: List[str] = [token for token in latin if token not in STOP_TERMS]
    for sequence in cjk_sequences:
        if sequence not in STOP_TERMS:
            terms.append(sequence)
        terms.extend(sequence[i : i + 2] for i in range(max(0, len(sequence) - 1)))
    return Counter(token for token in terms if token and token not in STOP_TERMS)


def cosine_counter(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def semantic_time_role(event: object) -> str:
    event_type = str(getattr(event, "event_type", ""))
    if event_type in {"plan", "deadline"} and getattr(event, "planned_for", None):
        return "planned_for"
    if getattr(event, "deadline_at", None):
        return "deadline_at"
    for role in EVENT_SEMANTIC_TIME_ROLES:
        if getattr(event, role, None):
            return role
    return "updated_at"


def semantic_time_value(event: object) -> str:
    role = semantic_time_role(event)
    return str(getattr(event, role, None) or getattr(event, "updated_at", ""))


def month_start(value: str) -> str:
    time = parse_time(value)
    return f"{time.year:04d}-{time.month:02d}-01T00:00:00"


def next_month_start(value: str) -> str:
    time = parse_time(value)
    year = time.year + (1 if time.month == 12 else 0)
    month = 1 if time.month == 12 else time.month + 1
    return f"{year:04d}-{month:02d}-01T00:00:00"


def relation_for_event(event: object) -> str:
    return RELATION_BY_EVENT_TYPE.get(str(getattr(event, "event_type", "")), "mentions_fact")


def extract_entities(event: object) -> List[str]:
    content = str(getattr(event, "content", ""))
    candidates: List[str] = [str(getattr(event, "scope_id", "")), str(getattr(event, "event_type", ""))]
    candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}", content))
    candidates.extend(re.findall(r"[A-Z]{2,}[0-9]*|[A-Za-z]+-[A-Za-z0-9-]+|[A-Za-z]+[0-9]+", content))
    for clause in re.split(r"[，。；;:：、（）()“”\"/]+", content):
        clause = normalize_space(clause)
        if 2 <= len(clause) <= 28 and clause not in STOP_TERMS:
            candidates.append(clause)

    seen: Set[str] = set()
    entities: List[str] = []
    for raw in candidates:
        name = normalize_space(str(raw)).strip("_- ")
        if not name or name.lower() in STOP_TERMS:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(name)
        if len(entities) >= 10:
            break
    return entities


def event_payload(event: object) -> Dict[str, object]:
    return {
        "event_id": str(getattr(event, "event_id")),
        "scope_id": str(getattr(event, "scope_id", "")),
        "event_type": str(getattr(event, "event_type", "")),
        "content": str(getattr(event, "content", "")),
        "occurred_at": getattr(event, "occurred_at", None),
        "mentioned_at": getattr(event, "mentioned_at", None),
        "updated_at": getattr(event, "updated_at", None),
        "planned_for": getattr(event, "planned_for", None),
        "deadline_at": getattr(event, "deadline_at", None),
    }


def tsm_extraction_system_prompt() -> str:
    return (
        "You are the Memory Construction stage of Temporal Semantic Memory. "
        "Extract entities and temporally grounded relation facts from one chat turn, using the preceding turns only as context. "
        "Return JSON only with schema: {"
        "\"entities\": [{\"name\": \"canonical entity\", \"summary\": \"brief salient attributes\"}], "
        "\"facts\": [{\"subject\": \"entity or scope\", \"relation\": \"snake_case relation\", "
        "\"object\": \"faithful fact text\", \"valid_time\": \"YYYY-MM-DDTHH:MM:SS\", "
        "\"time_source\": \"occurred_at|planned_for|deadline_at|mentioned_at|updated_at|text\"}]"
        "}. "
        "Do not use benchmark gold labels. Do not infer final answers. "
        "If the turn states a correction, cancellation, replacement, plan, deadline, decision, progress, or issue, "
        "extract that statement as a fact instead of pre-deciding which older fact is current."
    )


def tsm_extraction_user_prompt(event: object, context_events: Sequence[object]) -> str:
    payload = {
        "task": "Extract TSM entities and temporal facts from current_turn.",
        "preceding_context_window": [event_payload(item) for item in context_events[-CONTEXT_TURNS:]],
        "current_turn": event_payload(event),
        "time_role_guidance": (
            "Prefer planned_for/deadline_at for plans and deadlines, occurred_at for actual events, "
            "and updated_at/mentioned_at only when the fact has no stronger semantic time."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def tsm_update_system_prompt() -> str:
    return (
        "You are the Hierarchical Memory Update stage of Temporal Semantic Memory. "
        "Given one newly extracted temporal fact and candidate existing TKG edges, choose exactly one operation: "
        "DUPLICATE, ADD, INVALIDATE, or UPDATE. "
        "DUPLICATE means the new fact repeats an existing fact. ADD means it is new independent knowledge. "
        "INVALIDATE means the new fact says an older fact should no longer hold. "
        "UPDATE means the new fact replaces or revises older fact(s) with a newer value. "
        "Return JSON only with schema: {\"operation\": \"DUPLICATE|ADD|INVALIDATE|UPDATE\", "
        "\"invalidated_fact_ids\": [\"fact_id\"], \"reason\": \"brief reason\"}. "
        "Base the decision on semantic content and temporal consistency, not on event_type names alone. "
        "Only list fact IDs provided in candidate_existing_facts."
    )


def tsm_update_user_prompt(new_fact: TemporalFact, existing_facts: Sequence[TemporalFact]) -> str:
    payload = {
        "new_fact": fact_view(new_fact),
        "candidate_existing_facts": [fact_view(fact) for fact in existing_facts],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def tsm_summary_system_prompt() -> str:
    return (
        "You are the sleep-time summary consolidation stage of Temporal Semantic Memory. "
        "Return JSON only with schema: {\"summary\": \"concise temporal summary\"}. "
        "For topic memory, summarize the coherent theme in the slice. "
        "For persona memory, summarize stable or evolving user/project state patterns in the slice. "
        "Do not add facts not supported by the provided entities and turns."
    )


def tsm_summary_user_prompt(
    kind: str,
    slice_start: str,
    entity_names: Sequence[str],
    snippets: Sequence[str],
) -> str:
    payload = {
        "kind": kind,
        "slice_start": slice_start,
        "entity_names": list(entity_names),
        "supporting_turn_snippets": list(snippets),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def as_list_of_dicts(value: object) -> List[Dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def clean_entity_name(value: object) -> Optional[str]:
    name = normalize_space(str(value)).strip("_- ")
    if not name or name.lower() in STOP_TERMS:
        return None
    return name[:80]


def coerce_valid_time(value: object, event: object) -> str:
    candidate = normalize_space(str(value)) if value is not None else ""
    if candidate:
        try:
            return parse_time(candidate).isoformat()
        except Exception:
            pass
    return semantic_time_value(event)


def parsed_llm_entities(raw: Dict[str, object], event: object) -> Tuple[List[str], Dict[str, str]]:
    names: List[str] = []
    summaries: Dict[str, str] = {}
    for item in as_list_of_dicts(raw.get("entities")):
        name = clean_entity_name(item.get("name"))
        if not name:
            continue
        names.append(name)
        summary = compact(str(item.get("summary", "")), 180)
        if summary:
            summaries[name] = summary
    scope_name = clean_entity_name(getattr(event, "scope_id", ""))
    if scope_name:
        names.append(scope_name)
    return unique_ordered(names)[:12], summaries


def extracted_facts_from_llm(raw: Dict[str, object], event: object) -> Tuple[List[ExtractedFact], Dict[str, str]]:
    entities, summaries = parsed_llm_entities(raw, event)
    facts: List[ExtractedFact] = []
    for item in as_list_of_dicts(raw.get("facts")):
        object_text = compact(str(item.get("object") or item.get("object_text") or ""), 180)
        if not object_text:
            continue
        subject = clean_entity_name(item.get("subject")) or str(getattr(event, "scope_id", ""))
        relation = normalize_space(str(item.get("relation") or "mentions_fact")).lower()
        relation = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "_", relation).strip("_") or "mentions_fact"
        valid_time = coerce_valid_time(item.get("valid_time"), event)
        fact_entities = unique_ordered([subject, *entities])[:12]
        facts.append(
            ExtractedFact(
                subject=subject,
                relation=relation,
                object_text=object_text,
                valid_time=valid_time,
                entities=fact_entities,
                source="llm",
            )
        )
    return facts, summaries


def heuristic_extracted_facts(event: object) -> Tuple[List[ExtractedFact], Dict[str, str]]:
    entities = extract_entities(event)
    fact = ExtractedFact(
        subject=str(getattr(event, "scope_id", "")),
        relation=relation_for_event(event),
        object_text=compact(str(getattr(event, "content", "")), 180),
        valid_time=semantic_time_value(event),
        entities=entities,
        source="heuristic",
    )
    return [fact], {}


def llm_extract_facts(
    construction_llm: LLMJSONFn,
    event: object,
    context_events: Sequence[object],
) -> Tuple[List[ExtractedFact], Dict[str, str], List[str]]:
    raw = construction_llm(tsm_extraction_system_prompt(), tsm_extraction_user_prompt(event, context_events))
    facts, summaries = extracted_facts_from_llm(raw, event)
    if facts:
        return facts, summaries, []
    fallback_facts, fallback_summaries = heuristic_extracted_facts(event)
    note = f"{getattr(event, 'event_id')}: LLM extraction returned no facts; used raw-turn fallback."
    return fallback_facts, {**fallback_summaries, **summaries}, [note]


def select_update_candidates(new_fact: TemporalFact, active_facts: Sequence[TemporalFact]) -> List[TemporalFact]:
    scored: List[Tuple[float, TemporalFact]] = []
    new_terms = term_features(f"{new_fact.subject} {new_fact.relation} {new_fact.object_text}")
    for old in active_facts:
        if old.invalid_time is not None:
            continue
        old_terms = term_features(f"{old.subject} {old.relation} {old.object_text}")
        score = cosine_counter(new_terms, old_terms)
        if new_fact.subject == old.subject:
            score += 0.4
        if new_fact.relation == old.relation:
            score += 0.2
        if score > 0:
            scored.append((score, old))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [fact for _, fact in scored[:MAX_UPDATE_CANDIDATES]]


def parse_construction_decision(raw: Dict[str, object], existing_facts: Sequence[TemporalFact]) -> ConstructionDecision:
    valid_operations = {"DUPLICATE", "ADD", "INVALIDATE", "UPDATE"}
    operation = str(raw.get("operation", "ADD")).upper()
    if operation not in valid_operations:
        operation = "ADD"
    allowed_ids = {fact.fact_id for fact in existing_facts}
    invalidated = [
        str(fact_id)
        for fact_id in raw.get("invalidated_fact_ids", [])
        if str(fact_id) in allowed_ids
    ] if isinstance(raw.get("invalidated_fact_ids"), list) else []
    if operation in {"INVALIDATE", "UPDATE"} and not invalidated:
        operation = "ADD"
    reason = compact(str(raw.get("reason", "")), 240)
    return ConstructionDecision(operation=operation, invalidated_fact_ids=unique_ordered(invalidated), reason=reason)


def llm_decide_update(
    construction_llm: LLMJSONFn,
    new_fact: TemporalFact,
    active_facts: Sequence[TemporalFact],
) -> ConstructionDecision:
    candidates = select_update_candidates(new_fact, active_facts)
    if not candidates:
        return ConstructionDecision("ADD", [], "No candidate existing fact.")
    raw = construction_llm(tsm_update_system_prompt(), tsm_update_user_prompt(new_fact, candidates))
    return parse_construction_decision(raw, candidates)


def heuristic_decide_update(new_fact: TemporalFact, active_facts: Sequence[TemporalFact], event: object) -> ConstructionDecision:
    duplicate = next((old for old in active_facts if is_duplicate_fact(new_fact, old)), None)
    if duplicate:
        return ConstructionDecision("DUPLICATE", [], f"Heuristic duplicate of {duplicate.fact_id}.")
    revision_like = str(getattr(event, "event_type", "")) in {"correction", "decision", "fix", "mitigation"} or contains_any(
        str(getattr(event, "content", "")),
        HEURISTIC_REVISION_MARKERS,
    )
    related_active = [old for old in active_facts if old.invalid_time is None and is_related_fact(new_fact, old)]
    if revision_like and related_active:
        return ConstructionDecision("UPDATE", [old.fact_id for old in related_active], "Heuristic revision marker matched related active facts.")
    if revision_like:
        return ConstructionDecision("INVALIDATE", [], "Heuristic revision marker without target.")
    return ConstructionDecision("ADD", [], "Heuristic new fact.")


def is_duplicate_fact(new_fact: TemporalFact, old_fact: TemporalFact) -> bool:
    return (
        new_fact.subject == old_fact.subject
        and new_fact.relation == old_fact.relation
        and cosine_counter(term_features(new_fact.object_text), term_features(old_fact.object_text)) >= 0.92
    )


def is_related_fact(new_fact: TemporalFact, old_fact: TemporalFact) -> bool:
    if new_fact.subject != old_fact.subject:
        return False
    if new_fact.relation == old_fact.relation:
        return True
    return cosine_counter(term_features(new_fact.object_text), term_features(old_fact.object_text)) >= 0.28


def build_episodic_memory(
    events: Sequence[object],
    construction_llm: Optional[LLMJSONFn] = None,
    construction_mode: str = "llm",
) -> Tuple[Dict[str, EntityNode], List[TemporalFact], Dict[str, List[str]], List[str]]:
    entity_nodes: Dict[str, EntityNode] = {}
    temporal_facts: List[TemporalFact] = []
    active_facts: List[TemporalFact] = []
    fact_event_index: Dict[str, List[str]] = defaultdict(list)
    construction_notes: List[str] = []

    sorted_events = sorted(events, key=lambda event: parse_time(getattr(event, "updated_at", None) or semantic_time_value(event)))
    processed_events: List[object] = []
    use_llm = construction_mode == "llm" and construction_llm is not None
    for event in sorted_events:
        event_id = str(getattr(event, "event_id"))
        if use_llm:
            extracted_facts, entity_summaries, notes = llm_extract_facts(construction_llm, event, processed_events)
            construction_notes.extend(notes)
        else:
            extracted_facts, entity_summaries = heuristic_extracted_facts(event)

        if not extracted_facts:
            processed_events.append(event)
            continue

        for extracted in extracted_facts:
            entities = unique_ordered(extracted.entities)
            for entity in entities:
                node = entity_nodes.setdefault(entity, EntityNode(name=entity, summary=""))
                summary = entity_summaries.get(entity)
                if summary and summary not in node.summary:
                    node.summary = compact(" | ".join([part for part in [node.summary, summary] if part]), 260)
                if event_id not in node.event_ids:
                    node.event_ids.append(event_id)

            fact = TemporalFact(
                fact_id=f"tsm_fact_{len(temporal_facts) + 1}",
                subject=extracted.subject,
                relation=extracted.relation,
                object_text=extracted.object_text,
                valid_time=extracted.valid_time,
                invalid_time=None,
                source_event_id=event_id,
                operation="ADD",
                supporting_entities=entities,
                extraction_source=extracted.source,
            )

            if use_llm:
                decision = llm_decide_update(construction_llm, fact, active_facts)
            else:
                decision = heuristic_decide_update(fact, active_facts, event)
            fact.operation = decision.operation
            fact.decision_reason = decision.reason
            for old in active_facts:
                if old.fact_id in decision.invalidated_fact_ids and old.invalid_time is None:
                    old.invalid_time = fact.valid_time
                    old.invalidated_by = event_id

            temporal_facts.append(fact)
            if fact.operation != "DUPLICATE":
                active_facts.append(fact)
            fact_event_index[fact.fact_id].append(event_id)
        processed_events.append(event)

    for node in entity_nodes.values():
        if not node.summary:
            node.summary = build_entity_summary(node.name, node.event_ids, {str(getattr(event, "event_id")): event for event in events})
    return entity_nodes, temporal_facts, dict(fact_event_index), construction_notes


def build_entity_summary(entity_name: str, event_ids: Sequence[str], events_by_id: Dict[str, object]) -> str:
    snippets = [compact(str(getattr(events_by_id[event_id], "content", "")), 70) for event_id in event_ids[:3] if event_id in events_by_id]
    return f"{entity_name}: " + " | ".join(snippets)


def cluster_entity_summaries(entity_summaries: Sequence[str]) -> List[int]:
    if not entity_summaries:
        return []
    if len(entity_summaries) <= 2 or TfidfVectorizer is None or GaussianMixture is None or np is None:
        return list(range(len(entity_summaries)))
    n_components = min(4, max(1, round(math.sqrt(len(entity_summaries)))))
    if n_components >= len(entity_summaries):
        return list(range(len(entity_summaries)))
    try:
        vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
        matrix = vectorizer.fit_transform(entity_summaries).toarray()
        model = GaussianMixture(n_components=n_components, covariance_type="diag", random_state=13)
        return [int(label) for label in model.fit_predict(matrix)]
    except Exception:
        return [idx % n_components for idx in range(len(entity_summaries))]


def summarize_cluster(kind: str, slice_start: str, entity_names: Sequence[str], event_ids: Sequence[str], events_by_id: Dict[str, object]) -> str:
    snippets = [compact(str(getattr(events_by_id[event_id], "content", "")), 90) for event_id in event_ids[:5] if event_id in events_by_id]
    entity_text = ", ".join(entity_names[:8])
    if kind == "topic":
        return f"{slice_start[:7]} topic over {entity_text}: " + " / ".join(snippets)
    return f"{slice_start[:7]} persona/state pattern from {entity_text}: " + " / ".join(snippets)


def llm_summarize_cluster(
    construction_llm: LLMJSONFn,
    kind: str,
    slice_start: str,
    entity_names: Sequence[str],
    event_ids: Sequence[str],
    events_by_id: Dict[str, object],
) -> str:
    snippets = [compact(str(getattr(events_by_id[event_id], "content", "")), 120) for event_id in event_ids[:10] if event_id in events_by_id]
    raw = construction_llm(tsm_summary_system_prompt(), tsm_summary_user_prompt(kind, slice_start, entity_names[:12], snippets))
    summary = compact(str(raw.get("summary", "")), 260)
    if summary:
        return summary
    return summarize_cluster(kind, slice_start, entity_names, event_ids, events_by_id)


def build_durative_memory(
    index_events: Sequence[object],
    entity_nodes: Dict[str, EntityNode],
    temporal_facts: Sequence[TemporalFact],
    construction_llm: Optional[LLMJSONFn] = None,
    construction_mode: str = "llm",
) -> List[DurativeMemory]:
    events_by_id = {str(getattr(event, "event_id")): event for event in index_events}
    entities_by_slice: Dict[str, Set[str]] = defaultdict(set)
    for fact in temporal_facts:
        slice_start = month_start(fact.valid_time)
        for entity in fact.supporting_entities:
            entities_by_slice[slice_start].add(entity)

    memories: List[DurativeMemory] = []
    for slice_start in sorted(entities_by_slice):
        entity_names = sorted(entities_by_slice[slice_start])
        summaries = [entity_nodes[name].summary for name in entity_names if name in entity_nodes]
        labels = cluster_entity_summaries(summaries)
        clusters: Dict[int, List[str]] = defaultdict(list)
        for entity_name, label in zip(entity_names, labels):
            clusters[label].append(entity_name)

        for cluster_id, names in sorted(clusters.items()):
            event_ids: List[str] = []
            for name in names:
                event_ids.extend(entity_nodes[name].event_ids)
            event_ids = unique_ordered(event_ids)
            slice_end = next_month_start(slice_start)
            if construction_mode == "llm" and construction_llm is not None:
                topic_summary = llm_summarize_cluster(construction_llm, "topic", slice_start, names, event_ids, events_by_id)
                persona_summary = llm_summarize_cluster(construction_llm, "persona", slice_start, names, event_ids, events_by_id)
            else:
                topic_summary = summarize_cluster("topic", slice_start, names, event_ids, events_by_id)
                persona_summary = summarize_cluster("persona", slice_start, names, event_ids, events_by_id)
            memories.append(
                DurativeMemory(
                    memory_id=f"tsm_topic_{slice_start[:7]}_{cluster_id}",
                    kind="topic",
                    slice_start=slice_start,
                    slice_end=slice_end,
                    cluster_id=cluster_id,
                    summary=topic_summary,
                    entity_names=list(names),
                    source_event_ids=event_ids,
                )
            )
            memories.append(
                DurativeMemory(
                    memory_id=f"tsm_persona_{slice_start[:7]}_{cluster_id}",
                    kind="persona",
                    slice_start=slice_start,
                    slice_end=slice_end,
                    cluster_id=cluster_id,
                    summary=persona_summary,
                    entity_names=list(names),
                    source_event_ids=event_ids,
                )
            )
    return memories


def unique_ordered(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_tsm_index(
    events: Sequence[object],
    construction_llm: Optional[LLMJSONFn] = None,
    construction_mode: str = "llm",
) -> TSMIndex:
    event_list = list(events)
    effective_mode = "llm" if construction_mode == "llm" and construction_llm is not None else "heuristic"
    entity_nodes, temporal_facts, fact_event_index, construction_notes = build_episodic_memory(
        event_list,
        construction_llm=construction_llm,
        construction_mode=effective_mode,
    )
    return TSMIndex(
        events=event_list,
        events_by_id={str(getattr(event, "event_id")): event for event in event_list},
        entity_nodes=entity_nodes,
        temporal_facts=temporal_facts,
        durative_memories=build_durative_memory(
            event_list,
            entity_nodes,
            temporal_facts,
            construction_llm=construction_llm,
            construction_mode=effective_mode,
        ),
        fact_event_index=fact_event_index,
        construction_mode=effective_mode,
        construction_notes=construction_notes,
    )


def latest_time(events: Sequence[object]) -> datetime:
    values = [parse_time(getattr(event, "updated_at", None) or semantic_time_value(event)) for event in events]
    return max(values) if values else datetime.now()


def spacy_temporal_candidates(query: str) -> List[str]:
    if spacy is None:
        return []
    try:
        nlp = spacy.blank("xx")
        doc = nlp(query)
    except Exception:
        return []
    candidates: List[str] = []
    for token in doc:
        text = token.text.strip()
        if re.search(r"\d{4}[-/年]\d{1,2}|\d{1,2}月|\d{1,2}日|today|yesterday|tomorrow|week|month|year", text, re.I):
            candidates.append(text)
    return candidates


def dateparser_constraint(query: str, reference: datetime) -> Optional[QueryTimeConstraint]:
    if search_dates is None:
        return None
    languages = ["zh", "en"]
    settings = {
        "RELATIVE_BASE": reference,
        "PREFER_DATES_FROM": "past",
        "RETURN_AS_TIMEZONE_AWARE": False,
    }
    search_text = " ".join(unique_ordered([query, *spacy_temporal_candidates(query)]))
    try:
        parsed = search_dates(search_text, languages=languages, settings=settings)
    except Exception:
        return None
    if not parsed:
        return None
    expression, time = parsed[0]
    if re.search(r"\d{1,2}月|month|月份", expression, re.I) and not re.search(r"\d{1,2}[日号]|\d{4}[-/]\d{1,2}[-/]\d{1,2}", expression):
        start = datetime(time.year, time.month, 1)
        end = parse_time(next_month_start(start.isoformat()))
        return QueryTimeConstraint(start, end, "spacy_dateparser_month", expression)
    start = datetime(time.year, time.month, time.day)
    end = datetime(time.year, time.month, time.day, 23, 59, 59)
    return QueryTimeConstraint(start, end, "spacy_dateparser_day", expression)


def parse_query_time_constraint(query: str, events: Sequence[object]) -> QueryTimeConstraint:
    reference = latest_time(events)
    query_text = query.strip()

    iso_match = re.search(r"(20\d{2})[-/年](\d{1,2})(?:[-/月](\d{1,2})日?)?", query_text)
    if iso_match:
        year = int(iso_match.group(1))
        month = int(iso_match.group(2))
        day = int(iso_match.group(3) or 1)
        start = datetime(year, month, day)
        if iso_match.group(3):
            end = datetime(year, month, day, 23, 59, 59)
            expression = iso_match.group(0)
        else:
            end = parse_time(next_month_start(start.isoformat()))
            expression = f"{year:04d}-{month:02d}"
        return QueryTimeConstraint(start, end, "explicit", expression)

    month_match = re.search(r"(\d{1,2})月", query_text)
    if month_match:
        month = int(month_match.group(1))
        year = reference.year
        start = datetime(year, month, 1)
        end = parse_time(next_month_start(start.isoformat()))
        return QueryTimeConstraint(start, end, "explicit_month", month_match.group(0))

    if contains_any(query_text, FUTURE_QUERY_MARKERS):
        return QueryTimeConstraint(reference, None, "future", "future_or_next_step")
    if contains_any(query_text, CURRENT_QUERY_MARKERS):
        return QueryTimeConstraint(None, reference, "current", "current_or_recent")
    if contains_any(query_text, PAST_QUERY_MARKERS):
        return QueryTimeConstraint(None, reference, "past", "past_or_previous")

    parsed_constraint = dateparser_constraint(query_text, reference)
    if parsed_constraint:
        return parsed_constraint
    return QueryTimeConstraint(None, None, "unbounded", "no_explicit_time")


def interval_overlaps(start: str, end: Optional[str], constraint: QueryTimeConstraint) -> bool:
    start_time = parse_time(start)
    end_time = parse_time(end) if end else None
    if constraint.start and end_time and end_time < constraint.start:
        return False
    if constraint.end and start_time > constraint.end:
        return False
    return True


def durative_overlaps(memory: DurativeMemory, constraint: QueryTimeConstraint) -> bool:
    if constraint.intent == "unbounded":
        return True
    return interval_overlaps(memory.slice_start, memory.slice_end, constraint)


def fact_temporal_match(fact: TemporalFact, constraint: QueryTimeConstraint) -> bool:
    if constraint.intent == "unbounded":
        return True
    if constraint.intent == "current" and constraint.end:
        valid = parse_time(fact.valid_time) <= constraint.end
        not_invalid = fact.invalid_time is None or parse_time(fact.invalid_time) > constraint.end
        return valid and not_invalid
    return interval_overlaps(fact.valid_time, fact.invalid_time, constraint)


def build_memory_pool(index: TSMIndex) -> List[MemoryCandidate]:
    pool: List[MemoryCandidate] = []
    for event in index.events:
        event_id = str(getattr(event, "event_id"))
        pool.append(
            MemoryCandidate(
                memory_id=event_id,
                kind="raw",
                text=f"{getattr(event, 'scope_id', '')} {getattr(event, 'event_type', '')} {getattr(event, 'content', '')}",
                timestamp=semantic_time_value(event),
                source_event_ids=[event_id],
            )
        )
    for memory in index.durative_memories:
        pool.append(
            MemoryCandidate(
                memory_id=memory.memory_id,
                kind=memory.kind,
                text=memory.summary,
                timestamp=memory.slice_start,
                source_event_ids=list(memory.source_event_ids),
            )
        )
    return pool


def dense_retrieve(pool: Sequence[MemoryCandidate], query: str, top_k: int = TOP_K) -> List[MemoryCandidate]:
    query_terms = term_features(query)
    scored: List[MemoryCandidate] = []
    for candidate in pool:
        clone = MemoryCandidate(
            memory_id=candidate.memory_id,
            kind=candidate.kind,
            text=candidate.text,
            timestamp=candidate.timestamp,
            source_event_ids=list(candidate.source_event_ids),
            semantic_score=cosine_counter(query_terms, term_features(candidate.text)),
        )
        scored.append(clone)
    scored.sort(key=lambda item: item.semantic_score, reverse=True)
    return scored[:top_k]


def temporal_fact_events(index: TSMIndex, constraint: QueryTimeConstraint) -> Tuple[Set[str], List[TemporalFact]]:
    matched_facts = [fact for fact in index.temporal_facts if fact_temporal_match(fact, constraint)]
    event_ids = {event_id for fact in matched_facts for event_id in index.fact_event_index.get(fact.fact_id, [])}
    return event_ids, matched_facts


def rerank_candidates(
    candidates: Sequence[MemoryCandidate],
    index: TSMIndex,
    constraint: QueryTimeConstraint,
    tkg_event_ids: Set[str],
) -> List[MemoryCandidate]:
    memory_by_id = {memory.memory_id: memory for memory in index.durative_memories}
    reranked: List[MemoryCandidate] = []
    for candidate in candidates:
        if candidate.kind in {"topic", "persona"}:
            memory = memory_by_id.get(candidate.memory_id)
            if memory is None or not durative_overlaps(memory, constraint):
                continue
            candidate.temporal_match = 1
        else:
            candidate.temporal_match = 1 if (constraint.intent == "unbounded" or any(event_id in tkg_event_ids for event_id in candidate.source_event_ids)) else 0
        candidate.tkg_match = 1 if any(event_id in tkg_event_ids for event_id in candidate.source_event_ids) else 0
        reranked.append(candidate)
    reranked.sort(key=lambda item: (item.temporal_match, item.tkg_match, item.semantic_score), reverse=True)
    return reranked


def relevant_durative_memories(event_id: str, candidates: Sequence[MemoryCandidate], index: TSMIndex, limit: int = 3) -> List[DurativeMemory]:
    memory_by_id = {memory.memory_id: memory for memory in index.durative_memories}
    result: List[DurativeMemory] = []
    for candidate in candidates:
        if candidate.kind not in {"topic", "persona"}:
            continue
        memory = memory_by_id.get(candidate.memory_id)
        if memory and event_id in memory.source_event_ids:
            result.append(memory)
        if len(result) >= limit:
            break
    return result


def facts_for_event(event_id: str, facts: Sequence[TemporalFact]) -> List[TemporalFact]:
    return [fact for fact in facts if fact.source_event_id == event_id]


def fact_view(fact: TemporalFact) -> Dict[str, object]:
    return {
        "fact_id": fact.fact_id,
        "subject": fact.subject,
        "relation": fact.relation,
        "object": fact.object_text,
        "valid_time": fact.valid_time,
        "invalid_time": fact.invalid_time,
        "operation": fact.operation,
        "invalidated_by": fact.invalidated_by,
        "extraction_source": fact.extraction_source,
        "decision_reason": fact.decision_reason,
    }


def durative_view(memory: DurativeMemory) -> Dict[str, object]:
    return {
        "memory_id": memory.memory_id,
        "kind": memory.kind,
        "slice_start": memory.slice_start,
        "slice_end": memory.slice_end,
        "summary": compact(memory.summary, 220),
        "source_event_ids": memory.source_event_ids[:8],
    }


def collect_visible_events(
    reranked: Sequence[MemoryCandidate],
    index: TSMIndex,
    temporal_facts: Sequence[TemporalFact],
    tkg_event_ids: Set[str],
    constraint: QueryTimeConstraint,
) -> List[Dict[str, object]]:
    selected_ids: List[str] = []
    for candidate in reranked:
        selected_ids.extend(candidate.source_event_ids)
        if len(unique_ordered(selected_ids)) >= MAX_VISIBLE_EVENTS:
            break
    selected_ids.extend(sorted(tkg_event_ids))
    selected_ids = unique_ordered(selected_ids)[:MAX_VISIBLE_EVENTS]

    rank_by_event: Dict[str, int] = {}
    reason_by_event: Dict[str, List[str]] = defaultdict(list)
    for rank, candidate in enumerate(reranked, start=1):
        for event_id in candidate.source_event_ids:
            rank_by_event.setdefault(event_id, rank)
            reason_by_event[event_id].append(candidate.kind)

    visible: List[Dict[str, object]] = []
    for event_id in selected_ids:
        event = index.events_by_id.get(event_id)
        if event is None:
            continue
        view = event_view(event, include_relations=False, include_state_relevant=False)
        view["tsm_rank"] = rank_by_event.get(event_id, len(reranked) + 1)
        view["semantic_time_role"] = semantic_time_role(event)
        view["semantic_time"] = semantic_time_value(event)
        view["query_time_constraint"] = constraint.as_dict()
        view["tsm_retrieval_sources"] = sorted(set(reason_by_event.get(event_id, [])))
        view["tkg_temporal_hit"] = event_id in tkg_event_ids
        view["temporal_facts"] = [fact_view(fact) for fact in facts_for_event(event_id, temporal_facts)]
        view["durative_memories"] = [durative_view(memory) for memory in relevant_durative_memories(event_id, reranked, index)]
        visible.append(view)
    visible.sort(key=lambda item: (int(item.get("tsm_rank", 999)), str(item.get("semantic_time", ""))))
    return visible


def build_instruction(
    constraint: QueryTimeConstraint,
    reranked: Sequence[MemoryCandidate],
    matched_facts: Sequence[TemporalFact],
    index: TSMIndex,
    has_output_slots: bool,
) -> str:
    top_memories = []
    memory_by_id = {memory.memory_id: memory for memory in index.durative_memories}
    for candidate in reranked[:8]:
        item = {
            "memory_id": candidate.memory_id,
            "kind": candidate.kind,
            "semantic_score": round(candidate.semantic_score, 3),
            "temporal_match": candidate.temporal_match,
            "tkg_match": candidate.tkg_match,
            "source_event_ids": candidate.source_event_ids[:8],
        }
        if candidate.kind in {"topic", "persona"} and candidate.memory_id in memory_by_id:
            item["summary"] = compact(memory_by_id[candidate.memory_id].summary, 220)
        else:
            item["summary"] = compact(candidate.text, 220)
        top_memories.append(item)

    matched_fact_views = [fact_view(fact) for fact in matched_facts[:16]]
    construction_audit = {
        "construction_mode": index.construction_mode,
        "notes": index.construction_notes[:8],
    }
    output_guidance = (
        "根据 TSM 的 semantic timeline 和 durative memory，回答每个 output_slot；"
        if has_output_slots
        else (
            "这是 public End-to-End setting：你看不到 hidden output_slots，"
            "必须根据 query、operation、TSM 的 semantic timeline 和 durative memory 自由识别相关状态 facets；"
            "按外层 runner 要求输出 facets、evidence_events 和 answer，不要请求或假设 output_slots；"
        )
    )
    return (
        "按论文完整模拟 TSM / Temporal Semantic Memory，而不是普通 prompt baseline。"
        "本实现遵循论文三段式流程："
        "1. Memory Construction：从目标 scoped history 构建 Temporal Knowledge Graph episodic memory，"
        "每条 temporal fact 带 valid_time/invalid_time，并使用 DUPLICATE、ADD、INVALIDATE、UPDATE 操作维护一致性。"
        "默认口径下，entity/relation extraction、TKG update operation 和 topic/persona LLMsum 由 construction LLM 执行；"
        "只有 dry-run 或显式 fallback 才会使用 heuristic construction；"
        "2. Durative Memory Construction：按月切片，使用 GMM-style clustering 聚合 entity summaries，"
        "构造 topic/persona durative memories；"
        "3. Memory Utilization：先 ParseTime 得到 query semantic time constraint，"
        "再对 raw/topic/persona memory 做 Top-K dense retrieval，过滤不满足时间约束的 topic/persona，"
        "并用 TKG temporal facts 作 primary rerank signal，semantic similarity 作 secondary key。"
        "construction_audit="
        f"{json.dumps(construction_audit, ensure_ascii=False)}。"
        "当前查询的 semantic_time_constraint="
        f"{json.dumps(constraint.as_dict(), ensure_ascii=False)}。"
        "reranked_memory="
        f"{json.dumps(top_memories, ensure_ascii=False)}。"
        "temporally_valid_tkg_facts="
        f"{json.dumps(matched_fact_views, ensure_ascii=False)}。"
        "可见事件是 TSM utilization 输出的 raw chat turns；durative_memories 和 temporal_facts 是上下文，"
        "不能把 synthetic memory_id 当作 support_event。"
        "你必须只用可见 raw event_id 填写 support_event、support_events 和 evidence_events。"
        f"{output_guidance}"
        "如果 temporal_facts 显示旧 fact 已有 invalid_time 或 invalidated_by，旧 fact 只能作为被替代背景，不能当作当前有效状态。"
    )


def build_tsm_prompt_spec(
    events: Sequence[object],
    case: object,
    construction_llm: Optional[LLMJSONFn] = None,
    construction_mode: str = "llm",
) -> BaselinePromptSpec:
    scope_id = getattr(case, "scope_id", None)
    scoped_events = [event for event in events if scope_id and getattr(event, "scope_id", None) == scope_id]
    index = build_tsm_index(scoped_events or events, construction_llm=construction_llm, construction_mode=construction_mode)
    return build_tsm_prompt_spec_from_index(index, case)


def build_tsm_prompt_spec_from_index(index: TSMIndex, case: object) -> BaselinePromptSpec:
    constraint = parse_query_time_constraint(str(getattr(case, "query", "")), index.events)
    pool = build_memory_pool(index)
    dense_candidates = dense_retrieve(pool, str(getattr(case, "query", "")), TOP_K)
    tkg_event_ids, matched_facts = temporal_fact_events(index, constraint)
    reranked = rerank_candidates(dense_candidates, index, constraint, tkg_event_ids)
    visible = collect_visible_events(reranked, index, index.temporal_facts, tkg_event_ids, constraint)
    instruction = build_instruction(
        constraint,
        reranked,
        matched_facts,
        index,
        has_output_slots=bool(getattr(case, "output_slots", None)),
    )
    return BaselinePromptSpec("tsm", visible, instruction)

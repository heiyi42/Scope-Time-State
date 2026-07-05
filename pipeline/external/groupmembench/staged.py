from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

from Experiment.run.common.llm_client import LLMClient
from pipeline.external.groupmembench.adapters.base import TaskAdapter
from pipeline.external.groupmembench.graph_schema import EDGE_TYPES, build_event_scope_graph, time_id
from pipeline.external.groupmembench.loader import GroupMessage, GroupQuestion
from pipeline.external.groupmembench.prompts import (
    claim_extraction_system_prompt,
    claim_extraction_user_prompt,
    composer_system_prompt,
    composer_user_prompt,
    direct_baseline_system_prompt,
    direct_baseline_user_prompt,
    state_selection_system_prompt,
    state_selection_user_prompt,
    support_verification_system_prompt,
    support_verification_user_prompt,
    validity_system_prompt,
    validity_user_prompt,
)
from pipeline.external.groupmembench.retrieval import bm25_scores, document_text, question_target_terms
from pipeline.external.groupmembench.routing import ScopeRoute


ALLOWED_RELATION_TYPES = {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}
ISO_DATE_RE = re.compile(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)")
MONTH_DATE_RE = re.compile(
    r"\b("
    r"january|february|march|april|may|june|july|august|september|october|november|december"
    r")\s+(\d{1,2}),\s*(20\d{2})\b",
    re.I,
)
MONTH_DAY_RE = re.compile(
    r"\b("
    r"january|february|march|april|may|june|july|august|september|october|november|december"
    r")\s+(\d{1,2})(?:,\s*(20\d{2}))?\b",
    re.I,
)
WEEKDAY_RE = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
RELATIVE_DAY_RE = re.compile(r"\b(today|tomorrow|tonight|eod|end of day)\b", re.I)
DAY_AFTER_TOMORROW_RE = re.compile(r"\bday after tomorrow\b", re.I)
WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
MONTHS = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}
CLAIM_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
CLAIM_SUPPORT_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "into",
    "from",
    "now",
    "are",
    "what",
    "date",
    "current",
    "before",
    "after",
    "against",
    "same",
    "they",
    "can",
    "need",
    "needs",
    "must",
    "should",
    "would",
    "could",
    "will",
    "have",
    "has",
    "had",
    "been",
    "being",
}
IMPORTANT_SHORT_SUPPORT_TOKENS = {
    "ai",
    "aml",
    "api",
    "eod",
    "ehr",
    "etl",
    "kpi",
    "qa",
    "roi",
    "sla",
    "sop",
    "ui",
    "ux",
}
KNOWLEDGE_UPDATE_ACTION_TERMS = (
    "instead",
    "widen",
    "widening",
    "expand",
    "include",
    "cover",
    "fold",
    "add",
    "pause",
    "route",
    "keep",
    "replace",
    "update",
    "change",
)
KNOWLEDGE_UPDATE_REVISION_MARKERS = {
    "change:": 8.0,
    "new plan": 8.0,
    "new path": 8.0,
    "proposal:": 6.0,
    "proposed change": 7.0,
    "revisit": 5.0,
    "revise": 5.0,
    "no longer works": 7.0,
    "old \"": 4.0,
    "old “": 4.0,
    "instead of": 5.0,
}
KNOWLEDGE_UPDATE_BOUNDARY_TERMS = (
    "scope",
    "approach",
    "approval",
    "boundary",
    "decision gate",
    "fallback",
    "exception",
    "edge case",
    "controlled change",
    "as-is",
    "provisional",
    "sign-off",
    "signoff",
    "delay",
    "tradeoff",
    "plus",
)
KNOWLEDGE_UPDATE_TARGET_TERMS = (
    "scope",
    "approval",
    "approach",
    "decision",
    "status",
    "owner",
    "responsibility",
    "deadline",
)
GENERIC_UPDATE_PATTERNS = (
    "lock one decision",
    "close this phase out",
    "we're at",
    "we’re at",
    "complete",
    "please weigh in",
)
TRADEOFF_QUALIFIER_WEIGHTS = {
    "delay": 5.0,
    "tradeoff": 4.0,
    "cost": 3.0,
    "risk": 2.0,
    "rework": 2.0,
    "fallout": 2.0,
    "downstream impact": 2.0,
    "support pain": 2.0,
    "avoid": 1.0,
    "not optional": 1.0,
}


def is_emptyish(value: object) -> bool:
    return value is None or value == ""


def normalize_id_list(value: object) -> List[str]:
    if value is None or value == "" or value == "null":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and item != "" and item != "null"]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None and item != "" and item != "null"]
    return [str(value)]


def raw_state_packet(raw: Dict[str, object]) -> Dict[str, object]:
    packet = raw.get("state_packet")
    return deepcopy(packet) if isinstance(packet, dict) else deepcopy(raw)


def message_times_by_id(messages: Sequence[GroupMessage]) -> Dict[str, str]:
    return {message.event_id: message.timestamp for message in messages}


def messages_by_id(messages: Sequence[GroupMessage]) -> Dict[str, GroupMessage]:
    return {message.event_id: message for message in messages}


def claim_support_tokens(text: object) -> List[str]:
    return [
        token
        for token in CLAIM_TOKEN_RE.findall(str(text or "").lower())
        if (len(token) >= 4 or token in IMPORTANT_SHORT_SUPPORT_TOKENS)
        and token not in CLAIM_SUPPORT_STOPWORDS
    ]


def claim_support_score(value: object, source_text: object) -> float:
    claim_tokens = claim_support_tokens(value)
    if not claim_tokens:
        return 1.0
    source_tokens = set(claim_support_tokens(source_text))
    if not source_tokens:
        return 0.0
    return len([token for token in claim_tokens if token in source_tokens]) / max(1, len(claim_tokens))


def knowledge_update_claim_quality(question: GroupQuestion, claim: Dict[str, object]) -> float:
    value = str(claim.get("value", "")).lower()
    facet_type = str(claim.get("facet_type", "")).lower()
    claim_type = str(claim.get("claim_type", "")).lower()
    text = " ".join(part for part in (facet_type, claim_type, value) if part)
    question_text = question.question.lower()
    question_tokens = set(claim_support_tokens(question_text))
    claim_tokens = set(claim_support_tokens(text))
    overlap = len(question_tokens & claim_tokens)
    action_hits = sum(1 for term in KNOWLEDGE_UPDATE_ACTION_TERMS if term in text)
    boundary_hits = sum(1 for term in KNOWLEDGE_UPDATE_BOUNDARY_TERMS if term in text)
    target_hits = sum(
        1
        for term in KNOWLEDGE_UPDATE_TARGET_TERMS
        if term in question_text and term in text
    )
    score = (1.25 * overlap) + (2.0 * action_hits) + (1.0 * boundary_hits) + (1.5 * target_hits)
    score += min(6.0, knowledge_update_revision_signal(value))
    score += min(4.0, len(claim_tokens) / 5.0)
    if ("scope" in question_text or "approval" in question_text) and any(
        term in text for term in ("scope", "approval", "boundary", "cover")
    ):
        score += 3.0
    if claim_type in {"decision", "update", "correction"}:
        score += 1.0
    if facet_type in {"scope", "current_approach", "status"}:
        score += 1.0
    if any(pattern in value for pattern in GENERIC_UPDATE_PATTERNS):
        score -= 8.0
    return score


def knowledge_update_revision_signal(text: object) -> float:
    lowered = str(text or "").lower()
    return sum(weight for term, weight in KNOWLEDGE_UPDATE_REVISION_MARKERS.items() if term in lowered)


def knowledge_update_target_overlap(question: GroupQuestion, text: object) -> int:
    target_terms = question_target_terms(question)
    if not target_terms:
        return 0
    return len(target_terms & set(claim_support_tokens(text)))


def sentence_chunks(text: object) -> List[str]:
    chunks = []
    for item in SENTENCE_SPLIT_RE.split(str(text or "")):
        cleaned = re.sub(r"\s+", " ", item.replace("**", "")).strip()
        if cleaned:
            chunks.append(cleaned)
    return chunks


def tradeoff_qualifier_score(sentence: str) -> float:
    lowered = sentence.lower()
    return sum(weight for term, weight in TRADEOFF_QUALIFIER_WEIGHTS.items() if term in lowered)


def enrich_knowledge_update_claims(
    question: GroupQuestion,
    claims: Sequence[Dict[str, object]],
    event_by_id: Dict[str, GroupMessage],
) -> List[Dict[str, object]]:
    enriched: List[Dict[str, object]] = []
    for claim in claims:
        item = deepcopy(claim)
        if item.get("source_enrichment"):
            enriched.append(item)
            continue
        text = " ".join(
            str(part).lower()
            for part in (item.get("facet_type", ""), item.get("claim_type", ""), item.get("value", ""))
        )
        if not any(term in text for term in KNOWLEDGE_UPDATE_ACTION_TERMS) or not any(
            term in text for term in KNOWLEDGE_UPDATE_BOUNDARY_TERMS
        ):
            enriched.append(item)
            continue
        message = event_by_id.get(str(item.get("event_id", "")))
        if not message:
            enriched.append(item)
            continue
        value = str(item.get("value", ""))
        value_lower = value.lower()
        best_qualifier: Optional[Tuple[float, str]] = None
        for sentence in sentence_chunks(message.content):
            sentence_lower = sentence.lower()
            if len(sentence) > 260:
                continue
            if sentence_lower in value_lower:
                continue
            qualifier_score = tradeoff_qualifier_score(sentence)
            if qualifier_score > 0 and (best_qualifier is None or qualifier_score > best_qualifier[0]):
                best_qualifier = (qualifier_score, sentence)
        if best_qualifier:
            item["value"] = f"{value} Tradeoff: {best_qualifier[1]}"
            item["source_enrichment"] = "knowledge_update_tradeoff_from_event"
        enriched.append(item)

    existing_pairs = {
        (str(item.get("event_id", "")), re.sub(r"\s+", " ", str(item.get("value", "")).lower()).strip())
        for item in enriched
        if isinstance(item, dict)
    }
    next_index = 1
    for message in event_by_id.values():
        message_overlap = knowledge_update_target_overlap(question, message.content)
        message_revision_signal = knowledge_update_revision_signal(message.content)
        for sentence in sentence_chunks(message.content):
            revision_signal = knowledge_update_revision_signal(sentence)
            if revision_signal <= 0:
                continue
            sentence_overlap = knowledge_update_target_overlap(question, sentence)
            if revision_signal < 7.0 and sentence_overlap < 1:
                continue
            if message_overlap < 1 and sentence_overlap < 1:
                continue
            normalized = re.sub(r"\s+", " ", sentence.lower()).strip()
            if (message.event_id, normalized) in existing_pairs:
                continue
            if any(claim_support_score(sentence, item.get("value", "")) >= 0.82 for item in enriched if item.get("event_id") == message.event_id):
                continue
            enriched.append(
                {
                    "claim_id": f"ku_revision_{next_index}",
                    "source_claim_id": f"deterministic_revision_{next_index}",
                    "event_id": message.event_id,
                    "facet_type": "current_approach",
                    "value": sentence,
                    "claim_type": "correction" if revision_signal >= message_revision_signal else "update",
                    "time_value": None,
                    "time_role": "updated_at",
                    "source_enrichment": "knowledge_update_revision_sentence",
                }
            )
            existing_pairs.add((message.event_id, normalized))
            next_index += 1
        if message_revision_signal <= 0:
            continue
        for sentence in sentence_chunks(message.content):
            if not re.match(r"^\s*proposal\s*:", sentence, flags=re.I):
                continue
            sentence_overlap = knowledge_update_target_overlap(question, sentence)
            if message_overlap < 1 and sentence_overlap < 1:
                continue
            normalized = re.sub(r"\s+", " ", sentence.lower()).strip()
            if (message.event_id, normalized) in existing_pairs:
                continue
            if any(
                claim_support_score(sentence, item.get("value", "")) >= 0.82
                for item in enriched
                if item.get("event_id") == message.event_id
            ):
                continue
            enriched.append(
                {
                    "claim_id": f"ku_revision_{next_index}",
                    "source_claim_id": f"deterministic_revision_{next_index}",
                    "event_id": message.event_id,
                    "facet_type": "current_approach",
                    "value": sentence,
                    "claim_type": "update",
                    "time_value": None,
                    "time_role": "updated_at",
                    "source_enrichment": "knowledge_update_proposal_sentence",
                }
            )
            existing_pairs.add((message.event_id, normalized))
            next_index += 1
    return enriched


def chunks(items: Sequence[GroupMessage], size: int) -> List[Sequence[GroupMessage]]:
    chunk_size = max(1, size)
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def normalize_claim_nodes(
    raw: Dict[str, object],
    visible_messages: Sequence[GroupMessage],
    chunk_index: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    visible_ids = {message.event_id for message in visible_messages}
    claims: List[Dict[str, object]] = []
    rejected_claims: List[Dict[str, object]] = []
    dropped_invalid: List[Dict[str, str]] = []
    dropped_unsupported: List[Dict[str, object]] = []
    visible_by_id = messages_by_id(visible_messages)
    raw_claims = raw.get("claims", [])
    if isinstance(raw_claims, list):
        for index, item in enumerate(raw_claims):
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id", ""))
            if event_id not in visible_ids:
                dropped_invalid.append({"field": f"claims[{index}].event_id", "event_id": event_id})
                continue
            source_message = visible_by_id[event_id]
            support_score = claim_support_score(item.get("value", ""), source_message.content)
            if support_score < 0.45:
                dropped_unsupported.append(
                    {
                        "event_id": event_id,
                        "value": str(item.get("value", ""))[:240],
                        "support_score": round(support_score, 4),
                    }
                )
                continue
            claim_id = str(item.get("claim_id") or f"chunk{chunk_index}_claim{len(claims) + 1}")
            claims.append(
                {
                    "claim_id": f"c{chunk_index}_{len(claims) + 1}",
                    "source_claim_id": claim_id,
                    "event_id": event_id,
                    "facet_type": str(item.get("facet_type") or "state"),
                    "value": str(item.get("value", "")),
                    "claim_type": str(item.get("claim_type") or "observation"),
                    "time_value": item.get("time_value") if item.get("time_value") not in {"", "null"} else None,
                    "time_role": item.get("time_role") if item.get("time_role") not in {"", "null"} else None,
                }
            )
    raw_rejected = raw.get("rejected_claims", [])
    if isinstance(raw_rejected, list):
        for item in raw_rejected:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id", ""))
            if event_id and event_id not in visible_ids:
                continue
            rejected_claims.append({"event_id": event_id, "reason": str(item.get("reason", ""))})
    validation = {
        "chunk_index": chunk_index,
        "visible_event_count": len(visible_ids),
        "claim_count": len(claims),
        "rejected_claim_count": len(rejected_claims),
        "dropped_invalid_event_ids": dropped_invalid,
        "dropped_unsupported_claims": dropped_unsupported,
    }
    return claims, rejected_claims, validation


def claim_document(claim: Dict[str, object], event_by_id: Dict[str, GroupMessage]) -> str:
    message = event_by_id.get(str(claim.get("event_id", "")))
    parts = [
        claim.get("facet_type", ""),
        claim.get("claim_type", ""),
        claim.get("value", ""),
        claim.get("time_value", ""),
    ]
    if message:
        parts.extend([message.content, message.author, message.role, message.phase_name, message.topic])
    return " ".join(str(part) for part in parts if part)


def claim_task_boost(
    question: GroupQuestion,
    adapter: TaskAdapter,
    claim: Dict[str, object],
    routed_time_role: Optional[str] = None,
) -> float:
    value = str(claim.get("value", "")).lower()
    question_text = question.question.lower()
    boost = 0.0
    if adapter.qtype == "knowledge_update":
        boost += max(-6.0, min(10.0, 0.6 * knowledge_update_claim_quality(question, claim)))
    if adapter.qtype in {"temporal", "multi_hop", "term_ambiguity"} and (
        "date" in question_text or "deadline" in question_text or "yyyy-mm-dd" in question_text
    ):
        time_text = " ".join(str(claim.get(key, "") or "") for key in ("time_value", "time_role", "value")).lower()
        if ISO_DATE_RE.search(time_text) or MONTH_DATE_RE.search(time_text) or WEEKDAY_RE.search(time_text) or RELATIVE_DAY_RE.search(time_text):
            boost += 4.0
        if routed_time_role and str(claim.get("time_role") or "") == routed_time_role:
            boost += 3.0
        if routed_time_role == "occurred_at":
            question_tokens = set(claim_support_tokens(question_text))
            claim_tokens = set(claim_support_tokens(value))
            boost += min(6.0, 0.9 * len(question_tokens & claim_tokens))
            if any(term in value for term in ("asked", "instructed", "please", "lock", "freeze", "send")):
                boost += 2.0
        elif routed_time_role in {"deadline_at", "planned_for"}:
            question_tokens = set(claim_support_tokens(question_text))
            claim_tokens = set(claim_support_tokens(time_text))
            boost += min(5.0, 0.7 * len(question_tokens & claim_tokens))
            if any(term in value for term in ("deadline", "due", "target", "by ", "eod", "end of day", "friday", "tomorrow")):
                boost += 2.0
    if adapter.qtype == "user_implicit" and question.asking_user_id:
        if "i " in value or "my " in value or question.asking_user_id.lower() in value:
            boost += 2.0
    return boost


def select_claim_candidates(
    question: GroupQuestion,
    adapter: TaskAdapter,
    claims: Sequence[Dict[str, object]],
    graph_messages: Sequence[GroupMessage],
    claim_limit: int,
    routed_time_role: Optional[str] = None,
) -> Tuple[List[Dict[str, object]], List[GroupMessage], Dict[str, object]]:
    if not claims:
        return [], [], {"selection_strategy": "claim_bm25", "selected_claim_count": 0}
    event_by_id = messages_by_id(graph_messages)
    query = f"{question.asking_user_id} {question.question}".strip()
    documents = [claim_document(claim, event_by_id) for claim in claims]
    scores = bm25_scores(documents, query)
    scored = []
    for index, (claim, score) in enumerate(zip(claims, scores)):
        event_time = ""
        message = event_by_id.get(str(claim.get("event_id", "")))
        if message:
            event_time = message.timestamp
        total_score = score + claim_task_boost(question, adapter, claim, routed_time_role)
        scored.append((total_score, event_time, index, claim))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected_claims = [deepcopy(item[3]) for item in scored[: max(1, claim_limit)]]
    selected_event_ids = []
    for claim in selected_claims:
        event_id = str(claim.get("event_id", ""))
        if event_id and event_id not in selected_event_ids:
            selected_event_ids.append(event_id)
    source_messages = [event_by_id[event_id] for event_id in selected_event_ids if event_id in event_by_id]
    return selected_claims, source_messages, {
        "selection_strategy": "claim_bm25_over_extracted_claim_graph",
        "extracted_claim_count": len(claims),
        "selected_claim_count": len(selected_claims),
        "selected_event_count": len(source_messages),
        "top_claim_scores": [
            {
                "claim_id": str(item[3].get("claim_id", "")),
                "event_id": str(item[3].get("event_id", "")),
                "score": round(item[0], 6),
                "time_role": item[3].get("time_role"),
                "time_value": item[3].get("time_value"),
                "value": str(item[3].get("value", ""))[:240],
            }
            for item in scored[: min(max(1, claim_limit), 20)]
        ],
    }


def raw_validity_packet(raw: Dict[str, object]) -> Dict[str, object]:
    packet = raw.get("validity_packet")
    return deepcopy(packet) if isinstance(packet, dict) else deepcopy(raw)


def knowledge_update_required_qualifiers(text: object) -> set[str]:
    lowered = str(text or "").lower()
    qualifiers = set()
    if "recovery state" in lowered or "recovery-state" in lowered or ("recovery" in lowered and "state" in lowered):
        qualifiers.add("recovery_states")
    if "before sign-off" in lowered or "before signoff" in lowered or "before sign off" in lowered:
        qualifiers.add("before_signoff")
    if "delay" in lowered or "tradeoff" in lowered or "trade-off" in lowered:
        qualifiers.add("delay_tradeoff")
    if "owner" in lowered or "dependency" in lowered or "dependencies" in lowered:
        qualifiers.add("owner_dependency")
    if "fallback" in lowered:
        qualifiers.add("fallback_boundary")
    if "exception" in lowered or "condition" in lowered:
        qualifiers.add("condition_boundary")
    return qualifiers


TARGET_SUPPORT_STOPWORDS = {
    "that",
    "will",
    "with",
    "using",
    "used",
    "uses",
    "need",
    "needs",
    "available",
    "conversation",
    "answer",
    "question",
}


def normalize_target_token(token: str) -> str:
    token = token.lower()
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def target_object_terms(question: GroupQuestion) -> set[str]:
    return {
        normalize_target_token(term)
        for term in question_target_terms(question)
        if term not in TARGET_SUPPORT_STOPWORDS
    }


def normalized_support_token_set(text: object) -> set[str]:
    tokens: set[str] = set()
    for token in claim_support_tokens(text):
        normalized = normalize_target_token(token)
        tokens.add(normalized)
        if normalized.startswith("revalidation"):
            tokens.add("validation")
    return tokens


def repair_knowledge_update_supersedes(
    question: GroupQuestion,
    accepted_current_claims: List[Dict[str, object]],
    rejected_claims: List[Dict[str, object]],
    relations: List[Dict[str, object]],
    claim_by_id: Dict[str, Dict[str, object]],
    warnings: List[str],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    if question.qtype != "knowledge_update":
        return accepted_current_claims, rejected_claims, relations
    accepted_ids = {str(item.get("claim_id", "")) for item in accepted_current_claims}
    next_relations: List[Dict[str, object]] = []
    resurrected_ids = set()
    for relation in relations:
        if str(relation.get("type", "")).upper() != "SUPERSEDES":
            next_relations.append(relation)
            continue
        newer_id = str(relation.get("from", ""))
        older_id = str(relation.get("to", ""))
        newer = claim_by_id.get(newer_id)
        older = claim_by_id.get(older_id)
        if not newer or not older or newer_id not in accepted_ids:
            next_relations.append(relation)
            continue
        older_qualifiers = knowledge_update_required_qualifiers(older.get("value", ""))
        if not older_qualifiers:
            next_relations.append(relation)
            continue
        newer_qualifiers = knowledge_update_required_qualifiers(newer.get("value", ""))
        missing = sorted(older_qualifiers - newer_qualifiers)
        if not missing or knowledge_update_target_overlap(question, older.get("value", "")) < 1:
            next_relations.append(relation)
            continue
        warnings.append(
            f"knowledge_update_incomplete_supersedes_removed:{newer_id}->{older_id}:{','.join(missing)}"
        )
        if older_id not in accepted_ids:
            accepted_current_claims.append(
                {
                    "claim_id": older_id,
                    "event_id": str(older.get("event_id", "")),
                    "facet_type": str(older.get("facet_type") or "state"),
                    "validity": "current_valid",
                    "reason": (
                        "Preserved as current StateFacet support because a later confirming Claim did not cover "
                        f"required qualifiers: {', '.join(missing)}."
                    ),
                }
            )
            accepted_ids.add(older_id)
            resurrected_ids.add(older_id)
    if resurrected_ids:
        rejected_claims = [
            item
            for item in rejected_claims
            if str(item.get("claim_id", "")) not in resurrected_ids
        ]
    return accepted_current_claims, rejected_claims, next_relations


KNOWLEDGE_UPDATE_DETAIL_TERMS = {
    "band",
    "breach",
    "breached",
    "checkpoint",
    "condition",
    "control",
    "fallback",
    "hours",
    "include",
    "primary",
    "queue",
    "revalidation",
    "secondary",
    "tolerance",
    "trigger",
    "volume",
}


def knowledge_update_focus_terms(question: GroupQuestion) -> set[str]:
    return target_object_terms(question)


def knowledge_update_claim_focus_metrics(
    question: GroupQuestion,
    claim: Dict[str, object],
    event_by_id: Dict[str, GroupMessage],
) -> Dict[str, object]:
    value = str(claim.get("value", ""))
    claim_text = " ".join(
        str(part or "")
        for part in (claim.get("facet_type"), claim.get("claim_type"), value)
    )
    message = event_by_id.get(str(claim.get("event_id", "")))
    event_text = message.content if message else ""
    combined_text = " ".join(part for part in (claim_text, event_text) if part)
    terms = knowledge_update_focus_terms(question)
    claim_overlap = terms & normalized_support_token_set(claim_text)
    combined_overlap = terms & normalized_support_token_set(combined_text)
    value_tokens = normalized_support_token_set(value)
    detail_hits = len(KNOWLEDGE_UPDATE_DETAIL_TERMS & value_tokens)
    revision_signal = knowledge_update_revision_signal(combined_text)
    score = (
        4.0 * len(combined_overlap)
        + 2.0 * len(claim_overlap)
        + min(12.0, revision_signal)
        + 1.2 * knowledge_update_claim_quality(question, claim)
        + 0.9 * detail_hits
        + min(4.0, len(value_tokens) / 5.0)
    )
    question_text = question.question.lower()
    if str(claim.get("time_role") or "") in {"deadline_at", "planned_for"} and not any(
        term in question_text for term in ("date", "deadline", "when", "by what")
    ):
        score -= 4.0
    if re.search(r"\bconfirm\b.*\bby\b", value, flags=re.I):
        score -= 3.0
    return {
        "score": score,
        "claim_overlap_count": len(claim_overlap),
        "combined_overlap_count": len(combined_overlap),
        "target_terms": sorted(terms),
        "claim_overlap": sorted(claim_overlap),
        "combined_overlap": sorted(combined_overlap),
        "detail_hits": detail_hits,
        "revision_signal": revision_signal,
        "event_time": message.timestamp if message else "",
    }


def required_knowledge_update_overlap(question: GroupQuestion) -> int:
    terms = knowledge_update_focus_terms(question)
    if not terms:
        return 0
    return max(1, min(len(terms), math.ceil(0.60 * len(terms))))


def best_knowledge_update_claim_id(
    question: GroupQuestion,
    claim_ids: Sequence[str],
    claim_by_id: Dict[str, Dict[str, object]],
    event_by_id: Dict[str, GroupMessage],
) -> Optional[str]:
    required_overlap = required_knowledge_update_overlap(question)
    candidates: List[Tuple[float, str, str]] = []
    for claim_id in claim_ids:
        claim = claim_by_id.get(claim_id)
        if not claim:
            continue
        metrics = knowledge_update_claim_focus_metrics(question, claim, event_by_id)
        if required_overlap and int(metrics["combined_overlap_count"]) < required_overlap:
            continue
        candidates.append((float(metrics["score"]), str(metrics["event_time"]), claim_id))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates[0][2]


def repair_knowledge_update_target_miss(
    question: GroupQuestion,
    accepted_current_claims: List[Dict[str, object]],
    rejected_claims: List[Dict[str, object]],
    claim_by_id: Dict[str, Dict[str, object]],
    event_by_id: Dict[str, GroupMessage],
    warnings: List[str],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    if question.qtype != "knowledge_update":
        return accepted_current_claims, rejected_claims
    required_overlap = required_knowledge_update_overlap(question)
    if required_overlap <= 0:
        return accepted_current_claims, rejected_claims

    accepted_ids = {str(item.get("claim_id", "")) for item in accepted_current_claims}
    accepted_metrics = {
        claim_id: knowledge_update_claim_focus_metrics(question, claim_by_id[claim_id], event_by_id)
        for claim_id in accepted_ids
        if claim_id in claim_by_id
    }
    accepted_best_score = max((float(item["score"]) for item in accepted_metrics.values()), default=-999.0)
    accepted_best_overlap = max((int(item["combined_overlap_count"]) for item in accepted_metrics.values()), default=0)
    accepted_latest_time = max((str(item["event_time"]) for item in accepted_metrics.values()), default="")

    candidates: List[Tuple[float, str, str, Dict[str, object]]] = []
    for claim_id, claim in claim_by_id.items():
        if claim_id in accepted_ids:
            continue
        metrics = knowledge_update_claim_focus_metrics(question, claim, event_by_id)
        if int(metrics["combined_overlap_count"]) < required_overlap:
            continue
        if float(metrics["revision_signal"]) < 5.0:
            continue
        if accepted_latest_time and str(metrics["event_time"]) < accepted_latest_time and float(metrics["score"]) <= accepted_best_score + 8.0:
            continue
        if float(metrics["score"]) <= accepted_best_score + 3.0 and int(metrics["combined_overlap_count"]) <= accepted_best_overlap:
            continue
        candidates.append((float(metrics["score"]), str(metrics["event_time"]), claim_id, metrics))

    if not candidates:
        return accepted_current_claims, rejected_claims

    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    best_score, best_time, best_id, best_metrics = candidates[0]
    repaired_accepted: List[Dict[str, object]] = []
    rejected_ids = {str(item.get("claim_id", "")) for item in rejected_claims}
    for item in accepted_current_claims:
        claim_id = str(item.get("claim_id", ""))
        metrics = accepted_metrics.get(claim_id)
        if not metrics:
            continue
        if (
            best_time >= str(metrics["event_time"])
            and best_score >= float(metrics["score"]) + 6.0
            and int(metrics["claim_overlap_count"]) < required_overlap
        ):
            warnings.append(f"knowledge_update_target_mismatch_demoted:{claim_id}->{best_id}")
            if claim_id not in rejected_ids:
                rejected_claims.append(
                    {
                        "claim_id": claim_id,
                        "event_id": str(claim_by_id.get(claim_id, {}).get("event_id", "")),
                        "validity": "wrong_target",
                        "reason": (
                            "Demoted because a later update Claim covers the query target more directly "
                            f"(target_overlap={best_metrics['combined_overlap']})."
                        ),
                    }
                )
                rejected_ids.add(claim_id)
            continue
        repaired_accepted.append(item)

    best_claim = claim_by_id[best_id]
    repaired_accepted.append(
        {
            "claim_id": best_id,
            "event_id": str(best_claim.get("event_id", "")),
            "facet_type": str(best_claim.get("facet_type") or "current_approach"),
            "validity": "current_valid",
            "reason": (
                "Recovered as current support because it is an update/revision Claim that directly covers "
                f"the query target terms {best_metrics['combined_overlap']}."
            ),
        }
    )
    rejected_claims = [
        item
        for item in rejected_claims
        if str(item.get("claim_id", "")) != best_id
    ]
    warnings.append(f"knowledge_update_target_support_recovered:{best_id}")
    return repaired_accepted, rejected_claims


def validate_and_repair_validity_packet(
    raw: Dict[str, object],
    question: GroupQuestion,
    route: ScopeRoute,
    candidate_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    packet = raw_validity_packet(raw)
    claim_by_id = {
        str(claim.get("claim_id", "")): claim
        for claim in candidate_claims
        if isinstance(claim, dict) and claim.get("claim_id")
    }
    claim_ids = set(claim_by_id)
    visible_ids = {message.event_id for message in source_messages}
    warnings: List[str] = []
    dropped_invalid: List[Dict[str, str]] = []

    target_scope_id = str(packet.get("target_scope_id") or route.target_scope.scope_id)
    if target_scope_id != route.target_scope.scope_id:
        warnings.append("validity_target_scope_id_repaired")
        target_scope_id = route.target_scope.scope_id

    accepted_current_claims: List[Dict[str, object]] = []
    raw_accepted = packet.get("accepted_current_claims", [])
    if isinstance(raw_accepted, list):
        seen = set()
        for index, item in enumerate(raw_accepted):
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id", ""))
            if claim_id not in claim_ids:
                dropped_invalid.append({"field": f"validity_packet.accepted_current_claims[{index}].claim_id", "claim_id": claim_id})
                continue
            if claim_id in seen:
                continue
            seen.add(claim_id)
            source_claim = claim_by_id[claim_id]
            accepted_current_claims.append(
                {
                    "claim_id": claim_id,
                    "event_id": str(source_claim.get("event_id", "")),
                    "facet_type": str(item.get("facet_type") or source_claim.get("facet_type") or "state"),
                    "validity": "current_valid",
                    "reason": str(item.get("reason", "")),
                }
            )
    elif not is_emptyish(raw_accepted):
        warnings.append("validity_accepted_current_claims_not_list")

    rejected_claims: List[Dict[str, object]] = []
    raw_rejected = packet.get("rejected_claims", [])
    if isinstance(raw_rejected, list):
        seen_rejected = set()
        for index, item in enumerate(raw_rejected):
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id", ""))
            if claim_id and claim_id not in claim_ids:
                dropped_invalid.append({"field": f"validity_packet.rejected_claims[{index}].claim_id", "claim_id": claim_id})
                continue
            event_id = str(item.get("event_id") or claim_by_id.get(claim_id, {}).get("event_id", ""))
            if event_id and visible_ids and event_id not in visible_ids:
                dropped_invalid.append({"field": f"validity_packet.rejected_claims[{index}].event_id", "event_id": event_id})
                continue
            key = (claim_id, event_id, str(item.get("validity", "")))
            if key in seen_rejected:
                continue
            seen_rejected.add(key)
            rejected_claims.append(
                {
                    "claim_id": claim_id,
                    "event_id": event_id,
                    "validity": str(item.get("validity") or item.get("reason") or "irrelevant"),
                    "reason": str(item.get("reason", "")),
                }
            )
    elif not is_emptyish(raw_rejected):
        warnings.append("validity_rejected_claims_not_list")

    relations: List[Dict[str, object]] = []
    raw_relations = packet.get("relations", [])
    if isinstance(raw_relations, list):
        for index, item in enumerate(raw_relations):
            if not isinstance(item, dict):
                continue
            relation_type = str(item.get("type", "")).upper()
            if relation_type not in ALLOWED_RELATION_TYPES:
                warnings.append(f"validity_unsupported_relation_type:{relation_type or 'missing'}")
                continue
            from_id = str(item.get("from", ""))
            to_id = str(item.get("to", ""))
            if from_id not in claim_ids or to_id not in claim_ids:
                dropped_invalid.append({"field": f"validity_packet.relations[{index}]", "claim_id": f"{from_id}->{to_id}"})
                continue
            evidence_event_ids = [
                event_id
                for event_id in normalize_id_list(item.get("evidence_event_ids"))
                if not visible_ids or event_id in visible_ids
            ]
            relations.append(
                {
                    "type": relation_type,
                    "from": from_id,
                    "to": to_id,
                    "evidence_event_ids": evidence_event_ids,
                    "reason": str(item.get("reason", "")),
                }
            )
    elif not is_emptyish(raw_relations):
        warnings.append("validity_relations_not_list")

    accepted_ids = {str(item.get("claim_id", "")) for item in accepted_current_claims}
    rejected_ids = {str(item.get("claim_id", "")) for item in rejected_claims}
    overlap = accepted_ids & rejected_ids
    if overlap:
        warnings.append("validity_claim_id_overlap_repaired")
        rejected_claims = [item for item in rejected_claims if str(item.get("claim_id", "")) not in overlap]

    accepted_current_claims, rejected_claims, relations = repair_knowledge_update_supersedes(
        question,
        accepted_current_claims,
        rejected_claims,
        relations,
        claim_by_id,
        warnings,
    )
    accepted_current_claims, rejected_claims = repair_knowledge_update_target_miss(
        question,
        accepted_current_claims,
        rejected_claims,
        claim_by_id,
        messages_by_id(source_messages),
        warnings,
    )
    repaired_packet = {
        "target_scope_id": target_scope_id,
        "accepted_current_claims": accepted_current_claims,
        "rejected_claims": rejected_claims,
        "relations": relations,
    }
    validation = {
        "status": "invalid_removed" if dropped_invalid else "schema_warning" if warnings else "ok",
        "case_id": question.case_id,
        "candidate_claim_count": len(candidate_claims),
        "accepted_current_claim_count": len(accepted_current_claims),
        "rejected_claim_count": len(rejected_claims),
        "relation_count": len(relations),
        "dropped_invalid_ids": dropped_invalid,
        "schema_warnings": warnings,
    }
    return repaired_packet, validation


def complete_claim_validity_packet(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    selected_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    routed_time_role: Optional[str] = None,
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object]]:
    if not selected_claims:
        packet = {
            "target_scope_id": route.target_scope.scope_id,
            "accepted_current_claims": [],
            "rejected_claims": [],
            "relations": [],
        }
        validation = {
            "status": "ok",
            "case_id": question.case_id,
            "candidate_claim_count": 0,
            "accepted_current_claim_count": 0,
            "rejected_claim_count": 0,
            "relation_count": 0,
            "dropped_invalid_ids": [],
            "schema_warnings": [],
        }
        return packet, validation, {}
    system = validity_system_prompt(adapter)
    raw = client.complete_json(
        system,
        validity_user_prompt(
            question,
            adapter,
            route,
            selected_claims,
            source_messages,
            scope_messages,
            routed_time_role,
        ),
    )
    repaired, validation = validate_and_repair_validity_packet(raw, question, route, selected_claims, source_messages)
    return repaired, validation, raw


def validate_and_repair_graph_packet(
    raw: Dict[str, object],
    question: GroupQuestion,
    route: ScopeRoute,
    candidate_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    routed_time_role: Optional[str] = None,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    visible_ids = {message.event_id for message in candidate_messages}
    visible_order = [message.event_id for message in candidate_messages]
    times_by_id = message_times_by_id(candidate_messages)
    visible_by_id = messages_by_id(candidate_messages)
    packet = raw_state_packet(raw)
    warnings: List[str] = []
    dropped_invalid: List[Dict[str, str]] = []

    def repair_event_ids(value: object, field: str) -> List[str]:
        repaired: List[str] = []
        for event_id in normalize_id_list(value):
            if event_id in visible_ids:
                if event_id not in repaired:
                    repaired.append(event_id)
            else:
                dropped_invalid.append({"field": field, "event_id": event_id})
        return repaired

    target_scope_id = str(packet.get("target_scope_id") or route.target_scope.scope_id)
    if target_scope_id != route.target_scope.scope_id:
        warnings.append("target_scope_id_repaired")
        target_scope_id = route.target_scope.scope_id

    candidate_events = repair_event_ids(packet.get("candidate_events"), "state_packet.candidate_events")
    if not candidate_events:
        candidate_events = list(visible_order)

    claims: List[Dict[str, object]] = []
    raw_claims = packet.get("claims", [])
    if isinstance(raw_claims, list):
        for index, item in enumerate(raw_claims):
            if not isinstance(item, dict):
                continue
            claim = deepcopy(item)
            event_id = str(claim.get("event_id", ""))
            if event_id not in visible_ids:
                dropped_invalid.append({"field": f"state_packet.claims[{index}].event_id", "event_id": event_id})
                continue
            claim["claim_id"] = str(claim.get("claim_id") or f"claim_{len(claims) + 1}")
            claim["event_id"] = event_id
            claim["facet_type"] = str(claim.get("facet_type") or "state")
            claim["value"] = str(claim.get("value", ""))
            claim["claim_type"] = str(claim.get("claim_type") or "observation")
            claims.append(claim)
    elif not is_emptyish(raw_claims):
        warnings.append("claims_not_list")
    claim_ids = {str(claim["claim_id"]) for claim in claims}

    relations: List[Dict[str, object]] = []
    raw_relations = packet.get("relations", [])
    if isinstance(raw_relations, list):
        for index, item in enumerate(raw_relations):
            if not isinstance(item, dict):
                continue
            relation_type = str(item.get("type", "")).upper()
            if relation_type not in ALLOWED_RELATION_TYPES:
                warnings.append(f"unsupported_relation_type:{relation_type or 'missing'}")
                continue
            relation = deepcopy(item)
            relation["type"] = relation_type
            relation["from"] = str(relation.get("from", ""))
            relation["to"] = str(relation.get("to", ""))
            relation["evidence_event_ids"] = repair_event_ids(
                relation.get("evidence_event_ids"),
                f"state_packet.relations[{index}].evidence_event_ids",
            )
            relation["reason"] = str(relation.get("reason", ""))
            relations.append(relation)
    elif not is_emptyish(raw_relations):
        warnings.append("relations_not_list")

    rejected_claims: List[Dict[str, object]] = []
    raw_rejected = packet.get("rejected_claims", [])
    if isinstance(raw_rejected, list):
        for index, item in enumerate(raw_rejected):
            if not isinstance(item, dict):
                continue
            rejected = deepcopy(item)
            event_id = str(rejected.get("event_id", ""))
            if event_id and event_id not in visible_ids:
                dropped_invalid.append(
                    {"field": f"state_packet.rejected_claims[{index}].event_id", "event_id": event_id}
                )
                continue
            rejected["claim_id"] = str(rejected.get("claim_id", ""))
            rejected["event_id"] = event_id
            rejected["reason"] = str(rejected.get("reason", ""))
            rejected_claims.append(rejected)
    elif not is_emptyish(raw_rejected):
        warnings.append("rejected_claims_not_list")

    claim_by_id = {str(claim["claim_id"]): claim for claim in claims}
    raw_validity = packet.get("validity_decisions", {})
    validity_packet = raw_validity if isinstance(raw_validity, dict) else {}
    accepted_current_claim_ids: List[str] = []
    validity_by_claim: Dict[str, str] = {}
    if isinstance(validity_packet.get("accepted_current_claims"), list):
        for item in validity_packet.get("accepted_current_claims", []):
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id", ""))
            if claim_id in claim_by_id and claim_id not in accepted_current_claim_ids:
                accepted_current_claim_ids.append(claim_id)
                validity_by_claim[claim_id] = "current_valid"
    if isinstance(validity_packet.get("rejected_claims"), list):
        for item in validity_packet.get("rejected_claims", []):
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id", ""))
            if claim_id in claim_by_id and claim_id not in validity_by_claim:
                validity_by_claim[claim_id] = str(item.get("validity") or "rejected")
    if validity_packet and not accepted_current_claim_ids:
        warnings.append("validity_packet_without_accepted_current_claims")
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        if claim_id in validity_by_claim:
            claim["validity_status"] = validity_by_claim[claim_id]

    replacement_by_claim: Dict[str, str] = {}
    for relation in relations:
        if relation.get("type") in {"SUPERSEDES", "CORRECTS"}:
            newer = str(relation.get("from", ""))
            older = str(relation.get("to", ""))
            if newer in claim_by_id and older in claim_by_id:
                replacement_by_claim[older] = newer

    def current_claim_id(claim_id: str) -> str:
        seen = set()
        current = claim_id
        while current in replacement_by_claim and current not in seen:
            seen.add(current)
            current = replacement_by_claim[current]
        return current

    def best_knowledge_update_support_claim_id() -> Optional[str]:
        if question.qtype != "knowledge_update":
            return None
        return best_knowledge_update_claim_id(
            question,
            accepted_current_claim_ids,
            claim_by_id,
            visible_by_id,
        )

    def event_date_for_claim(claim: Dict[str, object]) -> Optional[str]:
        event_time = times_by_id.get(str(claim.get("event_id", "")), "")
        match = ISO_DATE_RE.search(event_time)
        return match.group(0) if match else None

    def temporal_date_candidates_for_claim(claim: Dict[str, object], role: Optional[str]) -> List[str]:
        event_id = str(claim.get("event_id", ""))
        event_time = times_by_id.get(event_id, "")
        event_year = int(event_time[:4]) if ISO_DATE_RE.search(event_time) else None
        if role in {"occurred_at", "updated_at"}:
            event_date = event_date_for_claim(claim)
            return [event_date] if event_date else []
        texts = [claim.get("value", "")]
        message = visible_by_id.get(event_id)
        if message:
            texts.append(message.content)
        texts.append(claim.get("time_value", ""))
        candidates: List[str] = []
        for text in texts:
            for candidate in date_candidates_from_text(text, event_year, event_time):
                if candidate not in candidates:
                    candidates.append(candidate)
        if candidates:
            return candidates
        if role == "mentioned_at":
            event_date = event_date_for_claim(claim)
            return [event_date] if event_date else []
        return []

    def temporal_claim_score(claim: Dict[str, object], role: Optional[str]) -> float:
        event_id = str(claim.get("event_id", ""))
        message = visible_by_id.get(event_id)
        text = " ".join(
            str(part or "")
            for part in (
                claim.get("facet_type"),
                claim.get("claim_type"),
                claim.get("value"),
                claim.get("time_value"),
                message.content if message else "",
            )
        ).lower()
        question_tokens = set(claim_support_tokens(question.question))
        claim_tokens = set(claim_support_tokens(text))
        overlap = len(question_tokens & claim_tokens)
        score = 1.8 * overlap
        score += min(4.0, len(claim_tokens) / 6.0)
        if temporal_date_candidates_for_claim(claim, role):
            score += 4.0
        if role and str(claim.get("time_role") or "") == role:
            score += 3.0
        elif role and not claim.get("time_role"):
            score += 0.5
        if role == "occurred_at":
            if any(term in text for term in ("asked", "instructed", "requested", "please", "lock", "freeze", "send")):
                score += 3.0
        elif role == "deadline_at":
            if any(term in text for term in ("deadline", "due", "target", "by ", "eod", "end of day", "cutoff")):
                score += 3.0
            if WEEKDAY_RE.search(text) or "tomorrow" in text:
                score += 3.0
        elif role == "planned_for":
            if any(term in text for term in ("expected", "complete", "completed", "target", "planned", "scheduled", "clean")):
                score += 2.5
            if WEEKDAY_RE.search(text) or "tomorrow" in text:
                score += 3.0
            if any(term in text for term in ("final", "frozen", "clean", "closed", "last")):
                score += 2.0
        elif role == "mentioned_at":
            if any(term in text for term in ("mentioned", "noted", "target", "deadline", "date")):
                score += 1.5
        return score

    def repair_temporal_facet_support(
        facet_id: str,
        facet_name: str,
        value: str,
        status: str,
        support_claims: Sequence[str],
    ) -> Optional[Tuple[List[str], List[str], Optional[str], str, str, str, str]]:
        if question.qtype != "temporal" or status != "active":
            return None
        role = routed_time_role or "updated_at"
        current_scores = [
            temporal_claim_score(claim_by_id[claim_id], role)
            for claim_id in support_claims
            if claim_id in claim_by_id
        ]
        current_score = max(current_scores) if current_scores else -999.0
        candidates: List[Tuple[float, int, str, str, Dict[str, object], str]] = []
        for claim in claims:
            claim_id = str(claim.get("claim_id", ""))
            if not claim_id:
                continue
            if accepted_current_claim_ids and claim_id not in accepted_current_claim_ids:
                continue
            claim_dates = temporal_date_candidates_for_claim(claim, role)
            if not claim_dates:
                continue
            event_id = str(claim.get("event_id", ""))
            if event_id not in visible_ids:
                continue
            score = temporal_claim_score(claim, role)
            if score < 7.0:
                continue
            specificity = len(set(claim_support_tokens(str(claim.get("value", "")))))
            candidates.append((score, specificity, times_by_id.get(event_id, ""), claim_id, claim, claim_dates[0]))
        if not candidates:
            return None
        if role == "occurred_at":
            max_score = max(item[0] for item in candidates)
            close_candidates = [item for item in candidates if item[0] >= max_score - 3.0]
            close_candidates.sort(key=lambda item: (item[5], -item[0], -item[1], item[2], item[3]))
            candidates = close_candidates
        elif role == "planned_for":
            max_score = max(item[0] for item in candidates)
            close_candidates = [item for item in candidates if item[0] >= max_score - 3.0]
            close_candidates.sort(key=lambda item: (item[5], item[0], item[1], item[2], item[3]), reverse=True)
            candidates = close_candidates
        else:
            candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
        best_score, _, _, best_claim_id, best_claim, best_date = candidates[0]
        current_dates = [
            temporal_date_candidates_for_claim(claim_by_id[claim_id], role)[0]
            for claim_id in support_claims
            if claim_id in claim_by_id and temporal_date_candidates_for_claim(claim_by_id[claim_id], role)
        ]
        if best_claim_id in support_claims and current_dates and current_dates[0] == best_date:
            return None
        if best_claim_id not in support_claims and best_score <= current_score + 1.5:
            return None
        best_event_id = str(best_claim.get("event_id", ""))
        current_after = times_by_id.get(best_event_id) or None
        reason = f"temporal_state_facet_support_repaired:{facet_id}:{best_claim_id}:{role}"
        return [best_claim_id], [best_event_id], current_after, best_date, best_date, role, reason

    def filter_support_to_validity(
        facet_id: str,
        status: str,
        support_claims: Sequence[str],
    ) -> Tuple[List[str], Optional[str]]:
        if status != "active":
            return list(support_claims), None
        if validity_packet and not accepted_current_claim_ids:
            return [], f"state_facet_without_current_valid_support:{facet_id}"
        valid_supports = [claim_id for claim_id in support_claims if claim_id in accepted_current_claim_ids]
        if len(valid_supports) == len(list(support_claims)):
            return list(support_claims), None
        invalid_supports = [claim_id for claim_id in support_claims if claim_id not in accepted_current_claim_ids]
        if valid_supports:
            return valid_supports, f"state_facet_invalid_support_claims_removed:{facet_id}:{','.join(invalid_supports)}"
        return [], f"state_facet_without_current_valid_support:{facet_id}"

    state_facets: List[Dict[str, object]] = []
    raw_facets = packet.get("state_facets", [])
    if isinstance(raw_facets, list):
        for index, item in enumerate(raw_facets):
            if not isinstance(item, dict):
                continue
            facet = deepcopy(item)
            facet_id = str(facet.get("facet_id") or f"facet_{len(state_facets) + 1}")
            support_events = repair_event_ids(
                facet.get("support_events"),
                f"state_packet.state_facets[{index}].support_events",
            )
            raw_support_claims = [claim_id for claim_id in normalize_id_list(facet.get("support_claims")) if claim_id in claim_ids]
            support_claims = []
            for claim_id in raw_support_claims:
                repaired_claim_id = current_claim_id(claim_id)
                if repaired_claim_id not in support_claims:
                    support_claims.append(repaired_claim_id)
            if support_claims != raw_support_claims:
                warnings.append(f"state_facet_support_claims_repaired:{facet_id}")
            claim_support_events = []
            for claim_id in support_claims:
                claim = claim_by_id.get(claim_id)
                if claim and str(claim.get("event_id")) in visible_ids and str(claim.get("event_id")) not in claim_support_events:
                    claim_support_events.append(str(claim["event_id"]))
            if claim_support_events:
                support_events = claim_support_events
            status = str(facet.get("status") or "active")
            value = str(facet.get("value", ""))
            name = str(facet.get("name") or facet.get("facet_type") or facet_id)
            time_value = facet.get("time_value") if facet.get("time_value") not in {"", "null"} else None
            time_role = facet.get("time_role") if facet.get("time_role") not in {"", "null"} else None
            if status == "insufficient_evidence":
                if support_claims or support_events:
                    warnings.append(f"insufficient_evidence_facet_support_cleared:{facet_id}")
                support_claims = []
                support_events = []
                current_after = None
                value = "There is no information available in the conversation to answer this question."
                time_value = None
                time_role = None
            if not support_events and status != "insufficient_evidence":
                warnings.append(f"state_facet_without_support:{facet_id}")
            current_after = current_after if status == "insufficient_evidence" else facet.get("current_after")
            if not current_after and support_events:
                current_after = max(times_by_id.get(event_id, "") for event_id in support_events)
            filtered_support_claims, validity_support_warning = filter_support_to_validity(
                facet_id,
                status,
                support_claims,
            )
            if validity_support_warning:
                warnings.append(validity_support_warning)
            if filtered_support_claims != support_claims:
                support_claims = filtered_support_claims
                support_events = []
                for claim_id in support_claims:
                    event_id = str(claim_by_id.get(claim_id, {}).get("event_id", ""))
                    if event_id and event_id in visible_ids and event_id not in support_events:
                        support_events.append(event_id)
                current_after = max((times_by_id.get(event_id, "") for event_id in support_events), default="") or None
                if status == "active" and not support_claims:
                    if question.qtype == "knowledge_update":
                        fallback_claim_id = best_knowledge_update_support_claim_id()
                        fallback_claim = claim_by_id.get(fallback_claim_id or "")
                        fallback_event_id = str(fallback_claim.get("event_id", "")) if fallback_claim else ""
                        if fallback_claim and fallback_event_id in visible_ids:
                            support_claims = [str(fallback_claim_id)]
                            support_events = [fallback_event_id]
                            value = str(fallback_claim.get("value", ""))
                            name = str(fallback_claim.get("facet_type") or name or "current_approach")
                            status = "active"
                            current_after = times_by_id.get(fallback_event_id) or None
                            warnings.append(f"knowledge_update_state_support_repaired:{facet_id}:{fallback_claim_id}")
                        else:
                            status = "unknown_current"
                            current_after = None
                    else:
                        status = "unknown_current"
                        current_after = None
            temporal_repaired_support = repair_temporal_facet_support(
                facet_id,
                name,
                value,
                status,
                support_claims,
            )
            if temporal_repaired_support:
                support_claims, support_events, current_after, value, time_value, time_role, repair_reason = temporal_repaired_support
                warnings.append(repair_reason)
            if question.qtype == "temporal" and support_claims:
                role = routed_time_role or "updated_at"
                support_date_candidates: List[Tuple[float, str, str]] = []
                for claim_id in support_claims:
                    claim = claim_by_id.get(claim_id)
                    if not claim:
                        continue
                    claim_dates = temporal_date_candidates_for_claim(claim, role)
                    if not claim_dates:
                        continue
                    support_date_candidates.append((temporal_claim_score(claim, role), claim_id, claim_dates[0]))
                if support_date_candidates:
                    support_date_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
                    _, chosen_claim_id, chosen_date = support_date_candidates[0]
                    existing_dates = date_candidates_from_text(
                        " ".join(str(part or "") for part in (time_value, value)),
                        default_year_from_facets([{"current_after": current_after}]),
                        str(current_after or ""),
                    )
                    if time_value is None or not existing_dates or existing_dates[0] != chosen_date:
                        time_value = chosen_date
                        time_role = role
                        value = chosen_date
                        warnings.append(f"temporal_state_facet_time_value_repaired:{facet_id}:{chosen_claim_id}:{role}")
            if support_events:
                support_current_after = max(times_by_id.get(event_id, "") for event_id in support_events)
                if support_current_after and current_after != support_current_after:
                    warnings.append(f"state_facet_current_after_repaired_from_support:{facet_id}")
                    current_after = support_current_after
            state_facets.append(
                {
                    "facet_id": facet_id,
                    "name": name,
                    "value": value,
                    "status": status,
                    "support_claims": support_claims,
                    "support_events": support_events,
                    "current_after": str(current_after) if current_after is not None and current_after != "" else None,
                    "time_value": str(time_value) if time_value is not None and time_value != "" else None,
                    "time_role": str(time_role) if time_role is not None and time_role != "" else None,
                }
            )
    elif not is_emptyish(raw_facets):
        warnings.append("state_facets_not_list")
    if not state_facets:
        warnings.append("missing_state_facets")

    repaired_packet = {
        "target_scope_id": target_scope_id,
        "candidate_events": candidate_events,
        "claims": claims,
        "validity_decisions": validity_packet,
        "relations": relations,
        "rejected_claims": rejected_claims,
        "state_facets": state_facets,
    }
    graph_trace = build_graph_trace(route, scope_messages or candidate_messages, repaired_packet, routed_time_role)
    evidence_events: List[str] = []
    for facet in state_facets:
        for event_id in normalize_id_list(facet.get("support_events")):
            if event_id not in evidence_events:
                evidence_events.append(event_id)
    repaired = deepcopy(raw)
    repaired["state_packet"] = repaired_packet
    repaired["graph_trace"] = graph_trace
    repaired["evidence_events"] = evidence_events
    repaired["facets"] = state_facets
    validation = {
        "status": "invalid_removed" if dropped_invalid else "schema_warning" if warnings else "ok",
        "case_id": question.case_id,
        "routed_time_role": routed_time_role,
        "visible_event_count": len(visible_ids),
        "dropped_invalid_event_ids": dropped_invalid,
        "schema_warnings": warnings,
        "state_packet_invariants": {
            "target_scope_is_fixed": target_scope_id == route.target_scope.scope_id,
            "candidate_events_visible": all(event_id in visible_ids for event_id in candidate_events),
            "claims_have_visible_event_ids": all(claim.get("event_id") in visible_ids for claim in claims),
            "in_scope_episode_event_count": len(scope_messages or candidate_messages),
            "episode_event_context_count": len(candidate_messages),
            "facet_count": len(state_facets),
            "claim_count": len(claims),
            "relation_count": len(relations),
            "rejected_claim_count": len(rejected_claims),
            "accepted_current_claim_count": len(accepted_current_claim_ids),
            "active_facets_support_current_valid_claims": all(
                str(facet.get("status", "")) != "active"
                or not accepted_current_claim_ids
                or all(claim_id in accepted_current_claim_ids for claim_id in normalize_id_list(facet.get("support_claims")))
                for facet in state_facets
            ),
        },
    }
    trace = repaired.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["graph_packet_validation"] = validation
    repaired["pipeline_trace"] = trace
    return repaired, validation


def build_graph_trace(
    route: ScopeRoute,
    candidate_messages: Sequence[GroupMessage],
    packet: Dict[str, object],
    routed_time_role: Optional[str] = None,
) -> Dict[str, object]:
    graph = build_event_scope_graph(route.target_scope, candidate_messages)
    if routed_time_role:
        graph["routed_time_role"] = routed_time_role
    edges = list(graph["edges"])
    raw_claims = packet.get("claims", []) if isinstance(packet.get("claims"), list) else []
    raw_facets = packet.get("state_facets", []) if isinstance(packet.get("state_facets"), list) else []
    claims = []
    for claim in raw_claims:
        if not isinstance(claim, dict):
            continue
        claim_node = deepcopy(claim)
        claim_node["node_type"] = "Claim"
        claims.append(claim_node)
    facets = []
    for facet in raw_facets:
        if not isinstance(facet, dict):
            continue
        facet_node = deepcopy(facet)
        facet_node["node_type"] = "StateFacet"
        facets.append(facet_node)
    relations = packet.get("relations", []) if isinstance(packet.get("relations"), list) else []

    def ensure_time_node(value: object, role: object) -> Optional[str]:
        if value in {None, "", "null"}:
            return None
        node_id = time_id(str(value))
        existing_time_ids = {
            str(node.get("time_id"))
            for node in graph["nodes"].get("times", [])
            if isinstance(node, dict)
        }
        if node_id not in existing_time_ids:
            graph["nodes"].setdefault("times", []).append(
                {
                    "node_type": "Time",
                    "time_id": node_id,
                    "value": str(value),
                    "time_role": str(role or routed_time_role or "mentioned_at"),
                }
            )
        return node_id

    for claim in claims:
        edges.append(
            {
                "type": "ASSERTS",
                "from": claim.get("event_id"),
                "to": claim.get("claim_id"),
                "reason": "claim extracted from scoped event",
            }
        )
    for relation in relations:
        relation_type = str(relation.get("type", "")).upper()
        if relation_type in EDGE_TYPES:
            edges.append(
                {
                    "type": relation_type,
                    "from": relation.get("from"),
                    "to": relation.get("to"),
                    "evidence_event_ids": relation.get("evidence_event_ids", []),
                    "reason": relation.get("reason", ""),
                }
            )
    for facet in facets:
        facet_id = facet.get("facet_id")
        for claim_id in normalize_id_list(facet.get("support_claims")):
            edges.append({"type": "SUPPORTS", "from": claim_id, "to": facet_id})
        current_after = facet.get("current_after")
        if current_after:
            current_after_id = ensure_time_node(current_after, "current_after")
            edges.append({"type": "CURRENT_AFTER", "from": facet_id, "to": current_after_id})
        edges.append({"type": "CURRENT_STATE_OF", "from": facet_id, "to": route.target_scope.scope_id})
    graph["nodes"]["claims"] = claims
    graph["nodes"]["state_facets"] = facets
    graph["edges"] = edges
    return graph


def validation_needs_retry(validation: Dict[str, object]) -> bool:
    warnings = validation.get("schema_warnings", []) or []
    dropped = validation.get("dropped_invalid_event_ids", []) or []
    invariants = validation.get("state_packet_invariants", {}) or {}
    return bool(dropped or "missing_state_facets" in warnings or not invariants.get("target_scope_is_fixed", False))


def extract_claim_graph(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    graph_messages: Sequence[GroupMessage],
    claim_chunk_size: int,
    routed_time_role: Optional[str] = None,
) -> Dict[str, object]:
    system = claim_extraction_system_prompt(adapter)
    all_claims: List[Dict[str, object]] = []
    all_rejected: List[Dict[str, object]] = []
    validations: List[Dict[str, object]] = []
    message_chunks = chunks(graph_messages, claim_chunk_size)
    for chunk_index, message_chunk in enumerate(message_chunks, start=1):
        raw = client.complete_json(
            system,
            claim_extraction_user_prompt(
                question,
                route,
                message_chunk,
                chunk_index,
                len(message_chunks),
                routed_time_role,
            ),
        )
        claims, rejected, validation = normalize_claim_nodes(raw, message_chunk, chunk_index)
        all_claims.extend(claims)
        all_rejected.extend(rejected)
        validations.append(validation)
    if adapter.qtype == "knowledge_update":
        all_claims = enrich_knowledge_update_claims(question, all_claims, messages_by_id(graph_messages))
    return {
        "claims": all_claims,
        "rejected_claims": all_rejected,
        "claim_extraction_validations": validations,
    }


def source_messages_for_claims(
    claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
) -> List[GroupMessage]:
    event_ids = {
        str(claim.get("event_id", ""))
        for claim in claims
        if isinstance(claim, dict) and claim.get("event_id")
    }
    if not event_ids:
        return list(source_messages[: min(4, len(source_messages))])
    return [message for message in source_messages if message.event_id in event_ids]


def fallback_state_selection_raw(
    question: GroupQuestion,
    route: ScopeRoute,
    candidate_claims: Sequence[Dict[str, object]],
    validity_packet: Dict[str, object],
    source_messages: Sequence[GroupMessage],
    reason: str,
) -> Dict[str, object]:
    claim_by_id = {
        str(claim.get("claim_id", "")): claim
        for claim in candidate_claims
        if isinstance(claim, dict) and claim.get("claim_id")
    }
    source_by_id = messages_by_id(source_messages)
    accepted_claim_ids = [
        str(item.get("claim_id", ""))
        for item in validity_packet.get("accepted_current_claims", [])
        if isinstance(item, dict) and str(item.get("claim_id", "")) in claim_by_id
    ]
    accepted_claim_ids = list(dict.fromkeys(accepted_claim_ids))
    if accepted_claim_ids:
        support_events: List[str] = []
        values: List[str] = []
        facet_names: List[str] = []
        time_values: List[str] = []
        time_roles: List[str] = []
        for claim_id in accepted_claim_ids:
            claim = claim_by_id[claim_id]
            event_id = str(claim.get("event_id", ""))
            if event_id and event_id not in support_events:
                support_events.append(event_id)
            value = str(claim.get("value", "")).strip()
            if value and value not in values:
                values.append(value)
            facet_name = str(claim.get("facet_type") or "current_state")
            if facet_name and facet_name not in facet_names:
                facet_names.append(facet_name)
            time_value = str(claim.get("time_value") or "").strip()
            if time_value and time_value not in time_values:
                time_values.append(time_value)
            time_role = str(claim.get("time_role") or "").strip()
            if time_role and time_role not in time_roles:
                time_roles.append(time_role)
        current_after = max(
            (source_by_id[event_id].timestamp for event_id in support_events if event_id in source_by_id),
            default="",
        )
        value = "; ".join(values[:3])
        if len(values) > 3:
            value = f"{value}; ..."
        facets = [
            {
                "facet_id": "facet_1",
                "name": facet_names[0] if len(facet_names) == 1 else "current_state",
                "value": value,
                "status": "active",
                "support_claims": accepted_claim_ids,
                "support_events": support_events,
                "current_after": current_after or None,
                "time_value": time_values[0] if len(time_values) == 1 else None,
                "time_role": time_roles[0] if len(time_roles) == 1 else None,
            }
        ]
    else:
        facets = [
            {
                "facet_id": "facet_1",
                "name": "insufficient_evidence",
                "value": "There is no information available in the conversation to answer this question.",
                "status": "insufficient_evidence",
                "support_claims": [],
                "support_events": [],
                "current_after": None,
                "time_value": None,
                "time_role": None,
            }
        ]

    return {
        "state_packet": {
            "target_scope_id": route.target_scope.scope_id,
            "relations": [],
            "rejected_claims": [],
            "state_facets": facets,
        },
        "pipeline_trace": {
            "state_selection_fallback": {
                "reason": reason[:500],
                "accepted_current_claim_count": len(accepted_claim_ids),
                "fallback_source": "validity_packet",
                "case_id": question.case_id,
            }
        },
    }


def raw_support_verification_packet(raw: Dict[str, object]) -> Dict[str, object]:
    packet = raw.get("support_verification")
    return deepcopy(packet) if isinstance(packet, dict) else deepcopy(raw)


def message_list_for_event_ids(
    event_ids: Sequence[str],
    messages: Sequence[GroupMessage],
    limit: int = 18,
) -> List[GroupMessage]:
    by_id = messages_by_id(messages)
    selected: List[GroupMessage] = []
    for event_id in event_ids:
        if event_id in by_id and event_id not in {message.event_id for message in selected}:
            selected.append(by_id[event_id])
        if len(selected) >= limit:
            break
    return selected


def verify_state_facet_supports(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    repaired: Dict[str, object],
    graph_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    routed_time_role: Optional[str] = None,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    packet = repaired.get("state_packet", {}) if isinstance(repaired.get("state_packet"), dict) else {}
    facets = packet.get("state_facets", []) if isinstance(packet.get("state_facets"), list) else []
    claims = packet.get("claims", []) if isinstance(packet.get("claims"), list) else []
    claim_by_id = {
        str(claim.get("claim_id", "")): claim
        for claim in claims
        if isinstance(claim, dict) and claim.get("claim_id")
    }
    active_facets = [
        deepcopy(facet)
        for facet in facets
        if isinstance(facet, dict)
        and str(facet.get("status", "")) == "active"
        and normalize_id_list(facet.get("support_claims"))
    ]
    if not active_facets:
        return repaired, {
            "status": "skipped",
            "reason": "no_active_state_facets_with_supports",
            "active_facet_count": 0,
        }

    support_claim_ids: List[str] = []
    for facet in active_facets:
        for claim_id in normalize_id_list(facet.get("support_claims")):
            if claim_id in claim_by_id and claim_id not in support_claim_ids:
                support_claim_ids.append(claim_id)
    if not support_claim_ids:
        return repaired, {
            "status": "skipped",
            "reason": "active_state_facets_without_known_support_claims",
            "active_facet_count": len(active_facets),
        }

    support_claims = [deepcopy(claim_by_id[claim_id]) for claim_id in support_claim_ids]
    rejected_or_near_miss_claims: List[Dict[str, object]] = []
    seen_near_miss: set[str] = set()
    rejected_sources = []
    validity_packet = packet.get("validity_decisions", {}) if isinstance(packet.get("validity_decisions"), dict) else {}
    rejected_sources.extend(validity_packet.get("rejected_claims", []) if isinstance(validity_packet.get("rejected_claims"), list) else [])
    rejected_sources.extend(packet.get("rejected_claims", []) if isinstance(packet.get("rejected_claims"), list) else [])
    for rejected in rejected_sources:
        if not isinstance(rejected, dict):
            continue
        claim_id = str(rejected.get("claim_id", ""))
        if not claim_id or claim_id in support_claim_ids or claim_id in seen_near_miss or claim_id not in claim_by_id:
            continue
        near_miss = deepcopy(claim_by_id[claim_id])
        near_miss["validity_status"] = str(rejected.get("validity") or rejected.get("reason") or "rejected")
        near_miss["rejection_reason"] = str(rejected.get("reason") or "")
        rejected_or_near_miss_claims.append(near_miss)
        seen_near_miss.add(claim_id)
        if len(rejected_or_near_miss_claims) >= 12:
            break

    event_ids: List[str] = []
    for claim in list(support_claims) + list(rejected_or_near_miss_claims):
        event_id = str(claim.get("event_id", ""))
        if event_id and event_id not in event_ids:
            event_ids.append(event_id)
    source_messages = message_list_for_event_ids(event_ids, scope_messages or graph_messages)

    try:
        raw = client.complete_json(
            support_verification_system_prompt(adapter),
            support_verification_user_prompt(
                question,
                adapter,
                route,
                active_facets,
                support_claims,
                rejected_or_near_miss_claims,
                source_messages,
                routed_time_role,
            ),
        )
    except ValueError as exc:
        return repaired, {
            "status": "parse_error",
            "reason": str(exc)[:500],
            "active_facet_count": len(active_facets),
            "support_claim_count": len(support_claim_ids),
        }

    verification_packet = raw_support_verification_packet(raw)
    raw_decisions = verification_packet.get("facet_decisions", [])
    decisions = raw_decisions if isinstance(raw_decisions, list) else []
    decisions_by_facet: Dict[str, Dict[str, object]] = {}
    for item in decisions:
        if not isinstance(item, dict):
            continue
        facet_id = str(item.get("facet_id", ""))
        if facet_id:
            decisions_by_facet[facet_id] = item

    updated = deepcopy(repaired)
    updated_packet = updated.get("state_packet", {}) if isinstance(updated.get("state_packet"), dict) else {}
    updated_facets = updated_packet.get("state_facets", []) if isinstance(updated_packet.get("state_facets"), list) else []
    times_by_id = message_times_by_id(scope_messages or graph_messages)
    removed_supports: Dict[str, Dict[str, str]] = {}
    demoted_facets: List[str] = []
    narrowed_facets: List[str] = []

    for facet in updated_facets:
        if not isinstance(facet, dict) or str(facet.get("status", "")) != "active":
            continue
        facet_id = str(facet.get("facet_id", ""))
        decision = decisions_by_facet.get(facet_id)
        if not decision:
            continue
        original_supports = [claim_id for claim_id in normalize_id_list(facet.get("support_claims")) if claim_id in claim_by_id]
        if not original_supports:
            continue
        decision_label = str(decision.get("decision", "")).strip().lower()
        if decision_label == "supported":
            supported_claim_ids = [
                claim_id
                for claim_id in normalize_id_list(decision.get("supported_claim_ids"))
                if claim_id in original_supports
            ]
            if not supported_claim_ids:
                supported_claim_ids = list(original_supports)
        else:
            supported_claim_ids = []
        rejected_supports = decision.get("rejected_supports", [])
        rejection_by_claim: Dict[str, Dict[str, str]] = {}
        if isinstance(rejected_supports, list):
            for rejected in rejected_supports:
                if not isinstance(rejected, dict):
                    continue
                claim_id = str(rejected.get("claim_id", ""))
                if claim_id not in original_supports:
                    continue
                rejection_by_claim[claim_id] = {
                    "validity": str(rejected.get("validity") or "insufficient_direct_support"),
                    "reason": str(rejected.get("reason") or decision.get("reason") or "support_verification_rejected"),
                }
        for claim_id in original_supports:
            if claim_id not in supported_claim_ids:
                removed_supports[claim_id] = rejection_by_claim.get(
                    claim_id,
                    {
                        "validity": "insufficient_direct_support",
                        "reason": str(decision.get("reason") or "support_verification_rejected"),
                    },
                )
        if not supported_claim_ids:
            facet["status"] = "insufficient_evidence"
            facet["name"] = "insufficient_evidence"
            facet["value"] = "There is no information available in the conversation to answer this question."
            facet["support_claims"] = []
            facet["support_events"] = []
            facet["current_after"] = None
            facet["time_value"] = None
            facet["time_role"] = None
            demoted_facets.append(facet_id)
            continue
        if supported_claim_ids != original_supports:
            support_events: List[str] = []
            support_values: List[str] = []
            for claim_id in supported_claim_ids:
                claim = claim_by_id[claim_id]
                event_id = str(claim.get("event_id", ""))
                if event_id and event_id not in support_events:
                    support_events.append(event_id)
                value = str(claim.get("value", "")).strip()
                if value and value not in support_values:
                    support_values.append(value)
            facet["support_claims"] = supported_claim_ids
            facet["support_events"] = support_events
            if support_values:
                facet["value"] = "; ".join(support_values[:3])
            facet["current_after"] = max((times_by_id.get(event_id, "") for event_id in support_events), default="") or None
            narrowed_facets.append(facet_id)

    if not removed_supports and not demoted_facets and not narrowed_facets:
        trace = {
            "status": "ok",
            "changed": False,
            "active_facet_count": len(active_facets),
            "support_claim_count": len(support_claim_ids),
            "verified_facet_count": len(decisions_by_facet),
            "raw_output": raw,
        }
        return repaired, trace

    remaining_active_supports: set[str] = set()
    for facet in updated_facets:
        if isinstance(facet, dict) and str(facet.get("status", "")) == "active":
            remaining_active_supports.update(normalize_id_list(facet.get("support_claims")))
    globally_removed = {claim_id for claim_id in removed_supports if claim_id not in remaining_active_supports}

    validity_decisions = updated_packet.get("validity_decisions", {})
    if not isinstance(validity_decisions, dict):
        validity_decisions = {}
        updated_packet["validity_decisions"] = validity_decisions
    accepted = validity_decisions.get("accepted_current_claims", [])
    if isinstance(accepted, list) and globally_removed:
        validity_decisions["accepted_current_claims"] = [
            item
            for item in accepted
            if not (isinstance(item, dict) and str(item.get("claim_id", "")) in globally_removed)
        ]
    elif not isinstance(accepted, list):
        validity_decisions["accepted_current_claims"] = []

    def append_rejection(target: Dict[str, object], claim_id: str, rejection: Dict[str, str]) -> None:
        raw_rejected = target.get("rejected_claims", [])
        rejected_list = raw_rejected if isinstance(raw_rejected, list) else []
        if any(isinstance(item, dict) and str(item.get("claim_id", "")) == claim_id for item in rejected_list):
            target["rejected_claims"] = rejected_list
            return
        claim = claim_by_id.get(claim_id, {})
        rejected_list.append(
            {
                "claim_id": claim_id,
                "event_id": str(claim.get("event_id", "")),
                "validity": rejection.get("validity", "insufficient_direct_support"),
                "reason": rejection.get("reason", "support_verification_rejected"),
            }
        )
        target["rejected_claims"] = rejected_list

    for claim_id in sorted(globally_removed):
        append_rejection(validity_decisions, claim_id, removed_supports[claim_id])
        append_rejection(updated_packet, claim_id, removed_supports[claim_id])

    trace = {
        "status": "ok",
        "changed": True,
        "active_facet_count": len(active_facets),
        "support_claim_count": len(support_claim_ids),
        "verified_facet_count": len(decisions_by_facet),
        "removed_support_count": len(removed_supports),
        "globally_removed_support_count": len(globally_removed),
        "demoted_facet_ids": demoted_facets,
        "narrowed_facet_ids": narrowed_facets,
        "removed_support_claim_ids": sorted(removed_supports),
        "raw_output": raw,
    }
    return updated, trace


def complete_graph_state_packet_from_claim_graph(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    claim_graph: Dict[str, object],
    graph_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    claim_top_k: int = 24,
    routed_time_role: Optional[str] = None,
    claim_source: str = "llm_claim_extraction",
    claim_chunk_size: Optional[int] = None,
) -> Dict[str, object]:
    if adapter.qtype == "knowledge_update":
        enriched_claims = enrich_knowledge_update_claims(
            question,
            claim_graph.get("claims", []),
            messages_by_id(graph_messages),
        )
        claim_graph = {
            **claim_graph,
            "claims": enriched_claims,
            "claim_extraction_validations": list(claim_graph.get("claim_extraction_validations", []))
            + [
                {
                    "mode": "query_time_knowledge_update_enrichment",
                    "source": claim_source,
                    "input_claim_count": len(claim_graph.get("claims", [])),
                    "output_claim_count": len(enriched_claims),
                }
            ],
        }
    selected_claims, source_messages, claim_selection = select_claim_candidates(
        question,
        adapter,
        claim_graph.get("claims", []),
        graph_messages,
        claim_top_k,
        routed_time_role,
    )
    source_messages = source_messages or list(graph_messages[: min(len(graph_messages), 8)])
    validity_packet, validity_validation, validity_raw = complete_claim_validity_packet(
        client,
        question,
        adapter,
        route,
        selected_claims,
        source_messages,
        scope_messages,
        routed_time_role,
    )
    validity_status_by_claim = {
        str(item.get("claim_id", "")): "current_valid"
        for item in validity_packet.get("accepted_current_claims", [])
        if isinstance(item, dict)
    }
    for item in validity_packet.get("rejected_claims", []):
        if isinstance(item, dict):
            validity_status_by_claim.setdefault(str(item.get("claim_id", "")), str(item.get("validity") or "rejected"))
    selected_claims_for_state = []
    for claim in selected_claims:
        item = deepcopy(claim)
        claim_id = str(item.get("claim_id", ""))
        if claim_id in validity_status_by_claim:
            item["validity_status"] = validity_status_by_claim[claim_id]
        selected_claims_for_state.append(item)
    system = state_selection_system_prompt(adapter)
    state_selection_recovery: Dict[str, object] = {}
    try:
        raw = client.complete_json(
            system,
            state_selection_user_prompt(
                question,
                adapter,
                route,
                selected_claims_for_state,
                validity_packet,
                source_messages,
                scope_messages,
                routed_time_role,
            ),
        )
    except ValueError as exc:
        retry_claims = [
            claim
            for claim in selected_claims_for_state
            if str(claim.get("validity_status", "")) == "current_valid"
        ]
        if not retry_claims:
            retry_claims = selected_claims_for_state[: min(8, len(selected_claims_for_state))]
        retry_source_messages = source_messages_for_claims(retry_claims, source_messages)
        state_selection_recovery = {
            "initial_parse_error": str(exc)[:500],
            "retry_claim_count": len(retry_claims),
            "retry_source_event_count": len(retry_source_messages),
        }
        try:
            raw = client.complete_json(
                system,
                state_selection_user_prompt(
                    question,
                    adapter,
                    route,
                    retry_claims,
                    validity_packet,
                    retry_source_messages,
                    scope_messages,
                    routed_time_role,
                    validation_error={
                        "error": str(exc)[:500],
                        "retry_instruction": (
                            "Return compact valid JSON only. Include state_packet.state_facets and only "
                            "relations or rejected_claims newly required for StateFacet selection."
                        ),
                    },
                ),
            )
            state_selection_recovery["retry_succeeded"] = True
        except ValueError as retry_exc:
            state_selection_recovery["retry_succeeded"] = False
            state_selection_recovery["fallback_used"] = True
            state_selection_recovery["retry_parse_error"] = str(retry_exc)[:500]
            raw = fallback_state_selection_raw(
                question,
                route,
                selected_claims_for_state,
                validity_packet,
                retry_source_messages,
                reason=f"state_selection_json_parse_failed:{exc}; retry_failed:{retry_exc}",
            )
    state_packet = raw_state_packet(raw)
    merged_relations: List[Dict[str, object]] = []
    seen_relations = set()
    for relation in list(validity_packet.get("relations", [])) + list(state_packet.get("relations", [])):
        if not isinstance(relation, dict):
            continue
        key = (str(relation.get("type", "")).upper(), str(relation.get("from", "")), str(relation.get("to", "")))
        if key in seen_relations:
            continue
        seen_relations.add(key)
        merged_relations.append(deepcopy(relation))
    merged_raw = deepcopy(raw)
    merged_raw["state_packet"] = {
        "target_scope_id": state_packet.get("target_scope_id") or route.target_scope.scope_id,
        "candidate_events": [message.event_id for message in graph_messages],
        "claims": claim_graph.get("claims", []),
        "validity_decisions": validity_packet,
        "relations": merged_relations,
        "rejected_claims": list(claim_graph.get("rejected_claims", [])) + list(validity_packet.get("rejected_claims", [])),
        "state_facets": state_packet.get("state_facets", []),
    }
    rejected_from_state = state_packet.get("rejected_claims", [])
    if isinstance(rejected_from_state, list):
        merged_raw["state_packet"]["rejected_claims"].extend(rejected_from_state)
    repaired, validation = validate_and_repair_graph_packet(
        merged_raw,
        question,
        route,
        graph_messages,
        scope_messages,
        routed_time_role,
    )
    support_repaired, support_verification_trace = verify_state_facet_supports(
        client,
        question,
        adapter,
        route,
        repaired,
        graph_messages,
        scope_messages,
        routed_time_role,
    )
    if support_verification_trace.get("changed"):
        existing_trace = repaired.get("pipeline_trace", {}) if isinstance(repaired.get("pipeline_trace"), dict) else {}
        support_repaired["pipeline_trace"] = {
            **existing_trace,
            "support_verification": support_verification_trace,
        }
        repaired, support_validation = validate_and_repair_graph_packet(
            support_repaired,
            question,
            route,
            graph_messages,
            scope_messages,
            routed_time_role,
        )
        validation = {
            **validation,
            "support_verification_validation": support_validation,
        }
    else:
        repaired = support_repaired
    trace = repaired.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["support_verification"] = support_verification_trace
    trace["claim_graph_build"] = {
        "graph_event_count": len(graph_messages),
        "claim_chunk_size": max(1, claim_chunk_size) if claim_chunk_size else None,
        "claim_source": claim_source,
        "extracted_claim_count": len(claim_graph.get("claims", [])),
        "claim_extraction_validations": claim_graph.get("claim_extraction_validations", []),
        "routed_time_role": routed_time_role,
    }
    trace["claim_graph_selection"] = claim_selection
    trace["claim_validity"] = {
        "accepted_current_claim_count": len(validity_packet.get("accepted_current_claims", [])),
        "rejected_claim_count": len(validity_packet.get("rejected_claims", [])),
        "relation_count": len(validity_packet.get("relations", [])),
        "validation": validity_validation,
        "raw_output": validity_raw,
    }
    if state_selection_recovery:
        trace["state_selection_recovery"] = state_selection_recovery
    trace["time_role_route"] = {"time_role": routed_time_role} if routed_time_role else None
    repaired["pipeline_trace"] = trace
    return repaired


def complete_graph_state_packet(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    graph_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    claim_chunk_size: int = 16,
    claim_top_k: int = 24,
    routed_time_role: Optional[str] = None,
) -> Dict[str, object]:
    claim_graph = extract_claim_graph(client, question, adapter, route, graph_messages, claim_chunk_size, routed_time_role)
    return complete_graph_state_packet_from_claim_graph(
        client,
        question,
        adapter,
        route,
        claim_graph,
        graph_messages,
        scope_messages,
        claim_top_k,
        routed_time_role,
        claim_source="llm_claim_extraction",
        claim_chunk_size=claim_chunk_size,
    )


def complete_graph_state_packet_from_claims(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    claims: Sequence[Dict[str, object]],
    graph_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    claim_top_k: int = 24,
    routed_time_role: Optional[str] = None,
    rejected_claims: Optional[Sequence[Dict[str, object]]] = None,
    claim_source: str = "prebuilt_domain_graph",
) -> Dict[str, object]:
    claim_graph = {
        "claims": [deepcopy(claim) for claim in claims],
        "rejected_claims": [deepcopy(claim) for claim in rejected_claims or []],
        "claim_extraction_validations": [
            {
                "source": claim_source,
                "mode": "prebuilt_claim_graph",
                "claim_count": len(claims),
                "event_count": len(graph_messages),
            }
        ],
    }
    return complete_graph_state_packet_from_claim_graph(
        client,
        question,
        adapter,
        route,
        claim_graph,
        graph_messages,
        scope_messages,
        claim_top_k,
        routed_time_role,
        claim_source=claim_source,
        claim_chunk_size=None,
    )


def state_facets_from_locked(locked_raw: Dict[str, object]) -> List[Dict[str, object]]:
    packet = locked_raw.get("state_packet", {}) if isinstance(locked_raw.get("state_packet"), dict) else {}
    facets = packet.get("state_facets", []) if isinstance(packet, dict) else []
    return [facet for facet in facets if isinstance(facet, dict)]


def default_year_from_facets(facets: Sequence[Dict[str, object]]) -> Optional[int]:
    for facet in facets:
        current_after = str(facet.get("current_after") or "")
        match = ISO_DATE_RE.search(current_after)
        if match:
            return int(match.group(0)[:4])
    return None


def parse_month_day(match: re.Match[str], default_year: Optional[int]) -> Optional[str]:
    month, day, year = match.groups()
    chosen_year = int(year) if year else default_year
    if not chosen_year:
        return None
    return f"{chosen_year}-{MONTHS[month.lower()]}-{int(day):02d}"


def next_weekday_iso(base_iso: str, weekday_name: str, allow_same_day: bool = True) -> Optional[str]:
    base_match = ISO_DATE_RE.search(base_iso)
    if not base_match:
        return None
    base = date.fromisoformat(base_match.group(0))
    target = WEEKDAY_INDEX[weekday_name.lower()]
    delta = (target - base.weekday()) % 7
    if delta == 0 and not allow_same_day:
        delta = 7
    return (base + timedelta(days=delta)).isoformat()


def date_candidates_from_text(text: object, default_year: Optional[int], base_iso: str = "") -> List[str]:
    raw = str(text or "")
    lowered = raw.lower()
    candidates: List[str] = []
    for match in ISO_DATE_RE.finditer(raw):
        value = match.group(0)
        if value not in candidates:
            candidates.append(value)
    for match in MONTH_DAY_RE.finditer(raw):
        value = parse_month_day(match, default_year)
        if value and value not in candidates:
            candidates.append(value)
    for match in WEEKDAY_RE.finditer(raw):
        value = next_weekday_iso(base_iso, match.group(1))
        if value and value not in candidates:
            candidates.append(value)
    base_match = ISO_DATE_RE.search(base_iso)
    if base_match:
        base_date = date.fromisoformat(base_match.group(0))
        if DAY_AFTER_TOMORROW_RE.search(lowered):
            value = (base_date + timedelta(days=2)).isoformat()
            if value not in candidates:
                candidates.append(value)
        elif re.search(r"\btomorrow\b", lowered):
            value = (base_date + timedelta(days=1)).isoformat()
            if value not in candidates:
                candidates.append(value)
        elif re.search(r"\b(today|tonight|eod|end of day)\b", lowered):
            value = base_date.isoformat()
            if value not in candidates:
                candidates.append(value)
    return candidates


def normalize_date_answer(
    question: GroupQuestion,
    answer: str,
    facets: Sequence[Dict[str, object]],
    routed_time_role: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    question_text = question.question.lower()
    date_question = (
        "yyyy-mm-dd" in question_text
        or "by what date" in question_text
        or "due date" in question_text
        or bool(re.search(r"\b(date|deadline)\b", question_text))
    )
    if not date_question:
        return None, None
    default_year = default_year_from_facets(facets)
    answer_candidates = date_candidates_from_text(answer, default_year)
    if answer_candidates:
        return answer_candidates[0], "date_answer_normalized"
    for facet in facets:
        if str(facet.get("status", "")) != "active":
            continue
        facet_time_role = str(facet.get("time_role") or "")
        time_value = str(facet.get("time_value") or "")
        if routed_time_role and facet_time_role and facet_time_role != routed_time_role:
            continue
        candidates = date_candidates_from_text(time_value, default_year, str(facet.get("current_after") or ""))
        if candidates:
            return candidates[0], "date_facet_time_value_normalized"
    for facet in facets:
        if str(facet.get("status", "")) != "active":
            continue
        text = " ".join(str(facet.get(key, "")) for key in ("name", "value"))
        candidates = date_candidates_from_text(text, default_year, str(facet.get("current_after") or ""))
        if candidates:
            return candidates[0], "date_facet_normalized"
        if routed_time_role in {"occurred_at", "updated_at"}:
            current_after_candidates = date_candidates_from_text(facet.get("current_after"), default_year)
            if current_after_candidates:
                return current_after_candidates[0], "date_facet_current_after_normalized"
    return None, None


def normalize_field_answer(question: GroupQuestion, answer: str, facets: Sequence[Dict[str, object]]) -> Tuple[Optional[str], Optional[str]]:
    question_text = question.question.lower()
    if "what fields" not in question_text and "which fields" not in question_text:
        return None, None
    texts = [answer] + [str(facet.get("value", "")) for facet in facets if facet.get("status") == "active"]
    for text in texts:
        match = re.search(r"\bfields?\s+for\s+(.+?)\s+should\b", text, re.I)
        if match:
            return match.group(1).strip(" ."), "field_list_extracted"
        match = re.search(r"\bfields?\s+(?:are|include)\s+(.+?)(?:\.|$)", text, re.I)
        if match:
            return match.group(1).strip(" ."), "field_list_extracted"
    return None, None


def normalize_status_answer(question: GroupQuestion, answer: str, facets: Sequence[Dict[str, object]]) -> Tuple[Optional[str], Optional[str]]:
    question_text = question.question.lower()
    answer_text = answer.lower()
    if "freeze status" in question_text:
        if any(term in answer_text for term in ("frozen", "freeze", "locked")) and not any(
            term in answer_text for term in ("not frozen", "not locked", "unfrozen")
        ):
            return "frozen", "freeze_status_normalized"
    if "status" not in question_text:
        return None, None
    texts = [answer] + [str(facet.get("value", "")) for facet in facets if facet.get("status") == "active"]
    for text in texts:
        lowered = text.lower()
        if "incomplete" in lowered or "not complete" in lowered:
            return "incomplete", "status_value_extracted"
        if "complete" in lowered or "completed" in lowered:
            return "complete", "status_value_extracted"
        if "frozen" in lowered or "locked" in lowered:
            return "frozen", "status_value_extracted"
    return None, None


def normalize_user_implicit_answer(
    question: GroupQuestion,
    answer: str,
    adapter: TaskAdapter,
    locked_raw: Optional[Dict[str, object]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    if adapter.qtype != "user_implicit":
        return None, None
    question_text = question.question.strip()
    answer_text = answer.strip()
    lowered_answer = answer_text.lower()
    if re.search(r"\bwhat do i need signed off\b", question_text, re.I):
        texts = [answer_text]
        if locked_raw:
            packet = locked_raw.get("state_packet", {}) if isinstance(locked_raw.get("state_packet"), dict) else {}
            texts.extend(
                str(facet.get("value", ""))
                for facet in packet.get("state_facets", [])
                if isinstance(facet, dict)
            )
            texts.extend(
                str(claim.get("value", ""))
                for claim in packet.get("claims", [])
                if isinstance(claim, dict)
            )
        for text in texts:
            match = re.search(
                r"\b(?:need|needs|missing)?\s*(?:a\s+)?signed[- ]off\s+(.+?)(?:\s+before|\s+to\b|[,.;]|$)",
                text,
                re.I,
            )
            if match:
                item = re.sub(r"\s+", " ", match.group(1)).strip(" .").lower()
                item = re.split(r"\s+blocks?\b|\s+is required\b|\s+required\b", item, maxsplit=1, flags=re.I)[0].strip()
                if item:
                    return f"a signed-off {item}", "user_implicit_signed_off_item_extracted"
            match = re.search(r"\b([A-Za-z][A-Za-z\s/-]*?\brule)\s+sign[- ]off\b", text, re.I)
            if match:
                item = re.sub(r"\s+", " ", match.group(1)).strip(" .").lower()
                if item:
                    return f"a signed-off {item}", "user_implicit_signed_off_item_extracted"
    ask_match = re.search(r"\bwhich teams am i asking to\s+(.+?)(?:\s+in\s+the\b|\?)", question_text, re.I)
    if ask_match and not any(verb in lowered_answer for verb in ("ask", "asking", "pressure-test", "pressure test")):
        action = ask_match.group(1).strip(" ?")
        return f"{answer_text} are being asked to {action}.", "user_implicit_action_restored"
    if re.search(r"\bwhat (?:is|are).*\bblocking me\b|\bwhat is the blocker i\b", question_text, re.I):
        first_sentence = re.split(r"(?<=[.!?])\s+", answer_text, maxsplit=1)[0]
        blocker = re.split(r",?\s+so\s+", first_sentence, maxsplit=1, flags=re.I)[0].strip(" .")
        if blocker and blocker != answer_text:
            return blocker, "blocker_clause_extracted"
    return None, None


def normalize_answer_for_task(
    question: GroupQuestion,
    adapter: TaskAdapter,
    answer: str,
    locked_raw: Dict[str, object],
) -> Tuple[str, Optional[str]]:
    answer_text = answer.strip()
    facets = state_facets_from_locked(locked_raw)
    trace = locked_raw.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    time_role_route = trace.get("time_role_route", {})
    routed_time_role = None
    if isinstance(time_role_route, dict):
        routed_time_role = str(time_role_route.get("time_role") or "") or None
    normalized, method = normalize_date_answer(question, answer_text, facets, routed_time_role)
    if normalized:
        return normalized, method
    normalized, method = normalize_field_answer(question, answer_text, facets)
    if normalized:
        return normalized, method
    normalized, method = normalize_status_answer(question, answer_text, facets)
    if normalized:
        return normalized, method
    normalized, method = normalize_user_implicit_answer(question, answer_text, adapter, locked_raw)
    if normalized:
        return normalized, method
    return answer_text, None


def compose_answer(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    locked_raw: Dict[str, object],
) -> Dict[str, object]:
    composer_raw = client.complete_json(composer_system_prompt(adapter), composer_user_prompt(question, locked_raw))
    answer = str(composer_raw.get("answer", "")).strip()
    normalized_answer, normalization = normalize_answer_for_task(question, adapter, answer, locked_raw)
    merged = deepcopy(locked_raw)
    merged["answer"] = normalized_answer
    trace = merged.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["composer_output"] = composer_raw
    if normalization:
        trace["answer_normalization"] = {
            "method": normalization,
            "raw_answer": answer,
            "normalized_answer": normalized_answer,
        }
    merged["pipeline_trace"] = trace
    return merged


def run_graph_scope_state_packet(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    graph_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    claim_chunk_size: int = 16,
    claim_top_k: int = 24,
    routed_time_role: Optional[str] = None,
    composer_client: Optional[LLMClient] = None,
) -> Dict[str, object]:
    locked_raw = complete_graph_state_packet(
        client,
        question,
        adapter,
        route,
        graph_messages,
        scope_messages,
        claim_chunk_size,
        claim_top_k,
        routed_time_role,
    )
    return compose_answer(composer_client or client, question, adapter, locked_raw)


def dry_run_graph_scope_state_packet(
    question: GroupQuestion,
    route: ScopeRoute,
    candidate_messages: Sequence[GroupMessage],
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    routed_time_role: Optional[str] = None,
) -> Dict[str, object]:
    packet = {
        "target_scope_id": route.target_scope.scope_id,
        "candidate_events": [message.event_id for message in candidate_messages],
        "claims": [],
        "relations": [],
        "rejected_claims": [],
        "state_facets": [],
    }
    return {
        "answer": "",
        "state_packet": packet,
        "graph_trace": build_graph_trace(route, scope_messages or candidate_messages, packet, routed_time_role),
        "pipeline_trace": {
            "pipeline": "graph_scope_state_packet",
            "dry_run": True,
            "case_id": question.case_id,
            "time_role_route": {"time_role": routed_time_role} if routed_time_role else None,
            "in_scope_episode_event_count": len(scope_messages or candidate_messages),
            "episode_event_context_count": len(candidate_messages),
        },
    }


def run_bm25_message_baseline(
    client: LLMClient,
    question: GroupQuestion,
    candidate_messages: Sequence[GroupMessage],
) -> Dict[str, object]:
    raw = client.complete_json(direct_baseline_system_prompt(), direct_baseline_user_prompt(question, candidate_messages))
    return {
        "answer": str(raw.get("answer", "")).strip(),
        "raw_output": raw,
        "pipeline_trace": {
            "pipeline": "bm25_message",
            "candidate_events": [message.event_id for message in candidate_messages],
        },
    }

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pipeline.external.groupmembench.adapters.base import TaskAdapter
from pipeline.external.groupmembench.loader import GroupMessage, GroupQuestion, ScopeNode, filter_messages_for_scope, scope_id_for
from pipeline.external.groupmembench.routing import ScopeRoute, score_scope, with_source_anchor


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
DATE_RE = re.compile(r"\b(?:20\d{2}-\d{2}-\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", re.I)
RELATIVE_TIME_RE = re.compile(r"\b(?:today|tomorrow|tonight|eod|end of day|friday|thursday|wednesday|tuesday|monday|saturday|sunday)\b", re.I)
DEFAULT_EMBEDDING_MESSAGE_SCORE_WEIGHT = 6.0
DEFAULT_EMBEDDING_SCOPE_SCORE_WEIGHT = 6.0


def tokenized(text: object) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def document_text(message: GroupMessage, adapter: TaskAdapter) -> str:
    parts = [
        message.content,
        message.author,
        message.role,
        message.phase_name,
        message.topic,
    ]
    if adapter.alias_normalization_required:
        parts.extend(alias_expansions(message.content))
    return " ".join(part for part in parts if part)


def alias_expansions(text: str) -> List[str]:
    lowered = text.lower()
    expansions: List[str] = []
    finance_aliases = ("finance ops", "financial operations", "operational finance", "finance workflows")
    if any(alias in lowered for alias in finance_aliases):
        expansions.extend(finance_aliases)
    legal_aliases = ("legal", "compliance", "risk", "controls")
    if any(alias in lowered for alias in legal_aliases):
        expansions.extend(legal_aliases)
    return expansions


def bm25_scores(documents: Sequence[str], query: str) -> List[float]:
    doc_terms = [Counter(tokenized(document)) for document in documents]
    query_terms = Counter(tokenized(query))
    if not query_terms:
        return [0.0 for _ in documents]
    doc_count = len(doc_terms)
    avg_len = sum(sum(counter.values()) for counter in doc_terms) / max(doc_count, 1)
    df: Counter[str] = Counter()
    for counter in doc_terms:
        df.update(counter.keys())
    k1 = 1.5
    b = 0.75
    scores: List[float] = []
    for terms in doc_terms:
        doc_len = sum(terms.values()) or 1
        score = 0.0
        for term, query_count in query_terms.items():
            tf = terms.get(term, 0)
            if tf <= 0:
                continue
            idf = math.log(1 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1e-9))
            score += idf * (tf * (k1 + 1) / denom) * query_count
        scores.append(score)
    return scores


def source_anchor_boost(message: GroupMessage, source_anchor: str) -> float:
    if not source_anchor:
        return 0.0
    boost = 0.0
    if message.author == source_anchor:
        boost += 5.0
    if source_anchor in message.content or f"@{source_anchor}" in message.content:
        boost += 3.0
    return boost


def unique_messages(messages: Iterable[GroupMessage]) -> List[GroupMessage]:
    seen = set()
    output: List[GroupMessage] = []
    for message in messages:
        if message.event_id in seen:
            continue
        seen.add(message.event_id)
        output.append(message)
    return output


def chronological(messages: Iterable[GroupMessage]) -> List[GroupMessage]:
    return sorted(unique_messages(messages), key=lambda item: (item.timestamp, item.event_id))


def question_target_terms(question: GroupQuestion) -> set[str]:
    generic = {
        "what",
        "which",
        "when",
        "date",
        "deadline",
        "yyyy",
        "mm",
        "dd",
        "current",
        "approach",
        "using",
        "team",
        "members",
        "projectmanager",
        "project",
        "phase",
        "process",
        "transaction",
        "monitoring",
        "framework",
    }
    important_short_terms = {
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
    return {
        token
        for token in tokenized(question.question)
        if (len(token) >= 4 or token in important_short_terms) and token not in generic
    }


def target_overlap_count(message: GroupMessage, question: GroupQuestion) -> int:
    target_terms = question_target_terms(question)
    if not target_terms:
        return 0
    content_terms = set(tokenized(message.content))
    return len(target_terms & content_terms)


def query_state_target(question: GroupQuestion, adapter: TaskAdapter) -> Tuple[str, Tuple[str, ...]]:
    terms = tuple(sorted(question_target_terms(question)))
    label_terms = terms[:8] or (adapter.qtype,)
    label = f"{adapter.qtype}:{'_'.join(label_terms)}"
    return label, terms


def with_query_state_scope(scope: ScopeNode, question: GroupQuestion, adapter: TaskAdapter) -> ScopeNode:
    state_target, state_target_terms = query_state_target(question, adapter)
    base_scope_id = scope.base_scope_id or scope_id_for(
        scope.domain,
        scope.channel,
        scope.phase_name,
        scope.topic,
        scope.source_anchor,
    )
    return ScopeNode(
        scope_id=scope_id_for(
            scope.domain,
            scope.channel,
            scope.phase_name,
            scope.topic,
            scope.source_anchor,
            state_target,
        ),
        domain=scope.domain,
        channel=scope.channel,
        phase_name=scope.phase_name,
        topic=scope.topic,
        scope_type="query_state_scope",
        source_anchor=scope.source_anchor,
        state_target=state_target,
        state_target_terms=state_target_terms,
        base_scope_id=base_scope_id,
        reply_thread=scope.reply_thread,
        event_count=scope.event_count,
    )


def task_cue_boost(
    message: GroupMessage,
    question: GroupQuestion,
    adapter: TaskAdapter,
    routed_time_role: Optional[str] = None,
) -> Tuple[float, List[str]]:
    content = message.content.lower()
    question_text = question.question.lower()
    boost = 0.0
    reasons: List[str] = []

    asks_instruction_date = "instructed" in question_text or "asked to" in question_text or "were team members asked" in question_text
    overlap = target_overlap_count(message, question)
    target_term_count = len(question_target_terms(question))
    overlap_threshold = 1 if target_term_count <= 2 else min(3, target_term_count)
    if (
        (routed_time_role is None or adapter.qtype == "knowledge_update")
        and adapter.qtype in {"temporal", "knowledge_update", "multi_hop"}
        and overlap >= overlap_threshold
    ):
        boost += min(6.0, 1.0 * overlap)
        reasons.append("target_term_overlap")
    if routed_time_role in {"deadline_at", "planned_for"}:
        if (DATE_RE.search(message.content) or RELATIVE_TIME_RE.search(message.content)) and overlap:
            boost += min(8.0, 2.0 + 0.9 * overlap)
            reasons.append(f"{routed_time_role}_date_content_cues")
        deadline_terms = ("by ", "deadline", "due", "target", "eod", "end of day", "cutoff", "cut-off")
        if routed_time_role == "deadline_at" and any(term in content for term in deadline_terms) and overlap:
            boost += min(5.0, 1.5 + 0.7 * overlap)
            reasons.append("deadline_at_target_overlap")
    elif routed_time_role == "occurred_at" and asks_instruction_date:
        instruction_terms = ("@projectmanager", "projectmanager", "please", "can we", "i'd", "asked", "send", "lock", "freeze")
        if any(term in content for term in instruction_terms) and overlap:
            boost += min(7.0, 2.0 + 0.8 * overlap)
            reasons.append("occurred_at_instruction_event_cues")
    elif routed_time_role == "mentioned_at":
        if (DATE_RE.search(message.content) or RELATIVE_TIME_RE.search(message.content)) and overlap:
            boost += min(5.0, 1.5 + 0.6 * overlap)
            reasons.append("mentioned_at_date_cues")

    if adapter.qtype in {"multi_hop", "temporal"} and not asks_instruction_date and (
        "date" in question_text or "deadline" in question_text or "yyyy-mm-dd" in question_text
    ):
        if DATE_RE.search(message.content) or RELATIVE_TIME_RE.search(message.content):
            boost += 3.0
            reasons.append("date_or_deadline_cue")

    if adapter.qtype == "temporal" and asks_instruction_date:
        instruction_terms = ("@projectmanager", "projectmanager", "please", "can we", "i'd want", "lock")
        target_terms = ("primary", "backup", "handoff trigger", "rollback owner", "rollback")
        instruction_hits = [term for term in instruction_terms if term in content]
        target_hits = [term for term in target_terms if term in content]
        if instruction_hits and target_hits:
            boost += min(6.0, 1.5 * len(instruction_hits) + 1.0 * len(target_hits))
            reasons.append("instruction_occurred_at_cues")

    if adapter.qtype == "knowledge_update":
        update_terms = (
            "current",
            "now",
            "new ask",
            "new plan",
            "new path",
            "change:",
            "proposed change",
            "revisit",
            "revise",
            "no longer works",
            "instead",
            "widen",
            "widening",
            "expand",
            "include",
            "fold",
            "approval",
            "scope",
            "decision gate",
            "sign-off",
            "signoff",
            "lock",
            "freeze",
            "final",
            "late-stage",
            "fallback",
            "exception",
            "edge case",
            "boundary",
        )
        hits = [term for term in update_terms if term in content]
        if hits:
            boost += min(7.0, 1.15 * len(hits))
            reasons.append("knowledge_update_cues:" + ",".join(hits[:5]))

    if adapter.qtype == "term_ambiguity":
        if "freeze status" in question_text or "frozen" in question_text:
            freeze_terms = ("frozen", "freeze", "locked", "versioned pack", "hash", "controlled change")
            hits = [term for term in freeze_terms if term in content]
            if hits:
                boost += min(8.0, 2.0 * len(hits))
                reasons.append("freeze_status_cues:" + ",".join(hits[:5]))
        if adapter.alias_normalization_required:
            alias_hits = [term for term in ("finance ops", "financial operations", "finance workflows") if term in content]
            if alias_hits:
                boost += 3.0
                reasons.append("alias_cues:" + ",".join(alias_hits[:3]))

    return boost, reasons


def knowledge_change_anchor_score(message: GroupMessage) -> float:
    content = message.content.lower()
    weighted_terms = {
        "new ask": 4.0,
        "new plan": 6.0,
        "new path": 6.0,
        "change:": 6.0,
        "proposed change": 5.0,
        "revisit": 4.0,
        "revise": 4.0,
        "no longer works": 5.0,
        "old \"": 3.0,
        "old “": 3.0,
        "widen": 3.0,
        "widening": 3.0,
        "expand": 3.0,
        "include": 2.0,
        "fold": 3.0,
        "decision gate": 4.0,
        "approval gate": 3.0,
        "fallback": 2.0,
        "exception": 2.0,
        "edge case": 2.0,
        "boundary": 2.0,
        "sign-off": 1.5,
    }
    return sum(weight for term, weight in weighted_terms.items() if term in content)


def ranked_messages(
    messages: Sequence[GroupMessage],
    question: GroupQuestion,
    adapter: TaskAdapter,
    source_anchor: str = "",
    routed_time_role: Optional[str] = None,
    embedding_scores: Optional[Mapping[str, float]] = None,
    embedding_score_weight: float = DEFAULT_EMBEDDING_MESSAGE_SCORE_WEIGHT,
) -> List[Tuple[float, float, float, int, GroupMessage, List[str]]]:
    query = f"{question.asking_user_id} {question.question}".strip()
    documents = [document_text(message, adapter) for message in messages]
    base_scores = bm25_scores(documents, query)
    ranked: List[Tuple[float, float, float, int, GroupMessage, List[str]]] = []
    for index, (message, base_score) in enumerate(zip(messages, base_scores)):
        cue_boost, reasons = task_cue_boost(message, question, adapter, routed_time_role)
        anchor_boost = source_anchor_boost(message, source_anchor)
        embedding_boost = 0.0
        if embedding_scores:
            embedding_boost = max(0.0, embedding_score_weight) * max(
                float(embedding_scores.get(message.event_id, 0.0)), 0.0
            )
            if embedding_boost:
                reasons = [*reasons, "embedding_hit"]
        total = base_score + cue_boost + anchor_boost + embedding_boost
        ranked.append((total, base_score, cue_boost + anchor_boost, index, message, reasons))
    ranked.sort(key=lambda item: (-item[0], item[4].timestamp, item[3]))
    return ranked


def score_messages_for_scope(ranked: Sequence[Tuple[float, float, float, int, GroupMessage, List[str]]]) -> float:
    positive = [item[0] for item in ranked if item[0] > 0]
    if not positive:
        return 0.0
    head = positive[:3]
    return head[0] + (0.25 * sum(head[1:]))


def refine_scope_route_with_evidence(
    messages: Sequence[GroupMessage],
    question: GroupQuestion,
    adapter: TaskAdapter,
    scopes: Sequence[ScopeNode],
    candidate_k: int,
    evidence_k: int,
    message_embedding_scores: Optional[Mapping[str, float]] = None,
    scope_embedding_scores: Optional[Mapping[str, float]] = None,
    message_embedding_score_weight: float = DEFAULT_EMBEDDING_MESSAGE_SCORE_WEIGHT,
    scope_embedding_score_weight: float = DEFAULT_EMBEDDING_SCOPE_SCORE_WEIGHT,
) -> Tuple[ScopeRoute, Dict[str, object]]:
    source_anchor = question.asking_user_id if adapter.source_anchor_required else ""
    global_ranked = ranked_messages(
        messages,
        question,
        adapter,
        source_anchor="",
        embedding_scores=message_embedding_scores,
        embedding_score_weight=message_embedding_score_weight,
    )
    top_global = global_ranked[: max(1, evidence_k)]
    evidence_by_scope: Dict[Tuple[str, str, str, str], List[Tuple[float, float, float, int, GroupMessage, List[str]]]] = {}
    for item in top_global:
        message = item[4]
        evidence_by_scope.setdefault(message.scope_key(), []).append(item)

    scored: List[Tuple[float, float, float, int, ScopeNode]] = []
    for index, scope in enumerate(scopes):
        lexical = score_scope(question, scope)
        evidence = score_messages_for_scope(evidence_by_scope.get((scope.domain, scope.channel, scope.phase_name, scope.topic), []))
        scope_embedding = max(float((scope_embedding_scores or {}).get(scope.scope_id, 0.0)), 0.0)
        total = lexical + (0.35 * evidence) + (max(0.0, scope_embedding_score_weight) * scope_embedding)
        scored.append((total, lexical, evidence, index, scope))
    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[4].event_count, item[3]))

    top = scored[: max(1, candidate_k)]
    best_total, best_lexical, best_evidence, _, best_scope = top[0]
    route_override_reason = None
    evidence_best_total, evidence_best_lexical, evidence_best_evidence, evidence_best_index, evidence_best_scope = max(
        scored,
        key=lambda item: (item[2], item[0], item[1], item[4].event_count),
    )
    evidence_dominates = evidence_best_evidence >= max(best_evidence + 8.0, best_evidence * 1.25)
    evidence_close_enough = evidence_best_total >= best_total - 3.0
    fine_target_evidence_override = (
        adapter.qtype == "knowledge_update"
        and evidence_best_scope.scope_id != best_scope.scope_id
        and len(question_target_terms(question)) <= 4
        and evidence_best_evidence >= best_evidence + 1.0
        and evidence_best_total >= best_total - 5.0
    )
    if evidence_best_scope.scope_id != best_scope.scope_id and (
        (evidence_dominates and evidence_close_enough) or fine_target_evidence_override
    ):
        best_total, best_lexical, best_evidence, best_scope = (
            evidence_best_total,
            evidence_best_lexical,
            evidence_best_evidence,
            evidence_best_scope,
        )
        route_override_reason = "fine_target_evidence_scope_override" if fine_target_evidence_override else "evidence_dominant_scope_override"
        if all(item[4].scope_id != best_scope.scope_id for item in top):
            top = [(evidence_best_total, evidence_best_lexical, evidence_best_evidence, evidence_best_index, evidence_best_scope)] + top[
                : max(0, len(top) - 1)
            ]

    second_total = max((item[0] for item in scored if item[4].scope_id != best_scope.scope_id), default=0.0)
    confidence = 1.0 if best_total > 0 and second_total <= 0 else 0.5
    if best_total > 0 and second_total > 0:
        confidence = max(0.0, min(1.0, (best_total - second_total) / max(best_total, 1.0)))

    target_scope = with_query_state_scope(with_source_anchor(best_scope, source_anchor), question, adapter)
    candidate_scopes = []
    for total, lexical, evidence, _, scope in top:
        candidate = with_query_state_scope(with_source_anchor(scope, source_anchor), question, adapter)
        payload = candidate.as_dict()
        payload["route_score"] = round(total, 4)
        payload["lexical_scope_score"] = round(lexical, 4)
        payload["evidence_scope_score"] = round(evidence, 4)
        payload["embedding_scope_score"] = round(float((scope_embedding_scores or {}).get(scope.scope_id, 0.0)), 6)
        candidate_scopes.append(payload)

    route = ScopeRoute(
        target_scope=target_scope,
        score=round(best_total, 4),
        confidence=round(confidence, 4),
        candidate_scopes=candidate_scopes,
        source_anchor=source_anchor,
    )
    debug = {
        "scope_route_strategy": "lexical_scope_plus_global_evidence",
        "scope_route_override": route_override_reason,
        "scope_evidence_k": max(1, evidence_k),
        "query_state_target": target_scope.state_target,
        "query_state_target_terms": list(target_scope.state_target_terms),
        "target_lexical_scope_score": round(best_lexical, 4),
        "target_evidence_scope_score": round(best_evidence, 4),
        "target_embedding_scope_score": round(float((scope_embedding_scores or {}).get(best_scope.scope_id, 0.0)), 6),
        "embedding_retrieval_used": bool(message_embedding_scores or scope_embedding_scores),
        "embedding_message_score_weight": round(max(0.0, message_embedding_score_weight), 4),
        "embedding_scope_score_weight": round(max(0.0, scope_embedding_score_weight), 4),
        "global_evidence_top_scores": [
            {
                "event_id": item[4].event_id,
                "scope_id": "::".join(item[4].scope_key()),
                "score": round(item[0], 6),
                "base_score": round(item[1], 6),
                "boost": round(item[2], 6),
                "embedding_score": round(float((message_embedding_scores or {}).get(item[4].event_id, 0.0)), 6),
                "timestamp": item[4].timestamp,
                "author": item[4].author,
                "reasons": item[5],
            }
            for item in top_global[: min(20, len(top_global))]
        ],
    }
    return route, debug


def select_graph_build_messages(
    scoped_messages: Sequence[GroupMessage],
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: ScopeRoute,
    event_limit: int,
    routed_time_role: Optional[str] = None,
    embedding_scores: Optional[Mapping[str, float]] = None,
    embedding_score_weight: float = DEFAULT_EMBEDDING_MESSAGE_SCORE_WEIGHT,
) -> Tuple[List[GroupMessage], Dict[str, object]]:
    scoped = chronological(scoped_messages)
    if event_limit <= 0 or event_limit >= len(scoped):
        return scoped, {
            "selection_strategy": "full_scope_for_claim_graph_build",
            "routed_time_role": routed_time_role,
            "scoped_event_count": len(scoped),
            "graph_event_count": len(scoped),
            "selected_event_reasons": {message.event_id: ["full_scope"] for message in scoped},
            "top_scores": [],
        }
    ranked = ranked_messages(
        scoped,
        question,
        adapter,
        route.source_anchor,
        routed_time_role,
        embedding_scores,
        embedding_score_weight=embedding_score_weight,
    )
    by_original_index = {item[4].event_id: item[3] for item in ranked}
    selected_ids: List[str] = []
    selection_reasons: Dict[str, List[str]] = {}

    def add(message: GroupMessage, reason: str) -> None:
        if message.event_id in selected_ids or len(selected_ids) >= max(1, event_limit):
            return
        selected_ids.append(message.event_id)
        selection_reasons.setdefault(message.event_id, []).append(reason)

    anchors: List[Tuple[float, float, float, int, GroupMessage, List[str]]] = []
    if adapter.qtype == "knowledge_update":
        change_anchors = [
            (knowledge_change_anchor_score(item[4]), item)
            for item in ranked
            if knowledge_change_anchor_score(item[4]) > 0
        ]
        change_anchors.sort(key=lambda item: (-item[0], -item[1][0], item[1][4].timestamp, item[1][3]))
        for _, item in change_anchors[: max(1, min(8, max(1, event_limit) // 6 + 1))]:
            anchors.append(item)
            add(item[4], "knowledge_update_change_anchor")

    anchor_count = max(2, min(len(ranked), max(1, event_limit) // 3))
    for item in ranked:
        if len(anchors) >= anchor_count:
            break
        if item[4].event_id not in {anchor[4].event_id for anchor in anchors}:
            anchors.append(item)

    for item in anchors:
        add(item[4], "ranked_anchor")

    neighbor_offsets = (-1, 1, -2, 2) if adapter.qtype == "knowledge_update" else (-1, 1)
    for _, _, _, index, _, _ in anchors:
        for offset in neighbor_offsets:
            neighbor_index = index + offset
            if 0 <= neighbor_index < len(scoped):
                add(scoped[neighbor_index], f"scope_timeline_neighbor:{offset:+d}")

    for item in ranked:
        add(item[4], "ranked_fill")
        if len(selected_ids) >= max(1, event_limit):
            break

    selected = chronological([message for message in scoped if message.event_id in selected_ids])
    debug_scores = [
        {
            "event_id": item[4].event_id,
            "score": round(item[0], 6),
            "base_score": round(item[1], 6),
            "boost": round(item[2], 6),
            "embedding_score": round(float((embedding_scores or {}).get(item[4].event_id, 0.0)), 6),
            "timestamp": item[4].timestamp,
            "author": item[4].author,
            "reasons": item[5],
        }
        for item in ranked[: max(1, min(max(event_limit, 20), len(ranked)))]
    ]
    return selected, {
        "selection_strategy": "expanded_scope_events_for_claim_graph_build",
        "routed_time_role": routed_time_role,
        "scoped_event_count": len(scoped),
        "graph_event_count": len(selected),
        "anchor_event_ids": [item[4].event_id for item in anchors],
        "selected_event_reasons": {
            event_id: selection_reasons.get(event_id, [])
            for event_id in selected_ids
        },
        "selected_original_indexes": {
            event_id: by_original_index[event_id]
            for event_id in selected_ids
            if event_id in by_original_index
        },
        "embedding_message_score_weight": round(max(0.0, embedding_score_weight), 4),
        "top_scores": debug_scores,
    }


def select_global_messages(
    messages: Sequence[GroupMessage],
    question: GroupQuestion,
    adapter: TaskAdapter,
    top_k: int,
) -> Tuple[List[GroupMessage], Dict[str, object]]:
    query = f"{question.asking_user_id} {question.question}".strip()
    documents = [document_text(message, adapter) for message in messages]
    scores = bm25_scores(documents, query)
    scored = [(score, message.timestamp, index, message) for index, (message, score) in enumerate(zip(messages, scores))]
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = [item[3] for item in scored[: max(1, top_k)]]
    return selected, {
        "global_event_count": len(messages),
        "selected_event_count": len(selected),
        "top_scores": [
            {
                "event_id": item[3].event_id,
                "score": round(item[0], 6),
                "timestamp": item[3].timestamp,
                "author": item[3].author,
            }
            for item in scored[: max(1, min(top_k, 20))]
        ],
    }

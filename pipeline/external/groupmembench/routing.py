from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Sequence

from pipeline.external.groupmembench.adapters.base import TaskAdapter
from pipeline.external.groupmembench.loader import GroupQuestion, ScopeNode, scope_id_for


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class ScopeRoute:
    target_scope: ScopeNode
    score: float
    confidence: float
    candidate_scopes: List[Dict[str, object]]
    source_anchor: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "target_scope_id": self.target_scope.scope_id,
            "scope_node": self.target_scope.as_dict(),
            "score": self.score,
            "confidence": self.confidence,
            "source_anchor": self.source_anchor or None,
            "candidate_scopes": self.candidate_scopes,
        }


def normalize_text(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("_", " ").replace("-", " ")).strip().lower()


def tokens(text: object) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "does",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


def meaningful_tokens(text: object) -> List[str]:
    return [token for token in tokens(text) if len(token) > 1 and token not in STOPWORDS]


def phrase_bonus(question_text: str, value: str, weight: float) -> float:
    value_norm = normalize_text(value)
    if not value_norm:
        return 0.0
    if value_norm in question_text:
        return weight
    parts = [part for part in meaningful_tokens(value_norm) if len(part) >= 4]
    if not parts:
        return 0.0
    hits = sum(1 for part in parts if part in question_text)
    return weight * min(1.0, hits / max(1, min(4, len(parts))))


def score_scope(question: GroupQuestion, scope: ScopeNode) -> float:
    question_norm = normalize_text(question.question)
    question_terms = set(meaningful_tokens(question.question))
    scope_terms = set(meaningful_tokens(scope.text()))
    overlap = len(question_terms & scope_terms)
    score = float(overlap)
    score += phrase_bonus(question_norm, scope.channel, 8.0)
    score += phrase_bonus(question_norm, scope.phase_name, 10.0)
    score += phrase_bonus(question_norm, scope.topic, 5.0)
    return score


def with_source_anchor(scope: ScopeNode, source_anchor: str) -> ScopeNode:
    if not source_anchor:
        return scope
    return ScopeNode(
        scope_id=scope_id_for(
            scope.domain,
            scope.channel,
            scope.phase_name,
            scope.topic,
            source_anchor,
            scope.state_target,
        ),
        domain=scope.domain,
        channel=scope.channel,
        phase_name=scope.phase_name,
        topic=scope.topic,
        scope_type=scope.scope_type,
        source_anchor=source_anchor,
        state_target=scope.state_target,
        state_target_terms=scope.state_target_terms,
        base_scope_id=scope.base_scope_id,
        reply_thread=scope.reply_thread,
        event_count=scope.event_count,
    )


def route_scope(
    question: GroupQuestion,
    adapter: TaskAdapter,
    scopes: Sequence[ScopeNode],
    candidate_k: int,
) -> ScopeRoute:
    if not scopes:
        raise ValueError(f"{question.case_id}: no scope nodes available")
    source_anchor = question.asking_user_id if adapter.source_anchor_required else ""
    scored = [(score_scope(question, scope), index, scope) for index, scope in enumerate(scopes)]
    scored.sort(key=lambda item: (-item[0], -item[2].event_count, item[1]))
    top = scored[: max(1, candidate_k)]
    best_score, _, best_scope = top[0]
    second_score = top[1][0] if len(top) > 1 else 0.0
    confidence = 1.0 if best_score > 0 and second_score <= 0 else 0.5
    if best_score > 0 and second_score > 0:
        confidence = max(0.0, min(1.0, (best_score - second_score) / max(best_score, 1.0)))
    target_scope = with_source_anchor(best_scope, source_anchor)
    candidate_scopes = []
    for score, _, scope in top:
        candidate = with_source_anchor(scope, source_anchor)
        payload = candidate.as_dict()
        payload["route_score"] = round(score, 4)
        candidate_scopes.append(payload)
    return ScopeRoute(
        target_scope=target_scope,
        score=round(best_score, 4),
        confidence=round(confidence, 4),
        candidate_scopes=candidate_scopes,
        source_anchor=source_anchor,
    )

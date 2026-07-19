"""Question-only time-role routing shared by Scope-Time-State retrievers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Protocol, Sequence


TIME_ROLE_ONTOLOGY = (
    "CURRENT_AFTER",
    "occurred_at",
    "mentioned_at",
    "updated_at",
    "planned_for",
    "deadline_at",
    "valid_from",
    "started_at",
    "completed_at",
    "finalized_at",
)

TIME_ROLE_ALIASES = {
    "current": "CURRENT_AFTER",
    "current_after": "CURRENT_AFTER",
    "latest": "CURRENT_AFTER",
    "occurred": "occurred_at",
    "occurred_at": "occurred_at",
    "mentioned": "mentioned_at",
    "mentioned_at": "mentioned_at",
    "updated": "updated_at",
    "updated_at": "updated_at",
    "planned": "planned_for",
    "planned_for": "planned_for",
    "deadline": "deadline_at",
    "deadline_at": "deadline_at",
    "valid": "valid_from",
    "valid_from": "valid_from",
    "started": "started_at",
    "started_at": "started_at",
    "completed": "completed_at",
    "completed_at": "completed_at",
    "finalized": "finalized_at",
    "finalized_at": "finalized_at",
}

TIME_ROLE_SELECTOR_SYSTEM_PROMPT = """You are a generic time-semantics router for long-term memory retrieval.
Read only the user question. Do not use benchmark names, task labels, answer options, answers, or outside facts.
Choose zero to three retrieval roles from this fixed ontology:
- CURRENT_AFTER: the state currently in effect after the latest valid update.
- occurred_at: when an event actually happened.
- mentioned_at: when information was stated or mentioned.
- updated_at: when a state was changed or updated.
- planned_for: a planned or scheduled future state.
- deadline_at: a due date or deadline.
- valid_from: when a state becomes valid.
- started_at: an actual start or beginning.
- completed_at: an actual completion.
- finalized_at: an approved, released, closed, or finalized completion.

Use an empty list when time or current-state validity is not needed to answer the question. Do not force a
time role onto ordinary entity, attribute, reason, list, or descriptive questions. Questions explicitly asking
for the current/latest valid state may use CURRENT_AFTER even when they do not contain a date expression.

Return JSON only: {"time_applicable": true, "time_roles": ["role"], "reason": "short semantic explanation"}.
This routes evidence retrieval only. Do not calculate a duration, select an answer, or infer facts not in the question."""

TIME_ROLE_COMPATIBLE_SELECTOR_SYSTEM_PROMPT = """You are a generic time-semantics router for long-term memory retrieval.
Read only the user question. Do not use benchmark names, task labels, answer options, answers, evidence, or outside facts.
Choose temporal retrieval roles from this fixed ontology:
- CURRENT_AFTER: the state currently in effect after the latest valid update.
- occurred_at: when an event actually happened.
- mentioned_at: when information was stated or mentioned.
- updated_at: when a state was changed or updated.
- planned_for: a planned or scheduled future state.
- deadline_at: a due date or deadline.
- valid_from: when a state becomes valid.
- started_at: an actual start or beginning.
- completed_at: an actual completion.
- finalized_at: an approved, released, closed, or finalized completion.

Return zero to two primary_roles that directly express the question's temporal intent. Return zero to two
compatible_roles only when the same temporal meaning could reasonably be represented under another ontology role
in stored evidence. Keep the union to at most three roles and do not add broad compatibility merely to increase recall.
Use empty lists when time or current-state validity is not needed. Do not force time roles onto ordinary entity,
attribute, reason, list, or descriptive questions.

Return JSON only: {"time_applicable": true, "primary_roles": ["role"], "compatible_roles": ["role"],
"reason": "short semantic explanation"}. This routes evidence retrieval only. Do not answer the question."""

TIME_ROLE_TOP2_SELECTOR_SYSTEM_PROMPT = """You are a generic time-semantics router for long-term memory retrieval.
Read only the user question. Do not use benchmark names, task labels, answer options, answers, evidence, or outside facts.
Choose zero to two roles from this fixed ontology: CURRENT_AFTER, occurred_at, mentioned_at, updated_at, planned_for,
deadline_at, valid_from, started_at, completed_at, finalized_at. Use an empty list when time or current-state validity
is not needed. Assign each selected role a confidence from 0 to 1 and order roles from highest to lowest confidence.
Return JSON only: {"time_applicable": true, "time_roles": ["role"],
"time_role_confidences": {"role": 0.95}, "reason": "short semantic explanation"}."""


class JsonCompletionClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, object]: ...


def normalize_time_roles(values: object) -> List[str]:
    rows: Sequence[object]
    if isinstance(values, str):
        rows = [values]
    elif isinstance(values, Sequence):
        rows = values
    else:
        rows = []
    selected: List[str] = []
    for value in rows:
        key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        canonical = TIME_ROLE_ALIASES.get(key)
        if canonical in TIME_ROLE_ONTOLOGY and canonical not in selected:
            selected.append(canonical)
    return selected


QUESTION_TIME_ROLE_RULES = (
    ("deadline_explicit", "deadline_at", re.compile(r"\b(?:deadline|due date|when is .+ due)\b|截止", re.I)),
    ("finalized_explicit", "finalized_at", re.compile(r"\b(?:finali[sz]ed|final decision|finally decided)\b|最终定稿|最终确定", re.I)),
    ("completed_explicit", "completed_at", re.compile(r"\b(?:completed|finished|completion|when did .+ finish)\b|什么时候完成|何时完成", re.I)),
    ("updated_explicit", "updated_at", re.compile(r"\b(?:updated|changed|revised|corrected|modified)\b|什么时候更新|何时更新|改成", re.I)),
    ("started_explicit", "started_at", re.compile(r"\b(?:started|began|when did .+ start)\b|什么时候开始|何时开始", re.I)),
    ("valid_from_explicit", "valid_from", re.compile(r"\b(?:effective from|valid from)\b|何时生效|什么时候生效", re.I)),
    ("planned_explicit", "planned_for", re.compile(r"\b(?:planned|scheduled|when will|going to)\b|计划什么时候|安排在", re.I)),
    (
        "current_explicit",
        "CURRENT_AFTER",
        re.compile(
            r"\b(?:current|currently|right now|(?:latest|most recent) (?:state|status|decision|value))\b|目前|当前|现在",
            re.I,
        ),
    ),
)


RECENT_QUESTION_RE = re.compile(r"\b(?:recent|recently|most recent|lately)\b|最近", re.I)
MENTION_TIME_QUESTION_RE = re.compile(
    r"\b(?:when|what (?:date|day|time))\b",
    re.I,
)
REPORTING_VERB_RE = re.compile(r"\b(?:mention(?:ed)?|say|said|tell|told|state(?:d)?|report(?:ed)?)\b", re.I)
REPORTING_NOMINAL_PREFIX_RE = re.compile(
    r"\b(?:the|a|an|this|that|my|your|his|her|our|their)\s+$",
    re.I,
)
EVENT_PREDICATE_RE = re.compile(
    r"\b(?:finish(?:ed|ing)?|complete(?:d|ing)?|conclud(?:e|ed|ing)|start(?:ed|ing)?|began|begin(?:ning)?|"
    r"launch(?:ed|ing)?|update(?:d|ing)?|change(?:d|ing)?|revise(?:d|ing)?|correct(?:ed|ing)?|modify|modified|"
    r"finali[sz](?:e|ed|ing)|plan(?:ned|ning)?|schedul(?:e|ed|ing)|visit(?:ed|ing)?|met|meet(?:ing)?|"
    r"happen(?:ed|ing)?|occur(?:red|ring)?)\b",
    re.I,
)
COMPLETION_ACTION_RE = re.compile(
    r"\b(?:finish(?:ed|ing)?|complete(?:d|ing)?|conclud(?:e|ed|ing))\b|完成|完工|结束",
    re.I,
)


def question_asks_mention_time(question: str) -> bool:
    temporal_prefix = MENTION_TIME_QUESTION_RE.search(question)
    if temporal_prefix is None:
        return False
    reporting_match = None
    for candidate in REPORTING_VERB_RE.finditer(question, temporal_prefix.end()):
        if REPORTING_NOMINAL_PREFIX_RE.search(question[: candidate.start()]):
            continue
        reporting_match = candidate
        break
    if reporting_match is None:
        return False
    event_match = EVENT_PREDICATE_RE.search(question, temporal_prefix.end())
    return event_match is None or reporting_match.start() < event_match.start()


def deterministic_question_time_roles(question: object) -> Dict[str, Any] | None:
    normalized_question = " ".join(str(question or "").split())
    if not normalized_question:
        return None
    if question_asks_mention_time(normalized_question):
        selection = {
            "time_applicable": True,
            "time_roles": ["mentioned_at"],
            "primary_roles": ["mentioned_at"],
            "compatible_roles": [],
            "source": "deterministic_high_precision_question_rule:mentioned_explicit",
            "reason": "The question asks when information was mentioned, not when its embedded event happened.",
            "question": normalized_question,
        }
        if RECENT_QUESTION_RE.search(normalized_question):
            selection["ordering"] = "newest_first"
        return selection
    if RECENT_QUESTION_RE.search(normalized_question) and COMPLETION_ACTION_RE.search(normalized_question):
        return {
            "time_applicable": True,
            "time_roles": ["completed_at"],
            "primary_roles": ["completed_at"],
            "compatible_roles": [],
            "ordering": "newest_first",
            "source": "deterministic_high_precision_question_rule:recent_completion",
            "reason": "The question explicitly requests the newest actual completion.",
            "question": normalized_question,
        }
    matches = [(name, role) for name, role, pattern in QUESTION_TIME_ROLE_RULES if pattern.search(normalized_question)]
    roles = list(dict.fromkeys(role for _name, role in matches))
    if len(roles) == 1:
        selection = {
            "time_applicable": True,
            "time_roles": roles,
            "primary_roles": roles,
            "compatible_roles": [],
            "source": f"deterministic_high_precision_question_rule:{'+'.join(name for name, _role in matches)}",
            "reason": "The question contains one unambiguous temporal-role expression.",
            "question": normalized_question,
        }
        if RECENT_QUESTION_RE.search(normalized_question):
            selection["ordering"] = "newest_first"
            selection["reason"] = (
                "The question contains one unambiguous temporal role and explicitly requests its newest match."
            )
        return selection
    if not roles and RECENT_QUESTION_RE.search(normalized_question):
        return {
            "time_applicable": True,
            "time_roles": ["occurred_at", "started_at", "updated_at"],
            "primary_roles": ["occurred_at"],
            "compatible_roles": ["started_at", "updated_at"],
            "ordering": "newest_first",
            "source": "deterministic_high_precision_question_rule:recent",
            "reason": "The question explicitly asks for recent activity; retrieve event/update boundaries and rank newest first.",
            "question": normalized_question,
        }
    return None


def select_time_roles(question: object, client: JsonCompletionClient, selector: str) -> Dict[str, Any]:
    normalized_question = " ".join(str(question or "").split())
    fallback: Dict[str, Any] = {
        "time_applicable": False,
        "time_roles": [],
        "source": "no_time_fallback",
        "reason": "No reliable temporal intent was selected; keep relevance ranking unchanged.",
        "question": normalized_question,
    }
    if selector == "none":
        return {
            **fallback,
            "time_roles": [],
            "source": "selector_disabled",
            "reason": "Time-role selection is disabled.",
        }
    deterministic = deterministic_question_time_roles(normalized_question)
    if deterministic is not None and selector != "llm-top2":
        return deterministic
    try:
        raw = client.complete_json(
            (
                TIME_ROLE_COMPATIBLE_SELECTOR_SYSTEM_PROMPT
                if selector == "llm-compatible"
                else TIME_ROLE_TOP2_SELECTOR_SYSTEM_PROMPT
                if selector == "llm-top2"
                else TIME_ROLE_SELECTOR_SYSTEM_PROMPT
            ),
            f"Question:\n{normalized_question}",
        )
    except Exception as exc:
        return {
            **fallback,
            "source": "selector_error_fallback",
            "error": f"{type(exc).__name__}: {exc}",
        }
    expected_key = "primary_roles" if selector == "llm-compatible" else "time_roles"
    if (
        not isinstance(raw, Mapping)
        or expected_key not in raw
        or type(raw.get("time_applicable")) is not bool
    ):
        return {
            **fallback,
            "source": "selector_invalid_fallback",
            "raw": raw,
        }
    if selector == "llm-compatible":
        primary_roles = normalize_time_roles(raw.get("primary_roles"))[:2]
        candidate_compatible_roles = [
            role
            for role in normalize_time_roles(raw.get("compatible_roles"))
            if role not in primary_roles
        ]
        compatible_roles = candidate_compatible_roles[: min(2, max(0, 3 - len(primary_roles)))]
        time_roles = primary_roles + compatible_roles
    elif selector == "llm-top2":
        raw_roles = normalize_time_roles(raw.get("time_roles"))
        raw_confidences = raw.get("time_role_confidences")
        confidence_by_role: Dict[str, float] = {}
        if isinstance(raw_confidences, Mapping):
            for role in raw_roles:
                try:
                    confidence_by_role[role] = max(
                        0.0,
                        min(1.0, float(raw_confidences.get(role, 0.0))),
                    )
                except (TypeError, ValueError):
                    confidence_by_role[role] = 0.0
        original_order = {role: index for index, role in enumerate(raw_roles)}
        raw_roles.sort(
            key=lambda role: (-confidence_by_role.get(role, 0.0), original_order[role])
        )
        primary_roles = raw_roles[:2]
        compatible_roles = []
        time_roles = primary_roles
    else:
        primary_roles = normalize_time_roles(raw.get("time_roles"))[:3]
        compatible_roles = []
        time_roles = primary_roles
    if raw.get("time_applicable") is True and selector == "llm-compatible" and not primary_roles:
        return {
            **fallback,
            "source": "selector_invalid_fallback",
            "raw": raw,
        }
    time_applicable = raw.get("time_applicable") is True and bool(time_roles)
    if not time_applicable:
        time_roles = []
    return {
        "time_applicable": time_applicable,
        "time_roles": time_roles,
        "primary_roles": primary_roles if time_applicable else [],
        "compatible_roles": compatible_roles if time_applicable else [],
        "time_role_confidences": (
            {role: confidence_by_role.get(role, 0.0) for role in time_roles}
            if selector == "llm-top2" and time_applicable
            else {}
        ),
        "source": (
            "llm_compatible_question_only"
            if selector == "llm-compatible"
            else "llm_top2_confidence_question_only"
            if selector == "llm-top2"
            else "llm_question_only"
        ),
        "reason": str(raw.get("reason") or "")[:400] if isinstance(raw, Mapping) else "",
        "question": normalized_question,
        "raw": raw,
    }

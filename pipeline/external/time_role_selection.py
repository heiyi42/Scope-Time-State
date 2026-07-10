"""Question-only time-role routing shared by Scope-Time-State retrievers."""

from __future__ import annotations

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
Choose one to three retrieval roles from this fixed ontology:
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

Return JSON only: {"time_roles": ["role"], "reason": "short semantic explanation"}.
This routes evidence retrieval only. Do not calculate a duration, select an answer, or infer facts not in the question."""


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


def select_time_roles(question: object, client: JsonCompletionClient, selector: str) -> Dict[str, Any]:
    normalized_question = " ".join(str(question or "").split())
    fallback: Dict[str, Any] = {
        "time_roles": ["CURRENT_AFTER"],
        "source": "default_current_state",
        "reason": "No semantic selector result; retrieve the currently effective state.",
        "question": normalized_question,
    }
    if selector == "none":
        return {
            **fallback,
            "time_roles": [],
            "source": "selector_disabled",
            "reason": "Time-role selection is disabled.",
        }
    try:
        raw = client.complete_json(
            TIME_ROLE_SELECTOR_SYSTEM_PROMPT,
            f"Question:\n{normalized_question}",
        )
    except Exception as exc:
        return {
            **fallback,
            "source": "selector_error_fallback",
            "error": f"{type(exc).__name__}: {exc}",
        }
    time_roles = normalize_time_roles(raw.get("time_roles") if isinstance(raw, Mapping) else None)
    if not time_roles:
        return {
            **fallback,
            "source": "selector_empty_fallback",
            "raw": raw,
        }
    return {
        "time_roles": time_roles,
        "source": "llm_question_only",
        "reason": str(raw.get("reason") or "")[:400] if isinstance(raw, Mapping) else "",
        "question": normalized_question,
        "raw": raw,
    }

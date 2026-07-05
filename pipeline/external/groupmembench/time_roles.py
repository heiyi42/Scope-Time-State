from __future__ import annotations

import hashlib
import json
from typing import Dict

from Experiment.run.common.llm_client import LLMClient
from pipeline.external.groupmembench.adapters.base import TaskAdapter
from pipeline.external.groupmembench.loader import GroupQuestion


TIME_ROLES = ("occurred_at", "mentioned_at", "updated_at", "planned_for", "deadline_at")


def infer_group_time_role_with_llm(client: LLMClient, question: GroupQuestion, adapter: TaskAdapter) -> Dict[str, object]:
    raw = client.complete_json(time_role_system_prompt(), time_role_user_prompt(question, adapter))
    return normalize_time_role_route(raw)


def infer_group_time_role(question: GroupQuestion, adapter: TaskAdapter) -> Dict[str, object]:
    return route("updated_at", 0.0, ["fallback_without_llm_time_role_selector"])


def time_role_system_prompt() -> str:
    return (
        "You are the time-role routing node for GroupMemBench. Use only the question text, asking_user_id, "
        "and task adapter description. Do not use corpus messages, hidden metadata, benchmark answers, "
        "or external knowledge. Choose exactly one time role for downstream retrieval and state selection. "
        "Return valid JSON only."
    )


def prompt_cache_namespace(question: GroupQuestion, adapter: TaskAdapter, stage: str) -> Dict[str, object]:
    namespace: Dict[str, object] = {
        "benchmark": "GroupMemBench",
        "domain": question.domain,
        "task": adapter.qtype,
        "stage": stage,
    }
    if adapter.qtype == "state_query":
        seed = f"{question.domain}\n{question.asking_user_id}\n{question.question}"
        namespace["case_key"] = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    else:
        namespace["question_id"] = question.question_id
    return namespace


def time_role_user_prompt(question: GroupQuestion, adapter: TaskAdapter) -> str:
    payload = {
        "cache_namespace": prompt_cache_namespace(question, adapter, "time_role_routing"),
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "task_adapter": adapter.prompt_payload(),
        "time_role_options": {
            "occurred_at": (
                "Use when the question asks when an instruction, request, ask, message, or event happened."
            ),
            "mentioned_at": (
                "Use when the question asks for a date that was mentioned, noted, called out, or potentially moved, "
                "rather than asking for the final current deadline."
            ),
            "updated_at": (
                "Use for current state, latest valid state, owner, rule, team, status, scope, or decision questions "
                "where the requested answer is not a planned/deadline/mentioned/occurrence date."
            ),
            "planned_for": (
                "Use when the question asks for a scheduled, planned, expected, target, or completion date/time."
            ),
            "deadline_at": (
                "Use when the question asks for a deadline, due date, cutoff, by-when date, or must-be-done-by date."
            ),
        },
        "output_schema": {
            "time_role": "one of occurred_at|mentioned_at|updated_at|planned_for|deadline_at",
            "confidence": "number from 0 to 1",
            "reasons": ["short question-only reasons"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_time_role_route(raw: Dict[str, object]) -> Dict[str, object]:
    time_role = str(raw.get("time_role") or "").strip()
    if time_role not in TIME_ROLES:
        raise ValueError(f"invalid time_role from LLM selector: {time_role!r}")
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reasons_raw = raw.get("reasons", [])
    reasons = [str(reason) for reason in reasons_raw] if isinstance(reasons_raw, list) else [str(reasons_raw)]
    return {
        "time_role": time_role,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "strategy": "groupmembench_llm_question_time_role_selector",
        "reasons": reasons,
    }


def route(time_role: str, confidence: float, reasons: list[str]) -> Dict[str, object]:
    return {
        "time_role": time_role if time_role in TIME_ROLES else "updated_at",
        "confidence": round(confidence, 4),
        "strategy": "groupmembench_question_time_role_rules",
        "reasons": list(reasons),
    }

def time_role_instruction(time_role: object) -> str:
    role = str(time_role or "updated_at")
    if role == "occurred_at":
        return (
            "The routed time role is occurred_at: for instruction/asked-date questions, use the supporting "
            "Episode/Event occurred_at timestamp as the date answer. Do not replace it with a deadline mentioned "
            "inside the message."
        )
    if role == "deadline_at":
        return (
            "The routed time role is deadline_at: extract the date or relative deadline asserted in the message "
            "content, resolving today/tomorrow/weekday/EOD relative to the supporting Episode/Event occurred_at."
        )
    if role == "planned_for":
        return (
            "The routed time role is planned_for: extract the expected, scheduled, target, or completion date "
            "asserted in the message content, resolving relative dates against the supporting event timestamp."
        )
    if role == "mentioned_at":
        return (
            "The routed time role is mentioned_at: answer the date mentioned by the evidence, not merely the "
            "latest message timestamp unless the question asks when the mention happened."
        )
    return (
        "The routed time role is updated_at: prefer the latest valid scoped update after resolving corrections "
        "and superseding claims."
    )

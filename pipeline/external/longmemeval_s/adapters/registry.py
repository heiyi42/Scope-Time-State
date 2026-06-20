from __future__ import annotations

from importlib import import_module
from typing import Dict

from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


TASK_TYPES: Dict[str, str] = {
    "single-session-user": "single_session_user.adapter",
    "single-session-assistant": "single_session_assistant.adapter",
    "single-session-preference": "single_session_preference.adapter",
    "multi-session": "multi_session.adapter",
    "temporal-reasoning": "temporal_reasoning.adapter",
    "knowledge-update": "knowledge_update.adapter",
}


def get_adapter(question_type: str) -> TaskAdapter:
    try:
        module_name = TASK_TYPES[question_type]
    except KeyError as exc:
        known = ", ".join(sorted(TASK_TYPES))
        raise ValueError(f"unsupported LongMemEval-S question_type={question_type}; known={known}") from exc
    module = import_module(f"pipeline.external.longmemeval_s.adapters.{module_name}")
    adapter = getattr(module, "ADAPTER")
    if not isinstance(adapter, TaskAdapter):
        raise TypeError(f"{module.__name__}.ADAPTER must be a TaskAdapter")
    return adapter

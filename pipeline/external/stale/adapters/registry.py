from __future__ import annotations

from importlib import import_module
from typing import Dict

from pipeline.external.stale.adapters.base import TaskAdapter


TASK_TYPES: Dict[str, str] = {
    "state_resolution": "state_resolution.adapter",
    "premise_resistance": "premise_resistance.adapter",
    "implicit_policy_adaptation": "implicit_policy_adaptation.adapter",
}


def get_adapter(task_type: str) -> TaskAdapter:
    try:
        module_name = TASK_TYPES[task_type]
    except KeyError as exc:
        known = ", ".join(sorted(TASK_TYPES))
        raise ValueError(f"unsupported STALE task_type={task_type}; known={known}") from exc
    module = import_module(f"pipeline.external.stale.adapters.{module_name}")
    adapter = getattr(module, "ADAPTER")
    if not isinstance(adapter, TaskAdapter):
        raise TypeError(f"{module.__name__}.ADAPTER must be a TaskAdapter")
    return adapter


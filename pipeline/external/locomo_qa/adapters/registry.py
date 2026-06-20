from __future__ import annotations

from importlib import import_module
from typing import Dict

from pipeline.external.locomo_qa.adapters.base import TaskAdapter


# Official LoCoMo QA category IDs are not ordered by task name.
# The mapping follows the public LoCoMo evaluator:
# 4 single-hop, 1 multi-hop, 2 temporal, 3 open-domain knowledge, 5 adversarial.
CATEGORY_TO_TASK_TYPE: Dict[int, str] = {
    4: "single-hop",
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    5: "adversarial",
}

TASK_TYPES: Dict[str, str] = {
    "single-hop": "single_hop.adapter",
    "multi-hop": "multi_hop.adapter",
    "temporal": "temporal.adapter",
    "open-domain": "open_domain.adapter",
    "adversarial": "adversarial.adapter",
}


def task_type_from_category(category: int) -> str:
    try:
        return CATEGORY_TO_TASK_TYPE[int(category)]
    except KeyError as exc:
        known = ", ".join(str(item) for item in sorted(CATEGORY_TO_TASK_TYPE))
        raise ValueError(f"unsupported LoCoMo QA category={category}; known={known}") from exc


def get_adapter(question_type: str) -> TaskAdapter:
    try:
        module_name = TASK_TYPES[question_type]
    except KeyError as exc:
        known = ", ".join(sorted(TASK_TYPES))
        raise ValueError(f"unsupported LoCoMo QA question_type={question_type}; known={known}") from exc
    module = import_module(f"pipeline.external.locomo_qa.adapters.{module_name}")
    adapter = getattr(module, "ADAPTER")
    if not isinstance(adapter, TaskAdapter):
        raise TypeError(f"{module.__name__}.ADAPTER must be a TaskAdapter")
    return adapter

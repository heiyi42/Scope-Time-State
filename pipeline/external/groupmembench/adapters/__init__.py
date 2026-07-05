from __future__ import annotations

from typing import Dict

from pipeline.external.groupmembench.adapters.abstention import ADAPTER as ABSTENTION
from pipeline.external.groupmembench.adapters.base import TASK_TYPES, TaskAdapter
from pipeline.external.groupmembench.adapters.knowledge_update import ADAPTER as KNOWLEDGE_UPDATE
from pipeline.external.groupmembench.adapters.multi_hop import ADAPTER as MULTI_HOP
from pipeline.external.groupmembench.adapters.temporal import ADAPTER as TEMPORAL
from pipeline.external.groupmembench.adapters.term_ambiguity import ADAPTER as TERM_AMBIGUITY
from pipeline.external.groupmembench.adapters.user_implicit import ADAPTER as USER_IMPLICIT


_ADAPTERS: Dict[str, TaskAdapter] = {
    "multi_hop": MULTI_HOP,
    "knowledge_update": KNOWLEDGE_UPDATE,
    "temporal": TEMPORAL,
    "user_implicit": USER_IMPLICIT,
    "term_ambiguity": TERM_AMBIGUITY,
    "abstention": ABSTENTION,
}


def get_adapter(qtype: str) -> TaskAdapter:
    try:
        return _ADAPTERS[qtype]
    except KeyError as exc:
        known = ", ".join(TASK_TYPES)
        raise ValueError(f"unsupported GroupMemBench qtype={qtype}; known={known}") from exc


__all__ = ["TASK_TYPES", "TaskAdapter", "get_adapter"]

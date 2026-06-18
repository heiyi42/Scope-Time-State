from __future__ import annotations

from typing import Sequence

from ...common import BaselinePromptSpec, event_view, relevant_by_scope, sort_by_time


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    sorted_scoped = sort_by_time(relevant_by_scope(events, case.scope_id), case.time_role)
    visible = [event_view(event, include_relations=False, include_state_relevant=False) for event in sorted_scoped[:4]]
    instruction = "模拟普通 Hybrid RAG：你拿到按 query time_role 排序的 top-4 事件。直接根据检索证据填状态字段，不额外使用纠错、废弃或 state-relevance 规则。"
    return BaselinePromptSpec("hybrid_rag", visible, instruction)

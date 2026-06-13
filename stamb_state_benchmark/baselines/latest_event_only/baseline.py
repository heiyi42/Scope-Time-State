from __future__ import annotations

from typing import Sequence

from ..common import BaselinePromptSpec, event_view, relevant_by_scope, sort_by_time


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    sorted_scoped = sort_by_time(relevant_by_scope(events, case.scope_id), case.time_role)
    visible = [event_view(sorted_scoped[0], include_relations=False, include_state_relevant=False)]
    instruction = "模拟只取 latest event 的长期记忆系统。你只能根据给定的 1 条最新事件回答，不要推断不可见的历史纠错关系。"
    return BaselinePromptSpec("latest_event_only", visible, instruction)

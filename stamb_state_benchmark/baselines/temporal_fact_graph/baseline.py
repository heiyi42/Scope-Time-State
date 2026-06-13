from __future__ import annotations

from typing import Sequence

from ..common import BaselinePromptSpec, event_view, relevant_by_scope, sort_by_time


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    scoped = relevant_by_scope(events, case.scope_id)
    facts = [event for event in scoped if event.status != "superseded"]
    visible = [event_view(event, include_relations=True, include_state_relevant=False) for event in sort_by_time(facts, case.time_role)]
    instruction = "模拟 temporal KG facts：你能看到事实、时间和部分 corrects/supersedes 关系，但没有专门的项目状态答案规范，也没有 state_relevant 标注。"
    return BaselinePromptSpec("temporal_fact_graph", visible, instruction)

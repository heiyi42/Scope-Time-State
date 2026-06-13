from __future__ import annotations

from typing import Sequence

from ..common import BaselinePromptSpec, event_view, relevant_by_scope, sort_by_time


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    sorted_scoped = sort_by_time(relevant_by_scope(events, case.scope_id), case.time_role)
    visible = [event_view(event, include_relations=True, include_state_relevant=True) for event in sorted_scoped]
    instruction = (
        "模拟强 KG + prompt/Pydantic baseline：你能看到完整 metadata，并且必须执行这些规则："
        "1. status=superseded 的事件不能作为当前状态；"
        "2. 被 corrects 或 supersedes 指向的旧事件不能作为当前状态；"
        "3. state_relevant=false 的事件只是复述、日志或无状态变化，不应更新状态字段；"
        "4. 用户问“最近怎么样”时，输出目标 scope 下由有效证据支持的 latest valid state。"
    )
    return BaselinePromptSpec("kg_schema_with_validity_rules", visible, instruction)

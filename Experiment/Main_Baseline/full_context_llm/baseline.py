from __future__ import annotations

from typing import Sequence

from ...common import BaselinePromptSpec, event_view, sort_by_time


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    visible = [
        event_view(event, include_relations=True, include_state_relevant=False)
        for event in sort_by_time(events, case.time_role)
    ]
    instruction = (
        "模拟 LLM-only / full-context baseline：你能看到完整事件流，但没有外部检索器、"
        "知识图谱、validity resolver 或 state aggregator。请只依靠给定事件内容、"
        "时间字段自己推理答案。如果可见事件包含 status、corrects 或 supersedes，"
        "可以使用这些字段；如果没有，就不能假设外部有效性标注存在。"
    )
    return BaselinePromptSpec("full_context_llm", visible, instruction)

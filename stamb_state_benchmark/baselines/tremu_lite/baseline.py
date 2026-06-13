from __future__ import annotations

from typing import Dict, Sequence

from ..common import BaselinePromptSpec, relevant_by_scope, sort_by_time


def timeline_entry(event: object) -> Dict[str, object]:
    return {
        "event_id": event.event_id,
        "timeline_time": event.occurred_at,
        "content": event.content,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "mentioned_at": event.mentioned_at,
        "updated_at": event.updated_at,
    }


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    scoped = relevant_by_scope(events, case.scope_id)
    timeline = [timeline_entry(event) for event in reversed(sort_by_time(scoped, "occurred_at"))]
    instruction = (
        "模拟 TReMu-lite baseline：你拿到目标 scope 下按 occurrence time 组织的 timeline memory。"
        "你应优先基于事件发生时间进行 temporal reasoning，并可结合 query 的时间意图选择相关 timeline entries。"
        "这个 baseline 不提供显式 validity 过滤、state_relevant 标注或专门的 latest valid state 规则；"
        "如果需要判断旧方案是否失效，只能根据 timeline 事件文本本身推理。"
    )
    return BaselinePromptSpec("tremu_lite", timeline, instruction)

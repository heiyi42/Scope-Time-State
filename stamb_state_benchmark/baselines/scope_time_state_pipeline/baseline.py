from __future__ import annotations

from typing import Sequence

from ..common import (
    BaselinePromptSpec,
    event_view,
    relevant_by_scope,
    resolve_valid_events,
    sort_by_time,
)


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    scoped = relevant_by_scope(events, case.scope_id)
    valid_events, invalid_ids = resolve_valid_events(scoped, case.time_role)
    invalid_events = sort_by_time(
        [event for event in scoped if event.event_id in set(invalid_ids)],
        case.time_role,
    )
    visible = [
        event_view(event, include_relations=True, include_state_relevant=True, state_role="valid_current_state_evidence")
        for event in valid_events
    ]
    visible.extend(
        event_view(event, include_relations=True, include_state_relevant=True, state_role="invalidated_context_only")
        for event in invalid_events
    )
    instruction = (
        "模拟我们的 Scope-Time-State Retriever：上游已经完成 scope routing、time-role 选择、"
        f"validity 过滤和 state-relevance 过滤。已过滤无效事件：{invalid_ids}。"
        "state_role=valid_current_state_evidence 的事件可作为当前有效状态证据；"
        "state_role=invalidated_context_only 的事件只能用于解释旧判断、旧方案或旧结果为什么无效，不能当作当前状态。"
        "你现在做 state retrieval，不写最终自然语言 answer。"
        "必须对每个 output_slot 同时生成 value、support_event 和 support_events。"
        "support_event 是最直接主证据；support_events 是该 slot 完整证据集合。"
        "你必须执行显式 State Aggregator 规则："
        "1. 对 output_slots 中每个 slot 都生成 value、support_event 和 support_events，不能遗漏。"
        "2. invalidated_* 字段必须表达“旧状态/旧方案/旧判断已经失效、被替代或被纠正”，不能只复述旧状态本身。"
        "3. resolved_* 字段必须表达“问题已经解决/修复”，不能只复述旧问题。"
        "4. remaining_* 字段必须同时保留已完成事实和剩余工作，不能只写剩余工作。"
        "5. completed_item 只能写已完成事项，不能扩展成整个项目已经完成。"
        "6. next_step 若有多个并列后续动作，必须全部保留。"
        "7. invalidated_*、resolved_*、corrected_* 这类 slot 往往需要旧事件和纠正/替代事件共同支撑。"
        "8. evidence_events 必须是所有 support_events 的去重集合，不要为了写回答额外加入背景事件。"
    )
    return BaselinePromptSpec("scope_time_state_pipeline", visible, instruction)

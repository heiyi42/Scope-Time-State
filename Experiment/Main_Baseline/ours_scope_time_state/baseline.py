from __future__ import annotations

from typing import Sequence

from ...common import (
    BaselinePromptSpec,
    event_view,
    has_validity_annotations,
    relevant_by_scope,
    resolve_valid_events,
    sort_by_time,
)


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    scoped = relevant_by_scope(events, case.scope_id)
    if not has_validity_annotations(scoped):
        visible = [
            event_view(event, include_relations=True, include_state_relevant=True)
            for event in sort_by_time(scoped, case.time_role)
        ]
        instruction = (
            "模拟我们的 Scope-Time-State state construction：输入是目标 scope 的 raw events，"
            "不包含 oracle status、state_relevant、corrects 或 supersedes 标注。"
            "你必须根据事件文本、event_type 和时间字段自己判断纠错、替代、计划未完成、"
            "最近复述干扰和当前有效状态。你现在做 state retrieval，不写最终自然语言 answer。"
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
            "9. risk 字段必须写具体风险来源和被风险影响的对象；invalidated_* 字段再写哪个旧方向被后续决策替代，不要混写。"
            "10. 如果 query 明确对比实际发生/完成时间与记录/提到时间，slot value 必须同时保留两个时间角色。"
            "11. 如果 query 问旧状态、旧错误或旧 token 状态是否“现在还是”成立，slot value 必须同时写旧状态是什么、"
            "以及哪个新事件证明当前状态已经改变；support_events 必须包含旧状态事件和新状态事件。"
            "12. remaining_*、risk 或剩余风险/剩余工作类字段必须同时写风险/剩余项和同一证据里的处置要求、"
            "保留动作或后续约束，不能只列风险名。"
            "13. 当前 root_cause/current_* slot 只写当前有效原因/状态；被纠正的旧原因只能进入 invalidated_* 或背景字段，"
            "不能混进当前 root_cause value。"
            "14. 对 completion_status、submission_status、audit_log_status、training_status、review_status 等是否完成类字段，"
            "如果证据只有计划、待办、草稿、待补或未复核，没有明确完成记录，必须同时写清楚："
            "只有哪个计划/安排/待办/草稿/待补/未复核记录，以及没有明确完成/提交/补完/复核完成记录，"
            "因此无法确认已经完成/提交/补完；"
            "不能写成“未完成”“尚未完成”或“not_submitted”，除非事件明确说该事项未完成。"
        )
        return BaselinePromptSpec("ours_scope_time_state", visible, instruction)

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
        "9. risk 字段必须写具体风险来源和被风险影响的对象；invalidated_* 字段再写哪个旧方向被后续决策替代，不要混写。"
        "10. 如果 query 明确对比实际发生/完成时间与记录/提到时间，slot value 必须同时保留两个时间角色。"
        "11. 如果 query 问旧状态、旧错误或旧 token 状态是否“现在还是”成立，slot value 必须同时写旧状态是什么、"
        "以及哪个新事件证明当前状态已经改变；support_events 必须包含旧状态事件和新状态事件。"
        "12. remaining_*、risk 或剩余风险/剩余工作类字段必须同时写风险/剩余项和同一证据里的处置要求、"
        "保留动作或后续约束，不能只列风险名。"
        "13. 当前 root_cause/current_* slot 只写当前有效原因/状态；被纠正的旧原因只能进入 invalidated_* 或背景字段，"
        "不能混进当前 root_cause value。"
        "14. 对 completion_status、submission_status、audit_log_status、training_status、review_status 等是否完成类字段，"
        "如果证据只有计划、待办、草稿、待补或未复核，没有明确完成记录，必须同时写清楚："
        "只有哪个计划/安排/待办/草稿/待补/未复核记录，以及没有明确完成/提交/补完/复核完成记录，"
        "因此无法确认已经完成/提交/补完；"
        "不能写成“未完成”“尚未完成”或“not_submitted”，除非事件明确说该事项未完成。"
    )
    return BaselinePromptSpec("ours_scope_time_state", visible, instruction)

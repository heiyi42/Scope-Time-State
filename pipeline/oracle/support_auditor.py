from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence, Tuple

from Experiment.run.common.llm_client import LLMClient
from Experiment.run.common.models import QueryCase
from pipeline.oracle.event_ids import (
    event_ids_from_visible_events,
    restrict_auditor_to_candidate_events,
    validate_and_repair_event_ids,
)


def support_auditor_system_prompt() -> str:
    return (
        "你是 Scope-Time-State Support Auditor。你只做 locked_state 审计和改写，不写最终 answer。"
        "输入包含 visible_events 和 candidate_locked_state。输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}'
        "}。"
        "你必须保留 output_slots 中每个 slot，但可以删除候选 state value 中不属于该 slot 的背景事实、旧事实、"
        "相邻计划、旧截止时间、旧完成项、旧误判或其他 slot 的信息。"
        "support_events 必须是支撑该 slot value 的最小必要集合，并且必须逐字复制 visible_events[].event_id。"
        "evidence_events 必须是所有 support_events 的去重集合。"
        "state_slots.*.value 必须是自然语言状态，不要把 event_id 写进 value；event_id 只能放在 evidence/support 字段。"
        "不要把历史上所有完成项累积成当前状态；只保留与 query 和该 output_slot 直接相关的最新有效完成/剩余事实。"
        "completed_item 表示当前/latest state 下仍相关的完成项，不是历史完成清单；"
        "如果候选 completed_item 同时包含较早的初始化、草稿、提纲、准备性完成记录和较新的当前完成记录，"
        "而 query 没有要求列出全部历史完成项，必须删除较早的历史完成记录及其 support_event。"
        "如果 output_slots 已经把 remaining_work 和 completed_item 拆开，remaining_work 只写仍需处理的工作"
        "及其处置要求，completed_item 只写明确完成且与当前问题直接相关的事项。"
        "如果 query 问“主要质量问题/当前问题/issue 是什么”，current_issue 只写直接的问题事实；"
        "删除进度、复核状态、质量确认状态、历史规范和下一步计划。"
        "如果 query 问某事是否已经完成，completion_status 应写成“只有...计划/安排，没有完成记录，"
        "因此无法确认已经完成”；除非 query 明确询问日期，否则删除具体日期和记录日期。"
        "如果 query 问“能否直接说/是否仍然成立/现在还是不是”，slot value 必须包含明确的不能/不是/已不成立结论，"
        "以及使旧判断失效的当前规则或当前证据；不要只保留当前规则而删掉否定结论。"
        "support_events 必须同时保留被判断的旧说法/旧前提事件和当前纠正/当前规则事件。"
        "如果 query 问 event_f1 第一能不能直接说最好，support_events 必须同时保留旧排序口径、"
        "当前主排序规则，以及说明 event_f1 第一代表最好属于旧口径的事件；不能只保留当前主排序规则。"
        "如果 output_slot 是 diagnostic_metric，value 必须写清该诊断指标不单独决定方法优劣，不能只写指标名。"
        "如果某指标从旧主排序/旧判断依据降为当前诊断指标，diagnostic_metric 的 support_events 必须同时保留旧口径事件和当前口径事件。"
        "如果 query 问某个限制/额度/故障“怎么处理”，只保留处理方式；删除 endpoint ping、全量 run 进展、"
        "后续风险、cache 或成本，除非 query 明确询问这些。"
        "support_events 必须同时保留限制/额度/故障本身的事件和当前处理决策事件。"
        "如果处理方式是 provider 角色拆分，必须保留每个 provider 仍负责什么、切换到什么 provider 负责什么；"
        "不要只保留被切换的那一半。"
        "如果 query 问计划事项是否做完，且候选或可见事件中已有 execution_log / 完成记录，"
        "不要按 unknown_current 模板回答无法确认；必须把计划和后续执行记录合并为当前状态。"
        "如果后续 execution_log 记录了依赖该计划的完整 workflow/run 已完成并产出结果，"
        "应视为该计划对应流程已完成，除非事件明确说只是部分完成、跳过该计划或仍未完成。"
        "如果 query 用“和/以及/and”同时询问多个 workflow 组件是否完成，slot value 必须逐项覆盖这些组件；"
        "不能只回答最后一个 execution_log。support_events 应保留每个组件对应的计划/执行记录。"
        "如果某个组件只有 plan 事件，而其完成状态由后续完整 workflow/run 推断，support_events 仍必须保留该组件的 plan 事件。"
        "Support Auditor 只能删除 candidate_locked_state 中的多余事实和 support_events，不能新增 candidate 中没有的 event_id。"
        "除非 query 或 slot 明确询问 deadline/date/time，否则不要把截止日期、提交时间或旧日期加入 remaining_work。"
        "如果删除某个事实后对应事件不再支撑任何 slot，必须从 support_events 和 evidence_events 中移除。"
    )


def support_auditor_user_prompt(
    case: QueryCase,
    visible_events: Sequence[Dict[str, object]],
    locked_state: Dict[str, object],
    validation_error: Optional[Dict[str, object]] = None,
) -> str:
    payload: Dict[str, object] = {
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "time_roles": list(case.time_roles),
        "output_slots": list(case.output_slots),
        "visible_event_ids": sorted(event_ids_from_visible_events(visible_events)),
        "visible_events": list(visible_events),
        "candidate_locked_state": {
            "evidence_events": locked_state.get("evidence_events", []),
            "state_slots": locked_state.get("state_slots", {}),
        },
        "task": (
            "审计 candidate_locked_state。只删除或改写不属于当前 output_slot 的背景/旧事实，"
            "并同步收紧 support_events/evidence_events。不要新增 visible_events 里没有的事实。"
        ),
    }
    if validation_error is not None:
        payload["previous_output_error"] = {
            "problem": "previous support auditor output used event ids that are not in visible_event_ids",
            "dropped_invalid_event_ids": validation_error.get("dropped_invalid_event_ids", []),
            "required_fix": (
                "Rewrite the full JSON. Every evidence_events/support_event/support_events value must be copied "
                "exactly from visible_event_ids."
            ),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def complete_validated_support_auditor(
    client: LLMClient,
    case: QueryCase,
    visible_events: Sequence[Dict[str, object]],
    locked_state: Dict[str, object],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    system = support_auditor_system_prompt()
    raw = client.complete_json(system, support_auditor_user_prompt(case, visible_events, locked_state))
    repaired, validation = validate_and_repair_event_ids(raw, visible_events, case)
    repaired, subset_guard = restrict_auditor_to_candidate_events(repaired, locked_state, case)
    validation["support_auditor_subset_guard"] = subset_guard
    if validation["dropped_invalid_event_ids"]:
        retry_raw = client.complete_json(
            system,
            support_auditor_user_prompt(case, visible_events, locked_state, validation),
        )
        retry_repaired, retry_validation = validate_and_repair_event_ids(retry_raw, visible_events, case)
        retry_repaired, retry_subset_guard = restrict_auditor_to_candidate_events(retry_repaired, locked_state, case)
        retry_validation["support_auditor_subset_guard"] = retry_subset_guard
        retry_validation["retry_after_invalid_event_ids"] = {
            "initial_validation": validation,
            "retry_used": True,
        }
        retry_trace = retry_repaired.get("pipeline_trace", {})
        if not isinstance(retry_trace, dict):
            retry_trace = {}
        retry_trace["event_id_validation"] = retry_validation
        retry_repaired["pipeline_trace"] = retry_trace
        return retry_repaired, retry_validation
    return repaired, validation

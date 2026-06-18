from __future__ import annotations

import json
from typing import Dict, Sequence

from Experiment.run.common.models import QueryCase
from Experiment.common import BaselinePromptSpec


def system_prompt() -> str:
    return (
        "你是一个长期记忆系统评测器。你必须只基于用户给出的事件作答。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}, '
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "state_slots 只能包含用户要求的 output_slots。support_event 和 support_events 必须来自可见事件。"
        "如果一个 slot 需要多个事件共同支撑，必须在 support_events 中全部列出；support_event 放最直接的主证据。"
        "slot value 必须忠实保留支撑事件中的具体对象、风险来源和结论；"
        "不要把相邻事件里的后续决策、原因或替代方向泛化成另一个 slot 的 value。"
        "如果查询询问某事项是否已经完成、提交、补完、复核或训练完成，而证据只有计划、待办、草稿、"
        "待补或未复核记录，没有明确完成记录，必须回答“无法确认已经完成/提交/补完”；"
        "不能改写成“未完成”“尚未完成”“not_submitted”。只有事件明确说未完成时才可断言未完成。"
        "coverage_check 必须逐项列出所有 output_slots，并标明 answer 是否已经显式覆盖该 slot。"
    )


def retriever_system_prompt(readout_policy: str = "baseline") -> str:
    support_minimizer_rules = (
        "当前 readout_policy=minimized_no_background；以下规则优先于用户 payload 中 instruction 的泛化聚合规则。"
        "support_events 必须是支撑该 slot value 的最小必要集合；"
        "support_events 要按 slot 独立最小化，不能因为某事件支撑另一个 slot 就列入当前 slot。"
        "不要加入只提供背景、相邻计划、旧误判、被否定方案或其他 slot 信息的事件。"
        "current/latest 查询下的 completed_item 不是历史完成清单；"
        "除非 query 明确询问所有历史完成项，否则不要累积更早的初始化、草稿、提纲或准备性完成记录。"
        "如果 output_slots 已经把 remaining_work 和 completed_item 拆成两个 slot，"
        "remaining_work 只写仍需处理的工作及其处置要求，completed_item 只写明确完成的事项。"
        "如果 query 问“主要质量问题/当前问题/issue 是什么”，current_issue 只写直接的问题事实，"
        "不要混入进度、复核状态、质量确认状态或下一步计划。"
        "如果 query 问某事是否已经完成，completion_status 应写成“只有...计划/安排，没有完成记录，"
        "因此无法确认已经完成”；除非 query 明确询问日期，否则不要加入具体日期。"
        "如果 query 问“能否直接说/是否仍然成立/现在还是不是”，slot value 必须包含明确的不能/不是/已不成立结论，"
        "以及使旧判断失效的当前规则或当前证据。"
        "这类 query 的 support_events 必须同时包含被判断的旧说法/旧前提事件和当前纠正/当前规则事件。"
        "如果 query 问 event_f1 第一能不能直接说最好，support_events 必须同时包含旧排序口径、"
        "当前主排序规则，以及说明 event_f1 第一代表最好属于旧口径的事件，不能只保留当前主排序规则。"
        "如果 output_slot 是 diagnostic_metric，value 必须写清该诊断指标不单独决定方法优劣，不能只写指标名。"
        "如果某指标从旧主排序/旧判断依据降为当前诊断指标，diagnostic_metric 的 support_events 必须同时包含旧口径事件和当前口径事件。"
        "如果 query 问某个限制/额度/故障“怎么处理”，只写处理方式；不要混入 endpoint ping、全量 run 进展、"
        "后续风险、cache 或成本，除非 query 明确询问这些。"
        "这类 query 的 support_events 必须同时包含限制/额度/故障本身的事件和当前处理决策事件。"
        "如果处理方式是 provider 角色拆分，必须保留每个 provider 仍负责什么、切换到什么 provider 负责什么；"
        "不要只保留被切换的那一半。"
        "如果 query 问计划事项是否做完，且可见事件中已有 execution_log / 完成记录，"
        "不要按 unknown_current 模板回答无法确认；必须把计划和后续执行记录合并为当前状态。"
        "如果后续 execution_log 记录了依赖该计划的完整 workflow/run 已完成并产出结果，"
        "应视为该计划对应流程已完成，除非事件明确说只是部分完成、跳过该计划或仍未完成。"
        "如果 query 用“和/以及/and”同时询问多个 workflow 组件是否完成，slot value 必须逐项覆盖这些组件；"
        "不能只回答最后一个 execution_log。support_events 应包含每个组件对应的计划/执行记录。"
        "如果某个组件只有 plan 事件，而其完成状态由后续完整 workflow/run 推断，support_events 仍必须保留该组件的 plan 事件。"
        "不要补全支撑事件和 query 中没有明确给出的年份、日期、时刻或数值。"
        "如果 visible_events 中有 state_role=invalidated_context_only 的事件，它只能用于 invalidated_*、corrected_*、"
        "resolved_* 或 query 明确询问旧状态是否仍成立的 slot；其他当前状态 slot 不能把它列入 support_events。"
        if readout_policy == "minimized_no_background"
        else ""
    )
    return (
        "你是 Scope-Time-State Retriever。你必须只基于用户给出的事件选择当前有效状态证据。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}'
        "}。"
        "state_slots 只能包含用户要求的 output_slots。support_event 和 support_events 必须来自可见事件。"
        "所有 event_id 必须逐字复制 visible_events[].event_id，不能缩写成 e1/e2/e3 这类局部编号。"
        "state_slots.*.value 必须是自然语言状态，不要把 event_id 写进 value；event_id 只能放在 evidence/support 字段。"
        "如果一个 slot 需要多个事件共同支撑，必须在 support_events 中全部列出；support_event 放最直接的主证据。"
        "slot value 必须忠实保留支撑事件中的具体对象、风险来源和结论；"
        "不要把相邻事件里的后续决策、原因或替代方向泛化成另一个 slot 的 value。"
        f"{support_minimizer_rules}"
        "如果 query 明确对比实际发生/完成时间与记录/提到时间，slot value 必须同时保留这两个时间角色；"
        "不能只写实际发生的事件或只写记录时间。"
        "如果 query 问旧状态/旧错误是否“现在还是”成立，slot value 必须同时保留旧状态是什么、"
        "以及新的修复/验证/通过记录如何改变当前状态；support_events 应包含旧状态事件和新状态事件。"
        "如果 slot 名包含 remaining、risk 或 query 问剩余风险/剩余工作，slot value 必须同时保留风险本身"
        "和同一证据中给出的处置要求、保留动作或后续约束；不能只列风险名。"
        "如果旧 root cause、旧判断或旧方案后来被纠正，当前 root_cause/current_* slot 只写当前有效原因/状态；"
        "除非 output_slot 明确要求 invalidated_*，否则不要把被否定的旧原因写进当前 slot value。"
        "如果查询询问某事项是否已经完成、提交、补完、复核或训练完成，而证据只有计划、待办、草稿、"
        "待补或未复核记录，没有明确完成记录，slot value 必须同时保留两部分："
        "1) 只有哪个计划/安排/待办/草稿/待补/未复核记录；"
        "2) 没有明确完成/提交/补完/复核完成记录，因此无法确认已经完成/提交/补完；"
        "不能改写成“未完成”“尚未完成”“not_submitted”。只有事件明确说未完成时才可断言未完成。"
        "evidence_events 必须是所有 support_events 的去重集合。不要输出 answer 或 coverage_check。"
    )


STATE_FRAME_SCHEMA = {
    "atomic_state": "单一当前状态事实。",
    "time_gap": "需要同时保留 actual/occurred/completed time 与 mentioned/recorded time 的状态。",
    "old_to_current": "旧状态、旧错误、旧判断或旧方案被新证据修正后的当前状态。",
    "remaining_risk": "风险、剩余问题或剩余工作，必须包含风险对象和处置要求/后续约束。",
    "unknown_completion": "只有计划、待办、草稿、待补或未复核记录，缺少完成/提交/补完/复核完成记录。",
    "multi_facet_state": "多个并列 facet 共同构成的当前状态摘要。",
}


def state_frame_system_prompt() -> str:
    return (
        "你是 Scope-Time-State StateFrame Builder。你的任务是把上游锁定的 state_slots 转换为类型化状态帧，"
        "不重新检索证据，不新增事实，不改写 state_slots。输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"typed_state_frames": {'
        '"slot_name": {'
        '"frame_type": "atomic_state|time_gap|old_to_current|remaining_risk|unknown_completion|multi_facet_state", '
        '"claim": "string", '
        '"components": {"component_name": "string"}, '
        '"support_events": ["event_id"], '
        '"background_events": ["event_id"], '
        '"coverage_obligations": ["string"]'
        "}"
        "}, "
        '"support_checks": {"slot_name": {"status": "ok|needs_attention", "notes": ["string"]}}'
        "}。"
        "typed_state_schema="
        f"{json.dumps(STATE_FRAME_SCHEMA, ensure_ascii=False)}。"
        "必须为每个 output_slot 生成一个 typed_state_frame。claim 必须等于或语义忠实于 locked_state_slots[slot].value。"
        "support_events 只能来自 locked_state_slots[slot].support_events；background_events 只能来自 visible_events，"
        "且不能作为当前状态支撑。coverage_obligations 是最终 answer 必须逐项覆盖的最小语义义务。"
        "如果 value 包含时间对比、旧状态到当前状态、剩余风险、unknown-current completion 或多 facet，"
        "必须拆进 components 和 coverage_obligations，不能压缩成一句泛化结论。"
    )


def user_prompt(spec: BaselinePromptSpec, case: QueryCase) -> str:
    payload = {
        "variant": spec.name,
        "instruction": spec.instruction,
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "time_roles": list(case.time_roles),
        "output_slots": list(case.output_slots),
        "visible_events": spec.visible_events,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def state_frame_user_prompt(
    case: QueryCase,
    visible_events: Sequence[Dict[str, object]],
    locked_raw: Dict[str, object],
) -> str:
    payload = {
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "time_roles": list(case.time_roles),
        "output_slots": list(case.output_slots),
        "visible_events": list(visible_events),
        "locked_evidence_events": locked_raw.get("evidence_events", []),
        "locked_state_slots": locked_raw.get("state_slots", {}),
        "task": (
            "把 locked_state_slots 转换为 typed_state_frames。不要新增 slot，不要新增事实，"
            "不要使用 locked support_events 之外的 event_id 作为 support_events。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def composer_system_prompt(readout_policy: str = "baseline") -> str:
    no_background_rules = (
        "answer 只能表达 locked_state_slots 中的 value；不能把 value 外的背景事实写进 answer。"
        "如果 value 只包含当前有效状态，answer 不能额外解释旧误判、旧原因、旧方案或被否定背景。"
        "如果 value 没有明确年份、日期、时刻或数值，answer 不能自行补全年份、日期、时刻或数值。"
        if readout_policy == "minimized_no_background"
        else ""
    )
    return (
        "你是 Answer Composer。你只能把上游锁定的 state_slots 写成最终自然语言答案。"
        "不能新增、删除或修改 evidence_events、support_event、support_events、state_slots 的值。"
        "如果输入包含 typed_state_frames 和 coverage_obligations，你必须按这些 obligations 组织答案。"
        f"{no_background_rules}"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "answer 必须逐项覆盖所有 output_slots，且要覆盖每个 locked_state_slots[slot].value 的完整语义；"
        "不能只写简短结论，不能删掉 value 中的时间、旧状态背景、风险对象、处置要求、无完成记录 basis 或并列下一步。"
        "尤其不能漏掉风险、已解决问题、已作废旧状态、剩余工作、未复核状态和并列下一步。"
        "如果 value 同时包含实际发生时间和记录/提到时间，answer 必须两个都写。"
        "如果 value 包含旧状态和当前修正状态，answer 必须明确旧状态已被当前证据更新，不能只写当前可用。"
        "如果 value 包含剩余风险和处置要求，answer 必须两个都写。"
        "如果 locked_state_slots 写的是“当前证据只显示...；没有明确...记录，因此无法确认...”，"
        "answer 必须同时保留证据 basis 和无法确认结论，不能只输出“无法确认”。"
        "如果 locked_state_slots 写的是“只有...安排/计划，没有完成记录”，answer 必须保留这句话的两部分。"
        "不能改写成确定的“未完成”“尚未完成”或“未提交”。"
    )


def composer_user_prompt(
    case: QueryCase,
    visible_events: Sequence[Dict[str, object]],
    locked_raw: Dict[str, object],
    state_frame_trace: Dict[str, object],
    readout_policy: str = "baseline",
) -> str:
    payload = {
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "output_slots": list(case.output_slots),
        "locked_evidence_events": locked_raw.get("evidence_events", []),
        "locked_state_slots": locked_raw.get("state_slots", {}),
        "typed_state_frames": state_frame_trace.get("typed_state_frames", {}),
        "coverage_obligations": state_frame_trace.get("coverage_obligations", {}),
        "support_verification": state_frame_trace.get("support_verification", {}),
        "task": (
            "只根据 locked_state_slots 和 typed_state_frames 写 answer，并输出 coverage_check。"
            "coverage_check 中每个 slot 为 true 才表示 answer 明确覆盖了该 slot 的 value。"
        ),
    }
    if readout_policy == "baseline":
        payload["visible_events"] = list(visible_events)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def verifier_system_prompt(readout_policy: str = "baseline") -> str:
    no_background_rules = (
        "如果原 answer 写入 locked_state_slots value 之外的背景事实、被否定旧判断、旧误判、额外日期/年份/时刻或额外数值，"
        "必须删除这些内容。"
        if readout_policy == "minimized_no_background"
        else ""
    )
    return (
        "你是 Coverage Verifier。你只能检查并改写 answer，不能改 state_slots 或证据。"
        "如果输入包含 coverage_obligations，你必须逐项检查 answer 是否覆盖这些 obligations。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "如果原 answer 漏掉任一 output slot，就重写 answer，直到每个 slot 的核心 value 都被明确表达。"
        "coverage_check 中某个 slot 只有在 answer 覆盖该 slot value 的完整语义时才为 true；"
        "如果 answer 只覆盖简短结论但漏掉 value 中的时间、旧状态背景、风险对象、处置要求、无完成记录 basis 或并列动作，"
        "必须改写 answer 并把这些内容补回。"
        "不要加入 locked_state_slots 之外的新事实。不能修改 support_event 或 support_events。"
        f"{no_background_rules}"
        "如果 locked_state_slots 写的是“当前证据只显示...；没有明确...记录，因此无法确认...”，"
        "修正后的 answer 必须同时保留证据 basis 和无法确认结论，不能只输出“无法确认”。"
        "如果 locked_state_slots 写的是“只有...安排/计划，没有完成记录”，修正后的 answer 必须保留这句话的两部分。"
        "不能改写成确定的“未完成”“尚未完成”或“未提交”。"
    )


def verifier_user_prompt(
    case: QueryCase,
    locked_raw: Dict[str, object],
    answer_raw: Dict[str, object],
    state_frame_trace: Dict[str, object],
) -> str:
    payload = {
        "query": case.query,
        "output_slots": list(case.output_slots),
        "locked_state_slots": locked_raw.get("state_slots", {}),
        "typed_state_frames": state_frame_trace.get("typed_state_frames", {}),
        "coverage_obligations": state_frame_trace.get("coverage_obligations", {}),
        "support_verification": state_frame_trace.get("support_verification", {}),
        "draft_answer": answer_raw.get("answer", ""),
        "draft_coverage_check": answer_raw.get("coverage_check", {}),
        "task": "只修正 answer 和 coverage_check，不要输出或修改 evidence_events/state_slots/support_events。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

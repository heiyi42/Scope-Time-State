from __future__ import annotations

import json
from typing import Dict, Optional, Sequence

from Experiment.common import BaselinePromptSpec
from Experiment.run.run_public_benchmark.types import PublicCase
from Experiment.run.run_public_benchmark.utils import normalize_public_output, public_visible_event_ids


def public_system_prompt() -> str:
    return (
        "你是长期记忆系统的 End-to-End 回答器。你只能基于用户给出的 visible_events 作答。"
        "你看不到 hidden output_slots、gold_state_slots 或 gold support。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"facets": [{"name": "short_facet_name", "value": "string", "support_events": ["event_id"]}], '
        '"answer": "string"'
        "}。"
        "facets 是你自由识别的状态字段；每个 facet 必须有清晰 value 和来自 visible_events 的 support_events。"
        "evidence_events 必须是所有 support_events 的去重集合。"
        "answer 必须覆盖所有你认为与 query 相关的状态 facet。"
        "不要编造事件中没有的信息。"
    )


def public_user_prompt(spec: BaselinePromptSpec, case: PublicCase) -> str:
    payload = {
        "variant": spec.name,
        "instruction": spec.instruction,
        "query": case.query,
        "operation": case.operation,
        "visible_events": spec.visible_events,
        "task": (
            "自由识别 query 需要的状态 facets，输出 facets、evidence_events 和 answer。"
            "不要请求或假设 hidden output_slots。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def public_retriever_system_prompt() -> str:
    return (
        "你是 Scope-Time-State public State Retriever。你只能基于用户给出的 visible_events "
        "自由识别 query 需要的当前状态 facets，不写最终自然语言 answer。"
        "你看不到 hidden output_slots、gold_state_slots 或 gold support。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"facets": [{"name": "short_facet_name", "value": "string", "support_events": ["event_id"]}]'
        "}。"
        "facets 是 public setting 下自由生成的状态字段；每个 facet 必须有清晰 value 和来自 visible_events 的 support_events。"
        "所有 event_id 必须逐字复制 visible_events[].event_id，不能缩写成 e1/e2/e3。"
        "evidence_events 必须是所有 support_events 的去重集合。"
        "对项目最近怎么样、当前状态、下一步、风险、问题在哪这类查询，必须保留所有关键当前 facet："
        "当前决策、当前风险/问题、下一步、已作废旧判断、已完成事项和剩余工作；不能只取最新一条事件。"
        "如果 query 问下一步，而同一证据还说明当前决策或方向切换，也要把当前决策作为 facet 输出。"
        "如果 query 问风险，必须输出具体风险来源以及被该风险影响或替代的旧方向；不要把无关 baseline 提及当作风险。"
        "invalidated、resolved、corrected 这类 facet 往往需要旧事件和纠正/替代事件共同支撑。"
        "remaining、risk 或剩余风险/剩余工作类 facet 必须同时写风险/剩余项和同一证据里的处置要求、"
        "保留动作或后续约束，不能只列风险名。"
        "最近复述、随口提到、复盘旧判断、无新结论这类事件只能用来避免被误导，不能作为当前状态 facet。"
        "不要创建项目整体是否完成的额外 facet；只有事件明确记录某个子任务已完成时，才能输出该 completed facet。"
        "如果查询询问是否已经完成、提交、补完、复核或训练完成，而证据只有计划、待办、草稿、"
        "待补或未复核记录，没有明确完成记录，必须输出“无法确认已经完成/提交/补完”；"
        "不能改写成确定的“未完成”“尚未完成”或“未提交”。"
        "不要编造事件中没有的信息。"
    )


def public_retriever_user_prompt(
    spec: BaselinePromptSpec,
    case: PublicCase,
    validation_error: Optional[Dict[str, object]] = None,
) -> str:
    payload: Dict[str, object] = {
        "variant": spec.name,
        "instruction": spec.instruction,
        "query": case.query,
        "operation": case.operation,
        "visible_event_ids": sorted(public_visible_event_ids(spec.visible_events)),
        "visible_events": spec.visible_events,
        "task": (
            "在 public End-to-End setting 下执行 state retrieval：自由识别 query 需要的状态 facets，"
            "输出 facets 和 evidence_events。不要输出 answer，不要请求或假设 hidden output_slots。"
        ),
    }
    if validation_error is not None:
        payload["previous_output_error"] = {
            "problem": "previous retriever output used event ids that are not in visible_event_ids",
            "dropped_invalid_event_ids": validation_error.get("dropped_invalid_event_ids", []),
            "required_fix": (
                "Rewrite the full JSON. Every evidence_events/support_events value must be copied "
                "exactly from visible_event_ids. Do not use short ids such as e1/e2/e3."
            ),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def public_composer_system_prompt() -> str:
    return (
        "你是 Scope-Time-State public Answer Composer。你只能把上游锁定的 facets 写成最终自然语言答案。"
        "不能新增、删除或修改 evidence_events、facets 或 support_events。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        'JSON schema: {"coverage_check": {"facet_index_or_name": true or false}, "answer": "string"}。'
        "answer 必须覆盖每个 locked facet 的完整语义，不能只写简短结论。"
        "不能加入 locked facets 之外的新事实。"
        "如果 facet value 包含旧状态和当前修正状态，answer 必须明确旧状态已被当前证据更新。"
        "如果 facet value 包含剩余风险和处置要求，answer 必须两个都写。"
        "如果 facet value 写的是只有计划/安排/草稿/待补/未复核记录且无法确认完成，"
        "answer 必须同时保留证据 basis 和无法确认结论，不能改写成确定的未完成/未提交。"
    )


def public_composer_user_prompt(case: PublicCase, locked_raw: Dict[str, object]) -> str:
    pred_events, pred_facets, _ = normalize_public_output(locked_raw)
    payload = {
        "query": case.query,
        "operation": case.operation,
        "locked_evidence_events": pred_events,
        "locked_facets": pred_facets,
        "task": "只根据 locked_facets 写 answer，并输出 coverage_check。不要新增 facet 或 event_id。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def public_verifier_system_prompt() -> str:
    return (
        "你是 Scope-Time-State public Coverage Verifier。你只能检查并改写 answer，不能改 facets 或证据。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        'JSON schema: {"coverage_check": {"facet_index_or_name": true or false}, "answer": "string"}。'
        "如果 draft_answer 漏掉任一 locked facet，就重写 answer，直到每个 facet 的核心 value 都被明确表达。"
        "不要加入 locked facets 之外的新事实。"
        "如果 locked facet 写的是只有计划/安排/草稿/待补/未复核记录且无法确认完成，"
        "修正后的 answer 必须同时保留证据 basis 和无法确认结论；不能改写成确定的未完成、尚未完成或未提交。"
    )


def public_verifier_user_prompt(
    case: PublicCase,
    locked_raw: Dict[str, object],
    draft_raw: Dict[str, object],
) -> str:
    pred_events, pred_facets, _ = normalize_public_output(locked_raw)
    payload = {
        "query": case.query,
        "operation": case.operation,
        "locked_evidence_events": pred_events,
        "locked_facets": pred_facets,
        "draft_answer": draft_raw.get("answer", ""),
        "draft_coverage_check": draft_raw.get("coverage_check", {}),
        "task": "只修正 answer 和 coverage_check，不要输出或修改 evidence_events/facets/support_events。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

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


def public_state_packet_system_prompt() -> str:
    return (
        "你是 Scope-Time-State public StatePacket Constructor。你只能基于用户给出的 visible_events "
        "构造 query-conditioned state_packet，不写最终自然语言 answer。"
        "你看不到 hidden output_slots、gold_state_slots 或 gold support。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"state_packet": {'
        '"predicted_scope": {"scope_id": "string or null", "confidence": 0.0, "reason": "string"}, '
        '"time_roles": ["updated_at"], '
        '"candidate_events": ["event_id"], '
        '"claims": [{"claim_id": "string", "event_id": "event_id", "facet_type": "string", '
        '"value": "atomic claim text", "claim_type": "decision|risk|plan|completion|mention|correction|observation"}], '
        '"relations": [{"type": "CORRECTS|SUPERSEDES|INVALIDATES|CONFLICTS_WITH|SUPPORTS", '
        '"from": "claim_id", "to": "claim_id", "evidence_event_ids": ["event_id"], "reason": "string"}], '
        '"rejected_claims": [{"claim_id": "claim_id", "event_id": "event_id", '
        '"reason": "stale|mention_only|plan_only|superseded|non_update|irrelevant"}], '
        '"state_facets": [{"name": "short_facet_name", "value": "current valid state text", '
        '"status": "active|unknown_current|insufficient_evidence|superseded_or_corrected|conflict_unresolved", '
        '"support_claims": ["claim_id"], "support_events": ["event_id"]}]'
        "}"
        "}。"
        "state_facets 是 public setting 下自由生成的状态字段；每个 facet 必须有清晰 value 和来自 visible_events 的 support_events。"
        "所有 event_id 必须逐字复制 visible_events[].event_id，不能缩写成 e1/e2/e3。"
        "candidate_events 是被考虑过的候选事件；它不是最终证据集合。"
        "claims 必须是从 candidate_events 中抽出的原子状态断言；claim_id 必须在当前输出内唯一。"
        "relations 只描述 claim 之间的纠错、覆盖、失效、冲突或支撑关系；不能把无关系的事件硬连边。"
        "rejected_claims 必须说明为什么最近复述、旧计划、无状态更新日志或过时 claim 不能作为当前状态。"
        "最终 evidence 会由 state_facets[*].support_events 自动派生，所以 support_events 必须最小但充分。"
        "对项目最近怎么样、当前状态、下一步、风险、问题在哪这类查询，必须保留所有关键当前 facet："
        "当前决策、当前风险/问题、下一步、已作废旧判断、已完成事项和剩余工作；不能只取最新一条事件。"
        "如果 query 问下一步，而同一证据还说明当前决策或方向切换，也要把当前决策作为 facet 输出。"
        "如果 query 问风险，必须输出具体风险来源以及被该风险影响或替代的旧方向；不要把无关 baseline 提及当作风险。"
        "invalidated、resolved、corrected 这类 facet 往往需要旧 claim 和纠正/替代 claim 共同支撑。"
        "remaining、risk 或剩余风险/剩余工作类 facet 必须同时写风险/剩余项和同一证据里的处置要求、"
        "保留动作或后续约束，不能只列风险名。"
        "最近复述、随口提到、复盘旧判断、无新结论这类事件只能用来避免被误导，不能作为当前状态 facet。"
        "不要创建项目整体是否完成的额外 facet；只有事件明确记录某个子任务已完成时，才能输出该 completed facet。"
        "如果查询询问是否已经完成、提交、补完、复核或训练完成，而证据只有计划、待办、草稿、"
        "待补或未复核记录，没有明确完成记录，必须输出“无法确认已经完成/提交/补完”；"
        "不能改写成确定的“未完成”“尚未完成”或“未提交”。"
        "不要编造事件中没有的信息。"
    )


def public_state_packet_user_prompt(
    spec: BaselinePromptSpec,
    case: PublicCase,
    routed_scope: Optional[str],
    routed_time_role: Optional[str],
    validation_error: Optional[Dict[str, object]] = None,
) -> str:
    payload: Dict[str, object] = {
        "variant": spec.name,
        "instruction": spec.instruction,
        "query": case.query,
        "operation": case.operation,
        "public_scope_hint": routed_scope,
        "public_time_role_hint": routed_time_role,
        "visible_event_ids": sorted(public_visible_event_ids(spec.visible_events)),
        "visible_events": spec.visible_events,
        "task": (
            "在 public End-to-End setting 下执行 Scope-Time-State state construction："
            "自由识别 query 需要的状态 facets，先构造 claims、validity relations、rejected_claims，"
            "再输出 state_packet.state_facets。不要输出 answer，不要请求或假设 hidden output_slots。"
        ),
    }
    if validation_error is not None:
        payload["previous_output_error"] = {
            "problem": "previous state_packet was invalid or used event ids that are not in visible_event_ids",
            "dropped_invalid_event_ids": validation_error.get("dropped_invalid_event_ids", []),
            "schema_warnings": validation_error.get("schema_warnings", []),
            "required_fix": (
                "Rewrite the full JSON with state_packet. Every candidate_events, claims[].event_id, "
                "relations[].evidence_event_ids, rejected_claims[].event_id, and "
                "state_facets[].support_events value must be copied exactly from visible_event_ids. "
                "Do not use short ids such as e1/e2/e3."
            ),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def public_state_facet_repair_system_prompt() -> str:
    return (
        "你是 Scope-Time-State public Facet Repairer。上游已经给出 query-conditioned "
        "state_packet，但 state_facets 为空或不完整。你只能基于 visible_events 和 "
        "state_packet 中的 candidate_events、claims、relations、rejected_claims 补全 state_facets。"
        "你看不到 hidden output_slots、gold_state_slots 或 gold support。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        'JSON schema: {"state_facets": [{"name": "short_facet_name", '
        '"value": "current valid state text", '
        '"status": "active|unknown_current|insufficient_evidence|superseded_or_corrected|conflict_unresolved", '
        '"support_claims": ["claim_id"], "support_events": ["event_id"]}], "repair_notes": "string"}。'
        "所有 event_id 必须逐字复制 visible_events[].event_id。"
        "如果 claims 为空或遗漏了 query 需要的信息，可以直接从 visible_events 抽取最小充分 facet。"
        "对于下一步、当前状态、风险、质量问题、剩余工作、是否完成这类查询，只要 visible_events 有相关证据，"
        "就必须至少输出一个 state_facet。"
        "如果证据只有计划、待办、草稿、待补或未复核记录，没有明确完成记录，"
        "facet value 必须写“无法确认已经完成/提交/补完”，不能改写成确定已完成。"
        "最近复述、无新结论、旧计划、被纠正或被替代的 claim 不能单独作为当前状态；"
        "只有在解释 superseded/corrected 关系时才作为辅助证据。"
        "不要编造事件中没有的信息。"
    )


def public_state_facet_repair_user_prompt(
    case: PublicCase,
    locked_raw: Dict[str, object],
    validation_error: Dict[str, object],
    visible_events: Sequence[Dict[str, object]],
) -> str:
    payload = {
        "query": case.query,
        "operation": case.operation,
        "visible_event_ids": sorted(public_visible_event_ids(visible_events)),
        "visible_events": visible_events,
        "state_packet": locked_raw.get("state_packet", {}),
        "current_facets": locked_raw.get("facets", []),
        "validation_error": {
            "schema_warnings": validation_error.get("schema_warnings", []),
            "state_packet_invariants": validation_error.get("state_packet_invariants", {}),
        },
        "task": (
            "补全 state_facets。不要输出 answer。不要请求或假设 hidden output_slots。"
            "support_events 必须来自 visible_event_ids；support_claims 如果使用，必须来自 state_packet.claims[].claim_id。"
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

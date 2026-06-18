from __future__ import annotations

import json
from typing import Dict

from Experiment.run.common.models import EvalRow, QueryCase
from Experiment.run.common.llm_client import LLMClient


def judge_system_prompt() -> str:
    return (
        "你是一个严格的 benchmark 评测员。你的任务是评估长期记忆系统对状态查询的回答。"
        "你需要分别判断：1. 每个预测状态字段与 gold 状态字段是否语义等价；"
        "2. 最终自然语言 answer 是否整体正确覆盖 gold 状态。"
        "不要求逐字一致；但不能把缺失、相反、过度推断、错误 slot 当作正确。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"slot_scores": {"slot_name": {"score": 0 or 1, "reason": "short reason"}}, '
        '"answer_score": {"score": 0 or 1, "reason": "short reason"}, '
        '"slot_overall_score": number'
        "}。slot_overall_score 是所有 slot score 的平均值。answer_score 单独评价最终 answer。"
        "answer_score 和 slot_overall_score 必须是顶层字段，不能放进 slot_scores 里。"
    )


def judge_user_prompt(case: QueryCase, row: EvalRow) -> str:
    pred_values = {
        slot: row.pred_state_slots.get(slot, {}).get("value", "")
        for slot in case.output_slots
    }
    payload = {
        "query": case.query,
        "output_slots": list(case.output_slots),
        "gold_state_slots": case.gold_state_slots,
        "pred_state_slots": pred_values,
        "pred_answer": row.answer,
        "grading_rules": [
            "同义改写可以算正确。",
            "只要核心状态含义一致即可算正确。",
            "缺失、回答未知、回答无但 gold 有明确状态，算错误。",
            "把已完成事项误解成整个项目完成状态，算错误。",
            "把已修复问题说成仍然存在，或把仍需记录的当前问题说成无，算错误。",
            "最终 answer 需要覆盖所有 gold 状态；如果只答对一部分，answer_score 算 0。",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def slot_judge_score(judge_output: Dict[str, object], case: QueryCase) -> float:
    raw_scores = normalized_judge_output(judge_output).get("slot_scores", {})
    if not isinstance(raw_scores, dict) or not case.output_slots:
        return 0.0
    scores = []
    for slot in case.output_slots:
        item = raw_scores.get(slot)
        if not isinstance(item, dict):
            scores.append(0.0)
            continue
        try:
            scores.append(1.0 if float(item.get("score", 0)) >= 0.5 else 0.0)
        except (TypeError, ValueError):
            scores.append(0.0)
    return round(sum(scores) / len(scores), 3)


def answer_judge_score(judge_output: Dict[str, object]) -> float:
    raw_score = normalized_judge_output(judge_output).get("answer_score", {})
    if not isinstance(raw_score, dict):
        return 0.0
    try:
        return 1.0 if float(raw_score.get("score", 0)) >= 0.5 else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalized_judge_output(judge_output: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(judge_output)
    slot_scores = normalized.get("slot_scores")
    if isinstance(slot_scores, dict):
        slot_scores = dict(slot_scores)
        if "answer_score" not in normalized and isinstance(slot_scores.get("answer_score"), dict):
            normalized["answer_score"] = slot_scores.pop("answer_score")
        if "slot_overall_score" not in normalized and "slot_overall_score" in slot_scores:
            normalized["slot_overall_score"] = slot_scores.pop("slot_overall_score")
        normalized["slot_scores"] = slot_scores
    return normalized


def attach_judge_score(judge_client: LLMClient, case: QueryCase, row: EvalRow) -> EvalRow:
    raw = normalized_judge_output(judge_client.complete_json(judge_system_prompt(), judge_user_prompt(case, row)))
    row.judge_output = raw
    row.slot_value_judge = slot_judge_score(raw, case)
    row.answer_judge = answer_judge_score(raw)
    return row

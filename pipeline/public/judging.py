from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from Experiment.run.common.llm_client import LLMClient
from Experiment.run.common.metrics import (
    declared_evidence_events,
    f1,
    gold_support_event_pool,
    over_evidence_diagnostic,
    set_precision,
    set_recall,
    unknown_current_diagnostic,
)
from Experiment.run.common.models import QueryCase
from Experiment.run.run_oracle_benchmark.judging import normalized_judge_output
from Experiment.run.run_public_benchmark.types import PublicEvalRow
from Experiment.run.run_public_benchmark.utils import normalize_public_output


def public_judge_system_prompt() -> str:
    return (
        "你是严格的 End-to-End benchmark 评测员。你需要把模型自由生成的 facets/answer "
        "与 hidden gold_state_slots 对齐。"
        "不要求 facet 名称一致，只判断语义是否覆盖。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"gold_slot_scores": {"gold_slot_name": {"score": 0 or 1, "matched_pred_facets": [integer], "reason": "short reason"}}, '
        '"pred_facet_scores": [{"index": integer, "score": 0 or 1, "matched_gold_slots": ["slot_name"], "reason": "short reason"}], '
        '"answer_slot_scores": {"gold_slot_name": {"score": 0 or 0.5 or 1, "reason": "short reason"}}, '
        '"answer_score": {"score": 0 or 1, "reason": "short reason"}, '
        '"answer_score_10": {"score": integer 0 to 10, "reason": "short reason"}'
        "}。"
        "gold_slot_scores 评价每个 gold slot 是否被 pred_facets 或 pred_answer 覆盖。"
        "pred_facet_scores 评价每个预测 facet 是否被 gold 状态支持；无支撑、过度推断或矛盾的 facet 记 0。"
        "answer_slot_scores 只评价最终 answer 对每个 gold slot 的覆盖：1=完整覆盖，0.5=部分覆盖，0=未覆盖或矛盾。"
        "answer_score 是严格最终答案成功率：只有最终 answer 完整覆盖全部 gold 状态且没有矛盾时才给 1，否则给 0。"
        "answer_score_10 是 graded 最终答案质量分：10=完整正确；8-9=覆盖所有核心状态但有轻微压缩；"
        "6-7=覆盖大部分核心状态但漏掉一个重要 slot 或限定；4-5=只答对一部分；"
        "1-3=只有边缘相关信息；0=答错 scope、矛盾、编造关键事实或 answer 为空。"
    )


def public_judge_user_prompt(case: QueryCase, row: PublicEvalRow) -> str:
    payload = {
        "query": case.query,
        "operation": case.operation,
        "answerability": case.answerability,
        "gold_state_slots": case.gold_state_slots,
        "pred_facets": row.pred_facets,
        "pred_answer": row.answer,
        "grading_rules": [
            "同义改写可以算正确。",
            "只答对一部分 gold slots 时，answer_score 算 0。",
            "answer_score_10 可以给部分分，但必须根据 answer_slot_scores 和是否存在矛盾/编造来扣分。",
            "把无法确认完成/提交误写成确定未完成/未提交，算错误。",
            "预测 facet 如果不是 gold 状态的等价或必要上下文，算 unsupported。",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def score_value(value: object) -> float:
    try:
        return 1.0 if float(value) >= 0.5 else 0.0
    except (TypeError, ValueError):
        return 0.0


def score_10_value(value: object) -> Optional[float]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(10.0, max(0.0, score)), 3)


def normalized_public_judge_output(judge_output: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(judge_output)
    gold_scores = normalized.get("gold_slot_scores")
    if isinstance(gold_scores, dict):
        gold_scores = dict(gold_scores)
        if "answer_score" not in normalized and isinstance(gold_scores.get("answer_score"), dict):
            normalized["answer_score"] = gold_scores.pop("answer_score")
        if "answer_score_10" not in normalized and isinstance(gold_scores.get("answer_score_10"), dict):
            normalized["answer_score_10"] = gold_scores.pop("answer_score_10")
        if "slot_overall_score" not in normalized and "slot_overall_score" in gold_scores:
            normalized["slot_overall_score"] = gold_scores.pop("slot_overall_score")
        normalized["gold_slot_scores"] = gold_scores
    slot_scores = normalized.get("slot_scores")
    if "gold_slot_scores" not in normalized and isinstance(slot_scores, dict):
        normalized["gold_slot_scores"] = slot_scores
    return normalized


def public_judge_metrics(
    judge_output: Optional[Dict[str, object]],
    case: QueryCase,
    facet_count: int,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    if judge_output is None:
        return None, None, None, None, None
    raw = normalized_public_judge_output(normalized_judge_output(judge_output))
    gold_scores = raw.get("gold_slot_scores", raw.get("slot_scores", {}))
    slot_scores: List[float] = []
    if isinstance(gold_scores, dict):
        for slot in case.output_slots:
            item = gold_scores.get(slot)
            if isinstance(item, dict):
                slot_scores.append(score_value(item.get("score", 0)))
            else:
                slot_scores.append(0.0)
    facet_recall = round(sum(slot_scores) / len(slot_scores), 3) if slot_scores else None

    pred_scores = raw.get("pred_facet_scores", [])
    scored_facets: List[float] = []
    if isinstance(pred_scores, list):
        for item in pred_scores:
            if isinstance(item, dict):
                scored_facets.append(score_value(item.get("score", 0)))
    if facet_count and len(scored_facets) < facet_count:
        scored_facets.extend([0.0] * (facet_count - len(scored_facets)))
    facet_precision = round(sum(scored_facets) / len(scored_facets), 3) if scored_facets else None

    answer_score = raw.get("answer_score", {})
    answer_judge = score_value(answer_score.get("score", 0)) if isinstance(answer_score, dict) else 0.0
    answer_score_10 = raw.get("answer_score_10", {})
    answer_judge_10 = (
        score_10_value(answer_score_10.get("score"))
        if isinstance(answer_score_10, dict)
        else score_10_value(answer_score_10)
    )
    unsupported_claim_rate = round(1.0 - facet_precision, 3) if facet_precision is not None else None
    return facet_recall, facet_precision, answer_judge, answer_judge_10, unsupported_claim_rate


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 3)


def evaluate_public_output(
    raw: Dict[str, object],
    case: QueryCase,
    judge_output: Optional[Dict[str, object]] = None,
) -> PublicEvalRow:
    pred_events, pred_facets, answer = normalize_public_output(raw)
    pred_event_set = set(pred_events)
    gold_support_events = gold_support_event_pool(case)
    hard_negative_set = set(case.hard_negative_events)
    hard_negative_hits = sorted(pred_event_set & hard_negative_set)
    invalid_distractor_rate = (
        round(len(hard_negative_hits) / len(pred_event_set), 3)
        if pred_event_set and hard_negative_set
        else None
    )
    facet_support_sets = {
        str(facet.get("name", facet.get("index", index))): tuple(str(event_id) for event_id in facet.get("support_events", []))
        for index, facet in enumerate(pred_facets)
    }
    declared_events = declared_evidence_events(pred_events, facet_support_sets)
    over_evidence_rate, over_evidence_count = over_evidence_diagnostic(declared_events, case)
    pseudo_state_slots = {
        str(facet.get("name", facet.get("index", index))): {"value": str(facet.get("value", ""))}
        for index, facet in enumerate(pred_facets)
    }
    unknown_current_correct, unknown_current_false_completion = unknown_current_diagnostic(
        pseudo_state_slots,
        answer,
        case,
    )
    facet_recall, facet_precision, answer_judge, answer_judge_10, unsupported_claim_rate = public_judge_metrics(
        judge_output,
        case,
        len(pred_facets),
    )
    return PublicEvalRow(
        case_id=case.case_id,
        query=case.query,
        evidence_support_f1=round(f1(pred_events, gold_support_events), 3),
        evidence_precision=round(set_precision(pred_events, gold_support_events), 3),
        gold_event_recall=round(set_recall(pred_events, case.gold_events), 3),
        facet_recall=facet_recall,
        facet_precision=facet_precision,
        answer_judge=answer_judge,
        answer_judge_10=answer_judge_10,
        unsupported_claim_rate=unsupported_claim_rate,
        invalid_distractor_rate=invalid_distractor_rate,
        over_evidence_rate=over_evidence_rate,
        over_evidence_count=over_evidence_count,
        unknown_current_correct=unknown_current_correct,
        unknown_current_false_completion=unknown_current_false_completion,
        hard_negative_hits=hard_negative_hits,
        difficulty_tags=case.difficulty_tags,
        answerability=case.answerability,
        pred_events=pred_events,
        pred_facets=pred_facets,
        answer=answer,
        raw_output=raw,
        judge_output=judge_output,
    )


def attach_public_judge_score(judge_client: LLMClient, case: QueryCase, row: PublicEvalRow) -> PublicEvalRow:
    raw = judge_client.complete_json(public_judge_system_prompt(), public_judge_user_prompt(case, row))
    raw = normalized_public_judge_output(raw)
    row.judge_output = raw
    (
        row.facet_recall,
        row.facet_precision,
        row.answer_judge,
        row.answer_judge_10,
        row.unsupported_claim_rate,
    ) = public_judge_metrics(
        raw,
        case,
        len(row.pred_facets),
    )
    return row

from __future__ import annotations

from collections import defaultdict
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from Experiment.run.common.llm_client import LLMClient
from pipeline.external.groupmembench.loader import GroupQuestion


def normalize_text(text: Any) -> str:
    lowered = str(text or "").lower().replace("_", " ").replace("-", " ")
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def local_accuracy(gold: str, answer: str) -> float:
    gold_norm = normalize_text(gold)
    answer_norm = normalize_text(answer)
    if not gold_norm or not answer_norm:
        return 0.0
    if gold_norm == answer_norm or gold_norm in answer_norm or answer_norm in gold_norm:
        return 1.0
    gold_tokens = set(gold_norm.split())
    answer_tokens = set(answer_norm.split())
    if not gold_tokens:
        return 0.0
    overlap = len(gold_tokens & answer_tokens) / max(1, len(gold_tokens))
    return 0.5 if overlap >= 0.5 else 0.0


def judge_system_prompt() -> str:
    return (
        "You are a strict judge evaluating whether a GroupMemBench agent answer matches the gold answer. "
        "Consider paraphrases correct if they have the same meaning. Return valid JSON only."
    )


def judge_user_prompt(question: GroupQuestion, answer: str) -> str:
    payload = {
        "question": question.question,
        "gold_answer": question.answer,
        "agent_answer": answer,
        "output_schema": {"judge_answer": "Correct|Incorrect", "reasoning": "brief rationale"},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def judge_answer(judge_client: Optional[LLMClient], question: GroupQuestion, answer: str) -> Dict[str, Any]:
    if judge_client is None:
        score = local_accuracy(question.answer, answer)
        return {
            "judge_method": "local_lexical_smoke",
            "correct": score >= 1.0,
            "score": score,
            "reasoning": "Local lexical smoke metric; use --judge for official-style scoring.",
        }
    raw = judge_client.complete_json(judge_system_prompt(), judge_user_prompt(question, answer))
    final = normalize_text(raw.get("judge_answer", ""))
    correct = "correct" in final and "incorrect" not in final
    return {
        "judge_method": "llm_judge",
        "correct": correct,
        "score": 1.0 if correct else 0.0,
        "reasoning": str(raw.get("reasoning", "")),
        "raw": raw,
    }


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 4)


def trace_rate(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    values: List[float] = []
    for row in rows:
        packet = row.get("model_output", {}).get("state_packet", {})
        if not isinstance(packet, dict):
            values.append(0.0)
            continue
        if key == "scope":
            values.append(1.0 if packet.get("target_scope_id") else 0.0)
        elif key == "claim":
            values.append(1.0 if packet.get("claims") else 0.0)
        elif key == "relation":
            values.append(1.0 if packet.get("relations") else 0.0)
        elif key == "state_facet":
            values.append(1.0 if packet.get("state_facets") else 0.0)
    return mean(values)


def summarize(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_domain: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_qtype: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[str(row["domain"])].append(row)
        by_qtype[str(row["qtype"])].append(row)

    def accuracy(items: Sequence[Dict[str, Any]]) -> Optional[float]:
        return mean(float(item.get("evaluation", {}).get("score", 0.0)) for item in items)

    return {
        "n_cases": len(rows),
        "overall_accuracy": accuracy(rows),
        "accuracy_by_domain": {domain: accuracy(items) for domain, items in sorted(by_domain.items())},
        "accuracy_by_qtype": {qtype: accuracy(items) for qtype, items in sorted(by_qtype.items())},
        "trace_has_scope_rate": trace_rate(rows, "scope"),
        "trace_has_claim_rate": trace_rate(rows, "claim"),
        "trace_has_relation_rate": trace_rate(rows, "relation"),
        "trace_has_state_facet_rate": trace_rate(rows, "state_facet"),
        "abstention_accuracy": accuracy(by_qtype.get("abstention", [])) if "abstention" in by_qtype else None,
        "temporal_date_exact_match": accuracy(by_qtype.get("temporal", [])) if "temporal" in by_qtype else None,
        "update_resolution_rate": accuracy(by_qtype.get("knowledge_update", [])) if "knowledge_update" in by_qtype else None,
    }


from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from baselines.common import BaselinePromptSpec
    from baselines.registry import baseline_names, build_prompt_spec
except ModuleNotFoundError:
    from stamb_state_benchmark.baselines.common import BaselinePromptSpec
    from stamb_state_benchmark.baselines.registry import baseline_names, build_prompt_spec


BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BENCHMARK_DIR.parent


@dataclass(frozen=True)
class Event:
    event_id: str
    scope_id: str
    content: str
    event_type: str
    occurred_at: str
    mentioned_at: str
    updated_at: str
    status: str = "active"
    planned_for: Optional[str] = None
    corrects: Tuple[str, ...] = ()
    supersedes: Tuple[str, ...] = ()
    state_relevant: bool = True


@dataclass(frozen=True)
class QueryCase:
    case_id: str
    query: str
    scope_id: str
    operation: str
    time_role: str
    output_slots: Tuple[str, ...]
    gold_events: Tuple[str, ...]
    gold_state_slots: Dict[str, str]
    gold_slot_support: Dict[str, Tuple[str, ...]]


@dataclass
class EvalRow:
    case_id: str
    query: str
    event_f1: float
    event_precision: float
    gold_event_recall: float
    context_event_recall: Optional[float]
    slot_support_accuracy: float
    slot_support_f1: float
    required_support_f1: float
    slot_value_judge: Optional[float]
    answer_judge: Optional[float]
    pred_events: List[str]
    pred_state_slots: Dict[str, Dict[str, object]]
    answer: str
    raw_output: Dict[str, object]
    judge_output: Optional[Dict[str, object]]


class LLMRequestError(RuntimeError):
    def __init__(self, provider: str, model: str, endpoint: str, message: str):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.endpoint = endpoint


def load_dotenv(path: Path = PROJECT_DIR / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def load_events(path: Path) -> List[Event]:
    rows = json.loads(path.read_text())
    return [
        Event(
            event_id=row["event_id"],
            scope_id=row["scope_id"],
            content=row["content"],
            event_type=row["event_type"],
            occurred_at=row["occurred_at"],
            mentioned_at=row["mentioned_at"],
            updated_at=row["updated_at"],
            status=row.get("status", "active"),
            planned_for=row.get("planned_for"),
            corrects=tuple(row.get("corrects", [])),
            supersedes=tuple(row.get("supersedes", [])),
            state_relevant=bool(row.get("state_relevant", True)),
        )
        for row in rows
    ]


def load_cases(path: Path) -> List[QueryCase]:
    rows = json.loads(path.read_text())
    def support_values(raw: Dict[str, object]) -> Dict[str, Tuple[str, ...]]:
        normalized: Dict[str, Tuple[str, ...]] = {}
        for slot, value in raw.items():
            if isinstance(value, list):
                normalized[slot] = tuple(str(item) for item in value)
            else:
                normalized[slot] = (str(value),)
        return normalized

    return [
        QueryCase(
            case_id=row["case_id"],
            query=row["query"],
            scope_id=row["scope_id"],
            operation=row["operation"],
            time_role=row["time_role"],
            output_slots=tuple(row["output_slots"]),
            gold_events=tuple(row["gold_events"]),
            gold_state_slots=dict(row["gold_state_slots"]),
            gold_slot_support=support_values(row["gold_slot_support"]),
        )
        for row in rows
    ]


def validate_benchmark(events: Sequence[Event], cases: Sequence[QueryCase]) -> None:
    events_by_id = {event.event_id: event for event in events}
    errors: List[str] = []
    for case in cases:
        scoped_ids = {event.event_id for event in events if event.scope_id == case.scope_id}
        if not scoped_ids:
            errors.append(f"{case.case_id}: no events for scope_id={case.scope_id}")
        for event_id in case.gold_events:
            if event_id not in events_by_id:
                errors.append(f"{case.case_id}: gold event does not exist: {event_id}")
            elif event_id not in scoped_ids:
                errors.append(f"{case.case_id}: gold event outside scope: {event_id}")
        for slot in case.output_slots:
            if slot not in case.gold_state_slots:
                errors.append(f"{case.case_id}: missing gold_state_slots[{slot}]")
            if slot not in case.gold_slot_support:
                errors.append(f"{case.case_id}: missing gold_slot_support[{slot}]")
        for slot, event_ids in case.gold_slot_support.items():
            if slot not in case.output_slots:
                errors.append(f"{case.case_id}: support for unknown slot: {slot}")
            for event_id in event_ids:
                if event_id not in events_by_id:
                    errors.append(f"{case.case_id}: support event does not exist: {event_id}")
                elif event_id not in scoped_ids:
                    errors.append(f"{case.case_id}: support event outside scope: {event_id}")
                if event_id not in case.gold_events:
                    errors.append(f"{case.case_id}: support event not listed in gold_events: {event_id}")
    if errors:
        formatted = "\n".join(f"- {error}" for error in errors)
        raise RuntimeError(f"benchmark validation failed:\n{formatted}")


def f1(predicted: Iterable[str], gold: Iterable[str]) -> float:
    pred_set = set(predicted)
    gold_set = set(gold)
    if not pred_set and not gold_set:
        return 1.0
    if not pred_set or not gold_set:
        return 0.0
    tp = len(pred_set & gold_set)
    precision = tp / len(pred_set)
    recall = tp / len(gold_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def set_precision(predicted: Iterable[str], gold: Iterable[str]) -> float:
    pred_set = set(predicted)
    gold_set = set(gold)
    if not pred_set and not gold_set:
        return 1.0
    if not pred_set:
        return 0.0
    return len(pred_set & gold_set) / len(pred_set)


def set_recall(predicted: Iterable[str], gold: Iterable[str]) -> float:
    pred_set = set(predicted)
    gold_set = set(gold)
    if not pred_set and not gold_set:
        return 1.0
    if not gold_set:
        return 1.0
    return len(pred_set & gold_set) / len(gold_set)


def support_accuracy(predicted: Dict[str, Optional[str]], gold: Dict[str, Tuple[str, ...]]) -> float:
    if not gold:
        return 1.0
    correct = sum(1 for key, values in gold.items() if predicted.get(key) in values)
    return correct / len(gold)


def slot_support_f1(predicted: Dict[str, Tuple[str, ...]], gold: Dict[str, Tuple[str, ...]]) -> float:
    if not gold:
        return 1.0
    scores = []
    for slot, gold_events in gold.items():
        scores.append(f1(predicted.get(slot, ()), gold_events))
    return sum(scores) / len(scores)


def gold_support_event_pool(case: QueryCase) -> Set[str]:
    return {event_id for values in case.gold_slot_support.values() for event_id in values}


def context_events(case: QueryCase) -> Set[str]:
    return set(case.gold_events) - gold_support_event_pool(case)


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str, api_base: str, cache_path: Path, use_cache: bool):
        from openai import OpenAI

        self.provider = provider
        self.model = model
        self.api_base = api_base
        self.client = OpenAI(api_key=api_key, base_url=api_base)
        self.cache_path = cache_path
        self.use_cache = use_cache
        self.cache: Dict[str, Dict[str, object]] = {}
        if use_cache and cache_path.exists():
            self.cache = json.loads(cache_path.read_text())

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, object]:
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "api_base": self.api_base,
                    "system": system_prompt,
                    "user": user_prompt,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.use_cache and cache_key in self.cache:
            return self.cache[cache_key]

        try:
            content = self._call_chat(system_prompt, user_prompt, json_mode=True)
        except Exception as json_mode_exc:
            try:
                content = self._call_chat(system_prompt, user_prompt, json_mode=False)
            except Exception:
                raise json_mode_exc
        try:
            parsed = parse_json_object(content)
        except ValueError:
            content = self._call_chat(system_prompt, user_prompt, json_mode=False)
            parsed = parse_json_object(content)

        if self.use_cache:
            self.cache[cache_key] = parsed
            self.cache_path.parent.mkdir(exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2))
        return parsed

    def _call_chat(self, system_prompt: str, user_prompt: str, json_mode: bool) -> str:
        request: Dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            message = f"{self.provider} API request failed; model={self.model}; base_url={self.api_base}; error={exc}"
            raise LLMRequestError(self.provider, self.model, self.api_base, message) from exc
        return response.choices[0].message.content or ""


def parse_json_object(text: str) -> Dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError(f"model did not return JSON: {text[:200]}")
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model JSON output is not an object")
    return value


def provider_config(provider: str) -> Tuple[str, str, str]:
    prefix = provider.upper()
    api_key = os.environ.get(f"{prefix}_API_KEY")
    model = os.environ.get(f"{prefix}_MODEL")
    api_base = os.environ.get(f"{prefix}_API_BASE") or os.environ.get(f"{prefix}_BASE_URL")
    if not api_key:
        raise RuntimeError(f"missing {prefix}_API_KEY in .env or environment")
    if not model:
        raise RuntimeError(f"missing {prefix}_MODEL in .env or environment")
    if not api_base:
        raise RuntimeError(f"missing {prefix}_API_BASE or {prefix}_BASE_URL in .env or environment")
    return api_key, model, api_base


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
        "coverage_check 必须逐项列出所有 output_slots，并标明 answer 是否已经显式覆盖该 slot。"
    )


def retriever_system_prompt() -> str:
    return (
        "你是 Scope-Time-State Retriever。你必须只基于用户给出的事件选择当前有效状态证据。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}'
        "}。"
        "state_slots 只能包含用户要求的 output_slots。support_event 和 support_events 必须来自可见事件。"
        "如果一个 slot 需要多个事件共同支撑，必须在 support_events 中全部列出；support_event 放最直接的主证据。"
        "evidence_events 必须是所有 support_events 的去重集合。不要输出 answer 或 coverage_check。"
    )


def user_prompt(spec: BaselinePromptSpec, case: QueryCase) -> str:
    payload = {
        "variant": spec.name,
        "instruction": spec.instruction,
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "output_slots": list(case.output_slots),
        "visible_events": spec.visible_events,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def composer_system_prompt() -> str:
    return (
        "你是 Answer Composer。你只能把上游锁定的 state_slots 写成最终自然语言答案。"
        "不能新增、删除或修改 evidence_events、support_event、support_events、state_slots 的值。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "answer 必须逐项覆盖所有 output_slots，尤其不能漏掉风险、已解决问题、"
        "已作废旧状态、剩余工作、未复核状态和并列下一步。"
    )


def composer_user_prompt(case: QueryCase, visible_events: Sequence[Dict[str, object]], locked_raw: Dict[str, object]) -> str:
    payload = {
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "output_slots": list(case.output_slots),
        "visible_events": list(visible_events),
        "locked_evidence_events": locked_raw.get("evidence_events", []),
        "locked_state_slots": locked_raw.get("state_slots", {}),
        "task": (
            "只根据 locked_state_slots 写 answer，并输出 coverage_check。"
            "coverage_check 中每个 slot 为 true 才表示 answer 明确覆盖了该 slot 的 value。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def verifier_system_prompt() -> str:
    return (
        "你是 Coverage Verifier。你只能检查并改写 answer，不能改 state_slots 或证据。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "如果原 answer 漏掉任一 output slot，就重写 answer，直到每个 slot 的核心 value 都被明确表达。"
        "不要加入 locked_state_slots 之外的新事实。不能修改 support_event 或 support_events。"
    )


def verifier_user_prompt(case: QueryCase, locked_raw: Dict[str, object], answer_raw: Dict[str, object]) -> str:
    payload = {
        "query": case.query,
        "output_slots": list(case.output_slots),
        "locked_state_slots": locked_raw.get("state_slots", {}),
        "draft_answer": answer_raw.get("answer", ""),
        "draft_coverage_check": answer_raw.get("coverage_check", {}),
        "task": "只修正 answer 和 coverage_check，不要输出或修改 evidence_events/state_slots/support_events。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def merge_locked_state_with_answer(locked_raw: Dict[str, object], answer_raw: Dict[str, object]) -> Dict[str, object]:
    trace = {}
    raw_trace = locked_raw.get("pipeline_trace")
    if isinstance(raw_trace, dict):
        trace.update(raw_trace)
    trace["answer_stage_output"] = answer_raw
    return {
        "evidence_events": locked_raw.get("evidence_events", []),
        "state_slots": locked_raw.get("state_slots", {}),
        "coverage_check": answer_raw.get("coverage_check", {}),
        "answer": answer_raw.get("answer", ""),
        "pipeline_trace": trace,
    }


def normalize_support_events(item: Dict[str, object]) -> Tuple[str, ...]:
    raw_events = item.get("support_events")
    support_events: List[str] = []
    if isinstance(raw_events, list):
        support_events = [str(event_id) for event_id in raw_events if event_id not in {None, "", "null"}]
    support = item.get("support_event")
    if support not in {None, "", "null"}:
        support_text = str(support)
        if support_text not in support_events:
            support_events.insert(0, support_text)
    return tuple(support_events)


def normalize_model_output(raw: Dict[str, object], case: QueryCase) -> Tuple[List[str], Dict[str, Dict[str, object]], str]:
    evidence = raw.get("evidence_events", [])
    if not isinstance(evidence, list):
        evidence = []
    pred_events = [str(item) for item in evidence]

    state_slots: Dict[str, Dict[str, object]] = {}

    raw_slots = raw.get("state_slots", {})
    if isinstance(raw_slots, dict):
        for slot in case.output_slots:
            item = raw_slots.get(slot)
            if isinstance(item, dict):
                value = item.get("value")
                support = item.get("support_event")
                support_events = normalize_support_events(item)
                state_slots[slot] = {
                    "value": str(value) if value is not None else "",
                    "support_event": str(support) if support not in {None, "null", ""} else None,
                    "support_events": list(support_events),
                }
            elif isinstance(item, str):
                state_slots[slot] = {"value": item, "support_event": None, "support_events": []}

    answer = raw.get("answer", "")
    return pred_events, state_slots, str(answer)


def evaluate_output(raw: Dict[str, object], case: QueryCase) -> EvalRow:
    pred_events, state_slots, answer = normalize_model_output(raw, case)
    pred_support = {slot: item.get("support_event") for slot, item in state_slots.items()}
    pred_support_sets = {
        slot: tuple(str(event_id) for event_id in item.get("support_events", []))
        for slot, item in state_slots.items()
    }
    required_support_events = gold_support_event_pool(case)
    ctx_events = context_events(case)
    return EvalRow(
        case_id=case.case_id,
        query=case.query,
        event_f1=round(f1(pred_events, case.gold_events), 3),
        event_precision=round(set_precision(pred_events, case.gold_events), 3),
        gold_event_recall=round(set_recall(pred_events, case.gold_events), 3),
        context_event_recall=round(set_recall(pred_events, ctx_events), 3) if ctx_events else None,
        slot_support_accuracy=round(support_accuracy(pred_support, case.gold_slot_support), 3),
        slot_support_f1=round(slot_support_f1(pred_support_sets, case.gold_slot_support), 3),
        required_support_f1=round(f1(pred_events, required_support_events), 3),
        slot_value_judge=None,
        answer_judge=None,
        pred_events=pred_events,
        pred_state_slots=state_slots,
        answer=answer,
        raw_output=raw,
        judge_output=None,
    )


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
    raw_scores = judge_output.get("slot_scores", {})
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
    raw_score = judge_output.get("answer_score", {})
    if not isinstance(raw_score, dict):
        return 0.0
    try:
        return 1.0 if float(raw_score.get("score", 0)) >= 0.5 else 0.0
    except (TypeError, ValueError):
        return 0.0


def attach_judge_score(judge_client: LLMClient, case: QueryCase, row: EvalRow) -> EvalRow:
    raw = judge_client.complete_json(judge_system_prompt(), judge_user_prompt(case, row))
    row.judge_output = raw
    row.slot_value_judge = slot_judge_score(raw, case)
    row.answer_judge = answer_judge_score(raw)
    return row


def run_variant(
    client: LLMClient,
    judge_client: Optional[LLMClient],
    variant_name: str,
    events: Sequence[Event],
    cases: Sequence[QueryCase],
) -> Dict[str, object]:
    rows: List[EvalRow] = []
    for case in cases:
        print(f"running {variant_name} / {case.case_id}", flush=True)
        spec = build_prompt_spec(variant_name, events, case)
        if variant_name == "scope_time_state_pipeline":
            locked_state = client.complete_json(retriever_system_prompt(), user_prompt(spec, case))
            answer_raw = client.complete_json(composer_system_prompt(), composer_user_prompt(case, spec.visible_events, locked_state))
            verified_answer_raw = client.complete_json(verifier_system_prompt(), verifier_user_prompt(case, locked_state, answer_raw))
            raw = merge_locked_state_with_answer(locked_state, verified_answer_raw)
            raw["pipeline_trace"]["retriever_output"] = locked_state
            raw["pipeline_trace"]["composer_output"] = answer_raw
        else:
            raw = client.complete_json(system_prompt(), user_prompt(spec, case))
        row = evaluate_output(raw, case)
        if judge_client is not None:
            print(f"judging {variant_name} / {case.case_id}", flush=True)
            row = attach_judge_score(judge_client, case, row)
        rows.append(row)
        time.sleep(0.2)
    judge_scores = [row.slot_value_judge for row in rows if row.slot_value_judge is not None]
    answer_scores = [row.answer_judge for row in rows if row.answer_judge is not None]
    context_scores = [row.context_event_recall for row in rows if row.context_event_recall is not None]
    return {
        "variant": variant_name,
        "model_provider": client.provider,
        "model": client.model,
        "judge_provider": judge_client.provider if judge_client else None,
        "judge_model": judge_client.model if judge_client else None,
        "avg_event_f1": round(sum(row.event_f1 for row in rows) / len(rows), 3),
        "avg_event_precision": round(sum(row.event_precision for row in rows) / len(rows), 3),
        "avg_gold_event_recall": round(sum(row.gold_event_recall for row in rows) / len(rows), 3),
        "avg_context_event_recall": round(sum(context_scores) / len(context_scores), 3) if context_scores else None,
        "avg_slot_support_accuracy": round(sum(row.slot_support_accuracy for row in rows) / len(rows), 3),
        "avg_slot_support_f1": round(sum(row.slot_support_f1 for row in rows) / len(rows), 3),
        "avg_required_support_f1": round(sum(row.required_support_f1 for row in rows) / len(rows), 3),
        "avg_slot_value_judge": round(sum(judge_scores) / len(judge_scores), 3) if judge_scores else None,
        "avg_answer_judge": round(sum(answer_scores) / len(answer_scores), 3) if answer_scores else None,
        "cases": [row.__dict__ for row in rows],
    }


def print_summary(
    provider: str,
    model: str,
    results: Sequence[Dict[str, object]],
    judge_provider: Optional[str],
    judge_model: Optional[str],
) -> None:
    print("STAMB-State LLM benchmark")
    print(f"provider={provider} model={model}")
    if judge_provider and judge_model:
        print(f"judge_provider={judge_provider} judge_model={judge_model}")
    print("NOTE: these are prompt-level variants, not paper-faithful reproductions.")
    print()
    has_judge = any(result.get("avg_slot_value_judge") is not None for result in results)
    if has_judge:
        print(f"{'variant':<34} {'ev_f1':>7} {'req_f1':>7} {'ev_p':>7} {'ev_r':>7} {'support':>8} {'sup_f1':>8} {'slot_j':>8} {'ans_j':>8}")
        print("-" * 104)
    else:
        print(f"{'variant':<34} {'ev_f1':>7} {'req_f1':>7} {'ev_p':>7} {'ev_r':>7} {'support':>8} {'sup_f1':>8}")
        print("-" * 84)
    for result in results:
        base = (
            f"{result['variant']:<34} "
            f"{result['avg_event_f1']:>7.3f} "
            f"{result['avg_required_support_f1']:>7.3f} "
            f"{result['avg_event_precision']:>7.3f} "
            f"{result['avg_gold_event_recall']:>7.3f} "
            f"{result['avg_slot_support_accuracy']:>8.3f} "
            f"{result['avg_slot_support_f1']:>8.3f}"
        )
        if has_judge:
            slot_judge = result.get("avg_slot_value_judge")
            answer_judge = result.get("avg_answer_judge")
            slot_text = f"{slot_judge:>8.3f}" if isinstance(slot_judge, float) else f"{'n/a':>8}"
            answer_text = f"{answer_judge:>8.3f}" if isinstance(answer_judge, float) else f"{'n/a':>8}"
            print(f"{base} {slot_text} {answer_text}")
        else:
            print(base)
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an LLM-backed STAMB-State benchmark.")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument(
        "--variants",
        nargs="+",
        default=list(baseline_names()),
    )
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--judge", action="store_true", help="Use an LLM judge for semantic slot-value grading.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--dry-run", action="store_true", help="Validate benchmark files without calling an LLM.")
    parser.add_argument("--events", default=str(BENCHMARK_DIR / "data/events.json"))
    parser.add_argument("--cases", default=str(BENCHMARK_DIR / "data/cases.json"))
    parser.add_argument("--output", default=str(BENCHMARK_DIR / "output/results.json"))
    parser.add_argument("--cache", default=str(BENCHMARK_DIR / "output/llm_cache.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv()
    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    events = load_events(Path(args.events))
    cases = load_cases(Path(args.cases))
    validate_benchmark(events, cases)
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    if args.dry_run:
        scopes = {event.scope_id for event in events}
        print(f"valid benchmark: {len(events)} events, {len(cases)} cases, {len(scopes)} scopes")
        return 0

    client = LLMClient(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )

    judge_client: Optional[LLMClient] = None
    judge_model: Optional[str] = None
    if args.judge:
        try:
            judge_api_key, judge_model, judge_api_base = provider_config(args.judge_provider)
        except RuntimeError as exc:
            print(f"Judge config error: {exc}", file=sys.stderr)
            return 2
        judge_cache = Path(args.cache).with_name(f"{Path(args.cache).stem}.{args.judge_provider}_judge.json")
        judge_client = LLMClient(
            provider=args.judge_provider,
            model=judge_model,
            api_key=judge_api_key,
            api_base=judge_api_base,
            cache_path=judge_cache,
            use_cache=not args.no_cache,
        )

    print(f"target_provider={args.provider} target_model={model}", flush=True)
    if judge_client is not None:
        print(f"judge_provider={args.judge_provider} judge_model={judge_model}", flush=True)
    try:
        results = [run_variant(client, judge_client, variant_name, events, cases) for variant_name in args.variants]
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        if args.judge and exc.provider == args.judge_provider:
            print(
                "This happened during LLM-as-a-judge scoring. "
                "Fix the judge provider API settings, or rerun without --judge for generation-only metrics.",
                file=sys.stderr,
            )
        return 1
    print_summary(args.provider, model, results, args.judge_provider if args.judge else None, judge_model)

    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

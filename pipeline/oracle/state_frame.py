from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from Experiment.run.common.io import normalize_id_list
from Experiment.run.common.models import QueryCase
from Experiment.run.common.utils import normalize_support_events
from Experiment.run.run_oracle_benchmark.prompts import STATE_FRAME_SCHEMA
from pipeline.oracle.event_ids import event_ids_from_visible_events


def infer_state_frame_type(slot: str, value: str, case: QueryCase) -> str:
    text = f"{slot}\n{case.query}\n{value}".lower()
    if any(marker in text for marker in ("实际", "记录", "mentioned", "occurred", "recorded", "actual")):
        return "time_gap"
    if is_unknown_current_case(case) or any(
        marker in text
        for marker in (
            "无法确认",
            "没有明确完成",
            "没有完成记录",
            "没有提交记录",
            "没有复核记录",
            "only planned",
            "no completion record",
        )
    ):
        return "unknown_completion"
    if any(marker in text for marker in ("现在还是", "旧", "invalid", "修复", "通过", "不再", "纠正", "替代")):
        return "old_to_current"
    if any(marker in text for marker in ("risk", "remaining", "风险", "剩余", "仍", "还", "需要")):
        return "remaining_risk"
    if any(separator in value for separator in ("；", ";", "。")):
        return "multi_facet_state"
    return "atomic_state"


def split_coverage_obligations(slot: str, value: str) -> List[str]:
    segments = [
        segment.strip()
        for segment in re.split(r"[；;。]\s*", value)
        if segment and segment.strip()
    ]
    if not segments:
        return [f"{slot}: {value}"] if value else [f"{slot}: <empty>"]
    return [f"{slot}: {segment}" for segment in segments]


def fallback_state_frame(slot: str, slot_item: Dict[str, object], case: QueryCase) -> Dict[str, object]:
    value = str(slot_item.get("value", ""))
    support_events = list(normalize_support_events(slot_item))
    return {
        "frame_type": infer_state_frame_type(slot, value, case),
        "claim": value,
        "components": {"value": value},
        "support_events": support_events,
        "background_events": [],
        "coverage_obligations": split_coverage_obligations(slot, value),
    }


def normalize_state_frame(
    slot: str,
    raw_frame: object,
    locked_slot: Dict[str, object],
    case: QueryCase,
) -> Dict[str, object]:
    fallback = fallback_state_frame(slot, locked_slot, case)
    if not isinstance(raw_frame, dict):
        return fallback
    frame_type = str(raw_frame.get("frame_type", fallback["frame_type"]))
    if frame_type not in STATE_FRAME_SCHEMA:
        frame_type = str(fallback["frame_type"])
    claim = str(raw_frame.get("claim", fallback["claim"]))
    components = raw_frame.get("components", {})
    if not isinstance(components, dict):
        components = dict(fallback["components"])
    support_events = list(normalize_id_list(raw_frame.get("support_events")))
    if not support_events:
        support_events = list(fallback["support_events"])
    background_events = list(normalize_id_list(raw_frame.get("background_events")))
    obligations = [
        str(item)
        for item in normalize_id_list(raw_frame.get("coverage_obligations"))
        if str(item).strip()
    ]
    if not obligations:
        obligations = list(fallback["coverage_obligations"])
    return {
        "frame_type": frame_type,
        "claim": claim,
        "components": {str(key): str(value) for key, value in components.items()},
        "support_events": support_events,
        "background_events": background_events,
        "coverage_obligations": obligations,
    }


def verify_state_frame_support(
    case: QueryCase,
    visible_events: Sequence[Dict[str, object]],
    locked_raw: Dict[str, object],
    state_frame_raw: Dict[str, object],
) -> Dict[str, object]:
    visible_ids = event_ids_from_visible_events(visible_events)
    locked_slots = locked_raw.get("state_slots", {})
    raw_frames = state_frame_raw.get("typed_state_frames", {})
    if not isinstance(locked_slots, dict):
        locked_slots = {}
    if not isinstance(raw_frames, dict):
        raw_frames = {}

    typed_frames: Dict[str, Dict[str, object]] = {}
    coverage_obligations: Dict[str, List[str]] = {}
    support_checks: Dict[str, Dict[str, object]] = {}
    overall_status = "ok"

    for slot in case.output_slots:
        locked_slot = locked_slots.get(slot)
        if not isinstance(locked_slot, dict):
            locked_slot = {"value": "", "support_events": []}
        locked_support = set(normalize_support_events(locked_slot))
        raw_frame = raw_frames.get(slot)
        missing_or_invalid_frame = not isinstance(raw_frame, dict)
        frame = normalize_state_frame(slot, raw_frame, locked_slot, case)
        frame_support = set(normalize_id_list(frame.get("support_events")))
        frame_background = set(normalize_id_list(frame.get("background_events")))
        issues: List[str] = []
        repaired = False

        if missing_or_invalid_frame:
            issues.append("missing_or_invalid_typed_state_frame")
            repaired = True

        unknown_support = sorted(frame_support - visible_ids)
        if unknown_support:
            issues.append(f"support_events_not_visible={unknown_support}")
        support_outside_locked = sorted(frame_support - locked_support)
        if support_outside_locked:
            issues.append(f"support_events_not_in_locked_slot={support_outside_locked}")
        unknown_background = sorted(frame_background - visible_ids)
        if unknown_background:
            issues.append(f"background_events_not_visible={unknown_background}")
        if not str(frame.get("claim", "")).strip():
            issues.append("empty_claim")
        obligations = [
            str(item)
            for item in frame.get("coverage_obligations", [])
            if str(item).strip()
        ]
        if not obligations:
            issues.append("missing_coverage_obligations")
            obligations = split_coverage_obligations(slot, str(locked_slot.get("value", "")))

        if unknown_support or support_outside_locked:
            frame["support_events"] = sorted(locked_support)
            repaired = True
        if unknown_background:
            frame["background_events"] = sorted(frame_background & visible_ids)
            repaired = True
        if not str(frame.get("claim", "")).strip():
            frame["claim"] = str(locked_slot.get("value", ""))
            repaired = True
        frame["coverage_obligations"] = obligations

        status = "ok"
        if issues:
            status = "repaired" if repaired else "needs_attention"
            overall_status = "repaired" if repaired and overall_status == "ok" else overall_status
            if status == "needs_attention":
                overall_status = "needs_attention"
        typed_frames[slot] = frame
        coverage_obligations[slot] = obligations
        support_checks[slot] = {
            "status": status,
            "locked_support_events": sorted(locked_support),
            "frame_support_events": list(frame.get("support_events", [])),
            "notes": issues,
        }

    return {
        "typed_state_frames": typed_frames,
        "coverage_obligations": coverage_obligations,
        "support_verification": {
            "overall_status": overall_status,
            "slot_checks": support_checks,
        },
        "state_frame_builder_output": state_frame_raw,
    }


def merge_locked_state_with_answer(
    locked_raw: Dict[str, object],
    answer_raw: Dict[str, object],
    state_frame_trace: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    trace = {}
    raw_trace = locked_raw.get("pipeline_trace")
    if isinstance(raw_trace, dict):
        trace.update(raw_trace)
    if state_frame_trace is not None:
        trace["state_frame_trace"] = state_frame_trace
    trace["answer_stage_output"] = answer_raw
    return {
        "evidence_events": locked_raw.get("evidence_events", []),
        "state_slots": locked_raw.get("state_slots", {}),
        "typed_state_frames": state_frame_trace.get("typed_state_frames", {}) if state_frame_trace else {},
        "coverage_obligations": state_frame_trace.get("coverage_obligations", {}) if state_frame_trace else {},
        "support_verification": state_frame_trace.get("support_verification", {}) if state_frame_trace else {},
        "coverage_check": answer_raw.get("coverage_check", {}),
        "answer": answer_raw.get("answer", ""),
        "pipeline_trace": trace,
    }

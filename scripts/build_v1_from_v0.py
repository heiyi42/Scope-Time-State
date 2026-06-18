from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from v1_common import (
    DEFAULT_V0_DIR,
    DEFAULT_V1_DIR,
    LEGACY_DATA_DIR,
    RAW_EVENT_FIELDS,
    build_scope_splits,
    infer_difficulty_tags,
    infer_hard_negative_events,
    load_legacy_cases,
    load_legacy_events,
    normalize_id_list,
    normalize_slot_support,
    write_json,
)


CURATED_V1_CASES: List[Dict[str, Any]] = [
    {
        "case_id": "amp_late_mentioned_completion",
        "query": "微波放大器 6月7日才提到、但实际 5月20日已经完成的事项是什么？",
        "scope_id": "amp_project",
        "operation": "state_lookup",
        "time_roles": ["occurred_at", "mentioned_at"],
        "difficulty_tags": ["cross_time_constraint", "stale_mention_distractor"],
        "gold_events": ["amp_e1"],
        "hard_negative_events": ["amp_e5", "amp_e2"],
        "gold_state_slots": {
            "late_mentioned_completed_work": "第一级输入匹配实际在 5月20日已经完成，只是到 6月7日才被提到。"
        },
        "gold_slot_support": {
            "late_mentioned_completed_work": ["amp_e1"]
        },
        "output_slots": ["late_mentioned_completed_work"],
        "answerability": "answerable",
    },
    {
        "case_id": "amp_planned_recalc",
        "query": "微波放大器 6月9日计划重算什么？",
        "scope_id": "amp_project",
        "operation": "next_action",
        "time_roles": ["planned_for"],
        "difficulty_tags": ["cross_time_constraint", "plan_not_done"],
        "gold_events": ["amp_e4"],
        "hard_negative_events": ["amp_e5", "amp_e2"],
        "gold_state_slots": {
            "planned_work": "6月9日计划重算级间匹配网络线长。"
        },
        "gold_slot_support": {
            "planned_work": ["amp_e4"]
        },
        "output_slots": ["planned_work"],
        "answerability": "answerable",
    },
    {
        "case_id": "robot_planned_calibration",
        "query": "机器人导航 6月8日计划做什么？",
        "scope_id": "robot_nav",
        "operation": "next_action",
        "time_roles": ["planned_for"],
        "difficulty_tags": ["cross_time_constraint", "plan_not_done"],
        "gold_events": ["robot_e5"],
        "hard_negative_events": ["robot_e6", "robot_e1"],
        "gold_state_slots": {
            "planned_work": "6月8日计划标定 depth camera 外参。"
        },
        "gold_slot_support": {
            "planned_work": ["robot_e5"]
        },
        "output_slots": ["planned_work"],
        "answerability": "answerable",
    },
    {
        "case_id": "robot_calibration_completion_unknown",
        "query": "机器人导航 depth camera 外参已经标定完成了吗？",
        "scope_id": "robot_nav",
        "operation": "state_lookup",
        "time_roles": ["updated_at", "planned_for"],
        "difficulty_tags": ["plan_not_done", "unknown_current", "cross_time_constraint"],
        "gold_events": ["robot_e5"],
        "hard_negative_events": ["robot_e6", "robot_e2"],
        "gold_state_slots": {
            "completion_status": "无法确认已经完成；当前证据只有 6月8日计划标定 depth camera 外参，没有完成记录。"
        },
        "gold_slot_support": {
            "completion_status": ["robot_e5"]
        },
        "output_slots": ["completion_status"],
        "answerability": "insufficient_evidence",
    },
    {
        "case_id": "thesis_original_and_current_deadline",
        "query": "论文第二章原计划和当前截止时间分别是什么？",
        "scope_id": "thesis_ch2",
        "operation": "state_lookup",
        "time_roles": ["updated_at", "planned_for"],
        "difficulty_tags": ["deadline_change", "cross_time_constraint", "stale_mention_distractor", "facet_specific_validity"],
        "gold_events": ["thesis_e2", "thesis_e4"],
        "hard_negative_events": ["thesis_e6"],
        "gold_state_slots": {
            "original_deadline": "原计划是 6月8日交第二章。",
            "current_deadline": "当前提交时间已经改到 6月10日。"
        },
        "gold_slot_support": {
            "original_deadline": ["thesis_e2"],
            "current_deadline": ["thesis_e4"]
        },
        "output_slots": ["original_deadline", "current_deadline"],
        "answerability": "answerable",
    },
    {
        "case_id": "grant_submission_unknown",
        "query": "基金申请是否已经正式提交？",
        "scope_id": "grant_app",
        "operation": "state_lookup",
        "time_roles": ["updated_at"],
        "difficulty_tags": ["unknown_current", "plan_not_done"],
        "gold_events": ["grant_e5"],
        "hard_negative_events": ["grant_e6", "grant_e1"],
        "gold_state_slots": {
            "submission_status": "无法确认已经正式提交；当前证据只显示申请书草稿已上传到系统，仍待补预算说明。"
        },
        "gold_slot_support": {
            "submission_status": ["grant_e5"]
        },
        "output_slots": ["submission_status"],
        "answerability": "unknown_current",
    },
    {
        "case_id": "label_retraining_completion_unknown",
        "query": "标注员是否已经按 v2 规范重新培训完成？",
        "scope_id": "labeling_guideline",
        "operation": "state_lookup",
        "time_roles": ["updated_at", "planned_for"],
        "difficulty_tags": ["plan_not_done", "unknown_current", "cross_time_constraint"],
        "gold_events": ["label_e4"],
        "hard_negative_events": ["label_e6", "label_e1"],
        "gold_state_slots": {
            "training_status": "无法确认已经完成重新培训；当前证据只有 6月8日计划用 v2 规范重新培训标注员。"
        },
        "gold_slot_support": {
            "training_status": ["label_e4"]
        },
        "output_slots": ["training_status"],
        "answerability": "insufficient_evidence",
    },
    {
        "case_id": "incident_actual_vs_mentioned_time",
        "query": "线上事故 14:05 发生、14:10 才记录的事情是什么？",
        "scope_id": "deployment_incident",
        "operation": "state_lookup",
        "time_roles": ["occurred_at", "mentioned_at"],
        "difficulty_tags": ["cross_time_constraint"],
        "gold_events": ["inc_e1"],
        "hard_negative_events": ["inc_e6", "inc_e3"],
        "gold_state_slots": {
            "incident_event": "线上推荐服务在 14:05 出现 5xx 峰值，并在 14:10 被记录。"
        },
        "gold_slot_support": {
            "incident_event": ["inc_e1"]
        },
        "output_slots": ["incident_event"],
        "answerability": "answerable",
    },
    {
        "case_id": "incident_mitigation_time_gap",
        "query": "线上事故 14:40 实际缓解、14:45 记录的状态是什么？",
        "scope_id": "deployment_incident",
        "operation": "state_lookup",
        "time_roles": ["occurred_at", "mentioned_at"],
        "difficulty_tags": ["cross_time_constraint"],
        "gold_events": ["inc_e2"],
        "hard_negative_events": ["inc_e6", "inc_e3"],
        "gold_state_slots": {
            "mitigation_status": "事故已通过回滚缓解，服务恢复；实际缓解时间是 14:40，记录时间是 14:45。"
        },
        "gold_slot_support": {
            "mitigation_status": ["inc_e2"]
        },
        "output_slots": ["mitigation_status"],
        "answerability": "answerable",
    },
    {
        "case_id": "rec_cold_start_completion_unknown",
        "query": "推荐系统 cold-start split 测试完成了吗？",
        "scope_id": "recsys_ablation",
        "operation": "state_lookup",
        "time_roles": ["updated_at"],
        "difficulty_tags": ["plan_not_done", "unknown_current", "non_update_latest"],
        "gold_events": ["rec_e5"],
        "hard_negative_events": ["rec_e6", "rec_e1"],
        "gold_state_slots": {
            "completion_status": "无法确认已经完成；当前证据只有计划补 cold-start split 测试，没有完成记录。"
        },
        "gold_slot_support": {
            "completion_status": ["rec_e5"]
        },
        "output_slots": ["completion_status"],
        "answerability": "insufficient_evidence",
    },
    {
        "case_id": "auth_audit_log_completion_unknown",
        "query": "magic link 登录审计日志已经补了吗？",
        "scope_id": "mobile_auth",
        "operation": "state_lookup",
        "time_roles": ["updated_at"],
        "difficulty_tags": ["plan_not_done", "unknown_current", "stale_mention_distractor"],
        "gold_events": ["auth_e6"],
        "hard_negative_events": ["auth_e7", "auth_e1"],
        "gold_state_slots": {
            "audit_log_status": "无法确认已经补完；当前证据只有计划补 magic link 登录审计日志。"
        },
        "gold_slot_support": {
            "audit_log_status": ["auth_e6"]
        },
        "output_slots": ["audit_log_status"],
        "answerability": "insufficient_evidence",
    },
    {
        "case_id": "label_batch_review_unknown",
        "query": "batch A 是否已经完成复核？",
        "scope_id": "labeling_guideline",
        "operation": "state_lookup",
        "time_roles": ["updated_at"],
        "difficulty_tags": ["latest_event_vs_state", "non_update_latest"],
        "gold_events": ["label_e5"],
        "hard_negative_events": ["label_e6", "label_e1"],
        "gold_state_slots": {
            "review_status": "batch A 还没有完成复核；当前证据只显示它已完成一轮标注，但还没复核。"
        },
        "gold_slot_support": {
            "review_status": ["label_e5"]
        },
        "output_slots": ["review_status"],
        "answerability": "answerable",
    },
]


def build_raw_event(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = {
        "event_id": event["event_id"],
        "scope_id": event["scope_id"],
        "content": event["content"],
        "event_type": event["event_type"],
        "occurred_at": event["occurred_at"],
        "mentioned_at": event["mentioned_at"],
        "updated_at": event["updated_at"],
        "planned_for": event.get("planned_for"),
        "deadline_at": event.get("deadline_at"),
        "source_id": event.get("source_id"),
        "metadata": dict(event.get("metadata", {})),
    }
    return {field: raw.get(field) for field in RAW_EVENT_FIELDS}


def build_event_annotation(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "updates_state": bool(event.get("state_relevant", True)),
        "event_status": event.get("status", "active"),
        "corrects": normalize_id_list(event.get("corrects")),
        "supersedes": normalize_id_list(event.get("supersedes")),
        "notes": "Generated from v0 event-level annotations.",
    }


def build_case(case: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "query": case["query"],
        "scope_id": case["scope_id"],
        "operation": case["operation"],
        "time_roles": normalize_id_list(case.get("time_roles", [case.get("time_role", "updated_at")])),
        "difficulty_tags": infer_difficulty_tags(case, events),
        "gold_events": normalize_id_list(case.get("gold_events")),
        "hard_negative_events": infer_hard_negative_events(case, events),
        "gold_state_slots": dict(case.get("gold_state_slots", {})),
        "gold_slot_support": normalize_slot_support(case.get("gold_slot_support", {})),
        "output_slots": [str(slot) for slot in case.get("output_slots", [])],
        "answerability": case.get("answerability", "answerable"),
        "gold_fields_usage": "evaluation_only",
    }


def build_curated_case(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "query": case["query"],
        "scope_id": case["scope_id"],
        "operation": case["operation"],
        "time_roles": list(case["time_roles"]),
        "difficulty_tags": list(case["difficulty_tags"]),
        "gold_events": normalize_id_list(case.get("gold_events")),
        "hard_negative_events": normalize_id_list(case.get("hard_negative_events")),
        "gold_state_slots": dict(case["gold_state_slots"]),
        "gold_slot_support": normalize_slot_support(case["gold_slot_support"]),
        "output_slots": [str(slot) for slot in case["output_slots"]],
        "answerability": case["answerability"],
        "gold_fields_usage": "evaluation_only",
    }


def build_readme() -> str:
    return """# STAMB-State v1 Scaffold

This directory is generated from the v0 pilot data plus curated v1 enrichment cases without overwriting the legacy files.

## Files

- `events_raw.json`: main-track visible event stream. It excludes status, state relevance, correction links, supersession links, and all gold fields.
- `event_annotations.json`: evaluator/oracle-only event annotations derived from v0.
- `claim_annotations.json`: placeholder for future claim/facet-level validity annotations.
- `cases.json`: query cases plus evaluator-only gold annotations, difficulty tags, hard negatives, and answerability labels.
- `splits.json`: scope-level train/dev/test split. Scopes do not cross splits.
- `public/`: no-gold public input generated by `scripts/make_public_track.py`.

## Main Track Contract

The public end-to-end track exposes only `events_raw.json` plus case id, query, and operation.
Gold state slots, support events, hard negatives, answerability labels, output slots, time roles, and scope ids stay in evaluator-only files.

## Current Primary Metrics

Keep the current task-definition ordering for method comparison:

1. `sup_f1`
2. `slot_j`
3. `ans_j`

Additional v1 metrics such as hard-negative rate, answerability accuracy, and time-role accuracy should be added as diagnostics unless the task definition is updated.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build STAMB-State v1 scaffold from the legacy v0 pilot data.")
    parser.add_argument("--events", type=Path, default=LEGACY_DATA_DIR / "events.json")
    parser.add_argument("--cases", type=Path, default=LEGACY_DATA_DIR / "cases.json")
    parser.add_argument("--v0-dir", type=Path, default=DEFAULT_V0_DIR)
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1_DIR)
    args = parser.parse_args()

    events = load_legacy_events(args.events)
    cases = load_legacy_cases(args.cases)

    write_json(args.v0_dir / "events.json", events)
    write_json(args.v0_dir / "cases.json", cases)

    raw_events = [build_raw_event(event) for event in events]
    event_annotations = [build_event_annotation(event) for event in events]
    legacy_cases = [build_case(case, events) for case in cases]
    curated_cases = [build_curated_case(case) for case in CURATED_V1_CASES]
    duplicate_case_ids = sorted({case["case_id"] for case in legacy_cases} & {case["case_id"] for case in curated_cases})
    if duplicate_case_ids:
        raise RuntimeError(f"curated v1 cases duplicate legacy case ids: {duplicate_case_ids}")
    v1_cases = legacy_cases + curated_cases
    splits = build_scope_splits(event["scope_id"] for event in events)

    write_json(args.v1_dir / "events_raw.json", raw_events)
    write_json(args.v1_dir / "event_annotations.json", event_annotations)
    write_json(args.v1_dir / "claim_annotations.json", [])
    write_json(args.v1_dir / "cases.json", v1_cases)
    write_json(args.v1_dir / "splits.json", splits)
    (args.v1_dir / "README.md").write_text(build_readme(), encoding="utf-8")

    print(f"wrote v0 copy to {args.v0_dir}")
    print(f"wrote v1 scaffold to {args.v1_dir}")
    print(
        f"events_raw={len(raw_events)} event_annotations={len(event_annotations)} "
        f"cases={len(v1_cases)} curated_cases={len(curated_cases)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

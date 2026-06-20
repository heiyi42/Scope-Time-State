from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from v1_common import (
    DEFAULT_V1_1_DIR,
    DEFAULT_V1_2_DIR,
    RAW_EVENT_FIELDS,
    build_scope_profiles,
    normalize_id_list,
    read_json,
    write_json,
)


TARGET_SCOPE_COUNTS = {
    "aaai_memory": 12,
    "amp_project": 12,
    "sql_lab_q6": 12,
    "thesis_ch2": 12,
    "grant_app": 18,
    "labeling_guideline": 18,
    "cache_refactor": 18,
    "mobile_auth": 18,
    "robot_nav": 18,
    "recsys_ablation": 18,
    "deployment_incident": 18,
    "ui_accessibility": 18,
    "search_index_rollout": 24,
    "billing_migration": 24,
    "eval_harness": 24,
    "api_rate_limit": 24,
}

EASY_CASE_SCOPES = [
    "aaai_memory",
    "amp_project",
    "sql_lab_q6",
    "robot_nav",
    "thesis_ch2",
    "mobile_auth",
    "search_index_rollout",
    "billing_migration",
    "eval_harness",
    "grant_app",
    "labeling_guideline",
    "cache_refactor",
    "recsys_ablation",
    "deployment_incident",
    "ui_accessibility",
    "api_rate_limit",
]
UNKNOWN_CASE_SCOPES = [
    "api_rate_limit",
    "eval_harness",
    "mobile_auth",
    "recsys_ablation",
]
INSUFFICIENT_CASE_SCOPES = [
    "aaai_memory",
    "grant_app",
    "labeling_guideline",
    "deployment_incident",
]
NEXT_ACTION_CASE_SCOPES = [
    "aaai_memory",
    "amp_project",
    "sql_lab_q6",
    "robot_nav",
    "thesis_ch2",
    "mobile_auth",
    "search_index_rollout",
    "billing_migration",
    "eval_harness",
    "grant_app",
    "labeling_guideline",
    "cache_refactor",
    "recsys_ablation",
    "deployment_incident",
    "ui_accessibility",
    "api_rate_limit",
]
SUMMARY_CASE_SCOPES = [
    "aaai_memory",
    "api_rate_limit",
    "billing_migration",
    "cache_refactor",
    "deployment_incident",
    "eval_harness",
    "grant_app",
    "labeling_guideline",
    "mobile_auth",
    "search_index_rollout",
    "sql_lab_q6",
    "ui_accessibility",
]

SCOPE_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "aaai_memory": {
        "scope_type": "research_writing",
        "task_family": ["state_tracking", "related_work", "next_step_planning"],
        "domain": "academic_project",
    },
    "amp_project": {
        "scope_type": "ml_product",
        "task_family": ["experiment_tracking", "issue_resolution", "next_step_planning"],
        "domain": "machine_learning",
    },
    "sql_lab_q6": {
        "scope_type": "coursework_debugging",
        "task_family": ["debug_status", "fix_validation", "state_tracking"],
        "domain": "education",
    },
    "robot_nav": {
        "scope_type": "robotics_system",
        "task_family": ["calibration_status", "plan_completion", "risk_tracking"],
        "domain": "robotics",
    },
    "thesis_ch2": {
        "scope_type": "research_writing",
        "task_family": ["draft_status", "deadline_tracking", "revision_planning"],
        "domain": "academic_project",
    },
    "mobile_auth": {
        "scope_type": "security_product",
        "task_family": ["decision_tracking", "issue_resolution", "audit_status"],
        "domain": "product_security",
    },
    "search_index_rollout": {
        "scope_type": "search_infra",
        "task_family": ["rollout_status", "latency_risk", "plan_completion"],
        "domain": "search_platform",
    },
    "billing_migration": {
        "scope_type": "business_infra",
        "task_family": ["migration_status", "provider_decision", "compliance_review"],
        "domain": "billing",
    },
    "eval_harness": {
        "scope_type": "benchmark_eval",
        "task_family": ["metric_semantics", "judge_coverage", "diagnostic_planning"],
        "domain": "evaluation",
    },
    "grant_app": {
        "scope_type": "admin_funding",
        "task_family": ["submission_status", "budget_tracking", "team_tracking"],
        "domain": "administration",
    },
    "labeling_guideline": {
        "scope_type": "data_ops",
        "task_family": ["guideline_status", "quality_control", "completion_unknown"],
        "domain": "data_annotation",
    },
    "cache_refactor": {
        "scope_type": "infra_refactor",
        "task_family": ["bug_status", "cleanup_status", "rollout_readiness"],
        "domain": "infrastructure",
    },
    "recsys_ablation": {
        "scope_type": "ml_product",
        "task_family": ["experiment_tracking", "metric_interpretation", "plan_completion"],
        "domain": "recommendation_system",
    },
    "deployment_incident": {
        "scope_type": "incident_response",
        "task_family": ["incident_status", "root_cause", "mitigation_tracking"],
        "domain": "operations",
    },
    "ui_accessibility": {
        "scope_type": "frontend_accessibility",
        "task_family": ["audit_status", "issue_resolution", "acceptance_unknown"],
        "domain": "frontend",
    },
    "api_rate_limit": {
        "scope_type": "api_platform",
        "task_family": ["policy_status", "token_status", "risk_tracking"],
        "domain": "api_platform",
    },
}


def require_unique(rows: Iterable[Mapping[str, Any]], key: str, owner: str) -> None:
    values = [str(row.get(key)) for row in rows]
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise RuntimeError(f"{owner} duplicate {key}: {duplicates}")


def event_time(row: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(str(row["updated_at"]))


def raw_event(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: row.get(field) for field in RAW_EVENT_FIELDS}


def event_annotation(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "updates_state": bool(row.get("updates_state", True)),
        "event_status": str(row.get("event_status", "active")),
        "corrects": normalize_id_list(row.get("corrects")),
        "supersedes": normalize_id_list(row.get("supersedes")),
        "notes": str(row.get("notes", "Generated by v1.2 benchmark expansion.")),
    }


def slug_scope(scope_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", scope_id.lower()).strip("_")


def generated_event_rows(scope_id: str, existing: Sequence[Mapping[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    missing = max(0, target_count - len(existing))
    if missing == 0:
        return []
    base_time = max(event_time(row) for row in existing)
    slug = slug_scope(scope_id)
    rows: List[Dict[str, Any]] = []
    templates = [
        (
            "stale_completion_mention",
            "mention",
            "historical_only",
            False,
            "{scope} 的旧周报再次写到“已经完成”，但这只是复述过期资料，没有新的完成记录。",
        ),
        (
            "background_meeting",
            "meeting_note",
            "active",
            False,
            "{scope} 例会记录了排期和参会人变动，没有改变当前状态判断。",
        ),
        (
            "side_observation",
            "observation",
            "active",
            True,
            "{scope} 新增旁路日志采样，当前只是观察信号，不改变主方案。",
        ),
        (
            "planned_review",
            "plan",
            "active",
            True,
            "{scope} 计划做一次轻量复查，目前只有计划，没有复查完成记录。",
        ),
        (
            "scope_collision",
            "mention",
            "historical_only",
            False,
            "有人把 {scope} 和另一个项目的上线状态混在一起，随后说明这不是本 scope 的有效状态。",
        ),
        (
            "procedural_note",
            "note",
            "active",
            False,
            "{scope} 补充了模板整理和归档说明，不涉及当前决策、风险或下一步。",
        ),
        (
            "old_blocker_mention",
            "mention",
            "historical_only",
            False,
            "{scope} 的旧阻塞原因被再次引用，但没有说明这个旧阻塞仍然有效。",
        ),
        (
            "low_priority_side_task",
            "task_note",
            "active",
            True,
            "{scope} 有一个低优先级旁支任务进入观察队列，主线状态暂不改变。",
        ),
    ]
    for index in range(missing):
        role, event_type, status, updates_state, content_template = templates[index % len(templates)]
        updated_at = base_time + timedelta(hours=index + 1)
        planned_for = None
        deadline_at = None
        if role == "planned_review":
            planned_for = (updated_at + timedelta(days=3)).isoformat(timespec="seconds")
        row = {
            "event_id": f"v12_{slug}_{index + 1:02d}",
            "scope_id": scope_id,
            "content": content_template.format(scope=scope_id),
            "event_type": event_type,
            "occurred_at": updated_at.isoformat(timespec="seconds"),
            "mentioned_at": updated_at.isoformat(timespec="seconds"),
            "updated_at": updated_at.isoformat(timespec="seconds"),
            "planned_for": planned_for,
            "deadline_at": deadline_at,
            "source_id": None,
            "metadata": {},
            "event_status": status,
            "updates_state": updates_state,
            "corrects": [],
            "supersedes": [],
            "v1_2_role": role,
        }
        rows.append(row)
    return rows


def difficulty_level(case: Mapping[str, Any]) -> str:
    tags = set(str(tag) for tag in case.get("difficulty_tags", []))
    gold_count = len(normalize_id_list(case.get("gold_events")))
    hard_negative_count = len(normalize_id_list(case.get("hard_negative_events")))
    output_slot_count = len(case.get("output_slots", []))
    if (
        len(tags) >= 5
        or gold_count >= 3
        or hard_negative_count >= 4
        or output_slot_count >= 3
        or {"correction_aware", "facet_specific_validity", "cross_time_constraint"} <= tags
    ):
        return "hard"
    if case.get("answerability") != "answerable" or len(tags) >= 3 or gold_count >= 2 or hard_negative_count >= 2:
        return "medium"
    return "easy"


def expand_original_cases(
    cases: Sequence[Mapping[str, Any]],
    generated_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []
    for case in cases:
        row = dict(case)
        row["difficulty_level"] = difficulty_level(row)
        gold_ids = set(normalize_id_list(row.get("gold_events")))
        hard_negatives = list(normalize_id_list(row.get("hard_negative_events")))
        target = {"easy": 1, "medium": 3, "hard": 5}[row["difficulty_level"]]
        for event in generated_by_scope.get(str(row["scope_id"]), []):
            if len(hard_negatives) >= target:
                break
            event_id = str(event["event_id"])
            if event_id in gold_ids or event_id in hard_negatives:
                continue
            if event.get("updates_state") is False:
                hard_negatives.append(event_id)
        row["hard_negative_events"] = hard_negatives
        row["difficulty_level"] = difficulty_level(row)
        expanded.append(row)
    return expanded


def first_generated_role(
    generated_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    scope_id: str,
    role: str,
) -> Mapping[str, Any]:
    for row in generated_by_scope.get(scope_id, []):
        if row.get("v1_2_role") == role:
            return row
    raise RuntimeError(f"missing generated role={role} for scope={scope_id}")


def make_easy_case(scope_id: str, event: Mapping[str, Any]) -> Dict[str, Any]:
    case_id = f"v12_{slug_scope(scope_id)}_side_observation"
    event_id = str(event["event_id"])
    return {
        "case_id": case_id,
        "query": f"{scope_id} 的旁路日志采样现在是什么状态？",
        "scope_id": scope_id,
        "operation": "state_lookup",
        "time_roles": ["updated_at"],
        "difficulty_tags": ["long_context_noise"],
        "difficulty_level": "easy",
        "gold_events": [event_id],
        "hard_negative_events": [],
        "gold_state_slots": {
            "side_observation_status": "新增旁路日志采样，目前只是观察信号，不改变主方案。"
        },
        "gold_slot_support": {"side_observation_status": [event_id]},
        "output_slots": ["side_observation_status"],
        "answerability": "answerable",
        "gold_fields_usage": "evaluation_only",
    }


def make_unknown_case(scope_id: str, event: Mapping[str, Any]) -> Dict[str, Any]:
    case_id = f"v12_{slug_scope(scope_id)}_planned_review_unknown"
    event_id = str(event["event_id"])
    return {
        "case_id": case_id,
        "query": f"{scope_id} 的轻量复查完成了吗？",
        "scope_id": scope_id,
        "operation": "state_lookup",
        "time_roles": ["planned_for", "updated_at"],
        "difficulty_tags": ["plan_not_done", "unknown_current", "long_context_noise"],
        "difficulty_level": "medium",
        "gold_events": [event_id],
        "hard_negative_events": [],
        "gold_state_slots": {"review_status": "只有轻量复查计划，没有复查完成记录。"},
        "gold_slot_support": {"review_status": [event_id]},
        "output_slots": ["review_status"],
        "answerability": "unknown_current",
        "gold_fields_usage": "evaluation_only",
    }


def make_insufficient_case(scope_id: str) -> Dict[str, Any]:
    case_id = f"v12_{slug_scope(scope_id)}_final_acceptance_insufficient"
    return {
        "case_id": case_id,
        "query": f"{scope_id} 的最终验收签字完成了吗？",
        "scope_id": scope_id,
        "operation": "state_lookup",
        "time_roles": ["updated_at"],
        "difficulty_tags": ["insufficient_evidence", "answerability", "long_context_noise"],
        "difficulty_level": "medium",
        "gold_events": [],
        "hard_negative_events": [],
        "gold_state_slots": {"acceptance_status": "没有足够证据判断最终验收签字是否完成。"},
        "gold_slot_support": {"acceptance_status": []},
        "output_slots": ["acceptance_status"],
        "answerability": "insufficient_evidence",
        "gold_fields_usage": "evaluation_only",
    }


def make_next_action_case(scope_id: str, event: Mapping[str, Any]) -> Dict[str, Any]:
    case_id = f"v12_{slug_scope(scope_id)}_next_action_review"
    event_id = str(event["event_id"])
    return {
        "case_id": case_id,
        "query": f"{scope_id} 接下来应该做什么？",
        "scope_id": scope_id,
        "operation": "next_action",
        "time_roles": ["planned_for", "updated_at"],
        "difficulty_tags": ["plan_not_done", "long_context_noise", "next_action"],
        "difficulty_level": "medium",
        "gold_events": [event_id],
        "hard_negative_events": [],
        "gold_state_slots": {"next_action": "下一步是做轻量复查；目前只有计划，没有完成记录。"},
        "gold_slot_support": {"next_action": [event_id]},
        "output_slots": ["next_action"],
        "answerability": "answerable",
        "gold_fields_usage": "evaluation_only",
    }


def make_summary_case(scope_id: str, event: Mapping[str, Any]) -> Dict[str, Any]:
    case_id = f"v12_{slug_scope(scope_id)}_brief_state_summary"
    event_id = str(event["event_id"])
    return {
        "case_id": case_id,
        "query": f"{scope_id} 当前补充观察可以怎么总结？",
        "scope_id": scope_id,
        "operation": "state_summary",
        "time_roles": ["updated_at"],
        "difficulty_tags": ["long_context_noise"],
        "difficulty_level": "easy",
        "gold_events": [event_id],
        "hard_negative_events": [],
        "gold_state_slots": {"brief_state_summary": "新增旁路日志采样，目前只是观察信号，不改变主方案。"},
        "gold_slot_support": {"brief_state_summary": [event_id]},
        "output_slots": ["brief_state_summary"],
        "answerability": "answerable",
        "gold_fields_usage": "evaluation_only",
    }


def make_new_cases(generated_by_scope: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for scope_id in EASY_CASE_SCOPES:
        cases.append(make_easy_case(scope_id, first_generated_role(generated_by_scope, scope_id, "side_observation")))
    for scope_id in UNKNOWN_CASE_SCOPES:
        cases.append(make_unknown_case(scope_id, first_generated_role(generated_by_scope, scope_id, "planned_review")))
    for scope_id in INSUFFICIENT_CASE_SCOPES:
        cases.append(make_insufficient_case(scope_id))
    for scope_id in NEXT_ACTION_CASE_SCOPES:
        cases.append(make_next_action_case(scope_id, first_generated_role(generated_by_scope, scope_id, "planned_review")))
    for scope_id in SUMMARY_CASE_SCOPES:
        cases.append(make_summary_case(scope_id, first_generated_role(generated_by_scope, scope_id, "side_observation")))
    return cases


def public_case(case: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "query": str(case["query"]),
        "operation": str(case["operation"]),
    }


def case_split(case: Mapping[str, Any], splits: Mapping[str, Sequence[str]]) -> str:
    scope_id = str(case["scope_id"])
    for split, scopes in splits.items():
        if scope_id in set(scopes):
            return split
    return "unknown"


def pick_round_robin_by_split(
    candidates: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Sequence[str]],
    count: int,
) -> List[Mapping[str, Any]]:
    buckets: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for case in candidates:
        buckets[case_split(case, splits)].append(case)
    picked: List[Mapping[str, Any]] = []
    split_order = ["test", "dev", "train"]
    while len(picked) < count and sum(len(bucket) for bucket in buckets.values()) > 0:
        progressed = False
        for split in split_order:
            bucket = buckets.get(split, [])
            if bucket and len(picked) < count:
                picked.append(bucket.pop(0))
                progressed = True
        if not progressed:
            break
    return picked


def choose_balanced_subset(cases: Sequence[Mapping[str, Any]], splits: Mapping[str, Sequence[str]], per_level: int) -> List[str]:
    total = per_level * 3
    difficulty_remaining = {"easy": per_level, "medium": per_level, "hard": per_level}
    selected: List[Mapping[str, Any]] = []
    selected_ids: set[str] = set()

    def add_from_candidates(candidates: Sequence[Mapping[str, Any]], count: int) -> None:
        if count <= 0:
            return
        ordered = pick_round_robin_by_split(
            [case for case in candidates if str(case["case_id"]) not in selected_ids],
            splits,
            count,
        )
        for case in ordered:
            if len(selected) >= total:
                break
            level = str(case.get("difficulty_level"))
            if difficulty_remaining.get(level, 0) <= 0:
                continue
            selected.append(case)
            selected_ids.add(str(case["case_id"]))
            difficulty_remaining[level] -= 1
            if sum(1 for item in selected if str(item["case_id"]) in {str(row["case_id"]) for row in ordered}) >= count:
                break

    def selected_operation_count(operation: str) -> int:
        return sum(1 for case in selected if case.get("operation") == operation)

    target_non_answerable = min(10, max(2, round(per_level * 0.625)))
    target_unknown = target_non_answerable // 2
    target_insufficient = target_non_answerable - target_unknown
    add_from_candidates(
        [
            case
            for case in cases
            if case.get("difficulty_level") == "medium" and case.get("answerability") == "unknown_current"
        ],
        target_unknown,
    )
    add_from_candidates(
        [
            case
            for case in cases
            if case.get("difficulty_level") == "medium" and case.get("answerability") == "insufficient_evidence"
        ],
        target_insufficient,
    )

    target_next_action = max(1, round(total * 0.18))
    for level in ["hard", "medium", "easy"]:
        add_from_candidates(
            [
                case
                for case in cases
                if case.get("difficulty_level") == level and case.get("operation") == "next_action"
            ],
            target_next_action - selected_operation_count("next_action"),
        )

    target_state_summary = max(1, round(total * 0.22))
    for level in ["easy", "hard", "medium"]:
        add_from_candidates(
            [
                case
                for case in cases
                if case.get("difficulty_level") == level and case.get("operation") == "state_summary"
            ],
            target_state_summary - selected_operation_count("state_summary"),
        )

    for level in ["easy", "medium", "hard"]:
        add_from_candidates(
            [
                case
                for case in cases
                if case.get("difficulty_level") == level and case.get("operation") == "state_lookup"
            ],
            difficulty_remaining[level],
        )
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level],
            difficulty_remaining[level],
        )

    if len(selected) != total or any(value != 0 for value in difficulty_remaining.values()):
        raise RuntimeError(
            f"could not build balanced subset: selected={len(selected)} remaining={difficulty_remaining}"
        )
    return [str(case["case_id"]) for case in cases if str(case["case_id"]) in selected_ids]


def count_bins(values: Iterable[int], bins: Sequence[tuple[str, int | None, int | None]]) -> Dict[str, int]:
    counts = {name: 0 for name, _, _ in bins}
    for value in values:
        for name, low, high in bins:
            if (low is None or value >= low) and (high is None or value <= high):
                counts[name] += 1
                break
    return counts


def build_audit(
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Sequence[str]],
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        by_scope[str(event["scope_id"])].append(event)
    scope_sizes = {scope: len(rows) for scope, rows in sorted(by_scope.items())}
    case_scope_sizes = [scope_sizes[str(case["scope_id"])] for case in cases]
    hard_negative_counts = [len(normalize_id_list(case.get("hard_negative_events"))) for case in cases]
    gold_counts = [len(normalize_id_list(case.get("gold_events"))) for case in cases]
    return {
        "events": len(events),
        "cases": len(cases),
        "scopes": len(by_scope),
        "scope_event_counts": scope_sizes,
        "scope_event_bins": count_bins(scope_sizes.values(), [("short_<=12", None, 12), ("medium_13_18", 13, 18), ("long_19+", 19, None)]),
        "case_scope_event_bins": count_bins(case_scope_sizes, [("short_<=12", None, 12), ("medium_13_18", 13, 18), ("long_19+", 19, None)]),
        "difficulty_level": dict(sorted(Counter(str(case.get("difficulty_level", "unset")) for case in cases).items())),
        "answerability": dict(sorted(Counter(str(case.get("answerability")) for case in cases).items())),
        "operation": dict(sorted(Counter(str(case.get("operation")) for case in cases).items())),
        "gold_event_count": dict(sorted(Counter(gold_counts).items())),
        "hard_negative_count": dict(sorted(Counter(hard_negative_counts).items())),
        "hard_negative_total": sum(hard_negative_counts),
        "gold_event_total": sum(gold_counts),
        "split_cases": dict(sorted(Counter(case_split(case, splits) for case in cases).items())),
        "scope_type": dict(sorted(Counter(str(taxonomy.get(str(scope), {}).get("scope_type", "unknown")) for scope in by_scope).items())),
        "case_scope_type": dict(sorted(Counter(str(taxonomy.get(str(case["scope_id"]), {}).get("scope_type", "unknown")) for case in cases).items())),
        "difficulty_by_split": {
            split: dict(sorted(Counter(str(case.get("difficulty_level")) for case in cases if case_split(case, splits) == split).items()))
            for split in sorted(splits)
        },
    }


def build_readme(audit: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# STAMB-State v1.2",
            "",
            "v1.2 upgrades v1.1 without overwriting it. The task remains latest-valid-state retrieval, but the data now has longer per-scope event streams, explicit difficulty levels, more answerability cases, and balanced subset files for partial public runs.",
            "",
            "## Counts",
            "",
            f"- events: {audit['events']}",
            f"- cases: {audit['cases']}",
            f"- scopes: {audit['scopes']}",
            f"- scope_event_bins: {audit['scope_event_bins']}",
            f"- case_scope_event_bins: {audit['case_scope_event_bins']}",
            f"- difficulty_level: {audit['difficulty_level']}",
            f"- answerability: {audit['answerability']}",
            f"- operations: {audit['operation']}",
            f"- scope_type: {audit['scope_type']}",
            f"- hard_negative_count: {audit['hard_negative_count']}",
            "",
            "## Added Coverage",
            "",
            "- explicit `difficulty_level` on every evaluator case;",
            "- public-safe `scope_taxonomy.json` and scope profile fields for domain/task-family breakdowns;",
            "- longer target-scope streams, with 12/18/24-event scope bins;",
            "- in-scope no-update and stale-mention distractors beyond the original hard negatives;",
            "- additional unknown-current and insufficient-evidence cases;",
            "- additional next-action and state-summary cases while keeping the three-operation contract fixed;",
            "- `subsets.json` with `balanced_half` and `smoke_12` case-id lists.",
            "",
            "## Files",
            "",
            "- `events_raw.json`: visible event stream without evaluator-only validity fields.",
            "- `event_annotations.json`: evaluator/oracle-only state relevance, status, correction, and supersession annotations.",
            "- `cases.json`: evaluator-only query cases with gold state slots, difficulty levels, and support events.",
            "- `subsets.json`: named case-id subsets for balanced partial runs.",
            "- `scope_taxonomy.json`: public-safe scope type, task family, and domain labels.",
            "- `benchmark_audit.json`: reproducible distribution audit.",
            "- `public/`: no-gold public input generated from the same events/cases.",
            "",
            "## Validation",
            "",
            "```bash",
            "python scripts/validate_v1.py --v1-dir /Users/mac/Desktop/EpisodicMemory/stamb_state_benchmark/data/v1_2",
            "python Experiment/run/run_public_benchmark.py --data-version v1_2 --case-subset balanced_half --dry-run",
            "```",
            "",
        ]
    )


def taxonomy_rows() -> List[Dict[str, Any]]:
    return [
        {"scope_id": scope_id, **values}
        for scope_id, values in sorted(SCOPE_TAXONOMY.items())
    ]


def enriched_scope_profiles(events: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    profiles = build_scope_profiles(events)
    for profile in profiles:
        taxonomy = SCOPE_TAXONOMY.get(str(profile.get("scope_id")), {})
        profile.update(taxonomy)
    return profiles


def write_public_track(out_dir: Path, events: Sequence[Mapping[str, Any]], cases: Sequence[Mapping[str, Any]], subsets: Mapping[str, Sequence[str]]) -> None:
    public_dir = out_dir / "public"
    write_json(public_dir / "events.json", list(events))
    write_json(public_dir / "cases.json", [public_case(case) for case in cases])
    write_json(public_dir / "scope_profiles.json", enriched_scope_profiles(events))
    write_json(public_dir / "scope_taxonomy.json", taxonomy_rows())
    write_json(public_dir / "subsets.json", subsets)
    (public_dir / "README.md").write_text(
        "# STAMB-State v1_2 Public Track\n\n"
        "`events.json`, `cases.json`, `scope_profiles.json`, `scope_taxonomy.json`, and `subsets.json` are the no-gold end-to-end input files.\n"
        "`scope_taxonomy.json` contains public-safe scope type, task family, and domain labels for routing and breakdown analysis.\n"
        "`subsets.json` contains only case ids, not gold labels or difficulty metadata.\n"
        "Evaluator-only fields are retained only in `../cases.json` and annotation files.\n",
        encoding="utf-8",
    )


def build_v1_2(source_dir: Path, out_dir: Path) -> Dict[str, Any]:
    source_events = read_json(source_dir / "events_raw.json")
    source_annotations = read_json(source_dir / "event_annotations.json")
    source_cases = read_json(source_dir / "cases.json")
    splits = read_json(source_dir / "splits.json")
    claims = read_json(source_dir / "claim_annotations.json")

    annotation_by_id = {str(row["event_id"]): dict(row) for row in source_annotations}
    by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in source_events:
        by_scope[str(row["scope_id"])].append(row)

    generated_by_scope: Dict[str, List[Mapping[str, Any]]] = {}
    generated_rows: List[Dict[str, Any]] = []
    for scope_id, rows in sorted(by_scope.items()):
        target_count = TARGET_SCOPE_COUNTS.get(scope_id, max(12, len(rows)))
        rows_for_scope = generated_event_rows(scope_id, rows, target_count)
        generated_by_scope[scope_id] = rows_for_scope
        generated_rows.extend(rows_for_scope)

    events = [dict(row) for row in source_events] + [raw_event(row) for row in generated_rows]
    annotations = [dict(row) for row in source_annotations] + [event_annotation(row) for row in generated_rows]

    cases = expand_original_cases(source_cases, generated_by_scope)
    cases.extend(make_new_cases(generated_by_scope))
    for case in cases:
        case["difficulty_level"] = difficulty_level(case)

    require_unique(events, "event_id", "events")
    require_unique(annotations, "event_id", "event_annotations")
    require_unique(cases, "case_id", "cases")
    missing_annotations = sorted(set(str(event["event_id"]) for event in events) - set(annotation_by_id) - set(str(row["event_id"]) for row in generated_rows))
    if missing_annotations:
        raise RuntimeError(f"source events missing annotations: {missing_annotations}")

    balanced_per_level = round(len(cases) / 6)
    subsets = {
        "balanced_half": choose_balanced_subset(cases, splits, per_level=balanced_per_level),
        "smoke_12": choose_balanced_subset(cases, splits, per_level=4),
    }
    audit = build_audit(events, cases, splits, SCOPE_TAXONOMY)

    write_json(out_dir / "events_raw.json", events)
    write_json(out_dir / "event_annotations.json", annotations)
    write_json(out_dir / "claim_annotations.json", claims)
    write_json(out_dir / "cases.json", cases)
    write_json(out_dir / "splits.json", splits)
    write_json(out_dir / "subsets.json", subsets)
    write_json(out_dir / "scope_taxonomy.json", taxonomy_rows())
    write_json(out_dir / "benchmark_audit.json", audit)
    write_public_track(out_dir, events, cases, subsets)
    (out_dir / "README.md").write_text(build_readme(audit), encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Build STAMB-State v1.2 from v1.1.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_V1_1_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_V1_2_DIR)
    args = parser.parse_args()

    audit = build_v1_2(args.source_dir, args.out_dir)
    print(f"wrote {args.out_dir}")
    print(f"events={audit['events']} cases={audit['cases']} scopes={audit['scopes']}")
    print(f"difficulty_level={audit['difficulty_level']}")
    print(f"scope_event_bins={audit['scope_event_bins']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

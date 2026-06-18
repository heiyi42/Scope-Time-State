from __future__ import annotations

from collections import Counter
import json
import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

from Experiment.run.common.io import normalize_id_list
from Experiment.common import BaselinePromptSpec, event_view, relevant_by_scope, sort_by_time
from Experiment.run.common.llm_client import LLMClient
from Experiment.run.run_public_benchmark.types import (
    PublicCase,
    SUPPORTED_VARIANTS,
    ScopeProfile,
    canonical_public_variant_name,
)


def load_public_cases(path: Path) -> List[PublicCase]:
    rows = json.loads(path.read_text())
    return [
        PublicCase(
            case_id=str(row["case_id"]),
            query=str(row["query"]),
            operation=str(row["operation"]),
        )
        for row in rows
    ]


def profile_text_from_dict(profile: Dict[str, object]) -> str:
    parts: List[str] = [
        str(profile.get("scope_id", "")),
        str(profile.get("name", "")),
        str(profile.get("summary", "")),
        " ".join(str(item) for item in profile.get("aliases", []) if item),
        " ".join(str(item) for item in profile.get("keywords", []) if item),
    ]
    event_types = profile.get("event_types", {})
    if isinstance(event_types, dict):
        parts.extend(str(key) for key in event_types)
    recent_events = profile.get("recent_events", [])
    if isinstance(recent_events, list):
        for event in recent_events:
            if not isinstance(event, dict):
                continue
            parts.extend(
                [
                    str(event.get("event_type", "")),
                    str(event.get("summary", "")),
                    str(event.get("content", "")),
                ]
            )
    return " ".join(part for part in parts if part)


def scope_profiles_from_rows(rows: Sequence[Dict[str, object]]) -> List[ScopeProfile]:
    profiles: List[ScopeProfile] = []
    for row in rows:
        scope_id = str(row.get("scope_id", ""))
        if not scope_id:
            continue
        profile = dict(row)
        profiles.append(
            ScopeProfile(
                scope_id=scope_id,
                profile=profile,
                profile_text=profile_text_from_dict(profile),
            )
        )
    return profiles


def load_scope_profiles(path: Path, events: Sequence[object]) -> List[ScopeProfile]:
    if path.exists():
        rows = json.loads(path.read_text())
        if not isinstance(rows, list):
            raise ValueError(f"{path} must contain a JSON list")
        return scope_profiles_from_rows([dict(row) for row in rows if isinstance(row, dict)])
    return scope_profiles_from_events(events)


def scope_profiles_from_events(events: Sequence[object], max_recent_events: int = 6) -> List[ScopeProfile]:
    grouped: Dict[str, List[object]] = {}
    for event in events:
        grouped.setdefault(event.scope_id, []).append(event)
    rows: List[Dict[str, object]] = []
    for scope_id, scoped_events in sorted(grouped.items()):
        ordered = sort_by_time(scoped_events, "updated_at")
        event_types = Counter(event.event_type for event in scoped_events)
        rows.append(
            {
                "scope_id": scope_id,
                "event_count": len(scoped_events),
                "event_types": dict(sorted(event_types.items())),
                "keywords": sorted(text_terms(" ".join(event.content for event in scoped_events)))[:20],
                "summary": "；".join(event.content for event in ordered[:3]),
                "recent_events": [
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "summary": event.content,
                        "occurred_at": event.occurred_at,
                        "mentioned_at": event.mentioned_at,
                        "updated_at": event.updated_at,
                        "planned_for": getattr(event, "planned_for", None),
                        "deadline_at": getattr(event, "deadline_at", None),
                    }
                    for event in ordered[:max_recent_events]
                ],
            }
        )
    return scope_profiles_from_rows(rows)


def validate_public_cases(public_cases: Sequence[PublicCase], hidden_cases: Sequence[QueryCase]) -> None:
    hidden_ids = {case.case_id for case in hidden_cases}
    errors = [
        f"public case has no hidden gold case: {case.case_id}"
        for case in public_cases
        if case.case_id not in hidden_ids
    ]
    if errors:
        formatted = "\n".join(f"- {error}" for error in errors)
        raise RuntimeError(f"public benchmark validation failed:\n{formatted}")


def text_terms(text: str) -> set[str]:
    lower = text.lower()
    terms = set(re.findall(r"[a-z0-9_]+", lower))
    for token in list(terms):
        if "_" in token:
            terms.update(part for part in token.split("_") if part)
    cjk_sequences = re.findall(r"[\u4e00-\u9fff]+", lower)
    for sequence in cjk_sequences:
        if len(sequence) >= 2:
            terms.add(sequence)
            terms.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return {term for term in terms if term}


def lexical_score(query: str, text: str) -> float:
    query_terms = text_terms(query)
    if not query_terms:
        return 0.0
    text_terms_value = text_terms(text)
    if not text_terms_value:
        return 0.0
    overlap = query_terms & text_terms_value
    return len(overlap) / len(query_terms)


def sparse_embedding(text: str) -> Counter[str]:
    return Counter(text_terms(text))


def cosine_score(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def event_text(event: object) -> str:
    parts = [
        event.event_id,
        event.scope_id,
        event.content,
        event.event_type,
        event.occurred_at,
        event.mentioned_at,
        event.updated_at,
        getattr(event, "planned_for", "") or "",
        getattr(event, "deadline_at", "") or "",
        getattr(event, "source_id", "") or "",
    ]
    return " ".join(str(part) for part in parts if part)


def top_events_by_query(events: Sequence[object], query: str, limit: int) -> List[object]:
    scored = [
        (lexical_score(query, event_text(event)), event.updated_at, event.event_id, event)
        for event in events
    ]
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    if any(score > 0 for score, _, _, _ in scored):
        return [event for score, _, _, event in scored[:limit] if score > 0]
    return sort_by_time(events, "updated_at")[:limit]


def route_scope(events: Sequence[object], query: str) -> Optional[str]:
    scores: Dict[str, float] = {}
    latest: Dict[str, str] = {}
    for event in events:
        score = lexical_score(query, event_text(event))
        scores[event.scope_id] = scores.get(event.scope_id, 0.0) + score
        latest[event.scope_id] = max(latest.get(event.scope_id, ""), event.updated_at)
    if not scores:
        return None
    return max(scores, key=lambda scope_id: (scores[scope_id], latest.get(scope_id, ""), scope_id))


def profile_query_text(case: PublicCase) -> str:
    return f"{case.query} {case.operation}"


def rank_scope_profiles(
    profiles: Sequence[ScopeProfile],
    case: PublicCase,
    limit: int,
) -> List[Dict[str, object]]:
    query_text = profile_query_text(case)
    query_embedding = sparse_embedding(query_text)
    ranked: List[Tuple[float, str, ScopeProfile]] = []
    for profile in profiles:
        score = cosine_score(query_embedding, sparse_embedding(profile.profile_text))
        if score == 0.0:
            score = lexical_score(query_text, profile.profile_text)
        ranked.append((score, profile.scope_id, profile))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if ranked and ranked[0][0] == 0.0:
        limit = len(ranked)
    if limit <= 0:
        limit = len(ranked)
    return [
        {
            "scope_id": profile.scope_id,
            "retrieval_score": round(score, 4),
            "profile": profile.profile,
        }
        for score, _, profile in ranked[:limit]
    ]


def fallback_scope_from_profiles(candidates: Sequence[Dict[str, object]]) -> Optional[str]:
    if not candidates:
        return None
    return str(candidates[0].get("scope_id", "") or "") or None


def route_scope_from_profiles(
    client: LLMClient,
    events: Sequence[object],
    scope_profiles: Sequence[ScopeProfile],
    case: PublicCase,
    scope_top_k: int,
) -> Tuple[Optional[str], Dict[str, object], List[Dict[str, object]]]:
    candidate_scope_profiles = rank_scope_profiles(scope_profiles, case, scope_top_k)
    router_raw = client.complete_json(
        scope_router_system_prompt(),
        scope_router_user_prompt(case, candidate_scope_profiles),
    )
    candidate_scope = str(router_raw.get("scope_id", ""))
    known_scopes = {profile.scope_id for profile in scope_profiles}
    routed_scope = (
        candidate_scope
        if candidate_scope in known_scopes
        else fallback_scope_from_profiles(candidate_scope_profiles) or route_scope(events, case.query)
    )
    return routed_scope, router_raw, candidate_scope_profiles


def infer_time_role(query: str, operation: str) -> str:
    lower = query.lower()
    if any(term in lower for term in ("deadline", "due", "截止", "到期")):
        return "deadline_at"
    if any(term in lower for term in ("提到", "说过", "记录", "复述", "mentioned", "recorded")):
        return "mentioned_at"
    if any(term in lower for term in ("计划", "安排", "下一步", "下周", "明天", "planned", "plan", "next")):
        return "planned_for"
    if any(term in lower for term in ("实际", "发生", "完成", "做完", "修复", "提交", "occurred", "completed", "done")):
        return "occurred_at"
    if operation == "next_action":
        return "planned_for"
    return "updated_at"


def select_scope_events_by_time_role(events: Sequence[object], time_role: str) -> List[object]:
    return sort_by_time(events, time_role)


def build_public_prompt_spec(
    variant_name: str,
    events: Sequence[object],
    case: PublicCase,
    routed_scope: Optional[str] = None,
    routed_time_role: Optional[str] = None,
) -> BaselinePromptSpec:
    canonical_name = canonical_public_variant_name(variant_name)
    if canonical_name == "full_context_llm":
        visible = [
            event_view(event, include_relations=False, include_state_relevant=False)
            for event in sort_by_time(events, "updated_at")
        ]
        instruction = (
            "模拟 End-to-End full-context LLM：你能看到完整事件流，但看不到 hidden output_slots、"
            "gold_state_slots 或目标 case 的 hidden scope_id。你必须自己判断哪些状态 facet 与 query 有关。"
        )
        return BaselinePromptSpec("full_context_llm", visible, instruction)

    if canonical_name == "hybrid_rag":
        visible = [
            event_view(event, include_relations=False, include_state_relevant=False)
            for event in top_events_by_query(events, case.query, limit=8)
        ]
        instruction = (
            "模拟 End-to-End Hybrid RAG：你只拿到 query 检索出的 top-8 raw events，"
            "不能看到 hidden output_slots、gold_state_slots 或 oracle validity 标注。"
        )
        return BaselinePromptSpec("hybrid_rag", visible, instruction)

    if canonical_name == "ours_scope_time_state":
        selected_scope = routed_scope or route_scope(events, case.query)
        selected_time_role = routed_time_role or infer_time_role(case.query, case.operation)
        scoped = relevant_by_scope(events, selected_scope) if selected_scope else []
        visible = [
            event_view(event, include_relations=False, include_state_relevant=False)
            for event in select_scope_events_by_time_role(scoped, selected_time_role)
        ]
        instruction = (
            "模拟 End-to-End Scope-Time-State：先根据 query 从 raw events 中路由 scope，"
            "再根据 query 推断 time role，并在该 scope 内按 time role 组织候选事件，"
            "最后判断纠错/替代、计划未完成、最近复述干扰和当前有效状态。"
            f"路由得到的候选 scope 是 {selected_scope or 'unknown'}。"
            f"推断的 time_role 是 {selected_time_role}。"
            "你不能看到 hidden output_slots 或 gold_state_slots，必须自己生成相关状态 facets。"
            "对状态总结类 query，要同时保留当前决策、风险/问题、下一步和旧判断是否已被纠正；"
            "对下一步 query，要同时保留产生该下一步的当前决策；"
            "对风险 query，要区分具体 related-work 风险和已被后续决策替代的旧方向。"
            "随口提到、复盘旧判断、无新结论的事件不要作为当前状态 facet。"
            "如果证据只有计划、待办、草稿、待补或未复核，没有明确完成记录，"
            "必须表达“无法确认已经完成/提交/补完”，不能断言“未完成/未提交”。"
        )
        return BaselinePromptSpec("ours_scope_time_state", visible, instruction)

    known = ", ".join(SUPPORTED_VARIANTS)
    raise ValueError(f"unsupported public variant: {variant_name}; supported variants: {known}")


def scope_router_system_prompt() -> str:
    return (
        "你是长期记忆系统的 Scope Anchor。你只能根据 query 和候选 scope profiles 选择最相关的 scope_id。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        'JSON schema: {"scope_id": "one candidate scope_id", "reason": "short reason"}。'
        "scope_id 必须来自候选列表；如果不确定，也要选择最可能的一个。"
    )


def scope_router_user_prompt(case: PublicCase, candidate_scope_profiles: Sequence[Dict[str, object]]) -> str:
    payload = {
        "query": case.query,
        "operation": case.operation,
        "candidate_scope_profiles": list(candidate_scope_profiles),
        "task": (
            "先根据 query 和 operation 判断用户指向哪个 scope。"
            "candidate_scope_profiles 可能包含全部 public profiles，也可能已由 sparse profile embedding 初筛；你只做最终 rerank。"
            "retrieval_score 只是候选召回提示，不是最终判断；如果 query 的中文领域名和 scope_id 缩写存在语义对应，也要结合 profile 内容判断。"
            "不要把 scope profile 里的 recent_events 当作最终证据，后续模块会进入 target scope 的事件时间流。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

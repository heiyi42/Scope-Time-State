from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Set


GRAPHITI_DIR = Path(__file__).resolve().parent
PROJECT_DIR = GRAPHITI_DIR.parents[2]
BENCHMARK_DIR = PROJECT_DIR / "stamb_state_benchmark"
V1_DATA_DIR = BENCHMARK_DIR / "data" / "v1"
DEFAULT_EVENTS_PATH = V1_DATA_DIR / "events_raw.json"
DEFAULT_CASES_PATH = V1_DATA_DIR / "cases.json"
sys.path.insert(0, str(PROJECT_DIR))

try:
    from graphiti_core.embedder.client import EmbedderClient  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - lets --dry-run work without Graphiti installed.
    class EmbedderClient:  # type: ignore[no-redef]
        pass

from Experiment.run.run_oracle_benchmark import (  # noqa: E402
    EvalRow,
    LLMClient,
    LLMRequestError,
    attach_judge_score,
    evaluate_output,
    load_cases,
    load_dotenv,
    load_events,
    provider_config,
    should_skip_judge_failures,
    validate_benchmark,
)
from Experiment.run.run_public_benchmark import (  # noqa: E402
    PublicEvalRow,
    attach_public_judge_score,
    evaluate_public_output,
    load_public_cases,
    load_scope_profiles,
    route_scope_from_profiles,
    summarize_rows as summarize_public_rows,
    validate_public_cases,
)


PUBLIC_GRAPHITI_VARIANTS = ("graphiti_global_public", "graphiti_scope_routed_public")


def event_payload(event: object, run_id: str) -> Dict[str, object]:
    return {
        "benchmark": "stamb_state",
        "benchmark_run_id": run_id,
        "event_id": event.event_id,
        "scope_id": event.scope_id,
        "content": event.content,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "mentioned_at": event.mentioned_at,
        "updated_at": event.updated_at,
        "planned_for": event.planned_for,
        "deadline_at": event.deadline_at,
        "source_id": event.source_id,
        "metadata": dict(event.metadata),
    }


def parse_reference_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def graphiti_system_prompt() -> str:
    return (
        "你是 Graphiti/Zep baseline 的状态抽取器。"
        "你只能基于 Graphiti advanced search 返回的 facts、entities、受控 communities 和 scoped_episode_context 作答。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}, '
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "graphiti_facts 是主证据；scoped_episode_context 是 Graphiti scope 内 episode fallback，"
        "用于补足 facts 没有抽取出的最新有效状态。entities 和 communities 只能作为解释性上下文，"
        "不能覆盖 event payload。"
        "evidence_events、support_event、support_events 必须使用 graphiti_facts 或 scoped_episode_context 里的 event_id，"
        "不能使用 graphiti_fact_uuid、source_node_uuid 或 target_node_uuid。"
        "如果 context 没有明确给出 event_id，不要编造。"
        "必须按 time_role 构造 latest valid state：较新的 correction、decision、fix、progress、plan 可以更新状态；"
        "mention 或 execution_log 只有在明确改变状态时才可替代旧状态。"
        "如果查询问是否已经完成/提交/补完/复核/培训完成，而只有计划、草稿、待补或未复核记录，"
        "必须回答无法确认已经完成/提交/补完，并保留该计划/草稿/待办证据。"
        "answer 必须覆盖所有 output_slots。"
    )


def graphiti_episode_system_prompt() -> str:
    return (
        "你是 Graphiti+Episode diagnostic baseline 的状态抽取器。"
        "Graphiti search 已经负责找到相关 facts；你可以使用这些 facts 关联到的完整 episode payloads 作答。"
        "这个 baseline 用于诊断 fact extraction 或 returned-fact 信息损耗，不代表原生 Graphiti 输出。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}, '
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "evidence_events、support_event、support_events 必须使用 episode_context 里的 event_id。"
        "state_slots 只能包含用户要求的 output_slots。answer 必须覆盖所有 output_slots。"
    )


def graphiti_user_prompt(
    case: object,
    run_id: str,
    search_payload: Dict[str, object],
    baseline_name: str,
) -> str:
    payload = {
        "baseline": baseline_name,
        "benchmark_run_id": run_id,
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "output_slots": list(case.output_slots),
        "graphiti_facts": list(search_payload.get("facts", [])),
        "graphiti_entities": list(search_payload.get("entities", [])),
        "graphiti_communities": list(search_payload.get("communities", [])),
        "scoped_episode_context": list(search_payload.get("scoped_episode_context", [])),
        "evidence_policy": [
            "优先使用 graphiti_facts；当 facts 未覆盖当前状态所需证据时，使用 scoped_episode_context fallback。",
            "support_events 可以来自 graphiti_facts.event_ids 或 scoped_episode_context.event_id。",
            "communities 只用于解释，不可覆盖具体 event payload。",
        ],
        "task": (
            "根据 Graphiti advanced search context 填写 current valid state slots、support_events 和 answer。"
            "support_events 只能来自 graphiti_facts 或 scoped_episode_context 里的 event_id；"
            "不要使用未出现在 context 中的信息。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def graphiti_readout_verifier_system_prompt() -> str:
    return (
        "你是 Graphiti/Zep readout verifier。你只能基于给定的 Graphiti context 和 draft_output 修正输出。"
        "不得使用 context 外的信息，不得编造 event_id。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}, '
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "必须逐项检查所有 output_slots：缺 slot 就补，support_events 不完整就补，answer 漏 slot 就改写。"
        "support_events 只能来自 graphiti_facts.event_ids 或 scoped_episode_context.event_id。"
        "evidence_events 必须是所有 support_events 的去重集合。"
        "latest valid state 规则：mention/execution_log 若无新结论不能替代之前有效状态；"
        "correction/fix/decision/progress/plan 要按 time_role 合并为当前状态。"
        "如果问完成/提交/补完/复核/培训是否已经发生，而 context 只有计划、草稿、待补或未复核记录，"
        "必须写“无法确认已经完成/提交/补完”，并说明当前证据只有该计划/草稿/待办；"
        "不能写成确定的“未完成”“尚未完成”“未提交”。"
        "如果问题同时涉及 occurred_at 和 mentioned_at，answer 必须同时保留实际发生时间和记录/提及时间。"
        "如果 draft_output 已正确且完整，原样保持。"
    )


def graphiti_readout_verifier_user_prompt(
    case: object,
    run_id: str,
    search_payload: Dict[str, object],
    draft_raw: Dict[str, object],
) -> str:
    payload = {
        "benchmark_run_id": run_id,
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "time_roles": list(case.time_roles),
        "output_slots": list(case.output_slots),
        "graphiti_facts": list(search_payload.get("facts", [])),
        "graphiti_entities": list(search_payload.get("entities", [])),
        "graphiti_communities": list(search_payload.get("communities", [])),
        "scoped_episode_context": list(search_payload.get("scoped_episode_context", [])),
        "draft_output": draft_raw,
        "task": (
            "修正 draft_output，使每个 output_slot 的 value、support_event、support_events 和最终 answer "
            "都与 Graphiti context 中的 latest valid state 一致。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def graphiti_public_system_prompt() -> str:
    return (
        "你是 Graphiti/Zep public End-to-End readout。"
        "你只能基于 Graphiti search 返回的 facts、entities、communities 和 episode_context 作答。"
        "这是 public setting：你看不到 hidden scope_id、time_role、output_slots、gold states 或 gold support。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"facets": [{"name": "short_facet_name", "value": "string", "support_events": ["event_id"]}], '
        '"answer": "string"'
        "}。"
        "facets 是你自由识别的当前状态字段；每个 facet 必须有清晰 value 和来自 graphiti_facts "
        "或 episode_context 的 support_events。"
        "evidence_events 必须是所有 support_events 的去重集合。"
        "Graphiti facts 的 valid_at/invalid_at 可用于判断事实有效期；invalid/stale facts 可以解释旧状态，"
        "但不能直接当作当前状态。episode_context 是非损 raw episode fallback，可用于补足 Graphiti facts "
        "未抽取出的当前状态。"
        "如果证据只有计划、草稿、待办、待补或未复核记录，没有明确完成记录，必须表达无法确认已经完成。"
        "不要输出 state_slots，不要请求或假设 output_slots，不要使用 context 外的信息。"
    )


def graphiti_public_user_prompt(
    case: object,
    run_id: str,
    search_payload: Dict[str, object],
    variant_name: str,
    routed_scope: Optional[str],
    router_raw: Optional[Dict[str, object]],
    candidate_scope_profiles: Sequence[Dict[str, object]],
) -> str:
    payload = {
        "baseline": variant_name,
        "benchmark_run_id": run_id,
        "query": case.query,
        "operation": case.operation,
        "public_scope_hint": routed_scope,
        "scope_router_output": router_raw,
        "candidate_scope_profiles": list(candidate_scope_profiles),
        "graphiti_facts": list(search_payload.get("facts", [])),
        "graphiti_entities": list(search_payload.get("entities", [])),
        "graphiti_communities": list(search_payload.get("communities", [])),
        "episode_context": list(search_payload.get("scoped_episode_context", [])),
        "evidence_policy": [
            "优先使用 Graphiti facts；当 facts 没有保留足够状态细节时，可以使用 episode_context fallback。",
            "support_events 只能来自 graphiti_facts.event_ids 或 episode_context.event_id。",
            "communities/entities 只能作为解释性上下文，不能覆盖具体 event payload。",
        ],
        "task": (
            "根据 Graphiti/Zep 检索上下文，自由识别 query 需要的当前状态 facets，"
            "输出 facets、evidence_events 和 answer。不要输出 state_slots；不要假设 hidden output_slots。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def graphiti_public_readout_verifier_system_prompt() -> str:
    return (
        "你是 Graphiti/Zep public readout verifier。你只能基于给定 Graphiti context 和 draft_output 修正输出。"
        "不得使用 context 外的信息，不得编造 event_id。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"facets": [{"name": "short_facet_name", "value": "string", "support_events": ["event_id"]}], '
        '"answer": "string"'
        "}。"
        "检查 facets 是否覆盖 query 需要的当前状态、support_events 是否来自 context、answer 是否完整。"
        "如果 draft 使用 graphiti_fact_uuid 作为证据，改成对应 event_ids。"
        "不要新增 hidden scope_id、time_role、output_slots 或 state_slots。"
    )


def graphiti_public_readout_verifier_user_prompt(
    case: object,
    run_id: str,
    search_payload: Dict[str, object],
    draft_raw: Dict[str, object],
    variant_name: str,
    routed_scope: Optional[str],
) -> str:
    payload = {
        "baseline": variant_name,
        "benchmark_run_id": run_id,
        "query": case.query,
        "operation": case.operation,
        "public_scope_hint": routed_scope,
        "graphiti_facts": list(search_payload.get("facts", [])),
        "graphiti_entities": list(search_payload.get("entities", [])),
        "graphiti_communities": list(search_payload.get("communities", [])),
        "episode_context": list(search_payload.get("scoped_episode_context", [])),
        "draft_output": draft_raw,
        "task": "修正 public facets/evidence_events/answer，使其只使用 Graphiti context 中的 event_id。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def graphiti_episode_user_prompt(
    case: object,
    run_id: str,
    facts: Sequence[Dict[str, object]],
    episode_context: Sequence[Dict[str, object]],
) -> str:
    payload = {
        "baseline": "graphiti_episode_context",
        "benchmark_run_id": run_id,
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "output_slots": list(case.output_slots),
        "graphiti_search_results": list(facts),
        "episode_context": list(episode_context),
        "task": (
            "Graphiti search results 只用于说明这些 episode 为什么被召回；"
            "请根据 episode_context 中的完整 event payload 填写 current valid state slots、"
            "support_events 和 answer。不要使用 episode_context 之外的信息。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def graphiti_fact_view(
    result: object,
    episode_event_ids: Dict[str, str],
    score: Optional[float] = None,
) -> Dict[str, object]:
    episode_uuids = [str(item) for item in (getattr(result, "episodes", None) or [])]
    event_ids = []
    for episode_uuid in episode_uuids:
        event_id = episode_event_ids.get(episode_uuid)
        if event_id and event_id not in event_ids:
            event_ids.append(event_id)
    data: Dict[str, object] = {
        "graphiti_fact_uuid": getattr(result, "uuid", None),
        "event_ids": event_ids,
        "fact": getattr(result, "fact", str(result)),
        "valid_at": str(getattr(result, "valid_at", "")) if getattr(result, "valid_at", None) else None,
        "invalid_at": str(getattr(result, "invalid_at", "")) if getattr(result, "invalid_at", None) else None,
        "source_node_uuid": getattr(result, "source_node_uuid", None),
        "target_node_uuid": getattr(result, "target_node_uuid", None),
        "score": score,
    }
    return data


def graphiti_node_view(result: object, score: Optional[float]) -> Dict[str, object]:
    return {
        "graphiti_node_uuid": getattr(result, "uuid", None),
        "name": getattr(result, "name", None),
        "summary": getattr(result, "summary", None),
        "labels": list(getattr(result, "labels", []) or []),
        "score": score,
    }


def graphiti_community_view(result: object, score: Optional[float]) -> Dict[str, object]:
    return {
        "graphiti_community_uuid": getattr(result, "uuid", None),
        "name": getattr(result, "name", None),
        "summary": getattr(result, "summary", None),
        "labels": list(getattr(result, "labels", []) or []),
        "score": score,
    }


def score_at(scores: Sequence[float], index: int) -> Optional[float]:
    if index >= len(scores):
        return None
    return float(scores[index])


def parse_optional_time(value: object) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def text_features(text: str) -> Set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text.lower()))


def keyword_overlap(*parts: object) -> int:
    if len(parts) < 2:
        return 0
    base = text_features(str(parts[0]))
    other = text_features(" ".join(str(part) for part in parts[1:]))
    return len(base & other)


def slot_text(case: object) -> str:
    return " ".join(str(slot) for slot in getattr(case, "output_slots", ()))


def event_type_bonus(payload: Dict[str, object], case: object) -> int:
    event_type = str(payload.get("event_type", "")).lower()
    query_slots = f"{case.query} {slot_text(case)}".lower()
    bonus = 0
    if event_type in {"decision", "team_change", "budget", "deadline", "guideline"}:
        bonus += 4
    if event_type in {"correction", "fix", "mitigation", "root_cause"}:
        bonus += 4
    if event_type in {"issue", "diagnosis", "feedback"}:
        bonus += 3
    if event_type in {"plan", "draft", "progress"}:
        bonus += 3
    if any(token in query_slots for token in ("next", "planned", "plan", "下一步", "计划")) and event_type == "plan":
        bonus += 6
    if any(token in query_slots for token in ("完成", "提交", "补", "复核", "培训", "completion", "submission", "audit", "training", "review")):
        if event_type in {"plan", "draft", "progress"}:
            bonus += 6
    if any(token in query_slots for token in ("issue", "risk", "root", "问题", "风险", "根因")):
        if event_type in {"issue", "diagnosis", "root_cause", "correction", "fix", "mitigation"}:
            bonus += 5
    if any(token in query_slots for token in ("deadline", "截止")) and event_type == "deadline":
        bonus += 6
    return bonus


def episode_relevance_score(payload: Dict[str, object], case: object, rank_index: int) -> float:
    query = f"{case.query} {slot_text(case)} {case.operation}"
    text = " ".join(
        str(payload.get(key, ""))
        for key in ("content", "event_type", "planned_for", "deadline_at", "source_id")
    )
    score = float(keyword_overlap(query, text))
    score += float(event_type_bonus(payload, case))
    time_role = getattr(case, "time_role", "updated_at")
    event_time = parse_optional_time(payload.get(time_role) or payload.get("updated_at"))
    if event_time != datetime.min.replace(tzinfo=timezone.utc):
        score += rank_index / 1000.0
    return score


def scope_marker(run_id: str) -> str:
    return f'"benchmark_run_id": "{run_id}"'


def graphiti_search_config(limit: int) -> object:
    from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_CROSS_ENCODER

    config = deepcopy(COMBINED_HYBRID_SEARCH_CROSS_ENCODER)
    config.limit = limit
    return config


async def ingest_events(
    graphiti: object,
    events: Sequence[object],
    run_id: str,
    batch_size: int,
    timeout_seconds: int,
) -> None:
    from graphiti_core.nodes import EpisodeType
    from graphiti_core.utils.bulk_utils import RawEpisode

    episodes = [
        RawEpisode(
            name=f"stamb-{run_id}-{event.event_id}",
            content=json.dumps(event_payload(event, run_id), ensure_ascii=False),
            source=EpisodeType.json,
            source_description=f"STAMB-State event scope={event.scope_id} event_id={event.event_id}",
            reference_time=parse_reference_time(event.updated_at),
        )
        for event in events
    ]
    for start in range(0, len(episodes), batch_size):
        batch = episodes[start : start + batch_size]
        batch_no = start // batch_size + 1
        batch_count = (len(episodes) + batch_size - 1) // batch_size
        print(
            f"ingesting Graphiti batch {batch_no}/{batch_count} "
            f"events {start + 1}-{start + len(batch)}",
            flush=True,
        )
        await asyncio.wait_for(
            graphiti.add_episode_bulk(batch),
            timeout=timeout_seconds,
        )


async def reset_graphiti_data(graphiti: object, *, run_id: Optional[str] = None) -> Dict[str, int]:
    if run_id:
        episode_filter = (
            "ep.source_description STARTS WITH 'STAMB-State event' "
            "AND ep.content CONTAINS $run_marker"
        )
        params = {"run_marker": f'"benchmark_run_id": "{run_id}"'}
    else:
        episode_filter = (
            "ep.source_description STARTS WITH 'STAMB-State event' "
            "OR ep.content CONTAINS '\"benchmark\": \"stamb_state\"'"
        )
        params = {}

    query = f"""
        MATCH (ep:Episodic)
        WHERE {episode_filter}
        WITH collect(DISTINCT ep) AS episodes, collect(DISTINCT ep.uuid) AS episode_ids
        OPTIONAL MATCH (mentioned_ep:Episodic)-[:MENTIONS]->(mentioned:Entity)
        WHERE mentioned_ep.uuid IN episode_ids
        WITH
            episodes,
            episode_ids,
            [entity_item IN collect(DISTINCT mentioned) WHERE entity_item IS NOT NULL] AS touched_entities,
            [entity_id IN collect(DISTINCT mentioned.uuid) WHERE entity_id IS NOT NULL] AS entity_ids
        OPTIONAL MATCH ()-[rel:RELATES_TO]->()
        WHERE any(episode_id IN coalesce(rel.episodes, []) WHERE episode_id IN episode_ids)
        WITH
            episodes,
            episode_ids,
            entity_ids,
            touched_entities,
            [rel_item IN collect(DISTINCT rel) WHERE rel_item IS NOT NULL] AS relates_to_edges
        OPTIONAL MATCH (community:Community)-[member_rel:HAS_MEMBER]-(entity:Entity)
        WHERE entity IN touched_entities
        WITH
            episodes,
            episode_ids,
            entity_ids,
            touched_entities,
            relates_to_edges,
            [community_item IN collect(DISTINCT community) WHERE community_item IS NOT NULL] AS communities,
            [member_rel_item IN collect(DISTINCT member_rel) WHERE member_rel_item IS NOT NULL] AS community_edges
        WITH
            episodes,
            episode_ids,
            entity_ids,
            touched_entities,
            relates_to_edges,
            communities,
            community_edges,
            size(relates_to_edges) AS deleted_relates_to,
            size(community_edges) AS deleted_community_edges,
            size(communities) AS deleted_communities
        FOREACH (rel_item IN relates_to_edges | DELETE rel_item)
        FOREACH (community_edge_item IN community_edges | DELETE community_edge_item)
        FOREACH (ep_item IN episodes | DETACH DELETE ep_item)
        FOREACH (community_item IN communities | DETACH DELETE community_item)
        WITH
            episode_ids,
            entity_ids,
            touched_entities,
            deleted_relates_to,
            deleted_community_edges,
            deleted_communities
        OPTIONAL MATCH (entity:Entity)
        WHERE entity IN touched_entities AND NOT (entity)--()
        WITH
            size(episode_ids) AS deleted_episodes,
            size(entity_ids) AS touched_entities,
            deleted_relates_to,
            deleted_community_edges,
            deleted_communities,
            [entity_item IN collect(DISTINCT entity) WHERE entity_item IS NOT NULL] AS orphan_entities
        FOREACH (entity_item IN orphan_entities | DELETE entity_item)
        RETURN
            deleted_episodes,
            touched_entities,
            deleted_relates_to,
            deleted_community_edges,
            deleted_communities,
            size(orphan_entities) AS deleted_orphan_entities
    """
    result = await graphiti.driver.execute_query(query, params=params)
    row = result.records[0] if result.records else {}
    return {
        "deleted_episodes": int(row.get("deleted_episodes", 0)),
        "touched_entities": int(row.get("touched_entities", 0)),
        "deleted_relates_to": int(row.get("deleted_relates_to", 0)),
        "deleted_community_edges": int(row.get("deleted_community_edges", 0)),
        "deleted_communities": int(row.get("deleted_communities", 0)),
        "deleted_orphan_entities": int(row.get("deleted_orphan_entities", 0)),
    }


async def load_episode_event_ids(graphiti: object, run_id: str) -> Dict[str, str]:
    query = """
        MATCH (ep:Episodic)
        WHERE ep.source_description STARTS WITH 'STAMB-State event'
          AND ep.content CONTAINS $run_marker
        RETURN ep.uuid AS uuid, ep.content AS content
    """
    result = await graphiti.driver.execute_query(
        query,
        params={"run_marker": f'"benchmark_run_id": "{run_id}"'},
    )
    episode_event_ids: Dict[str, str] = {}
    for row in result.records:
        try:
            content = json.loads(row["content"])
        except (TypeError, json.JSONDecodeError):
            continue
        event_id = content.get("event_id")
        if event_id:
            episode_event_ids[str(row["uuid"])] = str(event_id)
    return episode_event_ids


async def load_scope_edge_uuids(
    graphiti: object,
    episode_event_ids: Dict[str, str],
    event_scopes: Dict[str, str],
    scope_id: str,
) -> tuple[List[str], List[str]]:
    scope_episode_uuids = [
        episode_uuid
        for episode_uuid, event_id in episode_event_ids.items()
        if event_scopes.get(event_id) == scope_id
    ]
    if not scope_episode_uuids:
        return [], []
    query = """
        MATCH ()-[rel:RELATES_TO]->()
        WHERE any(episode_id IN coalesce(rel.episodes, []) WHERE episode_id IN $episode_uuids)
        RETURN DISTINCT rel.uuid AS uuid
    """
    result = await graphiti.driver.execute_query(
        query,
        params={"episode_uuids": scope_episode_uuids},
    )
    edge_uuids = [str(row["uuid"]) for row in result.records if row.get("uuid")]
    return scope_episode_uuids, edge_uuids


async def load_run_edge_uuids(
    graphiti: object,
    episode_event_ids: Dict[str, str],
) -> tuple[List[str], List[str]]:
    run_episode_uuids = list(episode_event_ids)
    if not run_episode_uuids:
        return [], []
    query = """
        MATCH ()-[rel:RELATES_TO]->()
        WHERE any(episode_id IN coalesce(rel.episodes, []) WHERE episode_id IN $episode_uuids)
        RETURN DISTINCT rel.uuid AS uuid
    """
    result = await graphiti.driver.execute_query(
        query,
        params={"episode_uuids": run_episode_uuids},
    )
    edge_uuids = [str(row["uuid"]) for row in result.records if row.get("uuid")]
    return run_episode_uuids, edge_uuids


async def load_scope_episode_context(
    graphiti: object,
    scope_episode_uuids: Sequence[str],
    case: object,
    run_id: str,
    limit: int,
    scope_id: Optional[str] = None,
) -> List[Dict[str, object]]:
    if limit <= 0 or not scope_episode_uuids:
        return []
    query = """
        MATCH (ep:Episodic)
        WHERE ep.uuid IN $episode_uuids
          AND ep.content CONTAINS $run_marker
        RETURN ep.uuid AS uuid, ep.content AS content
    """
    result = await graphiti.driver.execute_query(
        query,
        params={"episode_uuids": list(scope_episode_uuids), "run_marker": scope_marker(run_id)},
    )
    payloads: List[Dict[str, object]] = []
    for row in result.records:
        try:
            payload = json.loads(row["content"])
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("benchmark_run_id") != run_id:
            continue
        if scope_id and payload.get("scope_id") != scope_id:
            continue
        payload = dict(payload)
        payload["graphiti_episode_uuid"] = str(row["uuid"])
        payloads.append(payload)

    time_role = getattr(case, "time_role", "updated_at")
    payloads.sort(
        key=lambda payload: parse_optional_time(payload.get(time_role) or payload.get("updated_at")),
        reverse=True,
    )
    scored_payloads: List[Dict[str, object]] = []
    for rank_index, payload in enumerate(payloads):
        scored = dict(payload)
        scored["episode_fallback_score"] = round(episode_relevance_score(scored, case, len(payloads) - rank_index), 3)
        scored_payloads.append(scored)
    scored_payloads.sort(
        key=lambda payload: (
            float(payload.get("episode_fallback_score", 0.0)),
            parse_optional_time(payload.get(time_role) or payload.get("updated_at")),
        ),
        reverse=True,
    )
    for index, payload in enumerate(scored_payloads[:limit], start=1):
        payload["episode_fallback_rank"] = index
    return scored_payloads[:limit]


def rerank_facts_with_episode_context(
    facts: Sequence[Dict[str, object]],
    episode_context: Sequence[Dict[str, object]],
    case: object,
    limit: int,
) -> List[Dict[str, object]]:
    event_scores = {
        str(payload.get("event_id")): float(payload.get("episode_fallback_score", 0.0))
        for payload in episode_context
        if payload.get("event_id")
    }
    time_role = getattr(case, "time_role", "updated_at")
    event_times = {
        str(payload.get("event_id")): parse_optional_time(payload.get(time_role) or payload.get("updated_at"))
        for payload in episode_context
        if payload.get("event_id")
    }

    reranked: List[Dict[str, object]] = []
    for original_rank, fact in enumerate(facts, start=1):
        event_ids = [str(event_id) for event_id in fact.get("event_ids", []) if event_id]
        relevance = max((event_scores.get(event_id, 0.0) for event_id in event_ids), default=0.0)
        latest_time = max((event_times.get(event_id, datetime.min.replace(tzinfo=timezone.utc)) for event_id in event_ids), default=datetime.min.replace(tzinfo=timezone.utc))
        rerank_score = relevance + (1.0 / original_rank)
        if fact.get("invalid_at"):
            rerank_score -= 0.25
        updated = dict(fact)
        updated["graphiti_original_rank"] = original_rank
        updated["adapter_rerank_score"] = round(rerank_score, 3)
        updated["adapter_latest_event_time"] = latest_time.isoformat() if latest_time != datetime.min.replace(tzinfo=timezone.utc) else None
        reranked.append(updated)
    reranked.sort(
        key=lambda fact: (
            float(fact.get("adapter_rerank_score", 0.0)),
            str(fact.get("adapter_latest_event_time") or ""),
        ),
        reverse=True,
    )
    return reranked[:limit]


def filter_communities_for_case(
    communities: Sequence[Dict[str, object]],
    case: object,
    limit: int,
    scope_id: Optional[str] = None,
) -> List[Dict[str, object]]:
    query = " ".join(
        part
        for part in (
            scope_id or getattr(case, "scope_id", ""),
            getattr(case, "query", ""),
            slot_text(case),
            getattr(case, "operation", ""),
        )
        if part
    )
    filtered: List[Dict[str, object]] = []
    for community in communities:
        text = f"{community.get('name', '')} {community.get('summary', '')}"
        overlap = keyword_overlap(query, text)
        if overlap <= 0:
            continue
        updated = dict(community)
        updated["adapter_query_overlap"] = overlap
        filtered.append(updated)
    filtered.sort(key=lambda item: (int(item.get("adapter_query_overlap", 0)), float(item.get("score") or 0.0)), reverse=True)
    return filtered[:limit]


def normalize_graphiti_output_event_ids(
    raw: Dict[str, object],
    facts: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    replacements: Dict[str, List[str]] = {}
    for fact in facts:
        event_ids = [str(event_id) for event_id in fact.get("event_ids", []) if event_id]
        fact_uuid = fact.get("graphiti_fact_uuid")
        if fact_uuid and event_ids:
            replacements[str(fact_uuid)] = event_ids

    def normalize_ids(values: object) -> List[str]:
        if isinstance(values, str):
            raw_values = [values]
        elif isinstance(values, list):
            raw_values = [str(value) for value in values if value]
        else:
            raw_values = []

        normalized: List[str] = []
        for value in raw_values:
            mapped_values = replacements.get(value, [value])
            for mapped_value in mapped_values:
                if mapped_value not in normalized:
                    normalized.append(mapped_value)
        return normalized

    raw["evidence_events"] = normalize_ids(raw.get("evidence_events"))

    state_slots = raw.get("state_slots")
    if isinstance(state_slots, dict):
        for slot_data in state_slots.values():
            if not isinstance(slot_data, dict):
                continue
            support_values = slot_data.get("support_events")
            if not support_values and slot_data.get("support_event"):
                support_values = [slot_data.get("support_event")]
            support_events = normalize_ids(support_values)
            slot_data["support_events"] = support_events
            slot_data["support_event"] = support_events[0] if support_events else None
    facets = raw.get("facets")
    if isinstance(facets, list):
        for facet in facets:
            if not isinstance(facet, dict):
                continue
            facet["support_events"] = normalize_ids(facet.get("support_events"))
    return raw


def filter_facts_to_scope(
    facts: Sequence[Dict[str, object]],
    scope_id: str,
    event_scopes: Dict[str, str],
    limit: int,
) -> List[Dict[str, object]]:
    scoped_facts: List[Dict[str, object]] = []
    for fact in facts:
        event_ids = [str(event_id) for event_id in fact.get("event_ids", []) if event_id]
        scoped_event_ids = [event_id for event_id in event_ids if event_scopes.get(event_id) == scope_id]
        if not scoped_event_ids:
            continue
        scoped_fact = dict(fact)
        scoped_fact["event_ids"] = scoped_event_ids
        scoped_facts.append(scoped_fact)
        if len(scoped_facts) >= limit:
            break
    return scoped_facts


def filter_facts_to_events(
    facts: Sequence[Dict[str, object]],
    allowed_event_ids: Set[str],
    limit: int,
) -> List[Dict[str, object]]:
    filtered_facts: List[Dict[str, object]] = []
    for fact in facts:
        event_ids = [str(event_id) for event_id in fact.get("event_ids", []) if event_id]
        allowed_ids = [event_id for event_id in event_ids if event_id in allowed_event_ids]
        if not allowed_ids:
            continue
        filtered_fact = dict(fact)
        filtered_fact["event_ids"] = allowed_ids
        filtered_facts.append(filtered_fact)
        if len(filtered_facts) >= limit:
            break
    return filtered_facts


async def search_case(
    graphiti: object,
    case: object,
    run_id: str,
    limit: int,
    pool_limit: int,
    episode_fallback_limit: int,
    episode_event_ids: Dict[str, str],
    event_scopes: Dict[str, str],
    scope_id: Optional[str] = None,
    public_mode: bool = False,
) -> tuple[Dict[str, object], Dict[str, int]]:
    from graphiti_core.search.search_filters import SearchFilters

    selected_scope = scope_id if scope_id is not None else (None if public_mode else getattr(case, "scope_id", None))
    if public_mode:
        query_parts = [
            f"benchmark_run_id={run_id}",
            f"scope_hint={selected_scope}" if selected_scope else "scope_hint=global",
            f"question={case.query}",
            f"operation={case.operation}",
        ]
    else:
        query_parts = [
            f"benchmark_run_id={run_id}",
            f"scope_id={selected_scope}",
            f"question={case.query}",
            f"output_slots={', '.join(case.output_slots)}",
        ]
    query = "; ".join(part for part in query_parts if part)
    if selected_scope:
        selected_episode_uuids, selected_edge_uuids = await load_scope_edge_uuids(
            graphiti,
            episode_event_ids,
            event_scopes,
            selected_scope,
        )
    else:
        selected_episode_uuids, selected_edge_uuids = await load_run_edge_uuids(graphiti, episode_event_ids)
    search_filter = SearchFilters(edge_uuids=selected_edge_uuids)
    results = await graphiti.search_(
        query=query,
        config=graphiti_search_config(pool_limit),
        search_filter=search_filter,
    )
    facts = [
        graphiti_fact_view(result, episode_event_ids, score_at(results.edge_reranker_scores, index))
        for index, result in enumerate(results.edges)
    ]
    if selected_scope:
        scoped_facts = filter_facts_to_scope(facts, selected_scope, event_scopes, limit)
    else:
        scoped_facts = filter_facts_to_events(facts, set(event_scopes), limit)
    scoped_episode_context = await load_scope_episode_context(
        graphiti,
        selected_episode_uuids,
        case,
        run_id,
        episode_fallback_limit,
        scope_id=selected_scope,
    )
    scoped_facts = rerank_facts_with_episode_context(scoped_facts, scoped_episode_context, case, limit)
    scoped_node_uuids = {
        str(node_uuid)
        for fact in scoped_facts
        for node_uuid in (fact.get("source_node_uuid"), fact.get("target_node_uuid"))
        if node_uuid
    }
    entities = [
        graphiti_node_view(result, score_at(results.node_reranker_scores, index))
        for index, result in enumerate(results.nodes)
        if not scoped_node_uuids or str(getattr(result, "uuid", "")) in scoped_node_uuids
    ]
    communities = [
        graphiti_community_view(result, score_at(results.community_reranker_scores, index))
        for index, result in enumerate(results.communities)
    ]
    controlled_communities = filter_communities_for_case(communities, case, limit, scope_id=selected_scope)
    search_scope_label = selected_scope or "__global__"
    payload = {
        "query": query,
        "selected_scope": selected_scope,
        "facts": scoped_facts,
        "entities": entities[:limit],
        "communities": controlled_communities,
        "scoped_episode_context": scoped_episode_context,
        "search_config": (
            "COMBINED_HYBRID_SEARCH_CROSS_ENCODER + "
            f"{'scope' if selected_scope else 'run'} edge_uuid filter "
            "+ adapter event_id rerank + scoped episode fallback + controlled communities"
        ),
    }
    raw_counts = {
        "search_scope": search_scope_label,
        "scope_episode_uuids": len(selected_episode_uuids),
        "scope_edge_uuids": len(selected_edge_uuids),
        "facts": len(facts),
        "scoped_facts": len(scoped_facts),
        "entities": len(entities),
        "communities": len(communities),
        "controlled_communities": len(controlled_communities),
        "episodes": len(results.episodes),
        "scoped_episode_context": len(scoped_episode_context),
    }
    return payload, raw_counts


def episode_context_from_facts(
    facts: Sequence[Dict[str, object]],
    events_by_id: Dict[str, object],
    run_id: str,
) -> List[Dict[str, object]]:
    context: List[Dict[str, object]] = []
    seen_event_ids = set()
    for fact in facts:
        for event_id in [str(item) for item in fact.get("event_ids", []) if item]:
            if event_id in seen_event_ids:
                continue
            event = events_by_id.get(event_id)
            if event is None:
                continue
            context.append(event_payload(event, run_id))
            seen_event_ids.add(event_id)
    return context


def summarize_rows(
    rows: Sequence[EvalRow],
    provider: str,
    model: str,
    judge_client: Optional[LLMClient],
    variant_name: str,
) -> Dict[str, object]:
    judge_scores = [row.slot_value_judge for row in rows if row.slot_value_judge is not None]
    answer_scores = [row.answer_judge for row in rows if row.answer_judge is not None]
    judge_failed_cases = [row.case_id for row in rows if judge_client is not None and row.judge_output is None]
    context_scores = [row.context_event_recall for row in rows if row.context_event_recall is not None]
    return {
        "variant": variant_name,
        "model_provider": provider,
        "model": model,
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
        "judge_scored_cases": len(judge_scores),
        "judge_failed_cases": judge_failed_cases,
        "cases": [row.__dict__ for row in rows],
    }


def configure_openai_env_for_graphiti() -> None:
    if os.environ.get("OPENAI_API_BASE") and not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = os.environ["OPENAI_API_BASE"]
    os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")


def env_first(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def resolve_cross_encoder_name(requested: str, model: str, graphiti_provider: str = "openai") -> str:
    if requested != "auto":
        return requested
    if graphiti_provider == "deepseek":
        return "bge"
    normalized_model = model.lower().replace("_", "-")
    if normalized_model.startswith("gpt-5") or normalized_model.startswith("gpt5"):
        return "bge"
    return "openai"


def resolve_embedder_name(requested: str, model: str, graphiti_provider: str = "openai") -> str:
    if requested != "auto":
        return requested
    if graphiti_provider == "deepseek":
        return "bge"
    normalized_model = model.lower().replace("_", "-")
    if normalized_model.startswith("gpt-5") or normalized_model.startswith("gpt5"):
        return "bge"
    return "openai"


class SentenceTransformerEmbedder(EmbedderClient):
    def __init__(self, model_name: str, embedding_dim: int):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for --embedder bge. "
                "Install with: pip install 'graphiti-core[sentence-transformers]' sentence-transformers"
            ) from exc

        self.model_name = model_name
        self.embedding_dim = embedding_dim
        self.model = SentenceTransformer(model_name)

    def _normalize_input(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> str:
        if isinstance(input_data, str):
            return input_data
        if isinstance(input_data, list) and all(isinstance(item, str) for item in input_data):
            return "\n".join(input_data)
        return " ".join(str(item) for item in input_data)

    def _encode_one(self, text: str) -> List[float]:
        vector = self.model.encode(text, normalize_embeddings=True)
        return [float(value) for value in vector[: self.embedding_dim]]

    def _encode_batch(self, texts: Sequence[str]) -> List[List[float]]:
        vectors = self.model.encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in vector[: self.embedding_dim]] for vector in vectors]

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> List[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._encode_one, self._normalize_input(input_data))

    async def create_batch(self, input_data_list: List[str]) -> List[List[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._encode_batch, input_data_list)


def parse_json_object(text: str) -> Dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as first_error:
        start = stripped.find("{")
        if start == -1:
            raise
        decoder = json.JSONDecoder()
        try:
            value, _ = decoder.raw_decode(stripped[start:])
            if not isinstance(value, dict):
                raise ValueError("model JSON output is not an object")
            return value
        except json.JSONDecodeError:
            end = stripped.rfind("}")
            if end == -1 or end <= start:
                raise
            candidate = stripped[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    import json_repair

                    value = json.loads(json_repair.repair_json(candidate))
                except Exception as repair_error:
                    raise repair_error from first_error
                if not isinstance(value, dict):
                    raise ValueError("model JSON output is not an object")
                return value


def build_graphiti_clients(
    graphiti_provider: str,
    cross_encoder_name: str,
    embedder_name: str,
    bge_embedding_model: str,
) -> Dict[str, object]:
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

    class LenientOpenAIGenericClient(OpenAIGenericClient):
        async def _generate_response(
            self,
            messages: list[object],
            response_model: object = None,
            max_tokens: int = 8192,
            model_size: object = None,
        ) -> Dict[str, object]:
            try:
                return await super()._generate_response(
                    messages,
                    response_model=response_model,
                    max_tokens=max_tokens,
                    model_size=model_size,
                )
            except Exception as exc:
                if "response_format" not in str(exc):
                    raise

            openai_messages = []
            for message in messages:
                content = self._clean_input(getattr(message, "content"))
                if response_model is not None and getattr(message, "role") == "user":
                    schema = response_model.model_json_schema()
                    content += (
                        "\n\nReturn only a valid JSON object matching this JSON schema. "
                        "Do not include Markdown fences or commentary.\n"
                        f"{json.dumps(schema, ensure_ascii=False)}"
                    )
                openai_messages.append({"role": getattr(message, "role"), "content": content})
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return parse_json_object(response.choices[0].message.content or "")

    if graphiti_provider == "deepseek":
        api_key, model, base_url = provider_config("deepseek")
    else:
        api_key = env_first("OPENAI_API_KEY")
        base_url = env_first("OPENAI_BASE_URL", "OPENAI_API_BASE")
        model = env_first("OPENAI_MODEL")
    embedding_api_key = env_first("OPENAI_EMBEDDING_API_KEY", "OPENAI_API_KEY")
    embedding_base_url = env_first(
        "OPENAI_EMBEDDING_BASE_URL",
        "OPENAI_EMBEDDING_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
    )
    embedding_model = env_first("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
    embedding_dim = int(env_first("OPENAI_EMBEDDING_DIM", "EMBEDDING_DIM") or "1024")
    if not api_key:
        raise RuntimeError("missing OPENAI_API_KEY for Graphiti")
    if not model:
        raise RuntimeError("missing OPENAI_MODEL for Graphiti")
    if not embedding_api_key:
        raise RuntimeError("missing OPENAI_EMBEDDING_API_KEY or OPENAI_API_KEY for Graphiti embeddings")
    llm_config = LLMConfig(api_key=api_key, model=model, small_model=model, base_url=base_url, temperature=0)
    resolved_cross_encoder_name = resolve_cross_encoder_name(cross_encoder_name, model, graphiti_provider)
    resolved_embedder_name = resolve_embedder_name(embedder_name, model, graphiti_provider)
    if resolved_embedder_name == "bge":
        embedder = SentenceTransformerEmbedder(bge_embedding_model, embedding_dim)
        resolved_embedding_model = bge_embedding_model
    else:
        embedder_config = OpenAIEmbedderConfig(
            api_key=embedding_api_key,
            base_url=embedding_base_url,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        )
        embedder = OpenAIEmbedder(config=embedder_config)
        resolved_embedding_model = embedding_model
    if resolved_cross_encoder_name == "bge":
        try:
            from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient
        except ImportError as exc:
            raise RuntimeError(
                "missing sentence-transformers for --cross-encoder bge. "
                "Install with: pip install graphiti-core[sentence-transformers]"
            ) from exc
        cross_encoder = BGERerankerClient()
    else:
        cross_encoder = OpenAIRerankerClient(config=llm_config)
    return {
        "llm_client": LenientOpenAIGenericClient(config=llm_config, max_tokens=8192),
        "graphiti_provider": graphiti_provider,
        "graphiti_model": model,
        "embedder": embedder,
        "cross_encoder": cross_encoder,
        "cross_encoder_name": resolved_cross_encoder_name,
        "cross_encoder_requested": cross_encoder_name,
        "embedder_name": resolved_embedder_name,
        "embedder_requested": embedder_name,
        "embedding_model": resolved_embedding_model,
    }


def build_graphiti_driver(uri: str, user: str, password: str) -> object:
    from graphiti_core.driver.neo4j_driver import Neo4jDriver

    database = os.environ.get("NEO4J_DATABASE") or "neo4j"
    return Neo4jDriver(uri=uri, user=user, password=password, database=database)


def validate_limited_events_cover_cases(events: Sequence[object], cases: Sequence[object]) -> None:
    event_ids = {event.event_id for event in events}
    missing: List[str] = []
    for case in cases:
        needed = set(case.gold_events)
        for support_events in case.gold_slot_support.values():
            needed.update(support_events)
        missing_events = sorted(needed - event_ids)
        if missing_events:
            missing.append(f"{case.case_id}: missing {', '.join(missing_events)}")
    if missing:
        raise RuntimeError(
            "--limit-events removed gold/support events for selected cases: "
            + "; ".join(missing)
        )


async def run(args: argparse.Namespace) -> int:
    public_mode = args.variant in PUBLIC_GRAPHITI_VARIANTS
    load_dotenv()
    configure_openai_env_for_graphiti()

    data_dir = BENCHMARK_DIR / "data" / args.data_version
    events_path = Path(args.events) if args.events else data_dir / "events_raw.json"
    events = load_events(events_path)
    public_cases_path: Optional[Path] = None
    scope_profiles_path: Optional[Path] = None
    hidden_cases_by_id: Dict[str, object] = {}
    if public_mode:
        public_cases_path = Path(args.public_cases or args.cases) if (args.public_cases or args.cases) else data_dir / "public" / "cases.json"
        gold_cases_path = Path(args.gold_cases) if args.gold_cases else data_dir / "cases.json"
        public_cases = load_public_cases(public_cases_path)
        hidden_cases = load_cases(gold_cases_path)
        validate_benchmark(events, hidden_cases)
        validate_public_cases(public_cases, hidden_cases)
        if args.limit_cases:
            public_cases = public_cases[: args.limit_cases]
        hidden_cases_by_id = {case.case_id: case for case in hidden_cases}
        selected_hidden_cases = [hidden_cases_by_id[case.case_id] for case in public_cases]
        cases = public_cases
        cases_path = public_cases_path
        scope_profiles_path = Path(args.scope_profiles) if args.scope_profiles else data_dir / "public" / "scope_profiles.json"
        scope_profiles = load_scope_profiles(scope_profiles_path, events)
    else:
        cases_path = Path(args.cases) if args.cases else data_dir / "cases.json"
        cases = load_cases(cases_path)
        validate_benchmark(events, cases)
        if args.limit_cases:
            cases = cases[: args.limit_cases]
        selected_hidden_cases = list(cases)
        scope_profiles = []

    if args.limit_events:
        events = events[: args.limit_events]
    try:
        validate_limited_events_cover_cases(events, selected_hidden_cases)
    except RuntimeError as exc:
        print(f"Benchmark subset error: {exc}", file=sys.stderr)
        return 2
    event_scopes = {event.event_id: event.scope_id for event in events}
    events_by_id = {event.event_id: event for event in events}

    if args.dry_run:
        mode = "public End-to-End" if public_mode else "oracle-facet"
        print(
            f"valid Graphiti {mode} benchmark: events={len(events)} cases={len(cases)} "
            f"variant={args.variant}"
        )
        print(f"events_path={events_path}")
        print(f"cases_path={cases_path}")
        if public_mode:
            print(f"gold_cases_path={gold_cases_path}")
            print(f"scope_profiles_path={scope_profiles_path} profiles={len(scope_profiles)}")
        return 0

    try:
        from graphiti_core import Graphiti
    except ModuleNotFoundError:
        print("Missing dependency: graphiti_core. Install with: pip install graphiti-core", file=sys.stderr)
        return 2

    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME") or "neo4j"
    neo4j_password = os.environ.get("NEO4J_PASSWORD")
    if not neo4j_password:
        print("Missing NEO4J_PASSWORD. Graphiti requires a running Neo4j or FalkorDB backend.", file=sys.stderr)
        return 2

    client = LLMClient(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )

    judge_client: Optional[LLMClient] = None
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

    try:
        graphiti_clients = build_graphiti_clients(
            args.graphiti_provider,
            args.cross_encoder,
            args.embedder,
            args.bge_embedding_model,
        )
    except RuntimeError as exc:
        print(f"Graphiti config error: {exc}", file=sys.stderr)
        return 2

    graphiti = Graphiti(
        graph_driver=build_graphiti_driver(neo4j_uri, neo4j_user, neo4j_password),
        llm_client=graphiti_clients["llm_client"],
        embedder=graphiti_clients["embedder"],
        cross_encoder=graphiti_clients["cross_encoder"],
    )
    rows: List[object] = []
    reset_summary: Optional[Dict[str, int]] = None
    try:
        if args.reset_benchmark_data or args.reset_run:
            reset_scope = f"run_id={args.run_id}" if args.reset_run else "all STAMB benchmark data"
            print(f"resetting Graphiti data for {reset_scope}", flush=True)
            reset_summary = await reset_graphiti_data(
                graphiti,
                run_id=args.run_id if args.reset_run else None,
            )
            print(f"reset summary: {reset_summary}", flush=True)
        await graphiti.build_indices_and_constraints()
        if not args.skip_ingest:
            print(f"ingesting {len(events)} events into Graphiti run_id={args.run_id}", flush=True)
            await ingest_events(
                graphiti,
                events,
                args.run_id,
                batch_size=args.ingest_batch_size,
                timeout_seconds=args.ingest_timeout,
            )
        episode_event_ids = await load_episode_event_ids(graphiti, args.run_id)
        print(f"loaded {len(episode_event_ids)} Graphiti episode -> event_id mappings", flush=True)
        if args.ingest_only:
            result = {
                "variant": args.variant,
                "ingest_only": True,
                "run_id": args.run_id,
                "events_path": str(events_path),
                "cases_path": str(cases_path),
                "event_count": len(events),
                "case_count": len(cases),
                "episode_event_mapping_count": len(episode_event_ids),
                "reset_summary": reset_summary,
                "graphiti_provider": graphiti_clients["graphiti_provider"],
                "graphiti_model": graphiti_clients["graphiti_model"],
                "graphiti_cross_encoder": graphiti_clients["cross_encoder_name"],
                "graphiti_cross_encoder_requested": args.cross_encoder,
                "graphiti_embedder": graphiti_clients["embedder_name"],
                "graphiti_embedder_requested": args.embedder,
                "graphiti_embedding_model": graphiti_clients["embedding_model"],
            }
            output_path = Path(args.output)
            output_path.parent.mkdir(exist_ok=True)
            output_path.write_text(json.dumps([result], ensure_ascii=False, indent=2))
            print(f"Wrote {output_path}")
            return 0
        for case in cases:
            print(f"running {args.variant} / {case.case_id}", flush=True)
            if public_mode:
                hidden_case = hidden_cases_by_id[case.case_id]
                routed_scope = None
                router_raw = None
                candidate_scope_profiles: List[Dict[str, object]] = []
                if args.variant == "graphiti_scope_routed_public":
                    routed_scope, router_raw, candidate_scope_profiles = route_scope_from_profiles(
                        client,
                        events,
                        scope_profiles,
                        case,
                        args.scope_top_k,
                    )
                search_payload, graphiti_raw_search_counts = await search_case(
                    graphiti,
                    case,
                    args.run_id,
                    args.search_limit,
                    args.search_pool_limit,
                    args.episode_fallback_limit,
                    episode_event_ids,
                    event_scopes,
                    scope_id=routed_scope,
                    public_mode=True,
                )
                facts = list(search_payload.get("facts", []))
                draft_raw = client.complete_json(
                    graphiti_public_system_prompt(),
                    graphiti_public_user_prompt(
                        case,
                        args.run_id,
                        search_payload,
                        args.variant,
                        routed_scope,
                        router_raw,
                        candidate_scope_profiles,
                    ),
                )
                draft_trace = deepcopy(draft_raw)
                if args.disable_readout_verifier:
                    raw = draft_raw
                    verifier_trace = None
                else:
                    verifier_raw = client.complete_json(
                        graphiti_public_readout_verifier_system_prompt(),
                        graphiti_public_readout_verifier_user_prompt(
                            case,
                            args.run_id,
                            search_payload,
                            draft_raw,
                            args.variant,
                            routed_scope,
                        ),
                    )
                    verifier_trace = deepcopy(verifier_raw)
                    raw = verifier_raw
                raw = normalize_graphiti_output_event_ids(raw, facts)
                raw["pipeline_trace"] = {
                    "variant": args.variant,
                    "graphiti_run_id": args.run_id,
                    "public_mode": True,
                    "scope_router_output": router_raw,
                    "routed_scope": routed_scope,
                    "scope_profile_candidates": candidate_scope_profiles,
                    "graphiti_provider": graphiti_clients["graphiti_provider"],
                    "graphiti_model": graphiti_clients["graphiti_model"],
                    "graphiti_cross_encoder": graphiti_clients["cross_encoder_name"],
                    "graphiti_cross_encoder_requested": args.cross_encoder,
                    "graphiti_embedder": graphiti_clients["embedder_name"],
                    "graphiti_embedder_requested": args.embedder,
                    "graphiti_embedding_model": graphiti_clients["embedding_model"],
                    "graphiti_raw_search_counts": graphiti_raw_search_counts,
                    "graphiti_search_config": search_payload.get("search_config"),
                    "graphiti_search_results": facts,
                    "graphiti_advanced_search_payload": search_payload,
                    "graphiti_scoped_episode_context": search_payload.get("scoped_episode_context", []),
                    "graphiti_public_readout_draft_output": draft_trace,
                    "graphiti_public_readout_verifier_output": verifier_trace,
                }
                row = evaluate_public_output(raw, hidden_case)
                if judge_client is not None:
                    print(f"judging {args.variant} / {case.case_id}", flush=True)
                    try:
                        row = attach_public_judge_score(judge_client, hidden_case, row)
                    except Exception as exc:
                        if not should_skip_judge_failures():
                            raise
                        provider_name = getattr(exc, "provider", judge_client.provider)
                        model_name = getattr(exc, "model", judge_client.model)
                        endpoint = getattr(exc, "endpoint", judge_client.api_base)
                        row.raw_output["judge_error"] = {
                            "provider": provider_name,
                            "model": model_name,
                            "endpoint": endpoint,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                        print(
                            f"warning: judge failed for {args.variant} / {case.case_id}; continuing because "
                            "JUDGE_FAILURE_POLICY=skip",
                            flush=True,
                        )
            else:
                search_payload, graphiti_raw_search_counts = await search_case(
                    graphiti,
                    case,
                    args.run_id,
                    args.search_limit,
                    args.search_pool_limit,
                    args.episode_fallback_limit,
                    episode_event_ids,
                    event_scopes,
                )
                facts = list(search_payload.get("facts", []))
                episode_context: List[Dict[str, object]] = []
                if args.variant == "graphiti_episode_context":
                    episode_context = episode_context_from_facts(facts, events_by_id, args.run_id)
                    raw = client.complete_json(
                        graphiti_episode_system_prompt(),
                        graphiti_episode_user_prompt(case, args.run_id, facts, episode_context),
                    )
                else:
                    draft_raw = client.complete_json(
                        graphiti_system_prompt(),
                        graphiti_user_prompt(case, args.run_id, search_payload, args.variant),
                    )
                    draft_trace = deepcopy(draft_raw)
                    if args.disable_readout_verifier:
                        raw = draft_raw
                        verifier_raw = None
                        verifier_trace = None
                    else:
                        verifier_raw = client.complete_json(
                            graphiti_readout_verifier_system_prompt(),
                            graphiti_readout_verifier_user_prompt(case, args.run_id, search_payload, draft_raw),
                        )
                        verifier_trace = deepcopy(verifier_raw)
                        raw = verifier_raw
                raw = normalize_graphiti_output_event_ids(raw, facts)
                raw["pipeline_trace"] = {
                    "variant": args.variant,
                    "graphiti_run_id": args.run_id,
                    "graphiti_provider": graphiti_clients["graphiti_provider"],
                    "graphiti_model": graphiti_clients["graphiti_model"],
                    "graphiti_cross_encoder": graphiti_clients["cross_encoder_name"],
                    "graphiti_cross_encoder_requested": args.cross_encoder,
                    "graphiti_embedder": graphiti_clients["embedder_name"],
                    "graphiti_embedder_requested": args.embedder,
                    "graphiti_embedding_model": graphiti_clients["embedding_model"],
                    "graphiti_raw_search_counts": graphiti_raw_search_counts,
                    "graphiti_search_config": search_payload.get("search_config"),
                    "graphiti_search_results": facts,
                    "graphiti_advanced_search_payload": search_payload,
                    "graphiti_scoped_episode_context": search_payload.get("scoped_episode_context", []),
                    "episode_context": episode_context,
                }
                if args.variant == "graphiti_zep" and not args.disable_readout_verifier:
                    raw["pipeline_trace"]["graphiti_readout_draft_output"] = draft_trace
                    raw["pipeline_trace"]["graphiti_readout_verifier_output"] = verifier_trace
                row = evaluate_output(raw, case)
                if judge_client is not None:
                    print(f"judging {args.variant} / {case.case_id}", flush=True)
                    try:
                        row = attach_judge_score(judge_client, case, row)
                    except Exception as exc:
                        if not should_skip_judge_failures():
                            raise
                        provider_name = getattr(exc, "provider", judge_client.provider)
                        model_name = getattr(exc, "model", judge_client.model)
                        endpoint = getattr(exc, "endpoint", judge_client.api_base)
                        row.raw_output["judge_error"] = {
                            "provider": provider_name,
                            "model": model_name,
                            "endpoint": endpoint,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                        print(
                            f"warning: judge failed for {args.variant} / {case.case_id}; continuing because "
                            "JUDGE_FAILURE_POLICY=skip",
                            flush=True,
                        )
            rows.append(row)
            time.sleep(0.2)
    except LLMRequestError as exc:
        print(f"LLM request failed: {exc}", file=sys.stderr)
        return 1
    except asyncio.TimeoutError:
        print(
            f"Graphiti ingest timed out after {args.ingest_timeout}s for one batch. "
            "Try a smaller --ingest-batch-size or check the Graphiti LLM/Neo4j endpoint.",
            file=sys.stderr,
        )
        return 1
    finally:
        await graphiti.close()

    if public_mode:
        public_rows = [row for row in rows if isinstance(row, PublicEvalRow)]
        result = summarize_public_rows(public_rows)
        result.update(
            {
                "variant": args.variant,
                "model_provider": args.provider,
                "model": model,
                "judge_provider": judge_client.provider if judge_client else None,
                "judge_model": judge_client.model if judge_client else None,
                "cases": [row.__dict__ for row in public_rows],
            }
        )
    else:
        oracle_rows = [row for row in rows if isinstance(row, EvalRow)]
        result = summarize_rows(oracle_rows, args.provider, model, judge_client, args.variant)
    result["graphiti_provider"] = graphiti_clients["graphiti_provider"]
    result["graphiti_model"] = graphiti_clients["graphiti_model"]
    result["graphiti_cross_encoder"] = graphiti_clients["cross_encoder_name"]
    result["graphiti_cross_encoder_requested"] = args.cross_encoder
    result["graphiti_embedder"] = graphiti_clients["embedder_name"]
    result["graphiti_embedder_requested"] = args.embedder
    result["graphiti_embedding_model"] = graphiti_clients["embedding_model"]
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps([result], ensure_ascii=False, indent=2))
    print(f"Wrote {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Graphiti/Zep baseline for STAMB-State.")
    parser.add_argument(
        "--variant",
        choices=("graphiti_zep", "graphiti_episode_context", *PUBLIC_GRAPHITI_VARIANTS),
        default="graphiti_zep",
        help=(
            "graphiti_zep uses native Graphiti returned facts only; "
            "graphiti_episode_context uses Graphiti search facts to recover full episode payloads "
            "before state extraction; graphiti_global_public and graphiti_scope_routed_public run "
            "public End-to-End free-facet readout."
        ),
    )
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument(
        "--graphiti-provider",
        choices=("openai", "deepseek"),
        default="openai",
        help="Provider used for Graphiti graph construction LLM calls.",
    )
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-events", type=int, default=0)
    parser.add_argument("--search-limit", type=int, default=8)
    parser.add_argument("--search-pool-limit", type=int, default=80)
    parser.add_argument(
        "--episode-fallback-limit",
        type=int,
        default=8,
        help=(
            "Number of Graphiti scoped episodic nodes to pass as fallback context after fact search. "
            "Set to 0 to disable the repaired adapter fallback."
        ),
    )
    parser.add_argument(
        "--disable-readout-verifier",
        action="store_true",
        help="Disable the repaired adapter's second-pass Graphiti readout verifier.",
    )
    parser.add_argument(
        "--embedder",
        choices=("auto", "openai", "bge"),
        default="auto",
        help="Graphiti embedder implementation. auto uses bge for gpt-5* or --graphiti-provider deepseek.",
    )
    parser.add_argument(
        "--cross-encoder",
        choices=("auto", "openai", "bge"),
        default="auto",
        help=(
            "Cross-encoder reranker implementation used by Graphiti advanced search. "
            "auto uses bge for gpt-5* models or --graphiti-provider deepseek because Graphiti's OpenAI reranker requires "
            "logprobs/logit_bias support."
        ),
    )
    parser.add_argument("--bge-embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--run-id", default=f"stamb-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    parser.add_argument("--reset-run", action="store_true")
    parser.add_argument("--reset-benchmark-data", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="Reset/build indices/ingest events, then write an ingest summary without running benchmark cases.",
    )
    parser.add_argument("--ingest-batch-size", type=int, default=8)
    parser.add_argument("--ingest-timeout", type=int, default=600)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--data-version", default="v1")
    parser.add_argument("--events", default=None)
    parser.add_argument("--cases", default=None)
    parser.add_argument("--public-cases", default=None)
    parser.add_argument("--gold-cases", default=None)
    parser.add_argument("--scope-profiles", default=None)
    parser.add_argument(
        "--scope-top-k",
        type=int,
        default=0,
        help="Number of public scope profiles to preselect before LLM routing; 0 passes all profiles.",
    )
    parser.add_argument("--output", default=str(BENCHMARK_DIR / "output/results_graphiti_zep.json"))
    parser.add_argument("--cache", default=str(BENCHMARK_DIR / "output/graphiti_llm_cache.json"))
    args = parser.parse_args()
    if args.ingest_batch_size < 1:
        parser.error("--ingest-batch-size must be >= 1")
    if args.ingest_timeout < 1:
        parser.error("--ingest-timeout must be >= 1")
    if args.limit_events < 0:
        parser.error("--limit-events must be >= 0")
    if args.scope_top_k < 0:
        parser.error("--scope-top-k must be >= 0")
    if args.episode_fallback_limit < 0:
        parser.error("--episode-fallback-limit must be >= 0")
    if args.search_pool_limit < args.search_limit:
        parser.error("--search-pool-limit must be >= --search-limit")
    if args.reset_run and args.reset_benchmark_data:
        parser.error("--reset-run and --reset-benchmark-data are mutually exclusive")
    return args


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

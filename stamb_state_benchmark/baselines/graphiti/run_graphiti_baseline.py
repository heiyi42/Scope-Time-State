from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Sequence


GRAPHITI_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = GRAPHITI_DIR.parents[1]
PROJECT_DIR = BENCHMARK_DIR.parent
sys.path.insert(0, str(BENCHMARK_DIR))

from run_llm_benchmark import (  # noqa: E402
    EvalRow,
    LLMClient,
    LLMRequestError,
    attach_judge_score,
    evaluate_output,
    load_cases,
    load_dotenv,
    load_events,
    provider_config,
    validate_benchmark,
)


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
        "status": event.status,
        "corrects": list(event.corrects),
        "supersedes": list(event.supersedes),
        "state_relevant": event.state_relevant,
    }


def parse_reference_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def graphiti_system_prompt() -> str:
    return (
        "你是 Graphiti/Zep baseline 的状态抽取器。"
        "你只能基于 Graphiti search 返回的 facts 作答。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}, '
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "evidence_events、support_event、support_events 必须使用 facts 里的 event_ids，"
        "不能使用 graphiti_fact_uuid、source_node_uuid 或 target_node_uuid。"
        "如果 facts 没有明确给出 event_ids，不要编造。"
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
    facts: Sequence[Dict[str, object]],
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
        "graphiti_search_results": list(facts),
        "task": (
            "根据 Graphiti search results 填写 current valid state slots、support_events 和 answer。"
            "不要使用未出现在 search results 中的信息。"
        ),
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


def graphiti_fact_view(result: object, episode_event_ids: Dict[str, str]) -> Dict[str, object]:
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
    }
    return data


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
        WITH collect(DISTINCT ep.uuid) AS episode_ids
        OPTIONAL MATCH (mentioned_ep:Episodic)-[:MENTIONS]->(mentioned:Entity)
        WHERE mentioned_ep.uuid IN episode_ids
        WITH episode_ids, [entity_id IN collect(DISTINCT mentioned.uuid) WHERE entity_id IS NOT NULL] AS entity_ids
        OPTIONAL MATCH ()-[rel:RELATES_TO]->()
        WHERE any(episode_id IN coalesce(rel.episodes, []) WHERE episode_id IN episode_ids)
        WITH
            episode_ids,
            entity_ids,
            [rel_item IN collect(DISTINCT rel) WHERE rel_item IS NOT NULL] AS relates_to_edges
        WITH episode_ids, entity_ids, relates_to_edges, size(relates_to_edges) AS deleted_relates_to
        FOREACH (rel_item IN relates_to_edges | DELETE rel_item)
        WITH episode_ids, entity_ids, deleted_relates_to
        MATCH (ep:Episodic)
        WHERE ep.uuid IN episode_ids
        WITH episode_ids, entity_ids, deleted_relates_to, collect(DISTINCT ep) AS episodes_to_delete
        FOREACH (ep_item IN episodes_to_delete | DETACH DELETE ep_item)
        WITH episode_ids, entity_ids, deleted_relates_to
        OPTIONAL MATCH (entity:Entity)
        WHERE entity.uuid IN entity_ids AND NOT (entity)--()
        WITH
            size(episode_ids) AS deleted_episodes,
            size(entity_ids) AS touched_entities,
            deleted_relates_to,
            [entity_item IN collect(DISTINCT entity) WHERE entity_item IS NOT NULL] AS orphan_entities
        FOREACH (entity_item IN orphan_entities | DELETE entity_item)
        RETURN
            deleted_episodes,
            touched_entities,
            deleted_relates_to,
            size(orphan_entities) AS deleted_orphan_entities
    """
    result = await graphiti.driver.execute_query(query, params=params)
    row = result.records[0] if result.records else {}
    return {
        "deleted_episodes": int(row.get("deleted_episodes", 0)),
        "touched_entities": int(row.get("touched_entities", 0)),
        "deleted_relates_to": int(row.get("deleted_relates_to", 0)),
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
    if not isinstance(state_slots, dict):
        return raw
    for slot_data in state_slots.values():
        if not isinstance(slot_data, dict):
            continue
        support_values = slot_data.get("support_events")
        if not support_values and slot_data.get("support_event"):
            support_values = [slot_data.get("support_event")]
        support_events = normalize_ids(support_values)
        slot_data["support_events"] = support_events
        slot_data["support_event"] = support_events[0] if support_events else None
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


async def search_case(
    graphiti: object,
    case: object,
    run_id: str,
    limit: int,
    pool_limit: int,
    episode_event_ids: Dict[str, str],
    event_scopes: Dict[str, str],
) -> tuple[List[Dict[str, object]], int]:
    query = (
        f"benchmark_run_id={run_id}; scope_id={case.scope_id}; "
        f"question={case.query}; output_slots={', '.join(case.output_slots)}"
    )
    results = await graphiti.search(query, num_results=pool_limit)
    facts = [graphiti_fact_view(result, episode_event_ids) for result in list(results)]
    return filter_facts_to_scope(facts, case.scope_id, event_scopes, limit), len(facts)


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


def build_graphiti_clients() -> Dict[str, object]:
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

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
    embedder_config = OpenAIEmbedderConfig(
        api_key=embedding_api_key,
        base_url=embedding_base_url,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
    )
    return {
        "llm_client": OpenAIGenericClient(config=llm_config, max_tokens=8192),
        "embedder": OpenAIEmbedder(config=embedder_config),
        "cross_encoder": OpenAIRerankerClient(config=llm_config),
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
    try:
        from graphiti_core import Graphiti
    except ModuleNotFoundError:
        print("Missing dependency: graphiti_core. Install with: pip install graphiti-core", file=sys.stderr)
        return 2

    load_dotenv()
    configure_openai_env_for_graphiti()
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

    events = load_events(Path(args.events))
    cases = load_cases(Path(args.cases))
    validate_benchmark(events, cases)
    if args.limit_events:
        events = events[: args.limit_events]
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    try:
        validate_limited_events_cover_cases(events, cases)
    except RuntimeError as exc:
        print(f"Benchmark subset error: {exc}", file=sys.stderr)
        return 2
    event_scopes = {event.event_id: event.scope_id for event in events}
    events_by_id = {event.event_id: event for event in events}

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
        graphiti_clients = build_graphiti_clients()
    except RuntimeError as exc:
        print(f"Graphiti config error: {exc}", file=sys.stderr)
        return 2

    graphiti = Graphiti(
        graph_driver=build_graphiti_driver(neo4j_uri, neo4j_user, neo4j_password),
        llm_client=graphiti_clients["llm_client"],
        embedder=graphiti_clients["embedder"],
        cross_encoder=graphiti_clients["cross_encoder"],
    )
    rows: List[EvalRow] = []
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
        for case in cases:
            print(f"running {args.variant} / {case.case_id}", flush=True)
            facts, graphiti_raw_search_count = await search_case(
                graphiti,
                case,
                args.run_id,
                args.search_limit,
                args.search_pool_limit,
                episode_event_ids,
                event_scopes,
            )
            episode_context: List[Dict[str, object]] = []
            if args.variant == "graphiti_episode_context":
                episode_context = episode_context_from_facts(facts, events_by_id, args.run_id)
                raw = client.complete_json(
                    graphiti_episode_system_prompt(),
                    graphiti_episode_user_prompt(case, args.run_id, facts, episode_context),
                )
            else:
                raw = client.complete_json(
                    graphiti_system_prompt(),
                    graphiti_user_prompt(case, args.run_id, facts, args.variant),
                )
            raw = normalize_graphiti_output_event_ids(raw, facts)
            raw["pipeline_trace"] = {
                "variant": args.variant,
                "graphiti_run_id": args.run_id,
                "graphiti_raw_search_count": graphiti_raw_search_count,
                "graphiti_search_results": facts,
                "episode_context": episode_context,
            }
            row = evaluate_output(raw, case)
            if judge_client is not None:
                print(f"judging {args.variant} / {case.case_id}", flush=True)
                row = attach_judge_score(judge_client, case, row)
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

    result = summarize_rows(rows, args.provider, model, judge_client, args.variant)
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps([result], ensure_ascii=False, indent=2))
    print(f"Wrote {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Graphiti/Zep baseline for STAMB-State.")
    parser.add_argument(
        "--variant",
        choices=("graphiti_zep", "graphiti_episode_context"),
        default="graphiti_zep",
        help=(
            "graphiti_zep uses native Graphiti returned facts only; "
            "graphiti_episode_context uses Graphiti search facts to recover full episode payloads "
            "before state extraction."
        ),
    )
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-events", type=int, default=0)
    parser.add_argument("--search-limit", type=int, default=8)
    parser.add_argument("--search-pool-limit", type=int, default=80)
    parser.add_argument("--run-id", default=f"stamb-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    parser.add_argument("--reset-run", action="store_true")
    parser.add_argument("--reset-benchmark-data", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--ingest-batch-size", type=int, default=8)
    parser.add_argument("--ingest-timeout", type=int, default=600)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--events", default=str(BENCHMARK_DIR / "data/events.json"))
    parser.add_argument("--cases", default=str(BENCHMARK_DIR / "data/cases.json"))
    parser.add_argument("--output", default=str(BENCHMARK_DIR / "output/results_graphiti_zep.json"))
    parser.add_argument("--cache", default=str(BENCHMARK_DIR / "output/graphiti_llm_cache.json"))
    args = parser.parse_args()
    if args.ingest_batch_size < 1:
        parser.error("--ingest-batch-size must be >= 1")
    if args.ingest_timeout < 1:
        parser.error("--ingest-timeout must be >= 1")
    if args.limit_events < 0:
        parser.error("--limit-events must be >= 0")
    if args.search_pool_limit < args.search_limit:
        parser.error("--search-pool-limit must be >= --search-limit")
    if args.reset_run and args.reset_benchmark_data:
        parser.error("--reset-run and --reset-benchmark-data are mutually exclusive")
    return args


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

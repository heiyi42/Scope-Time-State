from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence


GRAPHITI_PAPER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = GRAPHITI_PAPER_DIR.parents[2]
BENCHMARK_DIR = PROJECT_DIR / "stamb_state_benchmark"
V1_DATA_DIR = BENCHMARK_DIR / "data" / "v1"
DEFAULT_EVENTS_PATH = V1_DATA_DIR / "events_raw.json"
DEFAULT_CASES_PATH = V1_DATA_DIR / "cases.json"
DEFAULT_VARIANT = "graphiti_paper_reproduction"
DEFAULT_GROUP_PREFIX = "stamb_graphiti_paper"
sys.path.insert(0, str(PROJECT_DIR))

from graphiti_core.embedder.client import EmbedderClient  # noqa: E402

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
    validate_benchmark,
)


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


def parse_reference_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def graphiti_group_id(run_id: str, scope_id: str, group_prefix: str) -> str:
    return f"{group_prefix}_{run_id}_{scope_id}"


def graphiti_run_prefix(run_id: str, group_prefix: str) -> str:
    return f"{group_prefix}_{run_id}_"


def event_message_body(event: object) -> str:
    lines = [
        f"{event.scope_id}: {event.content}",
        f"Event type: {event.event_type}",
        f"Occurred at: {event.occurred_at}",
        f"Mentioned at: {event.mentioned_at}",
        f"Updated at: {event.updated_at}",
    ]
    if event.planned_for:
        lines.append(f"Planned for: {event.planned_for}")
    if getattr(event, "deadline_at", None):
        lines.append(f"Deadline at: {event.deadline_at}")
    if getattr(event, "source_id", None):
        lines.append(f"Source: {event.source_id}")
    metadata = getattr(event, "metadata", None)
    if metadata:
        lines.append(f"Metadata: {json.dumps(metadata, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(lines)


def event_source_description(event: object, run_id: str) -> str:
    return (
        "STAMB-State Graphiti paper reproduction "
        f"run_id={run_id} scope_id={event.scope_id} event_id={event.event_id}"
    )


def extract_event_id_from_source_description(source_description: str) -> Optional[str]:
    match = re.search(r"(?:^|\s)event_id=([^\s]+)", source_description)
    return match.group(1) if match else None


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


def build_graphiti_clients(args: argparse.Namespace) -> Dict[str, object]:
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

    api_key = env_first("GRAPHITI_OPENAI_API_KEY", "OPENAI_API_KEY")
    base_url = env_first("GRAPHITI_OPENAI_BASE_URL", "GRAPHITI_OPENAI_API_BASE", "OPENAI_BASE_URL", "OPENAI_API_BASE")
    model = env_first("GRAPHITI_CONSTRUCTION_MODEL", "OPENAI_MODEL")
    if not api_key:
        raise RuntimeError("missing GRAPHITI_OPENAI_API_KEY or OPENAI_API_KEY for Graphiti construction")
    if not model:
        raise RuntimeError("missing GRAPHITI_CONSTRUCTION_MODEL or OPENAI_MODEL for Graphiti construction")

    llm_config = LLMConfig(api_key=api_key, model=model, small_model=model, base_url=base_url, temperature=0)
    clients: Dict[str, object] = {
        "llm_client": OpenAIGenericClient(config=llm_config, max_tokens=args.graphiti_max_tokens),
        "graph_construction_model": model,
    }

    if args.embedder == "bge":
        clients["embedder"] = SentenceTransformerEmbedder(args.bge_embedding_model, args.embedding_dim)
        clients["embedding_model"] = args.bge_embedding_model
    else:
        embedding_api_key = env_first("OPENAI_EMBEDDING_API_KEY", "OPENAI_API_KEY")
        embedding_base_url = env_first(
            "OPENAI_EMBEDDING_BASE_URL",
            "OPENAI_EMBEDDING_API_BASE",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
        )
        embedding_model = env_first("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
        if not embedding_api_key:
            raise RuntimeError("missing OPENAI_EMBEDDING_API_KEY or OPENAI_API_KEY for OpenAI embeddings")
        embedder_config = OpenAIEmbedderConfig(
            api_key=embedding_api_key,
            base_url=embedding_base_url,
            embedding_model=embedding_model,
            embedding_dim=args.embedding_dim,
        )
        clients["embedder"] = OpenAIEmbedder(config=embedder_config)
        clients["embedding_model"] = embedding_model

    if args.cross_encoder == "bge":
        try:
            from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for --cross-encoder bge. "
                "Install with: pip install 'graphiti-core[sentence-transformers]' sentence-transformers"
            ) from exc
        clients["cross_encoder"] = BGERerankerClient()
        clients["reranker_model"] = "BAAI/bge-reranker-v2-m3"
    else:
        clients["cross_encoder"] = OpenAIRerankerClient(config=llm_config)
        clients["reranker_model"] = model
    return clients


def build_graphiti_driver(uri: str, user: str, password: str) -> object:
    from graphiti_core.driver.neo4j_driver import Neo4jDriver

    database = os.environ.get("NEO4J_DATABASE") or "neo4j"
    return Neo4jDriver(uri=uri, user=user, password=password, database=database)


def build_search_config(args: argparse.Namespace) -> object:
    from graphiti_core.search.search_config import (
        CommunityReranker,
        CommunitySearchConfig,
        CommunitySearchMethod,
        EdgeReranker,
        EdgeSearchConfig,
        EdgeSearchMethod,
        NodeReranker,
        NodeSearchConfig,
        NodeSearchMethod,
        SearchConfig,
    )

    edge_config = EdgeSearchConfig(
        search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity, EdgeSearchMethod.bfs],
        reranker=EdgeReranker(args.edge_reranker),
        sim_min_score=args.sim_min_score,
        mmr_lambda=args.mmr_lambda,
        bfs_max_depth=args.bfs_max_depth,
    )
    node_config = NodeSearchConfig(
        search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity, NodeSearchMethod.bfs],
        reranker=NodeReranker(args.node_reranker),
        sim_min_score=args.sim_min_score,
        mmr_lambda=args.mmr_lambda,
        bfs_max_depth=args.bfs_max_depth,
    )
    community_config = CommunitySearchConfig(
        search_methods=[CommunitySearchMethod.bm25, CommunitySearchMethod.cosine_similarity],
        reranker=CommunityReranker(args.community_reranker),
        sim_min_score=args.sim_min_score,
        mmr_lambda=args.mmr_lambda,
        bfs_max_depth=args.bfs_max_depth,
    )
    return SearchConfig(
        edge_config=edge_config,
        node_config=node_config,
        community_config=community_config,
        limit=args.search_limit,
        reranker_min_score=args.reranker_min_score,
    )


def search_config_audit(args: argparse.Namespace) -> Dict[str, object]:
    return {
        "edge_search_methods": ["bm25", "cosine_similarity", "breadth_first_search"],
        "node_search_methods": ["bm25", "cosine_similarity", "breadth_first_search"],
        "community_search_methods": ["bm25", "cosine_similarity"],
        "edge_reranker": args.edge_reranker,
        "node_reranker": args.node_reranker,
        "community_reranker": args.community_reranker,
        "search_limit": args.search_limit,
        "sim_min_score": args.sim_min_score,
        "mmr_lambda": args.mmr_lambda,
        "bfs_max_depth": args.bfs_max_depth,
        "bfs_origin_limit": args.bfs_origin_limit,
    }


async def reset_graphiti_paper_data(
    graphiti: object,
    *,
    run_id: Optional[str],
    group_prefix: str,
) -> Dict[str, int]:
    if run_id:
        prefix = graphiti_run_prefix(run_id, group_prefix)
    else:
        prefix = f"{group_prefix}:"
    query = """
        MATCH (n)
        WHERE n.group_id STARTS WITH $prefix
        WITH collect(DISTINCT n) AS nodes
        FOREACH (node IN nodes | DETACH DELETE node)
        RETURN size(nodes) AS deleted_nodes
    """
    result = await graphiti.driver.execute_query(query, params={"prefix": prefix})
    row = result.records[0] if result.records else {}
    return {"deleted_nodes": int(row.get("deleted_nodes", 0))}


async def load_episode_event_ids(graphiti: object, run_id: str, group_prefix: str) -> Dict[str, str]:
    query = """
        MATCH (ep:Episodic)
        WHERE ep.group_id STARTS WITH $prefix
          AND ep.source_description STARTS WITH 'STAMB-State Graphiti paper reproduction'
        RETURN ep.uuid AS uuid, ep.source_description AS source_description
    """
    result = await graphiti.driver.execute_query(
        query,
        params={"prefix": graphiti_run_prefix(run_id, group_prefix)},
    )
    episode_event_ids: Dict[str, str] = {}
    for row in result.records:
        event_id = extract_event_id_from_source_description(str(row.get("source_description", "")))
        if event_id:
            episode_event_ids[str(row["uuid"])] = event_id
    return episode_event_ids


async def graph_count_audit(graphiti: object, run_id: str, group_prefix: str) -> Dict[str, int]:
    prefix = graphiti_run_prefix(run_id, group_prefix)
    queries = {
        "episodes": "MATCH (n:Episodic) WHERE n.group_id STARTS WITH $prefix RETURN count(n) AS value",
        "entities": "MATCH (n:Entity) WHERE n.group_id STARTS WITH $prefix RETURN count(n) AS value",
        "communities": "MATCH (n:Community) WHERE n.group_id STARTS WITH $prefix RETURN count(n) AS value",
        "semantic_edges": "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id STARTS WITH $prefix RETURN count(r) AS value",
        "episode_entity_edges": """
            MATCH (ep:Episodic)-[r:MENTIONS]->(:Entity)
            WHERE ep.group_id STARTS WITH $prefix
            RETURN count(r) AS value
        """,
        "community_edges": """
            MATCH (c:Community)-[r:HAS_MEMBER]->(:Entity)
            WHERE c.group_id STARTS WITH $prefix
            RETURN count(r) AS value
        """,
        "semantic_edges_with_valid_at": """
            MATCH ()-[r:RELATES_TO]->()
            WHERE r.group_id STARTS WITH $prefix AND r.valid_at IS NOT NULL
            RETURN count(r) AS value
        """,
        "semantic_edges_with_invalid_at": """
            MATCH ()-[r:RELATES_TO]->()
            WHERE r.group_id STARTS WITH $prefix AND r.invalid_at IS NOT NULL
            RETURN count(r) AS value
        """,
        "semantic_edges_with_expired_at": """
            MATCH ()-[r:RELATES_TO]->()
            WHERE r.group_id STARTS WITH $prefix AND r.expired_at IS NOT NULL
            RETURN count(r) AS value
        """,
    }
    counts: Dict[str, int] = {}
    for name, query in queries.items():
        result = await graphiti.driver.execute_query(query, params={"prefix": prefix})
        row = result.records[0] if result.records else {}
        counts[name] = int(row.get("value", 0))
    return counts


async def recent_bfs_origin_nodes(
    graphiti: object,
    group_id: str,
    limit: int,
) -> List[str]:
    if limit <= 0:
        return []
    query = """
        MATCH (ep:Episodic)-[:MENTIONS]->(entity:Entity)
        WHERE ep.group_id = $group_id
        WITH entity.uuid AS uuid, max(ep.valid_at) AS last_seen
        RETURN uuid
        ORDER BY last_seen DESC
        LIMIT $limit
    """
    result = await graphiti.driver.execute_query(
        query,
        params={"group_id": group_id, "limit": limit},
    )
    return [str(row["uuid"]) for row in result.records if row.get("uuid")]


async def ingest_events_sequentially(
    graphiti: object,
    events: Sequence[object],
    args: argparse.Namespace,
) -> List[Dict[str, object]]:
    from graphiti_core.nodes import EpisodeType

    ordered_events = sorted(
        events,
        key=lambda event: (event.scope_id, parse_reference_time(event.updated_at), event.event_id),
    )
    recent_episodes_by_scope: Dict[str, List[str]] = defaultdict(list)
    audits: List[Dict[str, object]] = []
    for index, event in enumerate(ordered_events, start=1):
        previous_episode_uuids = recent_episodes_by_scope[event.scope_id][-args.previous_message_window :]
        group_id = graphiti_group_id(args.run_id, event.scope_id, args.group_prefix)
        print(
            f"ingesting paper Graphiti episode {index}/{len(ordered_events)} "
            f"scope={event.scope_id} event_id={event.event_id}",
            flush=True,
        )
        result = await asyncio.wait_for(
            graphiti.add_episode(
                name=f"stamb-paper-{args.run_id}-{event.event_id}",
                episode_body=event_message_body(event),
                source_description=event_source_description(event, args.run_id),
                reference_time=parse_reference_time(event.updated_at),
                source=EpisodeType.message,
                group_id=group_id,
                previous_episode_uuids=previous_episode_uuids,
                update_communities=args.update_communities,
            ),
            timeout=args.ingest_timeout,
        )
        episode_uuid = str(result.episode.uuid)
        recent_episodes_by_scope[event.scope_id].append(episode_uuid)
        audits.append(
            {
                "event_id": event.event_id,
                "scope_id": event.scope_id,
                "episode_uuid": episode_uuid,
                "group_id": group_id,
                "reference_time": event.updated_at,
                "previous_episode_uuids": previous_episode_uuids,
                "extracted_node_count": len(result.nodes),
                "extracted_edge_count": len(result.edges),
                "community_count": len(result.communities),
                "community_edge_count": len(result.community_edges),
            }
        )
    return audits


async def build_run_communities(
    graphiti: object,
    events: Sequence[object],
    args: argparse.Namespace,
) -> Dict[str, object]:
    from graphiti_core.helpers import semaphore_gather
    from graphiti_core.utils.maintenance.community_operations import (
        build_community,
    )

    group_ids = sorted(
        {graphiti_group_id(args.run_id, event.scope_id, args.group_prefix) for event in events}
    )
    if not group_ids:
        return {
            "enabled": True,
            "status": "ok",
            "requested_group_ids": [],
            "attempted_group_ids": [],
            "community_count": 0,
            "community_edge_count": 0,
            "groups": [],
        }

    attempted_group_ids = group_ids
    if args.community_build_scope_limit:
        attempted_group_ids = group_ids[: args.community_build_scope_limit]

    def connected_components(projection: Dict[str, List[tuple[str, int]]]) -> List[List[str]]:
        remaining = set(projection)
        components: List[List[str]] = []
        while remaining:
            start = remaining.pop()
            stack = [start]
            component = [start]
            while stack:
                node_uuid = stack.pop()
                for neighbor_uuid, _edge_count in projection.get(node_uuid, []):
                    if neighbor_uuid in remaining:
                        remaining.remove(neighbor_uuid)
                        stack.append(neighbor_uuid)
                        component.append(neighbor_uuid)
            components.append(component)
        return components

    def bounded_label_propagation(projection: Dict[str, List[tuple[str, int]]]) -> List[List[str]]:
        community_map = {uuid: index for index, uuid in enumerate(projection)}
        seen_states = set()
        for _iteration in range(args.community_label_max_iterations):
            state = tuple(sorted(community_map.items()))
            if state in seen_states:
                return connected_components(projection)
            seen_states.add(state)
            no_change = True
            new_community_map: Dict[str, int] = {}
            for uuid, neighbors in projection.items():
                current_community = community_map[uuid]
                community_candidates: Dict[int, int] = defaultdict(int)
                for neighbor_uuid, edge_count in neighbors:
                    community_candidates[community_map[neighbor_uuid]] += edge_count
                ranked_candidates = sorted(
                    [(count, community) for community, count in community_candidates.items()],
                    reverse=True,
                )
                candidate_rank, candidate_community = (
                    ranked_candidates[0] if ranked_candidates else (0, -1)
                )
                if candidate_community != -1 and candidate_rank > 1:
                    new_community = candidate_community
                else:
                    new_community = max(candidate_community, current_community)
                new_community_map[uuid] = new_community
                if new_community != current_community:
                    no_change = False
            community_map = new_community_map
            if no_change:
                cluster_map: Dict[int, List[str]] = defaultdict(list)
                for uuid, community in community_map.items():
                    cluster_map[community].append(uuid)
                return list(cluster_map.values())
        return connected_components(projection)

    async def bounded_community_clusters(group_id: str) -> List[List[object]]:
        from graphiti_core.nodes import EntityNode

        nodes = await EntityNode.get_by_group_ids(graphiti.driver, [group_id])
        if not nodes:
            return []
        projection: Dict[str, List[tuple[str, int]]] = {str(node.uuid): [] for node in nodes}
        result = await graphiti.driver.execute_query(
            """
            MATCH (n:Entity {group_id: $group_id})-[e:RELATES_TO]-(m:Entity {group_id: $group_id})
            RETURN n.uuid AS source_uuid, m.uuid AS target_uuid, count(e) AS edge_count
            """,
            params={"group_id": group_id},
        )
        for row in result.records:
            source_uuid = str(row["source_uuid"])
            target_uuid = str(row["target_uuid"])
            edge_count = int(row.get("edge_count", 1))
            if source_uuid == target_uuid:
                continue
            projection.setdefault(source_uuid, []).append((target_uuid, edge_count))
            projection.setdefault(target_uuid, []).append((source_uuid, edge_count))
        node_by_uuid = {str(node.uuid): node for node in nodes}
        clusters = []
        for cluster in bounded_label_propagation(projection):
            hydrated_cluster = [node_by_uuid[uuid] for uuid in cluster if uuid in node_by_uuid]
            if hydrated_cluster:
                clusters.append(hydrated_cluster)
        return clusters

    async def build_one_group(group_id: str) -> Dict[str, object]:
        async def build_and_save() -> Dict[str, object]:
            community_clusters = await bounded_community_clusters(group_id)
            built_communities = (
                await semaphore_gather(
                    *[build_community(graphiti.llm_client, cluster) for cluster in community_clusters],
                    max_coroutines=graphiti.max_coroutines,
                )
                if community_clusters
                else []
            )
            communities = [community for community, _edges in built_communities]
            community_edges = [
                edge
                for _community, edges in built_communities
                for edge in edges
            ]
            if communities:
                await semaphore_gather(
                    *[community.generate_name_embedding(graphiti.embedder) for community in communities],
                    max_coroutines=graphiti.max_coroutines,
                )
                await semaphore_gather(
                    *[community.save(graphiti.driver) for community in communities],
                    max_coroutines=graphiti.max_coroutines,
                )
            if community_edges:
                await semaphore_gather(
                    *[edge.save(graphiti.driver) for edge in community_edges],
                    max_coroutines=graphiti.max_coroutines,
                )
            return {
                "group_id": group_id,
                "status": "ok",
                "cluster_count": len(community_clusters),
                "community_count": len(communities),
                "community_edge_count": len(community_edges),
            }

        try:
            return await asyncio.wait_for(build_and_save(), timeout=args.community_build_timeout)
        except asyncio.TimeoutError:
            return {
                "group_id": group_id,
                "status": "timed_out",
                "timeout_seconds": args.community_build_timeout,
                "cluster_count": 0,
                "community_count": 0,
                "community_edge_count": 0,
            }
        except Exception as exc:
            return {
                "group_id": group_id,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "cluster_count": 0,
                "community_count": 0,
                "community_edge_count": 0,
            }

    group_audits: List[Dict[str, object]] = []
    for index, group_id in enumerate(attempted_group_ids, start=1):
        print(
            f"building Graphiti paper communities group {index}/{len(attempted_group_ids)} "
            f"group_id={group_id}",
            flush=True,
        )
        group_audits.append(await build_one_group(group_id))

    statuses = {str(group["status"]) for group in group_audits}
    if statuses == {"ok"}:
        status = "ok"
    elif "ok" in statuses:
        status = "partial"
    else:
        status = "failed_or_timed_out"
    return {
        "enabled": True,
        "status": status,
        "requested_group_ids": group_ids,
        "attempted_group_ids": attempted_group_ids,
        "skipped_group_count": len(group_ids) - len(attempted_group_ids),
        "timeout_seconds": args.community_build_timeout,
        "label_max_iterations": args.community_label_max_iterations,
        "cluster_count": sum(int(group.get("cluster_count", 0)) for group in group_audits),
        "community_count": sum(int(group.get("community_count", 0)) for group in group_audits),
        "community_edge_count": sum(int(group.get("community_edge_count", 0)) for group in group_audits),
        "groups": group_audits,
    }


def edge_view(edge: object, episode_event_ids: Dict[str, str], score: Optional[float]) -> Dict[str, object]:
    episode_uuids = [str(item) for item in (getattr(edge, "episodes", None) or [])]
    event_ids: List[str] = []
    for episode_uuid in episode_uuids:
        event_id = episode_event_ids.get(episode_uuid)
        if event_id and event_id not in event_ids:
            event_ids.append(event_id)
    return {
        "graphiti_edge_uuid": getattr(edge, "uuid", None),
        "event_ids": event_ids,
        "fact": getattr(edge, "fact", str(edge)),
        "relation_type": getattr(edge, "name", None),
        "valid_at": str(getattr(edge, "valid_at", "")) if getattr(edge, "valid_at", None) else None,
        "invalid_at": str(getattr(edge, "invalid_at", "")) if getattr(edge, "invalid_at", None) else None,
        "created_at": str(getattr(edge, "created_at", "")) if getattr(edge, "created_at", None) else None,
        "expired_at": str(getattr(edge, "expired_at", "")) if getattr(edge, "expired_at", None) else None,
        "source_node_uuid": getattr(edge, "source_node_uuid", None),
        "target_node_uuid": getattr(edge, "target_node_uuid", None),
        "score": score,
    }


def node_view(node: object, score: Optional[float]) -> Dict[str, object]:
    return {
        "graphiti_node_uuid": getattr(node, "uuid", None),
        "name": getattr(node, "name", None),
        "summary": getattr(node, "summary", None),
        "labels": list(getattr(node, "labels", []) or []),
        "score": score,
    }


def community_view(community: object, score: Optional[float]) -> Dict[str, object]:
    return {
        "graphiti_community_uuid": getattr(community, "uuid", None),
        "name": getattr(community, "name", None),
        "summary": getattr(community, "summary", None),
        "labels": list(getattr(community, "labels", []) or []),
        "score": score,
    }


def score_at(scores: Sequence[float], index: int) -> Optional[float]:
    if index >= len(scores):
        return None
    return float(scores[index])


def construct_paper_context(
    facts: Sequence[Dict[str, object]],
    entities: Sequence[Dict[str, object]],
    communities: Sequence[Dict[str, object]],
) -> str:
    fact_lines = []
    for item in facts:
        date_range = f"{item.get('valid_at') or 'unknown'} - {item.get('invalid_at') or 'present'}"
        event_ids = ", ".join(str(event_id) for event_id in item.get("event_ids", []))
        fact_lines.append(f"- {item.get('fact')} (Date range: {date_range}; event_ids: {event_ids})")
    entity_lines = [f"- {item.get('name')}: {item.get('summary')}" for item in entities]
    community_lines = [f"- {item.get('name')}: {item.get('summary')}" for item in communities]
    return "\n".join(
        [
            "FACTS and ENTITIES represent relevant context to the current conversation.",
            "These are the most relevant facts and their valid date ranges.",
            "<FACTS>",
            "\n".join(fact_lines),
            "</FACTS>",
            "These are the most relevant entities.",
            "<ENTITIES>",
            "\n".join(entity_lines),
            "</ENTITIES>",
            "These are the most relevant communities.",
            "<COMMUNITIES>",
            "\n".join(community_lines),
            "</COMMUNITIES>",
        ]
    )


async def search_case(
    graphiti: object,
    case: object,
    args: argparse.Namespace,
    search_config: object,
    episode_event_ids: Dict[str, str],
) -> Dict[str, object]:
    group_id = graphiti_group_id(args.run_id, case.scope_id, args.group_prefix)
    bfs_origins = await recent_bfs_origin_nodes(graphiti, group_id, args.bfs_origin_limit)
    results = await graphiti.search_(
        query=case.query,
        config=search_config,
        group_ids=[group_id],
        bfs_origin_node_uuids=bfs_origins,
    )
    facts = [
        edge_view(edge, episode_event_ids, score_at(results.edge_reranker_scores, index))
        for index, edge in enumerate(results.edges)
    ]
    entities = [
        node_view(node, score_at(results.node_reranker_scores, index))
        for index, node in enumerate(results.nodes)
    ]
    communities = [
        community_view(community, score_at(results.community_reranker_scores, index))
        for index, community in enumerate(results.communities)
    ]
    return {
        "group_id": group_id,
        "query": case.query,
        "bfs_origin_node_uuids": bfs_origins,
        "facts": facts,
        "entities": entities,
        "communities": communities,
        "paper_context": construct_paper_context(facts, entities, communities),
        "returned_counts": {
            "facts": len(facts),
            "entities": len(entities),
            "communities": len(communities),
            "episodes": len(results.episodes),
        },
    }


def graphiti_paper_system_prompt() -> str:
    return (
        "你是 Graphiti/Zep paper reproduction baseline 的状态抽取器。"
        "你只能基于用户给出的 Graphiti paper context 作答；context 由 facts、entity summaries 和 community summaries 构成。"
        "输出必须是合法 JSON，不能包含 Markdown。"
        "JSON schema: {"
        '"evidence_events": ["event_id"], '
        '"state_slots": {"slot_name": {"value": "string", "support_event": "event_id or null", "support_events": ["event_id"]}}, '
        '"coverage_check": {"slot_name": true or false}, '
        '"answer": "string"'
        "}。"
        "evidence_events、support_event、support_events 必须使用 FACTS 中列出的 event_ids。"
        "如果 facts 没有明确给出 event_ids，不要编造。"
        "state_slots 只能包含用户要求的 output_slots。answer 必须覆盖所有 output_slots。"
    )


def graphiti_paper_user_prompt(case: object, search_payload: Dict[str, object]) -> str:
    payload = {
        "variant": DEFAULT_VARIANT,
        "query": case.query,
        "scope_id": case.scope_id,
        "operation": case.operation,
        "time_role": case.time_role,
        "time_roles": list(case.time_roles),
        "output_slots": list(case.output_slots),
        "paper_context": search_payload["paper_context"],
        "structured_facts": search_payload["facts"],
        "structured_entities": search_payload["entities"],
        "structured_communities": search_payload["communities"],
        "task": (
            "根据 Graphiti paper context 填写 current valid state slots、support_events 和 answer。"
            "不要使用未出现在 context 中的信息。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_graphiti_output_event_ids(
    raw: Dict[str, object],
    facts: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    replacements: Dict[str, List[str]] = {}
    for fact in facts:
        event_ids = [str(event_id) for event_id in fact.get("event_ids", []) if event_id]
        fact_uuid = fact.get("graphiti_edge_uuid")
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


def conformance_audit(
    args: argparse.Namespace,
    graphiti_clients: Dict[str, object],
    graph_counts: Dict[str, int],
) -> Dict[str, object]:
    return {
        "paper": "Zep: A Temporal Knowledge Graph Architecture for Agent Memory, arXiv:2501.13956v1",
        "graph_construction": {
            "episode_source": "message",
            "previous_message_window": args.previous_message_window,
            "expected_previous_message_window": 4,
            "uses_reference_time": True,
            "uses_group_id_per_scope": True,
            "updates_communities_during_ingest": args.update_communities,
            "builds_communities_after_ingest": not args.skip_build_communities,
            "community_build_timeout_seconds": args.community_build_timeout,
            "community_build_scope_limit": args.community_build_scope_limit,
            "community_label_max_iterations": args.community_label_max_iterations,
        },
        "retrieval": search_config_audit(args),
        "models": {
            "graph_construction_model": graphiti_clients.get("graph_construction_model"),
            "paper_graph_construction_model": "gpt-4o-mini-2024-07-18",
            "embedder_mode": args.embedder,
            "embedding_model": graphiti_clients.get("embedding_model"),
            "paper_embedding_model": "BAAI/bge-m3",
            "cross_encoder_mode": args.cross_encoder,
            "reranker_model": graphiti_clients.get("reranker_model"),
            "paper_reranker_model": "BGE-m3 family",
        },
        "graph_counts": graph_counts,
        "conformance_flags": {
            "episode_subgraph_present": graph_counts.get("episodes", 0) > 0,
            "semantic_entity_subgraph_present": graph_counts.get("entities", 0) > 0
            and graph_counts.get("semantic_edges", 0) > 0,
            "community_subgraph_present": graph_counts.get("communities", 0) > 0,
            "temporal_edge_fields_present": graph_counts.get("semantic_edges_with_valid_at", 0) > 0
            or graph_counts.get("semantic_edges_with_invalid_at", 0) > 0,
            "edge_invalidation_observed": graph_counts.get("semantic_edges_with_invalid_at", 0) > 0
            or graph_counts.get("semantic_edges_with_expired_at", 0) > 0,
        },
    }


def summarize_rows(
    rows: Sequence[EvalRow],
    provider: Optional[str],
    model: Optional[str],
    judge_client: Optional[LLMClient],
    paper_audit: Dict[str, object],
    ingest_audit: Sequence[Dict[str, object]],
    community_build_audit: Dict[str, object],
    case_audits: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    result: Dict[str, object] = {
        "variant": DEFAULT_VARIANT,
        "model_provider": provider,
        "model": model,
        "judge_provider": judge_client.provider if judge_client else None,
        "judge_model": judge_client.model if judge_client else None,
        "paper_audit": paper_audit,
        "ingest_audit": list(ingest_audit),
        "community_build_audit": community_build_audit,
        "case_search_audits": list(case_audits),
    }
    if not rows:
        result["cases"] = []
        return result

    judge_scores = [row.slot_value_judge for row in rows if row.slot_value_judge is not None]
    answer_scores = [row.answer_judge for row in rows if row.answer_judge is not None]
    context_scores = [row.context_event_recall for row in rows if row.context_event_recall is not None]
    result.update(
        {
            "avg_event_f1": round(sum(row.event_f1 for row in rows) / len(rows), 3),
            "avg_event_precision": round(sum(row.event_precision for row in rows) / len(rows), 3),
            "avg_gold_event_recall": round(sum(row.gold_event_recall for row in rows) / len(rows), 3),
            "avg_context_event_recall": round(sum(context_scores) / len(context_scores), 3)
            if context_scores
            else None,
            "avg_slot_support_accuracy": round(sum(row.slot_support_accuracy for row in rows) / len(rows), 3),
            "avg_slot_support_f1": round(sum(row.slot_support_f1 for row in rows) / len(rows), 3),
            "avg_required_support_f1": round(sum(row.required_support_f1 for row in rows) / len(rows), 3),
            "avg_slot_value_judge": round(sum(judge_scores) / len(judge_scores), 3) if judge_scores else None,
            "avg_answer_judge": round(sum(answer_scores) / len(answer_scores), 3) if answer_scores else None,
            "cases": [row.__dict__ for row in rows],
        }
    )
    return result


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

    provider: Optional[str] = None
    model: Optional[str] = None
    client: Optional[LLMClient] = None
    judge_client: Optional[LLMClient] = None
    if not args.audit_only:
        try:
            api_key, model, api_base = provider_config(args.provider)
        except RuntimeError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            return 2
        provider = args.provider
        client = LLMClient(
            provider=args.provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            cache_path=Path(args.cache),
            use_cache=not args.no_cache,
        )
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

    try:
        graphiti_clients = build_graphiti_clients(args)
    except RuntimeError as exc:
        print(f"Graphiti config error: {exc}", file=sys.stderr)
        return 2

    graphiti = Graphiti(
        graph_driver=build_graphiti_driver(neo4j_uri, neo4j_user, neo4j_password),
        llm_client=graphiti_clients["llm_client"],
        embedder=graphiti_clients["embedder"],
        cross_encoder=graphiti_clients["cross_encoder"],
        max_coroutines=args.max_coroutines or None,
    )

    rows: List[EvalRow] = []
    ingest_audit: List[Dict[str, object]] = []
    community_build_audit: Dict[str, object] = {"enabled": False}
    case_audits: List[Dict[str, object]] = []
    graph_counts: Dict[str, int] = {}
    try:
        if args.reset_benchmark_data or args.reset_run:
            reset_scope = f"run_id={args.run_id}" if args.reset_run else f"all {args.group_prefix} data"
            print(f"resetting Graphiti paper data for {reset_scope}", flush=True)
            reset_summary = await reset_graphiti_paper_data(
                graphiti,
                run_id=args.run_id if args.reset_run else None,
                group_prefix=args.group_prefix,
            )
            print(f"reset summary: {reset_summary}", flush=True)
        await graphiti.build_indices_and_constraints()
        if not args.skip_ingest:
            ingest_audit = await ingest_events_sequentially(graphiti, events, args)
        if not args.skip_build_communities:
            print("building Graphiti paper communities for this run", flush=True)
            community_build_audit = await build_run_communities(graphiti, events, args)
        else:
            community_build_audit = {"enabled": False, "reason": "--skip-build-communities"}

        episode_event_ids = await load_episode_event_ids(graphiti, args.run_id, args.group_prefix)
        print(f"loaded {len(episode_event_ids)} Graphiti episode -> event_id mappings", flush=True)
        search_config = build_search_config(args)
        graph_counts = await graph_count_audit(graphiti, args.run_id, args.group_prefix)
        if args.community_build_only:
            print("community build audit only; skipping Graphiti search cases", flush=True)
            cases = []

        for case in cases:
            print(f"running {DEFAULT_VARIANT} / {case.case_id}", flush=True)
            search_payload = await search_case(graphiti, case, args, search_config, episode_event_ids)
            case_audits.append(
                {
                    "case_id": case.case_id,
                    "group_id": search_payload["group_id"],
                    "query": search_payload["query"],
                    "bfs_origin_node_uuids": search_payload["bfs_origin_node_uuids"],
                    "returned_counts": search_payload["returned_counts"],
                    "facts": search_payload["facts"],
                    "entities": search_payload["entities"],
                    "communities": search_payload["communities"],
                }
            )
            if args.audit_only:
                continue
            if client is None:
                raise RuntimeError("internal error: answer client was not initialized")
            raw = client.complete_json(
                graphiti_paper_system_prompt(),
                graphiti_paper_user_prompt(case, search_payload),
            )
            raw = normalize_graphiti_output_event_ids(raw, search_payload["facts"])
            raw["pipeline_trace"] = {
                "variant": DEFAULT_VARIANT,
                "graphiti_run_id": args.run_id,
                "paper_search_config": search_config_audit(args),
                "paper_search_payload": search_payload,
            }
            row = evaluate_output(raw, case)
            if judge_client is not None:
                print(f"judging {DEFAULT_VARIANT} / {case.case_id}", flush=True)
                row = attach_judge_score(judge_client, case, row)
            rows.append(row)
            time.sleep(0.2)
    except LLMRequestError as exc:
        print(f"LLM request failed: {exc}", file=sys.stderr)
        return 1
    except asyncio.TimeoutError:
        print(
            f"Graphiti ingest/search timed out after {args.ingest_timeout}s. "
            "Try a smaller subset or check the Graphiti LLM/Neo4j endpoint.",
            file=sys.stderr,
        )
        return 1
    finally:
        await graphiti.close()

    paper_audit = conformance_audit(args, graphiti_clients, graph_counts)
    result = summarize_rows(
        rows,
        provider,
        model,
        judge_client,
        paper_audit,
        ingest_audit,
        community_build_audit,
        case_audits,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([result], ensure_ascii=False, indent=2))
    print(f"Wrote {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a paper-structured Graphiti/Zep audit baseline for STAMB-State.")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--audit-only", action="store_true", help="Only run Graphiti ingest/search/audit, no answer LLM.")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-events", type=int, default=0)
    parser.add_argument("--search-limit", type=int, default=20)
    parser.add_argument("--bfs-origin-limit", type=int, default=12)
    parser.add_argument("--previous-message-window", type=int, default=4)
    parser.add_argument("--run-id", default=f"stamb-paper-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    parser.add_argument("--group-prefix", default=DEFAULT_GROUP_PREFIX)
    parser.add_argument("--reset-run", action="store_true")
    parser.add_argument("--reset-benchmark-data", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--ingest-timeout", type=int, default=900)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--update-communities",
        action="store_true",
        help=(
            "Enable Graphiti's dynamic community update during add_episode. "
            "Disabled by default because the current graphiti-core release can fail in this path."
        ),
    )
    parser.add_argument("--skip-build-communities", action="store_true")
    parser.add_argument(
        "--community-build-only",
        action="store_true",
        help="Run ingest/community build/audit output, then skip per-case search and answer generation.",
    )
    parser.add_argument("--community-build-timeout", type=int, default=180)
    parser.add_argument(
        "--community-build-scope-limit",
        type=int,
        default=0,
        help="Limit post-ingest community build to the first N scope groups; 0 builds every group.",
    )
    parser.add_argument("--community-label-max-iterations", type=int, default=50)
    parser.add_argument("--embedder", choices=("bge", "openai"), default="bge")
    parser.add_argument("--cross-encoder", choices=("bge", "openai"), default="bge")
    parser.add_argument("--bge-embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--embedding-dim", type=int, default=1024)
    parser.add_argument("--graphiti-max-tokens", type=int, default=8192)
    parser.add_argument("--max-coroutines", type=int, default=0)
    parser.add_argument(
        "--edge-reranker",
        choices=("reciprocal_rank_fusion", "node_distance", "episode_mentions", "mmr", "cross_encoder"),
        default="cross_encoder",
    )
    parser.add_argument(
        "--node-reranker",
        choices=("reciprocal_rank_fusion", "node_distance", "episode_mentions", "mmr", "cross_encoder"),
        default="cross_encoder",
    )
    parser.add_argument(
        "--community-reranker",
        choices=("reciprocal_rank_fusion", "mmr", "cross_encoder"),
        default="cross_encoder",
    )
    parser.add_argument("--sim-min-score", type=float, default=0.6)
    parser.add_argument("--mmr-lambda", type=float, default=0.5)
    parser.add_argument("--bfs-max-depth", type=int, default=3)
    parser.add_argument("--reranker-min-score", type=float, default=0.0)
    parser.add_argument("--events", default=str(DEFAULT_EVENTS_PATH))
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--output", default=str(BENCHMARK_DIR / "output/results_graphiti_paper_reproduction.json"))
    parser.add_argument("--cache", default=str(BENCHMARK_DIR / "output/graphiti_paper_llm_cache.json"))
    args = parser.parse_args()
    if args.limit_events < 0:
        parser.error("--limit-events must be >= 0")
    if args.limit_cases < 0:
        parser.error("--limit-cases must be >= 0")
    if args.search_limit < 1:
        parser.error("--search-limit must be >= 1")
    if args.bfs_origin_limit < 0:
        parser.error("--bfs-origin-limit must be >= 0")
    if args.previous_message_window < 0:
        parser.error("--previous-message-window must be >= 0")
    if args.ingest_timeout < 1:
        parser.error("--ingest-timeout must be >= 1")
    if args.community_build_timeout < 1:
        parser.error("--community-build-timeout must be >= 1")
    if args.community_build_scope_limit < 0:
        parser.error("--community-build-scope-limit must be >= 0")
    if args.community_label_max_iterations < 1:
        parser.error("--community-label-max-iterations must be >= 1")
    if args.embedding_dim < 1:
        parser.error("--embedding-dim must be >= 1")
    if args.max_coroutines < 0:
        parser.error("--max-coroutines must be >= 0")
    if args.reset_run and args.reset_benchmark_data:
        parser.error("--reset-run and --reset-benchmark-data are mutually exclusive")
    if args.community_build_only and args.skip_build_communities:
        parser.error("--community-build-only requires community build; remove --skip-build-communities")
    return args


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

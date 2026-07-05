from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import networkx as nx

from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.graph_store import load_graph_artifact


DEFAULT_METHOD = "longmemeval_s_graph_retrieval_v2"
JSON_PREFIX = "__json__:"

NODE_LABELS = {
    "Episode/Event": "Event",
    "Claim": "Claim",
    "State Facet": "StateFacet",
    "Entity/Scope": "EntityScope",
    "Time": "Time",
}

EDGE_TYPES = {
    "event_mentions_entity": "EVENT_MENTIONS_ENTITY",
    "event_in_scope": "EVENT_IN_SCOPE",
    "claim_supported_by_event": "CLAIM_SUPPORTED_BY_EVENT",
    "claim_corrects_claim": "CLAIM_CORRECTS_CLAIM",
    "claim_supersedes_claim": "CLAIM_SUPERSEDES_CLAIM",
    "claim_conflicts_with_claim": "CLAIM_CONFLICTS_WITH_CLAIM",
    "facet_supported_by_claim": "FACET_SUPPORTED_BY_CLAIM",
    "facet_current_after_time": "FACET_CURRENT_AFTER_TIME",
}


def load_dotenv_if_available() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def neo4j_config_from_env() -> tuple[str, str, str]:
    load_dotenv_if_available()
    uri = os.environ.get("NEO4J_URI", "").strip()
    username = (os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER") or "").strip()
    password = os.environ.get("NEO4J_PASSWORD", "").strip()
    missing = [
        name
        for name, value in (
            ("NEO4J_URI", uri),
            ("NEO4J_USERNAME", username),
            ("NEO4J_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"missing Neo4j config: {', '.join(missing)}")
    return uri, username, password


def graph_files(graph_dir: Path, question_types: Iterable[str] = (), question_ids: Iterable[str] = ()) -> list[Path]:
    allowed_types = set(question_types)
    allowed_ids = set(question_ids)
    paths = sorted(graph_dir.glob("**/*.graph.json"))
    selected: list[Path] = []
    for path in paths:
        question_id = path.name.removesuffix(".graph.json")
        question_type = path.parent.name
        if allowed_types and question_type not in allowed_types:
            continue
        if allowed_ids and question_id not in allowed_ids:
            continue
        selected.append(path)
    return selected


def primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def encode_value(value: Any) -> Any:
    if primitive(value):
        return value
    if isinstance(value, list) and all(primitive(item) for item in value):
        return value
    return JSON_PREFIX + json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(JSON_PREFIX):
        try:
            return json.loads(value[len(JSON_PREFIX):])
        except json.JSONDecodeError:
            return value
    return value


def encode_properties(values: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): encode_value(value) for key, value in values.items() if value is not None}


def decode_properties(values: Mapping[str, Any], drop_internal: bool = True) -> dict[str, Any]:
    internal = {
        "method",
        "json_node_id",
        "json_source",
        "json_target",
        "json_edge_key",
        "import_edge_index",
    }
    props = {}
    for key, value in values.items():
        if drop_internal and key in internal:
            continue
        props[str(key)] = decode_value(value)
    return props


def safe_label(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return "Unknown"
    if value[0].isdigit():
        value = f"L_{value}"
    return value


def node_labels(node_type: str) -> str:
    semantic = NODE_LABELS.get(node_type, safe_label(node_type))
    return f":GraphNode:{safe_label(semantic)}"


def relationship_type(edge_type: str) -> str:
    return EDGE_TYPES.get(edge_type, safe_label(edge_type).upper())


class Neo4jGraphStore:
    def __init__(self, uri: str, username: str, password: str, method: str = DEFAULT_METHOD) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Neo4j Python driver is not installed. Install with: pip install neo4j") from exc
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.method = method

    @classmethod
    def from_env(cls, method: str = DEFAULT_METHOD) -> "Neo4jGraphStore":
        uri, username, password = neo4j_config_from_env()
        return cls(uri=uri, username=username, password=password, method=method)

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "Neo4jGraphStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def create_constraints(self) -> None:
        queries = [
            """
            CREATE CONSTRAINT graph_node_identity IF NOT EXISTS
            FOR (n:GraphNode)
            REQUIRE (n.method, n.question_id, n.json_node_id) IS UNIQUE
            """,
            """
            CREATE CONSTRAINT case_graph_identity IF NOT EXISTS
            FOR (c:CaseGraph)
            REQUIRE (c.method, c.question_id) IS UNIQUE
            """,
        ]
        with self.driver.session() as session:
            for query in queries:
                session.run(query)

    def clear_method_data(self) -> None:
        with self.driver.session() as session:
            session.run("MATCH (n:GraphNode {method: $method}) DETACH DELETE n", method=self.method)
            session.run("MATCH (c:CaseGraph {method: $method}) DETACH DELETE c", method=self.method)

    def clear_question(self, question_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (n:GraphNode {method: $method, question_id: $question_id}) DETACH DELETE n",
                method=self.method,
                question_id=question_id,
            )
            session.run(
                "MATCH (c:CaseGraph {method: $method, question_id: $question_id}) DETACH DELETE c",
                method=self.method,
                question_id=question_id,
            )

    def import_artifact(self, path: Path, clear_existing: bool = False) -> dict[str, Any]:
        artifact = load_graph_artifact(path)
        metadata = dict(artifact.get("metadata") or {})
        graph_metadata = dict(artifact.get("graph_metadata") or {})
        question_id = str(metadata.get("question_id") or path.name.removesuffix(".graph.json"))
        question_type = str(metadata.get("question_type") or path.parent.name)
        if clear_existing:
            self.clear_question(question_id)

        case_props = {
            "method": self.method,
            "question_id": question_id,
            "question_type": question_type,
            "artifact_path": str(path),
            "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            "graph_metadata_json": json.dumps(graph_metadata, ensure_ascii=False, sort_keys=True),
        }
        nodes = artifact.get("nodes") or []
        edges = artifact.get("edges") or []
        with self.driver.session() as session:
            session.run(
                """
                MERGE (c:CaseGraph {method: $method, question_id: $question_id})
                SET c += $props
                """,
                method=self.method,
                question_id=question_id,
                props=case_props,
            )
            for node in nodes:
                node_id = str(node["id"])
                attrs = dict(node.get("attributes") or {})
                props = encode_properties(
                    {
                        **attrs,
                        "method": self.method,
                        "question_id": question_id,
                        "question_type": question_type,
                        "json_node_id": node_id,
                    }
                )
                labels = node_labels(str(attrs.get("node_type") or "Unknown"))
                session.run(
                    f"""
                    MERGE (n{labels} {{method: $method, question_id: $question_id, json_node_id: $json_node_id}})
                    SET n += $props
                    """,
                    method=self.method,
                    question_id=question_id,
                    json_node_id=node_id,
                    props=props,
                )
            for edge_index, edge in enumerate(edges):
                source = str(edge["source"])
                target = str(edge["target"])
                attrs = dict(edge.get("attributes") or {})
                edge_type = str(attrs.get("edge_type") or edge.get("key") or "RELATED_TO")
                rel_type = relationship_type(edge_type)
                edge_key = str(edge.get("key") or edge_index)
                props = encode_properties(
                    {
                        **attrs,
                        "method": self.method,
                        "question_id": question_id,
                        "question_type": question_type,
                        "json_source": source,
                        "json_target": target,
                        "json_edge_key": edge_key,
                        "import_edge_index": edge_index,
                    }
                )
                session.run(
                    f"""
                    MATCH (s:GraphNode {{method: $method, question_id: $question_id, json_node_id: $source}})
                    MATCH (t:GraphNode {{method: $method, question_id: $question_id, json_node_id: $target}})
                    MERGE (s)-[r:{rel_type} {{
                        method: $method,
                        question_id: $question_id,
                        json_source: $source,
                        json_target: $target,
                        json_edge_key: $edge_key,
                        import_edge_index: $edge_index
                    }}]->(t)
                    SET r += $props
                    """,
                    method=self.method,
                    question_id=question_id,
                    source=source,
                    target=target,
                    edge_key=edge_key,
                    edge_index=edge_index,
                    props=props,
                )
        return {
            "question_id": question_id,
            "question_type": question_type,
            "nodes": len(nodes),
            "edges": len(edges),
            "path": str(path),
        }

    def has_graph(self, question_id: str) -> bool:
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (c:CaseGraph {method: $method, question_id: $question_id})
                RETURN count(c) AS count
                """,
                method=self.method,
                question_id=question_id,
            ).single()
        return bool(record and int(record["count"]) > 0)

    def graph_counts(self, question_id: str) -> dict[str, int]:
        with self.driver.session() as session:
            node_record = session.run(
                """
                MATCH (n:GraphNode {method: $method, question_id: $question_id})
                RETURN count(n) AS count
                """,
                method=self.method,
                question_id=question_id,
            ).single()
            edge_record = session.run(
                """
                MATCH (:GraphNode {method: $method, question_id: $question_id})-[r]->
                      (:GraphNode {method: $method, question_id: $question_id})
                RETURN count(r) AS count
                """,
                method=self.method,
                question_id=question_id,
            ).single()
        return {
            "nodes": int(node_record["count"]) if node_record else 0,
            "edges": int(edge_record["count"]) if edge_record else 0,
        }

    def fetch_graph(self, question_id: str) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph()
        with self.driver.session() as session:
            case_record = session.run(
                """
                MATCH (c:CaseGraph {method: $method, question_id: $question_id})
                RETURN c
                """,
                method=self.method,
                question_id=question_id,
            ).single()
            if case_record:
                case_props = dict(case_record["c"])
                graph.graph.update(json.loads(case_props.get("graph_metadata_json") or "{}"))
                graph.graph["artifact_metadata"] = json.loads(case_props.get("metadata_json") or "{}")

            node_records = session.run(
                """
                MATCH (n:GraphNode {method: $method, question_id: $question_id})
                RETURN n
                """,
                method=self.method,
                question_id=question_id,
            )
            for record in node_records:
                props = dict(record["n"])
                node_id = str(props.get("json_node_id"))
                graph.add_node(node_id, **decode_properties(props))

            edge_records = session.run(
                """
                MATCH (s:GraphNode {method: $method, question_id: $question_id})-[r]->
                      (t:GraphNode {method: $method, question_id: $question_id})
                RETURN s.json_node_id AS source, t.json_node_id AS target, r
                ORDER BY r.import_edge_index
                """,
                method=self.method,
                question_id=question_id,
            )
            for record in edge_records:
                source = str(record["source"])
                target = str(record["target"])
                props = dict(record["r"])
                edge_key = str(props.get("json_edge_key") or props.get("import_edge_index") or "")
                graph.add_edge(source, target, key=edge_key, **decode_properties(props))
        return graph

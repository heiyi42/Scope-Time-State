from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

import networkx as nx


def graph_to_artifact(graph: nx.MultiDiGraph, metadata: Mapping[str, Any]) -> Dict[str, Any]:
    nodes = [
        {
            "id": str(node_id),
            "attributes": dict(data),
        }
        for node_id, data in graph.nodes(data=True)
    ]
    edges = [
        {
            "source": str(source),
            "target": str(target),
            "key": str(key),
            "attributes": dict(data),
        }
        for source, target, key, data in graph.edges(keys=True, data=True)
    ]
    return {
        "metadata": dict(metadata),
        "graph_metadata": dict(graph.graph),
        "nodes": nodes,
        "edges": edges,
    }


def graph_from_artifact(artifact: Mapping[str, Any]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.graph.update(dict(artifact.get("graph_metadata") or {}))
    for node in artifact.get("nodes") or []:
        node_id = str(node["id"])
        attrs = dict(node.get("attributes") or {})
        graph.add_node(node_id, **attrs)
    for edge in artifact.get("edges") or []:
        source = str(edge["source"])
        target = str(edge["target"])
        attrs = dict(edge.get("attributes") or {})
        graph.add_edge(source, target, **attrs)
    return graph


def write_graph_artifact(path: Path, graph: nx.MultiDiGraph, metadata: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = graph_to_artifact(graph, metadata)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_graph_artifact(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_graph(path: Path) -> nx.MultiDiGraph:
    return graph_from_artifact(load_graph_artifact(path))


from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pipeline.external.groupmembench.graph_schema import (
    EDGE_ENDPOINT_TYPES,
    EDGE_TYPES,
    NODE_TYPES,
    canonical_edge_type,
)


SCHEMA_VERSION = "groupmembench-image-graph-v1"
KNOWN_ARTIFACT_FILES = ("manifest.json", "nodes.jsonl", "edges.jsonl", "locked_state_packet.json")
NODE_ID_FIELDS = ("event_id", "claim_id", "facet_id", "scope_id", "entity_id", "time_id")


@dataclass(frozen=True)
class GraphArtifact:
    root: Path
    manifest: Dict[str, Any]
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    locked_raw: Dict[str, Any]

    @property
    def node_by_id(self) -> Dict[str, Dict[str, Any]]:
        return {node_id(node): node for node in self.nodes if node_id(node)}

    @property
    def candidate_event_ids(self) -> List[str]:
        packet = self.locked_raw.get("state_packet", {})
        if isinstance(packet, dict) and isinstance(packet.get("candidate_events"), list):
            return [str(event_id) for event_id in packet["candidate_events"]]
        return [
            str(node.get("event_id"))
            for node in self.nodes
            if node.get("node_type") == "Episode/Event" and node.get("event_id")
        ]

    @property
    def target_scope_id(self) -> Optional[str]:
        packet = self.locked_raw.get("state_packet", {})
        if isinstance(packet, dict) and packet.get("target_scope_id"):
            return str(packet["target_scope_id"])
        return None


def safe_path_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "unknown"


def graph_artifact_dir(base_dir: Path, domain: str, qtype: str, question_id: str) -> Path:
    return base_dir / safe_path_part(domain) / safe_path_part(qtype) / safe_path_part(question_id)


def node_id(node: Mapping[str, Any]) -> str:
    node_type = str(node.get("node_type") or "")
    typed_fields = {
        "Episode/Event": ("event_id",),
        "Claim": ("claim_id",),
        "StateFacet": ("facet_id",),
        "Entity/Scope": ("scope_id", "entity_id"),
        "Time": ("time_id",),
    }.get(node_type)
    if typed_fields:
        for field in typed_fields:
            value = node.get(field)
            if value not in {None, "", "null"}:
                return str(value)
    for field in NODE_ID_FIELDS:
        value = node.get(field)
        if value not in {None, "", "null"}:
            return str(value)
    return ""


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def empty_merge_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def merge_node(existing: Dict[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged or empty_merge_value(merged[key]):
            merged[key] = value
    return merged


def graph_nodes(graph_trace: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw_nodes = graph_trace.get("nodes", {})
    if not isinstance(raw_nodes, dict):
        return []
    flattened: Dict[str, Dict[str, Any]] = {}

    def add_node(raw_node: object) -> None:
        if not isinstance(raw_node, dict):
            return
        node = deepcopy(raw_node)
        node_type = str(node.get("node_type") or "")
        if node_type not in NODE_TYPES:
            return
        identifier = node_id(node)
        if not identifier:
            return
        if identifier in flattened:
            flattened[identifier] = merge_node(flattened[identifier], node)
        else:
            flattened[identifier] = node

    add_node(raw_nodes.get("entity_scope"))
    for key in ("mentioned_entity_scopes", "episode_events", "times", "claims", "state_facets"):
        values = raw_nodes.get(key, [])
        if isinstance(values, list):
            for value in values:
                add_node(value)
    return sorted(flattened.values(), key=lambda item: (str(item.get("node_type", "")), node_id(item)))


def normalize_edges(
    graph_trace: Mapping[str, Any],
    nodes: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    node_types_by_id = {node_id(node): str(node.get("node_type") or "") for node in nodes if node_id(node)}
    normalized: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen = set()
    raw_edges = graph_trace.get("edges", [])
    if not isinstance(raw_edges, list):
        return [], ["edges_not_list"]
    for index, item in enumerate(raw_edges):
        if not isinstance(item, dict):
            warnings.append(f"edge_not_object:{index}")
            continue
        try:
            edge_type = canonical_edge_type(item.get("type"))
        except ValueError as exc:
            warnings.append(f"unsupported_edge_type:{index}:{exc}")
            continue
        source = str(item.get("from") or "")
        target = str(item.get("to") or "")
        if not source or not target:
            warnings.append(f"edge_missing_endpoint:{index}:{edge_type}")
            continue
        source_type = node_types_by_id.get(source)
        target_type = node_types_by_id.get(target)
        expected = EDGE_ENDPOINT_TYPES[edge_type]
        if source_type != expected[0] or target_type != expected[1]:
            warnings.append(
                f"edge_endpoint_type_mismatch:{index}:{edge_type}:{source_type or '?'}->{target_type or '?'}"
            )
            continue
        edge = deepcopy(item)
        edge["type"] = edge_type
        edge["from"] = source
        edge["to"] = target
        key = (
            edge["type"],
            edge["from"],
            edge["to"],
            json.dumps(edge.get("evidence_event_ids", []), ensure_ascii=False, sort_keys=True),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(edge)
    return normalized, warnings


def graph_schema_payload() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
        "edge_endpoint_types": {edge_type: list(types) for edge_type, types in EDGE_ENDPOINT_TYPES.items()},
        "source": "Design/Graph/*.png",
    }


def reset_artifact_dir(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def strip_answer_fields(locked_raw: Mapping[str, Any]) -> Dict[str, Any]:
    clean = deepcopy(dict(locked_raw))
    clean.pop("answer", None)
    trace = clean.get("pipeline_trace")
    if isinstance(trace, dict):
        trace.pop("composer_output", None)
        trace.pop("answer_normalization", None)
    return clean


def write_graph_artifact(
    root: Path,
    manifest: Mapping[str, Any],
    locked_raw: Mapping[str, Any],
) -> GraphArtifact:
    graph_trace = locked_raw.get("graph_trace", {})
    if not isinstance(graph_trace, dict):
        raise ValueError("locked_raw must contain graph_trace object")
    nodes = graph_nodes(graph_trace)
    edges, warnings = normalize_edges(graph_trace, nodes)
    clean_locked = strip_answer_fields(locked_raw)
    manifest_payload = {
        **dict(manifest),
        "schema": graph_schema_payload(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "graph_warnings": warnings,
        "artifact_files": list(KNOWN_ARTIFACT_FILES),
    }
    reset_artifact_dir(root)
    (root / "manifest.json").write_text(json_dump(manifest_payload))
    write_jsonl(root / "nodes.jsonl", nodes)
    write_jsonl(root / "edges.jsonl", edges)
    (root / "locked_state_packet.json").write_text(json_dump(clean_locked))
    return GraphArtifact(root=root, manifest=manifest_payload, nodes=nodes, edges=edges, locked_raw=clean_locked)


def load_graph_artifact(root: Path) -> GraphArtifact:
    manifest_path = root / "manifest.json"
    nodes_path = root / "nodes.jsonl"
    edges_path = root / "edges.jsonl"
    locked_path = root / "locked_state_packet.json"
    missing = [path.name for path in (manifest_path, nodes_path, edges_path, locked_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing graph artifact files under {root}: {', '.join(missing)}")
    manifest = json.loads(manifest_path.read_text())
    locked_raw = json.loads(locked_path.read_text())
    return GraphArtifact(
        root=root,
        manifest=manifest if isinstance(manifest, dict) else {},
        nodes=read_jsonl(nodes_path),
        edges=read_jsonl(edges_path),
        locked_raw=locked_raw if isinstance(locked_raw, dict) else {},
    )


def discover_graph_artifacts(base_dir: Path) -> List[Path]:
    return sorted(path.parent for path in base_dir.rglob("manifest.json"))


def graph_manifest_for_question(
    *,
    question: Any,
    build_config: Mapping[str, Any],
    scope_route: Mapping[str, Any],
    retrieval_debug: Mapping[str, Any],
    graph_provider: str,
    graph_model: str,
) -> Dict[str, Any]:
    return {
        "benchmark": "GroupMemBench",
        "graph_id": f"{question.domain}:{question.qtype}:{question.question_id}",
        "case_id": question.case_id,
        "domain": question.domain,
        "qtype": question.qtype,
        "question_id": question.question_id,
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "graph_provider": graph_provider,
        "graph_model": graph_model,
        "build_config": dict(build_config),
        "scope_route": dict(scope_route),
        "retrieval_debug": dict(retrieval_debug),
        "leakage_boundary": {
            "answer_reference_present": False,
            "judge_metadata_present": False,
        },
    }

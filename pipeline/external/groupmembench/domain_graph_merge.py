from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pipeline.external.groupmembench.domain_graph import domain_graph_artifact_dir  # noqa: E402
from pipeline.external.groupmembench.graph_schema import time_id, time_node  # noqa: E402
from pipeline.external.groupmembench.graph_store import load_graph_artifact, node_id, write_graph_artifact  # noqa: E402
from pipeline.external.groupmembench.loader import (  # noqa: E402
    DOMAINS,
    build_scope_inventory,
    conversation_path,
    load_domain_messages,
)


MERGEABLE_BUILD_UNITS = {"domain_corpus", "domain_scope"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge partial GroupMemBench domain graph artifacts.")
    parser.add_argument("--domain", choices=DOMAINS, required=True)
    parser.add_argument("--source-artifacts", nargs="+", required=True, help="Partial artifact directories to merge.")
    parser.add_argument("--output-dir", required=True, help="Root output dir; merged artifact is written under <output-dir>/<domain>.")
    parser.add_argument("--expected-scope-count", type=int, default=0)
    parser.add_argument("--expected-event-count", type=int, default=0)
    return parser.parse_args()


def unique_by_key(rows: Iterable[Mapping[str, Any]], key_fields: Sequence[str]) -> List[Dict[str, Any]]:
    unique: Dict[tuple[str, ...], Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = tuple(str(row.get(field) or "") for field in key_fields)
        if not any(key):
            key = (json.dumps(row, ensure_ascii=False, sort_keys=True),)
        unique.setdefault(key, deepcopy(dict(row)))
    return list(unique.values())


def state_packet(locked_raw: Mapping[str, Any]) -> Dict[str, Any]:
    packet = locked_raw.get("state_packet", {})
    return packet if isinstance(packet, dict) else {}


def full_domain_counts(domain: str) -> Dict[str, int]:
    messages = load_domain_messages(domain)
    return {
        "full_scope_count": len(build_scope_inventory(messages)),
        "full_event_count": len(messages),
    }


def build_nodes_payload(nodes: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "episode_events": [],
        "mentioned_entity_scopes": [],
        "times": [],
        "claims": [],
        "state_facets": [],
    }
    seen: set[str] = set()
    for raw_node in nodes:
        if not isinstance(raw_node, Mapping):
            continue
        node = deepcopy(dict(raw_node))
        identifier = node_id(node)
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        node_type = str(node.get("node_type") or "")
        if node_type == "Episode/Event":
            grouped["episode_events"].append(node)
        elif node_type == "Entity/Scope":
            grouped["mentioned_entity_scopes"].append(node)
        elif node_type == "Time":
            grouped["times"].append(node)
        elif node_type == "Claim":
            grouped["claims"].append(node)
        elif node_type == "StateFacet":
            grouped["state_facets"].append(node)
    for values in grouped.values():
        values.sort(key=lambda item: node_id(item))
    return grouped


def relation_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("type") or "").upper(),
        str(row.get("from") or ""),
        str(row.get("to") or ""),
        json.dumps(row.get("evidence_event_ids", []), ensure_ascii=False, sort_keys=True),
    )


def merge_artifacts(domain: str, source_dirs: Sequence[Path], output_dir: Path, expected_scope_count: int, expected_event_count: int) -> Dict[str, Any]:
    artifacts = [load_graph_artifact(path) for path in source_dirs]
    for artifact in artifacts:
        artifact_domain = str(artifact.manifest.get("domain") or "")
        if artifact_domain != domain:
            raise ValueError(f"artifact domain mismatch: {artifact.root} has {artifact_domain!r}, expected {domain!r}")
        build_unit = str(artifact.manifest.get("build_unit") or "")
        if build_unit not in MERGEABLE_BUILD_UNITS:
            raise ValueError(f"not a mergeable domain graph artifact: {artifact.root} build_unit={build_unit!r}")

    nodes = [node for artifact in artifacts for node in artifact.nodes]
    nodes_payload = build_nodes_payload(nodes)
    event_ids = [str(node.get("event_id")) for node in nodes_payload["episode_events"] if node.get("event_id")]
    claim_ids = {str(node.get("claim_id")) for node in nodes_payload["claims"] if node.get("claim_id")}
    scope_ids = {
        str(node.get("scope_id"))
        for node in nodes_payload["mentioned_entity_scopes"]
        if node.get("node_type") == "Entity/Scope" and node.get("role") == "scope" and node.get("scope_id")
    }

    relations_by_key: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    rejected_claims: List[Dict[str, Any]] = []
    state_facets_by_id: Dict[str, Dict[str, Any]] = {}
    for artifact in artifacts:
        packet = state_packet(artifact.locked_raw)
        for relation in packet.get("relations", []) if isinstance(packet.get("relations"), list) else []:
            if isinstance(relation, Mapping):
                relations_by_key.setdefault(relation_key(relation), deepcopy(dict(relation)))
        for rejected in packet.get("rejected_claims", []) if isinstance(packet.get("rejected_claims"), list) else []:
            if isinstance(rejected, Mapping):
                rejected_claims.append(deepcopy(dict(rejected)))
        for facet in packet.get("state_facets", []) if isinstance(packet.get("state_facets"), list) else []:
            if not isinstance(facet, Mapping):
                continue
            facet_id = str(facet.get("facet_id") or "")
            if facet_id:
                state_facets_by_id.setdefault(facet_id, deepcopy(dict(facet)))

    relations = sorted(relations_by_key.values(), key=relation_key)
    rejected_claims = unique_by_key(rejected_claims, ("claim_id", "event_id", "validity", "reason"))
    state_facets = sorted(state_facets_by_id.values(), key=lambda item: str(item.get("facet_id") or ""))
    nodes_payload["state_facets"] = state_facets
    known_time_ids = {str(node.get("time_id") or "") for node in nodes_payload["times"]}
    for facet in state_facets:
        current_after = str(facet.get("current_after") or "")
        if not current_after:
            continue
        current_after_id = time_id(current_after)
        if current_after_id in known_time_ids:
            continue
        known_time_ids.add(current_after_id)
        nodes_payload["times"].append(time_node(current_after, "state_facet_current_after"))
    nodes_payload["times"].sort(key=lambda item: node_id(item))

    edges_by_key: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    for artifact in artifacts:
        for edge in artifact.edges:
            if not isinstance(edge, Mapping):
                continue
            key = (
                str(edge.get("type") or "").upper(),
                str(edge.get("from") or ""),
                str(edge.get("to") or ""),
                json.dumps(edge.get("evidence_event_ids", []), ensure_ascii=False, sort_keys=True),
            )
            edges_by_key.setdefault(key, deepcopy(dict(edge)))

    stats = {
        "scope_count": len(scope_ids),
        "event_count": len(event_ids),
        "entity_count": sum(1 for node in nodes_payload["mentioned_entity_scopes"] if node.get("role") != "scope"),
        "time_count": len(nodes_payload["times"]),
        "claim_count": len(nodes_payload["claims"]),
        "events_with_claims": len({str(node.get("event_id") or "") for node in nodes_payload["claims"] if node.get("event_id")}),
        "claimless_event_count": len(event_ids)
        - len({str(node.get("event_id") or "") for node in nodes_payload["claims"] if node.get("event_id")}),
        "relation_count": len(relations),
        "rejected_claim_count": len(rejected_claims),
        "state_facet_count": len(state_facets),
    }
    if expected_scope_count and stats["scope_count"] != expected_scope_count:
        raise ValueError(f"merged scope_count={stats['scope_count']} expected={expected_scope_count}")
    if expected_event_count and stats["event_count"] != expected_event_count:
        raise ValueError(f"merged event_count={stats['event_count']} expected={expected_event_count}")

    full_counts = full_domain_counts(domain)
    is_partial = (
        stats["scope_count"] != full_counts["full_scope_count"]
        or stats["event_count"] != full_counts["full_event_count"]
    )

    source_artifacts = []
    for artifact in artifacts:
        source_artifacts.append(
            {
                "artifact_dir": str(artifact.root),
                "build_unit": artifact.manifest.get("build_unit"),
                "graph_model": artifact.manifest.get("graph_model"),
                "build_config": artifact.manifest.get("build_config", {}),
                "domain_stats": artifact.manifest.get("domain_stats", {}),
                "node_count": artifact.manifest.get("node_count"),
                "edge_count": artifact.manifest.get("edge_count"),
                "graph_warnings": artifact.manifest.get("graph_warnings", []),
            }
        )

    first_manifest = artifacts[0].manifest
    manifest = {
        "benchmark": "GroupMemBench",
        "graph_id": f"GroupMemBench:{domain}:domain_corpus",
        "build_unit": "domain_corpus",
        "protocol": "offline_domain_graph",
        "domain": domain,
        "source_corpus": str(conversation_path(domain)),
        "question_conditioned": False,
        "question_seen": False,
        "gold_seen": False,
        "graph_provider": first_manifest.get("graph_provider"),
        "graph_model": first_manifest.get("graph_model"),
        "claim_mode": first_manifest.get("claim_mode"),
        "is_partial": is_partial,
        "build_config": {
            **dict(first_manifest.get("build_config", {}) if isinstance(first_manifest.get("build_config"), dict) else {}),
            "merge_source_artifact_count": len(artifacts),
            "merged_from_partial_artifacts": True,
            **full_counts,
        },
        "domain_stats": stats,
        "source_artifacts": source_artifacts,
        "leakage_boundary": {
            "question_text_present": False,
            "answer_reference_present": False,
            "judge_metadata_present": False,
        },
    }
    locked_raw = {
        "state_packet": {
            "target_scope_id": None,
            "candidate_events": event_ids,
            "claims": nodes_payload["claims"],
            "validity_decisions": {},
            "relations": relations,
            "rejected_claims": rejected_claims,
            "state_facets": state_facets,
        },
        "graph_trace": {
            "nodes": nodes_payload,
            "edges": sorted(edges_by_key.values(), key=lambda item: (str(item.get("type") or ""), str(item.get("from") or ""), str(item.get("to") or ""))),
        },
        "pipeline_trace": {
            "pipeline": "offline_domain_graph_merge",
            "build_unit": "domain_corpus",
            "domain": domain,
            "question_conditioned": False,
            "question_seen": False,
            "gold_seen": False,
            "source_artifacts": source_artifacts,
        },
    }
    artifact = write_graph_artifact(domain_graph_artifact_dir(output_dir, domain), manifest, locked_raw)
    type_counts = Counter(str(node.get("node_type") or "") for node in artifact.nodes)
    edge_counts = Counter(str(edge.get("type") or "") for edge in artifact.edges)
    return {
        "domain": domain,
        "artifact_dir": str(artifact.root),
        "node_count": len(artifact.nodes),
        "edge_count": len(artifact.edges),
        "node_type_counts": dict(sorted(type_counts.items())),
        "edge_type_counts": dict(sorted(edge_counts.items())),
        "graph_warnings": artifact.manifest.get("graph_warnings", []),
        "domain_stats": stats,
    }


def main() -> int:
    args = parse_args()
    summary = merge_artifacts(
        args.domain,
        [Path(path) for path in args.source_artifacts],
        Path(args.output_dir),
        args.expected_scope_count,
        args.expected_event_count,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, DefaultDict, Dict, List, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[5]
BASELINE_DIR = Path(__file__).resolve().parents[1]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state.graph_builder import (
    dedupe_edges,
    enrich_claim_annotations,
    json_dump,
    materialize_claim_responsibility_edges,
    materialize_claim_task_objects,
    materialize_claim_time,
    materialize_state_task_object_links,
    node_id,
    validate_graph,
    write_jsonl,
)
from ours_scope_time_state.loader import DATA_DIR, GRAPH_OUTPUT_DIR, load_topic_events


DERIVED_CLAIM_FIELDS = (
    "time_value",
    "time_value_source",
    "time_explicitness_score",
    "metric_type",
    "metric_unit",
    "metric_value_num",
    "metric_value_text",
    "metric_kind",
    "metric_source",
    "task_object_scope_ids",
    "task_object_labels",
)
DERIVED_STATE_METRIC_FIELDS = (
    "metric_type",
    "metric_unit",
    "metric_value_num",
    "metric_value_text",
    "metric_kind",
    "metric_source",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich an existing EverMemBench STS graph without reading QA/gold files.")
    parser.add_argument("--topic", default="01")
    parser.add_argument("--data-root", type=Path, default=DATA_DIR)
    parser.add_argument("--input-graph-dir", type=Path, required=True)
    parser.add_argument(
        "--output-graph-dir",
        type=Path,
        default=GRAPH_OUTPUT_DIR / "evermembench_topic_graph_llm_v3_temporal_effort/01",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def graph_node_counts(nodes: Mapping[str, Mapping[str, Any]]) -> Dict[str, int]:
    return dict(Counter(str(node.get("node_type") or "") for node in nodes.values()))


def graph_edge_counts(edges: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    return dict(Counter(str(edge.get("type") or "") for edge in edges))


def collect_preserved_time_ids(
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> set[str]:
    kept: set[str] = set()
    for edge in edges:
        if edge.get("type") == "HAS_TIME":
            continue
        for endpoint_key in ("from", "to"):
            endpoint = str(edge.get(endpoint_key) or "")
            if str(nodes.get(endpoint, {}).get("node_type") or "") == "Time":
                kept.add(endpoint)
    return kept


def update_state_metric_fields(
    nodes: Dict[str, Dict[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    claims: Mapping[str, Mapping[str, Any]],
) -> Dict[str, int]:
    support_claims_by_state: DefaultDict[str, List[str]] = defaultdict(list)
    for edge in edges:
        if edge.get("type") == "SUPPORTS":
            claim_id = str(edge.get("from") or "")
            state_id = str(edge.get("to") or "")
            if claim_id and state_id:
                support_claims_by_state[state_id].append(claim_id)

    updated = 0
    cleared = 0
    for state_id, claim_ids in support_claims_by_state.items():
        state = nodes.get(state_id)
        if not state or str(state.get("node_type") or "") != "StateFacet":
            continue
        for field in DERIVED_STATE_METRIC_FIELDS:
            if field in state:
                state.pop(field, None)
                cleared += 1
        metric_claim = next(
            (
                claims[claim_id]
                for claim_id in claim_ids
                if claim_id in claims and claims[claim_id].get("metric_type") and claims[claim_id].get("metric_value_num") is not None
            ),
            None,
        )
        if metric_claim is None:
            continue
        for field in DERIVED_STATE_METRIC_FIELDS:
            if field in metric_claim:
                state[field] = metric_claim[field]
        updated += 1
    return {"state_metric_updates": updated, "state_metric_fields_cleared": cleared}


def enrich_graph(
    topic_id: str,
    data_root: Path,
    input_graph_dir: Path,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    events = load_topic_events(topic_id, data_root)
    events_by_id = {event.event_id: event for event in events}
    old_nodes = {node_id(row): row for row in read_jsonl(input_graph_dir / "nodes.jsonl")}
    old_edges = read_jsonl(input_graph_dir / "edges.jsonl")

    old_task_object_scope_ids = {
        identifier
        for identifier, node in old_nodes.items()
        if str(node.get("node_type") or "") == "Entity/Scope" and str(node.get("scope_type") or "") == "task_object"
    }
    preserved_time_ids = collect_preserved_time_ids(old_nodes, old_edges)
    nodes: Dict[str, Dict[str, Any]] = {}
    for identifier, node in old_nodes.items():
        node_type = str(node.get("node_type") or "")
        if identifier in old_task_object_scope_ids:
            continue
        if node_type != "Time" or identifier in preserved_time_ids:
            nodes[identifier] = dict(node)

    edges = [
        dict(edge)
        for edge in old_edges
        if edge.get("type") != "HAS_TIME"
        and str(edge.get("from") or "") not in old_task_object_scope_ids
        and str(edge.get("to") or "") not in old_task_object_scope_ids
    ]
    claims: Dict[str, Dict[str, Any]] = {}
    claim_enriched = 0
    claim_missing_event = 0
    responsibility_link_count = 0
    for identifier, node in list(nodes.items()):
        if str(node.get("node_type") or "") != "Claim":
            continue
        event_id = str(node.get("source_event_id") or "")
        event = events_by_id.get(event_id)
        if event is None:
            claim_missing_event += 1
            claims[identifier] = node
            continue
        for field in DERIVED_CLAIM_FIELDS:
            node.pop(field, None)
        enriched = enrich_claim_annotations(node, event)
        nodes[identifier] = enriched
        claims[identifier] = enriched
        claim_enriched += 1
        materialize_claim_task_objects(nodes, edges, enriched, event)
        responsibility_link_count += materialize_claim_responsibility_edges(nodes, edges, enriched, event)
        materialize_claim_time(nodes, edges, enriched, event)

    state_metric_summary = update_state_metric_fields(nodes, edges, claims)
    state_task_object_link_count = materialize_state_task_object_links(nodes, edges, claims)
    edges = dedupe_edges(edges)
    warnings = validate_graph(nodes, edges)
    node_rows = sorted(nodes.values(), key=lambda item: (str(item.get("node_type") or ""), node_id(item)))
    edge_rows = sorted(edges, key=lambda item: (str(item.get("type") or ""), str(item.get("from") or ""), str(item.get("to") or "")))
    summary = {
        "topic_id": topic_id,
        "event_count": len(events),
        "node_count": len(node_rows),
        "edge_count": len(edge_rows),
        "node_counts": graph_node_counts(nodes),
        "edge_counts": graph_edge_counts(edges),
        "claim_count": sum(1 for node in node_rows if node.get("node_type") == "Claim"),
        "state_facet_count": sum(1 for node in node_rows if node.get("node_type") == "StateFacet"),
        "claim_enriched": claim_enriched,
        "claim_missing_event": claim_missing_event,
        "claim_time_roles": dict(Counter(str(claim.get("time_role") or "None") for claim in claims.values()).most_common()),
        "claim_time_value_sources": dict(Counter(str(claim.get("time_value_source") or "None") for claim in claims.values()).most_common()),
        "claim_metric_types": dict(Counter(str(claim.get("metric_type") or "None") for claim in claims.values()).most_common()),
        "claim_metric_units": dict(Counter(str(claim.get("metric_unit") or "None") for claim in claims.values()).most_common()),
        "task_object_scope_count": sum(
            1
            for node in node_rows
            if node.get("node_type") == "Entity/Scope" and node.get("scope_type") == "task_object"
        ),
        "state_task_object_link_count": state_task_object_link_count,
        "responsibility_link_count": responsibility_link_count,
        "top_task_objects": dict(
            Counter(
                str(node.get("label") or "")
                for node in node_rows
                if node.get("node_type") == "Entity/Scope" and node.get("scope_type") == "task_object"
            ).most_common(20)
        ),
        "time_roles": dict(
            Counter(str(node.get("time_role") or "") for node in node_rows if node.get("node_type") == "Time").most_common()
        ),
        **state_metric_summary,
        "warnings": warnings,
    }
    return node_rows, edge_rows, summary


def write_enriched_graph(
    topic_id: str,
    data_root: Path,
    input_graph_dir: Path,
    output_graph_dir: Path,
    node_rows: Sequence[Mapping[str, Any]],
    edge_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> None:
    output_graph_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = input_graph_dir / "manifest.json"
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest = dict(old_manifest)
    manifest.update(
        {
            "benchmark": "EverMemBench",
            "topic_id": topic_id,
            "schema_version": "evermembench-sts-topic-graph-v5-responsibility",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data_root": str(data_root),
            "source_files": [str(data_root / topic_id / "dialogue.json"), str(input_graph_dir)],
            "leakage_policy": {
                "graph_build_inputs": ["dialogue.json", "existing_graph_nodes_edges"],
                "qa_loaded": False,
                "gold_fields_loaded": [],
                "notes": "This enrichment does not read qa_*.json, A, R, options, or evidence spans.",
            },
            "enrichment": {
                "source_graph_dir": str(input_graph_dir),
                "enriched_at": datetime.now(timezone.utc).isoformat(),
                "notes": "Existing claims were enriched with explicit time-source annotations, effort metric fields, task_object scope links, and owner-derived person-task responsibility links; old HAS_TIME/task_object/responsibility edges were rebuilt.",
            },
            "summary": dict(summary),
        }
    )
    write_jsonl(output_graph_dir / "nodes.jsonl", node_rows)
    write_jsonl(output_graph_dir / "edges.jsonl", edge_rows)
    (output_graph_dir / "graph_summary.json").write_text(json_dump(summary), encoding="utf-8")
    (output_graph_dir / "manifest.json").write_text(json_dump(manifest), encoding="utf-8")


def main() -> None:
    args = parse_args()
    node_rows, edge_rows, summary = enrich_graph(args.topic, args.data_root, args.input_graph_dir)
    write_enriched_graph(
        args.topic,
        args.data_root,
        args.input_graph_dir,
        args.output_graph_dir,
        node_rows,
        edge_rows,
        summary,
    )
    print(
        json.dumps(
            {
                "output_graph_dir": str(args.output_graph_dir),
                "node_count": summary["node_count"],
                "edge_count": summary["edge_count"],
                "task_object_scope_count": summary.get("task_object_scope_count"),
                "responsibility_link_count": summary.get("responsibility_link_count"),
                "state_task_object_link_count": summary.get("state_task_object_link_count"),
                "claim_time_value_sources": summary["claim_time_value_sources"],
                "claim_metric_types": summary["claim_metric_types"],
                "warnings": len(summary["warnings"]),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

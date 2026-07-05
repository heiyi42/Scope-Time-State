from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.neo4j_store import (
    DEFAULT_METHOD,
    Neo4jGraphStore,
    graph_files,
)
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.graph_store import load_graph
from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_retriever import StatePacketGraphRetriever


DEFAULT_GRAPH_DIR = Path(__file__).resolve().parent / "prebuilt_llm_kg_graph_v2_stability_first" / "artifacts" / "graphs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate JSON graph artifacts against Neo4j-loaded subgraphs.")
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--question-ids", nargs="+", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--method", default=DEFAULT_METHOD)
    parser.add_argument("--compare-state-packet", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def canonical(value: object) -> object:
    if isinstance(value, dict):
        return {key: canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return value


def main() -> int:
    args = parse_args()
    paths = graph_files(Path(args.graph_dir), args.question_types, args.question_ids)
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print("no graph artifacts selected", file=sys.stderr)
        return 2

    retriever = StatePacketGraphRetriever()
    rows = []
    failures = 0
    try:
        with Neo4jGraphStore.from_env(method=args.method) as store:
            for path in paths:
                question_id = path.name.removesuffix(".graph.json")
                json_graph = load_graph(path)
                neo4j_graph = store.fetch_graph(question_id)
                item = {
                    "question_id": question_id,
                    "question_type": path.parent.name,
                    "json_nodes": json_graph.number_of_nodes(),
                    "json_edges": json_graph.number_of_edges(),
                    "neo4j_nodes": neo4j_graph.number_of_nodes(),
                    "neo4j_edges": neo4j_graph.number_of_edges(),
                    "counts_match": (
                        json_graph.number_of_nodes() == neo4j_graph.number_of_nodes()
                        and json_graph.number_of_edges() == neo4j_graph.number_of_edges()
                    ),
                    "state_packet_match": None,
                }
                if args.compare_state_packet and item["counts_match"]:
                    json_packet = canonical(retriever.retrieve_state_packet(json_graph))
                    neo4j_packet = canonical(retriever.retrieve_state_packet(neo4j_graph))
                    item["state_packet_match"] = json_packet == neo4j_packet
                if not item["counts_match"] or item["state_packet_match"] is False:
                    failures += 1
                rows.append(item)
                print(
                    f"[validate-neo4j] {question_id} counts_match={item['counts_match']} "
                    f"state_packet_match={item['state_packet_match']}",
                    flush=True,
                )
    except RuntimeError as exc:
        print(f"Neo4j error: {exc}", file=sys.stderr)
        return 2

    output = {
        "method": args.method,
        "graph_dir": args.graph_dir,
        "n_checked": len(rows),
        "n_failures": failures,
        "rows": rows,
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {output_path}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

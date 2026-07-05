from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.neo4j_store import (
    DEFAULT_METHOD,
    Neo4jGraphStore,
    graph_files,
)
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.graph_store import load_graph_artifact


DEFAULT_GRAPH_DIR = Path(__file__).resolve().parent / "prebuilt_llm_kg_graph_v2_stability_first" / "artifacts" / "graphs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import LongMemEval-S graph JSON artifacts into Neo4j.")
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--question-ids", nargs="+", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--method", default=DEFAULT_METHOD)
    parser.add_argument("--create-constraints", action="store_true")
    parser.add_argument("--clear-method-data", action="store_true")
    parser.add_argument("--clear-existing-question", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def artifact_summary(paths: list[Path]) -> tuple[Counter[str], int, int]:
    by_type: Counter[str] = Counter()
    nodes = 0
    edges = 0
    for path in paths:
        artifact = load_graph_artifact(path)
        metadata = artifact.get("metadata") or {}
        by_type[str(metadata.get("question_type") or path.parent.name)] += 1
        nodes += len(artifact.get("nodes") or [])
        edges += len(artifact.get("edges") or [])
    return by_type, nodes, edges


def main() -> int:
    args = parse_args()
    paths = graph_files(Path(args.graph_dir), args.question_types, args.question_ids)
    if args.limit:
        paths = paths[: args.limit]
    by_type, nodes, edges = artifact_summary(paths)
    print(
        f"[neo4j-import] graph_dir={args.graph_dir} files={len(paths)} "
        f"nodes={nodes} edges={edges} question_types={dict(by_type)}",
        flush=True,
    )
    if args.dry_run:
        return 0
    if not paths:
        print("no graph artifacts selected", file=sys.stderr)
        return 2

    with Neo4jGraphStore.from_env(method=args.method) as store:
        if args.create_constraints:
            store.create_constraints()
            print("[neo4j-import] constraints ready", flush=True)
        if args.clear_method_data:
            store.clear_method_data()
            print(f"[neo4j-import] cleared method data: {args.method}", flush=True)
        imported = []
        for index, path in enumerate(paths, start=1):
            item = store.import_artifact(path, clear_existing=args.clear_existing_question)
            imported.append(item)
            print(
                f"[neo4j-import] {index}/{len(paths)} {item['question_type']} / {item['question_id']} "
                f"nodes={item['nodes']} edges={item['edges']}",
                flush=True,
            )
    manifest_path = Path(args.graph_dir) / "neo4j_import_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "method": args.method,
                "graph_dir": args.graph_dir,
                "imported": imported,
                "n_imported": len(imported),
                "question_types": dict(by_type),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[neo4j-import] wrote {manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

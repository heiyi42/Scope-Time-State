from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[5]
BASELINE_DIR = Path(__file__).resolve().parents[1]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state.loader import DATA_DIR, GRAPH_OUTPUT_DIR
from pipeline.external.sts_v2.schema import SCHEMA_VERSION


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class RankedEvent:
    event_id: str
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe EverMemBench topic QA queries against a built topic graph.")
    parser.add_argument("--topic", default="01")
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument(
        "--graph-dir",
        type=Path,
        default=GRAPH_OUTPUT_DIR / "evermembench_topic_graph_v2_state_merge/01",
        help="Directory containing nodes.jsonl and edges.jsonl for one topic.",
    )
    parser.add_argument("--mode", choices=("event_text", "graph_context"), default="graph_context")
    parser.add_argument("--include-options", action="store_true", help="Append MC option text to query text.")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSONL rows with ranked event ids.")
    return parser.parse_args()


def tokenize(text: str) -> List[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


class BM25Index:
    def __init__(self, doc_ids: Sequence[str], documents: Sequence[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.doc_ids = list(doc_ids)
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize(document) for document in documents]
        self.doc_lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.doc_lengths) / max(1, len(self.doc_lengths))
        self.postings: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        for index, tokens in enumerate(self.doc_tokens):
            for token, count in Counter(tokens).items():
                self.postings[token].append((index, count))
        doc_count = max(1, len(self.doc_ids))
        self.idf = {
            token: math.log(1.0 + (doc_count - len(postings) + 0.5) / (len(postings) + 0.5))
            for token, postings in self.postings.items()
        }

    def search(
        self,
        query: str,
        top_k: int,
        allowed_doc_ids: Optional[Sequence[str]] = None,
    ) -> List[RankedEvent]:
        allowed = (
            None
            if allowed_doc_ids is None
            else {str(doc_id) for doc_id in allowed_doc_ids if doc_id}
        )
        scores: Dict[int, float] = defaultdict(float)
        for token in Counter(tokenize(query)):
            idf = self.idf.get(token)
            if idf is None:
                continue
            for doc_index, tf in self.postings[token]:
                if allowed is not None and self.doc_ids[doc_index] not in allowed:
                    continue
                length = self.doc_lengths[doc_index]
                denom = tf + self.k1 * (1.0 - self.b + self.b * length / max(1e-9, self.avgdl))
                scores[doc_index] += idf * (tf * (self.k1 + 1.0) / denom)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], self.doc_ids[item[0]]))[:top_k]
        return [RankedEvent(self.doc_ids[index], score) for index, score in ranked]


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def compact_parts(*parts: Any) -> str:
    return " ".join(str(part) for part in parts if part is not None and str(part).strip())


def load_graph_documents(graph_dir: Path, mode: str) -> Tuple[List[str], List[str], Dict[str, Dict[str, Any]]]:
    manifest_path = graph_dir / "manifest.json"
    nodes_path = graph_dir / "nodes.jsonl"
    edges_path = graph_dir / "edges.jsonl"
    if not manifest_path.exists() or not nodes_path.exists() or not edges_path.exists():
        raise FileNotFoundError(f"missing graph files under {graph_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = str(manifest.get("schema_version") or "")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"incompatible STS v2 graph schema: expected {SCHEMA_VERSION}, got {schema_version or '<missing>'}"
        )

    events: Dict[str, Dict[str, Any]] = {}
    claims: Dict[str, Dict[str, Any]] = {}
    state_facets: Dict[str, Dict[str, Any]] = {}
    for node in read_jsonl(nodes_path):
        node_type = node.get("node_type")
        if node_type == "Episode/Event":
            events[str(node["event_id"])] = node
        elif node_type == "Claim":
            claims[str(node["claim_id"])] = node
        elif node_type == "StateFacet":
            facet_id = str(node.get("facet_id") or node.get("state_facet_id") or "")
            if facet_id:
                state_facets[facet_id] = node

    asserted_claims: Dict[str, List[str]] = defaultdict(list)
    supported_states_by_claim: Dict[str, List[str]] = defaultdict(list)
    for edge in read_jsonl(edges_path):
        edge_type = edge.get("type")
        if edge_type == "ASSERTS":
            asserted_claims[str(edge["from"])].append(str(edge["to"]))
        elif edge_type == "SUPPORTS":
            supported_states_by_claim[str(edge["from"])].append(str(edge["to"]))

    doc_ids: List[str] = []
    documents: List[str] = []
    for event_id in sorted(events):
        event = events[event_id]
        parts = [
            event.get("date"),
            event.get("group"),
            event.get("speaker"),
            event.get("text"),
        ]
        if mode == "graph_context":
            for claim_id in asserted_claims.get(event_id, []):
                claim = claims.get(claim_id)
                if not claim:
                    continue
                parts.append(
                    compact_parts(
                        claim.get("subject"),
                        claim.get("predicate"),
                        claim.get("object"),
                        claim.get("facet_key"),
                        claim.get("value"),
                        claim.get("scope_hint"),
                        claim.get("time_role"),
                        claim.get("phase_role"),
                    )
                )
                for state_id in supported_states_by_claim.get(claim_id, []):
                    state = state_facets.get(state_id)
                    if state:
                        parts.append(compact_parts(state.get("subject"), state.get("facet_key"), state.get("value")))
        doc_ids.append(event_id)
        documents.append(compact_parts(*parts))
    return doc_ids, documents, events


def expand_message_index(value: Any) -> List[int]:
    if value is None:
        return []
    result: List[int] = []
    for part in str(value).split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            try:
                start = int(left.strip())
                end = int(right.strip())
            except ValueError:
                continue
            result.extend(range(min(start, end), max(start, end) + 1))
        else:
            try:
                result.append(int(item))
            except ValueError:
                continue
    return result


def gold_event_ids(qa_item: Mapping[str, Any]) -> Set[str]:
    topic_id = str(qa_item.get("topic_id") or "")
    gold: Set[str] = set()
    for evidence in qa_item.get("R") or []:
        if not isinstance(evidence, Mapping):
            continue
        date = str(evidence.get("date") or "")
        group = str(evidence.get("group") or "")
        for message_index in expand_message_index(evidence.get("message_index")):
            gold.add(f"{topic_id}:{date}:{group}:{message_index}")
    return gold


def qa_query_text(qa_item: Mapping[str, Any], include_options: bool) -> str:
    parts = [qa_item.get("Q")]
    if include_options and isinstance(qa_item.get("options"), Mapping):
        for key in sorted(qa_item["options"]):
            parts.append(f"{key}: {qa_item['options'][key]}")
    return compact_parts(*parts)


def group_key(qa_id: str) -> str:
    return qa_id.split("_Top", 1)[0] if "_Top" in qa_id else qa_id.split("_", 1)[0]


def evaluate_rows(rows: Sequence[Dict[str, Any]], cutoffs: Sequence[int]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"n": len(rows)}
    for cutoff in cutoffs:
        hit_values = [1.0 if row[f"hit_at_{cutoff}"] else 0.0 for row in rows]
        recall_values = [row[f"recall_at_{cutoff}"] for row in rows]
        summary[f"hit_at_{cutoff}"] = round(sum(hit_values) / max(1, len(hit_values)), 4)
        summary[f"recall_at_{cutoff}"] = round(sum(recall_values) / max(1, len(recall_values)), 4)
    mrr_values = [row["reciprocal_rank"] for row in rows]
    summary["mrr"] = round(sum(mrr_values) / max(1, len(mrr_values)), 4)
    return summary


def main() -> None:
    args = parse_args()
    qa_path = args.qa_path or DATA_DIR / args.topic / f"qa_{args.topic}.json"
    qa_items = json.loads(qa_path.read_text(encoding="utf-8"))
    if args.limit:
        qa_items = qa_items[: args.limit]

    _, documents, events = load_graph_documents(args.graph_dir, args.mode)
    doc_ids = sorted(events)
    index = BM25Index(doc_ids, documents)

    cutoffs = tuple(sorted({1, 5, 10, args.top_k}))
    rows: List[Dict[str, Any]] = []
    for item in qa_items:
        gold = gold_event_ids(item)
        ranked = index.search(qa_query_text(item, args.include_options), max(cutoffs))
        ranked_ids = [event.event_id for event in ranked]
        first_rank: Optional[int] = None
        for rank, event_id in enumerate(ranked_ids, start=1):
            if event_id in gold:
                first_rank = rank
                break
        row: Dict[str, Any] = {
            "id": item.get("id"),
            "group": group_key(str(item.get("id") or "")),
            "gold_count": len(gold),
            "top_events": ranked_ids[: args.top_k],
            "reciprocal_rank": round(1.0 / first_rank, 6) if first_rank else 0.0,
        }
        for cutoff in cutoffs:
            predicted = set(ranked_ids[:cutoff])
            hits = predicted & gold
            row[f"hit_at_{cutoff}"] = bool(hits)
            row[f"recall_at_{cutoff}"] = round(len(hits) / max(1, len(gold)), 6)
        rows.append(row)

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["group"])].append(row)

    result = {
        "topic_id": args.topic,
        "qa_path": str(qa_path),
        "graph_dir": str(args.graph_dir),
        "mode": args.mode,
        "include_options": args.include_options,
        "top_k": args.top_k,
        "overall": evaluate_rows(rows, cutoffs),
        "by_group": {key: evaluate_rows(value, cutoffs) for key, value in sorted(grouped.items())},
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

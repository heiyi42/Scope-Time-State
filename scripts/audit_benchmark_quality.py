from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import os
from pathlib import Path
import re
import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from v1_common import DEFAULT_V1_3_DIR, PROJECT_DIR, read_json, write_json


GENERIC_MARKERS = [
    "旁路日志采样",
    "轻量复查",
    "旧完成状态",
    "主线阻塞",
    "acceptance",
    "approval",
]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def scope_pattern(scope_ids: Sequence[str]) -> re.Pattern[str] | None:
    if not scope_ids:
        return None
    return re.compile("|".join(re.escape(scope_id) for scope_id in sorted(scope_ids, key=len, reverse=True)))


def normalize_text(value: str, scope_ids: Sequence[str]) -> str:
    pattern = scope_pattern(scope_ids)
    text = str(value)
    if pattern:
        text = pattern.sub("<scope>", text)
    text = re.sub(r"\d+", "<n>", text)
    text = re.sub(r"[，。；：、“”\"'`（）()\\[\\]{}<>《》]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def normalized_counter(values: Iterable[str], scope_ids: Sequence[str]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for value in values:
        counter[normalize_text(str(value), scope_ids)] += 1
    return counter


def slot_values(cases: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    values: List[Dict[str, str]] = []
    for case in cases:
        slots = case.get("gold_state_slots", {})
        if isinstance(slots, Mapping):
            for slot, value in slots.items():
                values.append(
                    {
                        "case_id": str(case.get("case_id", "")),
                        "scope_id": str(case.get("scope_id", "")),
                        "slot": str(slot),
                        "text": str(value),
                    }
                )
    return values


def top_over(counter: Counter[str], threshold: int) -> Dict[str, int]:
    return dict(sorted(((text, count) for text, count in counter.items() if count > threshold), key=lambda item: (-item[1], item[0])))


def scope_table(
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    event_counter: Counter[str],
    query_counter: Counter[str],
    scope_ids: Sequence[str],
    repeat_threshold: int,
) -> List[Dict[str, Any]]:
    events_by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    cases_by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_scope[str(event["scope_id"])].append(event)
    for case in cases:
        cases_by_scope[str(case["scope_id"])].append(case)
    rows: List[Dict[str, Any]] = []
    for scope_id in sorted(events_by_scope):
        scope_events = events_by_scope[scope_id]
        scope_cases = cases_by_scope.get(scope_id, [])
        rows.append(
            {
                "scope_id": scope_id,
                "events": len(scope_events),
                "generated_events": sum(str(event.get("event_id", "")).startswith("v13_") for event in scope_events),
                "events_over_repeat_threshold": sum(event_counter[normalize_text(str(event.get("content", "")), scope_ids)] > repeat_threshold for event in scope_events),
                "cases": len(scope_cases),
                "queries_over_repeat_threshold": sum(query_counter[normalize_text(str(case.get("query", "")), scope_ids)] > repeat_threshold for case in scope_cases),
            }
        )
    return rows


def char_ngram_counter(text: str, n: int) -> Counter[str]:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return Counter()
    if len(compact) <= n:
        return Counter({compact: 1})
    return Counter(compact[index : index + n] for index in range(len(compact) - n + 1))


def cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    numerator = sum(left[key] * right[key] for key in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def near_duplicate_pairs(
    items: Sequence[Mapping[str, str]],
    scope_ids: Sequence[str],
    threshold: float,
    ngram_size: int,
    max_pairs: int,
) -> List[Dict[str, Any]]:
    normalized_items: List[Dict[str, Any]] = []
    for item in items:
        normalized = normalize_text(str(item["text"]), scope_ids)
        normalized_items.append(
            {
                **item,
                "normalized_text": normalized,
                "ngrams": char_ngram_counter(normalized, ngram_size),
            }
        )

    pairs: List[Dict[str, Any]] = []
    for left_index, left in enumerate(normalized_items):
        for right in normalized_items[left_index + 1 :]:
            if left["normalized_text"] == right["normalized_text"]:
                continue
            score = cosine_similarity(left["ngrams"], right["ngrams"])
            if score < threshold:
                continue
            pairs.append(
                {
                    "score": round(score, 4),
                    "left": {key: left[key] for key in left if key not in {"ngrams", "normalized_text"}},
                    "right": {key: right[key] for key in right if key not in {"ngrams", "normalized_text"}},
                    "left_normalized": left["normalized_text"],
                    "right_normalized": right["normalized_text"],
                    "cross_scope": left.get("scope_id") != right.get("scope_id"),
                }
            )
    pairs.sort(key=lambda pair: (-pair["score"], str(pair["left"].get("id", "")), str(pair["right"].get("id", ""))))
    return pairs[:max_pairs]


def embedding_near_duplicate_pairs(
    items: Sequence[Mapping[str, str]],
    scope_ids: Sequence[str],
    model_name: str,
    threshold: float,
    max_pairs: int,
) -> List[Dict[str, Any]]:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("embedding near-duplicate audit requires sentence-transformers and numpy") from exc

    normalized_items = [{**item, "normalized_text": normalize_text(str(item["text"]), scope_ids)} for item in items]
    if not normalized_items:
        return []
    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        [str(item["normalized_text"]) for item in normalized_items],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    matrix = np.asarray(embeddings)
    return embedding_pairs_from_matrix(normalized_items, matrix, threshold, max_pairs)


def embedding_pairs_from_matrix(
    normalized_items: Sequence[Mapping[str, Any]],
    matrix: Any,
    threshold: float,
    max_pairs: int,
) -> List[Dict[str, Any]]:
    import numpy as np

    pairs: List[Dict[str, Any]] = []
    for left_index, left in enumerate(normalized_items):
        for right_index in range(left_index + 1, len(normalized_items)):
            right = normalized_items[right_index]
            if left["normalized_text"] == right["normalized_text"]:
                continue
            score = float(np.dot(matrix[left_index], matrix[right_index]))
            if score < threshold:
                continue
            pairs.append(
                {
                    "score": round(score, 4),
                    "left": {key: left[key] for key in left if key != "normalized_text"},
                    "right": {key: right[key] for key in right if key != "normalized_text"},
                    "left_normalized": left["normalized_text"],
                    "right_normalized": right["normalized_text"],
                    "cross_scope": left.get("scope_id") != right.get("scope_id"),
                }
            )
    pairs.sort(key=lambda pair: (-pair["score"], str(pair["left"].get("id", "")), str(pair["right"].get("id", ""))))
    return pairs[:max_pairs]


def openai_embedding_matrix(
    texts: Sequence[str],
    model_name: str,
    batch_size: int,
    base_url: str | None,
) -> Any:
    try:
        import numpy as np
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI embedding audit requires openai and numpy") from exc

    if batch_size <= 0:
        raise ValueError("--openai-embedding-batch-size must be positive")
    api_key = env_first("OPENAI_EMBEDDING_API_KEY", "OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("missing OPENAI_EMBEDDING_API_KEY or OPENAI_API_KEY for OpenAI embedding audit")
    resolved_base_url = base_url or env_first(
        "OPENAI_EMBEDDING_BASE_URL",
        "OPENAI_EMBEDDING_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
    )
    client_kwargs = {"api_key": api_key}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url
    client = OpenAI(**client_kwargs)

    vectors: List[List[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        response = client.embeddings.create(model=model_name, input=batch)
        for item in sorted(response.data, key=lambda value: value.index):
            vectors.append(item.embedding)
    matrix = np.asarray(vectors, dtype="float32")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def openai_embedding_near_duplicate_pairs(
    items: Sequence[Mapping[str, str]],
    scope_ids: Sequence[str],
    model_name: str,
    threshold: float,
    max_pairs: int,
    batch_size: int,
    base_url: str | None,
) -> List[Dict[str, Any]]:
    normalized_items = [{**item, "normalized_text": normalize_text(str(item["text"]), scope_ids)} for item in items]
    if not normalized_items:
        return []
    matrix = openai_embedding_matrix(
        [str(item["normalized_text"]) for item in normalized_items],
        model_name,
        batch_size,
        base_url,
    )
    return embedding_pairs_from_matrix(normalized_items, matrix, threshold, max_pairs)


def text_items(
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
) -> Dict[str, List[Dict[str, str]]]:
    return {
        "event": [
            {
                "id": str(event.get("event_id", "")),
                "scope_id": str(event.get("scope_id", "")),
                "event_type": str(event.get("event_type", "")),
                "text": str(event.get("content", "")),
            }
            for event in events
        ],
        "query": [
            {
                "id": str(case.get("case_id", "")),
                "scope_id": str(case.get("scope_id", "")),
                "operation": str(case.get("operation", "")),
                "operation_subtype": str(case.get("operation_subtype", "")),
                "text": str(case.get("query", "")),
            }
            for case in cases
        ],
        "slot_value": [
            {
                "id": f"{slot['case_id']}::{slot['slot']}",
                "case_id": slot["case_id"],
                "scope_id": slot["scope_id"],
                "slot": slot["slot"],
                "text": slot["text"],
            }
            for slot in slot_values(cases)
        ],
    }


def semantic_duplicate_audit(
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    scope_ids: Sequence[str],
    event_threshold: float,
    query_threshold: float,
    slot_threshold: float,
    ngram_size: int,
    max_pairs: int,
) -> Dict[str, Any]:
    items = text_items(events, cases)
    event_pairs = near_duplicate_pairs(items["event"], scope_ids, event_threshold, ngram_size, max_pairs)
    query_pairs = near_duplicate_pairs(items["query"], scope_ids, query_threshold, ngram_size, max_pairs)
    slot_pairs = near_duplicate_pairs(items["slot_value"], scope_ids, slot_threshold, ngram_size, max_pairs)
    warnings = []
    if event_pairs:
        warnings.append(f"semantic event near-duplicates above {event_threshold}: {len(event_pairs)} top pairs")
    if query_pairs:
        warnings.append(f"semantic query near-duplicates above {query_threshold}: {len(query_pairs)} top pairs")
    if slot_pairs:
        warnings.append(f"semantic slot-value near-duplicates above {slot_threshold}: {len(slot_pairs)} top pairs")
    return {
        "method": "char_ngram_cosine_lexical_proxy",
        "interpretation": "This is a deterministic lexical near-duplicate screen for template-like wording, not a standalone semantic equivalence proof.",
        "thresholds": {
            "event": event_threshold,
            "query": query_threshold,
            "slot_value": slot_threshold,
            "ngram_size": ngram_size,
        },
        "max_pairs_per_kind": max_pairs,
        "counts": {
            "event_pairs": len(event_pairs),
            "query_pairs": len(query_pairs),
            "slot_value_pairs": len(slot_pairs),
        },
        "event_pairs": event_pairs,
        "query_pairs": query_pairs,
        "slot_value_pairs": slot_pairs,
        "warnings": warnings,
    }


def embedding_duplicate_audit(
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    scope_ids: Sequence[str],
    model_name: str,
    event_threshold: float,
    query_threshold: float,
    slot_threshold: float,
    max_pairs: int,
) -> Dict[str, Any]:
    items = text_items(events, cases)
    event_pairs = embedding_near_duplicate_pairs(items["event"], scope_ids, model_name, event_threshold, max_pairs)
    query_pairs = embedding_near_duplicate_pairs(items["query"], scope_ids, model_name, query_threshold, max_pairs)
    slot_pairs = embedding_near_duplicate_pairs(items["slot_value"], scope_ids, model_name, slot_threshold, max_pairs)
    warnings = []
    if event_pairs:
        warnings.append(f"embedding event near-duplicates above {event_threshold}: {len(event_pairs)} top pairs")
    if query_pairs:
        warnings.append(f"embedding query near-duplicates above {query_threshold}: {len(query_pairs)} top pairs")
    if slot_pairs:
        warnings.append(f"embedding slot-value near-duplicates above {slot_threshold}: {len(slot_pairs)} top pairs")
    return {
        "method": "sentence_transformer_embedding_cosine",
        "model": model_name,
        "thresholds": {
            "event": event_threshold,
            "query": query_threshold,
            "slot_value": slot_threshold,
        },
        "max_pairs_per_kind": max_pairs,
        "counts": {
            "event_pairs": len(event_pairs),
            "query_pairs": len(query_pairs),
            "slot_value_pairs": len(slot_pairs),
        },
        "event_pairs": event_pairs,
        "query_pairs": query_pairs,
        "slot_value_pairs": slot_pairs,
        "warnings": warnings,
    }


def openai_embedding_duplicate_audit(
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    scope_ids: Sequence[str],
    model_name: str,
    event_threshold: float,
    query_threshold: float,
    slot_threshold: float,
    max_pairs: int,
    batch_size: int,
    base_url: str | None,
) -> Dict[str, Any]:
    items = text_items(events, cases)
    event_pairs = openai_embedding_near_duplicate_pairs(items["event"], scope_ids, model_name, event_threshold, max_pairs, batch_size, base_url)
    query_pairs = openai_embedding_near_duplicate_pairs(items["query"], scope_ids, model_name, query_threshold, max_pairs, batch_size, base_url)
    slot_pairs = openai_embedding_near_duplicate_pairs(items["slot_value"], scope_ids, model_name, slot_threshold, max_pairs, batch_size, base_url)
    warnings = []
    if event_pairs:
        warnings.append(f"OpenAI embedding event near-duplicates above {event_threshold}: {len(event_pairs)} top pairs")
    if query_pairs:
        warnings.append(f"OpenAI embedding query near-duplicates above {query_threshold}: {len(query_pairs)} top pairs")
    if slot_pairs:
        warnings.append(f"OpenAI embedding slot-value near-duplicates above {slot_threshold}: {len(slot_pairs)} top pairs")
    return {
        "method": "openai_embedding_cosine_semantic_screen",
        "interpretation": "OpenAI embeddings provide a semantic near-duplicate screen for manual review; flagged pairs are not automatically removed without task-level inspection.",
        "model": model_name,
        "thresholds": {
            "event": event_threshold,
            "query": query_threshold,
            "slot_value": slot_threshold,
        },
        "max_pairs_per_kind": max_pairs,
        "counts": {
            "event_pairs": len(event_pairs),
            "query_pairs": len(query_pairs),
            "slot_value_pairs": len(slot_pairs),
        },
        "event_pairs": event_pairs,
        "query_pairs": query_pairs,
        "slot_value_pairs": slot_pairs,
        "warnings": warnings,
    }


def audit(
    v1_dir: Path,
    max_event_repeat: int,
    max_query_repeat: int,
    max_slot_repeat: int,
    semantic_event_threshold: float,
    semantic_query_threshold: float,
    semantic_slot_threshold: float,
    semantic_ngram_size: int,
    semantic_max_pairs: int,
    include_semantic: bool,
    embedding_model: str | None,
    embedding_event_threshold: float,
    embedding_query_threshold: float,
    embedding_slot_threshold: float,
    embedding_max_pairs: int,
    openai_embedding_model: str | None,
    openai_embedding_event_threshold: float,
    openai_embedding_query_threshold: float,
    openai_embedding_slot_threshold: float,
    openai_embedding_max_pairs: int,
    openai_embedding_batch_size: int,
    openai_embedding_base_url: str | None,
) -> Dict[str, Any]:
    events = read_json(v1_dir / "events_raw.json")
    cases = read_json(v1_dir / "cases.json")
    scope_ids = sorted({str(event["scope_id"]) for event in events})
    event_counter = normalized_counter([str(event.get("content", "")) for event in events], scope_ids)
    query_counter = normalized_counter([str(case.get("query", "")) for case in cases], scope_ids)
    slot_counter = normalized_counter([slot["text"] for slot in slot_values(cases)], scope_ids)
    combined_text = "\n".join(
        [str(event.get("content", "")) for event in events]
        + [str(case.get("query", "")) for case in cases]
        + [slot["text"] for slot in slot_values(cases)]
    )
    warnings = []
    event_repeats = top_over(event_counter, max_event_repeat)
    query_repeats = top_over(query_counter, max_query_repeat)
    slot_repeats = top_over(slot_counter, max_slot_repeat)
    if event_repeats:
        warnings.append(f"event content repeats above {max_event_repeat}")
    if query_repeats:
        warnings.append(f"query repeats above {max_query_repeat}")
    if slot_repeats:
        warnings.append(f"gold slot value repeats above {max_slot_repeat}")
    marker_counts = {marker: combined_text.count(marker) for marker in GENERIC_MARKERS}
    leaked_generic_markers = {marker: count for marker, count in marker_counts.items() if count > 0}
    if leaked_generic_markers:
        warnings.append(f"generic/stale template markers remain: {leaked_generic_markers}")
    report = {
        "v1_dir": str(v1_dir),
        "events": len(events),
        "cases": len(cases),
        "scopes": len(scope_ids),
        "max_normalized_event_repeat": max(event_counter.values(), default=0),
        "max_normalized_query_repeat": max(query_counter.values(), default=0),
        "max_normalized_slot_value_repeat": max(slot_counter.values(), default=0),
        "event_repeats": event_repeats,
        "query_repeats": query_repeats,
        "slot_value_repeats": slot_repeats,
        "generic_marker_counts": marker_counts,
        "scope_table": scope_table(events, cases, event_counter, query_counter, scope_ids, max(max_event_repeat, max_query_repeat)),
        "warnings": warnings,
        "passed": not warnings,
    }
    if include_semantic:
        report["semantic_near_duplicates"] = semantic_duplicate_audit(
            events,
            cases,
            scope_ids,
            semantic_event_threshold,
            semantic_query_threshold,
            semantic_slot_threshold,
            semantic_ngram_size,
            semantic_max_pairs,
        )
    if embedding_model:
        report["embedding_near_duplicates"] = embedding_duplicate_audit(
            events,
            cases,
            scope_ids,
            embedding_model,
            embedding_event_threshold,
            embedding_query_threshold,
            embedding_slot_threshold,
            embedding_max_pairs,
        )
    if openai_embedding_model:
        report["openai_embedding_near_duplicates"] = openai_embedding_duplicate_audit(
            events,
            cases,
            scope_ids,
            openai_embedding_model,
            openai_embedding_event_threshold,
            openai_embedding_query_threshold,
            openai_embedding_slot_threshold,
            openai_embedding_max_pairs,
            openai_embedding_batch_size,
            openai_embedding_base_url,
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit benchmark text diversity and stale template leakage.")
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1_3_DIR)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-event-repeat", type=int, default=8)
    parser.add_argument("--max-query-repeat", type=int, default=8)
    parser.add_argument("--max-slot-repeat", type=int, default=8)
    parser.add_argument("--semantic-out", type=Path)
    parser.add_argument("--semantic-event-threshold", type=float, default=0.9)
    parser.add_argument("--semantic-query-threshold", type=float, default=0.85)
    parser.add_argument("--semantic-slot-threshold", type=float, default=0.88)
    parser.add_argument("--semantic-ngram-size", type=int, default=3)
    parser.add_argument("--semantic-max-pairs", type=int, default=50)
    parser.add_argument("--skip-semantic", action="store_true")
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--embedding-out", type=Path)
    parser.add_argument("--embedding-event-threshold", type=float, default=0.92)
    parser.add_argument("--embedding-query-threshold", type=float, default=0.9)
    parser.add_argument("--embedding-slot-threshold", type=float, default=0.9)
    parser.add_argument("--embedding-max-pairs", type=int, default=50)
    parser.add_argument("--openai-embedding-model", default=None)
    parser.add_argument("--openai-embedding-out", type=Path)
    parser.add_argument("--openai-embedding-base-url", default=None)
    parser.add_argument("--openai-embedding-event-threshold", type=float, default=0.92)
    parser.add_argument("--openai-embedding-query-threshold", type=float, default=0.9)
    parser.add_argument("--openai-embedding-slot-threshold", type=float, default=0.9)
    parser.add_argument("--openai-embedding-max-pairs", type=int, default=50)
    parser.add_argument("--openai-embedding-batch-size", type=int, default=96)
    parser.add_argument("--env-file", type=Path, default=PROJECT_DIR / ".env")
    parser.add_argument("--fail-on-warnings", action="store_true")
    args = parser.parse_args()

    load_env_file(args.env_file)
    report = audit(
        args.v1_dir,
        args.max_event_repeat,
        args.max_query_repeat,
        args.max_slot_repeat,
        args.semantic_event_threshold,
        args.semantic_query_threshold,
        args.semantic_slot_threshold,
        args.semantic_ngram_size,
        args.semantic_max_pairs,
        not args.skip_semantic,
        args.embedding_model,
        args.embedding_event_threshold,
        args.embedding_query_threshold,
        args.embedding_slot_threshold,
        args.embedding_max_pairs,
        args.openai_embedding_model,
        args.openai_embedding_event_threshold,
        args.openai_embedding_query_threshold,
        args.openai_embedding_slot_threshold,
        args.openai_embedding_max_pairs,
        args.openai_embedding_batch_size,
        args.openai_embedding_base_url,
    )
    if args.out:
        write_json(args.out, report)
    if args.semantic_out and "semantic_near_duplicates" in report:
        write_json(args.semantic_out, report["semantic_near_duplicates"])
    if args.embedding_out and "embedding_near_duplicates" in report:
        write_json(args.embedding_out, report["embedding_near_duplicates"])
    if args.openai_embedding_out and "openai_embedding_near_duplicates" in report:
        write_json(args.openai_embedding_out, report["openai_embedding_near_duplicates"])
    print(f"passed={report['passed']}")
    print(f"max_event_repeat={report['max_normalized_event_repeat']}")
    print(f"max_query_repeat={report['max_normalized_query_repeat']}")
    print(f"max_slot_repeat={report['max_normalized_slot_value_repeat']}")
    print(f"generic_marker_counts={report['generic_marker_counts']}")
    semantic = report.get("semantic_near_duplicates")
    if isinstance(semantic, dict):
        print(f"semantic_counts={semantic['counts']}")
        if semantic["warnings"]:
            print("semantic warnings:")
            for warning in semantic["warnings"]:
                print(f"- {warning}")
    embedding = report.get("embedding_near_duplicates")
    if isinstance(embedding, dict):
        print(f"embedding_counts={embedding['counts']}")
        if embedding["warnings"]:
            print("embedding warnings:")
            for warning in embedding["warnings"]:
                print(f"- {warning}")
    openai_embedding = report.get("openai_embedding_near_duplicates")
    if isinstance(openai_embedding, dict):
        print(f"openai_embedding_counts={openai_embedding['counts']}")
        if openai_embedding["warnings"]:
            print("openai embedding warnings:")
            for warning in openai_embedding["warnings"]:
                print(f"- {warning}")
    if report["warnings"]:
        print("warnings:")
        for warning in report["warnings"]:
            print(f"- {warning}")
    return 1 if args.fail_on_warnings and report["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

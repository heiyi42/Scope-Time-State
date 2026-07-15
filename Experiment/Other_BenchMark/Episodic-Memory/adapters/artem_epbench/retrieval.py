"""EPBench Long Book adapter for the official ARTEM retrieval implementation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from config import BOOK_ID, DEFAULT_OUTPUT_ROOT, OFFICIAL_ARTEM_DIR, book_output_dir


if str(OFFICIAL_ARTEM_DIR) not in sys.path:
    sys.path.insert(0, str(OFFICIAL_ARTEM_DIR))

from eventNormalizer import EventNormalizer  # noqa: E402
from eventProcessor import process_event_data  # noqa: E402
from eventRetriever import (  # noqa: E402
    convert_np,
    fill_empty_fields,
    run_event_retrieval_pipeline,
    save_retrieval_results,
)


PAPER_VIGILANCE = [1.0, 0.99, 0.99, 0.98]


def _event_key(event: dict) -> tuple[str, str, str, str]:
    return (
        json.dumps(event.get("time", []), ensure_ascii=False, sort_keys=True),
        str(event.get("spaces", "")),
        str(event.get("entities", "")),
        str(event.get("content", "")),
    )


def restore_post_entities(result: dict, formatted_events: list[dict]) -> None:
    """Restore the field dropped by the official clean_event_data serializer."""
    post_entities_by_event = {
        _event_key(event): event.get("post_entities", []) for event in formatted_events
    }
    event_list_keys = (
        "top_k_events_time_sorted",
        "top_k_events_match_sorted",
        "all_vigilant_events_time_sorted",
        "all_vigilant_events_match_sorted",
    )
    for query_row in result.get("retrieval_results", []):
        query_results = query_row.get("results", {})
        for list_key in event_list_keys:
            for event in query_results.get(list_key, []):
                event["post_entities"] = post_entities_by_event.get(_event_key(event), [])
        highest = query_results.get("highest_scoring_event")
        if isinstance(highest, dict):
            highest["post_entities"] = post_entities_by_event.get(_event_key(highest), [])


def run_epbench_retrieval(
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    limit_questions: int = 686,
    question_offset: int = 0,
    max_retrievals: int = 20,
) -> Path:
    """Prepare four channels and call the unmodified official ARTEM retriever."""
    if question_offset < 0 or question_offset >= 686:
        raise ValueError("question_offset must be in [0, 685]")
    if limit_questions <= 0:
        raise ValueError("limit_questions must be positive")

    book_dir = book_output_dir(output_root)
    qa_path = book_dir / f"qa_book{BOOK_ID}.json"
    extracted_path = book_dir / f"extracted_features_book{BOOK_ID}.json"
    formatted_path = book_dir / f"formatted_extracted_features_book{BOOK_ID}.json"
    vectorized_path = book_dir / f"vectorized_features_book{BOOK_ID}.json"
    stats_path = book_dir / "normalization_stats.json"
    network_path = book_dir / "fusionart_network.json"
    retrieval_path = book_dir / f"match_based_retrieval_results_book{BOOK_ID}.json"

    missing = [path for path in (qa_path, extracted_path) if not path.is_file()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"ARTEM adapter inputs are incomplete:\n{formatted}")

    process_event_data(str(extracted_path), str(formatted_path))
    with formatted_path.open("r", encoding="utf-8") as stream:
        text_events = fill_empty_fields(json.load(stream))

    normalizer = EventNormalizer(method="min_max_per_vector")
    vectorized_events = json.loads(json.dumps(text_events))
    for field in ("spaces", "entities", "content"):
        normalizer.normalize_text_field(vectorized_events, field)
    normalizer.normalize_time_field(vectorized_events, "time")
    normalizer.save_stats(str(stats_path))
    with vectorized_path.open("w", encoding="utf-8") as stream:
        json.dump(vectorized_events, stream, indent=2, default=convert_np)
        stream.write("\n")

    with qa_path.open("r", encoding="utf-8") as stream:
        qa_rows = json.load(stream)
    selected_rows = qa_rows[question_offset : question_offset + limit_questions]
    selected_qa_path = book_dir / "qa_selected_for_retrieval.json"
    with selected_qa_path.open("w", encoding="utf-8") as stream:
        json.dump(selected_rows, stream, indent=2, ensure_ascii=False)
        stream.write("\n")

    result = run_event_retrieval_pipeline(
        str(selected_qa_path),
        vectorized_events,
        str(stats_path),
        str(formatted_path),
        n=len(selected_rows),
        vigilance_threshold=list(PAPER_VIGILANCE),
        max_retrievals=max_retrievals,
        network_path=str(network_path),
    )
    restore_post_entities(result, text_events)
    retrieval_rows = result.get("retrieval_results", [])
    if len(retrieval_rows) != len(selected_rows):
        raise RuntimeError(
            "Official ARTEM retriever did not emit one result per selected QA row: "
            f"expected {len(selected_rows)}, got {len(retrieval_rows)}"
        )
    for retrieval_row, qa_row in zip(retrieval_rows, selected_rows):
        retrieval_row["epbench_q_idx"] = retrieval_row.get("query_id")
        retrieval_row["query_id"] = qa_row["artem_query_index"]

    result["adapter_config"] = {
        "source": "EPBench Long Book, Claude 3.5 Sonnet, 196 validated chapters",
        "question_offset": question_offset,
        "question_count": len(selected_rows),
        "paper_vigilance": PAPER_VIGILANCE,
        "official_artem_dir": str(OFFICIAL_ARTEM_DIR),
    }
    save_retrieval_results(result, str(retrieval_path))
    return retrieval_path

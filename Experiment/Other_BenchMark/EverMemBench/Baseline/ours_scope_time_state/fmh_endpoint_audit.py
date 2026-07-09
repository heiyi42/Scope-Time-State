from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path
import re
import statistics
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[5]
BASELINE_DIR = Path(__file__).resolve().parents[1]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state.loader import DATA_DIR, RESULT_DIR
from ours_scope_time_state.qa_probe import expand_message_index, group_key


DEFAULT_RESULTS = (
    RESULT_DIR
    / "evermembench_topic_graph_llm_v5_subject_task_object"
    / "qa_eval_topic02_fmh_deepseek_v4_flash_v5.json"
)

MONTH_DATE_RE = re.compile(r"([A-Za-z]+ \d{1,2}, \d{4})")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit EverMemBench F_MH dual-endpoint date selection without changing gold data."
    )
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_gold_dates(answer: object) -> tuple[Optional[date], Optional[date]]:
    matches = MONTH_DATE_RE.findall(str(answer or ""))
    if len(matches) < 2:
        return None, None
    try:
        return (
            datetime.strptime(matches[0], "%B %d, %Y").date(),
            datetime.strptime(matches[1], "%B %d, %Y").date(),
        )
    except ValueError:
        return None, None


def parse_date(value: object) -> Optional[date]:
    text = str(value or "")
    match = ISO_DATE_RE.search(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        return None


def candidate_date(candidate: Mapping[str, Any]) -> Optional[date]:
    return parse_date(candidate.get("event_date")) or parse_date(candidate.get("time_value"))


def compact_text(value: object, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + " ...[truncated]"


def summarize_candidate(candidate: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(candidate, Mapping):
        return None
    content_trace = candidate.get("content_match_trace")
    if not isinstance(content_trace, Mapping):
        content_trace = {}
    return {
        "candidate_id": candidate.get("candidate_id"),
        "rank": candidate.get("rank"),
        "event_id": candidate.get("event_id"),
        "date": candidate_date(candidate).isoformat() if candidate_date(candidate) else None,
        "group": candidate.get("group"),
        "speaker": candidate.get("speaker"),
        "time_role": candidate.get("time_role"),
        "source": candidate.get("source"),
        "score": candidate.get("score"),
        "retrieval_channels": list(candidate.get("retrieval_channels") or []),
        "quality_reasons": list(candidate.get("quality_reasons") or []),
        "content_match": {
            "score": candidate.get("content_match_score"),
            "matched_terms": list(content_trace.get("matched_terms") or []),
            "missing_terms": list(content_trace.get("missing_terms") or []),
            "coverage": content_trace.get("coverage"),
        },
        "evidence_excerpt": compact_text(candidate.get("evidence_text")),
    }


def first_candidate_on_date(
    candidates: Sequence[Mapping[str, Any]],
    target: Optional[date],
) -> Optional[Mapping[str, Any]]:
    if target is None:
        return None
    matches = [candidate for candidate in candidates if candidate_date(candidate) == target]
    if not matches:
        return None
    return sorted(matches, key=lambda item: (int(item.get("rank") or 10**9), -float(item.get("score") or 0.0)))[0]


def qa_gold_date_groups(item: Mapping[str, Any], target: Optional[date]) -> Dict[str, Any]:
    if target is None:
        return {"groups": [], "event_count": 0}
    target_text = target.isoformat()
    groups: List[str] = []
    event_count = 0
    for evidence in item.get("R") or []:
        if not isinstance(evidence, Mapping) or str(evidence.get("date") or "") != target_text:
            continue
        group = str(evidence.get("group") or "")
        if group and group not in groups:
            groups.append(group)
        event_count += len(expand_message_index(evidence.get("message_index")))
    return {"groups": groups, "event_count": event_count}


def endpoint_error_kind(
    selected: Optional[Mapping[str, Any]],
    gold_date: Optional[date],
    gold_candidate: Optional[Mapping[str, Any]],
    gold_groups: Sequence[str],
) -> str:
    selected_date = candidate_date(selected or {})
    if gold_date is None:
        return "gold_date_unparseable"
    if selected_date == gold_date:
        return "date_exact"
    if gold_candidate is not None:
        return "gold_date_present_but_not_selected"
    selected_group = str((selected or {}).get("group") or "")
    if gold_groups and selected_group and selected_group not in set(gold_groups):
        return "gold_date_absent_and_selected_group_mismatch"
    return "gold_date_absent_from_endpoint_top_candidates"


def signed_day_diff(selected: Optional[date], gold: Optional[date]) -> Optional[int]:
    if selected is None or gold is None:
        return None
    return (selected - gold).days


def row_audit(row: Mapping[str, Any], qa_item: Mapping[str, Any]) -> Dict[str, Any]:
    gold_start, gold_end = parse_gold_dates(row.get("gold_answer"))
    trace = row.get("temporal_interval_trace")
    if not isinstance(trace, Mapping):
        trace = {}
    selected_pair = trace.get("selected_pair")
    if not isinstance(selected_pair, Mapping):
        selected_pair = {}
    selected_start = selected_pair.get("start") if isinstance(selected_pair.get("start"), Mapping) else None
    selected_end = selected_pair.get("end") if isinstance(selected_pair.get("end"), Mapping) else None

    antecedent = trace.get("antecedent") if isinstance(trace.get("antecedent"), Mapping) else {}
    consequent = trace.get("consequent") if isinstance(trace.get("consequent"), Mapping) else {}
    antecedent_top = [candidate for candidate in antecedent.get("top_candidates") or [] if isinstance(candidate, Mapping)]
    consequent_top = [candidate for candidate in consequent.get("top_candidates") or [] if isinstance(candidate, Mapping)]
    gold_start_candidate = first_candidate_on_date(antecedent_top, gold_start)
    gold_end_candidate = first_candidate_on_date(consequent_top, gold_end)

    selected_start_date = candidate_date(selected_start or {})
    selected_end_date = candidate_date(selected_end or {})
    gold_duration = (gold_end - gold_start).days if gold_start and gold_end else None
    selected_duration = (
        (selected_end_date - selected_start_date).days
        if selected_start_date and selected_end_date
        else None
    )
    start_groups = qa_gold_date_groups(qa_item, gold_start)
    end_groups = qa_gold_date_groups(qa_item, gold_end)

    start_error = endpoint_error_kind(
        selected_start,
        gold_start,
        gold_start_candidate,
        start_groups["groups"],
    )
    end_error = endpoint_error_kind(
        selected_end,
        gold_end,
        gold_end_candidate,
        end_groups["groups"],
    )
    if start_error == "date_exact" and end_error == "date_exact":
        date_match_category = "both_match"
    elif start_error == "date_exact":
        date_match_category = "start_match_only"
    elif end_error == "date_exact":
        date_match_category = "end_match_only"
    else:
        date_match_category = "neither_match"

    llm_selection = trace.get("llm_pair_selection")
    if not isinstance(llm_selection, Mapping):
        llm_selection = {}

    return {
        "id": row.get("id"),
        "is_correct": bool(row.get("is_correct")),
        "question": row.get("question"),
        "gold_answer": row.get("gold_answer"),
        "generated_answer": row.get("generated_answer"),
        "gold": {
            "start_date": gold_start.isoformat() if gold_start else None,
            "end_date": gold_end.isoformat() if gold_end else None,
            "duration_days": gold_duration,
            "start_groups": start_groups["groups"],
            "end_groups": end_groups["groups"],
            "start_event_count_on_date": start_groups["event_count"],
            "end_event_count_on_date": end_groups["event_count"],
        },
        "selected": {
            "start_date": selected_start_date.isoformat() if selected_start_date else None,
            "end_date": selected_end_date.isoformat() if selected_end_date else None,
            "duration_days": selected_duration,
            "duration_delta_days": (
                selected_duration - gold_duration
                if selected_duration is not None and gold_duration is not None
                else None
            ),
            "selection_mode": selected_pair.get("selection_mode"),
            "pair_score": selected_pair.get("pair_score"),
            "start": summarize_candidate(selected_start),
            "end": summarize_candidate(selected_end),
        },
        "endpoint_top_candidates": {
            "antecedent_count": len(antecedent_top),
            "consequent_count": len(consequent_top),
            "gold_start_in_antecedent_top": gold_start_candidate is not None,
            "gold_end_in_consequent_top": gold_end_candidate is not None,
            "gold_start_candidate": summarize_candidate(gold_start_candidate),
            "gold_end_candidate": summarize_candidate(gold_end_candidate),
        },
        "classification": {
            "date_match_category": date_match_category,
            "start_error_kind": start_error,
            "end_error_kind": end_error,
            "start_delta_days": signed_day_diff(selected_start_date, gold_start),
            "end_delta_days": signed_day_diff(selected_end_date, gold_end),
        },
        "retrieval_diagnostics": row.get("retrieval_diagnostics") or {},
        "llm_pair_selection": {
            "error": llm_selection.get("error"),
            "post_validation_error": llm_selection.get("post_validation_error"),
            "antecedent_prompt_candidate_count": llm_selection.get("antecedent_prompt_candidate_count"),
            "consequent_prompt_candidate_count": llm_selection.get("consequent_prompt_candidate_count"),
            "selected_antecedent": bool(llm_selection.get("selected_antecedent")),
            "selected_consequent": bool(llm_selection.get("selected_consequent")),
        },
    }


def mean(values: Iterable[Optional[int]]) -> Optional[float]:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return round(statistics.mean(numeric), 4)


def median(values: Iterable[Optional[int]]) -> Optional[float]:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return float(statistics.median(numeric))


def summarize(audited_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    total = len(audited_rows)
    correct = sum(1 for row in audited_rows if row.get("is_correct"))
    classification = Counter(str(row["classification"]["date_match_category"]) for row in audited_rows)
    start_errors = Counter(str(row["classification"]["start_error_kind"]) for row in audited_rows)
    end_errors = Counter(str(row["classification"]["end_error_kind"]) for row in audited_rows)
    selector_errors = Counter(
        str((row.get("llm_pair_selection") or {}).get("error") or "none")
        for row in audited_rows
    )
    selection_modes = Counter(str((row.get("selected") or {}).get("selection_mode") or "none") for row in audited_rows)
    retrieval = [row.get("retrieval_diagnostics") or {} for row in audited_rows]
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "date_match_category": dict(classification),
        "start_error_kind": dict(start_errors),
        "end_error_kind": dict(end_errors),
        "gold_start_in_antecedent_top": sum(
            1 for row in audited_rows if row["endpoint_top_candidates"]["gold_start_in_antecedent_top"]
        ),
        "gold_end_in_consequent_top": sum(
            1 for row in audited_rows if row["endpoint_top_candidates"]["gold_end_in_consequent_top"]
        ),
        "both_gold_dates_in_endpoint_top": sum(
            1
            for row in audited_rows
            if row["endpoint_top_candidates"]["gold_start_in_antecedent_top"]
            and row["endpoint_top_candidates"]["gold_end_in_consequent_top"]
        ),
        "gold_event_hit_at_context_k": sum(1 for item in retrieval if item.get("gold_hit_at_k")),
        "avg_gold_event_recall_at_context_k": round(
            sum(float(item.get("gold_recall_at_k") or 0.0) for item in retrieval) / total,
            4,
        )
        if total
        else 0.0,
        "avg_abs_start_delta_days": mean(
            abs(row["classification"]["start_delta_days"])
            if row["classification"]["start_delta_days"] is not None
            else None
            for row in audited_rows
        ),
        "median_abs_start_delta_days": median(
            abs(row["classification"]["start_delta_days"])
            if row["classification"]["start_delta_days"] is not None
            else None
            for row in audited_rows
        ),
        "avg_abs_end_delta_days": mean(
            abs(row["classification"]["end_delta_days"])
            if row["classification"]["end_delta_days"] is not None
            else None
            for row in audited_rows
        ),
        "median_abs_end_delta_days": median(
            abs(row["classification"]["end_delta_days"])
            if row["classification"]["end_delta_days"] is not None
            else None
            for row in audited_rows
        ),
        "avg_abs_duration_delta_days": mean(
            abs(row["selected"]["duration_delta_days"])
            if row["selected"]["duration_delta_days"] is not None
            else None
            for row in audited_rows
        ),
        "median_abs_duration_delta_days": median(
            abs(row["selected"]["duration_delta_days"])
            if row["selected"]["duration_delta_days"] is not None
            else None
            for row in audited_rows
        ),
        "selection_mode": dict(selection_modes),
        "llm_selector_error": dict(selector_errors),
    }


def default_qa_path(results: Mapping[str, Any]) -> Path:
    qa_path = results.get("qa_path")
    if qa_path:
        return Path(str(qa_path))
    topic = str(results.get("topic_id") or "02")
    return DATA_DIR / topic / f"qa_{topic}.json"


def main() -> None:
    args = parse_args()
    results = read_json(args.results)
    qa_path = args.qa_path or default_qa_path(results)
    qa_items = read_json(qa_path)
    qa_by_id = {str(item.get("id") or ""): item for item in qa_items if isinstance(item, Mapping)}
    rows = [
        row
        for row in results.get("rows", [])
        if isinstance(row, Mapping) and group_key(str(row.get("id") or "")) == "F_MH"
    ]
    missing = [str(row.get("id") or "") for row in rows if str(row.get("id") or "") not in qa_by_id]
    if missing:
        raise KeyError(f"missing QA gold rows for ids: {', '.join(missing[:5])}")

    audited_rows = [row_audit(row, qa_by_id[str(row.get("id") or "")]) for row in rows]
    report = {
        "results_path": str(args.results),
        "qa_path": str(qa_path),
        "topic_id": results.get("topic_id"),
        "summary": summarize(audited_rows),
        "rows": audited_rows,
    }
    output = args.output or args.results.with_suffix(".endpoint_audit.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"wrote {output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from v1_common import DEFAULT_V1_3_DIR, RAW_EVENT_FIELDS, normalize_id_list, read_json, write_json


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = PROJECT_DIR / "stamb_state_benchmark" / "annotation" / "v1_3_sample"


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def public_event(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: row.get(field) for field in RAW_EVENT_FIELDS}


def event_sort_key(row: Mapping[str, Any]) -> str:
    return str(row.get("updated_at") or row.get("mentioned_at") or row.get("occurred_at") or "")


def hard_negative_type_set(case: Mapping[str, Any]) -> set[str]:
    labels: set[str] = set()
    hard_negative_types = case.get("hard_negative_types", {})
    if isinstance(hard_negative_types, Mapping):
        for values in hard_negative_types.values():
            if isinstance(values, list):
                labels.update(str(value) for value in values)
    return labels


def add_first_matching(
    selected: List[Mapping[str, Any]],
    selected_ids: set[str],
    candidates: Sequence[Mapping[str, Any]],
    predicate,
) -> None:
    for case in candidates:
        case_id = str(case["case_id"])
        if case_id not in selected_ids and predicate(case):
            selected.append(case)
            selected_ids.add(case_id)
            return


def select_cases(cases: Sequence[Mapping[str, Any]], sample_size: int, seed: int) -> List[Mapping[str, Any]]:
    rng = random.Random(seed)
    ordered = sorted(cases, key=lambda case: str(case["case_id"]))
    shuffled = list(ordered)
    rng.shuffle(shuffled)
    selected: List[Mapping[str, Any]] = []
    selected_ids: set[str] = set()

    for value in sorted({str(case.get("operation_subtype", "")) for case in cases if case.get("operation_subtype")}):
        add_first_matching(selected, selected_ids, shuffled, lambda case, value=value: case.get("operation_subtype") == value)
    for value in ["answerable", "unknown_current", "insufficient_evidence"]:
        add_first_matching(selected, selected_ids, shuffled, lambda case, value=value: case.get("answerability") == value)
    for value in ["easy", "medium", "hard"]:
        add_first_matching(selected, selected_ids, shuffled, lambda case, value=value: case.get("difficulty_level") == value)
    for value in sorted(set().union(*(hard_negative_type_set(case) for case in cases))):
        add_first_matching(selected, selected_ids, shuffled, lambda case, value=value: value in hard_negative_type_set(case))
    for value in sorted({str(case.get("scope_id", "")) for case in cases}):
        add_first_matching(selected, selected_ids, shuffled, lambda case, value=value: case.get("scope_id") == value)

    buckets: Dict[tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
    for case in shuffled:
        buckets[(str(case.get("answerability")), str(case.get("difficulty_level")))].append(case)
    bucket_keys = sorted(buckets)
    while len(selected) < sample_size and any(buckets.values()):
        for key in bucket_keys:
            bucket = buckets[key]
            while bucket and str(bucket[0]["case_id"]) in selected_ids:
                bucket.pop(0)
            if bucket and len(selected) < sample_size:
                case = bucket.pop(0)
                selected.append(case)
                selected_ids.add(str(case["case_id"]))
    return sorted(selected[:sample_size], key=lambda case: str(case["case_id"]))


def annotation_template(case: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "answerability": "",
        "gold_state_slots": {},
        "gold_slot_support": {},
        "hard_negative_events": [],
        "hard_negative_types": {},
        "notes": "",
    }


def annotation_packet_row(
    case: Mapping[str, Any],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    scope_id = str(case["scope_id"])
    return {
        "case_id": str(case["case_id"]),
        "scope_id": scope_id,
        "query": str(case["query"]),
        "operation": str(case["operation"]),
        "events": [public_event(event) for event in sorted(events_by_scope[scope_id], key=event_sort_key)],
        "annotation_template": annotation_template(case),
    }


def gold_reference_row(case: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "scope_id": str(case["scope_id"]),
        "query": str(case["query"]),
        "operation": str(case["operation"]),
        "operation_subtype": str(case.get("operation_subtype", "")),
        "difficulty_level": str(case.get("difficulty_level", "")),
        "answerability": str(case.get("answerability", "")),
        "gold_events": normalize_id_list(case.get("gold_events")),
        "gold_state_slots": dict(case.get("gold_state_slots", {})),
        "gold_slot_support": dict(case.get("gold_slot_support", {})),
        "hard_negative_events": normalize_id_list(case.get("hard_negative_events")),
        "hard_negative_types": dict(case.get("hard_negative_types", {})),
    }


def md_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").strip()


def annotation_case_markdown(row: Mapping[str, Any], index: int, total: int, heading_level: int = 1) -> str:
    template = row["annotation_template"]
    heading = "#" * heading_level
    subheading = "#" * (heading_level + 1)
    lines = [
        f"{heading} Case {index}/{total}: {row['case_id']}",
        "",
        f"{subheading} Query",
        "",
        f"- case_id: `{row['case_id']}`",
        f"- scope_id: `{row['scope_id']}`",
        f"- operation: `{row['operation']}`",
        f"- query: {row['query']}",
        "",
        f"{subheading} Events",
        "",
    ]
    for event_index, event in enumerate(row["events"], start=1):
        planned_for = md_text(event.get("planned_for") or "none")
        lines.extend(
            [
                f"{event_index}. `{md_text(event.get('event_id'))}`",
                f"   - type: `{md_text(event.get('event_type'))}`",
                f"   - updated_at: `{md_text(event.get('updated_at'))}`",
                f"   - planned_for: `{planned_for}`",
                f"   - content: {md_text(event.get('content'))}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            f"{subheading} Annotation Template",
            "",
            "```json",
            json.dumps(template, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_readable_packet(out_dir: Path, rows: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> None:
    readable_dir = out_dir / "readable_cases"
    total = len(rows)
    index_lines = [
        "# STAMB-State v1.3 Readable Annotation Packet",
        "",
        "这个文件是人工阅读索引。不要读 `annotation_packet.jsonl`，那是给脚本用的。",
        "",
        "如果想在一个文件里连续阅读所有 case，打开 `annotation_workbook.md`。",
        "",
        "## Summary",
        "",
        f"- sample_size: {manifest['actual_sample_size']}",
        f"- operation: `{manifest['operation']}`",
        f"- answerability: `{manifest['answerability']}`",
        f"- difficulty_level: `{manifest['difficulty_level']}`",
        "",
        "## Case Index",
        "",
    ]
    workbook_lines = [
        "# STAMB-State v1.3 Annotation Workbook",
        "",
        "这个文件按 case 顺序展开，供人工标注阅读。填写时只需要参考每个 case 末尾的 `Annotation Template`。",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        case_id = str(row["case_id"])
        case_path = readable_dir / f"{case_id}.md"
        write_text(case_path, annotation_case_markdown(row, index, total))
        index_lines.extend(
            [
                f"### {index}. [`{case_id}`](readable_cases/{case_id}.md)",
                "",
                f"- scope_id: `{row['scope_id']}`",
                f"- operation: `{row['operation']}`",
                f"- query: {row['query']}",
                "",
            ]
        )
        workbook_lines.append(annotation_case_markdown(row, index, total, heading_level=2))
        workbook_lines.append("\n---\n")
    index_lines.extend(
        [
            "",
            "## Output Reminder",
            "",
            "标注完成后，把每个 case 的 `Annotation Template` 填好，合并成一行一个 JSON object 的 `annotator_a.jsonl` 或 `annotator_b.jsonl`。",
            "",
        ]
    )
    write_text(out_dir / "annotation_packet_readable.md", "\n".join(index_lines))
    write_text(out_dir / "annotation_workbook.md", "\n".join(workbook_lines))


def build_manifest(selected: Sequence[Mapping[str, Any]], sample_size: int, seed: int) -> Dict[str, Any]:
    hard_negative_type_counter: Counter[str] = Counter()
    for case in selected:
        hard_negative_type_counter.update(hard_negative_type_set(case))
    return {
        "requested_sample_size": sample_size,
        "actual_sample_size": len(selected),
        "seed": seed,
        "selected_case_ids": [str(case["case_id"]) for case in selected],
        "operation": dict(sorted(Counter(str(case.get("operation")) for case in selected).items())),
        "operation_subtype": dict(sorted(Counter(str(case.get("operation_subtype")) for case in selected).items())),
        "difficulty_level": dict(sorted(Counter(str(case.get("difficulty_level")) for case in selected).items())),
        "answerability": dict(sorted(Counter(str(case.get("answerability")) for case in selected).items())),
        "scope_count": len({str(case.get("scope_id")) for case in selected}),
        "hard_negative_type_coverage": dict(sorted(hard_negative_type_counter.items())),
    }


def build_packet(v1_dir: Path, out_dir: Path, sample_size: int, seed: int) -> Dict[str, Any]:
    events = read_json(v1_dir / "events_raw.json")
    cases = read_json(v1_dir / "cases.json")
    events_by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_scope[str(event["scope_id"])].append(event)

    selected = select_cases(cases, sample_size, seed)
    packet_rows = [annotation_packet_row(case, events_by_scope) for case in selected]
    gold_rows = [gold_reference_row(case) for case in selected]
    manifest = build_manifest(selected, sample_size, seed)

    write_jsonl(out_dir / "annotation_packet.jsonl", packet_rows)
    write_jsonl(out_dir / "gold_reference.jsonl", gold_rows)
    write_json(out_dir / "sample_manifest.json", manifest)
    write_readable_packet(out_dir, packet_rows, manifest)
    (out_dir / "README.md").write_text(
        "# STAMB-State v1.3 Annotation Packet\n\n"
        "Annotators should read `Design/BenchMark/STAMB-State_Annotation_Guidelines.md` first.\n\n"
        "- `annotation_packet.jsonl`: public events plus query and an empty annotation template.\n"
        "- `annotation_workbook.md`: single-file human-readable annotation workbook without Markdown tables.\n"
        "- `annotation_packet_readable.md`: human-readable index linking to one Markdown file per case.\n"
        "- `readable_cases/`: split human-readable case files without Markdown tables.\n"
        "- `gold_reference.jsonl`: evaluator-only labels for scoring/adjudication; do not give this file to annotators.\n"
        "- `sample_manifest.json`: deterministic sample coverage summary.\n\n"
        "Expected annotator output format is one JSON object per line matching `annotation_template`.\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a deterministic STAMB-State annotation packet.")
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1_3_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    manifest = build_packet(args.v1_dir, args.out_dir, args.sample_size, args.seed)
    print(f"wrote {args.out_dir}")
    print(f"sample_size={manifest['actual_sample_size']} seed={manifest['seed']}")
    print(f"operation={manifest['operation']}")
    print(f"answerability={manifest['answerability']}")
    print(f"operation_subtype={manifest['operation_subtype']}")
    print(f"hard_negative_type_coverage={manifest['hard_negative_type_coverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

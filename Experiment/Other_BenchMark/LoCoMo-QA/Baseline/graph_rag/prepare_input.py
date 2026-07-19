from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


BASELINE_DIR = Path(__file__).resolve().parents[1]
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

from common.loader import DATA_PATH, DialogTurn, LoCoMoSample, load_sample, load_samples  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare LoCoMo conversations as GraphRAG input text.")
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument("--all-samples", action="store_true")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--split-by-session", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = load_samples(args.data) if args.all_samples else [load_sample(args.data, args.sample_id)]
    prepare_samples(samples, args.workspace, split_by_session=args.split_by_session, data_path=args.data)
    return 0


def prepare_samples(samples: Iterable[LoCoMoSample], workspace: Path, *, split_by_session: bool, data_path: Path) -> None:
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "locomo-graphrag-input-v1",
        "adapter": "Baseline/graph_rag/prepare_input.py",
        "data_path": str(data_path.resolve()),
        "workspace": str(workspace.resolve()),
        "gold_fields_used_for_indexing": False,
        "ignored_source_fields": ["qa", "answer", "evidence", "category"],
        "samples": [],
    }

    for sample in samples:
        if split_by_session:
            for session in sample.sessions:
                filename = f"{safe_name(sample.sample_id)}_{safe_name(session.session_id)}.txt"
                write_text(input_dir / filename, sample_header(sample) + "\n\n" + session_text(session.turns))
            documents = len(sample.sessions)
        else:
            filename = f"{safe_name(sample.sample_id)}.txt"
            write_text(input_dir / filename, sample_header(sample) + "\n\n" + session_text(sample.turns))
            documents = 1

        manifest["samples"].append(
            {
                "sample_id": sample.sample_id,
                "num_sessions": len(sample.sessions),
                "num_turns": len(sample.turns),
                "documents_written": documents,
            }
        )

    (workspace / "locomo_graphrag_input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"prepared GraphRAG input: {input_dir}")
    print(f"manifest: {workspace / 'locomo_graphrag_input_manifest.json'}")


def sample_header(sample: LoCoMoSample) -> str:
    return (
        f"LoCoMo-QA conversation sample: {sample.sample_id}\n"
        "Source: LoCoMo released conversation only. Gold QA answers and evidence are not included."
    )


def session_text(turns: Iterable[DialogTurn]) -> str:
    lines = []
    current_session = None
    for turn in turns:
        if turn.session_id != current_session:
            current_session = turn.session_id
            lines.append("")
            lines.append(f"## Session {turn.session_id}")
            if turn.session_date_time:
                lines.append(f"Date/time: {turn.session_date_time}")
        lines.append(f"[{turn.dia_id}] {turn.speaker}: {turn.text}")
        if turn.image_caption:
            lines.append(f"[{turn.dia_id}] image caption: {turn.image_caption}")
        if turn.image_query:
            lines.append(f"[{turn.dia_id}] image query: {turn.image_query}")
    return "\n".join(lines).strip() + "\n"


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value).strip("_") or "sample"


if __name__ == "__main__":
    raise SystemExit(main())

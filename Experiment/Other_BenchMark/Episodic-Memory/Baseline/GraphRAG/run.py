#!/usr/bin/env python
"""EPBench adapter for the installed Microsoft GraphRAG package.

This mirrors the LoCoMo-QA GraphRAG runner boundary: Microsoft GraphRAG CLI
performs prepare/init/index/query, while this adapter only maps EPBench book
paragraphs and QA rows to GraphRAG input and EPBench judge-compatible output.
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


DEFAULT_CASE_ID = "Udefault_Sdefault_seed0"
DEFAULT_BOOK_FOLDER = (
    "model_claude-3-5-sonnet-20240620_itermax_10_"
    "Idefault_nbchapters_196_nbtokens_102870"
)

BASELINE_DIR = Path(__file__).resolve().parent
EPISODIC_ROOT = BASELINE_DIR.parents[1]
AAAI_DIR = BASELINE_DIR.parents[5]
PROJECT_DIR = AAAI_DIR / "Scope-Time-State"
CONFIG_PATH = EPISODIC_ROOT / "configs" / "epbench_memory.json"

FORBIDDEN_MEMORY_KEYS = {
    "gold_answer",
    "model_answer",
    "judge_result",
    "eval_result",
    "raw_answers",
    "evaluated_answers",
    "correct_answer",
    "answer",
    "answers",
    "qa",
    "questions",
}


@dataclass(frozen=True)
class MemoryParagraph:
    paragraph_id: str
    text: str
    source_index: int
    paragraph_index: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EPBench via the installed Microsoft GraphRAG package.")
    parser.add_argument("--stage", choices=("prepare", "init", "index", "answer", "all"), default="prepare")
    parser.add_argument("--book-path", type=Path, default=None)
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument("--workspace", type=Path, default=EPISODIC_ROOT / "artifacts/baselines/graphrag_gpt4omini_epbench/workspace")
    parser.add_argument("--output", type=Path, default=EPISODIC_ROOT / "artifacts/baselines/graphrag_gpt4omini_epbench/graphrag_predictions.jsonl")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--method", choices=("local", "global", "drift", "basic"), default="local")
    parser.add_argument(
        "--response-type",
        default="Compact JSON object with answer",
        help="GraphRAG response format hint. Default is aligned with EPBench answer-only evaluation.",
    )
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force-init", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.workspace = args.workspace.resolve()
    args.output = args.output.resolve()
    book_path = args.book_path or default_book_path()
    qa_path = args.qa_path or default_qa_path()
    if not book_path.is_file():
        raise FileNotFoundError(book_path)
    if not qa_path.is_file():
        raise FileNotFoundError(qa_path)

    if args.stage in {"prepare", "all"}:
        prepare_input(book_path, qa_path, args.workspace)

    if args.stage in {"init", "index", "answer", "all"}:
        ensure_graphrag_available()

    if args.stage in {"init", "all"}:
        run_graphrag(
            ["init", "--root", str(args.workspace), "--model", args.model, "--embedding", args.embedding_model, *force_flag(args.force_init)],
            args,
        )
        write_graphrag_env(args.workspace)

    if args.stage in {"index", "all"}:
        run_graphrag(["index", "--root", str(args.workspace)], args)

    if args.stage in {"answer", "all"}:
        run_answer(args, qa_path, book_path)

    return 0


def default_data_root() -> Path:
    return AAAI_DIR / "episodic-memory-benchmark-data" / "epbench" / "data"


def load_config_paths() -> tuple[Path | None, Path | None]:
    if not CONFIG_PATH.is_file():
        return None, None
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    book_path = Path(config["book_path"]) if config.get("book_path") else None
    qa_path = Path(config["evaluation_qa_path"]) if config.get("evaluation_qa_path") else None
    return book_path, qa_path


def default_book_path() -> Path:
    config_book, _ = load_config_paths()
    if config_book:
        return config_book
    return default_data_root() / DEFAULT_CASE_ID / "books" / DEFAULT_BOOK_FOLDER / "book.json"


def default_qa_path() -> Path:
    _, config_qa = load_config_paths()
    if config_qa:
        return config_qa
    return default_data_root() / DEFAULT_CASE_ID / "books" / DEFAULT_BOOK_FOLDER / "df_qa.parquet"


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text: str) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    parts = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", cleaned) if len(part.strip()) >= 80]
    return [part for part in parts if len(part) >= 40]


def collect_memory_strings(obj: Any, out: list[str]) -> None:
    if isinstance(obj, str):
        out.extend(split_paragraphs(obj))
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key) in FORBIDDEN_MEMORY_KEYS:
                continue
            collect_memory_strings(value, out)
        return
    if isinstance(obj, list):
        for value in obj:
            collect_memory_strings(value, out)


def load_book_paragraphs(book_path: Path) -> list[MemoryParagraph]:
    data = json.loads(book_path.read_text(encoding="utf-8"))
    strings: list[str] = []
    collect_memory_strings(data, strings)
    seen: set[str] = set()
    paragraphs: list[MemoryParagraph] = []
    for source_index, text in enumerate(strings):
        if text in seen:
            continue
        seen.add(text)
        paragraph_id = f"epbench_paragraph_{len(paragraphs):05d}"
        paragraphs.append(
            MemoryParagraph(
                paragraph_id=paragraph_id,
                text=text,
                source_index=source_index,
                paragraph_index=len(paragraphs),
            )
        )
    if not paragraphs:
        raise RuntimeError(f"No indexable EPBench memory text found in {book_path}")
    return paragraphs


def prepare_input(book_path: Path, qa_path: Path, workspace: Path) -> None:
    paragraphs = load_book_paragraphs(book_path)
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    text_path = input_dir / "epbench_long_book.txt"
    lines = [
        "EPBench / Episodic-Memory long book",
        "Source: canonical EPBench book text only. QA questions, gold answers, judge outputs, and evidence fields are not included.",
        "",
    ]
    for paragraph in paragraphs:
        lines.append(f"## {paragraph.paragraph_id}")
        lines.append(f"source_index: {paragraph.source_index}")
        lines.append(f"paragraph_index: {paragraph.paragraph_index}")
        lines.append(paragraph.text)
        lines.append("")
    text_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    manifest = {
        "schema_version": "epbench-graphrag-input-v1",
        "adapter": "Episodic-Memory/Baseline/GraphRAG/run.py",
        "book_path": str(book_path.resolve()),
        "qa_path": str(qa_path.resolve()),
        "workspace": str(workspace.resolve()),
        "documents_written": 1,
        "num_indexed_paragraphs": len(paragraphs),
        "gold_fields_used_for_indexing": False,
        "ignored_source_fields": sorted(FORBIDDEN_MEMORY_KEYS),
    }
    (workspace / "epbench_graphrag_input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"prepared GraphRAG input: {input_dir}")
    print(f"paragraphs: {len(paragraphs)}")
    print(f"manifest: {workspace / 'epbench_graphrag_input_manifest.json'}")


def graphrag_executable() -> str:
    env_script_dir = Path(sys.executable).resolve().parent
    script_dir = env_script_dir / "Scripts"
    for candidate in (
        script_dir / "graphrag.exe",
        script_dir / "graphrag",
        env_script_dir / "graphrag.exe",
        env_script_dir / "graphrag",
    ):
        if candidate.exists():
            return str(candidate)
    command = shutil.which("graphrag")
    if command:
        return command
    return "graphrag"


def ensure_graphrag_available() -> None:
    executable = graphrag_executable()
    if executable != "graphrag" or shutil.which("graphrag"):
        return
    raise RuntimeError("The Microsoft GraphRAG CLI is not installed in this environment. Install it with: python -m pip install graphrag")


def force_flag(enabled: bool) -> list[str]:
    return ["--force"] if enabled else []


def write_graphrag_env(workspace: Path) -> None:
    api_key = os.environ.get("GRAPHRAG_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("warning: OPENAI_API_KEY/GRAPHRAG_API_KEY is not set; GraphRAG may fail at index/query time.", file=sys.stderr)
        return
    env_path = workspace / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = [line for line in existing.splitlines() if not line.startswith("GRAPHRAG_API_KEY=")]
    lines.append(f"GRAPHRAG_API_KEY={api_key}")
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def run_answer(args: argparse.Namespace, qa_path: Path, book_path: Path) -> None:
    rows = select_rows(pd.read_parquet(qa_path).reset_index(), args)
    existing = load_existing(args.output) if args.resume else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("a" if args.resume else "w", encoding="utf-8") as handle:
        for index, row in enumerate(rows, start=1):
            row_key = str(row.get("debug_level_2", row.get("index", index - 1)))
            if index <= args.start:
                continue
            if row_key in existing:
                print(f"[skip {index}/{len(rows)}] row_key={row_key}", flush=True)
                continue
            question = str(row.get("question", "")).strip()
            print(f"[{index}/{len(rows)}] row_key={row_key}", flush=True)
            print("  question:", question, flush=True)
            query_result = query_graphrag(args, question)
            row_series = pd.Series(row)
            record = {
                "schema_version": "epbench-graphrag-answer-v1",
                "baseline": "microsoft_graphrag_cli",
                "row_key": row_key,
                "row_index": int(row.get("index", index - 1)),
                "debug_level_2": int(row.get("debug_level_2", row.get("index", index - 1))),
                "question": question,
                "retrieval_type": row.get("retrieval_type"),
                "time_instruction": normalize_time_instruction(row.get("get")),
                "bins_items_correct_answer": str(row.get("bins_items_correct_answer", "")),
                "n_items_correct_answer": int(row.get("n_items_correct_answer") or len(parse_gold_items(row_series))),
                "gold_items": parse_gold_items(row_series),
                "answer": query_result["answer"],
                "model_answer": query_result["answer"],
                "raw_graphrag_response": query_result["raw_response"],
                "graphrag_context_keys": query_result["context_keys"],
                "query_prompt": epbench_query_prompt(question),
                "graphrag_method": args.method,
                "graphrag_response_type": args.response_type,
                "trace": {
                    "retrieval_method": "microsoft_graphrag_cli",
                    "workspace": str(args.workspace),
                    "book_path": str(book_path),
                    "gold_used_for_retrieval_or_generation": False,
                    "judge_used": False,
                },
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            print("  answer:", str(query_result["answer"])[:300], flush=True)
    print(f"saved: {args.output}")


def query_graphrag(args: argparse.Namespace, question: str) -> dict[str, object]:
    if args.method == "local":
        try:
            return query_graphrag_local_api(args, question)
        except Exception as exc:
            print(f"warning: official GraphRAG Python API query failed; falling back to CLI: {exc}", file=sys.stderr)
    command = [
        "query",
        "--root",
        str(args.workspace),
        "--method",
        args.method,
        "--response-type",
        args.response_type,
        epbench_query_prompt(question),
    ]
    completed = run_graphrag(command, args, capture=True)
    raw_response = (completed.stdout or "").strip()
    parsed = parse_graphrag_answer(raw_response)
    return {"answer": parsed["answer"], "raw_response": raw_response, "context_keys": []}


def query_graphrag_local_api(args: argparse.Namespace, question: str) -> dict[str, object]:
    from graphrag.config.load_config import load_config
    import graphrag.api as api

    output_dir = args.workspace / "output"
    config = load_config(root_dir=args.workspace)
    required = {
        "communities": pd.read_parquet(output_dir / "communities.parquet"),
        "community_reports": pd.read_parquet(output_dir / "community_reports.parquet"),
        "text_units": pd.read_parquet(output_dir / "text_units.parquet"),
        "relationships": pd.read_parquet(output_dir / "relationships.parquet"),
        "entities": pd.read_parquet(output_dir / "entities.parquet"),
    }
    covariates_path = output_dir / "covariates.parquet"
    covariates = pd.read_parquet(covariates_path) if covariates_path.exists() else None
    raw_response, context_data = asyncio.run(
        api.local_search(
            config=config,
            entities=required["entities"],
            communities=required["communities"],
            community_reports=required["community_reports"],
            text_units=required["text_units"],
            relationships=required["relationships"],
            covariates=covariates,
            community_level=2,
            response_type=args.response_type,
            query=epbench_query_prompt(question),
            verbose=False,
        )
    )
    raw_text = response_to_text(raw_response)
    parsed = parse_graphrag_answer(raw_text)
    return {
        "answer": parsed["answer"],
        "raw_response": raw_text,
        "context_keys": sorted(context_data.keys()) if isinstance(context_data, dict) else [],
    }


def epbench_query_prompt(question: str) -> str:
    return (
        "Answer this EPBench episodic-memory question using only the indexed book memory. "
        "Return compact JSON only with key answer. "
        "The answer value must be a short gold-style phrase, date, name, or comma-separated list. "
        "Do not write a report, explanation, citations, markdown, or extra background. "
        "For false-premise or unavailable information, answer exactly \"No information available\". "
        "Do not use benchmark gold answers, judge outputs, evidence files, categories, or question-type labels. "
        f"Question: {question}"
    )


def parse_graphrag_answer(raw_response: str) -> dict[str, object]:
    text = raw_response.strip()
    json_text = extract_json_object(text)
    if json_text:
        try:
            payload = json.loads(json_text)
            answer = str(payload.get("answer") or "").strip()
            if answer:
                return {"answer": answer}
        except json.JSONDecodeError:
            pass
    return {"answer": strip_markdown_fences(text)}


def extract_json_object(text: str) -> str:
    stripped = strip_markdown_fences(text)
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return ""


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def response_to_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False)


def run_graphrag(command: Sequence[str], args: argparse.Namespace, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    full_command = [graphrag_executable(), *command]
    print(" ".join(quote(part) for part in full_command), flush=True)
    if args.dry_run:
        return subprocess.CompletedProcess(full_command, 0, stdout="", stderr="")
    env = os.environ.copy()
    if env.get("OPENAI_BASE_URL") and not env.get("GRAPHRAG_API_BASE"):
        env["GRAPHRAG_API_BASE"] = env["OPENAI_BASE_URL"]
    return subprocess.run(
        full_command,
        cwd=str(PROJECT_DIR),
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def select_rows(df: pd.DataFrame, args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.limit_cases > 0:
        df = df.iloc[: args.limit_cases]
    return df.to_dict(orient="records")


def load_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    existing: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("row_key") is not None:
            existing[str(item["row_key"])] = item
    return existing


def safe_isna(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if isinstance(result, bool) else False
    except Exception:
        return False


def parse_jsonish(value: Any) -> Any:
    if safe_isna(value):
        return None
    if isinstance(value, (list, tuple, dict)):
        return value
    if hasattr(value, "tolist"):
        return value.tolist()
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except Exception:
            pass
    return text


def parse_gold_items(row: pd.Series) -> list[str]:
    value = parse_jsonish(row.get("correct_answer"))
    if value is None:
        return []
    if isinstance(value, dict):
        return [str(v).strip() for v in value.values() if str(v).strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if ";" in text:
        return [item.strip() for item in text.split(";") if item.strip()]
    return [text] if text else []


def normalize_time_instruction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "latest":
        return "Latest"
    if text == "chronological":
        return "Chronological"
    return "All"


def quote(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        return repr(value)
    return value


if __name__ == "__main__":
    started = time.time()
    try:
        raise SystemExit(main())
    finally:
        print(f"elapsed_sec={time.time() - started:.1f}", flush=True)

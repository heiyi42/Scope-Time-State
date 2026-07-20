#!/usr/bin/env python
"""Official A-Mem baseline adapted from the local LoCoMo A-Mem integration."""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv


DEFAULT_CASE_ID = "Udefault_Sdefault_seed0"
DEFAULT_BOOK_FOLDER = "model_claude-3-5-sonnet-20240620_itermax_10_Idefault_nbchapters_196_nbtokens_102870"
BASELINE_DIR = Path(__file__).resolve().parent
EPISODIC_ROOT = BASELINE_DIR.parents[1]
REPO_ROOT = BASELINE_DIR.parents[4]
DEFAULT_AMEM_REPO = REPO_ROOT / "Graph/service_repos/epbench/A-mem"

FORBIDDEN_MEMORY_KEYS = {
    "gold_answer", "model_answer", "judge_result", "eval_result", "raw_answers",
    "evaluated_answers", "correct_answer", "answer", "answers", "qa", "questions",
}


@dataclass(frozen=True)
class Episode:
    episode_id: str
    text: str
    chapter_index: int
    paragraph_index: int


def parse_args() -> argparse.Namespace:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Run official A-Mem on the canonical EPBench book.")
    parser.add_argument("--book-path", type=Path, default=None)
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=EPISODIC_ROOT / "artifacts/baselines/a_mem_gpt4omini_epbench")
    parser.add_argument("--amem-repo-dir", type=Path, default=Path(os.environ.get("AMEM_REPO_DIR", DEFAULT_AMEM_REPO)))
    parser.add_argument("--amem-llm-backend", choices=("openai", "ollama"), default=os.environ.get("AMEM_LLM_BACKEND", "openai"))
    parser.add_argument("--amem-llm-model", default=os.environ.get("AMEM_LLM_MODEL") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--amem-llm-api-key", default=os.environ.get("AMEM_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", ""))
    parser.add_argument("--amem-embedding-model", default=os.environ.get("AMEM_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    parser.add_argument("--amem-evo-threshold", type=int, default=int(os.environ.get("AMEM_EVO_THRESHOLD", "1000000")))
    parser.add_argument("--top-k", type=int, default=24)
    parser.add_argument("--answering-model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--max-answer-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=-1)
    parser.add_argument("--ingest-limit", type=int, default=-1)
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        default=None,
        help="Per-episode A-Mem note checkpoint; defaults inside --out-dir.",
    )
    return parser.parse_args()


def default_book_path() -> Path:
    return EPISODIC_ROOT / "data" / DEFAULT_CASE_ID / "books" / DEFAULT_BOOK_FOLDER / "book.json"


def default_qa_path() -> Path:
    return EPISODIC_ROOT / "data" / DEFAULT_CASE_ID / "books" / DEFAULT_BOOK_FOLDER / "df_qa.parquet"


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+", " ", text).strip()


def split_paragraphs(text: str) -> list[str]:
    cleaned = clean_text(text)
    parts = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", cleaned) if len(part.strip()) >= 80]
    return [part for part in parts if len(part) >= 40]


def collect_memory_text(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        output.extend(split_paragraphs(value))
    elif isinstance(value, dict):
        for key, nested in value.items():
            if str(key) not in FORBIDDEN_MEMORY_KEYS:
                collect_memory_text(nested, output)
    elif isinstance(value, list):
        for nested in value:
            collect_memory_text(nested, output)


def load_episodes(book_path: Path) -> list[Episode]:
    content = json.loads(book_path.read_text(encoding="utf-8"))
    paragraphs: list[str] = []
    collect_memory_text(content, paragraphs)
    seen: set[str] = set()
    episodes: list[Episode] = []
    for paragraph in paragraphs:
        if paragraph in seen:
            continue
        seen.add(paragraph)
        index = len(episodes)
        episodes.append(Episode(f"epbench_paragraph_{index:05d}", paragraph, index, index))
    if not episodes:
        raise RuntimeError(f"No canonical-book paragraphs found in {book_path}")
    return episodes


def load_official_amem(repo: Path) -> dict[str, Any]:
    memory_system_path = repo.expanduser().resolve() / "agentic_memory/memory_system.py"
    if not memory_system_path.is_file():
        raise RuntimeError(f"A-Mem repository missing {memory_system_path}")
    if str(memory_system_path.parent.parent) not in sys.path:
        sys.path.insert(0, str(memory_system_path.parent.parent))
    module = importlib.import_module("agentic_memory.memory_system")
    memory_cls = getattr(module, "AgenticMemorySystem", None)
    note_cls = getattr(module, "MemoryNote", None)
    if memory_cls is None:
        raise RuntimeError("Official A-Mem runtime has no AgenticMemorySystem")
    if note_cls is None:
        raise RuntimeError("Official A-Mem runtime has no MemoryNote")
    return {"AgenticMemorySystem": memory_cls, "MemoryNote": note_cls}


def note_metadata(note: Any) -> dict[str, Any]:
    fields = (
        "content", "id", "keywords", "links", "retrieval_count", "timestamp",
        "last_accessed", "context", "evolution_history", "category", "tags",
    )
    return {field: getattr(note, field, None) for field in fields}


def restore_checkpoint(memory: Any, note_cls: type[Any], checkpoint_path: Path) -> set[str]:
    restored: set[str] = set()
    if not checkpoint_path.is_file():
        return restored
    for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        payload = record.get("note")
        episode_id = str(record.get("episode_id") or "")
        if not isinstance(payload, dict) or not episode_id:
            continue
        note = note_cls(**payload)
        memory.memories[note.id] = note
        memory.retriever.add_document(
            note.content,
            {
                "id": note.id,
                "content": note.content,
                "keywords": note.keywords,
                "links": note.links,
                "retrieval_count": note.retrieval_count,
                "timestamp": note.timestamp,
                "last_accessed": note.last_accessed,
                "context": note.context,
                "evolution_history": note.evolution_history,
                "category": note.category,
                "tags": note.tags,
            },
            note.id,
        )
        restored.add(episode_id)
    return restored


def parse_jsonish(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (dict, list, tuple)):
        return value
    text = str(value).strip()
    if not text:
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except Exception:
            pass
    return text


def gold_items(row: pd.Series) -> list[str]:
    value = parse_jsonish(row.get("correct_answer"))
    if isinstance(value, dict):
        return [str(item).strip() for item in value.values() if str(item).strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if value else []


def time_instruction(value: Any) -> str:
    return {"latest": "Latest", "chronological": "Chronological"}.get(str(value or "").lower(), "All")


def openai_base_url() -> str:
    return (os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE") or "https://api.openai.com/v1").rstrip("/")


def answer(question: str, context: str, args: argparse.Namespace) -> str:
    payload = {
        "model": args.answering_model,
        "messages": [{"role": "user", "content": (
            "# Episodic Memory Benchmark\n\n"
            "Answer only from the A-Mem memories below. The memories were created from the canonical book; "
            "they contain no gold answers. If evidence is insufficient, say the information is not available.\n\n"
            f"## A-Mem Retrieved Memories\n{context or '[none]'}\n\n## Question\n{question}"
        )}],
        "temperature": args.temperature,
        "max_tokens": args.max_answer_tokens,
    }
    headers = {"Authorization": f"Bearer {args.amem_llm_api_key}", "Content-Type": "application/json"}
    last_error = ""
    for attempt in range(4):
        try:
            response = requests.post(openai_base_url() + "/chat/completions", headers=headers, json=payload, timeout=180)
            if response.status_code < 400:
                return (response.json()["choices"][0]["message"].get("content") or "").strip()
            last_error = f"HTTP {response.status_code}: {response.text[:500]}"
        except Exception as exc:
            last_error = repr(exc)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Answer model failed after retries: {last_error}")


def memory_context(results: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    blocks: list[str] = []
    for rank, result in enumerate(results, start=1):
        content = str(result.get("content") or "")
        rows.append({
            "rank": rank, "id": result.get("id"), "score": result.get("score"),
            "timestamp": result.get("timestamp"), "context": result.get("context"),
            "keywords": result.get("keywords"), "tags": result.get("tags"),
            "is_neighbor": result.get("is_neighbor", False), "preview": content[:1000],
        })
        blocks.append(f'<memory rank="{rank}" timestamp="{result.get("timestamp", "")}">\n{content}\n'
                      f'context: {result.get("context", "")}\nkeywords: {result.get("keywords", [])}\n</memory>')
    return "\n\n".join(blocks), rows


def main() -> int:
    args = parse_args()
    book_path = args.book_path or default_book_path()
    qa_path = args.qa_path or default_qa_path()
    if not book_path.is_file() or not qa_path.is_file():
        raise FileNotFoundError(f"book={book_path}, qa={qa_path}")
    if not args.amem_llm_api_key:
        raise RuntimeError("OPENAI_API_KEY or AMEM_LLM_API_KEY is required for official A-Mem.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = args.out_dir / "a_mem_predictions.jsonl"
    config_path = args.out_dir / "a_mem_run_config.json"
    checkpoint_path = args.checkpoint_path or args.out_dir / "a_mem_ingest_checkpoint.jsonl"
    if args.reset:
        if predictions_path.exists():
            predictions_path.unlink()
        if checkpoint_path.exists():
            checkpoint_path.unlink()

    episodes = load_episodes(book_path)
    official = load_official_amem(args.amem_repo_dir)
    memory = official["AgenticMemorySystem"](
        model_name=args.amem_embedding_model,
        llm_backend=args.amem_llm_backend,
        llm_model=args.amem_llm_model,
        evo_threshold=args.amem_evo_threshold,
        api_key=args.amem_llm_api_key,
    )
    selected = episodes if args.ingest_limit < 0 else episodes[:args.ingest_limit]
    restored_episode_ids = restore_checkpoint(memory, official["MemoryNote"], checkpoint_path)
    if restored_episode_ids:
        print(f"[a-mem-checkpoint] restored={len(restored_episode_ids)} path={checkpoint_path}", flush=True)
    if not args.skip_ingest:
        base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        for index, episode in enumerate(selected, start=1):
            if episode.episode_id in restored_episode_ids:
                print(f"[a-mem-ingest] resume-skip {episode.episode_id}", flush=True)
                continue
            note_id = memory.add_note(
                content=(f"[episode_id={episode.episode_id}] [chapter_index={episode.chapter_index}] "
                         f"[paragraph_index={episode.paragraph_index}]\n{episode.text}"),
                time=(base_time + timedelta(minutes=index)).strftime("%Y%m%d%H%M"),
                tags=["epbench", episode.episode_id],
                category="EPBench canonical book",
            )
            note = memory.memories[note_id]
            with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
                checkpoint.write(json.dumps({"episode_id": episode.episode_id, "note": note_metadata(note)}, ensure_ascii=False) + "\n")
                checkpoint.flush()
                os.fsync(checkpoint.fileno())
            print(f"[a-mem-ingest] {index}/{len(selected)} {episode.episode_id}", flush=True)

    config_path.write_text(json.dumps({
        "baseline": "official_a_mem", "official_runtime": "agiresearch/A-mem AgenticMemorySystem",
        "official_repo": str(args.amem_repo_dir.resolve()), "book_path": str(book_path), "qa_path": str(qa_path),
        "predictions_path": str(predictions_path), "amem_llm_backend": args.amem_llm_backend,
        "amem_llm_model": args.amem_llm_model, "amem_embedding_model": args.amem_embedding_model,
        "amem_evo_threshold": args.amem_evo_threshold, "top_k": args.top_k,
        "num_available_episodes": len(episodes), "num_ingest_targets": len(selected),
        "ingest_checkpoint_path": str(checkpoint_path),
        "gold_used_for_retrieval_or_generation": False, "judge_used": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    done: set[str] = set()
    if predictions_path.exists():
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(str(json.loads(line).get("row_key")))
    qa = pd.read_parquet(qa_path).reset_index()
    rows = qa.iloc[args.start:] if args.limit < 0 else qa.iloc[args.start:args.start + args.limit]
    with predictions_path.open("a", encoding="utf-8") as handle:
        for _, row in rows.iterrows():
            row_index, row_key = int(row["index"]), str(row.get("debug_level_2", row["index"]))
            if row_key in done:
                continue
            question = str(row.get("question", "")).strip()
            results = memory.search_agentic(question, k=args.top_k)
            context, trace_results = memory_context(results or [])
            model_answer = answer(question, context, args)
            record = {
                "row_key": row_key, "row_index": row_index, "debug_level_2": int(row.get("debug_level_2", row_index)),
                "question": question, "retrieval_type": row.get("retrieval_type"), "time_instruction": time_instruction(row.get("get")),
                "bins_items_correct_answer": str(row.get("bins_items_correct_answer", "")),
                "n_items_correct_answer": int(row.get("n_items_correct_answer") or len(gold_items(row))),
                "gold_items": gold_items(row), "answer": model_answer, "model_answer": model_answer,
                "baseline": "official_a_mem", "trace": {"retrieval_method": "official_a_mem_search_agentic",
                    "official_runtime": "agiresearch/A-mem", "top_k": args.top_k, "results": trace_results,
                    "gold_used_for_retrieval_or_generation": False, "judge_used": False},
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"[a-mem-qa] {len(done) + 1}/{len(qa)} debug_level_2={record['debug_level_2']}", flush=True)
            done.add(row_key)
    print(f"Saved: {predictions_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

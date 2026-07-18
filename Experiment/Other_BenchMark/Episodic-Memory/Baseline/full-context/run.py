from __future__ import annotations

import argparse
import ast
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


BASELINE_DIR = Path(__file__).resolve().parent
EPISODIC_ROOT = BASELINE_DIR.parents[1]
AAAI_DIR = BASELINE_DIR.parents[5]
DATASET_ROOT = AAAI_DIR / "episodic-memory-benchmark-data" / "epbench" / "data" / "Udefault_Sdefault_seed0"
CONFIG_PATH = EPISODIC_ROOT / "configs" / "epbench_memory.json"
OUT_ROOT = EPISODIC_ROOT / "artifacts" / "baselines" / "full_context_llm"

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run EPBench full-context baseline on existing Udefault_Sdefault_seed0 data only."
    )
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--book-path", type=Path, default=None)
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument("--book-nb-events", type=int, default=200)
    parser.add_argument("--answering-model-name", "--answering_model", dest="answering_model_name", default="gpt-4o-mini")
    parser.add_argument("--max-memory-chars", type=int, default=-1)
    parser.add_argument("--max-new-tokens", "--max_tokens", dest="max_new_tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--sleeping-time", "--sleep", dest="sleeping_time", type=float, default=0.0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=-1)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=None)
    return parser.parse_args()


def load_config_paths() -> tuple[Path | None, Path | None]:
    if not CONFIG_PATH.is_file():
        return None, None
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    book_path = Path(config["book_path"]) if config.get("book_path") else None
    qa_path = Path(config["evaluation_qa_path"]) if config.get("evaluation_qa_path") else None
    return book_path, qa_path


def chapter_count(path: Path) -> int:
    match = re.search(r"nbchapters_(\d+)", str(path))
    return int(match.group(1)) if match else -1


def select_existing_dataset(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.book_path and args.qa_path:
        return args.book_path, args.qa_path

    config_book, config_qa = load_config_paths()
    if args.book_path or args.qa_path:
        book_path = args.book_path or config_book
        qa_path = args.qa_path or config_qa
        if not book_path or not qa_path:
            raise RuntimeError("Pass both --book-path and --qa-path, or keep the config file available.")
        return book_path, qa_path

    if args.book_nb_events == 200 and config_book and config_qa:
        return config_book, config_qa

    candidates: list[tuple[int, Path, Path]] = []
    for qa_path in sorted((args.dataset_root / "books").glob("*/df_qa.parquet")):
        book_path = qa_path.with_name("book.json")
        if book_path.is_file():
            candidates.append((abs(chapter_count(qa_path) - args.book_nb_events), book_path, qa_path))
    if not candidates:
        raise FileNotFoundError(f"No existing book.json/df_qa.parquet pair found under {args.dataset_root}")
    candidates.sort(key=lambda item: (item[0], str(item[2])))
    return candidates[0][1], candidates[0][2]


def safe_isna(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if isinstance(result, bool) else False
    except Exception:
        return False


def parse_list(value: Any) -> list[str]:
    if safe_isna(value):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if hasattr(value, "tolist"):
        return parse_list(value.tolist())
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
            if parsed is not value:
                return parse_list(parsed)
        except Exception:
            pass
    if ";" in text:
        return [item.strip() for item in text.split(";") if item.strip()]
    if "|" in text:
        return [item.strip() for item in text.split("|") if item.strip()]
    return [text]


def first_existing(row: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row and not safe_isna(row[name]):
            return row[name]
    return default


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def collect_long_strings(obj: Any, out: list[str]) -> None:
    if isinstance(obj, str):
        text = clean_text(obj)
        if len(text) >= 300:
            out.append(text)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in FORBIDDEN_MEMORY_KEYS:
                continue
            collect_long_strings(value, out)
        return
    if isinstance(obj, list):
        for value in obj:
            collect_long_strings(value, out)


def load_memory_text(book_path: Path, max_memory_chars: int) -> dict[str, Any]:
    data = json.loads(book_path.read_text(encoding="utf-8"))
    strings: list[str] = []
    collect_long_strings(data, strings)
    if not strings:
        raise RuntimeError(f"No narrative memory strings found in {book_path}")
    memory_text = max(strings, key=len)
    original_chars = len(memory_text)
    truncated = False
    if max_memory_chars > 0 and len(memory_text) > max_memory_chars:
        memory_text = memory_text[:max_memory_chars]
        truncated = True
    return {
        "memory_text": memory_text,
        "original_chars": original_chars,
        "used_chars": len(memory_text),
        "truncated": truncated,
    }


def call_chat_model(model: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing API key. Set OPENAI_API_KEY.")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.openai.com/v1"
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_error = None
    for attempt in range(4):
        try:
            resp = requests.post(base_url.rstrip("/") + "/chat/completions", headers=headers, json=payload, timeout=180)
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}: {resp.text[:1000]}"
                time.sleep(2 + attempt * 2)
                continue
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            last_error = repr(exc)
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"LLM call failed after retries: {last_error}")


def build_prompt(memory_text: str, question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "user",
            "content": (
                "# Episodic Memory Benchmark\n\n"
                "You are participating in an episodic memory test. You will be presented with "
                "a text to read and internalize as if you had personally experienced the events "
                "described. After the text, you will find a question about the content. Please "
                "answer this question based solely on the information provided in the text.\n\n"
                "## The Text to Memorize:\n"
                f"{memory_text}\n"
                "## Question:\n"
                f"{question}\n\n"
                "Please answer the question to the best of your ability, based only on the "
                "information provided in the text above. If you are unsure about an answer, "
                "it's okay to say so. Do not invent or assume information that was not "
                "explicitly stated in the text."
            ),
        },
    ]


def main() -> int:
    args = parse_args()
    book_path, qa_path = select_existing_dataset(args)
    if not book_path.is_file():
        raise FileNotFoundError(book_path)
    if not qa_path.is_file():
        raise FileNotFoundError(qa_path)

    out_dir = args.out_dir or (OUT_ROOT / f"events{args.book_nb_events}_{args.answering_model_name.replace('/', '_')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = out_dir / "full_context_predictions.jsonl"
    config_out = out_dir / "full_context_run_config.json"
    summary_path = out_dir / "full_context_summary.json"

    if args.reset and predictions_path.exists():
        predictions_path.unlink()

    df = pd.read_parquet(qa_path)
    total = len(df)
    rows = list(df.iterrows())
    if args.start > 0:
        rows = rows[args.start :]
    if args.limit is not None and args.limit >= 0:
        rows = rows[: args.limit]

    memory = load_memory_text(book_path, args.max_memory_chars)
    config = {
        "baseline": "full_context_llm",
        "dataset_root": str(args.dataset_root),
        "book_path": str(book_path),
        "qa_path": str(qa_path),
        "out_dir": str(out_dir),
        "predictions_path": str(predictions_path),
        "answering_model": args.answering_model_name,
        "max_memory_chars": args.max_memory_chars,
        "memory_original_chars": memory["original_chars"],
        "memory_used_chars": memory["used_chars"],
        "memory_truncated": memory["truncated"],
        "gold_used_for_retrieval_or_generation": False,
        "uses_generation_wrapper": False,
    }
    config_out.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({**config, "total_qa_available": total, "run_qa_count": len(rows)}, ensure_ascii=False, indent=2))
    done = 0
    mode = "a" if predictions_path.exists() and not args.reset else "w"
    with predictions_path.open(mode, encoding="utf-8") as handle:
        for local_i, (row_index, row) in enumerate(rows, start=1):
            row_dict = row.to_dict()
            question = str(first_existing(row_dict, ["question", "Question", "query"], "")).strip()
            gold_items = parse_list(first_existing(row_dict, ["correct_answer", "gold_items", "gold_answer", "answer", "answers"], ""))
            debug_level_2 = first_existing(row_dict, ["debug_level_2", "level_2", "row_key"], row_index)
            try:
                raw_answer = call_chat_model(
                    args.answering_model_name,
                    build_prompt(memory["memory_text"], question),
                    max_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                )
            except Exception as exc:
                raw_answer = ""
                print("LLM_ERROR:", repr(exc))
            answer = raw_answer.strip()
            if answer in {"[]", '""', "''"}:
                answer = ""
            out = {
                "row_key": str(debug_level_2),
                "row_index": int(row_index),
                "debug_level_2": debug_level_2,
                "question": question,
                "retrieval_type": str(first_existing(row_dict, ["retrieval_type", "kind"], "")),
                "time_instruction": str(first_existing(row_dict, ["time_instruction", "get"], "")),
                "bins_items_correct_answer": str(first_existing(row_dict, ["bins_items_correct_answer"], "")),
                "n_items_correct_answer": int(first_existing(row_dict, ["n_items_correct_answer"], len(gold_items)) or len(gold_items)),
                "gold_items": gold_items,
                "answer": answer,
                "model_answer": answer,
                "raw_model_answer": raw_answer,
                "baseline": "full_context_llm",
                "answering_model": args.answering_model_name,
                "protocol": {
                    "uses_graph": False,
                    "uses_retrieval": False,
                    "uses_generation_wrapper": False,
                    "gold_used_for_retrieval_or_generation": False,
                },
            }
            handle.write(json.dumps(out, ensure_ascii=False) + "\n")
            handle.flush()
            done += 1
            print(f"[{local_i}/{len(rows)}] row_key={debug_level_2}")
            print("  question:", question)
            print("  answer:", answer[:500])
            if args.sleeping_time > 0:
                time.sleep(args.sleeping_time)

    summary = {
        "status": "PASS",
        "baseline": "full_context_llm",
        "processed_this_run": done,
        "total_qa_available": total,
        "predictions_path": str(predictions_path),
        "config_path": str(config_out),
        "book_path": str(book_path),
        "qa_path": str(qa_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

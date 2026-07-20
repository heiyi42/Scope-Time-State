#!/usr/bin/env python
"""EPBench Graphiti baseline.

This adapts the local LoCoMo Graphiti baseline boundary to EPBench. It indexes
only the canonical EPBench book content, retrieves with the official Graphiti
package, and answers with an OpenAI-compatible chat model. Gold answers are
written only after generation so the existing EPBench judge can score them.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import inspect
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv


DEFAULT_CASE_ID = "Udefault_Sdefault_seed0"
DEFAULT_BOOK_FOLDER = (
    "model_claude-3-5-sonnet-20240620_itermax_10_"
    "Idefault_nbchapters_196_nbtokens_102870"
)

BASELINE_DIR = Path(__file__).resolve().parent
EPISODIC_ROOT = BASELINE_DIR.parents[1]
REPO_ROOT = BASELINE_DIR.parents[4]
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


@dataclass
class MemoryEpisode:
    episode_id: str
    text: str
    chapter_index: int
    paragraph_index: int


def parse_args() -> argparse.Namespace:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Run EPBench with open-source Graphiti.")
    parser.add_argument("--book-path", type=Path, default=None)
    parser.add_argument("--qa-path", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=EPISODIC_ROOT / "artifacts/baselines/graphiti_gpt4omini_epbench")
    parser.add_argument("--answering-model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--embedding-dim", type=int, default=int(os.environ.get("OPENAI_EMBEDDING_DIM", "1536")))
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument(
        "--neo4j-user",
        default=os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j"),
    )
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    parser.add_argument(
        "--neo4j-database",
        default=os.environ.get("NEO4J_DATABASE", "neo4j"),
        help="Neo4j database used by Graphiti. In graphiti-core 0.29 this is also its group_id.",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-search-context-chars", type=int, default=18000)
    parser.add_argument("--max-answer-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=-1)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--ingest-start", type=int, default=0)
    parser.add_argument(
        "--ingest-limit",
        type=int,
        default=-1,
        help="Number of book episodes to ingest; use 1 for an end-to-end smoke test.",
    )
    parser.add_argument("--ingest-batch-sleep", type=float, default=0.0)
    return parser.parse_args()


def default_data_root() -> Path:
    return EPISODIC_ROOT / "data"


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
        for paragraph in split_paragraphs(obj):
            out.append(paragraph)
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


def load_book_episodes(book_path: Path) -> list[MemoryEpisode]:
    data = json.loads(book_path.read_text(encoding="utf-8"))
    strings: list[str] = []
    collect_memory_strings(data, strings)
    seen: set[str] = set()
    episodes: list[MemoryEpisode] = []
    for idx, text in enumerate(strings):
        if text in seen:
            continue
        seen.add(text)
        episodes.append(
            MemoryEpisode(
                episode_id=f"epbench_paragraph_{len(episodes):05d}",
                text=text,
                chapter_index=idx,
                paragraph_index=len(episodes),
            )
        )
    if not episodes:
        raise RuntimeError(f"No indexable EPBench memory text found in {book_path}")
    return episodes


def openai_base_url() -> str:
    return (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or "https://api.openai.com/v1"
    ).rstrip("/")


def openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Missing OPENAI_API_KEY.")
    return key


def embedding_base_url() -> str:
    return (os.environ.get("OPENAI_EMBEDDING_BASE_URL") or openai_base_url()).rstrip("/")


def embedding_api_key() -> str:
    return os.environ.get("OPENAI_EMBEDDING_API_KEY") or openai_api_key()


def call_chat_model(model: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {openai_api_key()}", "Content-Type": "application/json"}
    last_error = None
    for attempt in range(4):
        try:
            resp = requests.post(openai_base_url() + "/chat/completions", headers=headers, json=payload, timeout=180)
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}: {resp.text[:1000]}"
                time.sleep(2 + attempt * 2)
                continue
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            last_error = repr(exc)
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"LLM call failed after retries: {last_error}")


def import_graphiti() -> dict[str, Any]:
    try:
        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        from graphiti_core.driver.neo4j_driver import Neo4jDriver
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.nodes import EpisodeType
        from graphiti_core.search.search_helpers import search_results_to_context_string
        from graphiti_core.search import search_config_recipes as recipes
    except ImportError as exc:
        raise RuntimeError("Graphiti dependencies are missing. Install with: pip install graphiti-core") from exc
    return locals()


def build_graphiti(args: argparse.Namespace, modules: dict[str, Any]) -> Any:
    llm_config = modules["LLMConfig"](
        api_key=openai_api_key(),
        model=args.answering_model,
        small_model=args.answering_model,
        base_url=openai_base_url(),
        temperature=0,
        max_tokens=8192,
    )
    client_kwargs = {"config": llm_config, "max_tokens": 8192}
    if "structured_output_mode" in inspect.signature(modules["OpenAIGenericClient"].__init__).parameters:
        client_kwargs["structured_output_mode"] = "json_schema"
    llm_client = modules["OpenAIGenericClient"](**client_kwargs)
    embedder = modules["OpenAIEmbedder"](
        config=modules["OpenAIEmbedderConfig"](
            api_key=embedding_api_key(),
            base_url=embedding_base_url(),
            embedding_model=args.embedding_model,
            embedding_dim=args.embedding_dim,
        )
    )
    driver = modules["Neo4jDriver"](
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )
    return modules["Graphiti"](
        graph_driver=driver,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=modules["OpenAIRerankerClient"](config=llm_config),
    )


async def ingest_graphiti(graphiti: Any, modules: dict[str, Any], args: argparse.Namespace, episodes: list[MemoryEpisode]) -> None:
    await graphiti.build_indices_and_constraints()
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    ingest_start = max(0, int(args.ingest_start))
    selected_episodes = episodes[ingest_start:]
    if args.ingest_limit >= 0:
        selected_episodes = selected_episodes[: args.ingest_limit]
    for idx, episode in enumerate(selected_episodes, start=ingest_start + 1):
        body = json.dumps(
            {
                "benchmark": "epbench",
                "episode_id": episode.episode_id,
                "chapter_index": episode.chapter_index,
                "paragraph_index": episode.paragraph_index,
                "content": episode.text,
            },
            ensure_ascii=False,
        )
        retry_delays = [0, 30, 60, 120]
        for attempt, delay in enumerate(retry_delays, start=1):
            if delay > 0:
                print(
                    f"[graphiti-ingest-retry] {idx}/{len(selected_episodes)} {episode.episode_id} "
                    f"waiting {delay}s before retry {attempt}/{len(retry_delays)}",
                    flush=True,
                )
                await asyncio.sleep(delay)
            try:
                await graphiti.add_episode(
                    name=f"{args.neo4j_database}-{episode.episode_id}",
                    episode_body=body,
                    source=modules["EpisodeType"].json,
                    source_description="EPBench canonical book paragraph. No QA, gold answers, or judge fields included.",
                    reference_time=base_time + timedelta(minutes=idx),
                    group_id=args.neo4j_database,
                )
                break
            except Exception as exc:
                if attempt == len(retry_delays):
                    raise
                print(
                    f"[graphiti-ingest-retry] {idx}/{len(selected_episodes)} {episode.episode_id} "
                    f"failed on attempt {attempt}/{len(retry_delays)}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
        if args.ingest_batch_sleep > 0:
            time.sleep(args.ingest_batch_sleep)
        print(f"[graphiti-ingest] {idx}/{len(selected_episodes)} {episode.episode_id}", flush=True)


def make_search_config(modules: dict[str, Any], top_k: int) -> Any:
    recipes = modules["recipes"]
    for name in ("COMBINED_HYBRID_SEARCH_RRF", "EDGE_HYBRID_SEARCH_RRF", "NODE_HYBRID_SEARCH_RRF"):
        config = getattr(recipes, name, None)
        if config is not None:
            break
    else:
        return None
    for attr in ("limit", "num_results", "top_k"):
        if hasattr(config, attr):
            try:
                setattr(config, attr, top_k)
            except Exception:
                pass
    return config


async def search_graphiti(graphiti: Any, modules: dict[str, Any], args: argparse.Namespace, question: str) -> str:
    config = make_search_config(modules, args.top_k)
    try:
        results = await graphiti.search_(
            query=question,
            group_ids=[args.neo4j_database],
            config=config,
        )
        context = modules["search_results_to_context_string"](results)
    except Exception:
        results = await graphiti.search(query=question, group_ids=[args.neo4j_database], num_results=args.top_k)
        context = "\n".join(str(item) for item in results)
    return context[: args.max_search_context_chars]


def build_answer_prompt(question: str, context: str) -> list[dict[str, str]]:
    return [
        {
            "role": "user",
            "content": (
                "# Episodic Memory Benchmark\n\n"
                "You are answering an episodic memory question using only the provided Graphiti memory context. "
                "The context was built from the canonical EPBench book only. It does not contain benchmark gold answers.\n\n"
                "## Retrieved Graphiti Memory Context:\n"
                f"{context}\n\n"
                "## Question:\n"
                f"{question}\n\n"
                "Answer based only on the retrieved memory context. If the context is insufficient, say that the "
                "information is not available. Do not invent facts."
            ),
        }
    ]


def config_payload(args: argparse.Namespace, book_path: Path, qa_path: Path, predictions_path: Path, episodes: list[MemoryEpisode]) -> dict[str, Any]:
    ingest_start = max(0, int(args.ingest_start))
    ingest_count = len(episodes[ingest_start:])
    if args.ingest_limit >= 0:
        ingest_count = min(ingest_count, args.ingest_limit)
    return {
        "baseline": "graphiti",
        "book_path": str(book_path),
        "qa_path": str(qa_path),
        "predictions_path": str(predictions_path),
        "answering_model": args.answering_model,
        "embedding_model": args.embedding_model,
        "embedding_dim": args.embedding_dim,
        "neo4j_database": args.neo4j_database,
        "top_k": args.top_k,
        "num_available_episodes": len(episodes),
        "num_ingested_episodes_this_run": 0 if args.skip_ingest else ingest_count,
        "gold_used_for_retrieval_or_generation": False,
        "graph_modified": False,
        "runtime_graph_clean_modified": False,
        "judge_used": False,
        "notes": [
            "Only canonical EPBench book text is indexed.",
            "QA questions and gold answers are used only after generation for judge-compatible output rows.",
            "No question-specific or answer-specific hard rules are applied.",
        ],
    }


async def run_benchmark(
    args: argparse.Namespace,
    graphiti: Any,
    modules: dict[str, Any],
    book_path: Path,
    qa_path: Path,
    episodes: list[MemoryEpisode],
    pred_path: Path,
    config_path: Path,
) -> None:
    """Keep one Graphiti client on one event loop for ingest, search, and close."""
    try:
        if not args.skip_ingest:
            await ingest_graphiti(graphiti, modules, args, episodes)
        config_path.write_text(
            json.dumps(config_payload(args, book_path, qa_path, pred_path, episodes), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        done = set()
        if pred_path.exists():
            for line in pred_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        done.add(str(json.loads(line).get("row_key")))
                    except Exception:
                        pass

        df = pd.read_parquet(qa_path).reset_index()
        rows = df.iloc[args.start :]
        if args.limit is not None and args.limit >= 0:
            rows = rows.iloc[: args.limit]

        with pred_path.open("a", encoding="utf-8") as handle:
            for pos, row in rows.iterrows():
                row_index = int(row["index"])
                question = str(row.get("question", "")).strip()
                row_key = str(row.get("debug_level_2", row_index))
                if row_key in done:
                    print(f"[skip] row_key={row_key}", flush=True)
                    continue
                context = await search_graphiti(graphiti, modules, args, question)
                answer = call_chat_model(
                    args.answering_model,
                    build_answer_prompt(question, context),
                    args.max_answer_tokens,
                    args.temperature,
                )
                record = {
                    "row_key": row_key,
                    "row_index": row_index,
                    "debug_level_2": int(row.get("debug_level_2", row_index)),
                    "question": question,
                    "retrieval_type": row.get("retrieval_type"),
                    "time_instruction": normalize_time_instruction(row.get("get")),
                    "bins_items_correct_answer": str(row.get("bins_items_correct_answer", "")),
                    "n_items_correct_answer": int(row.get("n_items_correct_answer") or len(parse_gold_items(row))),
                    "gold_items": parse_gold_items(row),
                    "answer": answer,
                    "model_answer": answer,
                    "baseline": "graphiti",
                    "trace": {
                        "retrieval_method": "graphiti_search",
                        "neo4j_database": args.neo4j_database,
                        "context_chars": len(context),
                        "gold_used_for_retrieval_or_generation": False,
                        "judge_used": False,
                    },
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"[{len(done) + 1}/{len(df)}] debug_level_2={record['debug_level_2']}", flush=True)
                print("  question:", question, flush=True)
                print("  answer:", answer[:300], flush=True)
                done.add(row_key)
                if args.sleep > 0:
                    time.sleep(args.sleep)
    finally:
        close = getattr(graphiti, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def main() -> int:
    args = parse_args()
    book_path = args.book_path or default_book_path()
    qa_path = args.qa_path or default_qa_path()
    if not book_path.is_file():
        raise FileNotFoundError(book_path)
    if not qa_path.is_file():
        raise FileNotFoundError(qa_path)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = args.out_dir / "graphiti_predictions.jsonl"
    config_path = args.out_dir / "graphiti_run_config.json"
    if args.reset and pred_path.exists():
        pred_path.unlink()

    episodes = load_book_episodes(book_path)
    modules = import_graphiti()
    graphiti = build_graphiti(args, modules)
    asyncio.run(
        run_benchmark(
            args,
            graphiti,
            modules,
            book_path,
            qa_path,
            episodes,
            pred_path,
            config_path,
        )
    )

    print("Saved:", pred_path)
    print("Config:", config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

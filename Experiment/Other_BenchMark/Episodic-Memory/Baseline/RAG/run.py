#!/usr/bin/env python
"""Paper-style EPBench paragraph RAG baseline.

This is the original STS paragraph-embedding RAG flow adapted only for the
current Episodic-Memory folder and OpenAI-compatible GPT answering:

1. split the canonical EPBench book into paragraph chunks;
2. embed paragraph text and questions with text-embedding-3-small;
3. retrieve top-k paragraphs by cosine similarity;
4. prepend retrieved paragraphs to the question;
5. answer with gpt-4o-mini without using gold answers, graph fields, or judge fields.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


DEFAULT_CASE_ID = "Udefault_Sdefault_seed0"
DEFAULT_BOOK_FOLDER = (
    "model_claude-3-5-sonnet-20240620_itermax_10_"
    "Idefault_nbchapters_196_nbtokens_102870"
)
DEFAULT_PARAGRAPH_MODEL = "model_claude-3-5-sonnet-20240620"

BASELINE_DIR = Path(__file__).resolve().parent
EPISODIC_ROOT = BASELINE_DIR.parents[1]
AAAI_DIR = BASELINE_DIR.parents[5]
CONFIG_PATH = EPISODIC_ROOT / "configs" / "epbench_memory.json"


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source_file: str
    event_id: int | None
    paragraph_index: int


def default_data_root() -> Path:
    return AAAI_DIR / "episodic-memory-benchmark-data" / "epbench" / "data"


def default_qa_path() -> Path:
    if CONFIG_PATH.is_file():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if config.get("evaluation_qa_path"):
            return Path(config["evaluation_qa_path"])
    return (
        default_data_root()
        / DEFAULT_CASE_ID
        / "books"
        / DEFAULT_BOOK_FOLDER
        / "df_qa.parquet"
    )


def default_book_path() -> Path:
    if CONFIG_PATH.is_file():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if config.get("book_path"):
            return Path(config["book_path"])
    return (
        default_data_root()
        / DEFAULT_CASE_ID
        / "books"
        / DEFAULT_BOOK_FOLDER
        / "book.json"
    )


def default_paragraph_dir() -> Path:
    return default_data_root() / DEFAULT_CASE_ID / "paragraphs"


def default_out_dir() -> Path:
    return EPISODIC_ROOT / "artifacts" / "baselines" / "rag_canonical_book_paragraph_top68_gpt4omini_paper_prompt"


def parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple, dict)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return text


def parse_gold_items(row: pd.Series) -> list[str]:
    value = parse_jsonish(row.get("correct_answer"))
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return [str(x) for x in value.tolist()]
    if isinstance(value, dict):
        return [str(x) for x in value.values()]
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value]
    text = str(value).strip()
    return [] if text in {"", "[]"} else [text]


def normalize_time_instruction(value: Any) -> str:
    text = str(value or "all").strip().lower()
    if text == "chronological":
        return "Chronological"
    if text == "latest":
        return "Latest"
    return "All"


def extract_event_id(path: Path) -> int | None:
    match = re.search(r"_e(\d+)_iter", path.name)
    return int(match.group(1)) if match else None


def text_candidates(obj: Any) -> list[str]:
    """Extract plausible paragraph strings from heterogeneous EPBench JSON."""
    out: list[str] = []
    preferred_keys = {
        "paragraph",
        "paragraph_text",
        "text",
        "content",
        "generated_text",
        "generated_paragraph",
        "completion",
    }

    def split_paragraph_text(value: str) -> list[str]:
        text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return []

        numbered = [
            part.strip()
            for part in re.split(r"(?m)(?=^\s*\(\d+\)\s)", text)
            if part.strip()
        ]
        if len(numbered) > 1:
            parts = numbered
        else:
            parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]

        cleaned_parts: list[str] = []
        for part in parts:
            s = " ".join(part.split())
            if len(s) >= 40:
                cleaned_parts.append(s)
        return cleaned_parts

    def walk(x: Any) -> None:
        if isinstance(x, str):
            for s in split_paragraph_text(x):
                out.append(s)
        elif isinstance(x, list):
            for item in x:
                walk(item)
        elif isinstance(x, dict):
            hit = False
            for k, v in x.items():
                if str(k) in preferred_keys:
                    walk(v)
                    hit = True
            if not hit:
                for v in x.values():
                    walk(v)

    walk(obj)

    seen: set[str] = set()
    cleaned: list[str] = []
    for s in out:
        if s in seen:
            continue
        if re.search(r"\b(correct_answer|gold_answer|ground_truth|groundtruth|judge_result|judge)\b", s.lower()):
            continue
        seen.add(s)
        cleaned.append(s)
    return cleaned


def load_paragraph_chunks(
    paragraph_dir: Path,
    paragraph_model: str,
    iter_id: int,
    max_events: int,
) -> list[Chunk]:
    pattern = f"{paragraph_model}_e*_iter{iter_id}.json"
    files = sorted(
        paragraph_dir.glob(pattern),
        key=lambda p: (extract_event_id(p) if extract_event_id(p) is not None else 10**9, p.name),
    )
    chunks: list[Chunk] = []
    for path in files:
        eid = extract_event_id(path)
        if eid is not None and eid >= max_events:
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for idx, text in enumerate(text_candidates(obj)):
            chunks.append(
                Chunk(
                    chunk_id=f"paragraph_e{eid}_p{idx}" if eid is not None else f"{path.stem}_p{idx}",
                    text=text,
                    source_file=path.name,
                    event_id=eid,
                    paragraph_index=idx,
                )
            )
    if not chunks:
        raise RuntimeError(
            f"No paragraph chunks found under {paragraph_dir} with pattern {pattern}"
        )
    return chunks


def load_book_paragraph_chunks(book_path: Path) -> list[Chunk]:
    obj = json.loads(book_path.read_text(encoding="utf-8"))
    book_text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    chapters = [
        chapter.strip()
        for chapter in re.split(r"(?m)(?=^Chapter\s+\d+\b)", book_text)
        if chapter.strip()
    ]
    chunks: list[Chunk] = []
    for chapter_pos, chapter in enumerate(chapters, start=1):
        header_match = re.match(r"^Chapter\s+(\d+)\b", chapter)
        chapter_id = int(header_match.group(1)) if header_match else chapter_pos
        body = re.sub(r"^Chapter\s+\d+\s*", "", chapter, count=1).strip()
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
        if not paragraphs:
            paragraphs = [body] if body else []
        for paragraph_pos, paragraph in enumerate(paragraphs, start=1):
            text = " ".join(paragraph.split())
            if len(text) < 40:
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"chapter_{chapter_id}_paragraph_{paragraph_pos}",
                    text=text,
                    source_file=book_path.name,
                    event_id=chapter_id - 1,
                    paragraph_index=paragraph_pos - 1,
                )
            )
    if not chunks:
        raise RuntimeError(f"No paragraph chunks found in canonical book {book_path}")
    return chunks


def cosine_topk(query: np.ndarray, matrix: np.ndarray, k: int) -> list[tuple[int, float]]:
    q = query / (np.linalg.norm(query) + 1e-12)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
    scores = m @ q
    idx = np.argsort(-scores)[:k]
    return [(int(i), float(scores[i])) for i in idx]


def openai_api_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required.")
    try:
        key.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            "OPENAI_API_KEY contains non-ASCII characters. Replace the placeholder "
            "with your real API key before running."
        ) from exc
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    response = requests.post(
        f"{base_url}/{endpoint.lstrip('/')}",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def embed_openai(texts: list[str], model: str, batch_size: int = 64) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        for attempt in range(6):
            try:
                resp = openai_api_post(
                    "/embeddings",
                    {
                        "model": model,
                        "input": batch,
                    },
                )
                vectors.extend([item["embedding"] for item in resp["data"]])
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(2**attempt)
    return np.array(vectors, dtype=np.float32)


def answer_with_openai(question: str, contexts: list[Chunk], model: str, temperature: float) -> str:
    context_text = "\n\n".join(
        f"Chapter {(c.event_id or 0) + 1}, Paragraph {c.paragraph_index + 1}\n{c.text}"
        for c in contexts
    )
    user = (
        "# Episodic Memory Benchmark\n\n"
        "You are participating in an episodic memory test, based on the data below, "
        "which was retrieved from a book. You need to read it and internalize as if "
        "you had personally experienced the events described. After the text, you "
        "will find a question about the content. Please answer this question based "
        "solely on the information provided in the retrieved data.\n\n"
        "## Retrieved Relevant Chunks from the Book:\n"
        f"{context_text}\n\n"
        "## Question:\n"
        f"{question}\n\n"
        "Please answer the question to the best of your ability, based only on the "
        "information provided in the relevant chunks above. If you are unsure about "
        "an answer, it's okay to say so. Do not invent or assume information that "
        "was not explicitly stated in the text."
    )

    for attempt in range(6):
        try:
            resp = openai_api_post(
                "/chat/completions",
                {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                },
            )
            return (resp["choices"][0]["message"].get("content") or "").strip()
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2**attempt)
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book_path", type=Path, default=default_book_path())
    parser.add_argument("--paragraph_dir", type=Path, default=default_paragraph_dir())
    parser.add_argument("--qa_path", type=Path, default=default_qa_path())
    parser.add_argument("--out_dir", type=Path, default=default_out_dir())
    parser.add_argument("--paragraph_model", default=DEFAULT_PARAGRAPH_MODEL)
    parser.add_argument("--iter_id", type=int, default=0)
    parser.add_argument("--max_events", type=int, default=200)
    parser.add_argument("--top_k", type=int, default=68)
    parser.add_argument("--limit", type=int, default=-1)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--answering_model", default="gpt-4o-mini")
    parser.add_argument("--embedding_model", default="text-embedding-3-small")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = args.out_dir / "rag_paragraph_embedding_predictions.jsonl"
    config_path = args.out_dir / "rag_paragraph_embedding_run_config.json"
    emb_cache_path = args.out_dir / "paragraph_embedding_cache.npz"

    if args.reset and pred_path.exists():
        pred_path.unlink()

    print("=" * 100)
    print("Paper-style paragraph embedding RAG")
    print("BOOK_PATH:", args.book_path)
    print("QA_PATH:", args.qa_path)
    print("PARAGRAPH_DIR:", args.paragraph_dir)
    print("OUT_DIR:", args.out_dir)
    print("TOP_K:", args.top_k)
    print("EMBEDDING_MODEL:", args.embedding_model)
    print("ANSWERING_MODEL:", args.answering_model)
    print("=" * 100)

    chunks = load_book_paragraph_chunks(args.book_path)
    print("CHUNKS:", len(chunks))

    if emb_cache_path.exists():
        cache = np.load(emb_cache_path, allow_pickle=True)
        chunk_ids = list(cache["chunk_ids"])
        if chunk_ids == [c.chunk_id for c in chunks]:
            chunk_embeddings = cache["embeddings"].astype(np.float32)
        else:
            chunk_embeddings = embed_openai([c.text for c in chunks], args.embedding_model)
            np.savez_compressed(
                emb_cache_path,
                chunk_ids=np.array([c.chunk_id for c in chunks], dtype=object),
                embeddings=chunk_embeddings,
            )
    else:
        chunk_embeddings = embed_openai([c.text for c in chunks], args.embedding_model)
        np.savez_compressed(
            emb_cache_path,
            chunk_ids=np.array([c.chunk_id for c in chunks], dtype=object),
            embeddings=chunk_embeddings,
        )

    qa = pd.read_parquet(args.qa_path)
    total = len(qa)
    end = total if args.limit < 0 else min(total, args.start + args.limit)
    qa_run = qa.iloc[args.start:end].reset_index(drop=False)

    config = {
        "baseline": "rag_paragraph_embedding",
        "paper_style": True,
        "retrieval_method": "embedding_cosine_similarity",
        "paper_rag_variant": "paragraph_top68_long_book",
        "embedding_model": args.embedding_model,
        "book_path": str(args.book_path),
        "paragraph_dir": str(args.paragraph_dir),
        "chunk_source": "canonical_book_paragraphs",
        "qa_path": str(args.qa_path),
        "out_dir": str(args.out_dir),
        "predictions_path": str(pred_path),
        "paragraph_model": args.paragraph_model,
        "iter_id": args.iter_id,
        "max_events": args.max_events,
        "top_k": args.top_k,
        "chunk_count": len(chunks),
        "answering_model": args.answering_model,
        "temperature": args.temperature,
        "total_qa_available": total,
        "run_start": args.start,
        "run_limit": args.limit,
        "gold_used_for_retrieval_or_generation": False,
        "graph_used": False,
        "judge_used": False,
        "uses_graph": False,
        "uses_retrieval": True,
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    with pred_path.open("a", encoding="utf-8") as f:
        for pos, row in qa_run.iterrows():
            row_index = int(row["index"])
            question = str(row.get("question", "")).strip()
            q_emb = embed_openai([question], args.embedding_model)[0]
            top = cosine_topk(q_emb, chunk_embeddings, args.top_k)
            retrieved = [chunks[i] for i, _ in top]
            answer = answer_with_openai(
                question, retrieved, args.answering_model, args.temperature
            )

            rec = {
                "row_key": str(row.get("debug_level_2", row_index)),
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
                "baseline": "rag_paragraph_embedding",
                "answering_model": args.answering_model,
                "embedding_model": args.embedding_model,
                "top_k": args.top_k,
                "retrieved_chunk_ids": [c.chunk_id for c in retrieved],
                "retrieved_context_preview": [
                    {
                        "chunk_id": c.chunk_id,
                        "source_file": c.source_file,
                        "event_id": c.event_id,
                        "paragraph_index": c.paragraph_index,
                        "score": score,
                        "preview": c.text[:500],
                    }
                    for c, (_, score) in zip(retrieved, top)
                ],
                "protocol": {
                    "paper_style": True,
                    "retrieval_method": "embedding_cosine_similarity",
                    "gold_used_for_retrieval_or_generation": False,
                    "graph_used": False,
                    "judge_used": False,
                },
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[{pos + 1}/{len(qa_run)}] debug_level_2={rec['debug_level_2']}")
            print("  question:", question)
            print("  answer:", answer[:300])
            print("-" * 100)

    print("Saved:", pred_path)
    print("Config:", config_path)


if __name__ == "__main__":
    main()

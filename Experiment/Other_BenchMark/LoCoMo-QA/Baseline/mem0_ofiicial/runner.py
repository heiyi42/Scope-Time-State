"""Official Mem0 LoCoMo protocol, isolated from the unified local baseline runner.

This follows the public ``mem0ai/memory-benchmarks`` LoCoMo flow:

    turn-level ingest -> Mem0 search -> answerer -> LoCoMo official F1

The directory name intentionally preserves the requested ``mem0_ofiicial`` spelling.
"""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import uuid


PACKAGE_DIR = Path(__file__).resolve().parent
BASELINE_DIR = PACKAGE_DIR.parent
PROJECT_DIR = PACKAGE_DIR.parents[4]
for import_path in (PACKAGE_DIR, BASELINE_DIR, PROJECT_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient  # noqa: E402
from common.loader import DialogTurn, LoCoMoSample, load_samples  # noqa: E402

try:  # noqa: E402
    from .client import Mem0OfficialOSSClient
    from .evaluation import official_qa_f1
    from .prompts import (
        ANSWERER_MEMORY_LIMIT,
        get_answer_generation_prompt,
    )
except ImportError:  # direct ``python runner.py`` execution
    from client import Mem0OfficialOSSClient  # type: ignore
    from evaluation import official_qa_f1  # type: ignore
    from prompts import (  # type: ignore
        ANSWERER_MEMORY_LIMIT,
        get_answer_generation_prompt,
    )


OFFICIAL_REPO = "https://github.com/mem0ai/memory-benchmarks"
OFFICIAL_REPO_COMMIT = "4b61c5d31b9c668a12b4f5e78064248a02c82d2b"
LOCOMO_REPO = "https://github.com/snap-research/locomo"
LOCOMO_REPO_COMMIT = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
INGEST_MODEL = "gpt-4o-mini"
CATEGORY_NAMES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}
CHUNK_SIZE = 1


@dataclass(frozen=True)
class QARecord:
    conversation_idx: int
    sample_id: str
    qa_idx: int
    category: int
    question: str
    answer: str
    evidence: Tuple[str, ...]

    @property
    def question_id(self) -> str:
        return f"conv{self.conversation_idx}_q{self.qa_idx}"


def parse_locomo_date(value: str) -> Optional[datetime]:
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def session_sort_key(session: Any) -> Tuple[int, datetime]:
    parsed = parse_locomo_date(str(session.date_time))
    if parsed is not None:
        return (0, parsed)
    return (1, datetime(2000, 1, int(session.session_index) + 1))


def ordered_sessions(sample: LoCoMoSample) -> List[Any]:
    return sorted(sample.sessions, key=session_sort_key)


def first_speaker(sample: LoCoMoSample) -> str:
    seen: List[str] = []
    for turn in sample.turns:
        if turn.speaker not in seen:
            seen.append(turn.speaker)
    return seen[0] if seen else ""


def photo_text(turn: DialogTurn) -> str:
    if turn.image_query and turn.image_caption:
        return f"[Sharing image - query: {turn.image_query}. The image shows: {turn.image_caption}]"
    if turn.image_query:
        return f"[Sharing image - query for: {turn.image_query}]"
    if turn.image_caption:
        return f"[Sharing image that shows: {turn.image_caption}]"
    return ""


def official_message(turn: DialogTurn, speaker_a: str) -> Dict[str, str]:
    text = turn.text
    image = photo_text(turn)
    if image:
        text = f"{text} {image}" if text else image
    return {
        "role": "user" if turn.speaker == speaker_a else "assistant",
        "content": f"{turn.speaker}: {text}",
    }


def session_epoch(date_time: str) -> Optional[int]:
    parsed = parse_locomo_date(date_time)
    if parsed is None:
        return None
    return int(parsed.replace(tzinfo=timezone.utc).timestamp())


def official_ingest_chunks(sample: LoCoMoSample) -> List[Tuple[str, int, List[Dict[str, str]], Optional[int]]]:
    speaker_a = first_speaker(sample)
    chunks: List[Tuple[str, int, List[Dict[str, str]], Optional[int]]] = []
    for session in ordered_sessions(sample):
        for turn_index, turn in enumerate(session.turns):
            if not turn.text.strip() and not turn.image_caption.strip() and not turn.image_query.strip():
                continue
            chunks.append((session.session_id, turn_index, [official_message(turn, speaker_a)], session_epoch(session.date_time)))
    return chunks


def load_qa_records(data_path: Path) -> Dict[int, List[QARecord]]:
    raw = json.loads(data_path.read_text(encoding="utf-8"))
    records: Dict[int, List[QARecord]] = {}
    for conversation_idx, sample in enumerate(raw):
        sample_id = str(sample.get("sample_id", f"conv-{conversation_idx}"))
        rows: List[QARecord] = []
        for qa_idx, qa in enumerate(sample.get("qa", [])):
            if not isinstance(qa, dict):
                continue
            evidence = tuple(str(item).strip() for item in (qa.get("evidence") or []) if str(item).strip())
            rows.append(
                QARecord(
                    conversation_idx=conversation_idx,
                    sample_id=sample_id,
                    qa_idx=qa_idx,
                    category=int(qa.get("category", 0)),
                    question=str(qa.get("question", "")),
                    answer=str(qa.get("answer", "")),
                    evidence=evidence,
                )
            )
        records[conversation_idx] = rows
    return records


def selected_conversations(args: argparse.Namespace, samples: Sequence[LoCoMoSample]) -> List[int]:
    if args.sample_id:
        for index, sample in enumerate(samples):
            if sample.sample_id == args.sample_id:
                return [index]
        raise ValueError(f"sample_id={args.sample_id!r} not found in {args.data}")
    values = [item.strip() for item in args.conversations.split(",") if item.strip()]
    indices = list(range(len(samples))) if values == ["all"] else [int(item) for item in values]
    invalid = [index for index in indices if index < 0 or index >= len(samples)]
    if invalid:
        raise ValueError(f"conversation indices out of range: {invalid}")
    return indices


def selected_rows(records: Iterable[QARecord], categories: Sequence[int], max_questions: Optional[int]) -> List[QARecord]:
    rows = [row for row in records if row.category in categories]
    return rows if max_questions is None else rows[:max_questions]


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def ingest_state_path(output_dir: Path, conversation_idx: int) -> Path:
    return output_dir / f"_ingest_conv{conversation_idx}.json"


async def ingest_conversation(
    client: Mem0OfficialOSSClient,
    sample: LoCoMoSample,
    conversation_idx: int,
    run_id: str,
    output_dir: Path,
    *,
    resume: bool,
) -> str:
    state_path = ingest_state_path(output_dir, conversation_idx)
    state: Dict[str, Any] = {}
    if resume and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("complete"):
            return str(state["user_id"])

    user_id = str(state.get("user_id") or f"locomo_{conversation_idx}_{run_id}")
    chunks = official_ingest_chunks(sample)
    completed = set(str(item) for item in state.get("completed_chunks", []))
    for session_id, turn_index, messages, timestamp in chunks:
        chunk_key = f"{session_id}_c{turn_index}"
        if chunk_key in completed:
            continue
        response = await client.add(messages, user_id, timestamp=timestamp)
        if response is None:
            raise RuntimeError(f"official Mem0 ingest failed: conversation={conversation_idx} chunk={chunk_key}")
        completed.add(chunk_key)
        write_json(
            state_path,
            {
                "schema_version": "mem0-official-locomo-ingest-v1",
                "implementation": OFFICIAL_REPO,
                "implementation_commit": OFFICIAL_REPO_COMMIT,
                "conversation_idx": conversation_idx,
                "sample_id": sample.sample_id,
                "user_id": user_id,
                "run_id": run_id,
                "chunk_size": CHUNK_SIZE,
                "completed_chunks": sorted(completed),
                "total_chunks": len(chunks),
                "complete": len(completed) == len(chunks),
            },
        )
    return user_id


def normalise_search_results(results: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    normalised: List[Dict[str, Any]] = []
    for item in results:
        row: Dict[str, Any] = {
            "memory": str(item.get("memory", "") or ""),
            "score": item.get("score", 0),
            "id": item.get("id", ""),
        }
        for key in ("created_at", "updated_at", "score_debug"):
            if key in item:
                row[key] = item[key]
        normalised.append(row)
    normalised.sort(key=lambda item: item.get("score", 0), reverse=True)
    return normalised


async def predict_conversation(
    client: Mem0OfficialOSSClient,
    sample: LoCoMoSample,
    conversation_idx: int,
    rows: Sequence[QARecord],
    args: argparse.Namespace,
    output_dir: Path,
    run_id: str,
    search_semaphore: asyncio.Semaphore,
) -> None:
    user_id = await ingest_conversation(client, sample, conversation_idx, run_id, output_dir, resume=args.resume)
    sessions = ordered_sessions(sample)
    reference_date = sessions[-1].date_time if sessions else None
    async def search_one(row: QARecord) -> None:
        result_path = output_dir / f"{row.question_id}.json"
        if args.resume and result_path.exists():
            return
        started = time.monotonic()
        async with search_semaphore:
            raw_results = await client.search(row.question, user_id, top_k=args.top_k)
        search_results = normalise_search_results(raw_results)
        result = {
            "question_id": row.question_id,
            "conversation_idx": conversation_idx,
            "sample_id": row.sample_id,
            "category": row.category,
            "category_name": CATEGORY_NAMES.get(row.category, "unknown"),
            "question": row.question,
            "ground_truth_answer": row.answer,
            "evidence": list(row.evidence),
            "user_id": user_id,
            "reference_date": reference_date,
            "retrieval": {
                "search_query": row.question,
                "search_results": search_results,
                "search_latency_ms": round((time.monotonic() - started) * 1000, 1),
                "total_results": len(search_results),
            },
        }
        write_json(result_path, result)
        print(f"[mem0_ofiicial-search] {row.question_id} results={len(search_results)}", flush=True)

    await asyncio.gather(*(search_one(row) for row in rows))


def provider_runtime(provider: str) -> Tuple[str, str]:
    prefix = provider.upper()
    api_key = os.environ.get(f"{prefix}_API_KEY", "")
    api_base = os.environ.get(f"{prefix}_API_BASE") or os.environ.get(f"{prefix}_BASE_URL", "")
    if not api_key:
        raise RuntimeError(f"missing {prefix}_API_KEY for {provider}")
    if not api_base:
        raise RuntimeError(f"missing {prefix}_API_BASE or {prefix}_BASE_URL for {provider}")
    return api_key, api_base


def cache_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:80]


def evaluate_one(
    prediction: Dict[str, Any],
    row: QARecord,
    args: argparse.Namespace,
    cache_dir: Path,
) -> Dict[str, Any]:
    answer_provider = args.provider
    answer_key, answer_base = provider_runtime(answer_provider)
    qid_slug = cache_slug(row.question_id)
    answerer = LLMClient(
        provider=answer_provider,
        model=args.answerer_model,
        api_key=answer_key,
        api_base=answer_base,
        cache_path=cache_dir / f"answerer_{qid_slug}.json",
        use_cache=not args.no_cache,
    )
    retrieved = list(prediction.get("retrieval", {}).get("search_results", []))
    cutoff_results: Dict[str, Dict[str, Any]] = {}
    for cutoff in args.top_k_cutoffs:
        sliced = retrieved[:cutoff]
        generated = answerer.complete_text(
            "",
            get_answer_generation_prompt(
                row.question,
                sliced[:ANSWERER_MEMORY_LIMIT],
                reference_date=prediction.get("reference_date"),
            ),
        ).strip()
        if "ANSWER:" in generated:
            generated = generated.rsplit("ANSWER:", 1)[-1].strip()
        score = official_qa_f1(row.category, generated, row.answer)
        cutoff_results[str(cutoff)] = {
            "locomo_official_f1": score,
            "score": score,
            "generated_answer": generated,
            "memories_evaluated": len(sliced),
        }
    result = dict(prediction)
    result["cutoff_results"] = cutoff_results
    result["evaluation"] = {
        "answerer_model": args.answerer_model,
        "answerer_provider": answer_provider,
        "scorer": "snap-research/locomo task_eval/evaluation.py",
        "metric": "official_qa_f1",
        "scorer_repo": LOCOMO_REPO,
        "scorer_commit": LOCOMO_REPO_COMMIT,
    }
    return result


def metric_summary(predictions: Sequence[Mapping[str, Any]], cutoffs: Sequence[int]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for cutoff in cutoffs:
        label = str(cutoff)
        scores = [float(item.get("cutoff_results", {}).get(label, {}).get("score", 0.0)) for item in predictions]
        by_category: Dict[str, List[float]] = {}
        for item, score in zip(predictions, scores):
            by_category.setdefault(str(item.get("category_name", "unknown")), []).append(score)
        output[label] = {
            "overall": {
                "total": len(scores),
                "mean_f1": (sum(scores) / len(scores)) if scores else 0.0,
            },
            "by_category": {
                category: {
                    "total": len(values),
                    "mean_f1": (sum(values) / len(values)) if values else 0.0,
                }
                for category, values in sorted(by_category.items())
            },
        }
    return output


def prediction_files(output_dir: Path, rows: Sequence[QARecord]) -> List[Tuple[QARecord, Path]]:
    missing: List[str] = []
    found: List[Tuple[QARecord, Path]] = []
    for row in rows:
        path = output_dir / f"{row.question_id}.json"
        if not path.exists():
            missing.append(row.question_id)
        else:
            found.append((row, path))
    if missing:
        raise RuntimeError(f"missing prediction files ({len(missing)}): {', '.join(missing[:10])}")
    return found


def evaluate_predictions(
    args: argparse.Namespace,
    rows: Sequence[QARecord],
    output_dir: Path,
    cache_dir: Path,
) -> Dict[str, Any]:
    files = prediction_files(output_dir, rows)
    pending: List[Tuple[QARecord, Dict[str, Any], Path]] = []
    completed: List[Dict[str, Any]] = []
    for row, path in files:
        prediction = json.loads(path.read_text(encoding="utf-8"))
        if prediction.get("cutoff_results") and not args.reevaluate:
            completed.append(prediction)
        else:
            pending.append((row, prediction, path))

    cache_dir.mkdir(parents=True, exist_ok=True)
    if pending:
        with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
            futures = {
                executor.submit(evaluate_one, prediction, row, args, cache_dir): (row, path)
                for row, prediction, path in pending
            }
            for future in futures:
                row, path = futures[future]
                result = future.result()
                write_json(path, result)
                completed.append(result)
                print(f"[mem0_ofiicial-score] {row.question_id}", flush=True)
    completed.sort(key=lambda item: item["question_id"])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    unified = {
        "metadata": {
            "benchmark": "locomo",
            "implementation": OFFICIAL_REPO,
            "implementation_commit": OFFICIAL_REPO_COMMIT,
            "project_name": args.project_name,
            "timestamp": timestamp,
            "answerer_model": args.answerer_model,
            "provider": args.provider,
            "ingest_model": INGEST_MODEL,
            "scorer": "snap-research/locomo task_eval/evaluation.py",
            "scorer_repo": LOCOMO_REPO,
            "scorer_commit": LOCOMO_REPO_COMMIT,
            "metric": "official_qa_f1",
            "top_k": args.top_k,
            "top_k_cutoffs": list(args.top_k_cutoffs),
            "categories": list(args.categories),
        },
        "metrics_by_cutoff": metric_summary(completed, args.top_k_cutoffs),
        "evaluations": completed,
    }
    result_path = output_dir / f"locomo_results_{timestamp}.json"
    write_json(result_path, unified)
    print(f"results={result_path}", flush=True)
    return unified


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the official Mem0 LoCoMo protocol")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--data", default=str(PROJECT_DIR / "Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json"))
    parser.add_argument("--sample-id", default="")
    parser.add_argument("--conversations", default="all", help="Comma-separated conversation indices or 'all'.")
    parser.add_argument("--answerer-model", default="gpt-4o-mini")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--mem0-host", default=os.environ.get("MEM0_HOST", "http://localhost:8888"))
    parser.add_argument("--mem0-api-key", default=os.environ.get("MEM0_API_KEY", ""))
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--top-k-cutoffs", default="20")
    parser.add_argument("--max-workers", type=int, default=10)
    parser.add_argument("--conversation-workers", type=int, default=1)
    parser.add_argument("--search-workers", type=int, default=1)
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--categories", default="1,2,3,4")
    parser.add_argument("--output-dir", default=str(PROJECT_DIR / "Graph/output/results/locomo_qa/mem0_ofiicial"))
    parser.add_argument("--cache-dir", default=str(PROJECT_DIR / "Graph/output/cache/mem0_ofiicial"))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    parser.add_argument("--mem0-timeout", type=float, default=300.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--predict-only", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--reevaluate", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    args.categories = tuple(int(item) for item in str(args.categories).split(",") if item.strip())
    args.top_k_cutoffs = tuple(int(item) for item in str(args.top_k_cutoffs).split(",") if item.strip())
    if args.top_k <= 0 or not args.top_k_cutoffs or any(item <= 0 for item in args.top_k_cutoffs):
        parser.error("top-k and top-k-cutoffs must be positive")
    if args.conversation_workers <= 0 or args.search_workers <= 0 or args.max_workers <= 0:
        parser.error("worker counts must be positive")
    if args.predict_only and args.evaluate_only:
        parser.error("--predict-only and --evaluate-only are mutually exclusive")
    return args


async def async_main(args: argparse.Namespace) -> int:
    data_path = Path(args.data).resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"LoCoMo data not found: {data_path}")
    samples = load_samples(data_path)
    records = load_qa_records(data_path)
    indices = selected_conversations(args, samples)
    selected_rows_by_conv = {
        index: selected_rows(records.get(index, []), args.categories, args.max_questions) for index in indices
    }
    output_dir = Path(args.output_dir).resolve() / f"predicted_{cache_slug(args.project_name)}"
    cache_dir = Path(args.cache_dir).resolve() / cache_slug(args.project_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or uuid.uuid4().hex[:8]
    print(
        f"LOCOMO official Mem0 | project={args.project_name} run_id={run_id} "
        f"ingest={INGEST_MODEL} answerer={args.answerer_model} scorer=locomo_official_f1",
        flush=True,
    )
    print(f"conversations={indices} top_k={args.top_k} cutoffs={list(args.top_k_cutoffs)}", flush=True)

    if args.dry_run:
        print(f"data={data_path}")
        print(f"output={output_dir}")
        print(f"rows={sum(len(rows) for rows in selected_rows_by_conv.values())}")
        return 0

    if not args.evaluate_only:
        client = Mem0OfficialOSSClient(
            args.mem0_host,
            api_key=args.mem0_api_key,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            timeout=args.mem0_timeout,
        )
        try:
            conversation_semaphore = asyncio.Semaphore(args.conversation_workers)
            search_semaphore = asyncio.Semaphore(args.search_workers)

            async def predict_one(conversation_idx: int) -> None:
                async with conversation_semaphore:
                    await predict_conversation(
                        client,
                        samples[conversation_idx],
                        conversation_idx,
                        selected_rows_by_conv[conversation_idx],
                        args,
                        output_dir,
                        run_id,
                        search_semaphore,
                    )

            await asyncio.gather(*(predict_one(conversation_idx) for conversation_idx in indices))
        finally:
            await client.close()

    if not args.predict_only:
        all_rows = [row for index in indices for row in selected_rows_by_conv[index]]
        evaluate_predictions(args, all_rows, output_dir, cache_dir)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_dotenv()
    return asyncio.run(async_main(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())

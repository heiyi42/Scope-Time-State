from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
PROJECT_DIR = BENCHMARK_DIR.parents[2]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, parse_json_object, provider_config  # noqa: E402
from Experiment.Main_Baseline.tsm.tsm_memory import (  # noqa: E402
    DurativeMemory,
    EntityNode,
    TSMIndex,
    TemporalFact,
    build_tsm_index,
    build_tsm_prompt_spec_from_index,
)
from ours_scope_time_state.graph_query_runner import (  # noqa: E402
    LLMRuntimeConfig,
    exact_match_score,
    f1_from_precision_recall,
    format_metric,
    official_style_answer_score,
    precision,
    recall,
    shard_cache_path,
    short_hash,
    summarize,
)
from common.loader import (  # noqa: E402
    DATA_PATH,
    DialogTurn,
    LoCoMoQAItem,
    LoCoMoSample,
    Session,
    dialog_sort_key,
    load_sample,
    load_sample_qa,
    normalize_dialog_ids,
    ordered_unique,
)
from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex  # noqa: E402
from pipeline.external.paths import EXTERNAL_CACHE_DIR, EXTERNAL_RESULT_DIR  # noqa: E402


SUPPORTED_VARIANTS = (
    "full_text",
    "rag",
    "mem0",
    "memgpt",
    "memory_bank",
    "memoryos",
    "zep",
    "tsm",
)


@dataclass(frozen=True)
class BaselineContext:
    candidate_dialog_ids: List[str]
    context: str
    trace: Dict[str, Any]
    direct_answer: Optional[str] = None
    direct_evidence_dialog_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LoCoMoTSMEvent:
    event_id: str
    scope_id: str
    content: str
    event_type: str
    occurred_at: str
    mentioned_at: str
    updated_at: str
    planned_for: Optional[str] = None
    deadline_at: Optional[str] = None
    source_id: Optional[str] = None
    metadata: Optional[Dict[str, object]] = None
    has_status_annotation: bool = False
    has_relation_annotations: bool = False
    has_state_relevant_annotation: bool = False
    status: str = "valid"
    corrects: Tuple[str, ...] = ()
    supersedes: Tuple[str, ...] = ()
    state_relevant: bool = True


@dataclass(frozen=True)
class LoCoMoTSMCase:
    query: str
    operation: str = "locomo_qa"
    scope_id: Optional[str] = None
    output_slots: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class EmbeddingRAGChunk:
    chunk_id: str
    turns: Tuple[DialogTurn, ...]
    document: str


class EmbeddingRAGCorpus:
    def __init__(self, sample: LoCoMoSample, args: argparse.Namespace) -> None:
        self.sample = sample
        self.turns_by_id = {turn.dia_id: turn for turn in sample.turns}
        self.chunk_target_chars = max(200, int(args.rag_chunk_target_chars))
        self.chunk_overlap_turns = max(0, int(args.rag_chunk_overlap_turns))
        self.embedding_model = str(args.rag_embedding_model)
        self.chunks = self._build_chunks()
        namespace = (
            f"locomo-qa:embedding-rag:{sample.sample_id}:"
            f"{short_hash(str(Path(args.data).resolve()))}:"
            f"{self.chunk_target_chars}:{self.chunk_overlap_turns}"
        )
        self.index = OpenAIEmbeddingIndex(
            [chunk.chunk_id for chunk in self.chunks],
            [chunk.document for chunk in self.chunks],
            model=self.embedding_model,
            cache_path=Path(args.rag_embedding_cache),
            namespace=namespace,
            batch_size=max(1, int(args.rag_embedding_batch_size)),
            base_url=args.rag_embedding_base_url or None,
        )

    def _build_chunks(self) -> List[EmbeddingRAGChunk]:
        ordered_turns = sorted(self.sample.turns, key=lambda turn: dialog_sort_key(turn.dia_id))
        turn_chunks = chunk_turns_by_chars(
            ordered_turns,
            target_chars=self.chunk_target_chars,
            overlap_turns=self.chunk_overlap_turns,
        )
        chunks: List[EmbeddingRAGChunk] = []
        for index, turns in enumerate(turn_chunks, start=1):
            if not turns:
                continue
            dialog_ids = [turn.dia_id for turn in turns]
            chunks.append(
                EmbeddingRAGChunk(
                    chunk_id=f"{self.sample.sample_id}:chunk:{index:04d}:{dialog_ids[0]}-{dialog_ids[-1]}",
                    turns=tuple(turns),
                    document=embedding_chunk_document(turns),
                )
            )
        return chunks

    def retrieve(self, question: str, top_k: int) -> BaselineContext:
        hits = self.index.search(question, top_k)
        chunks_by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        dialog_ids = ordered_unique(
            turn.dia_id
            for hit in hits
            for turn in chunks_by_id.get(hit.doc_id, EmbeddingRAGChunk(hit.doc_id, (), "")).turns
        )
        return BaselineContext(
            candidate_dialog_ids=dialog_ids,
            context=format_turn_context([self.turns_by_id[dialog_id] for dialog_id in dialog_ids if dialog_id in self.turns_by_id]),
            trace={
                "retriever": "embedding_turn_chunks",
                "embedding_model": self.embedding_model,
                "top_k_chunks": top_k,
                "chunk_target_chars": self.chunk_target_chars,
                "chunk_overlap_turns": self.chunk_overlap_turns,
                "n_chunks": len(self.chunks),
                "hits": [
                    {
                        "chunk_id": hit.doc_id,
                        "score": hit.score,
                        "dialog_ids": [turn.dia_id for turn in chunks_by_id.get(hit.doc_id, EmbeddingRAGChunk(hit.doc_id, (), "")).turns],
                        "char_count": len(chunks_by_id[hit.doc_id].document) if hit.doc_id in chunks_by_id else 0,
                    }
                    for hit in hits
                ],
            },
        )


class Mem0SampleIndex:
    def __init__(self, sample: LoCoMoSample, args: argparse.Namespace, runtime: LLMRuntimeConfig) -> None:
        os.environ.setdefault("MEM0_TELEMETRY", "False")
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise RuntimeError("mem0 baseline requires the mem0 Python package") from exc
        self.sample = sample
        self.turns_by_id = {turn.dia_id: turn for turn in sample.turns}
        collection_name = safe_collection_name(f"locomo_{sample.sample_id}_{short_hash(str(Path(args.data).resolve()))}")
        store_dir = Path(args.baseline_store_dir) / "mem0" / sample.sample_id
        self.store_dir = store_dir
        self.reuse_baseline_store = args.reuse_baseline_store
        vector_store_config = mem0_vector_store_config(args, store_dir, collection_name)
        config = {
            "version": "v1.1",
            "llm": {
                "provider": args.mem0_llm_provider or runtime.provider,
                "config": mem0_llm_config(args, runtime),
            },
            "embedder": {
                "provider": args.mem0_embedder_provider,
                "config": mem0_embedder_config(args),
            },
            "vector_store": {
                "provider": args.mem0_vector_store_provider,
                "config": vector_store_config,
            },
            "history_db_path": str(store_dir / "history.db"),
        }
        self.memory = Memory.from_config(config)
        if not args.reuse_baseline_store:
            self.memory.delete_all(user_id=sample.sample_id)
        if not args.mem0_skip_ingest:
            ingest_turns = sample.turns[: args.mem0_ingest_limit or None]
            start_index = max(1, args.mem0_start_index)
            self._ingest(
                ingest_turns[start_index - 1 :],
                offset=start_index - 1,
                total=len(ingest_turns),
                add_retries=max(1, args.mem0_add_retries),
                retry_sleep=max(1, args.mem0_retry_sleep),
            )

    def _ingest(
        self,
        turns: Sequence[DialogTurn],
        *,
        offset: int,
        total: int,
        add_retries: int,
        retry_sleep: int,
    ) -> None:
        existing_contents = self._existing_message_contents() if self.reuse_baseline_store and self.store_dir.exists() else set()
        for index, turn in enumerate(turns, start=1):
            display_index = offset + index
            content = self._turn_content(turn)
            if content in existing_contents:
                print(f"[mem0-ingest] {display_index}/{total} skip {turn.dia_id}", flush=True)
                continue
            print(f"[mem0-ingest] {display_index}/{total} add {turn.dia_id}", flush=True)
            self._add_with_retry(turn, content, add_retries=add_retries, retry_sleep=retry_sleep)
            existing_contents.add(content)

    def _add_with_retry(self, turn: DialogTurn, content: str, *, add_retries: int, retry_sleep: int) -> None:
        for attempt in range(1, add_retries + 1):
            try:
                self.memory.add(
                    [{"role": "user", "content": content}],
                    user_id=self.sample.sample_id,
                    metadata={
                        "dialog_id": turn.dia_id,
                        "session_id": turn.session_id,
                        "session_date_time": turn.session_date_time,
                        "speaker": turn.speaker,
                    },
                    infer=True,
                )
                return
            except Exception as exc:
                if attempt >= add_retries or not is_retryable_mem0_error(exc):
                    raise
                wait_seconds = retry_sleep * attempt
                print(
                    f"[mem0-ingest] retry {turn.dia_id} attempt={attempt}/{add_retries} "
                    f"sleep={wait_seconds}s error={exc}",
                    flush=True,
                )
                time.sleep(wait_seconds)

    def _existing_message_contents(self) -> set[str]:
        db_path = self.store_dir / "history.db"
        if not db_path.exists():
            return set()
        try:
            with sqlite3.connect(str(db_path)) as conn:
                return {str(row[0]) for row in conn.execute("select content from messages")}
        except sqlite3.DatabaseError:
            return set()

    @staticmethod
    def _turn_content(turn: DialogTurn) -> str:
        content = f"{turn.speaker}: {turn.text}"
        if turn.image_caption:
            content += f"\nImage caption: {turn.image_caption}"
        if turn.image_query:
            content += f"\nImage search query: {turn.image_query}"
        return content

    def retrieve(self, question: str, top_k: int) -> BaselineContext:
        raw = self.memory.search(question, top_k=top_k, filters={"user_id": self.sample.sample_id})
        results = raw.get("results", raw) if isinstance(raw, Mapping) else raw
        if not isinstance(results, list):
            results = []
        dialog_ids: List[str] = []
        lines: List[str] = []
        trace_rows: List[Dict[str, Any]] = []
        for rank, item in enumerate(results, start=1):
            if not isinstance(item, Mapping):
                continue
            memory_text = str(item.get("memory") or item.get("text") or item.get("content") or "")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            dialog_id = str(metadata.get("dialog_id") or "")
            if not dialog_id:
                match = re.search(r"\bD\d+:\d+\b", memory_text)
                dialog_id = match.group(0) if match else ""
            if dialog_id:
                dialog_ids.append(dialog_id)
            lines.append(f'<memory rank="{rank}" dialog_id="{dialog_id}" score="{item.get("score", "")}">{memory_text}</memory>')
            trace_rows.append(
                {
                    "rank": rank,
                    "dialog_id": dialog_id,
                    "score": item.get("score"),
                    "memory": memory_text,
                }
            )
        return BaselineContext(
            candidate_dialog_ids=ordered_unique(dialog_ids),
            context="\n\n".join(lines),
            trace={
                "retriever": "mem0",
                "top_k": top_k,
                "results": trace_rows,
            },
        )


class TSMSampleIndex:
    def __init__(self, sample: LoCoMoSample, args: argparse.Namespace, runtime: LLMRuntimeConfig) -> None:
        self.sample = sample
        self.runtime = runtime
        self.construction_calls = 0
        store_dir = Path(args.baseline_store_dir) / "tsm" / sample.sample_id
        index_path = store_dir / "index.json"
        if args.reuse_baseline_store and index_path.exists():
            self.index = load_tsm_index(index_path)
            print(f"[tsm-construction] load_index {index_path}", flush=True)
            return
        events = [tsm_event_from_turn(sample.sample_id, turn) for turn in sample.turns]
        print(f"[tsm-construction] build_index sample_id={sample.sample_id} events={len(events)} mode=llm", flush=True)
        self.index = build_tsm_index(events, construction_llm=self._construction_llm, construction_mode="llm")
        store_dir.mkdir(parents=True, exist_ok=True)
        save_tsm_index(self.index, index_path)
        print(
            f"[tsm-construction] done events={len(events)} facts={len(self.index.temporal_facts)} "
            f"durative={len(self.index.durative_memories)} calls={self.construction_calls} index={index_path}",
            flush=True,
        )

    def _construction_llm(self, system_prompt: str, user_prompt: str) -> Dict[str, object]:
        self.construction_calls += 1
        if self.construction_calls == 1 or self.construction_calls % 25 == 0:
            print(f"[tsm-construction] llm_call={self.construction_calls}", flush=True)
        client = make_sharded_client(
            self.runtime,
            "tsm_construction",
            short_hash(system_prompt + "\n" + user_prompt),
        )
        return client.complete_json(system_prompt, user_prompt)

    def retrieve(self, row: LoCoMoQAItem) -> BaselineContext:
        case = LoCoMoTSMCase(query=row.question)
        spec = build_tsm_prompt_spec_from_index(self.index, case)
        candidate_dialog_ids = [
            str(item.get("event_id"))
            for item in spec.visible_events
            if isinstance(item, Mapping) and re.match(r"D\d+:\d+", str(item.get("event_id", "")))
        ]
        return BaselineContext(
            candidate_dialog_ids=ordered_unique(candidate_dialog_ids),
            context=tsm_context_from_spec(spec),
            trace={
                "retriever": "tsm",
                "construction_mode": self.index.construction_mode,
                "visible_event_ids": candidate_dialog_ids,
                "n_visible_events": len(spec.visible_events),
            },
        )


class OfficialLettaMemGPTSampleIndex:
    def __init__(self, sample: LoCoMoSample, args: argparse.Namespace) -> None:
        self.sample = sample
        self.args = args
        self.store_dir = Path(args.baseline_store_dir) / "letta_memgpt" / sample.sample_id
        self.work_dir = self.store_dir / "runtime_cwd"
        self.state_path = self.store_dir / "agent_state.json"
        self.command, self.command_cwd = resolve_letta_command(args)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load_or_initialize_agent()

    def _load_or_initialize_agent(self) -> Dict[str, Any]:
        if self.args.reuse_baseline_store and self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            if state.get("agent_id") and state.get("ingested"):
                print(f"[letta-memgpt] load_agent_state {self.state_path}", flush=True)
                return state

        state: Dict[str, Any] = {}
        if self.args.letta_agent_id:
            state["agent_id"] = self.args.letta_agent_id
            state["conversation_id"] = self.args.letta_conversation_id or "default"

        if self.args.letta_skip_ingest:
            if not state.get("agent_id"):
                raise RuntimeError("--letta-skip-ingest requires --letta-agent-id or a reusable agent_state.json")
            state["ingested"] = False
            return state

        chunks = chunk_turns_by_count(self.sample.turns, self.args.letta_ingest_chunk_turns)
        if not chunks:
            raise RuntimeError(f"sample_id={self.sample.sample_id} has no dialog turns to ingest")

        agent_id = str(state.get("agent_id") or "")
        conversation_id = str(state.get("conversation_id") or self.args.letta_conversation_id or "default")
        for index, chunk in enumerate(chunks, start=1):
            prompt = letta_ingest_prompt(self.sample, chunk, index, len(chunks))
            print(f"[letta-memgpt] ingest_chunk {index}/{len(chunks)} turns={len(chunk)}", flush=True)
            result = self._run_letta_prompt(
                prompt,
                agent_id=agent_id or None,
                conversation_id=conversation_id if agent_id else None,
                new_agent=not agent_id,
                new_conversation=False,
            )
            agent_id = str(result.get("agent_id") or agent_id)
            conversation_id = str(result.get("conversation_id") or conversation_id or "default")
            if not agent_id:
                raise RuntimeError("official Letta command did not return agent_id")
            self._write_state(
                {
                    "schema_version": "locomo-letta-memgpt-official-v1",
                    "sample_id": self.sample.sample_id,
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "ingested": False,
                    "ingested_chunks": index,
                    "ingested_dialog_ids": [turn.dia_id for turn in self.sample.turns[: sum(len(item) for item in chunks[:index])]],
                    "letta_backend": self.args.letta_backend,
                    "letta_command": self.command,
                    "letta_command_cwd": str(self.command_cwd or self.work_dir),
                }
            )

        final_state = {
            "schema_version": "locomo-letta-memgpt-official-v1",
            "sample_id": self.sample.sample_id,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "ingested": True,
            "ingested_chunks": len(chunks),
            "ingested_dialog_ids": [turn.dia_id for turn in self.sample.turns],
            "letta_backend": self.args.letta_backend,
            "letta_command": self.command,
            "letta_command_cwd": str(self.command_cwd or self.work_dir),
        }
        self._write_state(final_state)
        return final_state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    def _run_letta_prompt(
        self,
        prompt: str,
        *,
        agent_id: Optional[str],
        conversation_id: Optional[str],
        new_agent: bool,
        new_conversation: bool,
    ) -> Dict[str, Any]:
        cmd = list(self.command)
        cmd.extend(["--backend", self.args.letta_backend, "--output-format", "json", "--memfs-startup", "skip", "--no-skills"])
        if self.args.letta_model:
            cmd.extend(["--model", self.args.letta_model])
        if self.args.letta_toolset:
            cmd.extend(["--toolset", self.args.letta_toolset])
        if new_agent:
            cmd.append("--new-agent")
            if self.args.letta_base_tools:
                cmd.extend(["--base-tools", self.args.letta_base_tools])
        elif agent_id:
            cmd.extend(["--agent", agent_id])
        if conversation_id:
            cmd.extend(["--conversation", conversation_id])
        if new_conversation:
            cmd.append("--new")
        cmd.extend(["-p", prompt])
        env = os.environ.copy()
        if self.args.letta_backend == "local":
            env.setdefault("LETTA_LOCAL_BACKEND_EXPERIMENTAL", "1")
        cwd = self.command_cwd or self.work_dir
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=env,
                text=True,
                capture_output=True,
                timeout=max(30, self.args.letta_timeout_seconds),
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"official Letta command not found: {cmd[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"official Letta command timed out after {self.args.letta_timeout_seconds}s") from exc
        if proc.returncode != 0:
            stderr = proc.stderr[-4000:]
            stdout = proc.stdout[-2000:]
            raise RuntimeError(
                "official Letta command failed; "
                f"returncode={proc.returncode}; stdout_tail={stdout!r}; stderr_tail={stderr!r}"
            )
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = parse_json_object(proc.stdout)
        if not isinstance(parsed, dict):
            raise RuntimeError("official Letta command did not return a JSON object")
        return parsed

    def retrieve(self, row: LoCoMoQAItem) -> BaselineContext:
        result = self._run_letta_prompt(
            letta_question_prompt(row),
            agent_id=str(self.state.get("agent_id") or ""),
            conversation_id=str(self.state.get("conversation_id") or "default")
            if self.args.letta_query_conversation == "ingest"
            else None,
            new_agent=False,
            new_conversation=self.args.letta_query_conversation == "new",
        )
        raw_text = str(result.get("result") or "")
        output = parse_model_json_or_answer(raw_text)
        evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
        answer = str(output.get("answer") or raw_text).strip()
        return BaselineContext(
            candidate_dialog_ids=evidence_dialog_ids,
            context=raw_text,
            direct_answer=answer,
            direct_evidence_dialog_ids=tuple(evidence_dialog_ids),
            trace={
                "retriever": "official_letta_memgpt",
                "official_runtime": "letta-code",
                "agent_id": self.state.get("agent_id"),
                "ingest_conversation_id": self.state.get("conversation_id"),
                "query_conversation_id": result.get("conversation_id"),
                "query_conversation_mode": self.args.letta_query_conversation,
                "candidate_dialog_ids_source": "model_emitted_evidence_dialog_ids",
                "letta_backend": self.args.letta_backend,
                "letta_command_cwd": str(self.command_cwd or self.work_dir),
            },
        )


class MemoryBankSubprocessSampleIndex:
    def __init__(
        self,
        sample: LoCoMoSample,
        rows: Sequence[LoCoMoQAItem],
        args: argparse.Namespace,
        runtime: LLMRuntimeConfig,
    ) -> None:
        self.sample = sample
        self.args = args
        self.runtime = runtime
        self.store_dir = Path(args.baseline_store_dir) / "memory_bank" / sample.sample_id
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.contexts = self._load_or_run_worker(rows)

    def retrieve(self, row: LoCoMoQAItem) -> BaselineContext:
        payload = self.contexts.get(row.question_id)
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"memory_bank worker did not return context for question_id={row.question_id}")
        return BaselineContext(
            candidate_dialog_ids=normalize_output_dialog_ids(payload.get("candidate_dialog_ids")),
            context=str(payload.get("context") or ""),
            direct_answer=str(payload.get("direct_answer") or "").strip(),
            direct_evidence_dialog_ids=tuple(normalize_output_dialog_ids(payload.get("direct_evidence_dialog_ids"))),
            trace=dict(payload.get("trace") if isinstance(payload.get("trace"), Mapping) else {}),
        )

    def _load_or_run_worker(self, rows: Sequence[LoCoMoQAItem]) -> Dict[str, Mapping[str, object]]:
        request_payload = self._request_payload(rows)
        request_hash = short_hash(json.dumps(request_payload, ensure_ascii=False, sort_keys=True))
        request_path = self.store_dir / f"worker_request.{request_hash}.json"
        response_path = self.store_dir / f"worker_response.{request_hash}.json"
        if self.args.reuse_baseline_store and response_path.exists():
            print(f"[memory-bank-official] load_worker_response {response_path}", flush=True)
            return self._read_worker_response(response_path)

        request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n")
        worker_path = BASELINE_DIR / "memory_bank" / "official_worker.py"
        command = self._worker_command(worker_path, request_path, response_path)
        print(
            f"[memory-bank-official] run_worker env={self.args.memory_bank_conda_env or '[current]'} "
            f"questions={len(rows)} request={request_path}",
            flush=True,
        )
        proc = subprocess.run(
            command,
            cwd=str(PROJECT_DIR),
            text=True,
            capture_output=True,
            timeout=max(30, self.args.memory_bank_timeout_seconds),
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "official MemoryBank worker failed; "
                f"returncode={proc.returncode}; stdout_tail={proc.stdout[-3000:]!r}; stderr_tail={proc.stderr[-5000:]!r}"
            )
        if proc.stdout.strip():
            print(proc.stdout[-3000:], flush=True)
        return self._read_worker_response(response_path)

    def _request_payload(self, rows: Sequence[LoCoMoQAItem]) -> Dict[str, object]:
        return {
            "schema_version": "locomo-memory-bank-worker-request-v1",
            "data": str(Path(self.args.data).resolve()),
            "sample_id": self.sample.sample_id,
            "questions": [
                {
                    "question_id": row.question_id,
                    "question": row.question,
                }
                for row in rows
            ],
            "provider": self.runtime.provider,
            "model": self.runtime.model,
            "cache": str(self.runtime.cache_path),
            "use_cache": self.runtime.use_cache,
            "top_k": self.args.top_k,
            "baseline_store_dir": str(Path(self.args.baseline_store_dir).resolve()),
            "reuse_baseline_store": self.args.reuse_baseline_store,
            "memory_bank_official_repo": self.args.memory_bank_official_repo,
            "memory_bank_language": self.args.memory_bank_language,
            "memory_bank_user_name": self.args.memory_bank_user_name,
            "memory_bank_boot_name": self.args.memory_bank_boot_name,
            "memory_bank_initial_strength": self.args.memory_bank_initial_strength,
            "memory_bank_current_date": self.args.memory_bank_current_date,
            "memory_bank_embedding_model": self.args.memory_bank_embedding_model,
            "memory_bank_embedding_device": self.args.memory_bank_embedding_device,
        }

    def _worker_command(self, worker_path: Path, request_path: Path, response_path: Path) -> List[str]:
        if self.args.memory_bank_python:
            command = [self.args.memory_bank_python]
        elif self.args.memory_bank_conda_env:
            command = ["conda", "run", "-n", self.args.memory_bank_conda_env, "python"]
        else:
            command = [sys.executable]
        command.extend([str(worker_path), "--request", str(request_path), "--response", str(response_path)])
        return command

    @staticmethod
    def _read_worker_response(response_path: Path) -> Dict[str, Mapping[str, object]]:
        if not response_path.exists():
            raise RuntimeError(f"official MemoryBank worker did not write response: {response_path}")
        payload = json.loads(response_path.read_text())
        contexts = payload.get("contexts") if isinstance(payload, Mapping) else None
        if not isinstance(contexts, Mapping):
            raise RuntimeError(f"official MemoryBank worker response missing contexts: {response_path}")
        return {str(key): value for key, value in contexts.items() if isinstance(value, Mapping)}


class MemoryOSOfficialSampleIndex:
    def __init__(self, sample: LoCoMoSample, args: argparse.Namespace, runtime: LLMRuntimeConfig) -> None:
        self.sample = sample
        self.args = args
        self.runtime = runtime
        self.user_id = safe_collection_name(args.memoryos_user_id or sample.sample_id)
        self.assistant_id = safe_collection_name(args.memoryos_assistant_id or f"locomo_{sample.sample_id}_assistant")
        self.store_dir = Path(args.baseline_store_dir) / "memoryos" / sample.sample_id
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.ingest_state_path = self.store_dir / "ingest_state.json"
        self.official = load_memoryos_official_runtime(args.memoryos_official_repo)
        embedding_kwargs = parse_json_mapping_arg(args.memoryos_embedding_kwargs, "--memoryos-embedding-kwargs")
        self.memoryos = self.official["Memoryos"](
            user_id=self.user_id,
            openai_api_key=runtime.api_key,
            openai_base_url=runtime.api_base,
            data_storage_path=str(self.store_dir),
            assistant_id=self.assistant_id,
            short_term_capacity=args.memoryos_short_term_capacity,
            mid_term_capacity=args.memoryos_mid_term_capacity,
            long_term_knowledge_capacity=args.memoryos_long_term_knowledge_capacity,
            retrieval_queue_capacity=args.memoryos_retrieval_queue_capacity or args.top_k,
            mid_term_heat_threshold=args.memoryos_mid_term_heat_threshold,
            mid_term_similarity_threshold=args.memoryos_mid_term_similarity_threshold,
            llm_model=args.memoryos_model or runtime.model,
            embedding_model_name=args.memoryos_embedding_model,
            embedding_model_kwargs=embedding_kwargs,
        )
        if args.memoryos_skip_ingest:
            if not self.ingest_state_path.exists():
                raise RuntimeError("--memoryos-skip-ingest requires a reusable MemoryOS ingest_state.json")
        elif not (args.reuse_baseline_store and self._is_ingested()):
            self._ingest()
        else:
            print(f"[memoryos-official] load_ingest_state {self.ingest_state_path}", flush=True)

    def _is_ingested(self) -> bool:
        try:
            payload = json.loads(self.ingest_state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        return bool(payload.get("ingested")) and payload.get("sample_id") == self.sample.sample_id

    def _ingest(self) -> None:
        pairs = memoryos_dialog_pairs_with_ids(self.sample.turns)
        if not pairs:
            raise RuntimeError(f"sample_id={self.sample.sample_id} has no dialog turns to ingest into MemoryOS")
        print(
            f"[memoryos-official] ingest sample_id={self.sample.sample_id} pairs={len(pairs)} "
            f"official_repo={self.official['repo']}",
            flush=True,
        )
        ingested_dialog_ids: List[str] = []
        for index, pair in enumerate(pairs, start=1):
            print(f"[memoryos-official] ingest_pair {index}/{len(pairs)}", flush=True)
            self.memoryos.add_memory(
                user_input=pair["user_input"],
                agent_response=pair["agent_response"],
                timestamp=pair["timestamp"],
                meta_data={"dialog_ids": pair["dialog_ids"]},
            )
            ingested_dialog_ids.extend(pair["dialog_ids"])
        state = {
            "schema_version": "locomo-memoryos-official-ingest-v1",
            "sample_id": self.sample.sample_id,
            "official_repo": str(self.official["repo"]),
            "official_runtime": "BAI-LAB/MemoryOS memoryos-pypi",
            "ingested": True,
            "n_pairs": len(pairs),
            "ingested_dialog_ids": ordered_unique(ingested_dialog_ids),
            "llm_model": self.args.memoryos_model or self.runtime.model,
            "embedding_model": self.args.memoryos_embedding_model,
        }
        self.ingest_state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    def retrieve(self, row: LoCoMoQAItem) -> BaselineContext:
        retrieval_results = self.memoryos.retriever.retrieve_context(
            user_query=row.question,
            user_id=self.user_id,
            segment_similarity_threshold=self.args.memoryos_segment_similarity_threshold,
            page_similarity_threshold=self.args.memoryos_page_similarity_threshold,
            knowledge_threshold=self.args.memoryos_knowledge_threshold,
            top_k_sessions=self.args.memoryos_top_k_sessions,
            top_k_knowledge=self.args.memoryos_top_k_knowledge,
        )
        context_parts = self._format_context_parts(retrieval_results)
        context_text = memoryos_context_text(context_parts)
        candidate_dialog_ids = ordered_unique(re.findall(r"\bD\d+:\d+\b", context_text))
        output_client = make_sharded_client(
            self.runtime,
            "memoryos_official_answer",
            f"{row.question_id}_{short_hash(row.question + context_text)}",
        )
        output = output_client.complete_json(
            memoryos_answer_system_prompt(self.official["prompts"], context_parts),
            memoryos_answer_user_prompt(self.official["prompts"], row, context_parts),
        )
        evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
        return BaselineContext(
            candidate_dialog_ids=candidate_dialog_ids,
            context=context_text,
            direct_answer=str(output.get("answer") or "").strip(),
            direct_evidence_dialog_ids=tuple(evidence_dialog_ids),
            trace={
                "retriever": "official_memoryos",
                "official_runtime": "BAI-LAB/MemoryOS",
                "official_repo": str(self.official["repo"]),
                "official_components": [
                    "memoryos-pypi.memoryos.Memoryos",
                    "ShortTermMemory",
                    "MidTermMemory",
                    "LongTermMemory",
                    "Retriever.retrieve_context",
                    "memoryos-pypi prompts.GENERATE_SYSTEM_RESPONSE_*",
                ],
                "answer_mode": "official_generation_prompt_json_adapter",
                "candidate_dialog_ids_source": "dialog_ids_embedded_in_official_retrieval_context",
                "n_retrieved_pages": len(context_parts["retrieved_pages"]),
                "n_user_knowledge": len(context_parts["retrieved_user_knowledge"]),
                "n_assistant_knowledge": len(context_parts["retrieved_assistant_knowledge"]),
                "embedding_model": self.args.memoryos_embedding_model,
                "llm_model": self.args.memoryos_model or self.runtime.model,
            },
        )

    def _format_context_parts(self, retrieval_results: Mapping[str, Any]) -> Dict[str, Any]:
        retrieved_pages = list(retrieval_results.get("retrieved_pages") or [])
        retrieved_user_knowledge = list(retrieval_results.get("retrieved_user_knowledge") or [])
        retrieved_assistant_knowledge = list(retrieval_results.get("retrieved_assistant_knowledge") or [])
        short_term_history = self.memoryos.short_term_memory.get_all()
        user_profile = self.memoryos.user_long_term_memory.get_raw_user_profile(self.user_id)
        if not user_profile or str(user_profile).lower() == "none":
            user_profile = "No detailed profile available yet."
        return {
            "retrieved_pages": retrieved_pages,
            "retrieved_user_knowledge": retrieved_user_knowledge,
            "retrieved_assistant_knowledge": retrieved_assistant_knowledge,
            "short_term_history": short_term_history,
            "user_profile": user_profile,
            "retrieved_at": retrieval_results.get("retrieved_at"),
        }


class ZepGraphitiSubprocessSampleIndex:
    def __init__(
        self,
        sample: LoCoMoSample,
        rows: Sequence[LoCoMoQAItem],
        args: argparse.Namespace,
        runtime: LLMRuntimeConfig,
    ) -> None:
        self.sample = sample
        self.args = args
        self.runtime = runtime
        self.store_dir = Path(args.baseline_store_dir) / "zep_graphiti" / sample.sample_id
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.contexts = self._load_or_run_worker(rows)

    def retrieve(self, row: LoCoMoQAItem) -> BaselineContext:
        payload = self.contexts.get(row.question_id)
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"zep worker did not return context for question_id={row.question_id}")
        return BaselineContext(
            candidate_dialog_ids=normalize_output_dialog_ids(payload.get("candidate_dialog_ids")),
            context=str(payload.get("context") or ""),
            direct_answer=str(payload.get("direct_answer") or "").strip(),
            direct_evidence_dialog_ids=tuple(normalize_output_dialog_ids(payload.get("direct_evidence_dialog_ids"))),
            trace=dict(payload.get("trace") if isinstance(payload.get("trace"), Mapping) else {}),
        )

    def _load_or_run_worker(self, rows: Sequence[LoCoMoQAItem]) -> Dict[str, Mapping[str, object]]:
        request_payload = self._request_payload(rows)
        request_hash = short_hash(json.dumps(request_payload, ensure_ascii=False, sort_keys=True))
        request_path = self.store_dir / f"worker_request.{request_hash}.json"
        response_path = self.store_dir / f"worker_response.{request_hash}.json"
        if self.args.reuse_baseline_store and response_path.exists():
            print(f"[zep-graphiti-official] load_worker_response {response_path}", flush=True)
            return self._read_worker_response(response_path)

        request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n")
        worker_path = BASELINE_DIR / "graphiti_zep" / "graphiti_official_worker.py"
        command = self._worker_command(worker_path, request_path, response_path)
        print(
            f"[zep-graphiti-official] run_worker env={self.args.zep_conda_env or '[current]'} "
            f"questions={len(rows)} request={request_path}",
            flush=True,
        )
        proc = subprocess.run(
            command,
            cwd=str(PROJECT_DIR),
            text=True,
            capture_output=True,
            timeout=max(30, self.args.zep_timeout_seconds),
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "official Zep/Graphiti worker failed; "
                f"returncode={proc.returncode}; stdout_tail={proc.stdout[-3000:]!r}; stderr_tail={proc.stderr[-5000:]!r}"
            )
        if proc.stdout.strip():
            print(proc.stdout[-3000:], flush=True)
        return self._read_worker_response(response_path)

    def _request_payload(self, rows: Sequence[LoCoMoQAItem]) -> Dict[str, object]:
        return {
            "schema_version": "locomo-zep-graphiti-worker-request-v1",
            "data": str(Path(self.args.data).resolve()),
            "sample_id": self.sample.sample_id,
            "questions": [{"question_id": row.question_id, "question": row.question} for row in rows],
            "provider": self.runtime.provider,
            "model": self.runtime.model,
            "cache": str(self.runtime.cache_path),
            "use_cache": self.runtime.use_cache,
            "top_k": self.args.top_k,
            "baseline_store_dir": str(Path(self.args.baseline_store_dir).resolve()),
            "reuse_baseline_store": self.args.reuse_baseline_store,
            "zep_official_repo": self.args.zep_official_repo,
            "zep_neo4j_uri": self.args.zep_neo4j_uri,
            "zep_neo4j_user": self.args.zep_neo4j_user,
            "zep_neo4j_password": self.args.zep_neo4j_password,
            "zep_neo4j_database": self.args.zep_neo4j_database,
            "zep_group_id": self.args.zep_group_id,
            "zep_graphiti_provider": self.args.zep_graphiti_provider or self.runtime.provider,
            "zep_cross_encoder": self.args.zep_cross_encoder,
            "zep_embedder": self.args.zep_embedder,
            "zep_bge_embedding_model": self.args.zep_bge_embedding_model,
            "zep_search_config": self.args.zep_search_config,
            "zep_skip_ingest": self.args.zep_skip_ingest,
            "zep_ingest_limit": self.args.zep_ingest_limit,
        }

    def _worker_command(self, worker_path: Path, request_path: Path, response_path: Path) -> List[str]:
        if self.args.zep_python:
            command = [self.args.zep_python]
        elif self.args.zep_conda_env:
            command = ["conda", "run", "-n", self.args.zep_conda_env, "python"]
        else:
            command = [sys.executable]
        command.extend([str(worker_path), "--request", str(request_path), "--response", str(response_path)])
        return command

    @staticmethod
    def _read_worker_response(response_path: Path) -> Dict[str, Mapping[str, object]]:
        if not response_path.exists():
            raise RuntimeError(f"official Zep/Graphiti worker did not write response: {response_path}")
        payload = json.loads(response_path.read_text())
        contexts = payload.get("contexts") if isinstance(payload, Mapping) else None
        if not isinstance(contexts, Mapping):
            raise RuntimeError(f"official Zep/Graphiti worker response missing contexts: {response_path}")
        return {str(key): value for key, value in contexts.items() if isinstance(value, Mapping)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LoCoMo QA memory baselines.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--variants", nargs="+", default=["full_text", "rag"], choices=SUPPORTED_VARIANTS)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=24)
    parser.add_argument("--answer-workers", type=int, default=2)
    parser.add_argument("--cache", default=str(EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_memory_baselines.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output", default=str(EXTERNAL_RESULT_DIR / "results_locomo_qa_memory_baselines.json"))
    parser.add_argument("--baseline-store-dir", default=str(PROJECT_DIR / "Graph/output/baseline_store/locomo_qa"))
    parser.add_argument("--reuse-baseline-store", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate selected rows and variants without LLM or embedding calls.")
    parser.add_argument("--rag-chunk-target-chars", type=int, default=900)
    parser.add_argument("--rag-chunk-overlap-turns", type=int, default=1)
    parser.add_argument("--rag-embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--rag-embedding-base-url", default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", ""))
    parser.add_argument("--rag-embedding-cache", default=str(EXTERNAL_CACHE_DIR / "embedding_cache.locomo_qa_rag.json"))
    parser.add_argument("--rag-embedding-batch-size", type=int, default=64)
    parser.add_argument("--mem0-skip-ingest", action="store_true")
    parser.add_argument("--mem0-ingest-limit", type=int, default=0)
    parser.add_argument("--mem0-start-index", type=int, default=1)
    parser.add_argument("--mem0-add-retries", type=int, default=6)
    parser.add_argument("--mem0-retry-sleep", type=int, default=60)
    parser.add_argument("--mem0-llm-provider", default="")
    parser.add_argument("--mem0-embedder-provider", default="openai")
    parser.add_argument("--mem0-embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--mem0-embedding-base-url", default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", ""))
    parser.add_argument("--mem0-embedding-dims", type=int, default=1536)
    parser.add_argument("--mem0-vector-store-provider", choices=("qdrant",), default="qdrant")
    parser.add_argument("--letta-command", default=os.environ.get("LETTA_COMMAND", ""))
    parser.add_argument("--letta-code-repo", default=os.environ.get("LETTA_CODE_REPO", ""))
    parser.add_argument("--letta-backend", choices=("local", "api"), default=os.environ.get("LETTA_BACKEND", "local"))
    parser.add_argument("--letta-model", default=os.environ.get("LETTA_MODEL", ""))
    parser.add_argument("--letta-agent-id", default=os.environ.get("LETTA_AGENT_ID", ""))
    parser.add_argument("--letta-conversation-id", default=os.environ.get("LETTA_CONVERSATION_ID", ""))
    parser.add_argument("--letta-skip-ingest", action="store_true")
    parser.add_argument("--letta-ingest-chunk-turns", type=int, default=10)
    parser.add_argument("--letta-timeout-seconds", type=int, default=900)
    parser.add_argument("--letta-toolset", choices=("auto", "codex", "default", "gemini"), default=os.environ.get("LETTA_TOOLSET", "auto"))
    parser.add_argument("--letta-base-tools", default=os.environ.get("LETTA_BASE_TOOLS", "memory"))
    parser.add_argument("--letta-query-conversation", choices=("new", "ingest"), default="new")
    parser.add_argument("--memory-bank-official-repo", default=os.environ.get("MEMORY_BANK_OFFICIAL_REPO", ""))
    parser.add_argument("--memory-bank-language", choices=("en", "cn"), default="en")
    parser.add_argument("--memory-bank-user-name", default="")
    parser.add_argument("--memory-bank-boot-name", default="AI")
    parser.add_argument("--memory-bank-initial-strength", type=float, default=1.0)
    parser.add_argument("--memory-bank-current-date", default="")
    parser.add_argument("--memory-bank-embedding-model", default=os.environ.get("MEMORY_BANK_EMBEDDING_MODEL", "minilm-l6"))
    parser.add_argument("--memory-bank-embedding-device", default=os.environ.get("MEMORY_BANK_EMBEDDING_DEVICE", "cpu"))
    parser.add_argument("--memory-bank-conda-env", default=os.environ.get("MEMORY_BANK_CONDA_ENV", "locomo_memorybank"))
    parser.add_argument("--memory-bank-python", default=os.environ.get("MEMORY_BANK_PYTHON", ""))
    parser.add_argument("--memory-bank-timeout-seconds", type=int, default=int(os.environ.get("MEMORY_BANK_TIMEOUT_SECONDS", "7200")))
    parser.add_argument("--memoryos-official-repo", default=os.environ.get("MEMORYOS_OFFICIAL_REPO", "/tmp/codex-official-memoryos"))
    parser.add_argument("--memoryos-user-id", default=os.environ.get("MEMORYOS_USER_ID", ""))
    parser.add_argument("--memoryos-assistant-id", default=os.environ.get("MEMORYOS_ASSISTANT_ID", ""))
    parser.add_argument("--memoryos-model", default=os.environ.get("MEMORYOS_MODEL", ""))
    parser.add_argument("--memoryos-embedding-model", default=os.environ.get("MEMORYOS_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    parser.add_argument("--memoryos-embedding-kwargs", default=os.environ.get("MEMORYOS_EMBEDDING_KWARGS", ""))
    parser.add_argument("--memoryos-short-term-capacity", type=int, default=int(os.environ.get("MEMORYOS_SHORT_TERM_CAPACITY", "7")))
    parser.add_argument("--memoryos-mid-term-capacity", type=int, default=int(os.environ.get("MEMORYOS_MID_TERM_CAPACITY", "2000")))
    parser.add_argument("--memoryos-long-term-knowledge-capacity", type=int, default=int(os.environ.get("MEMORYOS_LONG_TERM_KNOWLEDGE_CAPACITY", "100")))
    parser.add_argument("--memoryos-retrieval-queue-capacity", type=int, default=int(os.environ.get("MEMORYOS_RETRIEVAL_QUEUE_CAPACITY", "0")))
    parser.add_argument("--memoryos-mid-term-heat-threshold", type=float, default=float(os.environ.get("MEMORYOS_MID_TERM_HEAT_THRESHOLD", "5.0")))
    parser.add_argument("--memoryos-mid-term-similarity-threshold", type=float, default=float(os.environ.get("MEMORYOS_MID_TERM_SIMILARITY_THRESHOLD", "0.6")))
    parser.add_argument("--memoryos-segment-similarity-threshold", type=float, default=float(os.environ.get("MEMORYOS_SEGMENT_SIMILARITY_THRESHOLD", "0.1")))
    parser.add_argument("--memoryos-page-similarity-threshold", type=float, default=float(os.environ.get("MEMORYOS_PAGE_SIMILARITY_THRESHOLD", "0.1")))
    parser.add_argument("--memoryos-knowledge-threshold", type=float, default=float(os.environ.get("MEMORYOS_KNOWLEDGE_THRESHOLD", "0.01")))
    parser.add_argument("--memoryos-top-k-sessions", type=int, default=int(os.environ.get("MEMORYOS_TOP_K_SESSIONS", "5")))
    parser.add_argument("--memoryos-top-k-knowledge", type=int, default=int(os.environ.get("MEMORYOS_TOP_K_KNOWLEDGE", "20")))
    parser.add_argument("--memoryos-skip-ingest", action="store_true")
    parser.add_argument("--zep-official-repo", default=os.environ.get("ZEP_GRAPHITI_OFFICIAL_REPO", "/tmp/evermem_baseline_repos/graphiti"))
    parser.add_argument("--zep-conda-env", default=os.environ.get("ZEP_CONDA_ENV", "py311"))
    parser.add_argument("--zep-python", default=os.environ.get("ZEP_PYTHON", ""))
    parser.add_argument("--zep-timeout-seconds", type=int, default=int(os.environ.get("ZEP_TIMEOUT_SECONDS", "7200")))
    parser.add_argument("--zep-neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--zep-neo4j-user", default=os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--zep-neo4j-password", default=os.environ.get("NEO4J_PASSWORD", ""))
    parser.add_argument("--zep-neo4j-database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--zep-group-id", default=os.environ.get("ZEP_GROUP_ID", ""))
    parser.add_argument("--zep-graphiti-provider", choices=("openai", "deepseek", ""), default=os.environ.get("ZEP_GRAPHITI_PROVIDER", ""))
    parser.add_argument("--zep-cross-encoder", choices=("auto", "openai", "bge"), default=os.environ.get("ZEP_CROSS_ENCODER", "auto"))
    parser.add_argument("--zep-embedder", choices=("auto", "openai", "bge"), default=os.environ.get("ZEP_EMBEDDER", "auto"))
    parser.add_argument("--zep-bge-embedding-model", default=os.environ.get("ZEP_BGE_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))
    parser.add_argument(
        "--zep-search-config",
        choices=("combined_cross_encoder", "combined_rrf", "edge_rrf"),
        default=os.environ.get("ZEP_SEARCH_CONFIG", "combined_cross_encoder"),
    )
    parser.add_argument("--zep-skip-ingest", action="store_true")
    parser.add_argument("--zep-ingest-limit", type=int, default=int(os.environ.get("ZEP_INGEST_LIMIT", "0")))
    return parser.parse_args()


def select_rows(
    rows: Sequence[LoCoMoQAItem],
    question_types: Sequence[str],
    limit_cases: int,
    limit_per_type: int,
) -> List[LoCoMoQAItem]:
    selected = list(rows)
    if question_types:
        allowed = {normalize_question_type(item) for item in question_types}
        selected = [row for row in selected if row.question_type in allowed]
    if limit_per_type:
        counts: Counter[str] = Counter()
        limited: List[LoCoMoQAItem] = []
        for row in selected:
            if counts[row.question_type] >= limit_per_type:
                continue
            limited.append(row)
            counts[row.question_type] += 1
        selected = limited
    if limit_cases:
        selected = selected[:limit_cases]
    return selected


def normalize_question_type(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "multi": "multi-hop",
        "multi-hop-qa": "multi-hop",
        "open": "open-domain",
        "open-domain-knowledge": "open-domain",
        "commonsense": "open-domain",
        "common-sense": "open-domain",
        "single": "single-hop",
        "single-hop-qa": "single-hop",
        "time": "temporal",
        "temporal-reasoning": "temporal",
        "false-premise": "adversarial",
    }
    return aliases.get(normalized, normalized)


def turn_document(turn: DialogTurn) -> str:
    return " ".join(
        str(part or "")
        for part in (
            turn.dia_id,
            turn.session_id,
            turn.session_date_time,
            turn.speaker,
            turn.text,
            turn.image_caption,
            turn.image_query,
        )
    )


def embedding_chunk_document(turns: Sequence[DialogTurn]) -> str:
    lines: List[str] = []
    for turn in turns:
        lines.append(f"[{turn.dia_id} | {turn.session_date_time} | {turn.speaker}] {turn.text}")
        if turn.image_caption:
            lines.append(f"[{turn.dia_id} image_caption] {turn.image_caption}")
        if turn.image_query:
            lines.append(f"[{turn.dia_id} image_query] {turn.image_query}")
    return "\n".join(lines)


def chunk_turns_by_chars(
    turns: Sequence[DialogTurn],
    *,
    target_chars: int,
    overlap_turns: int,
) -> List[List[DialogTurn]]:
    target = max(200, target_chars)
    overlap = max(0, overlap_turns)
    chunks: List[List[DialogTurn]] = []
    current: List[DialogTurn] = []
    current_chars = 0
    for turn in turns:
        turn_chars = max(1, len(embedding_chunk_document([turn])))
        if current and current_chars + turn_chars > target:
            chunks.append(list(current))
            current = current[-overlap:] if overlap else []
            current_chars = sum(max(1, len(embedding_chunk_document([item]))) for item in current)
            if current and current_chars + turn_chars > target:
                current = []
                current_chars = 0
        current.append(turn)
        current_chars += turn_chars
    if current:
        chunks.append(list(current))
    return chunks


def chunk_turns_by_count(turns: Sequence[DialogTurn], chunk_size: int) -> List[List[DialogTurn]]:
    size = max(1, chunk_size)
    return [list(turns[index : index + size]) for index in range(0, len(turns), size)]


def resolve_letta_command(args: argparse.Namespace) -> Tuple[List[str], Optional[Path]]:
    if args.letta_command:
        return shlex.split(args.letta_command), None
    letta_bin = shutil.which("letta")
    if letta_bin:
        return [letta_bin], None
    if args.letta_code_repo:
        repo = Path(args.letta_code_repo).expanduser().resolve()
        entrypoint = repo / "src/index.ts"
        if not entrypoint.exists():
            raise RuntimeError(f"--letta-code-repo does not look like letta-ai/letta-code: missing {entrypoint}")
        if not shutil.which("bun"):
            raise RuntimeError("--letta-code-repo requires bun on PATH")
        return ["bun", "run", str(entrypoint)], repo
    raise RuntimeError(
        "memgpt official variant requires the official Letta Code CLI. "
        "Install @letta-ai/letta-code so `letta` is on PATH, or pass --letta-code-repo /path/to/letta-code."
    )


def letta_ingest_prompt(sample: LoCoMoSample, turns: Sequence[DialogTurn], chunk_index: int, n_chunks: int) -> str:
    return (
        "You are an official Letta/MemGPT memory agent being prepared for a LoCoMo QA evaluation.\n"
        "Ingest the following conversation chunk into your memory and conversation history. "
        "Preserve dialog IDs, speakers, dates, image captions, user preferences, events, and factual details. "
        "This is an ingestion turn only; do not answer any benchmark question yet.\n\n"
        f"Sample ID: {sample.sample_id}\n"
        f"Chunk: {chunk_index}/{n_chunks}\n\n"
        f"{format_turn_context(turns)}"
    )


def letta_question_prompt(row: LoCoMoQAItem) -> str:
    return (
        "Answer the LoCoMo QA question using only the conversation previously ingested into this Letta agent. "
        "Use your official memory and message-search mechanisms when needed. Do not use files, benchmark data, "
        "gold answers, gold evidence, categories, or question-type labels.\n\n"
        f"Question ID: {row.question_id}\n"
        f"Question: {row.question}\n\n"
        "Return strict JSON only:\n"
        "{\"answer\":\"short answer\", \"evidence_dialog_ids\":[\"D1:1\"]}"
    )


def parse_model_json_or_answer(text: str) -> Dict[str, object]:
    try:
        return parse_json_object(text)
    except Exception:
        return {"answer": text.strip(), "evidence_dialog_ids": []}


def load_memory_bank_official_prompts(repo_path: str) -> Dict[str, Any]:
    if not repo_path:
        raise RuntimeError(
            "memory_bank official variant requires --memory-bank-official-repo "
            "pointing to zhongwanjun/MemoryBank-SiliconFriend"
        )
    repo = Path(repo_path).expanduser().resolve()
    summary_path = repo / "memory_bank/summarize_memory.py"
    if not summary_path.exists():
        raise RuntimeError(f"--memory-bank-official-repo missing {summary_path}")
    spec = importlib.util.spec_from_file_location("official_memory_bank_summarize_memory", summary_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load official MemoryBank prompts from {summary_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = [
        "summarize_content_prompt",
        "summarize_person_prompt",
        "summarize_overall_prompt",
        "summarize_overall_personality",
    ]
    prompts: Dict[str, Any] = {}
    for name in required:
        value = getattr(module, name, None)
        if not callable(value):
            raise RuntimeError(f"official MemoryBank repo missing callable {name}")
        prompts[name] = value
    return prompts


def load_memory_bank_official_runtime(repo_path: str) -> Dict[str, Any]:
    if not repo_path:
        raise RuntimeError(
            "memory_bank official variant requires --memory-bank-official-repo "
            "pointing to zhongwanjun/MemoryBank-SiliconFriend"
        )
    repo = Path(repo_path).expanduser().resolve()
    memory_bank_dir = repo / "memory_bank"
    forget_path = memory_bank_dir / "memory_retrieval/forget_memory.py"
    if not forget_path.exists():
        raise RuntimeError(f"--memory-bank-official-repo missing {forget_path}")
    if str(memory_bank_dir) not in sys.path:
        sys.path.insert(0, str(memory_bank_dir))
    spec = importlib.util.spec_from_file_location("official_memory_bank_forget_memory", forget_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load official MemoryBank runtime from {forget_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = {
        "repo": repo,
        "prompts": load_memory_bank_official_prompts(str(repo)),
        "LocalMemoryRetrieval": getattr(module, "LocalMemoryRetrieval", None),
        "MemoryForgetterLoader": getattr(module, "MemoryForgetterLoader", None),
    }
    if runtime["LocalMemoryRetrieval"] is None or runtime["MemoryForgetterLoader"] is None:
        raise RuntimeError("official MemoryBank repo is missing LocalMemoryRetrieval or MemoryForgetterLoader")
    return runtime


def load_memoryos_official_runtime(repo_path: str) -> Dict[str, Any]:
    if not repo_path:
        raise RuntimeError("memoryos official variant requires --memoryos-official-repo pointing to BAI-LAB/MemoryOS")
    repo = Path(repo_path).expanduser().resolve()
    package_dir = repo / "memoryos-pypi"
    memoryos_path = package_dir / "memoryos.py"
    prompts_path = package_dir / "prompts.py"
    if not memoryos_path.exists() or not prompts_path.exists():
        raise RuntimeError(f"--memoryos-official-repo does not look like BAI-LAB/MemoryOS: missing {memoryos_path}")
    if str(package_dir) not in sys.path:
        sys.path.insert(0, str(package_dir))
    memoryos_module = importlib.import_module("memoryos")
    prompts_module = importlib.import_module("prompts")
    memoryos_cls = getattr(memoryos_module, "Memoryos", None)
    if memoryos_cls is None:
        raise RuntimeError(f"official MemoryOS repo is missing Memoryos class at {memoryos_path}")
    return {
        "repo": repo,
        "package_dir": package_dir,
        "Memoryos": memoryos_cls,
        "prompts": prompts_module,
    }


def parse_json_mapping_arg(value: str, flag_name: str) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{flag_name} must be a JSON object") from exc
    if not isinstance(parsed, Mapping):
        raise RuntimeError(f"{flag_name} must be a JSON object")
    return dict(parsed)


def official_memory_bank_dialog_pairs_with_ids(turns: Sequence[DialogTurn]) -> Tuple[List[Dict[str, str]], List[Tuple[str, ...]]]:
    pairs: List[Dict[str, str]] = []
    pair_dialog_ids: List[Tuple[str, ...]] = []
    index = 0
    while index < len(turns):
        first = turns[index]
        second = turns[index + 1] if index + 1 < len(turns) else None
        dialog_ids = [first.dia_id]
        query = f"{first.dia_id} {first.speaker}: {first.text}"
        if first.image_caption:
            query += f" Image caption: {first.image_caption}"
        if first.image_query:
            query += f" Image search query: {first.image_query}"
        if second is None:
            response = ""
            index += 1
        else:
            response = f"{second.dia_id} {second.speaker}: {second.text}"
            dialog_ids.append(second.dia_id)
            if second.image_caption:
                response += f" Image caption: {second.image_caption}"
            if second.image_query:
                response += f" Image search query: {second.image_query}"
            index += 2
        pairs.append({"query": query, "response": response})
        pair_dialog_ids.append(tuple(dialog_ids))
    return pairs, pair_dialog_ids


def memoryos_dialog_pairs_with_ids(turns: Sequence[DialogTurn]) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    index = 0
    while index < len(turns):
        first = turns[index]
        second = turns[index + 1] if index + 1 < len(turns) else None
        dialog_ids = [first.dia_id]
        user_input = memoryos_turn_text(first)
        if second is None:
            agent_response = ""
            timestamp = locomo_memoryos_timestamp(first.session_date_time)
            index += 1
        else:
            dialog_ids.append(second.dia_id)
            agent_response = memoryos_turn_text(second)
            timestamp = locomo_memoryos_timestamp(second.session_date_time or first.session_date_time)
            index += 2
        pairs.append(
            {
                "user_input": user_input,
                "agent_response": agent_response,
                "timestamp": timestamp,
                "dialog_ids": dialog_ids,
            }
        )
    return pairs


def memoryos_turn_text(turn: DialogTurn) -> str:
    text = f"{turn.dia_id} {turn.speaker}: {turn.text}"
    if turn.image_caption:
        text += f"\nImage caption: {turn.image_caption}"
    if turn.image_query:
        text += f"\nImage search query: {turn.image_query}"
    text += f"\nSession: {turn.session_id}; Time: {turn.session_date_time}"
    return text


def locomo_memoryos_timestamp(value: str) -> str:
    parsed = parse_session_date(value)
    if parsed is None:
        return "1970-01-01 00:00:00"
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def format_official_memorybank_recall(related_memos: Sequence[str], sources: Sequence[str]) -> str:
    chunks: List[str] = []
    for index, memo in enumerate(related_memos, start=1):
        source = sources[index - 1] if index - 1 < len(sources) else ""
        chunks.append(f"[{index}] source={source or '[unknown]'}\n{memo}")
    return "\n\n".join(chunks) or "[none]"


def memory_bank_date_key(session: Session) -> str:
    parsed = parse_session_date(session.date_time)
    if parsed is not None:
        return parsed.date().isoformat()
    return session.date_time or session.session_id


def memory_bank_official_summary_system_prompt(language: str) -> str:
    if language == "cn":
        return "以下是一个人类和一个聪明、懂心理学的AI助手之间的对话记录。"
    return "Below is a transcript of a conversation between a human and an AI assistant that is intelligent and knowledgeable in psychology."


def memory_bank_official_summary_messages(language: str, prompt: str) -> List[Dict[str, str]]:
    if language == "cn":
        return [
            {"role": "system", "content": memory_bank_official_summary_system_prompt(language)},
            {"role": "user", "content": "你好！请帮我对对话内容归纳总结"},
            {"role": "system", "content": "好的，我会尽力帮你的。"},
            {"role": "user", "content": prompt},
        ]
    return [
        {"role": "system", "content": memory_bank_official_summary_system_prompt(language)},
        {"role": "user", "content": "Hello! Please help me summarize the content of the conversation."},
        {"role": "system", "content": "Sure, I will do my best to assist you."},
        {"role": "user", "content": prompt},
    ]


def memory_bank_official_complete_text(client: LLMClient, language: str, prompt: str) -> str:
    return client.complete_text_messages(memory_bank_official_summary_messages(language, prompt))


def memory_bank_official_answer_system_prompt() -> str:
    return (
        "You answer LoCoMo QA questions from MemoryBank memories. "
        "Use only the provided MemoryBank summaries and recalled memories. "
        "Return strict JSON with keys answer and evidence_dialog_ids."
    )


def memory_bank_official_answer_user_prompt(row: LoCoMoQAItem, store: Mapping[str, Any], memory_context: str) -> str:
    return (
        "MemoryBank overall history:\n"
        f"{store.get('overall_history') or '[none]'}\n\n"
        "MemoryBank overall personality / response strategy:\n"
        f"{store.get('overall_personality') or '[none]'}\n\n"
        "Recalled MemoryBank memories:\n"
        f"{memory_context}\n\n"
        f"Question ID: {row.question_id}\n"
        f"Question: {row.question}\n\n"
        "Do not use benchmark gold answers, gold evidence, categories, or question-type labels. "
        "Cite only dialog IDs present in recalled memories. Return JSON only:\n"
        "{\"answer\":\"short answer\", \"evidence_dialog_ids\":[\"D1:1\"]}"
    )


def memoryos_context_text(parts: Mapping[str, Any]) -> str:
    chunks: List[str] = []
    chunks.append("Short-term history:")
    short_history = parts.get("short_term_history") if isinstance(parts.get("short_term_history"), list) else []
    if short_history:
        for rank, item in enumerate(short_history, start=1):
            if not isinstance(item, Mapping):
                continue
            chunks.append(
                f"[short {rank}]\n"
                f"User: {item.get('user_input', '')}\n"
                f"Assistant: {item.get('agent_response', '')}\n"
                f"Time: {item.get('timestamp', '')}"
            )
    else:
        chunks.append("[none]")

    chunks.append("\nRetrieved mid-term pages:")
    pages = parts.get("retrieved_pages") if isinstance(parts.get("retrieved_pages"), list) else []
    if pages:
        for rank, page in enumerate(pages, start=1):
            if not isinstance(page, Mapping):
                continue
            chunks.append(
                f"[page {rank} id={page.get('page_id', '')}]\n"
                f"User: {page.get('user_input', '')}\n"
                f"Assistant: {page.get('agent_response', '')}\n"
                f"Time: {page.get('timestamp', '')}\n"
                f"Conversation chain overview: {page.get('meta_info', 'N/A')}"
            )
    else:
        chunks.append("[none]")

    chunks.append("\nUser profile:")
    chunks.append(str(parts.get("user_profile") or "[none]"))

    chunks.append("\nRetrieved user long-term knowledge:")
    user_knowledge = parts.get("retrieved_user_knowledge") if isinstance(parts.get("retrieved_user_knowledge"), list) else []
    if user_knowledge:
        for rank, item in enumerate(user_knowledge, start=1):
            if isinstance(item, Mapping):
                chunks.append(f"[user knowledge {rank}] {item.get('knowledge', '')} (Recorded: {item.get('timestamp', '')})")
    else:
        chunks.append("[none]")

    chunks.append("\nRetrieved assistant long-term knowledge:")
    assistant_knowledge = (
        parts.get("retrieved_assistant_knowledge") if isinstance(parts.get("retrieved_assistant_knowledge"), list) else []
    )
    if assistant_knowledge:
        for rank, item in enumerate(assistant_knowledge, start=1):
            if isinstance(item, Mapping):
                chunks.append(f"[assistant knowledge {rank}] {item.get('knowledge', '')} (Recorded: {item.get('timestamp', '')})")
    else:
        chunks.append("[none]")
    return "\n".join(chunks)


def memoryos_answer_system_prompt(prompts_module: object, parts: Mapping[str, Any]) -> str:
    assistant_knowledge = "【Assistant Knowledge Base】\n"
    for item in parts.get("retrieved_assistant_knowledge") or []:
        if isinstance(item, Mapping):
            assistant_knowledge += f"- {item.get('knowledge', '')} (Recorded: {item.get('timestamp', '')})\n"
    if assistant_knowledge.strip() == "【Assistant Knowledge Base】":
        assistant_knowledge += "- No relevant assistant knowledge found for this query.\n"
    meta_data_text = "LoCoMo QA evaluation turn. No benchmark gold answers, evidence IDs, categories, or question-type labels are available."
    base_prompt = prompts_module.GENERATE_SYSTEM_RESPONSE_SYSTEM_PROMPT.format(
        relationship="memory QA assistant",
        assistant_knowledge_text=assistant_knowledge,
        meta_data_text=meta_data_text,
    )
    return (
        f"{base_prompt}\n"
        "For this evaluation, answer the user's question using only the supplied MemoryOS context. "
        "Return strict JSON only with keys answer and evidence_dialog_ids. "
        "Cite only dialog IDs that appear in the MemoryOS context."
    )


def memoryos_answer_user_prompt(prompts_module: object, row: LoCoMoQAItem, parts: Mapping[str, Any]) -> str:
    history_text = "\n".join(
        f"User: {item.get('user_input', '')}\nAssistant: {item.get('agent_response', '')} (Time: {item.get('timestamp', '')})"
        for item in (parts.get("short_term_history") or [])
        if isinstance(item, Mapping)
    )
    retrieval_text = "\n".join(
        "【Historical Memory】\n"
        f"User: {page.get('user_input', '')}\n"
        f"Assistant: {page.get('agent_response', '')}\n"
        f"Time: {page.get('timestamp', '')}\n"
        f"Conversation chain overview: {page.get('meta_info', 'N/A')}"
        for page in (parts.get("retrieved_pages") or [])
        if isinstance(page, Mapping)
    )
    user_knowledge_background = ""
    for item in parts.get("retrieved_user_knowledge") or []:
        if isinstance(item, Mapping):
            user_knowledge_background += f"- {item.get('knowledge', '')} (Recorded: {item.get('timestamp', '')})\n"
    background = f"【User Profile】\n{parts.get('user_profile') or '[none]'}\n【Relevant User Knowledge Entries】\n{user_knowledge_background or '[none]'}"
    base_prompt = prompts_module.GENERATE_SYSTEM_RESPONSE_USER_PROMPT.format(
        history_text=history_text or "[none]",
        retrieval_text=retrieval_text or "[none]",
        background=background,
        relationship="memory QA assistant",
        query=row.question,
    )
    return (
        f"{base_prompt}\n\n"
        f"Question ID: {row.question_id}\n"
        f"Question: {row.question}\n\n"
        "Do not use benchmark gold answers, gold evidence, categories, or question-type labels. "
        "Return JSON only:\n"
        "{\"answer\":\"short answer\", \"evidence_dialog_ids\":[\"D1:1\"]}"
    )


def memory_bank_current_date(sample: LoCoMoSample, args: argparse.Namespace) -> str:
    if args.memory_bank_current_date:
        return args.memory_bank_current_date
    dates = [parse_session_date(turn.session_date_time) for turn in sample.turns]
    dates = [date for date in dates if date is not None]
    if not dates:
        return "1970-01-01"
    return max(dates).date().isoformat()


def parse_session_date(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M%p on %d %B, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def tsm_event_from_turn(sample_id: str, turn: DialogTurn) -> LoCoMoTSMEvent:
    content = f"{turn.speaker}: {turn.text}"
    if turn.image_caption:
        content += f"\nImage caption: {turn.image_caption}"
    if turn.image_query:
        content += f"\nImage search query: {turn.image_query}"
    event_time = locomo_session_time_iso(turn.session_date_time)
    return LoCoMoTSMEvent(
        event_id=turn.dia_id,
        scope_id=sample_id,
        content=content,
        event_type="dialog_turn",
        occurred_at=event_time,
        mentioned_at=event_time,
        updated_at=event_time,
        source_id=turn.dia_id,
        metadata={
            "sample_id": sample_id,
            "session_id": turn.session_id,
            "session_index": turn.session_index,
            "session_date_time": turn.session_date_time,
            "speaker": turn.speaker,
        },
    )


def locomo_session_time_iso(value: str) -> str:
    text = str(value or "").strip()
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M%p on %d %B, %Y"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return "1970-01-01T00:00:00"


def tsm_context_from_spec(spec: object) -> str:
    visible_events = getattr(spec, "visible_events", [])
    return (
        "TSM instruction:\n"
        f"{getattr(spec, 'instruction', '')}\n\n"
        "TSM visible events:\n"
        f"{json.dumps(visible_events, ensure_ascii=False, indent=2)}"
    )


def save_tsm_index(index: TSMIndex, path: Path) -> None:
    payload = {
        "events": [asdict(event) for event in index.events],
        "entity_nodes": {key: asdict(value) for key, value in index.entity_nodes.items()},
        "temporal_facts": [asdict(fact) for fact in index.temporal_facts],
        "durative_memories": [asdict(memory) for memory in index.durative_memories],
        "fact_event_index": {key: list(value) for key, value in index.fact_event_index.items()},
        "construction_mode": index.construction_mode,
        "construction_notes": list(index.construction_notes),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_tsm_index(path: Path) -> TSMIndex:
    payload = json.loads(path.read_text())
    events = [LoCoMoTSMEvent(**item) for item in payload.get("events", [])]
    return TSMIndex(
        events=events,
        events_by_id={event.event_id: event for event in events},
        entity_nodes={key: EntityNode(**value) for key, value in payload.get("entity_nodes", {}).items()},
        temporal_facts=[TemporalFact(**item) for item in payload.get("temporal_facts", [])],
        durative_memories=[DurativeMemory(**item) for item in payload.get("durative_memories", [])],
        fact_event_index={key: list(value) for key, value in payload.get("fact_event_index", {}).items()},
        construction_mode=str(payload.get("construction_mode") or "llm"),
        construction_notes=list(payload.get("construction_notes") or []),
    )


def format_turn_context(turns: Sequence[DialogTurn]) -> str:
    chunks: List[str] = []
    for rank, turn in enumerate(turns, start=1):
        chunks.append(
            "\n".join(
                [
                    f'<dialog rank="{rank}" id="{turn.dia_id}" session_id="{turn.session_id}" date="{turn.session_date_time}" speaker="{turn.speaker}">',
                    turn.text,
                    f"Image caption: {turn.image_caption}" if turn.image_caption else "",
                    f"Image search query: {turn.image_query}" if turn.image_query else "",
                    "</dialog>",
                ]
            ).replace("\n\n", "\n")
        )
    return "\n\n".join(chunks)


def full_text_context(sample: LoCoMoSample) -> BaselineContext:
    turns = sorted(sample.turns, key=lambda turn: dialog_sort_key(turn.dia_id))
    return BaselineContext(
        candidate_dialog_ids=[turn.dia_id for turn in turns],
        context=format_turn_context(turns),
        trace={
            "retriever": "full_text",
            "n_turns": len(turns),
        },
    )


def answer_system_prompt() -> str:
    return (
        "You answer LoCoMo QA questions using only the provided baseline context. "
        "Return strict JSON with keys answer and evidence_dialog_ids. "
        "Keep the answer as a short gold-style phrase, date, name, or comma-separated list. "
        "For open-domain questions, ordinary commonsense may be used only as a bridge from cited conversation facts. "
        "For false-premise or unavailable information, answer exactly \"No information available\" or "
        "\"Not mentioned in the conversation\". Cite only dialog IDs present in the context."
    )


def answer_user_prompt(row: LoCoMoQAItem, variant: str, context: BaselineContext) -> str:
    return (
        f"Benchmark: LoCoMo QA\n"
        f"Variant: {variant}\n"
        f"Sample ID: {row.sample_id}\n"
        f"Question ID: {row.question_id}\n"
        f"Question: {row.question}\n\n"
        f"Baseline context:\n{context.context or '[none]'}\n\n"
        "Answer rules:\n"
        "- Use the cited dialog turns to support the answer.\n"
        "- For temporal questions, compute relative dates from session dates when needed.\n"
        "- For open-domain questions, infer only from cited conversation facts plus ordinary commonsense.\n"
        "- For multi-answer questions, return the complete requested set as comma-separated short phrases.\n"
        "- If evidence is missing or contradicts the premise, abstain with the exact unavailable phrase.\n\n"
        "Respond as JSON only:\n"
        "{\"answer\": \"...\", \"evidence_dialog_ids\": [\"D1:1\"]}"
    )


def make_sharded_client(runtime: LLMRuntimeConfig, stage: str, shard_name: str) -> LLMClient:
    return LLMClient(
        provider=runtime.provider,
        model=runtime.model,
        api_key=runtime.api_key,
        api_base=runtime.api_base,
        cache_path=shard_cache_path(runtime.cache_path, stage, shard_name),
        use_cache=runtime.use_cache,
    )


def normalize_output_dialog_ids(value: object) -> List[str]:
    ids = normalize_dialog_ids(value)
    expanded: List[str] = []
    for item in ids:
        if "," in item:
            expanded.extend(part.strip() for part in item.split(","))
        else:
            expanded.append(item)
    return ordered_unique(item for item in expanded if re.match(r"D\d+:\d+", item))


def mem0_llm_config(args: argparse.Namespace, runtime: LLMRuntimeConfig) -> Dict[str, object]:
    provider = args.mem0_llm_provider or runtime.provider
    if provider == "deepseek":
        return {
            "model": runtime.model,
            "api_key": runtime.api_key,
            "deepseek_base_url": runtime.api_base,
            "temperature": 0.0,
            "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        }
    if provider == "openai":
        return {
            "model": runtime.model,
            "api_key": runtime.api_key,
            "openai_base_url": runtime.api_base,
            "temperature": 0.0,
            "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        }
    return {
        "model": runtime.model,
        "api_key": runtime.api_key,
        "temperature": 0.0,
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
    }


def mem0_embedder_config(args: argparse.Namespace) -> Dict[str, object]:
    if args.mem0_embedder_provider == "openai":
        return {
            "model": args.mem0_embedding_model,
            "api_key": os.environ.get("OPENAI_EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            "openai_base_url": args.mem0_embedding_base_url
            or os.environ.get("OPENAI_EMBEDDING_BASE_URL")
            or os.environ.get("OPENAI_EMBEDDING_API_BASE")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE"),
        }
    return {}


def mem0_vector_store_config(args: argparse.Namespace, store_dir: Path, collection_name: str) -> Dict[str, object]:
    return {
        "collection_name": collection_name,
        "path": str(store_dir / "qdrant"),
        "embedding_model_dims": args.mem0_embedding_dims,
        "on_disk": True,
    }


def safe_collection_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")[:60] or "locomo"


def is_retryable_mem0_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(pattern in text for pattern in ("rate limit", "ratelimit", "429", "timeout", "temporarily unavailable"))


def run_variant(
    *,
    variant: str,
    rows: Sequence[LoCoMoQAItem],
    sample: LoCoMoSample,
    rag_corpus: EmbeddingRAGCorpus,
    answer_runtime: LLMRuntimeConfig,
    args: argparse.Namespace,
) -> Dict[str, object]:
    if variant == "mem0":
        mem0_index: Optional[Mem0SampleIndex] = Mem0SampleIndex(sample, args, answer_runtime)
    else:
        mem0_index = None
    if variant == "tsm":
        tsm_index: Optional[TSMSampleIndex] = TSMSampleIndex(sample, args, answer_runtime)
    else:
        tsm_index = None
    if variant == "memgpt":
        letta_memgpt_index: Optional[OfficialLettaMemGPTSampleIndex] = OfficialLettaMemGPTSampleIndex(sample, args)
    else:
        letta_memgpt_index = None
    if variant == "memory_bank":
        memory_bank_index: Optional[MemoryBankSubprocessSampleIndex] = MemoryBankSubprocessSampleIndex(sample, rows, args, answer_runtime)
    else:
        memory_bank_index = None
    if variant == "memoryos":
        memoryos_index: Optional[MemoryOSOfficialSampleIndex] = MemoryOSOfficialSampleIndex(sample, args, answer_runtime)
    else:
        memoryos_index = None
    if variant == "zep":
        zep_index: Optional[ZepGraphitiSubprocessSampleIndex] = ZepGraphitiSubprocessSampleIndex(sample, rows, args, answer_runtime)
    else:
        zep_index = None

    def context_for(row: LoCoMoQAItem) -> BaselineContext:
        if variant == "full_text":
            return full_text_context(sample)
        if variant == "rag":
            return rag_corpus.retrieve(row.question, args.top_k)
        if variant == "mem0":
            if mem0_index is None:
                raise RuntimeError("mem0 index was not initialized")
            return mem0_index.retrieve(row.question, args.top_k)
        if variant == "tsm":
            if tsm_index is None:
                raise RuntimeError("tsm index was not initialized")
            return tsm_index.retrieve(row)
        if variant == "memgpt":
            if letta_memgpt_index is None:
                raise RuntimeError("official letta memgpt index was not initialized")
            return letta_memgpt_index.retrieve(row)
        if variant == "memory_bank":
            if memory_bank_index is None:
                raise RuntimeError("memory_bank index was not initialized")
            return memory_bank_index.retrieve(row)
        if variant == "memoryos":
            if memoryos_index is None:
                raise RuntimeError("memoryos index was not initialized")
            return memoryos_index.retrieve(row)
        if variant == "zep":
            if zep_index is None:
                raise RuntimeError("zep index was not initialized")
            return zep_index.retrieve(row)
        raise ValueError(f"unsupported variant={variant}")

    def run_row(index: int, row: LoCoMoQAItem) -> Tuple[int, Dict[str, object]]:
        context = context_for(row)
        if context.direct_answer is not None:
            hypothesis = context.direct_answer
            evidence_dialog_ids = list(context.direct_evidence_dialog_ids)
        else:
            client = make_sharded_client(answer_runtime, f"answer_{variant}", f"{row.question_id}_{short_hash(row.question)}")
            output = client.complete_json(answer_system_prompt(), answer_user_prompt(row, variant, context))
            hypothesis = str(output.get("answer", "")).strip()
            evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
        evidence_precision = precision(evidence_dialog_ids, row.evidence_dialog_ids)
        evidence_recall = recall(evidence_dialog_ids, row.evidence_dialog_ids)
        return index, {
            "question_id": row.question_id,
            "sample_id": row.sample_id,
            "qa_index": row.qa_index,
            "category": row.category,
            "question_type": row.question_type,
            "question": row.question,
            "gold_answer": row.answer,
            "hypothesis": hypothesis,
            "candidate_dialog_ids": list(context.candidate_dialog_ids),
            "evidence_dialog_ids": evidence_dialog_ids,
            "gold_evidence_dialog_ids": list(row.evidence_dialog_ids),
            "candidate_dialog_recall": recall(context.candidate_dialog_ids, row.evidence_dialog_ids),
            "candidate_dialog_precision": precision(context.candidate_dialog_ids, row.evidence_dialog_ids),
            "evidence_dialog_recall": evidence_recall,
            "evidence_dialog_precision": evidence_precision,
            "evidence_dialog_f1": f1_from_precision_recall(evidence_precision, evidence_recall),
            "answer_f1": official_style_answer_score(row, hypothesis),
            "exact_match": exact_match_score(hypothesis, row.answer) if row.category != 5 else False,
            "retrieval_trace": context.trace,
        }

    eval_rows: List[Dict[str, object]] = []
    if args.answer_workers <= 1:
        for index, row in enumerate(rows, start=1):
            _index, result = run_row(index, row)
            eval_rows.append(result)
            print(f"[{variant}] {index}/{len(rows)} {row.question_id} {row.question_type}", flush=True)
    else:
        results: Dict[int, Dict[str, object]] = {}
        with ThreadPoolExecutor(max_workers=max(1, args.answer_workers)) as executor:
            futures = {executor.submit(run_row, index, row): index for index, row in enumerate(rows, start=1)}
            for future in as_completed(futures):
                index, result = future.result()
                results[index] = result
                print(f"[{variant}] {index}/{len(rows)} {result['question_id']} {result['question_type']}", flush=True)
        eval_rows = [results[index] for index in sorted(results)]
    return {"variant": variant, "summary": summarize(eval_rows), "rows": eval_rows}


def print_summary(provider: str, model: str, results: Sequence[Dict[str, object]]) -> None:
    print("LoCoMo QA memory baselines")
    print(f"answer_provider={provider} answer_model={model}")
    print()
    print(f"{'variant':<20} {'n':>4} {'ans_f1':>8} {'task_f1':>8} {'exact':>8} {'cand_r':>8} {'cand_p':>8} {'ev_r':>8} {'ev_p':>8} {'ev_f1':>8}")
    print("-" * 107)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<20} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['answer_f1']):>8} "
            f"{format_metric(summary['task_averaged_answer_f1']):>8} "
            f"{format_metric(summary['exact_match']):>8} "
            f"{format_metric(summary['candidate_dialog_recall']):>8} "
            f"{format_metric(summary['candidate_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_recall']):>8} "
            f"{format_metric(summary['evidence_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_f1']):>8}"
        )


def main() -> int:
    args = parse_args()
    load_dotenv()
    sample = load_sample(Path(args.data), args.sample_id)
    rows = select_rows(
        load_sample_qa(Path(args.data), args.sample_id),
        args.question_types,
        args.limit_cases,
        args.limit_per_type,
    )
    if not rows:
        print("empty selection; check --question-types/--limit-cases/--limit-per-type", file=sys.stderr)
        return 2
    if args.dry_run:
        print("LoCoMo QA memory baselines dry run")
        print(f"sample_id={args.sample_id} rows={len(rows)} variants={','.join(args.variants)}")
        print(f"question_types={','.join(args.question_types) if args.question_types else '[all]'}")
        print(f"top_k={args.top_k} baseline_store_dir={args.baseline_store_dir}")
        if "rag" in args.variants:
            print(
                "rag="
                f"model:{args.rag_embedding_model} "
                f"chunk_chars:{args.rag_chunk_target_chars} "
                f"overlap_turns:{args.rag_chunk_overlap_turns}"
            )
        return 0
    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.model:
        model = args.model
    answer_runtime = LLMRuntimeConfig(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )
    rag_corpus = EmbeddingRAGCorpus(sample, args)
    try:
        results = [
            run_variant(
                variant=variant,
                rows=rows,
                sample=sample,
                rag_corpus=rag_corpus,
                answer_runtime=answer_runtime,
                args=args,
            )
            for variant in args.variants
        ]
    except LLMRequestError as exc:
        print("\nLLM request failed during LoCoMo memory baseline QA.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output = {
        "benchmark": "LoCoMo QA memory baselines",
        "sample_id": args.sample_id,
        "data_path": str(Path(args.data)),
        "provider": args.provider,
        "model": model,
        "variants": list(args.variants),
        "question_types": [normalize_question_type(item) for item in args.question_types],
        "top_k": args.top_k,
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "baseline_config": {
            "baseline_store_dir": str(Path(args.baseline_store_dir)),
            "reuse_baseline_store": args.reuse_baseline_store,
            "rag": "openai_compatible_embedding_turn_chunks",
            "rag_chunk_target_chars": args.rag_chunk_target_chars,
            "rag_chunk_overlap_turns": args.rag_chunk_overlap_turns,
            "rag_embedding_model": args.rag_embedding_model,
            "rag_embedding_base_url": args.rag_embedding_base_url
            or os.environ.get("OPENAI_EMBEDDING_BASE_URL")
            or os.environ.get("OPENAI_EMBEDDING_API_BASE")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE"),
            "rag_embedding_cache": args.rag_embedding_cache,
            "rag_embedding_batch_size": args.rag_embedding_batch_size,
            "mem0_skip_ingest": args.mem0_skip_ingest,
            "mem0_start_index": args.mem0_start_index,
            "mem0_add_retries": args.mem0_add_retries,
            "mem0_retry_sleep": args.mem0_retry_sleep,
            "mem0_llm_provider": args.mem0_llm_provider or args.provider,
            "mem0_embedder_provider": args.mem0_embedder_provider,
            "mem0_embedding_model": args.mem0_embedding_model,
            "mem0_embedding_base_url": args.mem0_embedding_base_url
            or os.environ.get("OPENAI_EMBEDDING_BASE_URL")
            or os.environ.get("OPENAI_EMBEDDING_API_BASE")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE"),
            "mem0_embedding_dims": args.mem0_embedding_dims,
            "mem0_vector_store_provider": args.mem0_vector_store_provider,
            "memgpt": "official_letta_runtime",
            "letta_command": args.letta_command,
            "letta_code_repo": args.letta_code_repo,
            "letta_backend": args.letta_backend,
            "letta_model": args.letta_model,
            "letta_agent_id": args.letta_agent_id,
            "letta_conversation_id": args.letta_conversation_id,
            "letta_skip_ingest": args.letta_skip_ingest,
            "letta_ingest_chunk_turns": args.letta_ingest_chunk_turns,
            "letta_toolset": args.letta_toolset,
            "letta_base_tools": args.letta_base_tools,
            "letta_query_conversation": args.letta_query_conversation,
            "memory_bank": "official_memorybank_faiss_runtime",
            "memory_bank_official_repo": args.memory_bank_official_repo,
            "memory_bank_language": args.memory_bank_language,
            "memory_bank_retriever": "official_langchain_faiss",
            "memory_bank_summary_mode": "official_prompt_llm",
            "memory_bank_initial_strength": args.memory_bank_initial_strength,
            "memory_bank_current_date": args.memory_bank_current_date,
            "memory_bank_embedding_model": args.memory_bank_embedding_model,
            "memory_bank_embedding_device": args.memory_bank_embedding_device,
            "memory_bank_conda_env": args.memory_bank_conda_env,
            "memory_bank_python": args.memory_bank_python,
            "memoryos": "official_memoryos_source_runtime",
            "memoryos_official_repo": args.memoryos_official_repo,
            "memoryos_model": args.memoryos_model or model,
            "memoryos_embedding_model": args.memoryos_embedding_model,
            "memoryos_short_term_capacity": args.memoryos_short_term_capacity,
            "memoryos_mid_term_heat_threshold": args.memoryos_mid_term_heat_threshold,
            "memoryos_retrieval_queue_capacity": args.memoryos_retrieval_queue_capacity or args.top_k,
            "memoryos_skip_ingest": args.memoryos_skip_ingest,
            "zep": "official_graphiti_runtime",
            "zep_official_repo": args.zep_official_repo,
            "zep_conda_env": args.zep_conda_env,
            "zep_python": args.zep_python,
            "zep_neo4j_uri": args.zep_neo4j_uri,
            "zep_neo4j_user": args.zep_neo4j_user,
            "zep_neo4j_database": args.zep_neo4j_database,
            "zep_group_id": args.zep_group_id,
            "zep_graphiti_provider": args.zep_graphiti_provider or args.provider,
            "zep_cross_encoder": args.zep_cross_encoder,
            "zep_embedder": args.zep_embedder,
            "zep_search_config": args.zep_search_config,
            "zep_skip_ingest": args.zep_skip_ingest,
            "tsm_construction_mode": "llm",
        },
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    for result in results:
        jsonl_path = output_path.with_name(f"{output_path.stem}.{result['variant']}.hypotheses.jsonl")
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in result["rows"]:
                handle.write(
                    json.dumps(
                        {
                            "question_id": row["question_id"],
                            "sample_id": row["sample_id"],
                            "qa_index": row["qa_index"],
                            "category": row["category"],
                            "question_type": row["question_type"],
                            "hypothesis": row["hypothesis"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    print_summary(args.provider, model, results)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
PROJECT_DIR = BENCHMARK_DIR.parents[2]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, parse_json_object, provider_config  # noqa: E402
from adapter_registry import create_adapter, supported_adapters  # noqa: E402
from common.official_eval.data_models import Dataset, GroupChatDay, GroupChatMessage, SearchResult  # noqa: E402
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
    official_bleu1_score,
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


LEGACY_OFFICIAL_VARIANTS = (
    "memgpt",
    "memory_bank",
    "a_mem",
)
OFFICIAL_SERVICE_VARIANTS = supported_adapters()
SUPPORTED_VARIANTS = (
    "full_text",
    "rag",
    *LEGACY_OFFICIAL_VARIANTS,
    "tsm",
    *OFFICIAL_SERVICE_VARIANTS,
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
    STATE_SCHEMA = "locomo-letta-memgpt-official-recall-v2"

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
        state: Dict[str, Any] = {}
        if self.args.reuse_baseline_store and self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            if state.get("schema_version") != self.STATE_SCHEMA:
                state = {}
            if state.get("agent_id") and state.get("ingested"):
                print(f"[letta-memgpt] load_agent_state {self.state_path}", flush=True)
                return state
            if state.get("agent_id") and int(state.get("ingested_chunks") or 0) > 0:
                print(
                    f"[letta-memgpt] resume_agent_state {self.state_path} "
                    f"chunks={state['ingested_chunks']}",
                    flush=True,
                )
            else:
                state = {}

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
        if not agent_id:
            warmup = self._run_letta_prompt(
                "Reply exactly OK. Do not call any tool or start any agent.",
                agent_id=None,
                conversation_id=None,
                new_agent=True,
                new_conversation=True,
            )
            agent_id = str(warmup.get("agent_id") or "")
            conversation_id = str(warmup.get("conversation_id") or conversation_id or "default")
            if not agent_id:
                raise RuntimeError("official Letta warm-up did not return agent_id")
        completed_chunks = int(state.get("ingested_chunks") or 0)
        for index, chunk in enumerate(chunks, start=1):
            if index <= completed_chunks:
                continue
            prompt = letta_ingest_prompt(self.sample, chunk, index, len(chunks))
            print(f"[letta-memgpt] ingest_chunk {index}/{len(chunks)} turns={len(chunk)}", flush=True)
            result = self._run_letta_prompt(
                prompt,
                agent_id=agent_id or None,
                # Letta Code rejects --conversation together with --agent.
                # Start each chunk in a fresh conversation while preserving the
                # same agent's memory, preventing context growth across chunks.
                conversation_id=None,
                new_agent=False,
                new_conversation=True,
            )
            agent_id = str(result.get("agent_id") or agent_id)
            conversation_id = str(result.get("conversation_id") or conversation_id or "default")
            if not agent_id:
                raise RuntimeError("official Letta command did not return agent_id")
            self._checkpoint_state(agent_id, conversation_id, index, chunks)

        final_state = {
            "schema_version": self.STATE_SCHEMA,
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

    def _checkpoint_state(
        self,
        agent_id: str,
        conversation_id: str,
        index: int,
        chunks: Sequence[Sequence[DialogTurn]],
    ) -> None:
        self._write_state(
            {
                "schema_version": self.STATE_SCHEMA,
                "sample_id": self.sample.sample_id,
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "ingested": False,
                "ingested_chunks": index,
                "ingested_dialog_ids": [
                    turn.dia_id
                    for turn in self.sample.turns[: sum(len(item) for item in chunks[:index])]
                ],
                "letta_backend": self.args.letta_backend,
                "letta_command": self.command,
                "letta_command_cwd": str(self.command_cwd or self.work_dir),
            }
        )

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
        cmd.extend(
            [
                "--backend",
                self.args.letta_backend,
                "--output-format",
                "json",
                "--memfs-startup",
                "skip",
                "--no-skills",
                "--permission-mode",
                "unrestricted",
            ]
        )
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
        proc: Optional[subprocess.CompletedProcess[str]] = None
        attempts = max(1, self.args.letta_request_retries)
        for attempt in range(1, attempts + 1):
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
                if attempt == attempts:
                    raise RuntimeError(
                        f"official Letta command timed out after {self.args.letta_timeout_seconds}s"
                    ) from exc
                print(f"[letta-memgpt] request_retry {attempt}/{attempts} reason=timeout", flush=True)
                time.sleep(min(2 ** (attempt - 1), 5))
                continue
            if proc.returncode == 0:
                break
            if attempt < attempts:
                print(
                    f"[letta-memgpt] request_retry {attempt}/{attempts} returncode={proc.returncode}",
                    flush=True,
                )
                time.sleep(min(2 ** (attempt - 1), 5))
        if proc is None or proc.returncode != 0:
            stderr = "" if proc is None else proc.stderr[-4000:]
            stdout = "" if proc is None else proc.stdout[-2000:]
            returncode = "none" if proc is None else proc.returncode
            raise RuntimeError(
                "official Letta command failed; "
                f"returncode={returncode}; stdout_tail={stdout!r}; stderr_tail={stderr!r}"
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
                "retriever": "official_letta_recall",
                "official_runtime": "letta-code",
                "recall_method": "Agent(subagent_type=recall) -> letta messages search --mode hybrid",
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
            "memory_bank_chunk_size": self.args.memory_bank_chunk_size,
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


class AMemSampleIndex:
    def __init__(self, sample: LoCoMoSample, args: argparse.Namespace, runtime: LLMRuntimeConfig) -> None:
        self.sample = sample
        self.args = args
        self.runtime = runtime
        self.store_dir = Path(args.baseline_store_dir) / "a_mem" / sample.sample_id
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.official = load_amem_official_runtime(args.amem_repo_dir)
        self.memory = self.official["AgenticMemorySystem"](
            model_name=args.amem_embedding_model,
            llm_backend=args.amem_llm_backend,
            llm_model=args.amem_llm_model or runtime.model,
            evo_threshold=args.amem_evo_threshold,
            api_key=args.amem_llm_api_key or runtime.api_key,
        )
        self._ingest()

    def _ingest(self) -> None:
        turns = self.sample.turns[: self.args.amem_ingest_limit or None]
        if not turns:
            raise RuntimeError(f"sample_id={self.sample.sample_id} has no dialog turns to ingest into A-Mem")
        print(
            f"[a-mem-official] ingest sample_id={self.sample.sample_id} turns={len(turns)} "
            f"official_repo={self.official['repo']}",
            flush=True,
        )
        ingested_dialog_ids: List[str] = []
        for index, turn in enumerate(turns, start=1):
            print(f"[a-mem-official] add_note {index}/{len(turns)} {turn.dia_id}", flush=True)
            self.memory.add_note(
                content=amem_turn_text(turn),
                time=locomo_amem_timestamp(turn.session_date_time),
                tags=[self.sample.sample_id, turn.session_id, turn.speaker],
                category="LoCoMo QA",
            )
            ingested_dialog_ids.append(turn.dia_id)
        state = {
            "schema_version": "locomo-a-mem-official-ingest-v1",
            "sample_id": self.sample.sample_id,
            "official_repo": str(self.official["repo"]),
            "official_runtime": "agiresearch/A-mem agentic_memory.memory_system.AgenticMemorySystem",
            "ingested": True,
            "ingested_dialog_ids": ingested_dialog_ids,
            "llm_backend": self.args.amem_llm_backend,
            "llm_model": self.args.amem_llm_model or self.runtime.model,
            "embedding_model": self.args.amem_embedding_model,
            "agentic_search": self.args.amem_agentic_search,
        }
        (self.store_dir / "ingest_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    def retrieve(self, row: LoCoMoQAItem) -> BaselineContext:
        search = self.memory.search_agentic if self.args.amem_agentic_search else self.memory.search
        results = search(row.question, k=self.args.top_k)
        lines: List[str] = []
        candidate_dialog_ids: List[str] = []
        trace_rows: List[Dict[str, Any]] = []
        for rank, item in enumerate(results or [], start=1):
            if not isinstance(item, Mapping):
                continue
            content = str(item.get("content") or "")
            dialog_ids = re.findall(r"\bD\d+:\d+\b", content)
            candidate_dialog_ids.extend(dialog_ids)
            lines.append(
                f'<memory rank="{rank}" ids="{",".join(dialog_ids)}" score="{item.get("score", "")}">\n'
                f"{content}\n"
                f"context: {item.get('context', '')}\n"
                f"keywords: {item.get('keywords', [])}\n"
                "</memory>"
            )
            trace_rows.append(
                {
                    "rank": rank,
                    "dialog_ids": dialog_ids,
                    "score": item.get("score"),
                    "context": item.get("context"),
                    "keywords": item.get("keywords"),
                    "tags": item.get("tags"),
                    "timestamp": item.get("timestamp"),
                }
            )
        return BaselineContext(
            candidate_dialog_ids=ordered_unique(candidate_dialog_ids),
            context="\n\n".join(lines),
            trace={
                "retriever": "official_a_mem",
                "official_runtime": "agiresearch/A-mem",
                "official_repo": str(self.official["repo"]),
                "official_components": [
                    "agentic_memory.memory_system.AgenticMemorySystem",
                    "AgenticMemorySystem.add_note",
                    "AgenticMemorySystem.search_agentic" if self.args.amem_agentic_search else "AgenticMemorySystem.search",
                ],
                "candidate_dialog_ids_source": "dialog_ids_embedded_in_official_memory_content",
                "embedding_model": self.args.amem_embedding_model,
                "llm_backend": self.args.amem_llm_backend,
                "llm_model": self.args.amem_llm_model or self.runtime.model,
                "results": trace_rows,
            },
        )


class OfficialServiceSampleIndex:
    def __init__(
        self,
        system_name: str,
        sample: LoCoMoSample,
        rows: Sequence[LoCoMoQAItem],
        args: argparse.Namespace,
        runtime: LLMRuntimeConfig,
    ) -> None:
        self.system_name = system_name
        self.sample = sample
        self.args = args
        self.runtime = runtime
        self.user_id = args.official_user_id or safe_collection_name(
            f"locomo_{system_name}_{sample.sample_id}_{short_hash(str(Path(args.data).resolve()))}"
        )
        self.store_dir = Path(args.baseline_store_dir) / "official_services" / system_name / sample.sample_id
        self.state_path = self.store_dir / "ingest_state.json"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        seed_official_adapter_env(system_name, runtime)
        self.dataset = locomo_sample_to_official_dataset(sample)
        self.contexts = asyncio.run(self._build_contexts(rows))

    def retrieve(self, row: LoCoMoQAItem) -> BaselineContext:
        context = self.contexts.get(row.question_id)
        if context is None:
            raise RuntimeError(f"{self.system_name} missing context for question_id={row.question_id}")
        return context

    async def _build_contexts(self, rows: Sequence[LoCoMoQAItem]) -> Dict[str, BaselineContext]:
        adapter = create_adapter(
            self.system_name,
            output_dir=self.store_dir,
            base_url=official_base_url_for(self.args, self.system_name),
            config_overrides=official_config_overrides(self.args, self.system_name),
        )
        state: Dict[str, Any] = {}
        try:
            should_add = self._should_add()
            if should_add:
                print(
                    f"[{self.system_name}-add] sample_id={self.sample.sample_id} "
                    f"user_id={self.user_id} messages={self.dataset.total_messages}",
                    flush=True,
                )
                add_result = await adapter.add(self.dataset, self.user_id)
                if not add_result.success:
                    raise RuntimeError(f"{self.system_name} add failed: {add_result.errors}")
                state = self._write_ingest_state(add_result)
            else:
                state = self._load_ingest_state()
                print(
                    f"[{self.system_name}-add] skip existing ingest state user_id={self.user_id} "
                    f"state={self.state_path}",
                    flush=True,
                )

            contexts: Dict[str, BaselineContext] = {}
            semaphore = asyncio.Semaphore(max(1, int(self.args.official_search_concurrency)))

            async def search_one(index: int, row: LoCoMoQAItem) -> Tuple[str, BaselineContext]:
                async with semaphore:
                    result = await adapter.search(
                        row.question,
                        self.user_id,
                        top_k=self.args.top_k,
                        question_id=row.question_id,
                    )
                    print(f"[{self.system_name}-search] {index}/{len(rows)} {row.question_id}", flush=True)
                    return row.question_id, self._context_from_search(row, result, state)

            pairs = await asyncio.gather(*(search_one(index, row) for index, row in enumerate(rows, start=1)))
            contexts.update(pairs)
            return contexts
        finally:
            await adapter.close()

    def _should_add(self) -> bool:
        if self.args.skip_official_ingest:
            if not self.state_path.exists() and not self.args.official_user_id:
                raise RuntimeError(
                    "--skip-official-ingest without an ingest state requires --official-user-id "
                    "so the service-side memory namespace is explicit."
                )
            return False
        if self.args.force_official_ingest:
            return True
        return not (self.args.reuse_baseline_store and self.state_path.exists())

    def _load_ingest_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema_version": "locomo-official-service-ingest-v1",
                "system_name": self.system_name,
                "sample_id": self.sample.sample_id,
                "user_id": self.user_id,
                "ingested": False,
                "note": "ingest skipped by explicit user request; no local state file was present",
            }
        payload = json.loads(self.state_path.read_text())
        if str(payload.get("user_id") or "") != self.user_id:
            raise RuntimeError(
                f"{self.system_name} ingest state user_id mismatch: "
                f"state={payload.get('user_id')!r} current={self.user_id!r}"
            )
        return dict(payload)

    def _write_ingest_state(self, add_result: object) -> Dict[str, Any]:
        state = {
            "schema_version": "locomo-official-service-ingest-v1",
            "system_name": self.system_name,
            "sample_id": self.sample.sample_id,
            "user_id": self.user_id,
            "data_path": str(Path(self.args.data).resolve()),
            "ingested": True,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "dataset": {
                "name": self.dataset.name,
                "total_days": self.dataset.total_days,
                "total_messages": self.dataset.total_messages,
            },
            "add_result": sanitize_jsonable(asdict(add_result)),
        }
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        return state

    def _context_from_search(
        self,
        row: LoCoMoQAItem,
        search_result: SearchResult,
        state: Mapping[str, Any],
    ) -> BaselineContext:
        candidate_dialog_ids = extract_dialog_ids_from_search(search_result)
        trace = {
            "retriever": self.system_name,
            "official_adapter_interface": "EverMemBench Baseline BaseAdapter.add/search",
            "question_id": row.question_id,
            "user_id": self.user_id,
            "top_k": self.args.top_k,
            "candidate_dialog_ids_source": "dialog_ids_embedded_in_adapter_context_or_metadata",
            "search_duration_ms": search_result.search_duration_ms,
            "retrieved_memories": search_result.retrieved_memories,
            "search_metadata": sanitize_jsonable(search_result.metadata),
            "ingest_state": {
                "path": str(self.state_path),
                "ingested": bool(state.get("ingested")),
                "dataset": state.get("dataset"),
            },
        }
        return BaselineContext(
            candidate_dialog_ids=candidate_dialog_ids,
            context=search_result.context,
            trace=trace,
        )



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LoCoMo QA memory baselines.")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--variants", nargs="+", default=["full_text", "rag"], choices=SUPPORTED_VARIANTS)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--skip-cases", type=int, default=0)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=24)
    parser.add_argument("--answer-workers", type=int, default=2)
    parser.add_argument("--cache", default=str(EXTERNAL_CACHE_DIR / "llm_cache.locomo_qa_memory_baselines.json"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--baseline-store-dir", default=str(PROJECT_DIR / "Graph/output/baseline_store/locomo_qa"))
    parser.add_argument("--reuse-baseline-store", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate selected rows and variants without LLM or embedding calls.")
    parser.add_argument("--rag-chunk-target-chars", type=int, default=900)
    parser.add_argument("--rag-chunk-overlap-turns", type=int, default=1)
    parser.add_argument("--rag-embedding-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--rag-embedding-base-url", default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", ""))
    parser.add_argument("--rag-embedding-cache", default=str(EXTERNAL_CACHE_DIR / "embedding_cache.locomo_qa_rag.json"))
    parser.add_argument("--rag-embedding-batch-size", type=int, default=64)
    parser.add_argument("--letta-command", default=os.environ.get("LETTA_COMMAND", ""))
    parser.add_argument("--letta-code-repo", default=os.environ.get("LETTA_CODE_REPO", ""))
    parser.add_argument("--letta-backend", choices=("local", "api"), default=os.environ.get("LETTA_BACKEND", "local"))
    parser.add_argument("--letta-model", default=os.environ.get("LETTA_MODEL", ""))
    parser.add_argument("--letta-agent-id", default=os.environ.get("LETTA_AGENT_ID", ""))
    parser.add_argument("--letta-conversation-id", default=os.environ.get("LETTA_CONVERSATION_ID", ""))
    parser.add_argument("--letta-skip-ingest", action="store_true")
    parser.add_argument("--letta-ingest-chunk-turns", type=int, default=10)
    parser.add_argument("--letta-timeout-seconds", type=int, default=900)
    parser.add_argument("--letta-request-retries", type=int, default=3)
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
    parser.add_argument("--memory-bank-chunk-size", type=int, default=int(os.environ.get("MEMORY_BANK_CHUNK_SIZE", "12")))
    parser.add_argument("--memory-bank-conda-env", default=os.environ.get("MEMORY_BANK_CONDA_ENV", "locomo_memorybank"))
    parser.add_argument("--memory-bank-python", default=os.environ.get("MEMORY_BANK_PYTHON", ""))
    parser.add_argument("--memory-bank-timeout-seconds", type=int, default=int(os.environ.get("MEMORY_BANK_TIMEOUT_SECONDS", "7200")))
    parser.add_argument(
        "--amem-repo-dir",
        default=os.environ.get("AMEM_REPO_DIR", str(PROJECT_DIR / "Graph/output/service_repos/locomo_smoke/A-mem")),
    )
    parser.add_argument("--amem-llm-backend", choices=("openai", "ollama"), default=os.environ.get("AMEM_LLM_BACKEND", "ollama"))
    parser.add_argument("--amem-llm-model", default=os.environ.get("AMEM_LLM_MODEL", ""))
    parser.add_argument("--amem-llm-api-key", default=os.environ.get("AMEM_LLM_API_KEY", ""))
    parser.add_argument("--amem-embedding-model", default=os.environ.get("AMEM_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    parser.add_argument("--amem-evo-threshold", type=int, default=int(os.environ.get("AMEM_EVO_THRESHOLD", "1000000")))
    parser.add_argument("--amem-ingest-limit", type=int, default=int(os.environ.get("AMEM_INGEST_LIMIT", "0")))
    parser.add_argument("--amem-agentic-search", action=argparse.BooleanOptionalAction, default=env_bool("AMEM_AGENTIC_SEARCH", True))
    parser.add_argument("--official-user-id", default=os.environ.get("LOCOMO_OFFICIAL_USER_ID", ""))
    parser.add_argument(
        "--official-base-url",
        default=os.environ.get("LOCOMO_OFFICIAL_BASE_URL", ""),
        help="Optional one-off base URL override for mem0_local/memos_local/memobase.",
    )
    parser.add_argument(
        "--official-config-json",
        default=os.environ.get("LOCOMO_OFFICIAL_CONFIG_JSON", ""),
        help="JSON object merged into every official service adapter config.",
    )
    parser.add_argument("--official-search-concurrency", type=int, default=int(os.environ.get("LOCOMO_OFFICIAL_SEARCH_CONCURRENCY", "1")))
    parser.add_argument("--skip-official-ingest", action="store_true")
    parser.add_argument("--force-official-ingest", action="store_true")
    return parser.parse_args()


def default_output_path_for_variants(args: argparse.Namespace) -> Path:
    if len(args.variants) == 1:
        subdir = args.variants[0]
        variant_slug = args.variants[0]
    else:
        subdir = "mixed"
        variant_slug = "_".join(args.variants)
    return EXTERNAL_RESULT_DIR / "locomo_qa" / subdir / f"results_locomo_qa_{variant_slug}_{args.sample_id}.json"


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def sanitize_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): sanitize_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def select_rows(
    rows: Sequence[LoCoMoQAItem],
    question_types: Sequence[str],
    skip_cases: int,
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
    if skip_cases:
        selected = selected[skip_cases:]
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
        "The user message containing this chunk is automatically retained in your official recall/message history. "
        "Do not call tools, do not create or modify memory files, and do not summarize or transform the chunk. "
        "Reply exactly INGESTED. This is an ingestion turn only; do not answer any benchmark question yet.\n\n"
        f"Sample ID: {sample.sample_id}\n"
        f"Chunk: {chunk_index}/{n_chunks}\n\n"
        f"{format_turn_context(turns)}"
    )


def letta_question_prompt(row: LoCoMoQAItem) -> str:
    return (
        "Answer the LoCoMo QA question using only the conversation previously ingested into this Letta agent. "
        "Your first action must be exactly one Agent tool call with subagent_type='recall', "
        "description='Recall LoCoMo evidence', and run_in_background=false. Its prompt must ask it to use hybrid "
        "message search over this agent's past conversations for the question below and return only the few "
        "relevant messages, including exact dialog IDs and dates. Do not omit run_in_background=false. "
        "Do not call TaskList, TaskGet, TaskOutput, or a second Agent; the blocking Agent result is your evidence. "
        "Do not use Bash, Read, memory files, workspace files, or manually scan the full conversation. "
        "For date questions, resolve relative expressions such as yesterday or last Saturday against the dated "
        "dialog and return the resulting calendar date, never the unresolved relative phrase. "
        "Do not use gold answers, gold evidence, categories, or question-type labels.\n\n"
        f"Question ID: {row.question_id}\n"
        f"Question: {row.question}\n\n"
        "Return a strict JSON object only, with a string field named answer and an array field named "
        "evidence_dialog_ids. Fill evidence_dialog_ids only with the exact relevant dialog IDs returned by recall; "
        "do not copy an example or invent an ID."
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
        "module": module,
        "prompts": load_memory_bank_official_prompts(str(repo)),
        "LocalMemoryRetrieval": getattr(module, "LocalMemoryRetrieval", None),
        "MemoryForgetterLoader": getattr(module, "MemoryForgetterLoader", None),
    }
    if runtime["LocalMemoryRetrieval"] is None or runtime["MemoryForgetterLoader"] is None:
        raise RuntimeError("official MemoryBank repo is missing LocalMemoryRetrieval or MemoryForgetterLoader")
    return runtime


def load_amem_official_runtime(repo_path: str) -> Dict[str, Any]:
    if not repo_path:
        raise RuntimeError("a_mem official variant requires --amem-repo-dir pointing to agiresearch/A-mem")
    repo = Path(repo_path).expanduser().resolve()
    memory_system_path = repo / "agentic_memory/memory_system.py"
    if not memory_system_path.exists():
        raise RuntimeError(f"--amem-repo-dir does not look like agiresearch/A-mem: missing {memory_system_path}")
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    module = importlib.import_module("agentic_memory.memory_system")
    memory_cls = getattr(module, "AgenticMemorySystem", None)
    if memory_cls is None:
        raise RuntimeError(f"official A-Mem repo is missing AgenticMemorySystem at {memory_system_path}")
    return {
        "repo": repo,
        "AgenticMemorySystem": memory_cls,
    }


def locomo_sample_to_official_dataset(sample: LoCoMoSample) -> Dataset:
    days_by_date: Dict[str, Dict[str, List[GroupChatMessage]]] = defaultdict(lambda: defaultdict(list))
    for session in sample.sessions:
        session_time = parse_session_date(session.date_time)
        if session_time is None:
            session_time = datetime(1970, 1, 1)
        date_key = session_time.date().isoformat()
        for offset, turn in enumerate(session.turns):
            timestamp = session_time + timedelta(seconds=offset)
            days_by_date[date_key][session.session_id].append(
                GroupChatMessage(
                    speaker=turn.speaker,
                    content=official_visible_message_text(sample.sample_id, turn),
                    timestamp=timestamp,
                    group=session.session_id,
                    date=date_key,
                    metadata={
                        "benchmark": "LoCoMo QA",
                        "sample_id": sample.sample_id,
                        "dialog_id": turn.dia_id,
                        "session_id": turn.session_id,
                        "session_index": turn.session_index,
                        "session_date_time": turn.session_date_time,
                    },
                )
            )
    days = [
        GroupChatDay(
            date=date_key,
            groups={group_name: messages for group_name, messages in sorted(groups.items())},
            metadata={"sample_id": sample.sample_id},
        )
        for date_key, groups in sorted(days_by_date.items())
    ]
    return Dataset(
        name=f"locomo_qa_{sample.sample_id}",
        days=days,
        metadata={
            "benchmark": "LoCoMo QA",
            "sample_id": sample.sample_id,
            "source_fields": ["sample_id", "conversation"],
            "ignored_fields": ["qa", "answer", "evidence", "category", "question"],
        },
    )


def official_visible_message_text(sample_id: str, turn: DialogTurn) -> str:
    parts = [
        f"[LoCoMo sample_id={sample_id}]",
        f"[dialog_id={turn.dia_id}]",
        f"[session_id={turn.session_id}]",
        f"[session_time={turn.session_date_time}]",
        f"{turn.speaker}: {turn.text}",
    ]
    if turn.image_caption:
        parts.append(f"Image caption: {turn.image_caption}")
    if turn.image_query:
        parts.append(f"Image search query: {turn.image_query}")
    return " ".join(parts)


def extract_dialog_ids_from_search(search_result: SearchResult) -> List[str]:
    text_parts = [search_result.context, *search_result.retrieved_memories]
    try:
        text_parts.append(json.dumps(search_result.metadata, ensure_ascii=False, default=str))
    except TypeError:
        text_parts.append(str(search_result.metadata))
    return ordered_unique(re.findall(r"\bD\d+:\d+\b", "\n".join(str(part) for part in text_parts)))


def official_config_overrides(args: argparse.Namespace, system_name: str) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    for raw, label in (
        (args.official_config_json, "--official-config-json"),
        (os.environ.get(f"LOCOMO_{system_name.upper()}_CONFIG_JSON", ""), f"LOCOMO_{system_name.upper()}_CONFIG_JSON"),
    ):
        if not raw:
            continue
        parsed = parse_json_mapping_arg(raw, label)
        overrides.update(parsed)
    return overrides


def official_base_url_for(args: argparse.Namespace, system_name: str) -> str:
    return args.official_base_url or os.environ.get(f"LOCOMO_{system_name.upper()}_BASE_URL", "")


def seed_official_adapter_env(system_name: str, runtime: LLMRuntimeConfig) -> None:
    if system_name != "graphiti_local":
        return
    os.environ.setdefault("GRAPHITI_LLM_API_KEY", runtime.api_key)
    os.environ.setdefault("GRAPHITI_LLM_BASE_URL", runtime.api_base)
    os.environ.setdefault("GRAPHITI_LLM_MODEL", runtime.model)
    os.environ.setdefault("OPENAI_MODEL", runtime.model)


def official_env_snapshot() -> Dict[str, str]:
    names = [
        "MEM0_LOCAL_BASE_URL",
        "MEMOS_LOCAL_BASE_URL",
        "MEMOBASE_BASE_URL",
        "GRAPHITI_LLM_BASE_URL",
        "GRAPHITI_LLM_MODEL",
        "GRAPHITI_EMBEDDING_BASE_URL",
        "GRAPHITI_EMBEDDING_MODEL",
        "GRAPHITI_EMBEDDING_DIM",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_DATABASE",
        "LOCOMO_OFFICIAL_USER_ID",
    ]
    return {name: os.environ.get(name, "") for name in names if os.environ.get(name, "")}



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


def amem_turn_text(turn: DialogTurn) -> str:
    text = (
        f"[dialog_id={turn.dia_id}] "
        f"[session_id={turn.session_id}] "
        f"[session_time={turn.session_date_time}] "
        f"{turn.speaker}: {turn.text}"
    )
    if turn.image_caption:
        text += f"\nImage caption: {turn.image_caption}"
    if turn.image_query:
        text += f"\nImage search query: {turn.image_query}"
    return text


def locomo_amem_timestamp(value: str) -> str:
    parsed = parse_session_date(value)
    if parsed is None:
        return "197001010000"
    return parsed.strftime("%Y%m%d%H%M")


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


def memory_bank_official_answer_user_prompt(row: LoCoMoQAItem, memory_context: str) -> str:
    return (
        "Recalled MemoryBank memories:\n"
        f"{memory_context}\n\n"
        f"Question ID: {row.question_id}\n"
        f"Question: {row.question}\n\n"
        "Do not use benchmark gold answers, gold evidence, categories, or question-type labels. "
        "Cite only dialog IDs present in recalled memories. "
        "Use at most 5 evidence_dialog_ids, choosing the most direct supporting IDs. Return JSON only:\n"
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
        "construction_mode": index.construction_mode,
        "events": [asdict(event) for event in index.events],
        "temporal_facts": [asdict(fact) for fact in index.temporal_facts],
        "durative_memories": [asdict(memory) for memory in index.durative_memories],
        "entity_nodes": [asdict(node) for node in index.entity_nodes.values()],
        "fact_event_index": index.fact_event_index,
        "construction_notes": list(index.construction_notes),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_tsm_index(path: Path) -> TSMIndex:
    payload = json.loads(path.read_text())
    events = [LoCoMoTSMEvent(**item) for item in payload.get("events", [])]
    temporal_facts = [TemporalFact(**item) for item in payload.get("temporal_facts", [])]
    durative_memories = [DurativeMemory(**item) for item in payload.get("durative_memories", [])]
    entity_nodes = {
        str(node.name): node
        for node in (EntityNode(**item) for item in payload.get("entity_nodes", []))
    }
    return TSMIndex(
        events=events,
        events_by_id={event.event_id: event for event in events},
        entity_nodes=entity_nodes,
        temporal_facts=temporal_facts,
        durative_memories=durative_memories,
        fact_event_index={
            str(key): [str(item) for item in value]
            for key, value in dict(payload.get("fact_event_index", {})).items()
            if isinstance(value, list)
        },
        construction_mode=str(payload.get("construction_mode", "llm")),
        construction_notes=[str(item) for item in payload.get("construction_notes", [])],
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


def safe_collection_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")[:60] or "locomo"


def run_variant(
    *,
    variant: str,
    rows: Sequence[LoCoMoQAItem],
    sample: LoCoMoSample,
    rag_corpus: Optional[EmbeddingRAGCorpus],
    answer_runtime: LLMRuntimeConfig,
    args: argparse.Namespace,
) -> Dict[str, object]:
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
    if variant == "a_mem":
        amem_index: Optional[AMemSampleIndex] = AMemSampleIndex(sample, args, answer_runtime)
    else:
        amem_index = None
    if variant in OFFICIAL_SERVICE_VARIANTS:
        official_index: Optional[OfficialServiceSampleIndex] = OfficialServiceSampleIndex(
            variant,
            sample,
            rows,
            args,
            answer_runtime,
        )
    else:
        official_index = None

    def context_for(row: LoCoMoQAItem) -> BaselineContext:
        if variant == "full_text":
            return full_text_context(sample)
        if variant == "rag":
            if rag_corpus is None:
                raise RuntimeError("rag corpus was not initialized")
            return rag_corpus.retrieve(row.question, args.top_k)
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
        if variant == "a_mem":
            if amem_index is None:
                raise RuntimeError("a_mem index was not initialized")
            return amem_index.retrieve(row)
        if variant in OFFICIAL_SERVICE_VARIANTS:
            if official_index is None:
                raise RuntimeError(f"{variant} official adapter was not initialized")
            return official_index.retrieve(row)
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
            "bleu1": None if row.category == 5 else official_bleu1_score(hypothesis, row.answer),
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
    print(f"{'variant':<20} {'n':>4} {'ans_f1':>8} {'task_f1':>8} {'bleu1':>8} {'task_b1':>8} {'exact':>8} {'cand_r':>8} {'cand_p':>8} {'ev_r':>8} {'ev_p':>8} {'ev_f1':>8}")
    print("-" * 125)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<20} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['answer_f1']):>8} "
            f"{format_metric(summary['task_averaged_answer_f1']):>8} "
            f"{format_metric(summary['bleu1']):>8} "
            f"{format_metric(summary['task_averaged_bleu1']):>8} "
            f"{format_metric(summary['exact_match']):>8} "
            f"{format_metric(summary['candidate_dialog_recall']):>8} "
            f"{format_metric(summary['candidate_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_recall']):>8} "
            f"{format_metric(summary['evidence_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_f1']):>8}"
        )


def main() -> int:
    load_dotenv()
    args = parse_args()
    if not args.output:
        args.output = str(default_output_path_for_variants(args))
    sample = load_sample(Path(args.data), args.sample_id)
    rows = select_rows(
        load_sample_qa(Path(args.data), args.sample_id),
        args.question_types,
        args.skip_cases,
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
        print(f"skip_cases={args.skip_cases} limit_cases={args.limit_cases} limit_per_type={args.limit_per_type}")
        print(f"top_k={args.top_k} baseline_store_dir={args.baseline_store_dir}")
        print(f"output={args.output}")
        official_variants = [variant for variant in args.variants if variant in OFFICIAL_SERVICE_VARIANTS]
        if official_variants:
            print(f"official_service_variants={','.join(official_variants)}")
            print(f"official_search_concurrency={args.official_search_concurrency}")
            print(f"official_user_id={args.official_user_id or '[auto: locomo_<variant>_<sample>_<datahash>]'}")
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
    rag_corpus = EmbeddingRAGCorpus(sample, args) if "rag" in args.variants else None
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
        "skip_cases": args.skip_cases,
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
            "memgpt": "official_letta_recall_runtime",
            "letta_command": args.letta_command,
            "letta_code_repo": args.letta_code_repo,
            "letta_backend": args.letta_backend,
            "letta_model": args.letta_model,
            "letta_agent_id": args.letta_agent_id,
            "letta_conversation_id": args.letta_conversation_id,
            "letta_skip_ingest": args.letta_skip_ingest,
            "letta_ingest_chunk_turns": args.letta_ingest_chunk_turns,
            "letta_request_retries": args.letta_request_retries,
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
            "memory_bank_chunk_size": args.memory_bank_chunk_size,
            "memory_bank_answer_prompt_context": "official_search_memory_recall_only",
            "memory_bank_conda_env": args.memory_bank_conda_env,
            "memory_bank_python": args.memory_bank_python,
            "a_mem": "official_agiresearch_a_mem_runtime",
            "amem_repo_dir": args.amem_repo_dir,
            "amem_llm_backend": args.amem_llm_backend,
            "amem_llm_model": args.amem_llm_model or model,
            "amem_embedding_model": args.amem_embedding_model,
            "amem_evo_threshold": args.amem_evo_threshold,
            "amem_agentic_search": args.amem_agentic_search,
            "amem_ingest_limit": args.amem_ingest_limit,
            "tsm_construction_mode": "llm",
            "official_service_variants": list(OFFICIAL_SERVICE_VARIANTS),
            "official_adapter_interface": "EverMemBench Baseline BaseAdapter.add/search",
            "official_user_id": args.official_user_id,
            "official_base_url": args.official_base_url,
            "official_search_concurrency": args.official_search_concurrency,
            "skip_official_ingest": args.skip_official_ingest,
            "force_official_ingest": args.force_official_ingest,
            "official_env": official_env_snapshot(),
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

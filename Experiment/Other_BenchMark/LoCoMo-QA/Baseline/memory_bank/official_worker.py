from __future__ import annotations

import argparse
from collections import defaultdict
import importlib
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Mapping, Sequence


BASELINE_DIR = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = BASELINE_DIR.parent
PROJECT_DIR = BENCHMARK_DIR.parents[2]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import provider_config  # noqa: E402
from ours_scope_time_state.graph_query_runner import LLMRuntimeConfig, short_hash  # noqa: E402
from common.loader import (  # noqa: E402
    DialogTurn,
    LoCoMoSample,
    Session,
    load_sample,
    normalize_dialog_ids,
    ordered_unique,
)
from runner import (  # noqa: E402
    format_official_memorybank_recall,
    load_memory_bank_official_runtime,
    make_sharded_client,
    memory_bank_current_date,
    memory_bank_date_key,
    memory_bank_official_answer_system_prompt,
    memory_bank_official_answer_user_prompt,
    memory_bank_official_complete_text,
    normalize_output_dialog_ids,
    official_memory_bank_dialog_pairs_with_ids,
)


def install_memorybank_langchain_compat() -> None:
    aliases = {
        "langchain.embeddings.huggingface": "langchain_community.embeddings.huggingface",
        "langchain.document_loaders": "langchain_community.document_loaders",
        "langchain.vectorstores": "langchain_community.vectorstores",
        "langchain.text_splitter": "langchain_text_splitters",
        "langchain.docstore.document": "langchain_core.documents",
    }
    for old_name, new_name in aliases.items():
        module = importlib.import_module(new_name)
        sys.modules[old_name] = module
        parent_name, attr_name = old_name.rsplit(".", 1)
        try:
            parent = importlib.import_module(parent_name)
        except ModuleNotFoundError:
            parent = sys.modules.get(parent_name)
            if parent is None:
                parent = ModuleType(parent_name)
                sys.modules[parent_name] = parent
        setattr(parent, attr_name, module)
    vectorstores = importlib.import_module("langchain_community.vectorstores")
    faiss_cls = getattr(vectorstores, "FAISS", None)
    if faiss_cls is not None and not getattr(faiss_cls, "_locomo_memorybank_load_patch", False):
        original_load_local = faiss_cls.load_local

        def load_local_compat(cls: object, folder_path: str, embeddings: object, index_name: str = "index", **kwargs: Any) -> Any:
            kwargs.setdefault("allow_dangerous_deserialization", True)
            return original_load_local(folder_path, embeddings, index_name=index_name, **kwargs)

        faiss_cls.load_local = classmethod(load_local_compat)
        faiss_cls._locomo_memorybank_load_patch = True


class MemoryBankOfficialWorkerIndex:
    def __init__(self, sample: LoCoMoSample, config: argparse.Namespace, runtime: LLMRuntimeConfig) -> None:
        self.sample = sample
        self.config = config
        self.runtime = runtime
        self.user_name = config.memory_bank_user_name or sample.sample_id
        self.boot_name = config.memory_bank_boot_name or "AI"
        self.language = config.memory_bank_language
        self.current_date = memory_bank_current_date(sample, config)
        install_memorybank_langchain_compat()
        self.official = load_memory_bank_official_runtime(config.memory_bank_official_repo)
        self.official_prompts = self.official["prompts"]
        self._patch_official_splitter_chunk_size()
        self.store_dir = Path(config.baseline_store_dir) / "memory_bank" / sample.sample_id
        self.store_path = self.store_dir / "memory_bank.json"
        self.vector_store_dir = self.store_dir / "faiss"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        if config.reuse_baseline_store and self.store_path.exists():
            self.store = json.loads(self.store_path.read_text())
            print(f"[memory-bank-official-worker] load_store {self.store_path}", flush=True)
        else:
            self.store = self._build_store()
            self.store_path.write_text(json.dumps(self.store, ensure_ascii=False, indent=2) + "\n")
            print(f"[memory-bank-official-worker] wrote_store {self.store_path}", flush=True)
        self.memory_id_to_dialog_ids = self._memory_id_to_dialog_ids(self.store)
        self.local_memory_qa = self._new_official_retriever()
        self.vector_store = self._load_or_build_vector_store()
        self._patch_vector_store_signature()
        if self.store_path.exists():
            self.store = json.loads(self.store_path.read_text())
            self.memory_id_to_dialog_ids = self._memory_id_to_dialog_ids(self.store)

    def _build_store(self) -> Dict[str, Any]:
        print(
            f"[memory-bank-official-worker] build_store sample_id={self.sample.sample_id} "
            f"sessions={len(self.sample.sessions)} official_repo={self.official['repo']}",
            flush=True,
        )
        history_by_date: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        summary_by_date: Dict[str, Dict[str, Any]] = {}
        personality_by_date: Dict[str, Any] = {}
        date_dialog_ids: Dict[str, List[str]] = defaultdict(list)

        for index, session in enumerate(self.sample.sessions, start=1):
            date_key = memory_bank_date_key(session)
            content, pair_dialog_ids = official_memory_bank_dialog_pairs_with_ids(session.turns)
            content_prompt = self.official_prompts["summarize_content_prompt"](
                content,
                self.user_name,
                self.boot_name,
                self.language,
            )
            person_prompt = self.official_prompts["summarize_person_prompt"](
                content,
                self.user_name,
                self.boot_name,
                self.language,
            )
            summary_client = make_sharded_client(
                self.runtime,
                "memory_bank_official_session_summary",
                f"{self.sample.sample_id}_{session.session_id}_{short_hash(content_prompt)}",
            )
            summary = memory_bank_official_complete_text(summary_client, self.language, content_prompt).strip()
            person_client = make_sharded_client(
                self.runtime,
                "memory_bank_official_session_personality",
                f"{self.sample.sample_id}_{session.session_id}_{short_hash(person_prompt)}",
            )
            personality = memory_bank_official_complete_text(person_client, self.language, person_prompt).strip()

            start_index = len(history_by_date[date_key])
            for pair_index, pair in enumerate(content):
                memory_id = f"{self.user_name}_{date_key}_{start_index + pair_index}"
                dialog_ids = list(pair_dialog_ids[pair_index])
                history_by_date[date_key].append(
                    {
                        "query": pair["query"],
                        "response": pair["response"],
                        "memory_id": memory_id,
                        "memory_strength": self.config.memory_bank_initial_strength,
                        "last_recall_date": date_key,
                        "dialog_ids": dialog_ids,
                    }
                )
                date_dialog_ids[date_key].extend(dialog_ids)

            if summary:
                if date_key in summary_by_date and summary_by_date[date_key].get("content"):
                    summary_by_date[date_key]["content"] += "\n" + summary
                else:
                    summary_by_date[date_key] = {
                        "content": summary,
                        "memory_strength": self.config.memory_bank_initial_strength,
                        "last_recall_date": date_key,
                        "dialog_ids": [],
                    }
            if personality:
                if date_key in personality_by_date and personality_by_date[date_key]:
                    personality_by_date[date_key] = f"{personality_by_date[date_key]}\n{personality}"
                else:
                    personality_by_date[date_key] = personality
            print(f"[memory-bank-official-worker] session_summary {index}/{len(self.sample.sessions)} {session.session_id}", flush=True)

        for date_key, dialog_ids in date_dialog_ids.items():
            if date_key in summary_by_date:
                summary_by_date[date_key]["dialog_ids"] = ordered_unique(dialog_ids)

        summary_items = [(date_key, {"content": item.get("content", "")}) for date_key, item in sorted(summary_by_date.items())]
        personality_items = [(date_key, str(item)) for date_key, item in sorted(personality_by_date.items())]
        overall_history_prompt = self.official_prompts["summarize_overall_prompt"](summary_items, self.language)
        overall_personality_prompt = self.official_prompts["summarize_overall_personality"](personality_items, self.language)
        history_client = make_sharded_client(
            self.runtime,
            "memory_bank_official_overall_history",
            f"{self.sample.sample_id}_{short_hash(overall_history_prompt)}",
        )
        personality_client = make_sharded_client(
            self.runtime,
            "memory_bank_official_overall_personality",
            f"{self.sample.sample_id}_{short_hash(overall_personality_prompt)}",
        )
        overall_history = memory_bank_official_complete_text(history_client, self.language, overall_history_prompt).strip()
        overall_personality = memory_bank_official_complete_text(personality_client, self.language, overall_personality_prompt).strip()

        return {
            self.user_name: {
                "history": dict(sorted(history_by_date.items())),
                "summary": dict(sorted(summary_by_date.items())),
                "personality": dict(sorted(personality_by_date.items())),
                "overall_history": overall_history,
                "overall_personality": overall_personality,
                "_locomo_metadata": {
                    "schema_version": "locomo-memory-bank-official-runtime-v1",
                    "sample_id": self.sample.sample_id,
                    "official_repo": str(self.official["repo"]),
                    "official_components": [
                        "memory_bank/summarize_memory.py prompts",
                        "memory_bank/memory_retrieval/forget_memory.py LocalMemoryRetrieval",
                        "langchain.vectorstores.FAISS",
                    ],
                    "summary_mode": "official_prompt_llm",
                    "current_date": self.current_date,
                    "initial_strength": self.config.memory_bank_initial_strength,
                },
            }
        }

    def _new_official_retriever(self) -> Any:
        retriever = self.official["LocalMemoryRetrieval"]()
        retriever.init_cfg(
            embedding_model=self.config.memory_bank_embedding_model,
            embedding_device=self.config.memory_bank_embedding_device,
            top_k=self.config.top_k,
            language=self.language,
        )
        retriever.chunk_size = int(self.config.memory_bank_chunk_size)
        return retriever

    def _patch_official_splitter_chunk_size(self) -> None:
        module = self.official.get("module")
        if module is None:
            return
        chunk_size = int(self.config.memory_bank_chunk_size)
        if chunk_size <= 0:
            return
        if getattr(module, "_locomo_memorybank_splitter_chunk_size", None) == chunk_size:
            return
        splitter_cls = getattr(module, "ChineseTextSplitter", None)
        if splitter_cls is None:
            return

        class ChunkedChineseTextSplitter(splitter_cls):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs.setdefault("chunk_size", chunk_size)
                kwargs.setdefault("chunk_overlap", 0)
                super().__init__(*args, **kwargs)

            def split_text(self, text: str) -> List[str]:
                chunks: List[str] = []
                for piece in super().split_text(text):
                    if not piece:
                        continue
                    if len(piece) <= chunk_size:
                        chunks.append(piece)
                        continue
                    chunks.extend(piece[start : start + chunk_size] for start in range(0, len(piece), chunk_size))
                return chunks

        ChunkedChineseTextSplitter.__name__ = getattr(splitter_cls, "__name__", "ChineseTextSplitter")
        module.ChineseTextSplitter = ChunkedChineseTextSplitter
        module._locomo_memorybank_splitter_chunk_size = chunk_size

    def _load_or_build_vector_store(self) -> Any:
        if self.config.reuse_baseline_store and (self.vector_store_dir / "index.faiss").exists():
            loader = self.official["MemoryForgetterLoader"](str(self.store_path), self.language)
            loader.load_memories(str(self.store_path))
            self.local_memory_qa.memory_loader = loader
            self.local_memory_qa.memory_path = str(self.store_path)
            self.local_memory_qa.user = self.user_name
            print(f"[memory-bank-official-worker] load_faiss {self.vector_store_dir}", flush=True)
            return self.local_memory_qa.load_memory_index(str(self.vector_store_dir))

        built_vs_path, loaded_files = self.local_memory_qa.init_memory_vector_store(
            str(self.store_path),
            str(self.vector_store_dir),
            self.user_name,
            self.current_date,
        )
        if not built_vs_path:
            raise RuntimeError(f"official MemoryBank failed to build FAISS index from {self.store_path}; loaded_files={loaded_files}")
        print(f"[memory-bank-official-worker] built_faiss {built_vs_path}", flush=True)
        return self.local_memory_qa.load_memory_index(str(built_vs_path))

    def _patch_vector_store_signature(self) -> None:
        vector_store_cls = self.vector_store.__class__
        if getattr(vector_store_cls, "_locomo_memorybank_search_patch", False):
            return
        original = vector_store_cls.similarity_search_with_score_by_vector

        def search_with_score_by_vector_compat(self_obj: object, embedding: List[float], k: int = 4, **_: Any) -> Any:
            return original(self_obj, embedding, k=k)

        vector_store_cls.similarity_search_with_score_by_vector = search_with_score_by_vector_compat
        vector_store_cls._locomo_memorybank_search_patch = True

    def _memory_id_to_dialog_ids(self, store: Mapping[str, Any]) -> Dict[str, List[str]]:
        user_store = store.get(self.user_name) if isinstance(store.get(self.user_name), Mapping) else {}
        history = user_store.get("history") if isinstance(user_store.get("history"), Mapping) else {}
        summary = user_store.get("summary") if isinstance(user_store.get("summary"), Mapping) else {}
        date_dialog_ids: Dict[str, List[str]] = defaultdict(list)
        lookup: Dict[str, List[str]] = {}
        for date_key, entries in history.items():
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries):
                if not isinstance(entry, Mapping):
                    continue
                memory_id = str(entry.get("memory_id") or f"{self.user_name}_{date_key}_{index}")
                dialog_ids = normalize_dialog_ids(entry.get("dialog_ids"))
                if not dialog_ids:
                    dialog_ids = ordered_unique(re.findall(r"\bD\d+:\d+\b", f"{entry.get('query', '')}\n{entry.get('response', '')}"))
                lookup[memory_id] = dialog_ids
                date_dialog_ids[str(date_key)].extend(dialog_ids)
        for date_key, item in summary.items():
            if isinstance(item, Mapping):
                dialog_ids = normalize_dialog_ids(item.get("dialog_ids"))
            else:
                dialog_ids = []
            if not dialog_ids:
                dialog_ids = ordered_unique(date_dialog_ids.get(str(date_key), []))
            lookup[f"{self.user_name}_{date_key}_summary"] = dialog_ids
        return lookup

    def retrieve(self, question_id: str, question: str) -> Dict[str, object]:
        related_memos, memory_ids_text = self.local_memory_qa.search_memory(
            question,
            self.vector_store,
            cur_date=self.current_date,
        )
        sources = [source.strip() for source in str(memory_ids_text).split(",") if source.strip()]
        candidate_dialog_ids = self._candidate_dialog_ids(sources, related_memos)
        memory_context = format_official_memorybank_recall(related_memos, sources)
        row = SimpleNamespace(question_id=question_id, question=question)
        output_client = make_sharded_client(
            self.runtime,
            "memory_bank_official_answer",
            f"{question_id}_{short_hash(question + memory_context)}",
        )
        output = output_client.complete_json(
            memory_bank_official_answer_system_prompt(),
            memory_bank_official_answer_user_prompt(row, memory_context),
        )
        evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
        return {
            "candidate_dialog_ids": candidate_dialog_ids,
            "context": memory_context,
            "direct_answer": str(output.get("answer") or "").strip(),
            "direct_evidence_dialog_ids": evidence_dialog_ids,
            "trace": {
                "retriever": "official_memorybank_faiss",
                "official_runtime": "MemoryBank-SiliconFriend",
                "official_repo": str(self.official["repo"]),
                "runtime_isolation": "subprocess",
                "official_components": [
                    "memory_bank/summarize_memory.py prompts",
                    "memory_bank/memory_retrieval/forget_memory.py LocalMemoryRetrieval",
                    "langchain.vectorstores.FAISS",
                ],
                "embedding_model": self.config.memory_bank_embedding_model,
                "embedding_device": self.config.memory_bank_embedding_device,
                "current_date": self.current_date,
                "top_k": self.config.top_k,
                "chunk_size": self.config.memory_bank_chunk_size,
                "chunk_size_applied_to": "official_index_splitter_and_faiss_neighbor_expansion",
                "answer_prompt_context": "official_search_memory_recall_only",
                "sources": sources,
                "candidate_dialog_ids_source": "official_memory_ids_mapped_to_dialog_ids",
                "n_recalled": len(related_memos),
            },
        }

    def _candidate_dialog_ids(self, sources: Sequence[str], related_memos: Sequence[str]) -> List[str]:
        dialog_ids: List[str] = []
        for source in sources:
            dialog_ids.extend(self.memory_id_to_dialog_ids.get(source, []))
        for memo in related_memos:
            dialog_ids.extend(re.findall(r"\bD\d+:\d+\b", str(memo)))
        return ordered_unique(dialog_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated official MemoryBank LoCoMo worker.")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    return parser.parse_args()


def namespace_from_request(request: Mapping[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        data=str(request["data"]),
        sample_id=str(request["sample_id"]),
        top_k=int(request["top_k"]),
        baseline_store_dir=str(request["baseline_store_dir"]),
        reuse_baseline_store=bool(request.get("reuse_baseline_store")),
        memory_bank_official_repo=str(request["memory_bank_official_repo"]),
        memory_bank_language=str(request.get("memory_bank_language") or "en"),
        memory_bank_user_name=str(request.get("memory_bank_user_name") or ""),
        memory_bank_boot_name=str(request.get("memory_bank_boot_name") or "AI"),
        memory_bank_initial_strength=float(request.get("memory_bank_initial_strength") or 1.0),
        memory_bank_current_date=str(request.get("memory_bank_current_date") or ""),
        memory_bank_embedding_model=str(request.get("memory_bank_embedding_model") or "minilm-l6"),
        memory_bank_embedding_device=str(request.get("memory_bank_embedding_device") or "cpu"),
        memory_bank_chunk_size=int(request.get("memory_bank_chunk_size") or 12),
    )


def runtime_from_request(request: Mapping[str, Any]) -> LLMRuntimeConfig:
    provider = str(request.get("provider") or "deepseek")
    api_key, default_model, api_base = provider_config(provider)
    model = str(request.get("model") or default_model)
    return LLMRuntimeConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(str(request["cache"])),
        use_cache=bool(request.get("use_cache", True)),
    )


def main() -> int:
    args = parse_args()
    load_dotenv()
    request_path = Path(args.request)
    response_path = Path(args.response)
    request = json.loads(request_path.read_text())
    config = namespace_from_request(request)
    runtime = runtime_from_request(request)
    sample = load_sample(Path(config.data), config.sample_id)
    index = MemoryBankOfficialWorkerIndex(sample, config, runtime)
    contexts: Dict[str, Dict[str, object]] = {}
    for item in request.get("questions", []):
        if not isinstance(item, Mapping):
            continue
        question_id = str(item.get("question_id") or "")
        question = str(item.get("question") or "")
        if not question_id or not question:
            continue
        contexts[question_id] = index.retrieve(question_id, question)
        print(f"[memory-bank-official-worker] answered {question_id}", flush=True)
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(
        json.dumps(
            {
                "schema_version": "locomo-memory-bank-worker-response-v1",
                "contexts": contexts,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

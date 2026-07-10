"""Embedding-RAG baseline for EverMemBench group-chat QA."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

from common.official_eval.imports import AddResult, BaseAdapter, Dataset, GroupChatMessage, SearchResult, get_console, print_success


PROJECT_DIR = Path(__file__).resolve().parents[6]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex  # noqa: E402


@dataclass(frozen=True)
class DialogueChunk:
    chunk_id: str
    text: str


class EmbeddingRAGAdapter(BaseAdapter):
    """Dense retrieval over day-and-group-local dialogue chunks."""

    def __init__(self, config: Dict[str, Any], output_dir: Optional[Path] = None):
        super().__init__(config, output_dir)
        self.console = get_console()
        self.embedding_model = str(config.get("embedding_model") or "text-embedding-3-small")
        self.embedding_base_url = str(config.get("embedding_base_url") or "") or None
        self.embedding_cache = Path(str(config.get("embedding_cache") or "Graph/output/cache/evermembench_embedding_rag"))
        if not self.embedding_cache.is_absolute():
            self.embedding_cache = PROJECT_DIR / self.embedding_cache
        self.embedding_batch_size = max(1, int(config.get("embedding_batch_size", 48)))
        self.chunk_target_chars = max(400, int(config.get("chunk_target_chars", 2400)))
        self.chunk_overlap_messages = max(0, int(config.get("chunk_overlap_messages", 1)))
        self.default_top_k = max(1, int(config.get("search", {}).get("top_k", 10)))
        self._chunks: List[DialogueChunk] = []
        self._chunks_by_id: Dict[str, DialogueChunk] = {}
        self._index: Optional[OpenAIEmbeddingIndex] = None

        self.console.print("EmbeddingRAGAdapter initialized", style="bold green")
        self.console.print(f"   Embedding model: {self.embedding_model}")
        self.console.print(f"   Chunk target: {self.chunk_target_chars} characters")

    async def add(
        self,
        dataset: Dataset,
        user_id: str,
        days_to_process: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> AddResult:
        days = [day for day in dataset.days if day.date in days_to_process] if days_to_process else dataset.days
        self._chunks = self._build_chunks(days)
        if not self._chunks:
            raise ValueError("Embedding RAG cannot build an index from an empty dataset")
        self._chunks_by_id = {chunk.chunk_id: chunk for chunk in self._chunks}

        dataset_fingerprint = hashlib.sha256(
            "\n".join(f"{chunk.chunk_id}\t{chunk.text}" for chunk in self._chunks).encode("utf-8")
        ).hexdigest()[:16]
        self._index = OpenAIEmbeddingIndex(
            [chunk.chunk_id for chunk in self._chunks],
            [chunk.text for chunk in self._chunks],
            model=self.embedding_model,
            cache_path=self.embedding_cache,
            namespace=f"evermembench:embedding-rag:{dataset.name}:{dataset_fingerprint}",
            batch_size=self.embedding_batch_size,
            base_url=self.embedding_base_url,
        )

        start = time.perf_counter()
        await asyncio.to_thread(self._index.embed_documents)
        elapsed = time.perf_counter() - start
        total_messages = sum(day.total_messages for day in days)
        print_success(f"Embedding RAG indexed {len(self._chunks)} chunks from {total_messages} messages")
        return AddResult(
            success=True,
            days_processed=len(days),
            messages_sent=0,
            metadata={
                "mode": "embedding_rag",
                "embedding_model": self.embedding_model,
                "chunk_count": len(self._chunks),
                "total_messages": total_messages,
                "index_seconds": elapsed,
            },
        )

    async def search(
        self,
        query: str,
        user_id: str,
        top_k: int = 10,
        **kwargs: Any,
    ) -> SearchResult:
        if self._index is None:
            raise ValueError("Embedding RAG index is not initialized; run the add stage first")
        effective_top_k = max(1, int(top_k or self.default_top_k))
        start = time.perf_counter()
        hits = await asyncio.to_thread(self._index.search, query, effective_top_k)
        elapsed_ms = (time.perf_counter() - start) * 1000
        chunks = [self._chunks_by_id[hit.doc_id] for hit in hits if hit.doc_id in self._chunks_by_id]
        memories = [chunk.text for chunk in chunks]
        context = "\n\n".join(
            f"[Retrieved chunk {index}]\n{chunk.text}" for index, chunk in enumerate(chunks, start=1)
        ) or "(No dialogue chunks retrieved)"
        return SearchResult(
            question_id=str(kwargs.get("question_id") or ""),
            query=query,
            retrieved_memories=memories,
            context=context,
            search_duration_ms=elapsed_ms,
            metadata={
                "mode": "embedding_rag",
                "embedding_model": self.embedding_model,
                "top_k": effective_top_k,
                "hits": [{"chunk_id": hit.doc_id, "score": hit.score} for hit in hits],
            },
        )

    def _build_chunks(self, days: Sequence[Any]) -> List[DialogueChunk]:
        chunks: List[DialogueChunk] = []
        for day in days:
            for group_name in sorted(day.groups):
                messages = day.groups[group_name]
                for chunk_index, chunk_messages in enumerate(self._chunk_messages(messages), start=1):
                    header = f"Date: {day.date}\nGroup: {group_name}"
                    body = "\n".join(self._format_message(message) for message in chunk_messages)
                    chunks.append(
                        DialogueChunk(
                            chunk_id=f"{day.date}:{group_name}:chunk-{chunk_index:03d}",
                            text=f"{header}\n{body}",
                        )
                    )
        return chunks

    def _chunk_messages(self, messages: Sequence[GroupChatMessage]) -> List[List[GroupChatMessage]]:
        chunks: List[List[GroupChatMessage]] = []
        current: List[GroupChatMessage] = []
        current_chars = 0
        for message in messages:
            formatted_length = len(self._format_message(message)) + 1
            if current and current_chars + formatted_length > self.chunk_target_chars:
                chunks.append(current)
                overlap = current[-self.chunk_overlap_messages :] if self.chunk_overlap_messages else []
                current = list(overlap)
                current_chars = sum(len(self._format_message(item)) + 1 for item in current)
            current.append(message)
            current_chars += formatted_length
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _format_message(message: GroupChatMessage) -> str:
        return f"[{message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {message.speaker}: {message.content}"

    async def close(self) -> None:
        self._index = None
        self._chunks = []
        self._chunks_by_id = {}

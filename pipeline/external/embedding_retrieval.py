from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


def env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmbeddingHit:
    doc_id: str
    score: float


class OpenAIEmbeddingIndex:
    """Cached dense retriever over the full corpus or an explicit allowed subset."""

    def __init__(
        self,
        doc_ids: Sequence[str],
        documents: Sequence[str],
        *,
        model: str,
        cache_path: Path,
        namespace: str,
        batch_size: int = 24,
        base_url: Optional[str] = None,
    ) -> None:
        if len(doc_ids) != len(documents):
            raise ValueError("doc_ids and documents must have the same length")
        if batch_size <= 0:
            raise ValueError("embedding batch_size must be positive")
        self.doc_ids = [str(doc_id) for doc_id in doc_ids]
        self._document_index_by_id = {doc_id: index for index, doc_id in enumerate(self.doc_ids)}
        self.doc_by_id = {
            str(doc_id): " ".join(str(document or "").split())[:6000]
            for doc_id, document in zip(doc_ids, documents)
        }
        self.model = model
        self.cache_path = cache_path
        self.cache_root = _cache_root(cache_path)
        self.namespace = namespace
        self.batch_size = batch_size
        self.base_url = base_url
        self._lock = RLock()
        self._document_vectors_by_id: Dict[str, List[float]] = {}
        self._document_matrix: Any = None

    def _cache_key(self, kind: str, doc_id: str, text: str) -> str:
        return f"{self.namespace}:{self.model}:{kind}:{doc_id}:{_hash_text(text)}"

    def _cache_file(self, cache_key: str) -> Path:
        digest = _hash_text(cache_key)
        return self.cache_root / digest[:2] / f"{digest}.json"

    def _read_cached_vector(self, cache_key: str) -> Optional[List[float]]:
        path = self._cache_file(cache_key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        embedding = payload.get("embedding") if isinstance(payload, dict) else None
        if not isinstance(embedding, list):
            return None
        return [float(value) for value in embedding]

    def _write_cached_vector(self, cache_key: str, vector: Sequence[float]) -> None:
        path = self._cache_file(cache_key)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"embedding": list(vector)}, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

    def _client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI embeddings require the openai Python package") from exc
        api_key = env_first("OPENAI_EMBEDDING_API_KEY", "OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("missing OPENAI_EMBEDDING_API_KEY or OPENAI_API_KEY for OpenAI embeddings")
        resolved_base_url = self.base_url or env_first(
            "OPENAI_EMBEDDING_BASE_URL",
            "OPENAI_EMBEDDING_API_BASE",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
        )
        kwargs: Dict[str, Any] = {"api_key": api_key, "timeout": 60.0, "max_retries": 0}
        if resolved_base_url:
            kwargs["base_url"] = resolved_base_url
        return OpenAI(**kwargs)

    def _embed_texts(self, texts: Sequence[str], cache_keys: Sequence[str]) -> List[List[float]]:
        vectors: List[Optional[List[float]]] = [None] * len(texts)
        missing_indexes: List[int] = []
        for index, cache_key in enumerate(cache_keys):
            cached = self._read_cached_vector(cache_key)
            if cached is None:
                missing_indexes.append(index)
            else:
                vectors[index] = cached
        if missing_indexes:
            client = self._client()
            for start in range(0, len(missing_indexes), self.batch_size):
                batch_indexes = missing_indexes[start : start + self.batch_size]
                batch = [texts[index] for index in batch_indexes]
                response = self._create_embeddings_with_retry(client, batch)
                for item in sorted(response.data, key=lambda value: value.index):
                    source_index = batch_indexes[item.index]
                    vector = _normalize_vector([float(value) for value in item.embedding])
                    vectors[source_index] = vector
                    self._write_cached_vector(cache_keys[source_index], vector)
        return [vector or [] for vector in vectors]

    def embed_query(self, query: str) -> List[float]:
        key = self._cache_key("query", _hash_text(query), query)
        return self._embed_texts([query], [key])[0]

    def embed_documents(self) -> None:
        """Materialize and cache every document embedding in the index."""
        documents = [self.doc_by_id[doc_id] for doc_id in self.doc_ids]
        cache_keys = [self._cache_key("doc", doc_id, self.doc_by_id[doc_id]) for doc_id in self.doc_ids]
        vectors = self._embed_texts(documents, cache_keys)
        self._document_vectors_by_id = dict(zip(self.doc_ids, vectors))
        try:
            import numpy as np
        except ImportError:
            self._document_matrix = None
        else:
            self._document_matrix = np.asarray(vectors, dtype=np.float32)

    def _create_embeddings_with_retry(self, client: Any, batch: Sequence[str]) -> Any:
        delay_seconds = 5.0
        for attempt in range(1, 8):
            try:
                return client.embeddings.create(model=self.model, input=list(batch))
            except Exception as exc:
                message = str(exc)
                is_rate_limit = "429" in message or "RateLimit" in type(exc).__name__ or "rate limit" in message.lower()
                is_transient_connection = (
                    "APIConnectionError" in type(exc).__name__
                    or "ConnectError" in type(exc).__name__
                    or "connection reset" in message.lower()
                    or "connection error" in message.lower()
                    or "timed out" in message.lower()
                    or "timeout" in message.lower()
                )
                if not (is_rate_limit or is_transient_connection) or attempt >= 7:
                    raise
                retry_after = _retry_after_seconds(exc)
                sleep_seconds = retry_after if retry_after is not None else delay_seconds
                time.sleep(min(max(sleep_seconds, 1.0), 90.0))
                delay_seconds = min(delay_seconds * 1.8, 60.0)

    def search(
        self,
        query: str,
        top_k: int,
        allowed_doc_ids: Optional[Iterable[str]] = None,
        max_candidates: Optional[int] = None,
    ) -> List[EmbeddingHit]:
        if top_k <= 0:
            return []
        if allowed_doc_ids is None:
            candidate_ids = self.doc_ids
        else:
            allowed: Set[str] = {str(value) for value in allowed_doc_ids if str(value) in self.doc_by_id}
            candidate_ids = [doc_id for doc_id in self.doc_ids if doc_id in allowed]
        if max_candidates is not None:
            if max_candidates <= 0:
                return []
            candidate_ids = candidate_ids[:max_candidates]
        if not candidate_ids:
            return []
        query_vector = self.embed_query(str(query or ""))

        if self._document_matrix is not None:
            import numpy as np

            matrix_indexes = [self._document_index_by_id[doc_id] for doc_id in candidate_ids]
            scores = self._document_matrix[matrix_indexes] @ np.asarray(query_vector, dtype=np.float32)
            limit = min(top_k, len(candidate_ids))
            indexes = np.argpartition(scores, -limit)[-limit:]
            ranked_indexes = sorted(indexes.tolist(), key=lambda index: (-float(scores[index]), candidate_ids[index]))
            return [EmbeddingHit(doc_id=candidate_ids[index], score=float(scores[index])) for index in ranked_indexes]

        missing_ids = [doc_id for doc_id in candidate_ids if doc_id not in self._document_vectors_by_id]
        if missing_ids:
            missing_vectors = self._embed_texts(
                [self.doc_by_id[doc_id] for doc_id in missing_ids],
                [self._cache_key("doc", doc_id, self.doc_by_id[doc_id]) for doc_id in missing_ids],
            )
            self._document_vectors_by_id.update(zip(missing_ids, missing_vectors))
        vectors = [self._document_vectors_by_id.get(doc_id, []) for doc_id in candidate_ids]
        scored = [
            EmbeddingHit(doc_id=doc_id, score=_dot(query_vector, vector))
            for doc_id, vector in zip(candidate_ids, vectors)
            if vector
        ]
        scored.sort(key=lambda item: (-item.score, item.doc_id))
        return scored[:top_k]


def _cache_root(cache_path: Path) -> Path:
    return cache_path if not cache_path.suffix else cache_path.with_name(f"{cache_path.name}.d")


def _normalize_vector(vector: Sequence[float]) -> List[float]:
    norm = sum(value * value for value in vector) ** 0.5
    if norm <= 0.0:
        return [0.0 for _ in vector]
    return [value / norm for value in vector]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get("retry-after") or headers.get("Retry-After")
        if value:
            try:
                return float(value)
            except ValueError:
                pass
    match = re.search(r"retry after\s+(\d+(?:\.\d+)?)\s+seconds?", str(exc), re.I)
    if match:
        return float(match.group(1))
    return None

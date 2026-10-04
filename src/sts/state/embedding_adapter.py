from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol, Sequence


class EmbeddingBackend(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class CachedEmbeddingService:
    """Small persistent cache around the project's embedding provider."""

    def __init__(
        self,
        backend: EmbeddingBackend,
        cache_path: Path | None = None,
        batch_size: int = 64,
    ):
        self.backend = backend
        self.cache_path = cache_path
        self.batch_size = batch_size
        self._cache: dict[str, list[float]] = {}
        if cache_path and cache_path.exists():
            self._cache = json.loads(cache_path.read_text(encoding="utf-8"))

    def _key(self, text: str, logical_key: str, feature_version: str) -> str:
        payload = "\0".join(
            [logical_key, self.backend.model_name, feature_version, text]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def embed(
        self,
        texts: Sequence[str],
        logical_keys: Sequence[str],
        feature_version: str,
    ) -> list[list[float]]:
        if len(texts) != len(logical_keys):
            raise ValueError("texts and logical_keys must have equal length")
        keys = [
            self._key(text, logical_key, feature_version)
            for text, logical_key in zip(texts, logical_keys)
        ]
        missing_positions = [
            index for index, key in enumerate(keys) if key not in self._cache
        ]
        for start in range(0, len(missing_positions), self.batch_size):
            positions = missing_positions[start : start + self.batch_size]
            vectors = self.backend.embed([texts[index] for index in positions])
            if len(vectors) != len(positions):
                raise RuntimeError("Embedding provider returned the wrong row count")
            for position, vector in zip(positions, vectors):
                self._cache[keys[position]] = [float(value) for value in vector]
        if missing_positions:
            self._save()
        return [self._cache[key] for key in keys]

    def _save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_name(f".{self.cache_path.name}.tmp")
        temporary.write_text(
            json.dumps(self._cache, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, self.cache_path)

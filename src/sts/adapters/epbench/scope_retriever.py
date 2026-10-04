from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from sts.graph.types import Event, Scope


FEATURE_VERSION = "epbench-scope-theme-embedding-v1"


def event_theme_text(event: Event) -> str:
    return "\n".join(
        [
            f"Title: {event.subject or ''}",
            f"Summary: {event.summary}",
        ]
    )


def scope_theme_text(scope: Scope) -> str:
    return "\n".join(
        [
            f"Title: {scope.title}",
            f"Summary: {scope.summary}",
        ]
    )


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise RuntimeError("Embedding dimensions do not match")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class ScopeEmbeddingRetriever:
    def __init__(self, provider, cache_path: Path):
        self.provider = provider
        self.cache_path = cache_path
        self._cache: dict[str, list[float]] = {}
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                payload.get("feature_version") == FEATURE_VERSION
                and payload.get("embedding_model")
                == str(provider.model_name)
            ):
                self._cache = {
                    str(key): [float(value) for value in vector]
                    for key, vector in payload.get("vectors", {}).items()
                }

    def _key(self, text: str) -> str:
        value = "\0".join(
            [FEATURE_VERSION, str(self.provider.model_name), text]
        )
        return hashlib.sha256(value.encode()).hexdigest()

    async def _vectors(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(text) for text in texts]
        missing_keys = []
        missing_texts = []
        for key, text in zip(keys, texts):
            if key not in self._cache and key not in missing_keys:
                missing_keys.append(key)
                missing_texts.append(text)
        if missing_texts:
            vectors = await self.provider.embed(missing_texts)
            if len(vectors) != len(missing_texts):
                raise RuntimeError(
                    "Embedding provider returned the wrong row count"
                )
            for key, vector in zip(missing_keys, vectors):
                self._cache[key] = [float(value) for value in vector]
            self._save()
        return [self._cache[key] for key in keys]

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_name(
            f".{self.cache_path.name}.tmp"
        )
        temporary.write_text(
            json.dumps(
                {
                    "feature_version": FEATURE_VERSION,
                    "embedding_model": str(self.provider.model_name),
                    "vectors": self._cache,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.cache_path)

    async def top_k(
        self,
        event: Event,
        scopes: list[Scope],
        k: int,
    ) -> list[tuple[Scope, float]]:
        if not scopes:
            return []
        texts = [
            event_theme_text(event),
            *(scope_theme_text(scope) for scope in scopes),
        ]
        vectors = await self._vectors(texts)
        query = vectors[0]
        ranked = sorted(
            (
                (scope, _cosine(query, vector), index)
                for index, (scope, vector) in enumerate(
                    zip(scopes, vectors[1:])
                )
            ),
            key=lambda item: (-item[1], item[2]),
        )
        return [
            (scope, score)
            for scope, score, _ in ranked[: max(1, k)]
        ]

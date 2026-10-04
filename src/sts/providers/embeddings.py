from __future__ import annotations

import asyncio
import re
from typing import List

import aiohttp
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np
import time

class EmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        model_name: str,
        timeout: int = 120,
        max_retries: int = 5,
        api_key: str = "",
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_key = api_key

        # Create a session with retry mechanism
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,  # 1, 2, 4, 8, 16 seconds wait
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def cosine_similarity(self, query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        """
        Calculates cosine similarity between a query vector and multiple document vectors.

        Args:
            query_vec: A 1D numpy array for the query.
            doc_vecs: A 2D numpy array where each row is a document vector.

        Returns:
            A 1D numpy array of cosine similarity scores.
        """
        # Calculate dot product
        dot_product = np.dot(doc_vecs, query_vec)

        # Calculate norms
        query_norm = np.linalg.norm(query_vec)
        doc_norms = np.linalg.norm(doc_vecs, axis=1)

        # Calculate cosine similarity, handling potential division by zero
        denominator = query_norm * doc_norms
        # Replace 0s in denominator with a small number to avoid division by zero
        denominator[denominator == 0] = 1e-9

        similarity_scores = dot_product / denominator

        return similarity_scores

    def embed(self, texts: List[str]) -> List[List[float]]:
        # Manual retry logic (handles connection interruption and other exceptions)
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.post(
                    self.base_url,
                    json={"input": texts, "model": self.model_name},
                    headers=(
                        {"Authorization": f"Bearer {self.api_key}"}
                        if self.api_key
                        else None
                    ),
                    timeout=self.timeout
                )
                response.raise_for_status()
                result = response.json()
                vectors = [item['embedding'] for item in result['data']]
                return vectors
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                last_exception = e
                wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8, 16 seconds
                print(f"    [!] Connection failed (attempt {attempt + 1}/{self.max_retries}), retrying in {wait_time}s: {str(e)[:50]}")
                time.sleep(wait_time)
            except Exception as e:
                # Raise other errors directly
                raise e

        # All retries exhausted
        raise last_exception


def embedding_endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    return f"{value}/embeddings" if value.endswith("/v1") else value


class OpenAIEmbeddingProvider:
    """Asynchronous OpenAI-compatible embedding client."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str = "",
        timeout_seconds: int = 120,
        max_retries: int = 5,
    ):
        self.base_url = embedding_endpoint(base_url)
        self.model_name = model_name
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(
            timeout=timeout,
            trust_env=True,
        ) as session:
            for attempt in range(self.max_retries):
                async with session.post(
                    self.base_url,
                    json={"input": texts, "model": self.model_name},
                    headers=headers,
                ) as response:
                    payload = await response.json(content_type=None)
                    if response.status == 200:
                        break
                    message = payload.get("error", {}).get(
                        "message", f"HTTP {response.status}"
                    )
                    if (
                        response.status != 429
                        or attempt == self.max_retries - 1
                    ):
                        raise RuntimeError(
                            f"Embedding request failed: {message}"
                        )
                    retry_after = response.headers.get("Retry-After", "")
                    match = re.search(
                        r"retry after\s+(\d+(?:\.\d+)?)\s*seconds?",
                        message,
                        flags=re.IGNORECASE,
                    )
                    delay = (
                        float(retry_after)
                        if retry_after.replace(".", "", 1).isdigit()
                        else float(match.group(1))
                        if match
                        else min(2 ** attempt, 30)
                    )
                    await asyncio.sleep(min(max(delay, 1.0), 60.0))
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Embedding response requires a data list")
        ordered = sorted(rows, key=lambda row: int(row.get("index", 0)))
        vectors = [row.get("embedding") for row in ordered]
        if len(vectors) != len(texts) or any(
            not isinstance(vector, list) or not vector for vector in vectors
        ):
            raise RuntimeError(
                "Embedding provider returned an invalid row count or vector"
            )
        return [
            [float(value) for value in vector]
            for vector in vectors
        ]

if __name__ == "__main__":
    inputs = [
        "Tom moved here from his hometown last month",
        "Frank's hometown is Switzerland",
    ]

    provider = EmbeddingProvider(base_url="http://0.0.0.0:11000/v1/embeddings", model_name="Qwen3-Embedding-4B")
    print(provider.embed(inputs))

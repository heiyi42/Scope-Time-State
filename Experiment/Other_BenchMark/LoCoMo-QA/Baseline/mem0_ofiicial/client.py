"""Small OSS REST client matching mem0ai/memory-benchmarks' Mem0Client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp


LOGGER = logging.getLogger(__name__)


class Mem0OfficialOSSClient:
    """Mem0 OSS client with the official benchmark's request shapes.

    The important compatibility details are intentional:
    - ``POST /memories`` receives ``timestamp`` and no local ``run_id`` field.
    - ``POST /search`` receives ``user_id`` and ``limit`` (not ``top_k``).
    - OSS search is scoped by the user id in the request body.
    """

    def __init__(
        self,
        host: str,
        *,
        api_key: str = "",
        max_retries: int = 5,
        retry_delay: float = 5.0,
        timeout: float = 300.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.max_retries = max(1, int(max_retries))
        self.retry_delay = max(0.0, float(retry_delay))
        self.timeout = aiohttp.ClientTimeout(total=float(timeout))
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers, timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "Mem0OfficialOSSClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def add(
        self,
        messages: List[Dict[str, str]],
        user_id: str,
        *,
        timestamp: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {"messages": messages, "user_id": user_id}
        if timestamp is not None:
            payload["timestamp"] = int(timestamp)

        for attempt in range(self.max_retries):
            try:
                session = await self._get_session()
                async with session.post(f"{self.host}/memories", json=payload) as response:
                    if response.status >= 500:
                        raise RuntimeError(f"Mem0 add HTTP {response.status}: {await response.text()}")
                    response.raise_for_status()
                    data = await response.json()
                if isinstance(data, dict):
                    return data if "results" in data else {"results": []}
                if isinstance(data, list):
                    return {"results": data}
                return {"results": []}
            except Exception as exc:
                if attempt >= self.max_retries - 1:
                    LOGGER.error("Mem0 add failed after %d attempts: %s", self.max_retries, exc)
                    return None
                await asyncio.sleep(self.retry_delay * (attempt + 1))
        return None

    async def search(
        self,
        query: str,
        user_id: str,
        *,
        top_k: int = 200,
        rerank: bool = False,
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"query": query, "user_id": user_id, "limit": int(top_k)}
        if rerank:
            payload["rerank"] = True

        for attempt in range(self.max_retries):
            try:
                session = await self._get_session()
                async with session.post(f"{self.host}/search", json=payload) as response:
                    if response.status >= 500:
                        raise RuntimeError(f"Mem0 search HTTP {response.status}: {await response.text()}")
                    response.raise_for_status()
                    data = await response.json()
                raw_results = data.get("results", data) if isinstance(data, dict) else data
                if not isinstance(raw_results, list):
                    return []
                results: List[Dict[str, Any]] = []
                for item in raw_results:
                    if not isinstance(item, dict):
                        continue
                    results.append(
                        {
                            "memory": str(item.get("memory", item.get("data", "")) or ""),
                            "score": item.get("score", 0),
                            "id": item.get("id", ""),
                            **{
                                key: item[key]
                                for key in ("created_at", "updated_at", "score_breakdown", "score_debug")
                                if key in item
                            },
                        }
                    )
                results.sort(key=lambda item: item.get("score", 0), reverse=True)
                return results
            except Exception as exc:
                if attempt >= self.max_retries - 1:
                    LOGGER.error("Mem0 search failed after %d attempts: %s", self.max_retries, exc)
                    return []
                await asyncio.sleep(self.retry_delay * (attempt + 1))
        return []

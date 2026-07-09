"""
MemOS open-source local server adapter.

This targets the self-hosted MemOS product API, not the hosted OpenMem API used
by the legacy `memos` adapter. The local endpoints are:
- POST /product/add
- POST /product/search
"""

from __future__ import annotations

import asyncio
import time
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from common.official_eval.imports import (
    AddResult,
    BaseAdapter,
    Dataset,
    GroupChatMessage,
    SearchResult,
    get_console,
    print_success,
    print_warning,
)


class MemosLocalAdapter(BaseAdapter):
    """Adapter for a self-hosted MemOS server."""

    def __init__(self, config: Dict[str, Any], output_dir: Optional[Path] = None):
        super().__init__(config, output_dir)

        self.api_url = str(config.get("api_url", "")).rstrip("/")
        if not self.api_url:
            raise ValueError("MemOS local API URL is required. Set MEMOS_LOCAL_BASE_URL or api_url.")

        self.api_key = str(config.get("api_key", "") or "")
        self.batch_size = int(config.get("batch_size", 30))
        self.max_retries = int(config.get("max_retries", 5))
        self.http_timeout = int(config.get("http_timeout", 300))
        self.add_config = config.get("add", {})
        self.search_config = config.get("search", {})

        requests_per_second = float(config.get("requests_per_second", 5))
        self.request_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self.console = get_console()

        self.console.print("✅ MemosLocalAdapter initialized", style="bold green")
        self.console.print(f"   API URL: {self.api_url}")
        self.console.print(f"   Batch Size: {self.batch_size}")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Token {self.api_key}"
            timeout = aiohttp.ClientTimeout(total=self.http_timeout)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _wait_for_rate_limit(self):
        if self.request_interval <= 0:
            return
        async with self._request_lock:
            now = time.monotonic()
            wait_time = self.request_interval - (now - self._last_request_at)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request_at = time.monotonic()

    async def add(
        self,
        dataset: Dataset,
        user_id: str,
        days_to_process: Optional[List[str]] = None,
        **kwargs,
    ) -> AddResult:
        self.console.print(f"\n{'=' * 60}", style="bold cyan")
        self.console.print("Stage: Add (MemOS Local)", style="bold cyan")
        self.console.print(f"{'=' * 60}", style="bold cyan")
        self.console.print(f"User ID: {user_id}")
        self.console.print(f"Dataset: {dataset.name}")

        days = [d for d in dataset.days if d.date in days_to_process] if days_to_process else dataset.days
        self.console.print(f"Days to process: {len(days)}")

        total_messages = 0
        total_errors: List[str] = []
        cube_id = self._cube_id(user_id, kwargs)

        for day in days:
            self.console.print(f"\n📅 Processing {day.date}...", style="dim")
            for group_name, messages in day.groups.items():
                session_id = f"{user_id}_{self._group_suffix(group_name)}"
                self.console.print(
                    f"   👥 Group: {group_name} -> cube_id={cube_id}, session_id={session_id}",
                    style="dim",
                )

                formatted = [self._format_message(m) for m in messages]
                batches = [formatted[i : i + self.batch_size] for i in range(0, len(formatted), self.batch_size)]
                self.console.print(f"      Messages: {len(formatted)}")
                self.console.print(f"      Batches: {len(batches)}")

                for batch_idx, batch in enumerate(batches):
                    try:
                        await self._send_batch(batch, user_id=user_id, cube_id=cube_id, session_id=session_id)
                        total_messages += len(batch)
                        self.console.print(
                            f"      ✅ Batch {batch_idx + 1}/{len(batches)} sent ({len(batch)} messages)",
                            style="dim green",
                        )
                    except Exception as exc:
                        error_msg = f"[{day.date}][{group_name}] Batch {batch_idx + 1} failed: {exc}"
                        total_errors.append(error_msg)
                        self.console.print(f"      ❌ {error_msg}", style="red")

        success = not total_errors
        self.console.print(f"\n{'=' * 60}", style="bold cyan")
        if success:
            print_success(f"Add completed: {total_messages} messages sent")
        else:
            print_warning(f"Add completed with errors: {total_messages} messages, {len(total_errors)} errors")

        return AddResult(
            success=success,
            days_processed=len(days),
            messages_sent=total_messages,
            errors=total_errors,
            metadata={"user_id": user_id, "cube_id": cube_id, "dataset": dataset.name},
        )

    def _format_message(self, msg: GroupChatMessage) -> Dict[str, Any]:
        ts = msg.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return {
            "role": "user",
            "content": f"[{ts.isoformat(timespec='seconds')}][Group: {msg.group}][Speaker: {msg.speaker}]{msg.content}",
            "chat_time": ts.isoformat(),
        }

    async def _send_batch(self, messages: List[Dict[str, Any]], user_id: str, cube_id: str, session_id: str):
        if not messages:
            return

        payload: Dict[str, Any] = {
            "user_id": user_id,
            "mem_cube_id": cube_id,
            "writable_cube_ids": [cube_id],
            "session_id": session_id,
            "messages": messages,
            "async_mode": str(self.add_config.get("async_mode", "sync") or "sync"),
            "info": {
                "benchmark": "LoCoMo QA",
                "locomo_qa_user_id": user_id,
                "locomo_qa_session_id": session_id,
            },
        }
        mode = str(self.add_config.get("mode", "") or "").strip()
        if mode:
            payload["mode"] = mode

        result = await self._post_json("/product/add", payload)
        code = result.get("code")
        if code not in (None, 200):
            raise RuntimeError(f"MemOS add failed: {result}")

    async def search(
        self,
        query: str,
        user_id: str,
        top_k: int = 10,
        **kwargs,
    ) -> SearchResult:
        start_time = time.time()
        effective_top_k = top_k if top_k is not None else self.search_config.get("top_k", 10)
        cube_id = self._cube_id(user_id, kwargs)

        payload: Dict[str, Any] = {
            "query": query,
            "user_id": user_id,
            "mem_cube_id": cube_id,
            "readable_cube_ids": [cube_id],
            "top_k": effective_top_k,
            "relativity": float(kwargs.get("relativity", self.search_config.get("relativity", 0))),
            "dedup": kwargs.get("dedup", self.search_config.get("dedup", "mmr")),
            "include_preference": bool(kwargs.get("include_preference", self.search_config.get("include_preference", False))),
        }
        mode = str(kwargs.get("mode", self.search_config.get("mode", "")) or "").strip()
        if mode:
            payload["mode"] = mode

        result = await self._post_json("/product/search", payload)
        if result.get("code") not in (None, 200):
            raise RuntimeError(f"MemOS search failed: {result}")

        memories, details = self._parse_search_results(result.get("data", {}))
        context = self._format_search_context(memories)
        duration_ms = (time.time() - start_time) * 1000
        return SearchResult(
            question_id=kwargs.get("question_id", ""),
            query=query,
            retrieved_memories=memories,
            context=context,
            search_duration_ms=duration_ms,
            metadata={
                "user_id": user_id,
                "cube_id": cube_id,
                "details": details,
                "memories_count": len(memories),
            },
        )

    async def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = await self._get_session()
        url = f"{self.api_url}{path}"
        for attempt in range(self.max_retries):
            try:
                await self._wait_for_rate_limit()
                async with session.post(url, json=payload) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}: {text}")
                    if not text:
                        return {}
                    return await response.json()
            except Exception as exc:
                if attempt >= self.max_retries - 1:
                    raise
                wait_time = 2**attempt
                self.console.print(
                    f"      ⚠️  MemOS request retry {attempt + 1}/{self.max_retries} in {wait_time}s: {exc}",
                    style="yellow",
                )
                await asyncio.sleep(wait_time)
        raise RuntimeError("unreachable MemOS retry state")

    def _parse_search_results(self, data: Any) -> tuple[List[str], List[Dict[str, Any]]]:
        memories: List[str] = []
        details: List[Dict[str, Any]] = []
        if not isinstance(data, dict):
            return memories, details

        for bucket_key in ("text_mem", "pref_mem", "act_mem", "para_mem", "param_mem"):
            buckets = data.get(bucket_key, [])
            if isinstance(buckets, dict):
                buckets = [buckets]
            for bucket in buckets or []:
                if not isinstance(bucket, dict):
                    continue
                for item in bucket.get("memories", []) or []:
                    memory_text = self._memory_text(item)
                    if not memory_text:
                        continue
                    memories.append(memory_text)
                    details.append({"bucket": bucket_key, "cube_id": bucket.get("cube_id", ""), "raw": item})

        return memories, details

    def _memory_text(self, item: Any) -> str:
        if isinstance(item, str):
            return item.strip()
        if not isinstance(item, dict):
            return ""
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        for key in ("memory", "memory_value", "content", "text"):
            value = item.get(key)
            if value:
                return str(value).strip()
            value = metadata.get(key)
            if value:
                return str(value).strip()
        return ""

    def _format_search_context(self, memories: List[str]) -> str:
        if not memories:
            return "(No memories retrieved)"
        return "\n".join(f"- {memory}" for memory in memories)

    def _cube_id(self, user_id: str, kwargs: Dict[str, Any]) -> str:
        return str(kwargs.get("memos_cube_id") or kwargs.get("mem_cube_id") or f"{user_id}_cube")

    def _group_suffix(self, group_name: str) -> str:
        digits = "".join(ch for ch in str(group_name) if ch.isdigit())
        return digits or str(group_name).strip().replace(" ", "_")

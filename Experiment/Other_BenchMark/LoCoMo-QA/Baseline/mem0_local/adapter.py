"""
Mem0 self-host adapter for controlled local evaluation.

This adapter talks to the open-source Mem0 FastAPI server directly. It is kept
separate from the hosted Mem0 adapter because the self-host REST API exposes
different routes from the platform SDK.
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


class Mem0LocalAdapter(BaseAdapter):
    """
    Mem0 self-host adapter.

    Expected OSS server API:
    - POST /memories
    - POST /search
    """

    def __init__(self, config: Dict[str, Any], output_dir: Optional[Path] = None):
        super().__init__(config, output_dir)

        self.api_url = str(config.get("api_url", "")).rstrip("/")
        if not self.api_url:
            raise ValueError("Mem0 local API URL is required. Set MEM0_LOCAL_BASE_URL or api_url.")

        self.api_key = str(config.get("api_key", ""))
        self.batch_size = int(config.get("batch_size", 30))
        self.max_retries = int(config.get("max_retries", 5))
        self.add_interval = float(config.get("add_interval", 0.5))
        self.search_config = config.get("search", {})
        self.http_timeout = int(config.get("http_timeout", 120))

        requests_per_second = float(config.get("requests_per_second", 5))
        self.request_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self.console = get_console()

        self.console.print("✅ Mem0LocalAdapter initialized", style="bold green")
        self.console.print(f"   API URL: {self.api_url}")
        self.console.print(f"   Batch Size: {self.batch_size}")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-API-Key"] = self.api_key
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
        self.console.print("Stage: Add (Mem0 Local)", style="bold cyan")
        self.console.print(f"{'=' * 60}", style="bold cyan")
        self.console.print(f"User ID: {user_id}")
        self.console.print(f"Dataset: {dataset.name}")

        days = [d for d in dataset.days if d.date in days_to_process] if days_to_process else dataset.days
        self.console.print(f"Days to process: {len(days)}")

        total_messages = 0
        total_errors: List[str] = []

        for day in days:
            self.console.print(f"\n📅 Processing {day.date}...", style="dim")
            for group_name, messages in day.groups.items():
                run_id = f"{user_id}_{self._group_suffix(group_name)}"
                self.console.print(f"   👥 Group: {group_name} -> run_id={run_id}", style="dim")

                formatted = [self._format_message(m) for m in messages]
                batches = self._split_into_batches(formatted)
                self.console.print(f"      Messages: {len(formatted)}")
                self.console.print(f"      Batches: {len(batches)}")

                for batch_idx, batch in enumerate(batches):
                    try:
                        await self._send_batch(batch, user_id=user_id, run_id=run_id)
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
            metadata={"user_id": user_id, "dataset": dataset.name},
        )

    def _format_message(self, msg: GroupChatMessage) -> Dict[str, Any]:
        ts = msg.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        content = f"[{ts.isoformat(timespec='seconds')}][Group: {msg.group}][Speaker: {msg.speaker}]{msg.content}"
        return {"role": "user", "content": content}

    def _split_into_batches(self, messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        return [messages[i : i + self.batch_size] for i in range(0, len(messages), self.batch_size)]

    async def _send_batch(self, messages: List[Dict[str, Any]], user_id: str, run_id: str):
        if not messages:
            return

        session = await self._get_session()
        payload = {
            "messages": messages,
            "user_id": user_id,
            "run_id": run_id,
            "metadata": {"locomo_qa_user_id": user_id, "locomo_qa_run_id": run_id},
        }

        for attempt in range(self.max_retries):
            try:
                await self._wait_for_rate_limit()
                async with session.post(f"{self.api_url}/memories", json=payload) as response:
                    if response.status not in {200, 201}:
                        text = await response.text()
                        raise RuntimeError(f"HTTP {response.status}: {text}")
                    await response.json()
                if self.add_interval > 0:
                    await asyncio.sleep(self.add_interval)
                return
            except Exception as exc:
                if attempt >= self.max_retries - 1:
                    raise
                wait_time = 2**attempt
                self.console.print(
                    f"      ⚠️  Retry {attempt + 1}/{self.max_retries} in {wait_time}s: {exc}",
                    style="yellow",
                )
                await asyncio.sleep(wait_time)

    async def search(
        self,
        query: str,
        user_id: str,
        top_k: int = 10,
        **kwargs,
    ) -> SearchResult:
        start_time = time.time()
        session = await self._get_session()
        effective_top_k = top_k if top_k is not None else self.search_config.get("top_k", 10)

        payload = {
            "query": query,
            "top_k": effective_top_k,
            "filters": {"user_id": user_id},
        }

        for attempt in range(self.max_retries):
            try:
                await self._wait_for_rate_limit()
                async with session.post(f"{self.api_url}/search", json=payload) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise RuntimeError(f"HTTP {response.status}: {text}")
                    result = await response.json()

                memories, details = self._parse_search_results(result)
                context = self._format_search_context(memories)
                duration_ms = (time.time() - start_time) * 1000
                return SearchResult(
                    question_id=kwargs.get("question_id", ""),
                    query=query,
                    retrieved_memories=memories,
                    context=context,
                    search_duration_ms=duration_ms,
                    metadata={
                        "memories_count": len(memories),
                        "details": details,
                        "user_id": user_id,
                    },
                )
            except Exception as exc:
                if attempt >= self.max_retries - 1:
                    raise
                wait_time = 2**attempt
                self.console.print(
                    f"      ⚠️  Search retry {attempt + 1}/{self.max_retries} in {wait_time}s: {exc}",
                    style="yellow",
                )
                await asyncio.sleep(wait_time)

        raise RuntimeError("unreachable search retry state")

    def _parse_search_results(self, result: Dict[str, Any]) -> tuple[List[str], List[Dict[str, Any]]]:
        raw_items = result.get("results", result if isinstance(result, list) else [])
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("results", [])
        memories: List[str] = []
        details: List[Dict[str, Any]] = []
        for item in raw_items or []:
            if not isinstance(item, dict):
                continue
            memory_text = str(item.get("memory") or item.get("text") or item.get("data") or "").strip()
            if not memory_text:
                continue
            memories.append(memory_text)
            details.append(item)
        return memories, details

    def _format_search_context(self, memories: List[str]) -> str:
        if not memories:
            return "(No memories retrieved)"
        return "\n".join(f"- {memory}" for memory in memories)

    def _group_suffix(self, group_name: str) -> str:
        digits = "".join(ch for ch in str(group_name) if ch.isdigit())
        return digits or str(group_name).strip().replace(" ", "_")

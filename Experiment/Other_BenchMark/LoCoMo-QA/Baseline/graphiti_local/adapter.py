"""
Graphiti local adapter for controlled Zep/Graphiti-style evaluation.

This uses the open-source Graphiti library directly instead of Zep Cloud. Keep
it separate from the cloud Zep adapter so the reported baseline provenance stays
clear.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


class GraphitiLocalAdapter(BaseAdapter):
    """
    Graphiti open-source adapter backed by Neo4j graph storage.
    """

    def __init__(self, config: Dict[str, Any], output_dir: Optional[Path] = None):
        super().__init__(config, output_dir)

        self.batch_size = int(config.get("batch_size", 5))
        self.max_retries = int(config.get("max_retries", 3))
        self.add_interval = float(config.get("add_interval", 0.0))
        self.update_communities = bool(config.get("update_communities", False))
        self.search_config = config.get("search", {})
        self.console = get_console()

        self._graphiti = self._build_graphiti(config)

        self.console.print("✅ GraphitiLocalAdapter initialized", style="bold green")
        self.console.print(f"   Batch Size: {self.batch_size}")

    def _build_graphiti(self, config: Dict[str, Any]) -> object:
        try:
            from graphiti_core import Graphiti
            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
            from graphiti_core.driver.neo4j_driver import Neo4jDriver
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        except ImportError as exc:
            raise ImportError(
                "Graphiti dependencies are not installed. Install with: pip install graphiti-core"
            ) from exc

        llm_cfg = config.get("llm", {})
        embedding_cfg = config.get("embedding", {})
        neo4j_cfg = config.get("neo4j", {})

        api_key = self._first_config_or_env(llm_cfg, "api_key", "OPENAI_API_KEY")
        base_url = self._first_config_or_env(llm_cfg, "base_url", "OPENAI_API_BASE", "OPENAI_BASE_URL")
        model = self._first_config_or_env(llm_cfg, "model", "OPENAI_MODEL")
        if not api_key or not base_url or not model:
            raise ValueError(
                "Graphiti local requires llm.api_key, llm.base_url, and llm.model. "
                "Set GRAPHITI_LLM_* or OPENAI_* environment variables."
            )

        embedding_api_key = self._first_config_or_env(
            embedding_cfg,
            "api_key",
            "OPENAI_EMBEDDING_API_KEY",
            "OPENAI_API_KEY",
        )
        embedding_base_url = self._first_config_or_env(
            embedding_cfg,
            "base_url",
            "OPENAI_EMBEDDING_API_BASE",
            "OPENAI_EMBEDDING_BASE_URL",
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
        )
        embedding_model = self._first_config_or_env(
            embedding_cfg,
            "model",
            "OPENAI_EMBEDDING_MODEL",
            default="text-embedding-3-small",
        )
        embedding_dim = int(
            self._first_config_or_env(
                embedding_cfg,
                "dim",
                "OPENAI_EMBEDDING_DIM",
                "EMBEDDING_DIM",
                default="1536",
            )
        )
        if not embedding_api_key or not embedding_base_url or not embedding_model:
            raise ValueError(
                "Graphiti local requires embedding.api_key, embedding.base_url, and embedding.model. "
                "Set GRAPHITI_EMBEDDING_* or OPENAI_EMBEDDING_* environment variables."
            )

        llm_config = LLMConfig(
            api_key=api_key,
            model=model,
            small_model=model,
            base_url=base_url,
            temperature=0,
            max_tokens=int(llm_cfg.get("max_tokens", 8192)),
        )
        llm_client_kwargs = {
            "config": llm_config,
            "max_tokens": int(llm_cfg.get("max_tokens", 8192)),
        }
        if "structured_output_mode" in inspect.signature(OpenAIGenericClient.__init__).parameters:
            llm_client_kwargs["structured_output_mode"] = str(
                llm_cfg.get("structured_output_mode", "json_schema")
            )
        llm_client = OpenAIGenericClient(**llm_client_kwargs)
        embedder = OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                api_key=embedding_api_key,
                base_url=embedding_base_url,
                embedding_model=embedding_model,
                embedding_dim=embedding_dim,
            )
        )
        cross_encoder = OpenAIRerankerClient(config=llm_config)
        driver = Neo4jDriver(
            uri=str(neo4j_cfg.get("uri", "bolt://localhost:7687")),
            user=str(neo4j_cfg.get("user", "neo4j")),
            password=str(neo4j_cfg.get("password", "password")),
        )
        return Graphiti(
            graph_driver=driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )

    def _first_config_or_env(
        self,
        config: Dict[str, Any],
        key: str,
        *env_names: str,
        default: str = "",
    ) -> str:
        value = str(config.get(key, "") or "").strip()
        if value:
            return value
        for env_name in env_names:
            value = str(os.environ.get(env_name, "") or "").strip()
            if value:
                return value
        return default

    async def add(
        self,
        dataset: Dataset,
        user_id: str,
        days_to_process: Optional[List[str]] = None,
        **kwargs,
    ) -> AddResult:
        self.console.print(f"\n{'=' * 60}", style="bold cyan")
        self.console.print("Stage: Add (Graphiti Local)", style="bold cyan")
        self.console.print(f"{'=' * 60}", style="bold cyan")
        self.console.print(f"Graph group ID: {user_id}")
        self.console.print(f"Dataset: {dataset.name}")

        try:
            await self._graphiti.build_indices_and_constraints()
        except Exception as exc:
            self.console.print(f"   ⚠️  Graphiti index setup warning: {exc}", style="yellow")

        days = [d for d in dataset.days if d.date in days_to_process] if days_to_process else dataset.days
        self.console.print(f"Days to process: {len(days)}")

        total_messages = 0
        total_errors: List[str] = []

        for day in days:
            self.console.print(f"\n📅 Processing {day.date}...", style="dim")
            for group_name, messages in day.groups.items():
                self.console.print(f"   👥 Group: {group_name}", style="dim")
                formatted = [
                    self._format_message(m, user_id=user_id, message_index=message_index)
                    for message_index, m in enumerate(messages)
                ]
                batches = [formatted[i : i + self.batch_size] for i in range(0, len(formatted), self.batch_size)]
                self.console.print(f"      Messages: {len(formatted)}")
                self.console.print(f"      Batches: {len(batches)}")
                for batch_idx, batch in enumerate(batches):
                    try:
                        await self._send_batch(batch)
                        total_messages += len(batch)
                        self.console.print(
                            f"      ✅ Batch {batch_idx + 1}/{len(batches)} ingested ({len(batch)} messages)",
                            style="dim green",
                        )
                    except Exception as exc:
                        error_msg = f"[{day.date}][{group_name}] Batch {batch_idx + 1} failed: {exc}"
                        total_errors.append(error_msg)
                        self.console.print(f"      ❌ {error_msg}", style="red")

        success = not total_errors
        self.console.print(f"\n{'=' * 60}", style="bold cyan")
        if success:
            print_success(f"Add completed: {total_messages} messages ingested")
        else:
            print_warning(f"Add completed with errors: {total_messages} messages, {len(total_errors)} errors")

        return AddResult(
            success=success,
            days_processed=len(days),
            messages_sent=total_messages,
            errors=total_errors,
            metadata={"graphiti_group_id": user_id, "dataset": dataset.name},
        )

    def _format_message(self, msg: GroupChatMessage, user_id: str, message_index: int) -> Dict[str, Any]:
        ts = msg.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        body = f"{msg.speaker}: {msg.content}"
        return {
            "name": f"{user_id}:{msg.date}:{msg.group}:{int(ts.timestamp())}:{message_index}",
            "episode_body": body,
            "source_description": (
                f"LoCoMo QA conversation message from {msg.group} at "
                f"{ts.isoformat(timespec='seconds')}"
            ),
            "reference_time": ts,
            "group_id": user_id,
        }

    async def _send_batch(self, messages: List[Dict[str, Any]]):
        if not messages:
            return
        from graphiti_core.nodes import EpisodeType

        for message in messages:
            for attempt in range(self.max_retries):
                try:
                    await self._graphiti.add_episode(
                        name=message["name"],
                        episode_body=message["episode_body"],
                        source_description=message["source_description"],
                        reference_time=message["reference_time"],
                        source=EpisodeType.message,
                        group_id=message["group_id"],
                        update_communities=self.update_communities,
                    )
                    if self.add_interval > 0:
                        await asyncio.sleep(self.add_interval)
                    break
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
        effective_top_k = top_k if top_k is not None else self.search_config.get("top_k", 10)

        for attempt in range(self.max_retries):
            try:
                results = await self._graphiti.search(
                    query=query,
                    group_ids=[kwargs.get("graphiti_group_id") or user_id],
                    num_results=effective_top_k,
                )
                facts = self._parse_facts(results)
                context = self._format_search_context(facts)
                duration_ms = (time.time() - start_time) * 1000
                return SearchResult(
                    question_id=kwargs.get("question_id", ""),
                    query=query,
                    retrieved_memories=[fact["text"] for fact in facts],
                    context=context,
                    search_duration_ms=duration_ms,
                    metadata={
                        "graphiti_group_id": kwargs.get("graphiti_group_id") or user_id,
                        "facts_count": len(facts),
                        "facts": facts,
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

    def _parse_facts(self, results: List[object]) -> List[Dict[str, str]]:
        facts: List[Dict[str, str]] = []
        for result in results or []:
            fact = str(getattr(result, "fact", "") or "").strip()
            if not fact:
                continue
            valid_at = getattr(result, "valid_at", None)
            invalid_at = getattr(result, "invalid_at", None)
            fact_text = fact
            if valid_at:
                fact_text = f"{fact_text} (event_time: {valid_at})"
            if invalid_at:
                fact_text = f"{fact_text} (invalid_at: {invalid_at})"
            facts.append(
                {
                    "uuid": str(getattr(result, "uuid", "")),
                    "text": fact_text,
                    "fact": fact,
                    "valid_at": str(valid_at) if valid_at else "",
                    "invalid_at": str(invalid_at) if invalid_at else "",
                }
            )
        return facts

    def _format_search_context(self, facts: List[Dict[str, str]]) -> str:
        facts_text = "\n".join(f"  - {fact['text']}" for fact in facts) if facts else "  (no facts found)"
        return f"""FACTS represent relevant Graphiti context for the current question.

<FACTS>
{facts_text}
</FACTS>"""

    async def close(self):
        close = getattr(self._graphiti, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

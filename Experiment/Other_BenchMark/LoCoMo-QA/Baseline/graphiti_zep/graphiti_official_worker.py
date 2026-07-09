from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
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
from common.loader import DialogTurn, LoCoMoSample, load_sample, ordered_unique  # noqa: E402
from runner import (  # noqa: E402
    make_sharded_client,
    normalize_output_dialog_ids,
    parse_session_date,
    safe_collection_name,
)


class ZepGraphitiOfficialWorker:
    def __init__(self, sample: LoCoMoSample, config: argparse.Namespace, runtime: LLMRuntimeConfig) -> None:
        self.sample = sample
        self.config = config
        self.runtime = runtime
        self.store_dir = Path(config.baseline_store_dir) / "zep_graphiti" / sample.sample_id
        self.state_path = self.store_dir / "ingest_state.json"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.group_id = config.zep_group_id or safe_collection_name(config.zep_neo4j_database or "neo4j")
        self.official_repo = self._prepare_official_repo()
        self.graphiti, self.graphiti_clients = self._build_graphiti()

    def _prepare_official_repo(self) -> Path:
        repo = Path(self.config.zep_official_repo).expanduser().resolve()
        if not (repo / "graphiti_core/graphiti.py").exists():
            raise RuntimeError(f"--zep-official-repo does not look like getzep/graphiti: missing {repo / 'graphiti_core/graphiti.py'}")
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        return repo

    def _build_graphiti(self) -> tuple[object, Mapping[str, object]]:
        os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")
        os.environ["NEO4J_DATABASE"] = self.config.zep_neo4j_database or "neo4j"
        from Experiment.Main_Baseline.graphiti_zep.run_graphiti_baseline import (  # noqa: WPS433
            build_graphiti_clients,
            build_graphiti_driver,
        )
        from graphiti_core import Graphiti  # noqa: WPS433

        graphiti_clients = build_graphiti_clients(
            self.config.zep_graphiti_provider,
            self.config.zep_cross_encoder,
            self.config.zep_embedder,
            self.config.zep_bge_embedding_model,
        )
        graphiti = Graphiti(
            graph_driver=build_graphiti_driver(
                self.config.zep_neo4j_uri,
                self.config.zep_neo4j_user,
                self.config.zep_neo4j_password,
            ),
            llm_client=graphiti_clients["llm_client"],
            embedder=graphiti_clients["embedder"],
            cross_encoder=graphiti_clients["cross_encoder"],
        )
        return graphiti, graphiti_clients

    async def prepare(self) -> None:
        await self.graphiti.build_indices_and_constraints()
        if self.config.zep_skip_ingest:
            if not self.state_path.exists():
                raise RuntimeError("--zep-skip-ingest requires a reusable Graphiti ingest_state.json")
            return
        if self.config.reuse_baseline_store and self._is_ingested():
            print(f"[zep-graphiti-official-worker] load_ingest_state {self.state_path}", flush=True)
            return
        await self._ingest()

    def _is_ingested(self) -> bool:
        try:
            payload = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        return bool(payload.get("ingested")) and payload.get("sample_id") == self.sample.sample_id

    async def _ingest(self) -> None:
        from graphiti_core.nodes import EpisodeType  # noqa: WPS433

        turns = self.sample.turns[: self.config.zep_ingest_limit or None]
        if not turns:
            raise RuntimeError(f"sample_id={self.sample.sample_id} has no dialog turns to ingest into Graphiti")
        print(
            f"[zep-graphiti-official-worker] ingest sample_id={self.sample.sample_id} "
            f"turns={len(turns)} group_id={self.group_id} official_repo={self.official_repo}",
            flush=True,
        )
        ingested_dialog_ids: List[str] = []
        previous_episode_uuid = None
        for index, turn in enumerate(turns, start=1):
            result = await self.graphiti.add_episode(
                name=f"locomo-{self.sample.sample_id}-{turn.dia_id}",
                episode_body=json.dumps(graphiti_episode_payload(self.sample.sample_id, turn), ensure_ascii=False),
                source_description=f"LoCoMo QA dialog sample={self.sample.sample_id} dialog_id={turn.dia_id}",
                reference_time=parse_graphiti_reference_time(turn.session_date_time),
                source=EpisodeType.json,
                group_id=self.group_id,
                previous_episode_uuids=[previous_episode_uuid] if previous_episode_uuid else None,
            )
            previous_episode_uuid = getattr(getattr(result, "episode", None), "uuid", None) or previous_episode_uuid
            ingested_dialog_ids.append(turn.dia_id)
            print(f"[zep-graphiti-official-worker] ingested {index}/{len(turns)} {turn.dia_id}", flush=True)
        state = {
            "schema_version": "locomo-zep-graphiti-official-ingest-v1",
            "sample_id": self.sample.sample_id,
            "official_repo": str(self.official_repo),
            "official_runtime": "getzep/graphiti graphiti_core",
            "ingested": True,
            "group_id": self.group_id,
            "neo4j_uri": self.config.zep_neo4j_uri,
            "neo4j_database": self.config.zep_neo4j_database,
            "n_turns": len(turns),
            "ingested_dialog_ids": ingested_dialog_ids,
        }
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    async def retrieve(self, question_id: str, question: str) -> Dict[str, object]:
        from graphiti_core.search.search_helpers import search_results_to_context_string  # noqa: WPS433

        search_results = await self.graphiti.search_(
            question,
            config=graphiti_search_config(self.config.zep_search_config, self.config.top_k),
            group_ids=[self.group_id] if self.group_id else None,
        )
        context = search_results_to_context_string(search_results)
        candidate_dialog_ids = ordered_unique(re.findall(r"\bD\d+:\d+\b", context))
        output_client = make_sharded_client(
            self.runtime,
            "zep_graphiti_official_answer",
            f"{question_id}_{short_hash(question + context)}",
        )
        output = output_client.complete_json(
            zep_graphiti_answer_system_prompt(),
            zep_graphiti_answer_user_prompt(question_id, question, context),
        )
        evidence_dialog_ids = normalize_output_dialog_ids(output.get("evidence_dialog_ids"))
        return {
            "candidate_dialog_ids": candidate_dialog_ids,
            "context": context,
            "direct_answer": str(output.get("answer") or "").strip(),
            "direct_evidence_dialog_ids": evidence_dialog_ids,
            "trace": {
                "retriever": "official_zep_graphiti",
                "official_runtime": "getzep/graphiti graphiti_core",
                "official_repo": str(self.official_repo),
                "runtime_isolation": "subprocess",
                "official_components": [
                    "graphiti_core.Graphiti",
                    "Graphiti.add_episode",
                    "Graphiti.search_",
                    "graphiti_core.search.search_helpers.search_results_to_context_string",
                ],
                "graphiti_provider": self.graphiti_clients.get("graphiti_provider"),
                "graphiti_model": self.graphiti_clients.get("graphiti_model"),
                "embedder": self.graphiti_clients.get("embedder_name"),
                "embedding_model": self.graphiti_clients.get("embedding_model"),
                "cross_encoder": self.graphiti_clients.get("cross_encoder_name"),
                "search_config": self.config.zep_search_config,
                "group_id": self.group_id,
                "neo4j_uri": self.config.zep_neo4j_uri,
                "neo4j_database": self.config.zep_neo4j_database,
                "candidate_dialog_ids_source": "dialog_ids_embedded_in_graphiti_search_context",
                "n_candidate_dialog_ids": len(candidate_dialog_ids),
            },
        }

    async def close(self) -> None:
        await self.graphiti.close()


def graphiti_episode_payload(sample_id: str, turn: DialogTurn) -> Dict[str, object]:
    return {
        "benchmark": "locomo_qa",
        "sample_id": sample_id,
        "dialog_id": turn.dia_id,
        "session_id": turn.session_id,
        "session_index": turn.session_index,
        "session_date_time": turn.session_date_time,
        "speaker": turn.speaker,
        "text": turn.text,
        "image_caption": turn.image_caption,
        "image_query": turn.image_query,
    }


def parse_graphiti_reference_time(value: str) -> datetime:
    parsed = parse_session_date(value)
    if parsed is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def graphiti_search_config(name: str, top_k: int) -> object:
    from graphiti_core.search import search_config_recipes as recipes  # noqa: WPS433

    if name == "combined_rrf":
        config = deepcopy(recipes.COMBINED_HYBRID_SEARCH_RRF)
    elif name == "edge_rrf":
        config = deepcopy(recipes.EDGE_HYBRID_SEARCH_RRF)
    else:
        config = deepcopy(recipes.COMBINED_HYBRID_SEARCH_CROSS_ENCODER)
    config.limit = top_k
    return config


def zep_graphiti_answer_system_prompt() -> str:
    return (
        "You answer LoCoMo QA questions using only the provided official Zep/Graphiti search context. "
        "Return strict JSON only with keys answer and evidence_dialog_ids. "
        "Do not use benchmark gold answers, gold evidence, categories, or question-type labels. "
        "Cite only dialog IDs that appear in the Graphiti context."
    )


def zep_graphiti_answer_user_prompt(question_id: str, question: str, context: str) -> str:
    return (
        "Official Zep/Graphiti context:\n"
        f"{context or '[none]'}\n\n"
        f"Question ID: {question_id}\n"
        f"Question: {question}\n\n"
        "Return JSON only:\n"
        "{\"answer\":\"short answer\", \"evidence_dialog_ids\":[\"D1:1\"]}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated official Zep/Graphiti LoCoMo worker.")
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
        zep_official_repo=str(request["zep_official_repo"]),
        zep_neo4j_uri=str(request.get("zep_neo4j_uri") or "bolt://localhost:7687"),
        zep_neo4j_user=str(request.get("zep_neo4j_user") or "neo4j"),
        zep_neo4j_password=str(request.get("zep_neo4j_password") or ""),
        zep_neo4j_database=str(request.get("zep_neo4j_database") or "neo4j"),
        zep_group_id=str(request.get("zep_group_id") or ""),
        zep_graphiti_provider=str(request.get("zep_graphiti_provider") or request.get("provider") or "openai"),
        zep_cross_encoder=str(request.get("zep_cross_encoder") or "auto"),
        zep_embedder=str(request.get("zep_embedder") or "auto"),
        zep_bge_embedding_model=str(request.get("zep_bge_embedding_model") or "BAAI/bge-small-en-v1.5"),
        zep_search_config=str(request.get("zep_search_config") or "combined_cross_encoder"),
        zep_skip_ingest=bool(request.get("zep_skip_ingest")),
        zep_ingest_limit=int(request.get("zep_ingest_limit") or 0),
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


async def async_main() -> int:
    args = parse_args()
    load_dotenv()
    request_path = Path(args.request)
    response_path = Path(args.response)
    request = json.loads(request_path.read_text())
    config = namespace_from_request(request)
    runtime = runtime_from_request(request)
    sample = load_sample(Path(config.data), config.sample_id)
    worker = ZepGraphitiOfficialWorker(sample, config, runtime)
    try:
        await worker.prepare()
        contexts: Dict[str, Dict[str, object]] = {}
        for item in request.get("questions", []):
            if not isinstance(item, Mapping):
                continue
            question_id = str(item.get("question_id") or "")
            question = str(item.get("question") or "")
            if not question_id or not question:
                continue
            contexts[question_id] = await worker.retrieve(question_id, question)
            print(f"[zep-graphiti-official-worker] answered {question_id}", flush=True)
    finally:
        await worker.close()
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(
        json.dumps(
            {
                "schema_version": "locomo-zep-graphiti-worker-response-v1",
                "contexts": contexts,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())

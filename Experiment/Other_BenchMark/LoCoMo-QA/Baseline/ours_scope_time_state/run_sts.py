from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


METHOD_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = METHOD_DIR.parents[1]
PROJECT_DIR = BENCHMARK_DIR.parents[2]
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state import graph_builder, graph_query_runner  # noqa: E402
from Experiment.run.common.io import load_dotenv  # noqa: E402


DEFAULT_DATA = BENCHMARK_DIR / "data" / "locomo10.json"
ARTIFACT_DIR = PROJECT_DIR / "Graph" / "locomo_qa" / "ours_scope_time_state"
STATE_MERGE_SCHEMA = "scope-time-state-graph-v2-state-merge"
EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
PROFILES: Mapping[str, Mapping[str, Any]] = {
    "qwen7b": {
        "artifact_slug": "qwen25_7b",
        "model": "qwen2.5:7b",
        "base_url": "http://127.0.0.1:11434/v1",
        "build_max_tokens": 1024,
        "claim_workers": 1,
        "resolver_workers": 1,
        "scope_top_k": 8,
        "max_context_events": 16,
        "max_state_lines": 12,
        "max_ledger_claims": 8,
        "max_ledger_states": 6,
        "max_ledger_events": 6,
        "embedding_batch_size": 32,
        "answer_workers": 1,
        "answer_max_tokens": 512,
    },
    "gpt4omini": {
        "artifact_slug": "gpt4omini",
        "model": "gpt-4o-mini",
        "base_url": "",
        "build_max_tokens": 4096,
        "claim_workers": 4,
        "resolver_workers": 4,
        "scope_top_k": 10,
        "max_context_events": 24,
        "max_state_lines": 8,
        "max_ledger_claims": 12,
        "max_ledger_states": 8,
        "max_ledger_events": 8,
        "embedding_batch_size": 64,
        "answer_workers": 4,
        "answer_max_tokens": 2048,
    },
}


def validate_active_schema() -> None:
    builder_schema = str(graph_builder.GRAPH_SCHEMA_V2)
    query_schema = str(graph_query_runner.ACTIVE_GRAPH_SCHEMA_V2)
    if builder_schema != STATE_MERGE_SCHEMA or query_schema != STATE_MERGE_SCHEMA:
        raise RuntimeError(
            "LoCoMo STS requires the shared state-merge schema; "
            f"builder={builder_schema!r}, query={query_schema!r}"
        )


def resolve_args(args: argparse.Namespace) -> argparse.Namespace:
    profile = PROFILES[args.llm_profile]
    slug = str(profile["artifact_slug"])
    args.profile = profile
    args.model = str(profile["model"])
    args.llm_api_key = ""
    if args.llm_profile == "qwen7b":
        local_model = usable_env_value("LOCAL_MODEL")
        if local_model:
            local_base_url = usable_env_value("LOCAL_API_BASE")
            local_api_key = usable_env_value("LOCAL_API_KEY")
            missing = [
                name
                for name, value in (
                    ("LOCAL_API_BASE", local_base_url),
                    ("LOCAL_API_KEY", local_api_key),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "LOCAL_MODEL selects the school-server Qwen endpoint, but these settings are missing: "
                    + ", ".join(missing)
                )
            args.model = local_model
            args.llm_base_url = args.llm_base_url or local_base_url
            args.llm_api_key = local_api_key
        else:
            args.llm_base_url = args.llm_base_url or str(profile["base_url"])
            args.llm_api_key = "ollama"
    else:
        args.llm_base_url = args.llm_base_url or str(profile["base_url"])
    args.graph_root = args.graph_root or ARTIFACT_DIR / "graph" / f"locomo_{slug}_sts_state_merge"
    args.result_dir = args.result_dir or ARTIFACT_DIR / "results" / slug
    cache_dir = ARTIFACT_DIR / "cache" / slug
    args.build_cache = args.build_cache or cache_dir / "graph_builder.json"
    args.query_cache = args.query_cache or cache_dir / "graph_query.json"
    args.embedding_cache = args.embedding_cache or cache_dir / f"{EMBEDDING_MODEL}.json"
    return args


def usable_env_value(name: str) -> str:
    value = str(os.environ.get(name, "")).strip()
    if not value or value.startswith("$") or "你的" in value:
        return ""
    return value


def configure_llm_environment(args: argparse.Namespace) -> None:
    os.environ["OPENAI_MODEL"] = args.model
    if args.llm_base_url:
        os.environ["OPENAI_API_BASE"] = args.llm_base_url
    if args.llm_profile == "qwen7b":
        os.environ["OPENAI_API_KEY"] = args.llm_api_key
    os.environ.setdefault("LLM_PARSE_RETRIES", "3")
    os.environ.setdefault("LLM_SEMANTIC_RETRIES", "3")
    os.environ.setdefault("LLM_REQUEST_TIMEOUT", "180")
    os.environ.setdefault("LLM_MAX_RETRIES", "3")
    os.environ.setdefault("LLM_RETRY_BASE_DELAY_SECONDS", "2")
    os.environ.setdefault("LLM_RETRY_MAX_DELAY_SECONDS", "120")


def graph_dir(args: argparse.Namespace) -> Path:
    return args.graph_root / args.sample_id


def result_path(args: argparse.Namespace) -> Path:
    slug = str(args.profile["artifact_slug"])
    return args.result_dir / f"results_{args.sample_id}_{slug}_sts_state_merge.json"


def build_graph_args(args: argparse.Namespace) -> list[str]:
    profile = args.profile
    return [
        "--data", str(args.data),
        "--sample-id", args.sample_id,
        "--graph-schema", "v2",
        "--output-dir", str(args.graph_root),
        "--claim-mode", "llm",
        "--resolver-mode", "llm",
        "--provider", "openai",
        "--model", args.model,
        "--cache", str(args.build_cache),
        "--max-tokens", str(profile["build_max_tokens"]),
        "--message-chunk-size", "4",
        "--claim-workers", str(profile["claim_workers"]),
        "--resolver-workers", str(profile["resolver_workers"]),
        "--resolver-candidate-limit", "24",
        "--max-claims-per-turn", "2",
        "--event-limit", str(args.event_limit),
    ]


def query_graph_args(args: argparse.Namespace) -> list[str]:
    profile = args.profile
    values = [
        "--data", str(args.data),
        "--sample-id", args.sample_id,
        "--graph-dir", str(graph_dir(args)),
        "--provider", "openai",
        "--model", args.model,
        "--variants", "graph_embedding_scope_event",
        "--limit-cases", str(args.limit_cases),
        "--limit-per-type", "0",
        "--top-k", "12",
        "--scope-top-k", str(profile["scope_top_k"]),
        "--scope-backoff-k", "0",
        "--scope-types", "speaker,entity,topic",
        "--candidate-k", "80",
        "--embedding-candidate-k", "80",
        "--max-context-events", str(profile["max_context_events"]),
        "--max-state-lines", str(profile["max_state_lines"]),
        "--max-ledger-claims", str(profile["max_ledger_claims"]),
        "--max-ledger-states", str(profile["max_ledger_states"]),
        "--max-ledger-events", str(profile["max_ledger_events"]),
        "--ledger-fallback-events", "2",
        "--evidence-selector", "llm-ledger",
        "--time-role-selector", "llm",
        "--event-time-routing", "rerank",
        "--graph-expansion", "relation-aware",
        "--evidence-citation-source", "answer",
        "--embedding-model", EMBEDDING_MODEL,
        "--embedding-batch-size", str(profile["embedding_batch_size"]),
        "--answer-workers", str(profile["answer_workers"]),
        "--output", str(result_path(args)),
        "--cache", str(args.query_cache),
        "--embedding-cache", str(args.embedding_cache),
    ]
    if args.embedding_base_url:
        values.extend(("--embedding-base-url", args.embedding_base_url))
    return values


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and query LoCoMo state-merge STS with Qwen 7B or GPT-4o-mini."
    )
    parser.add_argument("command", choices=("build", "query", "run"))
    parser.add_argument("--llm-profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--graph-root", type=Path)
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--build-cache", type=Path)
    parser.add_argument("--query-cache", type=Path)
    parser.add_argument("--embedding-cache", type=Path)
    parser.add_argument(
        "--embedding-base-url",
        default=os.environ.get("OPENAI_EMBEDDING_BASE_URL", DEFAULT_EMBEDDING_BASE_URL),
    )
    parser.add_argument("--event-limit", type=int, default=0, help="Build smoke-test limit; 0 builds the full sample.")
    parser.add_argument("--limit-cases", type=int, default=0, help="QA smoke-test limit; 0 runs every question.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_dotenv()
    args = resolve_args(make_parser().parse_args(argv))
    validate_active_schema()
    configure_llm_environment(args)
    if args.command in {"build", "run"}:
        build_status = graph_builder.main(build_graph_args(args))
        if build_status != 0:
            return build_status
    if args.command in {"query", "run"}:
        os.environ["LLM_MAX_TOKENS"] = str(args.profile["answer_max_tokens"])
        return graph_query_runner.main(query_graph_args(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

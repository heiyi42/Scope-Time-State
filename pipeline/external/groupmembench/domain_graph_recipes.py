from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import sys
from typing import Dict, List


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pipeline.external.groupmembench.loader import (  # noqa: E402
    CACHE_DIR,
    DOMAINS,
    GRAPH_OUTPUT_DIR,
    build_scope_inventory,
    load_domain_messages,
)


CLAIM_WORKERS = 12
STATEFACET_WORKERS = 4
SCOPE_WORKERS = 1
MESSAGE_CHUNK_MAX_CHARS = 9000
DEFAULT_STATEFACET_GROUP_MAX_PROMPT_CHARS = 12000
GRAPH_RECIPE_TAG = "flashclaim_prostate_domainadaptive_v3"
DEFAULT_PROVIDER = "deepseek"
DEFAULT_CLAIM_MODEL = "deepseek-v4-flash"
DEFAULT_STATEFACET_MODEL = "deepseek-v4-pro"
DOMAIN_MESSAGE_CHUNK_SIZE = {
    "Finance": 16,
    "Technology": 16,
    "Healthcare": 32,
    "Manufacturing": 32,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print reproducible GroupMemBench domain graph build commands.")
    parser.add_argument("--domain", choices=DOMAINS, required=True)
    parser.add_argument(
        "--output-root",
        default=str(GRAPH_OUTPUT_DIR / f"groupmembench_domain_graph_llm_alldomains_{GRAPH_RECIPE_TAG}"),
    )
    parser.add_argument("--cache", default="")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--claim-provider", default="")
    parser.add_argument("--claim-model", default=DEFAULT_CLAIM_MODEL)
    parser.add_argument("--statefacet-provider", default="")
    parser.add_argument("--statefacet-model", default=DEFAULT_STATEFACET_MODEL)
    parser.add_argument(
        "--message-chunk-size",
        type=int,
        default=0,
        help="Override the domain-adaptive claim-extraction chunk size. 0 uses the recipe default.",
    )
    parser.add_argument("--message-chunk-max-chars", type=int, default=MESSAGE_CHUNK_MAX_CHARS)
    parser.add_argument("--claim-workers", type=int, default=CLAIM_WORKERS)
    parser.add_argument("--statefacet-workers", type=int, default=STATEFACET_WORKERS)
    parser.add_argument("--scope-workers", type=int, default=SCOPE_WORKERS)
    parser.add_argument("--statefacet-group-max-prompt-chars", type=int, default=DEFAULT_STATEFACET_GROUP_MAX_PROMPT_CHARS)
    return parser.parse_args()


def quote_command(parts: List[str], env: Dict[str, str] | None = None) -> str:
    prefix = ""
    if env:
        prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items()) + " "
    return prefix + " ".join(shlex.quote(part) for part in parts)


def builder_command(
    domain: str,
    output_dir: str,
    cache: str,
    provider: str,
    claim_provider: str,
    claim_model: str,
    statefacet_provider: str,
    statefacet_model: str,
    scope_offset: int,
    scope_limit: int,
    scope_workers: int,
    claim_workers: int,
    statefacet_workers: int,
    message_chunk_size: int,
    message_chunk_max_chars: int,
    claim_coverage_retry_chunk_size: int,
    statefacet_group_max_prompt_chars: int,
) -> str:
    env = {
        "LLM_REQUEST_TIMEOUT": "300",
        "LLM_MAX_RETRIES": "1",
        "LLM_MAX_TOKENS": "8192",
        "LLM_PARSE_RETRIES": "5",
    }
    parts = [
        "python",
        "-m",
        "pipeline.external.groupmembench.domain_graph_builder",
        "--domains",
        domain,
        "--output-dir",
        output_dir,
        "--claim-mode",
        "llm",
        "--provider",
        provider,
        "--model",
        statefacet_model,
        "--cache",
        cache,
        "--claim-provider",
        claim_provider or provider,
        "--claim-model",
        claim_model,
        "--statefacet-provider",
        statefacet_provider or provider,
        "--statefacet-model",
        statefacet_model,
        "--message-chunk-size",
        str(message_chunk_size),
        "--message-chunk-max-chars",
        str(message_chunk_max_chars),
        "--max-claims-per-event",
        "2",
        "--claim-workers",
        str(claim_workers),
        "--statefacet-workers",
        str(statefacet_workers),
        "--scope-workers",
        str(scope_workers),
        "--claim-input-filter",
        "all",
        "--claim-coverage-backfill",
        "strong",
        "--claim-coverage-retry-chunk-size",
        str(claim_coverage_retry_chunk_size),
        "--consolidation-claim-limit",
        "80",
        "--statefacet-claim-limit-per-group",
        "12",
        "--statefacet-max-groups",
        "6",
        "--statefacet-consolidation-mode",
        "grouped",
        "--statefacet-group-max-prompt-chars",
        str(statefacet_group_max_prompt_chars),
        "--scope-offset",
        str(scope_offset),
        "--scope-limit",
        str(scope_limit),
    ]
    return quote_command(parts, env)


def cache_for_recipe(base_cache: str, safe_domain: str, artifact_tag: str) -> str:
    if base_cache:
        return str(Path(base_cache))
    return str(CACHE_DIR / f"llm_cache.groupmembench_domain_graph_builder_{safe_domain}_{artifact_tag}.json")


def message_chunk_size_for_domain(domain: str, override: int) -> int:
    if override > 0:
        return override
    return DOMAIN_MESSAGE_CHUNK_SIZE[domain]


def model_tag(model: str) -> str:
    return model.replace("deepseek-", "").replace("v4-", "").replace("_", "-")


def main() -> int:
    args = parse_args()
    messages = load_domain_messages(args.domain)
    scope_count = len(build_scope_inventory(messages))
    event_count = len(messages)
    safe_domain = args.domain.lower()
    message_chunk_size = message_chunk_size_for_domain(args.domain, args.message_chunk_size)
    claim_provider = args.claim_provider or args.provider
    statefacet_provider = args.statefacet_provider or args.provider
    artifact_tag = (
        f"{model_tag(args.claim_model)}claim_{model_tag(args.statefacet_model)}state_"
        f"chunk{message_chunk_size}_cw{args.claim_workers}_v3"
    )
    batches = [("scope001", 0, 1, args.scope_workers)]
    middle_scope_count = min(5, max(0, scope_count - 1))
    if middle_scope_count:
        batches.append(("scope002_006", 1, middle_scope_count, args.scope_workers))
    first_split_tail_scope_count = min(11, max(0, scope_count - 6))
    if first_split_tail_scope_count:
        batches.append(("scope007_017", 6, first_split_tail_scope_count, args.scope_workers))
    second_split_offset = 6 + first_split_tail_scope_count
    second_split_tail_scope_count = min(12, max(0, scope_count - second_split_offset))
    if second_split_tail_scope_count:
        batches.append(("scope018_029", second_split_offset, second_split_tail_scope_count, args.scope_workers))
    no_split_offset = second_split_offset + second_split_tail_scope_count
    if scope_count > no_split_offset:
        batches.append(("scope030_end", no_split_offset, 0, args.scope_workers))

    print(
        f"# {args.domain}: scopes={scope_count} events={event_count} "
        f"claim_model={args.claim_model} statefacet_model={args.statefacet_model} "
        f"chunk_size={message_chunk_size} chunk_max_chars={args.message_chunk_max_chars} "
        f"claim_workers={args.claim_workers} scope_workers={args.scope_workers}"
    )
    source_artifacts: List[str] = []
    for name, offset, limit, scope_workers in batches:
        output_dir = str(GRAPH_OUTPUT_DIR / f"groupmembench_domain_graph_llm_{safe_domain}_{artifact_tag}_{name}")
        cache = cache_for_recipe(args.cache, safe_domain, artifact_tag)
        source_artifacts.append(f"{output_dir}/{args.domain}")
        print()
        print(f"# build {name}")
        print(
            builder_command(
                args.domain,
                output_dir,
                cache,
                args.provider,
                claim_provider,
                args.claim_model,
                statefacet_provider,
                args.statefacet_model,
                offset,
                limit,
                scope_workers,
                args.claim_workers,
                args.statefacet_workers,
                message_chunk_size,
                args.message_chunk_max_chars,
                message_chunk_size,
                args.statefacet_group_max_prompt_chars,
            )
        )

    merge_parts = [
        "python",
        "-m",
        "pipeline.external.groupmembench.domain_graph_merge",
        "--domain",
        args.domain,
        "--source-artifacts",
        *source_artifacts,
        "--output-dir",
        args.output_root,
        "--expected-scope-count",
        str(scope_count),
        "--expected-event-count",
        str(event_count),
    ]
    print()
    print("# merge")
    print(quote_command(merge_parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

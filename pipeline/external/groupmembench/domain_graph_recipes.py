from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import sys
from typing import Dict, List


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pipeline.external.groupmembench.loader import DOMAINS, build_scope_inventory, load_domain_messages  # noqa: E402


CLAIM_WORKERS = 4
STATEFACET_WORKERS = 4
SCOPE_WORKERS = 4
DEFAULT_STATEFACET_GROUP_MAX_PROMPT_CHARS = 12000
GRAPH_RECIPE_TAG = "pro_hybrid_chunk8_16_facetopen_tailnosplit_v1"
BATCH_RECIPES = {
    "scope001": {
        "artifact_tag": "pro_chunk8_facetopen_v1",
        "message_chunk_size": 8,
        "claim_coverage_retry_chunk_size": 8,
        "statefacet_group_max_prompt_chars": 12000,
    },
    "scope002_006": {
        "artifact_tag": "pro_chunk8_facetopen_v1",
        "message_chunk_size": 8,
        "claim_coverage_retry_chunk_size": 8,
        "statefacet_group_max_prompt_chars": 12000,
    },
    "scope007_017": {
        "artifact_tag": "pro_chunk16_facetopen_split_v1",
        "message_chunk_size": 16,
        "claim_coverage_retry_chunk_size": 16,
        "statefacet_group_max_prompt_chars": 12000,
    },
    "scope018_029": {
        "artifact_tag": "pro_chunk16_facetopen_split_v1",
        "message_chunk_size": 16,
        "claim_coverage_retry_chunk_size": 16,
        "statefacet_group_max_prompt_chars": 12000,
    },
    "scope030_end": {
        "artifact_tag": "pro_chunk16_facetopen_nosplit_v1",
        "message_chunk_size": 16,
        "claim_coverage_retry_chunk_size": 16,
        "statefacet_group_max_prompt_chars": 0,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print reproducible GroupMemBench domain graph build commands.")
    parser.add_argument("--domain", choices=DOMAINS, required=True)
    parser.add_argument(
        "--output-root",
        default=f"stamb_state_benchmark/output/groupmembench_domain_graph_llm_alldomains_{GRAPH_RECIPE_TAG}",
    )
    parser.add_argument("--cache", default="")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--provider", default="deepseek")
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
    model: str,
    provider: str,
    scope_offset: int,
    scope_limit: int,
    scope_workers: int,
    message_chunk_size: int,
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
        model,
        "--cache",
        cache,
        "--message-chunk-size",
        str(message_chunk_size),
        "--message-chunk-max-chars",
        "9000",
        "--max-claims-per-event",
        "2",
        "--claim-workers",
        str(CLAIM_WORKERS),
        "--statefacet-workers",
        str(STATEFACET_WORKERS),
        "--scope-workers",
        str(scope_workers),
        "--claim-input-filter",
        "all",
        "--claim-coverage-retry-chunk-size",
        str(claim_coverage_retry_chunk_size),
        "--consolidation-claim-limit",
        "80",
        "--statefacet-claim-limit-per-group",
        "12",
        "--statefacet-max-groups",
        "6",
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
    return (
        "stamb_state_benchmark/output/"
        f"llm_cache.groupmembench_domain_graph_builder_{safe_domain}_{artifact_tag}.json"
    )


def main() -> int:
    args = parse_args()
    messages = load_domain_messages(args.domain)
    scope_count = len(build_scope_inventory(messages))
    event_count = len(messages)
    safe_domain = args.domain.lower()
    batches = [("scope001", 0, 1, SCOPE_WORKERS)]
    middle_scope_count = min(5, max(0, scope_count - 1))
    if middle_scope_count:
        batches.append(("scope002_006", 1, middle_scope_count, SCOPE_WORKERS))
    first_split_tail_scope_count = min(11, max(0, scope_count - 6))
    if first_split_tail_scope_count:
        batches.append(("scope007_017", 6, first_split_tail_scope_count, SCOPE_WORKERS))
    second_split_offset = 6 + first_split_tail_scope_count
    second_split_tail_scope_count = min(12, max(0, scope_count - second_split_offset))
    if second_split_tail_scope_count:
        batches.append(("scope018_029", second_split_offset, second_split_tail_scope_count, SCOPE_WORKERS))
    no_split_offset = second_split_offset + second_split_tail_scope_count
    if scope_count > no_split_offset:
        batches.append(("scope030_end", no_split_offset, 0, SCOPE_WORKERS))

    print(f"# {args.domain}: scopes={scope_count} events={event_count} model={args.model}")
    source_artifacts: List[str] = []
    for name, offset, limit, scope_workers in batches:
        batch_recipe = BATCH_RECIPES[name]
        artifact_tag = str(batch_recipe["artifact_tag"])
        output_dir = f"stamb_state_benchmark/output/groupmembench_domain_graph_llm_{safe_domain}_{artifact_tag}_{name}"
        cache = cache_for_recipe(args.cache, safe_domain, artifact_tag)
        source_artifacts.append(f"{output_dir}/{args.domain}")
        print()
        print(f"# build {name}")
        print(
            builder_command(
                args.domain,
                output_dir,
                cache,
                args.model,
                args.provider,
                offset,
                limit,
                scope_workers,
                int(batch_recipe["message_chunk_size"]),
                int(batch_recipe["claim_coverage_retry_chunk_size"]),
                int(batch_recipe.get("statefacet_group_max_prompt_chars", DEFAULT_STATEFACET_GROUP_MAX_PROMPT_CHARS)),
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

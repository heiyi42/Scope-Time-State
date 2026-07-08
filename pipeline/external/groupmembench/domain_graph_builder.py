from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
from threading import RLock
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.groupmembench.domain_graph import domain_graph_artifact_dir  # noqa: E402
from pipeline.external.groupmembench.graph_schema import (  # noqa: E402
    EDGE_ALIASES,
    EDGE_ENDPOINT_TYPES,
    EDGE_TYPES,
    NODE_TYPES,
    event_node,
    mentioned_entities,
    scope_node,
    time_id,
    time_node,
    time_nodes,
)
from pipeline.external.groupmembench.graph_store import load_graph_artifact, safe_path_part, write_graph_artifact  # noqa: E402
from pipeline.external.groupmembench.loader import (  # noqa: E402
    CACHE_DIR,
    DOMAINS,
    GRAPH_OUTPUT_DIR,
    GroupMessage,
    build_scope_inventory,
    conversation_path,
    load_domain_messages,
    scope_id_for,
)


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
DATE_RE = re.compile(
    r"\b(?:20\d{2}-\d{2}-\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|today|tomorrow|tonight|eod|end of day)\b",
    re.I,
)
STATEFUL_TERMS = (
    "approve",
    "approved",
    "approval",
    "block",
    "blocked",
    "blocker",
    "change",
    "changed",
    "complete",
    "completed",
    "condition",
    "deadline",
    "decide",
    "decided",
    "decision",
    "delay",
    "delayed",
    "due",
    "exclude",
    "finish",
    "finished",
    "freeze",
    "include",
    "lock",
    "must",
    "need",
    "needs",
    "next",
    "owner",
    "plan",
    "planned",
    "propose",
    "proposed",
    "ready",
    "reject",
    "rejected",
    "replace",
    "responsible",
    "review",
    "risk",
    "scope",
    "should",
    "signed-off",
    "signed off",
    "sign-off",
    "signoff",
    "status",
    "submit",
    "submitted",
    "target",
    "update",
    "updated",
    "validate",
    "validated",
    "validation",
    "will",
)
CLAIM_COVERAGE_TERMS = (
    "approve",
    "block",
    "blocker",
    "calibration",
    "confirm",
    "deadline",
    "decision",
    "due",
    "freeze",
    "lock",
    "must",
    "need",
    "owner",
    "risk",
    "rule",
    "scope",
    "should",
    "signed-off",
    "signed off",
    "sign-off",
    "signoff",
    "threshold",
    "validate",
    "validation",
)
STATE_OBJECT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "must",
    "of",
    "on",
    "or",
    "should",
    "the",
    "to",
    "will",
    "with",
}
STATE_OBJECT_PREFIX_RE = re.compile(
    r"^(?:proposed|decision|risk|blocker|owner|deadline|status|plan|scope|current approach)\s*[:：-]\s*",
    re.I,
)
STATE_OBJECT_PREDICATE_RE = re.compile(
    r"\b(?:is|are|must|should|needs?|will|has|have|was|were|locked|confirmed|deferred|slipped|required|planned|blocked)\b",
    re.I,
)
RELATION_TYPES = {"CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"}
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
STAGE_INPUT_HASH_VERSION = "groupmembench-domain-graph-scope-v1"
STAGE_ARTIFACT_SCHEMA_VERSION = "groupmembench-scope-stage-v1"


def bounded_safe_part(value: str, max_len: int = 96) -> str:
    safe = safe_path_part(value)
    if len(safe) > max_len:
        safe = safe[:max_len].rstrip("._")
    return safe or "unknown"


def scope_dir_name(scope_number: int, scope_id: str) -> str:
    return f"scope{scope_number:03d}_{bounded_safe_part(scope_id)}"


class DomainGraphLLMClient:
    """Route GroupMemBench graph-construction LLM calls to per-scope cache shards."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        api_base: str,
        cache_path: Path,
        use_cache: bool,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.cache_path = cache_path
        self.use_cache = use_cache
        self._clients: Dict[Path, LLMClient] = {}
        self._clients_lock = RLock()
        self._legacy_cache: Dict[str, Any] = {}
        if use_cache and cache_path.exists() and cache_path.is_file():
            loaded = json.loads(cache_path.read_text())
            if isinstance(loaded, dict):
                self._legacy_cache = loaded

    @property
    def shard_root(self) -> Path:
        return self.cache_path.parent / f"{self.cache_path.with_suffix('').name}_shards"

    def shard_cache_path(
        self,
        *,
        domain: str,
        scope_number: int,
        scope_id: str,
        stage: str,
        shard_name: str,
    ) -> Path:
        return (
            self.shard_root
            / bounded_safe_part(domain)
            / scope_dir_name(scope_number, scope_id)
            / bounded_safe_part(stage)
            / f"{bounded_safe_part(shard_name)}.json"
        )

    def _client_for(self, shard_path: Path) -> LLMClient:
        with self._clients_lock:
            client = self._clients.get(shard_path)
            if client is None:
                client = LLMClient(
                    provider=self.provider,
                    model=self.model,
                    api_key=self.api_key,
                    api_base=self.api_base,
                    cache_path=shard_path,
                    use_cache=self.use_cache,
                )
                self._clients[shard_path] = client
            return client

    @staticmethod
    def _cache_key(
        client: LLMClient,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: Optional[int] = None,
    ) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "provider": client.provider,
                    "model": client.model,
                    "api_base": client.api_base,
                    "max_tokens": client.max_tokens if max_tokens is None else max_tokens,
                    "extra_body": client.extra_body,
                    "system": system_prompt,
                    "user": user_prompt,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _fallback_max_tokens(client: LLMClient) -> List[int]:
        values: List[int] = []
        for item in os.environ.get("LLM_CACHE_FALLBACK_MAX_TOKENS", "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = int(item)
            except ValueError:
                continue
            if value != client.max_tokens and value not in values:
                values.append(value)
        return values

    def _write_cache_entry(self, client: LLMClient, cache_key: str, value: Any) -> None:
        if not self.use_cache:
            return
        with client._cache_lock:  # type: ignore[attr-defined]
            if cache_key in client.cache:
                return
            next_cache = dict(client.cache)
            next_cache[cache_key] = deepcopy(value)
            client.cache = next_cache
            client.cache_path.parent.mkdir(parents=True, exist_ok=True)
            client.cache_path.write_text(json.dumps(next_cache, ensure_ascii=False, indent=2))

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        domain: str,
        scope_number: int,
        scope_id: str,
        stage: str,
        shard_name: str,
    ) -> Dict[str, object]:
        client = self._client_for(
            self.shard_cache_path(
                domain=domain,
                scope_number=scope_number,
                scope_id=scope_id,
                stage=stage,
                shard_name=shard_name,
            )
        )
        if self.use_cache:
            cache_key = self._cache_key(client, system_prompt, user_prompt)
            fallback_keys = [
                self._cache_key(client, system_prompt, user_prompt, max_tokens=max_tokens)
                for max_tokens in self._fallback_max_tokens(client)
            ]
            with client._cache_lock:  # type: ignore[attr-defined]
                if cache_key in client.cache:
                    return deepcopy(client.cache[cache_key])
                for fallback_key in fallback_keys:
                    if fallback_key in client.cache:
                        cached = client.cache[fallback_key]
                        self._write_cache_entry(client, cache_key, cached)
                        return deepcopy(cached)
            if cache_key in self._legacy_cache:
                cached = self._legacy_cache[cache_key]
                self._write_cache_entry(client, cache_key, cached)
                return deepcopy(cached)
            for fallback_key in fallback_keys:
                if fallback_key in self._legacy_cache:
                    cached = self._legacy_cache[fallback_key]
                    self._write_cache_entry(client, cache_key, cached)
                    return deepcopy(cached)
        return client.complete_json(system_prompt, user_prompt)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one offline GroupMemBench graph artifact per domain corpus.")
    parser.add_argument("--domains", nargs="+", choices=DOMAINS, default=["Finance"])
    parser.add_argument("--output-dir", default=str(GRAPH_OUTPUT_DIR / "groupmembench_domain_graph_v1"))
    parser.add_argument("--claim-mode", choices=("llm", "heuristic", "none"), default="llm")
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None, help="Optional model override for LLM graph construction.")
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.groupmembench_domain_graph_builder.json"))
    parser.add_argument(
        "--claim-provider",
        choices=("openai", "deepseek"),
        default=None,
        help="Provider override for claim extraction. Defaults to --provider.",
    )
    parser.add_argument("--claim-model", default=None, help="Model override for claim extraction. Defaults to --model.")
    parser.add_argument("--claim-cache", default=None, help="Cache root for claim extraction. Defaults to --cache.")
    parser.add_argument(
        "--statefacet-provider",
        choices=("openai", "deepseek"),
        default=None,
        help="Provider override for StateFacet consolidation. Defaults to --provider.",
    )
    parser.add_argument(
        "--statefacet-model",
        default=None,
        help="Model override for StateFacet consolidation. Defaults to --model.",
    )
    parser.add_argument("--statefacet-cache", default=None, help="Cache root for StateFacet consolidation. Defaults to --cache.")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--message-chunk-size", type=int, default=20)
    parser.add_argument(
        "--message-chunk-max-chars",
        type=int,
        default=0,
        help="Optional approximate character budget per claim-extraction chunk; 0 disables char-budget splitting.",
    )
    parser.add_argument("--max-claims-per-event", type=int, default=2)
    parser.add_argument(
        "--claim-workers",
        type=int,
        default=1,
        help="Concurrent claim-extraction LLM requests within each scope.",
    )
    parser.add_argument(
        "--statefacet-workers",
        type=int,
        default=1,
        help="Concurrent statefacet-consolidation LLM requests within each scope.",
    )
    parser.add_argument(
        "--scope-workers",
        type=int,
        default=1,
        help="Concurrent scope builds for a domain. Effective claim concurrency is scope_workers * claim_workers.",
    )
    parser.add_argument(
        "--no-scope-artifacts",
        action="store_true",
        help="Disable per-scope checkpoint artifacts. By default, each completed scope is written immediately.",
    )
    parser.add_argument(
        "--no-stage-resume",
        action="store_false",
        dest="stage_resume",
        help=(
            "Disable hash-based reuse of matching per-scope checkpoint artifacts. "
            "Resume is active by default when cache and scope artifacts are enabled."
        ),
    )
    parser.set_defaults(stage_resume=True)
    parser.add_argument(
        "--claim-input-filter",
        choices=("all", "stateful"),
        default="all",
        help="Use 'stateful' to send only events with deterministic state cues to the claim-extraction LLM.",
    )
    parser.add_argument(
        "--no-compact-llm-events",
        action="store_false",
        dest="compact_llm_events",
        help="Send full event metadata in LLM prompts instead of compact event payloads.",
    )
    parser.set_defaults(compact_llm_events=True)
    parser.add_argument(
        "--no-claim-coverage-audit",
        action="store_false",
        dest="claim_coverage_audit",
        help="Disable retrying stateful-looking events that produced no Claim nodes.",
    )
    parser.set_defaults(claim_coverage_audit=True)
    parser.add_argument(
        "--claim-coverage-retry-chunk-size",
        type=int,
        default=8,
        help="Chunk size for the no-Claim stateful event retry pass.",
    )
    parser.add_argument(
        "--claim-coverage-backfill",
        choices=("off", "strong", "all"),
        default="strong",
        help=(
            "Before the coverage retry LLM pass, deterministically backfill grounded sentence Claims for "
            "no-Claim events. 'strong' backfills only events with explicit coverage terms or dates; "
            "'all' backfills every stateful no-Claim event."
        ),
    )
    parser.add_argument("--consolidation-claim-limit", type=int, default=240)
    parser.add_argument("--statefacet-claim-limit-per-group", type=int, default=20)
    parser.add_argument("--statefacet-max-groups", type=int, default=8)
    parser.add_argument("--statefacet-consolidation-mode", choices=("grouped", "bucket"), default="grouped")
    parser.add_argument(
        "--statefacet-bucket-max-groups",
        type=int,
        default=0,
        help="Maximum statefacet buckets in bucket mode; 0 keeps all buckets.",
    )
    parser.add_argument(
        "--statefacet-group-max-prompt-chars",
        type=int,
        default=12000,
        help=(
            "If positive, split a statefacet consolidation group when its prompt exceeds this "
            "approximate character budget."
        ),
    )
    parser.add_argument(
        "--no-single-claim-statefacet-short-circuit",
        action="store_false",
        dest="single_claim_statefacet_short_circuit",
        help="Disable deterministic StateFacet creation for one-Claim consolidation groups.",
    )
    parser.set_defaults(single_claim_statefacet_short_circuit=True)
    parser.add_argument("--scope-offset", type=int, default=0, help="Debug/batch offset into sorted scopes before scope-limit.")
    parser.add_argument("--scope-limit", type=int, default=0, help="Debug limit only; 0 builds all scopes.")
    parser.add_argument("--event-limit", type=int, default=0, help="Debug limit only; 0 builds the full selected corpus.")
    return parser.parse_args()


def stable_hash(payload: Mapping[str, object]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_safe_rows(rows: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n")
    tmp_path.replace(path)


def load_json_object(path: Path) -> Optional[Dict[str, object]]:
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def message_hash_payload(message: GroupMessage) -> Dict[str, object]:
    return {
        "domain": message.domain,
        "channel": message.channel,
        "msg_node": message.msg_node,
        "content": message.content,
        "author": message.author,
        "role": message.role,
        "timestamp": message.timestamp,
        "reply_to": message.reply_to,
        "phase_name": message.phase_name,
        "topic": message.topic,
        "message_type": message.message_type,
        "path_type": message.path_type,
    }


def llm_runtime_hash_payload(client: DomainGraphLLMClient) -> Dict[str, object]:
    return {
        "provider": client.provider,
        "model": client.model,
        "api_base": client.api_base,
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        "deepseek_thinking": os.environ.get("DEEPSEEK_THINKING", ""),
        "json_mode_disabled_for": os.environ.get("LLM_DISABLE_JSON_MODE_FOR_PROVIDERS", ""),
    }


def scope_stage_input_hash(
    *,
    domain: str,
    scope: Mapping[str, object],
    messages: Sequence[GroupMessage],
    args: argparse.Namespace,
    claim_client: DomainGraphLLMClient,
    state_client: DomainGraphLLMClient,
) -> str:
    payload = {
        "version": STAGE_INPUT_HASH_VERSION,
        "domain": domain,
        "scope": dict(scope),
        "messages": [message_hash_payload(message) for message in messages],
        "llm_runtime": {
            "claim_extraction": llm_runtime_hash_payload(claim_client),
            "state_consolidation": llm_runtime_hash_payload(state_client),
        },
        "claim_extraction": {
            "message_chunk_size": args.message_chunk_size,
            "message_chunk_max_chars": args.message_chunk_max_chars,
            "max_claims_per_event": args.max_claims_per_event,
            "claim_input_filter": args.claim_input_filter,
            "compact_llm_events": args.compact_llm_events,
            "claim_coverage_audit": args.claim_coverage_audit,
            "claim_coverage_retry_chunk_size": args.claim_coverage_retry_chunk_size,
            "claim_coverage_backfill": args.claim_coverage_backfill,
        },
        "state_consolidation": {
            "consolidation_claim_limit": args.consolidation_claim_limit,
            "statefacet_claim_limit_per_group": args.statefacet_claim_limit_per_group,
            "statefacet_max_groups": args.statefacet_max_groups,
            "statefacet_consolidation_mode": args.statefacet_consolidation_mode,
            "statefacet_bucket_max_groups": args.statefacet_bucket_max_groups,
            "statefacet_group_max_prompt_chars": args.statefacet_group_max_prompt_chars,
            "single_claim_statefacet_short_circuit": args.single_claim_statefacet_short_circuit,
            "compact_llm_events": args.compact_llm_events,
        },
    }
    return stable_hash(payload)


def claim_stage_input_hash(
    *,
    domain: str,
    scope: Mapping[str, object],
    messages: Sequence[GroupMessage],
    args: argparse.Namespace,
    client: DomainGraphLLMClient,
) -> str:
    payload = {
        "version": f"{STAGE_INPUT_HASH_VERSION}:claim_extraction",
        "domain": domain,
        "scope": dict(scope),
        "messages": [message_hash_payload(message) for message in messages],
        "llm_runtime": llm_runtime_hash_payload(client),
        "claim_extraction": {
            "message_chunk_size": args.message_chunk_size,
            "message_chunk_max_chars": args.message_chunk_max_chars,
            "max_claims_per_event": args.max_claims_per_event,
            "claim_input_filter": args.claim_input_filter,
            "compact_llm_events": args.compact_llm_events,
            "claim_coverage_audit": args.claim_coverage_audit,
            "claim_coverage_retry_chunk_size": args.claim_coverage_retry_chunk_size,
            "claim_coverage_backfill": args.claim_coverage_backfill,
        },
    }
    return stable_hash(payload)


def claims_hash(claims: Sequence[Mapping[str, object]]) -> str:
    return stable_hash({"claims": json_safe_rows(claims)})


def state_stage_input_hash(
    *,
    domain: str,
    scope: Mapping[str, object],
    messages: Sequence[GroupMessage],
    claims: Sequence[Mapping[str, object]],
    args: argparse.Namespace,
    client: DomainGraphLLMClient,
) -> str:
    payload = {
        "version": f"{STAGE_INPUT_HASH_VERSION}:state_consolidation",
        "domain": domain,
        "scope": dict(scope),
        "messages": [message_hash_payload(message) for message in messages],
        "claims_hash": claims_hash(claims),
        "llm_runtime": llm_runtime_hash_payload(client),
        "state_consolidation": {
            "consolidation_claim_limit": args.consolidation_claim_limit,
            "statefacet_claim_limit_per_group": args.statefacet_claim_limit_per_group,
            "statefacet_max_groups": args.statefacet_max_groups,
            "statefacet_consolidation_mode": args.statefacet_consolidation_mode,
            "statefacet_bucket_max_groups": args.statefacet_bucket_max_groups,
            "statefacet_group_max_prompt_chars": args.statefacet_group_max_prompt_chars,
            "single_claim_statefacet_short_circuit": args.single_claim_statefacet_short_circuit,
            "compact_llm_events": args.compact_llm_events,
        },
    }
    return stable_hash(payload)


def stage_resume_enabled(args: argparse.Namespace, output_dir: Optional[Path]) -> bool:
    return bool(
        args.stage_resume
        and not args.no_cache
        and output_dir is not None
        and not args.no_scope_artifacts
    )


def schema_payload() -> Dict[str, object]:
    return {
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
        "edge_aliases": dict(EDGE_ALIASES),
        "edge_endpoint_types": {edge: list(types) for edge, types in EDGE_ENDPOINT_TYPES.items()},
        "source": "Design/Graph/*.png",
    }


def clean_sentence(text: str) -> str:
    return " ".join(text.strip().split())


def sentence_candidates(content: str) -> List[str]:
    candidates = [clean_sentence(part) for part in SENTENCE_SPLIT_RE.split(content) if clean_sentence(part)]
    if not candidates:
        cleaned = clean_sentence(content)
        return [cleaned] if cleaned else []
    return candidates


def is_stateful_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    if DATE_RE.search(sentence):
        return True
    return any(term in lowered for term in STATEFUL_TERMS)


def claim_coverage_reasons(message: GroupMessage) -> List[str]:
    content = clean_sentence(message.content)
    if len(content) < 30:
        return []
    if content.startswith("[Error generating message:"):
        return []
    lowered = content.lower()
    reasons: List[str] = []
    if DATE_RE.search(content):
        reasons.append("date_or_relative_time")
    if any(is_stateful_sentence(sentence) for sentence in sentence_candidates(content)):
        reasons.append("stateful_sentence")
    for term in CLAIM_COVERAGE_TERMS:
        if term in lowered:
            reasons.append(f"term:{term.replace(' ', '_')}")
    return list(dict.fromkeys(reasons))[:8]


def has_strong_claim_coverage_signal(reasons: Sequence[str]) -> bool:
    return any(reason != "stateful_sentence" for reason in reasons)


def should_backfill_claim_coverage(reasons: Sequence[str], policy: str) -> bool:
    if policy == "all":
        return bool(reasons)
    if policy == "strong":
        return has_strong_claim_coverage_signal(reasons)
    return False


def infer_facet_type(sentence: str) -> str:
    lowered = sentence.lower()
    if "deadline" in lowered or "due" in lowered or "eod" in lowered:
        return "deadline"
    if "owner" in lowered or "responsible" in lowered:
        return "owner"
    if "block" in lowered or "risk" in lowered:
        return "risk_or_blocker"
    if "scope" in lowered or "include" in lowered or "exclude" in lowered:
        return "scope"
    if "approve" in lowered or "sign-off" in lowered or "signoff" in lowered:
        return "approval"
    if "status" in lowered or "complete" in lowered or "ready" in lowered or "finished" in lowered:
        return "status"
    if DATE_RE.search(sentence):
        return "date"
    return "state"


def infer_claim_type(sentence: str) -> str:
    lowered = sentence.lower()
    if any(term in lowered for term in ("change", "changed", "replace", "updated", "update")):
        return "correction"
    if any(term in lowered for term in ("decide", "decided", "decision", "approved", "rejected")):
        return "decision"
    if any(term in lowered for term in ("plan", "planned", "will", "should", "need", "needs", "must")):
        return "plan"
    if any(term in lowered for term in ("complete", "completed", "submitted", "finished", "ready")):
        return "completion"
    if "risk" in lowered or "block" in lowered:
        return "risk"
    if DATE_RE.search(sentence):
        return "date"
    return "observation"


def tokens(text: object) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def token_support_score(value: object, source: object) -> float:
    value_tokens = [token for token in tokens(value) if len(token) > 2]
    if not value_tokens:
        return 0.0
    source_tokens = set(tokens(source))
    hits = sum(1 for token in value_tokens if token in source_tokens)
    return hits / max(1, len(value_tokens))


def extract_heuristic_claims(message: GroupMessage, max_claims_per_event: int) -> List[Dict[str, object]]:
    if max_claims_per_event <= 0:
        return []
    claims: List[Dict[str, object]] = []
    for sentence in sentence_candidates(message.content):
        if len(sentence) < 12 or not is_stateful_sentence(sentence):
            continue
        claim_index = len(claims) + 1
        claims.append(
            {
                "node_type": "Claim",
                "claim_id": f"claim::{message.event_id}::{claim_index}",
                "event_id": message.event_id,
                "facet_type": infer_facet_type(sentence),
                "value": sentence[:600],
                "claim_type": infer_claim_type(sentence),
                "time_value": None,
                "time_role": None,
                "extraction_method": "offline_heuristic_sentence",
            }
        )
        if len(claims) >= max_claims_per_event:
            break
    return claims


def coverage_backfill_claims(
    message: GroupMessage,
    scope_id: str,
    max_claims_per_event: int,
    per_event_counts: Dict[str, int],
) -> List[Dict[str, object]]:
    remaining = max(0, max_claims_per_event - per_event_counts.get(message.event_id, 0))
    if remaining <= 0:
        return []
    backfilled: List[Dict[str, object]] = []
    for claim in extract_heuristic_claims(message, remaining):
        per_event_counts[message.event_id] = per_event_counts.get(message.event_id, 0) + 1
        claim = dict(claim)
        claim["claim_id"] = f"claim::{message.event_id}::{per_event_counts[message.event_id]}"
        claim["scope_id"] = scope_id
        claim["extraction_method"] = "deterministic_coverage_backfill"
        backfilled.append(claim)
    return backfilled


def claims_for_messages(
    messages: Sequence[GroupMessage],
    claim_mode: str,
    max_claims_per_event: int,
) -> Tuple[List[Dict[str, object]], Dict[str, int]]:
    if claim_mode == "none":
        return [], {"events_with_claims": 0, "claims": 0}
    claims: List[Dict[str, object]] = []
    events_with_claims = 0
    for message in messages:
        extracted = extract_heuristic_claims(message, max_claims_per_event)
        if extracted:
            events_with_claims += 1
            claims.extend(extracted)
    return claims, {"events_with_claims": events_with_claims, "claims": len(claims)}


def visible_event_payload(message: GroupMessage) -> Dict[str, object]:
    return {
        "event_id": message.event_id,
        "content": message.content,
        "occurred_at": message.timestamp,
        "source_id": message.author,
        "metadata": {
            "domain": message.domain,
            "channel": message.channel,
            "phase_name": message.phase_name,
            "topic": message.topic,
            "role": message.role,
            "author": message.author,
            "reply_to": message.reply_to,
            "message_type": message.message_type,
        },
    }


def compact_event_payload(message: GroupMessage) -> Dict[str, object]:
    return {
        "event_id": message.event_id,
        "content": message.content,
        "occurred_at": message.timestamp,
        "source_id": message.author,
        "metadata": {
            "role": message.role,
            "author": message.author,
            "reply_to": message.reply_to,
            "message_type": message.message_type,
        },
    }


def llm_event_payload(message: GroupMessage, compact_events: bool) -> Dict[str, object]:
    if compact_events:
        return compact_event_payload(message)
    return visible_event_payload(message)


def claim_extraction_system_prompt() -> str:
    return (
        "You construct an offline Scope-Time-State Graph for GroupMemBench before any question is seen. "
        "Use only the provided Episode/Event nodes. Do not assume benchmark answers, questions, qtypes, or judge labels. "
        "Extract Claim nodes only: atomic state assertions made by the events. Keep dates, owners, decisions, status, "
        "scope boundaries, blockers, risks, corrections, and plans that may affect current state reasoning later. "
        "Do not create StateFacet nodes in this stage. Return valid JSON only."
    )


def claim_extraction_user_prompt(
    domain: str,
    scope: Dict[str, object],
    messages: Sequence[GroupMessage],
    chunk_index: int,
    chunk_count: int,
    max_claims_per_event: int,
    stage: str = "offline_claim_extraction",
    coverage_reasons_by_event_id: Optional[Dict[str, List[str]]] = None,
    compact_events: bool = True,
) -> str:
    payload = {
        "cache_namespace": {
            "benchmark": "GroupMemBench",
            "domain": domain,
            "stage": stage,
            "scope_id": scope.get("scope_id"),
            "chunk_index": chunk_index,
        },
        "graph_definition": {
            "node_types": list(NODE_TYPES),
            "edge_types_created_here": ["ASSERTS"],
            "claim_definition": "A Claim is an atomic state assertion extracted from an Event. It is not necessarily current valid.",
        },
        "scope": scope,
        "visible_event_ids": [message.event_id for message in messages],
        "visible_events": [llm_event_payload(message, compact_events) for message in messages],
        "task": (
            "For each visible event, extract at most max_claims_per_event stateful Claim candidates. "
            "Skip chit-chat, generic acknowledgements, and pure mentions. A claim value must be grounded in the event text. "
            "If an event corrects, replaces, changes, approves, rejects, blocks, schedules, assigns ownership, or states a deadline, keep it. "
            "Use time_value/time_role only when the event text explicitly states a date/time role."
        ),
        "max_claims_per_event": max_claims_per_event,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "canonical_facet_types": [
            "deadline",
            "owner",
            "status",
            "scope",
            "risk",
            "blocker",
            "decision",
            "plan",
            "date",
            "current_approach",
            "state",
        ],
        "facet_type_policy": (
            "Prefer a canonical_facet_type when it fits. You may introduce a concise lowercase snake_case "
            "facet_type when the claim has a real state dimension not covered by the canonical set."
        ),
        "output_schema": {
            "claims": [
                {
                    "event_id": "copied exactly from visible_event_ids",
                    "facet_type": "canonical type, or concise lowercase snake_case extension when needed",
                    "value": "grounded atomic state assertion",
                    "claim_type": "decision|risk|plan|completion|correction|observation|date|owner|scope",
                    "time_value": "explicit date/time if present, otherwise null",
                    "time_role": "occurred_at|mentioned_at|updated_at|planned_for|deadline_at|null",
                }
            ],
            "rejected_claims": [
                {"event_id": "Msg_...", "reason": "mention_only|not_stateful|duplicate|unsupported"}
            ],
        },
    }
    if coverage_reasons_by_event_id:
        payload["coverage_retry"] = {
            "reason": (
                "These visible events produced no Claim node in the first extraction pass, "
                "but a deterministic coverage audit found stateful cues. Re-check them carefully."
            ),
            "coverage_reasons_by_event_id": coverage_reasons_by_event_id,
            "instruction": (
                "Extract at least one grounded Claim when the event states a blocker, sign-off need, "
                "deadline, owner, decision, approval, risk, threshold/rule requirement, validation condition, "
                "or current plan. Reject only if the event is truly mention-only or non-stateful."
            ),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_offline_claims(
    raw: Dict[str, object],
    messages: Sequence[GroupMessage],
    scope_id: str,
    per_event_counts: Dict[str, int],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    visible_by_id = {message.event_id: message for message in messages}
    claims: List[Dict[str, object]] = []
    rejected: List[Dict[str, object]] = []
    dropped_invalid = 0
    dropped_unsupported = 0
    for item in raw.get("claims", []) if isinstance(raw.get("claims"), list) else []:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("event_id") or "")
        message = visible_by_id.get(event_id)
        if message is None:
            dropped_invalid += 1
            continue
        value = " ".join(str(item.get("value") or "").split())
        if not value or token_support_score(value, message.content) < 0.35:
            dropped_unsupported += 1
            continue
        per_event_counts[event_id] = per_event_counts.get(event_id, 0) + 1
        claims.append(
            {
                "node_type": "Claim",
                "claim_id": f"claim::{event_id}::{per_event_counts[event_id]}",
                "event_id": event_id,
                "scope_id": scope_id,
                "facet_type": str(item.get("facet_type") or "state"),
                "value": value[:800],
                "claim_type": str(item.get("claim_type") or "observation"),
                "time_value": item.get("time_value") if item.get("time_value") not in {"", "null"} else None,
                "time_role": item.get("time_role") if item.get("time_role") not in {"", "null"} else None,
                "extraction_method": "llm_offline_claim_extraction",
            }
        )
    for item in raw.get("rejected_claims", []) if isinstance(raw.get("rejected_claims"), list) else []:
        if isinstance(item, dict) and str(item.get("event_id") or "") in visible_by_id:
            rejected.append(
                {
                    "event_id": str(item.get("event_id") or ""),
                    "scope_id": scope_id,
                    "reason": str(item.get("reason") or ""),
                    "stage": "offline_claim_extraction",
                }
            )
    validation = {
        "visible_event_count": len(messages),
        "claim_count": len(claims),
        "rejected_claim_count": len(rejected),
        "dropped_invalid_event_id_count": dropped_invalid,
        "dropped_unsupported_count": dropped_unsupported,
    }
    return claims, rejected, validation


def approx_chunk_chars(message: GroupMessage) -> int:
    return (
        len(message.content)
        + len(message.event_id)
        + len(message.timestamp)
        + len(message.author)
        + len(message.role)
        + 128
    )


def chunks(
    items: Sequence[GroupMessage],
    size: int,
    max_chars: int = 0,
) -> List[Sequence[GroupMessage]]:
    chunk_size = max(1, size)
    if max_chars <= 0:
        return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]
    chunk_char_budget = max(1, max_chars)
    output: List[Sequence[GroupMessage]] = []
    current: List[GroupMessage] = []
    current_chars = 0
    for item in items:
        item_chars = approx_chunk_chars(item)
        if current and (len(current) >= chunk_size or current_chars + item_chars > chunk_char_budget):
            output.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
        if len(current) >= chunk_size:
            output.append(current)
            current = []
            current_chars = 0
    if current:
        output.append(current)
    return output


def claim_input_messages(messages: Sequence[GroupMessage], claim_input_filter: str) -> List[GroupMessage]:
    if claim_input_filter == "stateful":
        return [message for message in messages if claim_coverage_reasons(message)]
    return list(messages)


def extract_llm_claims_for_scope(
    client: DomainGraphLLMClient,
    domain: str,
    scope: Dict[str, object],
    scope_number: int,
    messages: Sequence[GroupMessage],
    message_chunk_size: int,
    message_chunk_max_chars: int,
    max_claims_per_event: int,
    claim_coverage_audit: bool,
    claim_coverage_retry_chunk_size: int,
    claim_coverage_backfill: str,
    claim_workers: int,
    claim_input_filter: str,
    compact_events: bool,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    claims: List[Dict[str, object]] = []
    rejected: List[Dict[str, object]] = []
    validations: List[Dict[str, object]] = []
    per_event_counts: Dict[str, int] = {}
    input_messages = claim_input_messages(messages, claim_input_filter)
    if claim_input_filter != "all":
        validations.append(
            {
                "stage": "offline_claim_input_filter",
                "claim_input_filter": claim_input_filter,
                "visible_event_count": len(messages),
                "llm_input_event_count": len(input_messages),
                "skipped_event_count": len(messages) - len(input_messages),
            }
        )

    def run_chunk_requests(
        stage: str,
        stage_label: str,
        message_chunks: Sequence[Sequence[GroupMessage]],
    ) -> List[Tuple[int, Sequence[GroupMessage], Dict[str, object]]]:
        chunk_count = len(message_chunks)
        if chunk_count == 0:
            return []
        worker_count = min(max(1, claim_workers), chunk_count)

        def run_one(chunk_index: int, message_chunk: Sequence[GroupMessage]) -> Tuple[int, Sequence[GroupMessage], Dict[str, object]]:
            coverage_reasons = None
            if stage == "offline_claim_coverage_retry":
                coverage_reasons = {message.event_id: claim_coverage_reasons(message) for message in message_chunk}
            raw = client.complete_json(
                claim_extraction_system_prompt(),
                claim_extraction_user_prompt(
                    domain,
                    scope,
                    message_chunk,
                    chunk_index,
                    chunk_count,
                    max_claims_per_event,
                    stage=stage,
                    coverage_reasons_by_event_id=coverage_reasons,
                    compact_events=compact_events,
                ),
                domain=domain,
                scope_number=scope_number,
                scope_id=str(scope.get("scope_id") or ""),
                stage=stage,
                shard_name=f"chunk{chunk_index:03d}",
            )
            return chunk_index, message_chunk, raw

        if worker_count == 1:
            results = []
            for chunk_index, message_chunk in enumerate(message_chunks, start=1):
                print(
                    f"  {stage_label} chunk {chunk_index}/{chunk_count} "
                    f"events={len(message_chunk)}",
                    flush=True,
                )
                results.append(run_one(chunk_index, message_chunk))
                time.sleep(0.05)
            return results

        print(f"  {stage_label} parallel workers={worker_count} chunks={chunk_count}", flush=True)
        results = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {}
            for chunk_index, message_chunk in enumerate(message_chunks, start=1):
                print(
                    f"  {stage_label} chunk {chunk_index}/{chunk_count} "
                    f"events={len(message_chunk)} queued",
                    flush=True,
                )
                futures[executor.submit(run_one, chunk_index, message_chunk)] = (chunk_index, message_chunk)
            for future in as_completed(futures):
                chunk_index, message_chunk = futures[future]
                result = future.result()
                print(
                    f"  {stage_label} chunk {chunk_index}/{chunk_count} "
                    f"events={len(message_chunk)} completed",
                    flush=True,
                )
                results.append(result)
        results.sort(key=lambda item: item[0])
        return results

    message_chunks = chunks(input_messages, message_chunk_size, message_chunk_max_chars)
    for chunk_index, message_chunk, raw in run_chunk_requests(
        "offline_claim_extraction",
        "claim extraction",
        message_chunks,
    ):
        chunk_claims, chunk_rejected, validation = normalize_offline_claims(
            raw,
            message_chunk,
            str(scope.get("scope_id") or ""),
            per_event_counts,
        )
        validation["chunk_index"] = chunk_index
        validations.append(validation)
        claims.extend(chunk_claims)
        rejected.extend(chunk_rejected)
        print(
            f"  chunk {chunk_index}/{len(message_chunks)} claims={validation['claim_count']} "
            f"rejected={validation['rejected_claim_count']} dropped_invalid={validation['dropped_invalid_event_id_count']} "
            f"dropped_unsupported={validation['dropped_unsupported_count']}",
            flush=True,
        )
        time.sleep(0.05)
    if claim_coverage_audit:
        missing_messages = [
            message
            for message in input_messages
            if per_event_counts.get(message.event_id, 0) == 0 and claim_coverage_reasons(message)
        ]
        validations.append(
            {
                "stage": "offline_claim_coverage_audit",
                "visible_event_count": len(messages),
                "events_with_claims": len(per_event_counts),
                "stateful_no_claim_event_count": len(missing_messages),
                "stateful_no_claim_event_ids": [message.event_id for message in missing_messages],
            }
        )
        if claim_coverage_backfill != "off" and missing_messages:
            retry_messages: List[GroupMessage] = []
            backfilled_event_ids: List[str] = []
            backfilled_claim_count = 0
            skipped_event_ids: List[str] = []
            scope_id = str(scope.get("scope_id") or "")
            for message in missing_messages:
                reasons = claim_coverage_reasons(message)
                if should_backfill_claim_coverage(reasons, claim_coverage_backfill):
                    backfilled = coverage_backfill_claims(message, scope_id, max_claims_per_event, per_event_counts)
                    if backfilled:
                        claims.extend(backfilled)
                        backfilled_event_ids.append(message.event_id)
                        backfilled_claim_count += len(backfilled)
                        continue
                    skipped_event_ids.append(message.event_id)
                retry_messages.append(message)
            validations.append(
                {
                    "stage": "offline_claim_coverage_backfill",
                    "policy": claim_coverage_backfill,
                    "input_event_count": len(missing_messages),
                    "backfilled_event_count": len(backfilled_event_ids),
                    "backfilled_claim_count": backfilled_claim_count,
                    "llm_retry_event_count": len(retry_messages),
                    "skipped_event_count": len(skipped_event_ids),
                    "backfilled_event_ids": backfilled_event_ids,
                    "skipped_event_ids": skipped_event_ids,
                }
            )
            print(
                f"  coverage backfill policy={claim_coverage_backfill} "
                f"events={len(backfilled_event_ids)} claims={backfilled_claim_count} "
                f"retry_events={len(retry_messages)}",
                flush=True,
            )
            missing_messages = retry_messages
        retry_chunks = chunks(missing_messages, claim_coverage_retry_chunk_size, message_chunk_max_chars)
        for retry_index, retry_chunk, raw in run_chunk_requests(
            "offline_claim_coverage_retry",
            "claim coverage retry",
            retry_chunks,
        ):
            retry_claims, retry_rejected, validation = normalize_offline_claims(
                raw,
                retry_chunk,
                str(scope.get("scope_id") or ""),
                per_event_counts,
            )
            validation["stage"] = "offline_claim_coverage_retry"
            validation["chunk_index"] = retry_index
            validation["coverage_retry_event_ids"] = [message.event_id for message in retry_chunk]
            validations.append(validation)
            claims.extend(retry_claims)
            rejected.extend(retry_rejected)
            print(
                f"  coverage retry {retry_index}/{len(retry_chunks)} claims={validation['claim_count']} "
                f"rejected={validation['rejected_claim_count']} "
                f"dropped_invalid={validation['dropped_invalid_event_id_count']} "
                f"dropped_unsupported={validation['dropped_unsupported_count']}",
                flush=True,
            )
            time.sleep(0.05)
    return claims, rejected, validations


def state_consolidation_system_prompt() -> str:
    return (
        "You construct offline current StateFacet nodes for a Scope-Time-State Graph before any question is seen. "
        "Given Claim nodes from one Scope, resolve claim-level currentness. Add only Claim-to-Claim relations "
        "CORRECTS, SUPERSEDES, or CONFLICTS_WITH when supported by the claim/event text. Then create active StateFacet "
        "nodes for current valid state dimensions under the scope. StateFacet is the current effective state field after "
        "claim selection, conflict resolution, and temporal/currentness reasoning. Do not answer any benchmark question. "
        "Return valid JSON only."
    )


def state_consolidation_user_prompt(
    domain: str,
    scope: Dict[str, object],
    claims: Sequence[Dict[str, object]],
    source_events: Sequence[GroupMessage],
    claim_limit: int,
    compact_events: bool = True,
) -> str:
    payload = {
        "cache_namespace": {
            "benchmark": "GroupMemBench",
            "domain": domain,
            "stage": "offline_statefacet_consolidation",
            "scope_id": scope.get("scope_id"),
        },
        "graph_definition": {
            "claim_relations": ["CORRECTS", "SUPERSEDES", "CONFLICTS_WITH"],
            "statefacet_edges": ["SUPPORTS", "CURRENT_AFTER", "CURRENT_STATE_OF"],
            "statefacet_definition": (
                "A StateFacet is a current valid state dimension for this scope, supported by accepted Claim nodes."
            ),
        },
        "scope": scope,
        "candidate_claim_count": len(claims),
        "claim_limit_note": "Claims are the most recent candidates when candidate_claim_count exceeds consolidation_claim_limit.",
        "consolidation_claim_limit": claim_limit,
        "candidate_claims": list(claims),
        "source_events": [llm_event_payload(message, compact_events) for message in source_events],
        "task": (
            "Resolve which claims are current valid for this scope. Create multiple StateFacet nodes if the scope has "
            "multiple current dimensions such as status, owner, deadline, blocker, decision, scope boundary, next step, "
            "or current approach. A later claim may SUPERSEDE an older true claim when it replaces the same state. "
            "Use CORRECTS when a later claim explicitly fixes an earlier wrong claim. Use CONFLICTS_WITH when two claims "
            "cannot both be active and the graph alone needs a later rule or explicit support to pick. "
            "Each StateFacet must cite support_claims and support_events from candidate_claims."
        ),
        "output_schema": {
            "relations": [
                {
                    "type": "CORRECTS|SUPERSEDES|CONFLICTS_WITH",
                    "from": "new_or_left_claim_id",
                    "to": "old_or_right_claim_id",
                    "evidence_event_ids": ["Msg_..."],
                    "reason": "why the relation holds",
                }
            ],
            "rejected_claims": [
                {
                    "claim_id": "claim id from candidate_claims",
                    "event_id": "source event id",
                    "validity": "stale|superseded|invalidated|conflicting|discussion_only|irrelevant",
                    "reason": "why it is not current valid",
                }
            ],
            "state_facets": [
                {
                    "name": "status|owner|deadline|blocker|decision|scope|next_step|current_approach|...",
                    "value": "current valid state value",
                    "status": "active",
                    "support_claims": ["claim::..."],
                    "support_events": ["Msg_..."],
                    "current_after": "timestamp after which this facet is current, preferably latest support event timestamp",
                    "time_value": "explicit date/time value if this facet is temporal, otherwise null",
                    "time_role": "occurred_at|mentioned_at|updated_at|planned_for|deadline_at|null",
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def messages_by_id(messages: Sequence[GroupMessage]) -> Dict[str, GroupMessage]:
    return {message.event_id: message for message in messages}


def recent_claims_for_consolidation(
    claims: Sequence[Dict[str, object]],
    messages: Sequence[GroupMessage],
    limit: int,
) -> List[Dict[str, object]]:
    if limit <= 0 or len(claims) <= limit:
        return [deepcopy(claim) for claim in claims]
    event_by_id = messages_by_id(messages)
    ranked = []
    for index, claim in enumerate(claims):
        event = event_by_id.get(str(claim.get("event_id") or ""))
        timestamp = event.timestamp if event else ""
        ranked.append((timestamp, index, claim))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = [deepcopy(item[2]) for item in ranked[:limit]]
    selected.sort(key=lambda item: (str(item.get("event_id") or ""), str(item.get("claim_id") or "")))
    return selected


def normalize_scope_state(
    raw: Dict[str, object],
    scope: Dict[str, object],
    claims: Sequence[Dict[str, object]],
    messages: Sequence[GroupMessage],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    claim_by_id = {str(claim.get("claim_id") or ""): claim for claim in claims}
    event_by_id = messages_by_id(messages)
    relations: List[Dict[str, object]] = []
    rejected: List[Dict[str, object]] = []
    facets: List[Dict[str, object]] = []
    dropped_relations = 0
    dropped_facets = 0
    for item in raw.get("relations", []) if isinstance(raw.get("relations"), list) else []:
        if not isinstance(item, dict):
            continue
        relation_type = str(item.get("type") or "").upper()
        source = str(item.get("from") or "")
        target = str(item.get("to") or "")
        if relation_type not in RELATION_TYPES or source not in claim_by_id or target not in claim_by_id:
            dropped_relations += 1
            continue
        relations.append(
            {
                "type": relation_type,
                "from": source,
                "to": target,
                "evidence_event_ids": [
                    str(event_id)
                    for event_id in item.get("evidence_event_ids", [])
                    if str(event_id) in event_by_id
                ],
                "reason": str(item.get("reason") or "")[:500],
            }
        )
    for item in raw.get("rejected_claims", []) if isinstance(raw.get("rejected_claims"), list) else []:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or "")
        if claim_id not in claim_by_id:
            continue
        rejected.append(
            {
                "claim_id": claim_id,
                "event_id": str(item.get("event_id") or claim_by_id[claim_id].get("event_id") or ""),
                "validity": str(item.get("validity") or "rejected"),
                "reason": str(item.get("reason") or "")[:500],
                "stage": "offline_statefacet_consolidation",
            }
        )
    for item in raw.get("state_facets", []) if isinstance(raw.get("state_facets"), list) else []:
        if not isinstance(item, dict):
            continue
        support_claims = [
            str(claim_id)
            for claim_id in item.get("support_claims", [])
            if str(claim_id) in claim_by_id
        ]
        if not support_claims:
            dropped_facets += 1
            continue
        support_events: List[str] = []
        for claim_id in support_claims:
            event_id = str(claim_by_id[claim_id].get("event_id") or "")
            if event_id and event_id not in support_events:
                support_events.append(event_id)
        for event_id in item.get("support_events", []):
            event_id = str(event_id)
            if event_id in event_by_id and event_id not in support_events:
                support_events.append(event_id)
        current_after = str(item.get("current_after") or "")
        if not current_after:
            current_after = max((event_by_id[event_id].timestamp for event_id in support_events if event_id in event_by_id), default="")
        facets.append(
            {
                "node_type": "StateFacet",
                "facet_id": f"facet::{scope.get('scope_id')}::{len(facets) + 1}",
                "scope_id": scope.get("scope_id"),
                "name": str(item.get("name") or "current_state"),
                "value": str(item.get("value") or "")[:1000],
                "status": str(item.get("status") or "active"),
                "support_claims": support_claims,
                "support_events": support_events,
                "current_after": current_after or None,
                "time_value": item.get("time_value") if item.get("time_value") not in {"", "null"} else None,
                "time_role": item.get("time_role") if item.get("time_role") not in {"", "null"} else None,
                "construction_method": "llm_offline_statefacet_consolidation",
            }
        )
    validation = {
        "input_claim_count": len(claims),
        "relation_count": len(relations),
        "rejected_claim_count": len(rejected),
        "state_facet_count": len(facets),
        "dropped_relation_count": dropped_relations,
        "dropped_facet_count": dropped_facets,
    }
    return relations, rejected, facets, validation


def single_claim_statefacet(
    scope: Mapping[str, object],
    claim: Mapping[str, object],
    messages: Sequence[GroupMessage],
) -> Dict[str, object]:
    event_id = str(claim.get("event_id") or "")
    event_by_id = messages_by_id(messages)
    event = event_by_id.get(event_id)
    current_after = event.timestamp if event is not None else None
    return {
        "node_type": "StateFacet",
        "facet_id": f"facet::{scope.get('scope_id')}::1",
        "scope_id": scope.get("scope_id"),
        "name": str(claim.get("facet_type") or "current_state"),
        "value": str(claim.get("value") or "")[:1000],
        "status": "active",
        "support_claims": [str(claim.get("claim_id") or "")],
        "support_events": [event_id] if event_id else [],
        "current_after": current_after,
        "time_value": claim.get("time_value") if claim.get("time_value") not in {"", "null"} else None,
        "time_role": claim.get("time_role") if claim.get("time_role") not in {"", "null"} else None,
        "construction_method": "deterministic_single_claim_statefacet",
    }


def grouped_claims_for_consolidation(
    claims: Sequence[Dict[str, object]],
    messages: Sequence[GroupMessage],
    total_limit: int,
    per_group_limit: int,
    max_groups: int,
) -> List[Tuple[str, List[Dict[str, object]]]]:
    selected_claims = recent_claims_for_consolidation(claims, messages, total_limit)
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for claim in selected_claims:
        key = str(claim.get("facet_type") or "state")
        grouped.setdefault(key, []).append(claim)
    ranked_groups = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))[: max(1, max_groups)]
    return [
        (name, recent_claims_for_consolidation(group_claims, messages, per_group_limit))
        for name, group_claims in ranked_groups
    ]


def state_object_key(value: object) -> str:
    text = clean_sentence(str(value or ""))
    text = STATE_OBJECT_PREFIX_RE.sub("", text)
    if not text:
        return "state"
    colon_parts = re.split(r"[:：]", text, maxsplit=1)
    if len(colon_parts) > 1 and 3 <= len(colon_parts[0]) <= 80:
        candidate = colon_parts[0]
    else:
        predicate_match = STATE_OBJECT_PREDICATE_RE.search(text)
        candidate = text[: predicate_match.start()] if predicate_match and predicate_match.start() >= 3 else text
    words = [
        token.lower()
        for token in TOKEN_RE.findall(candidate)
        if len(token) > 1 and token.lower() not in STATE_OBJECT_STOPWORDS
    ]
    if not words:
        words = [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1]
    return "_".join(words[:8]) or "state"


def bucket_group_name(facet_type: str, object_key: str) -> str:
    return f"bucket__{bounded_safe_part(facet_type, 32)}__{bounded_safe_part(object_key, 64)}"


def bucketed_claims_for_consolidation(
    claims: Sequence[Dict[str, object]],
    messages: Sequence[GroupMessage],
    total_limit: int,
    per_group_limit: int,
    max_groups: int,
) -> List[Tuple[str, List[Dict[str, object]]]]:
    selected_claims = recent_claims_for_consolidation(claims, messages, total_limit)
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = {}
    for claim in selected_claims:
        facet_type = str(claim.get("facet_type") or "state")
        object_key = state_object_key(claim.get("value"))
        grouped.setdefault((facet_type, object_key), []).append(claim)
    ranked_groups = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0][0], item[0][1]))
    if max_groups > 0:
        ranked_groups = ranked_groups[:max_groups]
    return [
        (bucket_group_name(facet_type, object_key), recent_claims_for_consolidation(group_claims, messages, per_group_limit))
        for (facet_type, object_key), group_claims in ranked_groups
    ]


StateGroupResult = Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]


@dataclass(frozen=True)
class StateGroupPlan:
    group_name: str
    selected_claims: List[Dict[str, object]]
    source_events: List[GroupMessage]
    system_prompt: str
    user_prompt: str
    prompt_chars: int
    group_hash: str
    children: Tuple["StateGroupPlan", ...] = ()
    resumed_result: Optional[StateGroupResult] = None


def build_state_group_plan(
    domain: str,
    scope: Dict[str, object],
    group_name: str,
    claims: Sequence[Dict[str, object]],
    messages: Sequence[GroupMessage],
    claim_limit: int,
    compact_events: bool,
    max_prompt_chars: int,
    stage_artifact_root: Optional[Path],
    state_stage_hash: Optional[str],
    stage_resume: bool,
) -> StateGroupPlan:
    selected_claims = recent_claims_for_consolidation(claims, messages, claim_limit)
    source_event_ids = {str(claim.get("event_id") or "") for claim in selected_claims}
    source_events = [message for message in messages if message.event_id in source_event_ids]
    system_prompt = state_consolidation_system_prompt()
    user_prompt = state_consolidation_user_prompt(domain, scope, selected_claims, source_events, claim_limit, compact_events)
    prompt_chars = len(user_prompt)
    group_hash = ""
    if stage_artifact_root is not None and state_stage_hash:
        group_hash = state_group_input_hash(
            state_stage_hash=state_stage_hash,
            group_name=group_name,
            selected_claims=selected_claims,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if stage_resume:
            resumed = load_state_group_stage_artifact(
                stage_root=stage_artifact_root,
                scope_id=str(scope.get("scope_id") or ""),
                group_name=group_name,
                expected_state_stage_hash=state_stage_hash,
                expected_group_hash=group_hash,
            )
            if resumed is not None:
                print(f"  statefacet consolidation group={group_name} resumed", flush=True)
                return StateGroupPlan(
                    group_name=group_name,
                    selected_claims=selected_claims,
                    source_events=source_events,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    prompt_chars=prompt_chars,
                    group_hash=group_hash,
                    resumed_result=resumed,
                )
    if max_prompt_chars > 0 and prompt_chars > max_prompt_chars and len(selected_claims) > 1:
        midpoint = max(1, len(selected_claims) // 2)
        split_claim_groups = [selected_claims[:midpoint], selected_claims[midpoint:]]
        print(
            f"  statefacet consolidation group={group_name} prompt_chars={prompt_chars} "
            f"claims={len(selected_claims)} split_groups={len(split_claim_groups)}",
            flush=True,
        )
        children = tuple(
            build_state_group_plan(
                domain,
                scope,
                f"{group_name}#{split_index}",
                split_claims,
                messages,
                len(split_claims),
                compact_events,
                max_prompt_chars,
                stage_artifact_root,
                state_stage_hash,
                stage_resume,
            )
            for split_index, split_claims in enumerate(split_claim_groups, start=1)
        )
        return StateGroupPlan(
            group_name=group_name,
            selected_claims=selected_claims,
            source_events=source_events,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prompt_chars=prompt_chars,
            group_hash=group_hash,
            children=children,
        )
    return StateGroupPlan(
        group_name=group_name,
        selected_claims=selected_claims,
        source_events=source_events,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        prompt_chars=prompt_chars,
        group_hash=group_hash,
    )


def leaf_state_group_plans(plan: StateGroupPlan) -> List[StateGroupPlan]:
    if plan.resumed_result is not None:
        return []
    if not plan.children:
        return [plan]
    leaves: List[StateGroupPlan] = []
    for child in plan.children:
        leaves.extend(leaf_state_group_plans(child))
    return leaves


def run_state_group_leaf(
    client: DomainGraphLLMClient,
    domain: str,
    scope: Dict[str, object],
    scope_number: int,
    plan: StateGroupPlan,
    messages: Sequence[GroupMessage],
    stage_artifact_root: Optional[Path] = None,
    state_stage_hash: Optional[str] = None,
    single_claim_short_circuit: bool = True,
) -> StateGroupResult:
    if single_claim_short_circuit and len(plan.selected_claims) == 1:
        facets = [single_claim_statefacet(scope, plan.selected_claims[0], messages)]
        validation = {
            "group": plan.group_name,
            "short_circuit": "single_claim_statefacet",
            "input_claim_count": 1,
            "selected_claim_count": 1,
            "source_event_count": len(plan.source_events),
            "prompt_chars": plan.prompt_chars,
            "relation_count": 0,
            "rejected_claim_count": 0,
            "state_facet_count": len(facets),
        }
        if stage_artifact_root is not None and state_stage_hash and plan.group_hash:
            path = write_state_group_stage_artifact(
                stage_root=stage_artifact_root,
                domain=domain,
                scope_number=scope_number,
                scope_id=str(scope.get("scope_id") or ""),
                group_name=plan.group_name,
                state_stage_hash=state_stage_hash,
                group_hash=plan.group_hash,
                relations=[],
                rejected_claims=[],
                state_facets=facets,
                validation=validation,
            )
            validation["stage_artifact_path"] = str(path)
            validation["written"] = True
        print(f"  statefacet consolidation group={plan.group_name} single-claim short-circuit", flush=True)
        return [], [], facets, validation
    print(
        f"  statefacet consolidation group={plan.group_name} claims={len(plan.selected_claims)} "
        f"source_events={len(plan.source_events)}",
        flush=True,
    )
    raw = client.complete_json(
        plan.system_prompt,
        plan.user_prompt,
        domain=domain,
        scope_number=scope_number,
        scope_id=str(scope.get("scope_id") or ""),
        stage="offline_statefacet_consolidation",
        shard_name=f"group_{plan.group_name}",
    )
    relations, rejected, facets, validation = normalize_scope_state(raw, scope, plan.selected_claims, messages)
    validation["group"] = plan.group_name
    validation["selected_claim_count"] = len(plan.selected_claims)
    validation["source_event_count"] = len(plan.source_events)
    validation["prompt_chars"] = plan.prompt_chars
    if stage_artifact_root is not None and state_stage_hash and plan.group_hash:
        path = write_state_group_stage_artifact(
            stage_root=stage_artifact_root,
            domain=domain,
            scope_number=scope_number,
            scope_id=str(scope.get("scope_id") or ""),
            group_name=plan.group_name,
            state_stage_hash=state_stage_hash,
            group_hash=plan.group_hash,
            relations=relations,
            rejected_claims=rejected,
            state_facets=facets,
            validation=validation,
        )
        validation["stage_artifact_path"] = str(path)
        validation["written"] = True
    return relations, rejected, facets, validation


def collect_state_group_result(
    plan: StateGroupPlan,
    completed_leaf_results: Mapping[str, StateGroupResult],
    *,
    domain: str,
    scope: Dict[str, object],
    scope_number: int,
    max_prompt_chars: int,
    stage_artifact_root: Optional[Path],
    state_stage_hash: Optional[str],
) -> StateGroupResult:
    if plan.resumed_result is not None:
        return plan.resumed_result
    if not plan.children:
        return completed_leaf_results[plan.group_name]
    combined_relations: List[Dict[str, object]] = []
    combined_rejected: List[Dict[str, object]] = []
    combined_facets: List[Dict[str, object]] = []
    split_validations: List[Dict[str, object]] = []
    for child in plan.children:
        relations, rejected, facets, validation = collect_state_group_result(
            child,
            completed_leaf_results,
            domain=domain,
            scope=scope,
            scope_number=scope_number,
            max_prompt_chars=max_prompt_chars,
            stage_artifact_root=stage_artifact_root,
            state_stage_hash=state_stage_hash,
        )
        combined_relations.extend(relations)
        combined_rejected.extend(rejected)
        combined_facets.extend(facets)
        split_validations.append(validation)
    validation = {
        "group": plan.group_name,
        "split_reason": "prompt_chars",
        "max_prompt_chars": max_prompt_chars,
        "prompt_chars": plan.prompt_chars,
        "split_count": len(split_validations),
        "selected_claim_count": len(plan.selected_claims),
        "source_event_count": len(plan.source_events),
        "relation_count": len(combined_relations),
        "rejected_claim_count": len(combined_rejected),
        "state_facet_count": len(combined_facets),
        "split_validations": split_validations,
    }
    if stage_artifact_root is not None and state_stage_hash and plan.group_hash:
        path = write_state_group_stage_artifact(
            stage_root=stage_artifact_root,
            domain=domain,
            scope_number=scope_number,
            scope_id=str(scope.get("scope_id") or ""),
            group_name=plan.group_name,
            state_stage_hash=state_stage_hash,
            group_hash=plan.group_hash,
            relations=combined_relations,
            rejected_claims=combined_rejected,
            state_facets=combined_facets,
            validation=validation,
        )
        validation["stage_artifact_path"] = str(path)
        validation["written"] = True
    return combined_relations, combined_rejected, combined_facets, validation


def consolidate_llm_state_for_scope(
    client: DomainGraphLLMClient,
    domain: str,
    scope: Dict[str, object],
    scope_number: int,
    claims: Sequence[Dict[str, object]],
    messages: Sequence[GroupMessage],
    claim_limit: int,
    per_group_limit: int,
    max_groups: int,
    statefacet_workers: int,
    compact_events: bool,
    group_max_prompt_chars: int = 0,
    consolidation_mode: str = "grouped",
    bucket_max_groups: int = 0,
    stage_artifact_root: Optional[Path] = None,
    state_stage_hash: Optional[str] = None,
    stage_resume: bool = False,
    single_claim_short_circuit: bool = True,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    all_relations: List[Dict[str, object]] = []
    all_rejected: List[Dict[str, object]] = []
    all_facets: List[Dict[str, object]] = []
    validations: List[Dict[str, object]] = []
    if consolidation_mode == "bucket":
        groups = bucketed_claims_for_consolidation(claims, messages, claim_limit, per_group_limit, bucket_max_groups)
    else:
        groups = grouped_claims_for_consolidation(claims, messages, claim_limit, per_group_limit, max_groups)
    group_plans = [
        (
            group_name,
            build_state_group_plan(
                domain,
                scope,
                group_name,
                group_claims,
                messages,
                per_group_limit,
                compact_events,
                group_max_prompt_chars,
                stage_artifact_root,
                state_stage_hash,
                stage_resume,
            ),
        )
        for group_name, group_claims in groups
    ]
    leaf_plans: List[StateGroupPlan] = []
    for _group_name, plan in group_plans:
        leaf_plans.extend(leaf_state_group_plans(plan))
    worker_count = min(max(1, statefacet_workers), len(leaf_plans)) if leaf_plans else 1

    def run_one(plan: StateGroupPlan) -> StateGroupResult:
        return run_state_group_leaf(
            client,
            domain,
            scope,
            scope_number,
            plan,
            messages,
            stage_artifact_root,
            state_stage_hash,
            single_claim_short_circuit,
        )

    completed_leaf_results: Dict[str, StateGroupResult] = {}
    if not leaf_plans:
        pass
    elif worker_count == 1:
        for plan in leaf_plans:
            completed_leaf_results[plan.group_name] = run_one(plan)
    else:
        print(
            f"  statefacet consolidation parallel workers={worker_count} "
            f"groups={len(groups)} leaf_groups={len(leaf_plans)}",
            flush=True,
        )
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(run_one, plan): plan.group_name
                for plan in leaf_plans
            }
            for future in as_completed(futures):
                group_name = futures[future]
                completed_leaf_results[group_name] = future.result()
                print(f"  statefacet consolidation group={group_name} completed", flush=True)
    group_results = [
        (
            group_name,
            collect_state_group_result(
                plan,
                completed_leaf_results,
                domain=domain,
                scope=scope,
                scope_number=scope_number,
                max_prompt_chars=group_max_prompt_chars,
                stage_artifact_root=stage_artifact_root,
                state_stage_hash=state_stage_hash,
            ),
        )
        for group_name, plan in group_plans
    ]

    for _group_name, (relations, rejected, facets, validation) in group_results:
        all_relations.extend(relations)
        all_rejected.extend(rejected)
        for facet in facets:
            facet = deepcopy(facet)
            facet["facet_id"] = f"facet::{scope.get('scope_id')}::{len(all_facets) + 1}"
            all_facets.append(facet)
        validations.append(validation)
    return all_relations, all_rejected, all_facets, {
        "consolidation_mode": consolidation_mode,
        "group_count": len(groups),
        "leaf_group_count": len(leaf_plans),
        "input_claim_count": len(claims),
        "relation_count": len(all_relations),
        "rejected_claim_count": len(all_rejected),
        "state_facet_count": len(all_facets),
        "group_validations": validations,
    }


def scope_by_key(scopes: Sequence[object]) -> Dict[Tuple[str, str, str, str], object]:
    return {(scope.domain, scope.channel, scope.phase_name, scope.topic): scope for scope in scopes}


def unique_entity_nodes(messages: Iterable[GroupMessage]) -> List[Dict[str, object]]:
    entities: Dict[str, Dict[str, object]] = {}
    for message in messages:
        for entity in mentioned_entities(message):
            entities[str(entity["entity_id"])] = entity
    return sorted(entities.values(), key=lambda item: str(item.get("entity_id") or ""))


def build_domain_graph_trace(
    domain: str,
    messages: Sequence[GroupMessage],
    claims: Sequence[Dict[str, object]],
    relations: Sequence[Dict[str, object]],
    rejected_claims: Sequence[Dict[str, object]],
    state_facets: Sequence[Dict[str, object]],
) -> Tuple[Dict[str, object], Dict[str, int]]:
    scopes = build_scope_inventory(messages)
    scopes_by_key = scope_by_key(scopes)
    claims_by_event: Dict[str, List[Dict[str, object]]] = {}
    for claim in claims:
        claims_by_event.setdefault(str(claim["event_id"]), []).append(claim)

    edges: List[Dict[str, object]] = []
    for message in messages:
        scope = scopes_by_key.get(message.scope_key())
        if scope is not None:
            edges.append(
                {
                    "type": "IN_SCOPE",
                    "from": message.event_id,
                    "to": scope.scope_id,
                    "reason": "message metadata assigns this event to the domain corpus scope",
                }
            )
        for entity in mentioned_entities(message):
            edges.append(
                {
                    "type": "MENTIONS",
                    "from": message.event_id,
                    "to": entity["entity_id"],
                    "reason": "visible message metadata mentions this entity",
                }
            )
        for claim in claims_by_event.get(message.event_id, []):
            edges.append(
                {
                    "type": "ASSERTS",
                    "from": message.event_id,
                    "to": claim["claim_id"],
                    "reason": "offline corpus graph claim extracted from the event text",
                }
            )
    claim_ids = {str(claim.get("claim_id") or "") for claim in claims}
    scope_ids = {scope.scope_id for scope in scopes}
    for relation in relations:
        relation_type = str(relation.get("type") or "").upper()
        source = str(relation.get("from") or "")
        target = str(relation.get("to") or "")
        if relation_type in RELATION_TYPES and source in claim_ids and target in claim_ids:
            edges.append(
                {
                    "type": relation_type,
                    "from": source,
                    "to": target,
                    "evidence_event_ids": relation.get("evidence_event_ids", []),
                    "reason": relation.get("reason", ""),
                }
            )
    for facet in state_facets:
        facet_id = str(facet.get("facet_id") or "")
        for claim_id in facet.get("support_claims", []):
            if str(claim_id) in claim_ids:
                edges.append({"type": "SUPPORTS", "from": str(claim_id), "to": facet_id})
        current_after = facet.get("current_after")
        if current_after:
            edges.append({"type": "CURRENT_AFTER", "from": facet_id, "to": f"time::{current_after}"})
        scope_id = str(facet.get("scope_id") or "")
        if scope_id in scope_ids:
            edges.append({"type": "CURRENT_STATE_OF", "from": facet_id, "to": scope_id})

    graph_time_nodes = time_nodes(messages)
    known_time_ids = {str(node.get("time_id") or "") for node in graph_time_nodes}
    for facet in state_facets:
        current_after = str(facet.get("current_after") or "")
        if not current_after:
            continue
        current_after_id = time_id(current_after)
        if current_after_id in known_time_ids:
            continue
        known_time_ids.add(current_after_id)
        graph_time_nodes.append(time_node(current_after, "state_facet_current_after"))

    return (
        {
            "schema": schema_payload(),
            "nodes": {
                "episode_events": [event_node(message) for message in messages],
                "mentioned_entity_scopes": [scope_node(scope) for scope in scopes] + unique_entity_nodes(messages),
                "times": graph_time_nodes,
                "claims": list(claims),
                "state_facets": list(state_facets),
            },
            "edges": edges,
        },
        {
            "scope_count": len(scopes),
            "event_count": len(messages),
            "entity_count": len(unique_entity_nodes(messages)),
            "time_count": len(graph_time_nodes),
            "claim_count": len(claims),
            "events_with_claims": len({str(claim.get("event_id") or "") for claim in claims}),
            "claimless_event_count": len(messages)
            - len({str(claim.get("event_id") or "") for claim in claims}),
            "relation_count": len(relations),
            "rejected_claim_count": len(rejected_claims),
            "state_facet_count": len(state_facets),
        },
    )


def build_manifest(
    domain: str,
    args: argparse.Namespace,
    stats: Dict[str, int],
    *,
    build_unit: str = "domain_corpus",
    graph_id: Optional[str] = None,
    is_partial: Optional[bool] = None,
    build_config_extra: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    partial = bool(args.scope_offset or args.scope_limit or args.event_limit) if is_partial is None else is_partial
    if args.claim_mode == "llm":
        provider_values = {str(args.claim_provider), str(args.statefacet_provider)}
        model_values = {str(args.claim_model), str(args.statefacet_model)}
        graph_provider = provider_values.pop() if len(provider_values) == 1 else "mixed"
        graph_model = model_values.pop() if len(model_values) == 1 else "mixed"
    else:
        graph_provider = "none"
        graph_model = args.claim_mode
    build_config = {
        "domains": list(args.domains),
        "event_limit": args.event_limit,
        "scope_offset": args.scope_offset,
        "scope_limit": args.scope_limit,
        "message_chunk_size": args.message_chunk_size,
        "message_chunk_max_chars": args.message_chunk_max_chars,
        "max_claims_per_event": args.max_claims_per_event,
        "claim_workers": args.claim_workers,
        "statefacet_workers": args.statefacet_workers,
        "scope_workers": args.scope_workers,
        "write_scope_artifacts": not args.no_scope_artifacts,
        "stage_resume": args.stage_resume,
        "cache_layout": "sharded_by_domain_scope_stage_chunk",
        "stage_checkpoint_layout": "_scope_stage_artifacts/domain/scope/stage.json",
        "stage_checkpoint_schema": STAGE_ARTIFACT_SCHEMA_VERSION,
        "legacy_cache_fallback": True,
        "claim_input_filter": args.claim_input_filter,
        "compact_llm_events": args.compact_llm_events,
        "claim_coverage_audit": args.claim_coverage_audit,
        "claim_coverage_retry_chunk_size": args.claim_coverage_retry_chunk_size,
        "claim_coverage_backfill": args.claim_coverage_backfill,
        "consolidation_claim_limit": args.consolidation_claim_limit,
        "statefacet_claim_limit_per_group": args.statefacet_claim_limit_per_group,
        "statefacet_max_groups": args.statefacet_max_groups,
        "statefacet_consolidation_mode": args.statefacet_consolidation_mode,
        "statefacet_bucket_max_groups": args.statefacet_bucket_max_groups,
        "statefacet_group_max_prompt_chars": args.statefacet_group_max_prompt_chars,
        "single_claim_statefacet_short_circuit": args.single_claim_statefacet_short_circuit,
        "claim_mode": args.claim_mode,
        "provider": args.provider if args.claim_mode == "llm" else None,
        "model": args.model,
        "claim_provider": args.claim_provider if args.claim_mode == "llm" else None,
        "claim_model": args.claim_model if args.claim_mode == "llm" else None,
        "claim_cache": args.claim_cache if args.claim_mode == "llm" else None,
        "statefacet_provider": args.statefacet_provider if args.claim_mode == "llm" else None,
        "statefacet_model": args.statefacet_model if args.claim_mode == "llm" else None,
        "statefacet_cache": args.statefacet_cache if args.claim_mode == "llm" else None,
    }
    if build_config_extra:
        build_config.update(dict(build_config_extra))
    return {
        "benchmark": "GroupMemBench",
        "graph_id": graph_id or f"GroupMemBench:{domain}:domain_corpus",
        "build_unit": build_unit,
        "protocol": "offline_domain_graph",
        "domain": domain,
        "source_corpus": str(conversation_path(domain)),
        "question_conditioned": False,
        "question_seen": False,
        "gold_seen": False,
        "graph_provider": graph_provider,
        "graph_model": graph_model,
        "claim_mode": args.claim_mode,
        "is_partial": partial,
        "build_config": build_config,
        "domain_stats": dict(stats),
        "leakage_boundary": {
            "question_text_present": False,
            "answer_reference_present": False,
            "judge_metadata_present": False,
        },
    }


def select_messages(domain: str, args: argparse.Namespace) -> List[GroupMessage]:
    all_messages = load_domain_messages(domain)
    if args.scope_offset > 0 or args.scope_limit > 0:
        scope_start = max(0, args.scope_offset)
        scope_end = None if args.scope_limit <= 0 else scope_start + args.scope_limit
        selected_scope_ids = {
            scope.scope_id
            for scope in build_scope_inventory(all_messages)[scope_start:scope_end]
        }
        messages = [
            message
            for message in all_messages
            if scope_id_for(message.domain, message.channel, message.phase_name, message.topic) in selected_scope_ids
        ]
    else:
        messages = all_messages
    if args.event_limit > 0:
        messages = messages[: args.event_limit]
    return messages


def graph_locked_raw(
    *,
    domain: str,
    messages: Sequence[GroupMessage],
    graph_trace: Mapping[str, object],
    relations: Sequence[Mapping[str, object]],
    rejected_claims: Sequence[Mapping[str, object]],
    state_facets: Sequence[Mapping[str, object]],
    stage_trace: Mapping[str, object],
    target_scope_id: Optional[str] = None,
    pipeline: str = "offline_domain_graph_builder",
) -> Dict[str, object]:
    return {
        "state_packet": {
            "target_scope_id": target_scope_id,
            "candidate_events": [message.event_id for message in messages],
            "claims": graph_trace["nodes"]["claims"],
            "validity_decisions": {},
            "relations": list(relations),
            "rejected_claims": list(rejected_claims),
            "state_facets": list(state_facets),
        },
        "graph_trace": graph_trace,
        "pipeline_trace": {
            "pipeline": pipeline,
            "build_unit": "domain_scope" if target_scope_id else "domain_corpus",
            "domain": domain,
            "target_scope_id": target_scope_id,
            "question_conditioned": False,
            "question_seen": False,
            "gold_seen": False,
            "stage_trace": dict(stage_trace),
        },
    }


def scope_artifact_dir(output_dir: Path, domain: str, scope_number: int, scope_id: str) -> Path:
    return output_dir / "_scope_artifacts" / safe_path_part(domain) / scope_dir_name(scope_number, scope_id)


def scope_stage_artifact_dir(output_dir: Path, domain: str, scope_number: int, scope_id: str) -> Path:
    return output_dir / "_scope_stage_artifacts" / safe_path_part(domain) / scope_dir_name(scope_number, scope_id)


def claim_stage_artifact_path(output_dir: Path, domain: str, scope_number: int, scope_id: str) -> Path:
    return scope_stage_artifact_dir(output_dir, domain, scope_number, scope_id) / "claim_extraction.json"


def state_group_artifact_path(stage_root: Path, group_name: str) -> Path:
    return stage_root / "statefacet_groups" / f"{bounded_safe_part(group_name)}.json"


def write_claim_stage_artifact(
    *,
    output_dir: Path,
    domain: str,
    scope_number: int,
    scope_id: str,
    scope_stage_hash: str,
    claim_stage_hash: str,
    event_count: int,
    claims: Sequence[Mapping[str, object]],
    rejected_claims: Sequence[Mapping[str, object]],
    validations: Sequence[Mapping[str, object]],
) -> Path:
    path = claim_stage_artifact_path(output_dir, domain, scope_number, scope_id)
    atomic_write_json(
        path,
        {
            "artifact_schema": STAGE_ARTIFACT_SCHEMA_VERSION,
            "stage": "claim_extraction",
            "domain": domain,
            "scope_number": scope_number,
            "scope_id": scope_id,
            "scope_stage_input_hash": scope_stage_hash,
            "claim_stage_input_hash": claim_stage_hash,
            "event_count": event_count,
            "claim_count": len(claims),
            "rejected_claim_count": len(rejected_claims),
            "claims": json_safe_rows(claims),
            "rejected_claims": json_safe_rows(rejected_claims),
            "validations": json_safe_rows(validations),
        },
    )
    return path


def load_claim_stage_artifact(
    *,
    output_dir: Path,
    domain: str,
    scope_number: int,
    scope_id: str,
    expected_claim_stage_hash: str,
) -> Optional[Dict[str, object]]:
    path = claim_stage_artifact_path(output_dir, domain, scope_number, scope_id)
    payload = load_json_object(path)
    if not payload:
        return None
    if payload.get("artifact_schema") != STAGE_ARTIFACT_SCHEMA_VERSION:
        return None
    if payload.get("stage") != "claim_extraction":
        return None
    if str(payload.get("scope_id") or "") != scope_id:
        return None
    if str(payload.get("claim_stage_input_hash") or "") != expected_claim_stage_hash:
        print(f"stage resume skip / {scope_id}: claim stage hash mismatch", flush=True)
        return None
    claims = payload.get("claims", [])
    rejected = payload.get("rejected_claims", [])
    validations = payload.get("validations", [])
    if not all(isinstance(value, list) for value in (claims, rejected, validations)):
        return None
    return {
        "claims": [dict(item) for item in claims if isinstance(item, dict)],
        "claim_rejected": [dict(item) for item in rejected if isinstance(item, dict)],
        "claim_validations": [dict(item) for item in validations if isinstance(item, dict)],
        "claim_stage_artifact": {
            "artifact_path": str(path),
            "claim_stage_input_hash": expected_claim_stage_hash,
            "resumed": True,
        },
    }


def state_group_input_hash(
    *,
    state_stage_hash: str,
    group_name: str,
    selected_claims: Sequence[Mapping[str, object]],
    system_prompt: str,
    user_prompt: str,
) -> str:
    return stable_hash(
        {
            "version": f"{STAGE_INPUT_HASH_VERSION}:state_group",
            "state_stage_input_hash": state_stage_hash,
            "group_name": group_name,
            "selected_claims_hash": claims_hash(selected_claims),
            "system_prompt_hash": text_hash(system_prompt),
            "user_prompt_hash": text_hash(user_prompt),
        }
    )


def write_state_group_stage_artifact(
    *,
    stage_root: Path,
    domain: str,
    scope_number: int,
    scope_id: str,
    group_name: str,
    state_stage_hash: str,
    group_hash: str,
    relations: Sequence[Mapping[str, object]],
    rejected_claims: Sequence[Mapping[str, object]],
    state_facets: Sequence[Mapping[str, object]],
    validation: Mapping[str, object],
) -> Path:
    path = state_group_artifact_path(stage_root, group_name)
    atomic_write_json(
        path,
        {
            "artifact_schema": STAGE_ARTIFACT_SCHEMA_VERSION,
            "stage": "statefacet_group",
            "domain": domain,
            "scope_number": scope_number,
            "scope_id": scope_id,
            "group_name": group_name,
            "state_stage_input_hash": state_stage_hash,
            "group_input_hash": group_hash,
            "relation_count": len(relations),
            "rejected_claim_count": len(rejected_claims),
            "state_facet_count": len(state_facets),
            "relations": json_safe_rows(relations),
            "rejected_claims": json_safe_rows(rejected_claims),
            "state_facets": json_safe_rows(state_facets),
            "validation": dict(validation),
        },
    )
    return path


def load_state_group_stage_artifact(
    *,
    stage_root: Path,
    scope_id: str,
    group_name: str,
    expected_state_stage_hash: str,
    expected_group_hash: str,
) -> Optional[Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]]:
    path = state_group_artifact_path(stage_root, group_name)
    payload = load_json_object(path)
    if not payload:
        return None
    if payload.get("artifact_schema") != STAGE_ARTIFACT_SCHEMA_VERSION:
        return None
    if payload.get("stage") != "statefacet_group":
        return None
    if str(payload.get("scope_id") or "") != scope_id:
        return None
    if str(payload.get("state_stage_input_hash") or "") != expected_state_stage_hash:
        print(f"stage resume skip / {scope_id}: state group {group_name} stage hash mismatch", flush=True)
        return None
    if str(payload.get("group_input_hash") or "") != expected_group_hash:
        print(f"stage resume skip / {scope_id}: state group {group_name} input hash mismatch", flush=True)
        return None
    relations = payload.get("relations", [])
    rejected = payload.get("rejected_claims", [])
    facets = payload.get("state_facets", [])
    validation = payload.get("validation", {})
    if not all(isinstance(value, list) for value in (relations, rejected, facets)):
        return None
    if not isinstance(validation, dict):
        validation = {}
    validation = dict(validation)
    validation["stage_artifact_path"] = str(path)
    validation["resumed"] = True
    return (
        [dict(item) for item in relations if isinstance(item, dict)],
        [dict(item) for item in rejected if isinstance(item, dict)],
        [dict(item) for item in facets if isinstance(item, dict)],
        validation,
    )


def write_scope_artifact(
    *,
    output_dir: Path,
    domain: str,
    args: argparse.Namespace,
    scope_number: int,
    scope_id: str,
    scope_messages: Sequence[GroupMessage],
    scope_claims: Sequence[Mapping[str, object]],
    scope_relations: Sequence[Mapping[str, object]],
    scope_rejected: Sequence[Mapping[str, object]],
    state_rejected: Sequence[Mapping[str, object]],
    scope_facets: Sequence[Mapping[str, object]],
    claim_validations: Sequence[Mapping[str, object]],
    state_validation: Mapping[str, object],
    stage_input_hash: Optional[str] = None,
) -> Dict[str, object]:
    rejected_claims = [*scope_rejected, *state_rejected]
    graph_trace, stats = build_domain_graph_trace(
        domain,
        scope_messages,
        list(scope_claims),
        list(scope_relations),
        list(rejected_claims),
        list(scope_facets),
    )
    stage_trace = {
        "claim_extraction": [
            {
                "scope_id": scope_id,
                "stage_input_hash": stage_input_hash,
                "event_count": len(scope_messages),
                "claim_count": len(scope_claims),
                "rejected_claim_count": len(scope_rejected),
                "validations": list(claim_validations),
            }
        ],
        "state_consolidation": [{"scope_id": scope_id, "stage_input_hash": stage_input_hash, **dict(state_validation)}],
    }
    locked_raw = graph_locked_raw(
        domain=domain,
        messages=scope_messages,
        graph_trace=graph_trace,
        relations=scope_relations,
        rejected_claims=rejected_claims,
        state_facets=scope_facets,
        stage_trace=stage_trace,
        target_scope_id=scope_id,
        pipeline="offline_domain_graph_scope_checkpoint",
    )
    artifact = write_graph_artifact(
        scope_artifact_dir(output_dir, domain, scope_number, scope_id),
        build_manifest(
            domain,
            args,
            stats,
            build_unit="domain_scope",
            graph_id=f"GroupMemBench:{domain}:domain_scope:{scope_number:03d}",
            is_partial=True,
            build_config_extra={
                "scope_checkpoint": True,
                "scope_number": scope_number,
                "scope_id": scope_id,
                "stage_input_hash": stage_input_hash,
                "stage_input_hash_version": STAGE_INPUT_HASH_VERSION,
            },
        ),
        locked_raw,
    )
    return {
        "artifact_dir": str(artifact.root),
        "node_count": len(artifact.nodes),
        "edge_count": len(artifact.edges),
        "graph_warnings": artifact.manifest.get("graph_warnings", []),
        "domain_stats": stats,
        "stage_input_hash": stage_input_hash,
    }


def artifact_stage_input_hash(artifact_manifest: Mapping[str, object], locked_raw: Mapping[str, object]) -> str:
    build_config = artifact_manifest.get("build_config")
    if isinstance(build_config, dict) and build_config.get("stage_input_hash"):
        return str(build_config["stage_input_hash"])
    pipeline_trace = locked_raw.get("pipeline_trace")
    if not isinstance(pipeline_trace, dict):
        return ""
    stage_trace = pipeline_trace.get("stage_trace")
    if not isinstance(stage_trace, dict):
        return ""
    for key in ("claim_extraction", "state_consolidation"):
        rows = stage_trace.get(key)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and rows[0].get("stage_input_hash"):
            return str(rows[0]["stage_input_hash"])
    return ""


def split_rejected_claims(
    rejected_claims: Sequence[Mapping[str, object]],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    claim_rejected: List[Dict[str, object]] = []
    state_rejected: List[Dict[str, object]] = []
    for item in rejected_claims:
        row = dict(item)
        if str(row.get("stage") or "") == "offline_statefacet_consolidation":
            state_rejected.append(row)
        else:
            claim_rejected.append(row)
    return claim_rejected, state_rejected


def load_scope_resume_artifact(
    *,
    output_dir: Path,
    domain: str,
    scope_number: int,
    scope_id: str,
    expected_stage_input_hash: str,
) -> Optional[Dict[str, object]]:
    root = scope_artifact_dir(output_dir, domain, scope_number, scope_id)
    if not root.exists():
        return None
    try:
        artifact = load_graph_artifact(root)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"stage resume skip / {scope_id}: cannot load checkpoint {root}: {exc}", flush=True)
        return None
    stored_hash = artifact_stage_input_hash(artifact.manifest, artifact.locked_raw)
    if stored_hash != expected_stage_input_hash:
        if stored_hash:
            print(f"stage resume skip / {scope_id}: checkpoint hash mismatch", flush=True)
        return None
    packet = artifact.locked_raw.get("state_packet")
    if not isinstance(packet, dict):
        return None
    if str(packet.get("target_scope_id") or "") != scope_id:
        return None
    claims = packet.get("claims", [])
    relations = packet.get("relations", [])
    rejected = packet.get("rejected_claims", [])
    state_facets = packet.get("state_facets", [])
    if not all(isinstance(value, list) for value in (claims, relations, rejected, state_facets)):
        return None
    claim_rejected, state_rejected = split_rejected_claims(rejected)  # type: ignore[arg-type]

    pipeline_trace = artifact.locked_raw.get("pipeline_trace")
    stage_trace = pipeline_trace.get("stage_trace") if isinstance(pipeline_trace, dict) else {}
    claim_rows = stage_trace.get("claim_extraction") if isinstance(stage_trace, dict) else []
    state_rows = stage_trace.get("state_consolidation") if isinstance(stage_trace, dict) else []
    claim_validations: List[Dict[str, object]] = []
    if isinstance(claim_rows, list) and claim_rows and isinstance(claim_rows[0], dict):
        raw_validations = claim_rows[0].get("validations", [])
        if isinstance(raw_validations, list):
            claim_validations = [dict(item) for item in raw_validations if isinstance(item, dict)]
    if isinstance(state_rows, list) and state_rows and isinstance(state_rows[0], dict):
        state_validation = {key: value for key, value in state_rows[0].items() if key != "scope_id"}
    else:
        state_validation = {
            "group_count": 0,
            "input_claim_count": len(claims),
            "relation_count": len(relations),
            "rejected_claim_count": len(state_rejected),
            "state_facet_count": len(state_facets),
            "group_validations": [],
        }

    return {
        "claims": [dict(item) for item in claims if isinstance(item, dict)],
        "relations": [dict(item) for item in relations if isinstance(item, dict)],
        "claim_rejected": claim_rejected,
        "state_rejected": state_rejected,
        "state_facets": [dict(item) for item in state_facets if isinstance(item, dict)],
        "claim_validations": claim_validations,
        "state_validation": state_validation,
        "scope_artifact": {
            "artifact_dir": str(artifact.root),
            "node_count": len(artifact.nodes),
            "edge_count": len(artifact.edges),
            "graph_warnings": artifact.manifest.get("graph_warnings", []),
            "domain_stats": artifact.manifest.get("domain_stats", {}),
            "stage_input_hash": expected_stage_input_hash,
            "resumed": True,
        },
    }


def build_llm_graph_components(
    claim_client: DomainGraphLLMClient,
    state_client: DomainGraphLLMClient,
    domain: str,
    messages: Sequence[GroupMessage],
    args: argparse.Namespace,
    output_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    scopes = build_scope_inventory(messages)
    claims: List[Dict[str, object]] = []
    relations: List[Dict[str, object]] = []
    rejected_claims: List[Dict[str, object]] = []
    state_facets: List[Dict[str, object]] = []
    stage_trace = {"claim_extraction": [], "state_consolidation": [], "scope_artifacts": []}

    def build_one_scope(scope_index: int, scope: object) -> Dict[str, object]:
        scope_number = args.scope_offset + scope_index
        scope_messages = [
            message
            for message in messages
            if (message.domain, message.channel, message.phase_name, message.topic)
            == (scope.domain, scope.channel, scope.phase_name, scope.topic)
        ]
        scope_dict = scope.as_dict()
        stage_input_hash = scope_stage_input_hash(
            domain=domain,
            scope=scope_dict,
            messages=scope_messages,
            args=args,
            claim_client=claim_client,
            state_client=state_client,
        )
        claim_input_hash = claim_stage_input_hash(
            domain=domain,
            scope=scope_dict,
            messages=scope_messages,
            args=args,
            client=claim_client,
        )
        resume_enabled = stage_resume_enabled(args, output_dir)
        stage_artifact_root = (
            scope_stage_artifact_dir(output_dir, domain, scope_number, scope.scope_id)
            if resume_enabled and output_dir is not None
            else None
        )
        if resume_enabled and output_dir is not None:
            resumed = load_scope_resume_artifact(
                output_dir=output_dir,
                domain=domain,
                scope_number=scope_number,
                scope_id=scope.scope_id,
                expected_stage_input_hash=stage_input_hash,
            )
            if resumed is not None:
                print(
                    f"llm graph stage / {domain} scope {scope_number:03d} resumed "
                    f"events={len(scope_messages)} scope_id={scope.scope_id}",
                    flush=True,
                )
                return {
                    "scope_index": scope_index,
                    "scope_number": scope_number,
                    "scope_id": scope.scope_id,
                    "event_count": len(scope_messages),
                    **resumed,
                }
        print(
            f"llm graph stage / {domain} scope {scope_index}/{len(scopes)} "
            f"events={len(scope_messages)} scope_id={scope.scope_id}",
            flush=True,
        )
        claim_stage_artifact = None
        claim_stage = None
        if resume_enabled and output_dir is not None:
            claim_stage = load_claim_stage_artifact(
                output_dir=output_dir,
                domain=domain,
                scope_number=scope_number,
                scope_id=scope.scope_id,
                expected_claim_stage_hash=claim_input_hash,
            )
        if claim_stage is not None:
            scope_claims = claim_stage["claims"]
            scope_rejected = claim_stage["claim_rejected"]
            claim_validations = claim_stage["claim_validations"]
            claim_stage_artifact = claim_stage.get("claim_stage_artifact")
            print(
                f"llm graph stage / {domain} scope {scope_number:03d} claim extraction resumed "
                f"claims={len(scope_claims)} rejected={len(scope_rejected)}",
                flush=True,
            )
        else:
            scope_claims, scope_rejected, claim_validations = extract_llm_claims_for_scope(
                claim_client,
                domain,
                scope_dict,
                scope_number,
                scope_messages,
                args.message_chunk_size,
                args.message_chunk_max_chars,
                args.max_claims_per_event,
                args.claim_coverage_audit,
                args.claim_coverage_retry_chunk_size,
                args.claim_coverage_backfill,
                args.claim_workers,
                args.claim_input_filter,
                args.compact_llm_events,
            )
            if resume_enabled and output_dir is not None:
                claim_path = write_claim_stage_artifact(
                    output_dir=output_dir,
                    domain=domain,
                    scope_number=scope_number,
                    scope_id=scope.scope_id,
                    scope_stage_hash=stage_input_hash,
                    claim_stage_hash=claim_input_hash,
                    event_count=len(scope_messages),
                    claims=scope_claims,
                    rejected_claims=scope_rejected,
                    validations=claim_validations,
                )
                claim_stage_artifact = {
                    "artifact_path": str(claim_path),
                    "claim_stage_input_hash": claim_input_hash,
                    "written": True,
                }
                print(
                    f"llm graph stage / {domain} scope {scope_number:03d} claim checkpoint "
                    f"artifact={claim_path}",
                    flush=True,
                )
        state_input_hash = state_stage_input_hash(
            domain=domain,
            scope=scope_dict,
            messages=scope_messages,
            claims=scope_claims,
            args=args,
            client=state_client,
        )
        scope_relations, state_rejected, scope_facets, state_validation = consolidate_llm_state_for_scope(
            state_client,
            domain,
            scope_dict,
            scope_number,
            scope_claims,
            scope_messages,
            args.consolidation_claim_limit,
            args.statefacet_claim_limit_per_group,
            args.statefacet_max_groups,
            args.statefacet_workers,
            args.compact_llm_events,
            args.statefacet_group_max_prompt_chars,
            args.statefacet_consolidation_mode,
            args.statefacet_bucket_max_groups,
            stage_artifact_root,
            state_input_hash,
            resume_enabled,
            args.single_claim_statefacet_short_circuit,
        )
        scope_artifact = None
        if output_dir is not None and not args.no_scope_artifacts:
            scope_artifact = write_scope_artifact(
                output_dir=output_dir,
                domain=domain,
                args=args,
                scope_number=scope_number,
                scope_id=scope.scope_id,
                scope_messages=scope_messages,
                scope_claims=scope_claims,
                scope_relations=scope_relations,
                scope_rejected=scope_rejected,
                state_rejected=state_rejected,
                scope_facets=scope_facets,
                claim_validations=claim_validations,
                state_validation=state_validation,
                stage_input_hash=stage_input_hash,
            )
            print(
                f"llm graph stage / {domain} scope {scope_number:03d} checkpoint "
                f"artifact={scope_artifact['artifact_dir']}",
                flush=True,
            )
        return {
            "scope_index": scope_index,
            "scope_number": scope_number,
            "scope_id": scope.scope_id,
            "event_count": len(scope_messages),
            "claims": scope_claims,
            "relations": scope_relations,
            "claim_rejected": scope_rejected,
            "state_rejected": state_rejected,
            "state_facets": scope_facets,
            "claim_validations": claim_validations,
            "state_validation": state_validation,
            "scope_artifact": scope_artifact,
            "claim_stage_artifact": claim_stage_artifact,
        }

    worker_count = min(max(1, args.scope_workers), len(scopes)) if scopes else 1
    if worker_count == 1:
        scope_results = [build_one_scope(scope_index, scope) for scope_index, scope in enumerate(scopes, start=1)]
    else:
        print(f"llm graph stage / {domain} parallel scope workers={worker_count} scopes={len(scopes)}", flush=True)
        scope_results = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(build_one_scope, scope_index, scope): scope_index
                for scope_index, scope in enumerate(scopes, start=1)
            }
            for future in as_completed(futures):
                scope_index = futures[future]
                result = future.result()
                print(
                    f"llm graph stage / {domain} scope {scope_index}/{len(scopes)} completed "
                    f"claims={len(result['claims'])} state_facets={len(result['state_facets'])}",
                    flush=True,
                )
                scope_results.append(result)
        scope_results.sort(key=lambda item: int(item["scope_index"]))

    for result in scope_results:
        scope_claims = result["claims"]
        scope_relations = result["relations"]
        scope_rejected = result["claim_rejected"]
        state_rejected = result["state_rejected"]
        scope_facets = result["state_facets"]
        claims.extend(scope_claims)
        relations.extend(scope_relations)
        rejected_claims.extend(scope_rejected)
        rejected_claims.extend(state_rejected)
        state_facets.extend(scope_facets)
        stage_trace["claim_extraction"].append(
            {
                "scope_id": result["scope_id"],
                "event_count": result["event_count"],
                "claim_count": len(scope_claims),
                "rejected_claim_count": len(scope_rejected),
                "validations": result["claim_validations"],
                "stage_artifact": result.get("claim_stage_artifact"),
            }
        )
        stage_trace["state_consolidation"].append({"scope_id": result["scope_id"], **result["state_validation"]})
        if result.get("scope_artifact"):
            stage_trace["scope_artifacts"].append(
                {
                    "scope_id": result["scope_id"],
                    "scope_number": result["scope_number"],
                    **result["scope_artifact"],
                }
            )
    return claims, relations, rejected_claims, state_facets, stage_trace


def build_graph_components(
    claim_client: Optional[DomainGraphLLMClient],
    state_client: Optional[DomainGraphLLMClient],
    domain: str,
    messages: Sequence[GroupMessage],
    args: argparse.Namespace,
    output_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    if args.claim_mode == "llm":
        if claim_client is None or state_client is None:
            raise ValueError("LLM claim_mode requires configured claim and StateFacet LLM clients")
        return build_llm_graph_components(claim_client, state_client, domain, messages, args, output_dir)
    claims, stats = claims_for_messages(messages, args.claim_mode, args.max_claims_per_event)
    return claims, [], [], [], {"heuristic_claim_stats": stats}


def build_domain_artifact(
    domain: str,
    args: argparse.Namespace,
    output_dir: Path,
    claim_client: Optional[DomainGraphLLMClient],
    state_client: Optional[DomainGraphLLMClient],
) -> Dict[str, object]:
    messages = select_messages(domain, args)
    claims, relations, rejected_claims, state_facets, stage_trace = build_graph_components(
        claim_client,
        state_client,
        domain,
        messages,
        args,
        output_dir,
    )
    graph_trace, stats = build_domain_graph_trace(domain, messages, claims, relations, rejected_claims, state_facets)
    locked_raw = graph_locked_raw(
        domain=domain,
        messages=messages,
        graph_trace=graph_trace,
        relations=relations,
        rejected_claims=rejected_claims,
        state_facets=state_facets,
        stage_trace=stage_trace,
    )
    artifact = write_graph_artifact(domain_graph_artifact_dir(output_dir, domain), build_manifest(domain, args, stats), locked_raw)
    type_counts = Counter(str(node.get("node_type") or "") for node in artifact.nodes)
    edge_counts = Counter(str(edge.get("type") or "") for edge in artifact.edges)
    return {
        "domain": domain,
        "artifact_dir": str(artifact.root),
        "node_count": len(artifact.nodes),
        "edge_count": len(artifact.edges),
        "node_type_counts": dict(sorted(type_counts.items())),
        "edge_type_counts": dict(sorted(edge_counts.items())),
        "graph_warnings": artifact.manifest.get("graph_warnings", []),
        "domain_stats": stats,
    }


def write_summary(output_dir: Path, summary: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "build_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {path}")


def print_summary(summary: Dict[str, object]) -> None:
    print("GroupMemBench domain graph builder")
    print(f"domains={summary['domains']} output_dir={summary['output_dir']}")
    for artifact in summary["artifacts"]:
        print(
            f"{artifact['domain']}: nodes={artifact['node_count']} edges={artifact['edge_count']} "
            f"warnings={len(artifact['graph_warnings'])} artifact={artifact['artifact_dir']}"
        )


def configure_stage_client(
    args: argparse.Namespace,
    *,
    stage_name: str,
    provider_attr: str,
    model_attr: str,
    cache_attr: str,
) -> DomainGraphLLMClient:
    provider = getattr(args, provider_attr) or args.provider
    api_key, model, api_base = provider_config(provider)
    model_override = getattr(args, model_attr) or args.model
    if model_override:
        model = model_override
    cache_path = str(getattr(args, cache_attr) or args.cache)
    setattr(args, provider_attr, provider)
    setattr(args, model_attr, model)
    setattr(args, cache_attr, cache_path)
    print(f"configured {stage_name} llm / provider={provider} model={model} cache={cache_path}", flush=True)
    return DomainGraphLLMClient(
        provider=provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(cache_path),
        use_cache=not args.no_cache,
    )


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    claim_client: Optional[DomainGraphLLMClient] = None
    state_client: Optional[DomainGraphLLMClient] = None
    if args.claim_mode == "llm":
        load_dotenv()
        try:
            claim_client = configure_stage_client(
                args,
                stage_name="claim_extraction",
                provider_attr="claim_provider",
                model_attr="claim_model",
                cache_attr="claim_cache",
            )
            state_client = configure_stage_client(
                args,
                stage_name="statefacet_consolidation",
                provider_attr="statefacet_provider",
                model_attr="statefacet_model",
                cache_attr="statefacet_cache",
            )
        except RuntimeError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            return 2
    artifacts = []
    try:
        for domain in args.domains:
            print(f"building offline domain graph / {domain}", flush=True)
            artifacts.append(build_domain_artifact(domain, args, output_dir, claim_client, state_client))
    except LLMRequestError as exc:
        print("\nLLM request failed during domain graph build.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("\nLLM output failed domain graph JSON validation.", file=sys.stderr)
        print(f"claim_provider: {args.claim_provider}", file=sys.stderr)
        print(f"claim_model: {args.claim_model}", file=sys.stderr)
        print(f"statefacet_provider: {args.statefacet_provider}", file=sys.stderr)
        print(f"statefacet_model: {args.statefacet_model}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    summary = {
        "benchmark": "GroupMemBench",
        "variant": "offline_domain_graph",
        "domains": list(args.domains),
        "output_dir": str(output_dir),
        "artifacts": artifacts,
    }
    print_summary(summary)
    write_summary(output_dir, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

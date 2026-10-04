from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from sts.config import ExperimentConfig

from .query_parser import QueryPlan


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "these", "this", "to", "was",
    "were", "what", "when", "where", "which", "who", "with", "provide", "list",
}
TEMPORAL_KEYWORDS = {
    "when", "what time", "what date", "which year", "which month",
    "which day", "how long", "before", "after", "during", "recently",
    "last", "next", "ago", "date", "time", "year", "month", "week", "day",
}
TEMPORAL_PROGRESSION_KEYWORDS = {
    "change", "changed", "changing", "progress", "progressed", "develop",
    "developed", "evolve", "evolved", "over time", "timeline", "sequence",
}


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if token not in STOP and len(token) > 1
    ]


def _join(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _scope_text(scope: dict) -> str:
    return " ".join(
        _join(scope.get(field))
        for field in (
            "title", "key_entities", "event_types", "key_locations",
            "keywords", "summary",
        )
    )


def _claim_text(claim: dict) -> str:
    return " ".join(
        _join(claim.get(field))
        for field in (
            "content", "claim_type", "entities", "temporal", "spatial",
            "evidence", "query_patterns", "keywords",
        )
    )


def _time(item: dict) -> datetime:
    raw = item.get("timestamp")
    if not raw:
        return datetime.min
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)


def should_expand_same_time_group(question: str) -> bool:
    normalized = question.casefold()
    return any(
        keyword in normalized
        for keyword in (
            TEMPORAL_KEYWORDS | TEMPORAL_PROGRESSION_KEYWORDS
        )
    )


def expand_same_time_group_claims(
    seed_claim_ids: list[str],
    ranked_claim_ids: list[str],
    graph: dict,
    claim_budget: int,
) -> list[str]:
    claims = graph.get("claims", {})
    claim_rank = {
        claim_id: rank
        for rank, claim_id in enumerate(ranked_claim_ids)
    }
    claim_to_group: dict[str, str] = {}
    group_to_claims: dict[str, list[str]] = {}
    for state in graph.get("states", {}).values():
        for group in state.get("time_groups", []):
            group_id = str(group.get("group_id", ""))
            if not group_id:
                continue
            members = [
                str(claim_id)
                for claim_id in group.get("claim_ids", [])
                if claim_id in claims
            ]
            group_to_claims[group_id] = members
            for claim_id in members:
                claim_to_group[claim_id] = group_id

    selected = list(dict.fromkeys(seed_claim_ids))[:claim_budget]
    selected_set = set(selected)
    expansion_support: dict[str, int] = {}
    for seed_rank, seed_id in enumerate(seed_claim_ids):
        group_id = claim_to_group.get(seed_id)
        if not group_id:
            continue
        for claim_id in group_to_claims.get(group_id, []):
            if claim_id not in selected_set:
                expansion_support[claim_id] = min(
                    expansion_support.get(
                        claim_id,
                        len(seed_claim_ids),
                    ),
                    seed_rank,
                )

    expansion = sorted(
        expansion_support,
        key=lambda claim_id: (
            expansion_support[claim_id],
            claim_rank.get(claim_id, len(ranked_claim_ids)),
            claim_id,
        ),
    )
    for claim_id in expansion:
        if len(selected) >= claim_budget:
            break
        group_id = claim_to_group.get(claim_id)
        if group_id and sum(
            claim_to_group.get(item) == group_id
            for item in selected
        ) >= ExperimentConfig.time_group_max_claims:
            continue
        state_id = claims.get(claim_id, {}).get("state_id")
        if state_id and sum(
            claims.get(item, {}).get("state_id") == state_id
            for item in selected
        ) >= ExperimentConfig.time_group_max_claims_per_state:
            continue
        selected.append(claim_id)
        selected_set.add(claim_id)

    for claim_id in ranked_claim_ids:
        if len(selected) >= claim_budget:
            break
        if claim_id not in selected_set:
            selected.append(claim_id)
            selected_set.add(claim_id)
    return selected


def supporting_state_ids(
    claim_ids: list[str],
    graph: dict,
) -> list[str]:
    claims = graph.get("claims", {})
    states = graph.get("states", {})
    state_ids = []
    for claim_id in claim_ids:
        state_id = claims.get(claim_id, {}).get("state_id")
        if (
            state_id
            and state_id in states
            and state_id not in state_ids
        ):
            state_ids.append(state_id)
    return state_ids[: ExperimentConfig.state_top_k]


class RetrievalEmbeddingCache:
    """Persistent async cache for Scope, Claim, and query embeddings."""

    feature_version = "epbench-qa-rrf-v1"

    def __init__(self, provider, cache_path: Path):
        self.provider = provider
        self.cache_path = cache_path
        self.lock = asyncio.Lock()
        self.vectors_by_key: dict[str, list[float]] = {}
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                payload.get("feature_version") == self.feature_version
                and payload.get("embedding_model")
                == str(provider.model_name)
            ):
                self.vectors_by_key = {
                    str(key): [float(value) for value in vector]
                    for key, vector in payload.get("vectors", {}).items()
                }

    def _key(self, logical_id: str, text: str) -> str:
        value = "\0".join(
            [
                self.feature_version,
                str(self.provider.model_name),
                logical_id,
                text,
            ]
        )
        return hashlib.sha256(value.encode()).hexdigest()

    async def vectors(
        self,
        logical_ids: list[str],
        texts: list[str],
    ) -> list[list[float]]:
        if len(logical_ids) != len(texts):
            raise ValueError("logical_ids and texts must have equal length")
        keys = [
            self._key(logical_id, text)
            for logical_id, text in zip(logical_ids, texts)
        ]
        async with self.lock:
            missing = [
                index
                for index, key in enumerate(keys)
                if key not in self.vectors_by_key
            ]
            for start in range(0, len(missing), 64):
                positions = missing[start : start + 64]
                embedded = await self.provider.embed(
                    [texts[index] for index in positions]
                )
                if len(embedded) != len(positions):
                    raise RuntimeError(
                        "Embedding provider returned the wrong row count"
                    )
                for position, vector in zip(positions, embedded):
                    self.vectors_by_key[keys[position]] = [
                        float(value) for value in vector
                    ]
            if missing:
                self._save()
        return [self.vectors_by_key[key] for key in keys]

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_name(
            f".{self.cache_path.name}.tmp"
        )
        temporary.write_text(
            json.dumps(
                {
                    "feature_version": self.feature_version,
                    "embedding_model": str(self.provider.model_name),
                    "vectors": self.vectors_by_key,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.cache_path)


def _rrf(
    rankings: list[list[str]],
    top_k: int,
    allowed_ids: set[str] | None = None,
) -> list[str]:
    scores: dict[str, float] = {}
    first_seen: dict[str, tuple[int, int]] = {}
    for source_index, ranking in enumerate(rankings):
        for rank, item_id in enumerate(ranking, 1):
            if allowed_ids is not None and item_id not in allowed_ids:
                continue
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (60 + rank)
            first_seen.setdefault(item_id, (source_index, rank))
    return sorted(
        scores,
        key=lambda item_id: (
            -scores[item_id],
            first_seen[item_id],
            item_id,
        ),
    )[:top_k]


def _bm25_ranking(
    index: BM25Okapi | None,
    ids: list[str],
    query_tokens: list[str],
    allowed_ids: set[str] | None = None,
) -> list[str]:
    if index is None:
        return []
    scores = index.get_scores(query_tokens)
    return [
        item_id
        for item_id, _ in sorted(
            (
                (item_id, float(score))
                for item_id, score in zip(ids, scores)
                if allowed_ids is None or item_id in allowed_ids
            ),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def _dense_ranking(
    ids: list[str],
    vectors: list[list[float]],
    query_vector: list[float],
    allowed_ids: set[str] | None = None,
) -> list[str]:
    if not ids:
        return []
    matrix = np.asarray(vectors, dtype=float)
    query = np.asarray(query_vector, dtype=float)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8
    query /= np.linalg.norm(query) + 1e-8
    scores = matrix @ query
    return [
        item_id
        for item_id, _ in sorted(
            (
                (item_id, float(score))
                for item_id, score in zip(ids, scores)
                if allowed_ids is None or item_id in allowed_ids
            ),
            key=lambda item: (-item[1], item[0]),
        )
    ]


class EPBenchRetriever:
    """Scope RRF -> Claim RRF -> conditional TimeGroup -> Event."""

    def __init__(
        self,
        graph: dict,
        embedding_provider,
        cache_path: str | Path,
    ):
        self.graph = graph
        self.embedding_cache = RetrievalEmbeddingCache(
            embedding_provider,
            Path(cache_path),
        )
        self.scope_ids = sorted(graph.get("scopes", {}))
        self.scope_texts = [
            _scope_text(graph["scopes"][scope_id])
            for scope_id in self.scope_ids
        ]
        self.claim_ids = sorted(graph.get("claims", {}))
        self.claim_texts = [
            _claim_text(graph["claims"][claim_id])
            for claim_id in self.claim_ids
        ]
        self.scope_bm25 = (
            BM25Okapi(
                [_tokens(text) or ["empty"] for text in self.scope_texts]
            )
            if self.scope_ids
            else None
        )
        self.claim_bm25 = (
            BM25Okapi(
                [_tokens(text) or ["empty"] for text in self.claim_texts]
            )
            if self.claim_ids
            else None
        )

    async def retrieve(
        self,
        question: str,
        plan: QueryPlan,
    ) -> dict:
        claims = self.graph.get("claims", {})
        query_tokens = _tokens(question)
        query_vector = (
            await self.embedding_cache.vectors(
                [f"query:{hashlib.sha256(question.encode()).hexdigest()}"],
                [question],
            )
        )[0]
        scope_vectors = await self.embedding_cache.vectors(
            [f"scope:{scope_id}" for scope_id in self.scope_ids],
            self.scope_texts,
        )
        scope_limit = min(
            ExperimentConfig.scope_top_k,
            len(self.scope_ids),
        )
        bm25_scopes = _bm25_ranking(
            self.scope_bm25,
            self.scope_ids,
            query_tokens,
        )
        dense_scopes = _dense_ranking(
            self.scope_ids,
            scope_vectors,
            query_vector,
        )
        selected_scopes = _rrf(
            [bm25_scopes, dense_scopes],
            scope_limit,
        )

        candidate_claim_ids = {
            claim_id
            for claim_id, claim in claims.items()
            if claim.get("scope_id") in selected_scopes
        }
        claim_vectors = await self.embedding_cache.vectors(
            [f"claim:{claim_id}" for claim_id in self.claim_ids],
            self.claim_texts,
        )
        bm25_claims = _bm25_ranking(
            self.claim_bm25,
            self.claim_ids,
            query_tokens,
            candidate_claim_ids,
        )
        dense_claims = _dense_ranking(
            self.claim_ids,
            claim_vectors,
            query_vector,
            candidate_claim_ids,
        )
        claim_limit = min(
            ExperimentConfig.claim_top_k,
            len(candidate_claim_ids),
        )
        ranked_claims = _rrf(
            [bm25_claims, dense_claims],
            claim_limit,
            candidate_claim_ids,
        )

        direct_seeds = ranked_claims[
            : ExperimentConfig.claim_seed_top_k
        ]
        if should_expand_same_time_group(question):
            selected_claims = expand_same_time_group_claims(
                direct_seeds,
                ranked_claims,
                self.graph,
                ExperimentConfig.claim_top_k,
            )
            retrieval_mode = "claim_seed_same_time_group"
        else:
            selected_claims = ranked_claims[
                : ExperimentConfig.claim_top_k
            ]
            retrieval_mode = "claim_seed"

        if plan.mode == "latest" and selected_claims:
            latest = max(
                _time(claims[claim_id])
                for claim_id in selected_claims
            )
            selected_claims = [
                claim_id
                for claim_id in selected_claims
                if _time(claims[claim_id]) == latest
            ]
        elif plan.mode == "chronological":
            selected_claims.sort(
                key=lambda claim_id: (
                    _time(claims[claim_id]),
                    claim_id,
                )
            )

        events = self.graph.get("events", {})
        packed_event_ids = list(
            dict.fromkeys(
                event_id
                for claim_id in selected_claims
                for event_id in claims[claim_id].get("event_ids", [])
                if event_id in events
            )
        )
        return {
            "scope_ids": selected_scopes,
            "state_ids": supporting_state_ids(
                selected_claims,
                self.graph,
            ),
            "claim_ids": selected_claims,
            "packed_event_ids": packed_event_ids,
            "retrieval_mode": retrieval_mode,
            "retrieval_log": {
                "scope_bm25": bm25_scopes[:scope_limit],
                "scope_dense": dense_scopes[:scope_limit],
                "scope_rrf": selected_scopes,
                "claim_bm25": bm25_claims[
                    : ExperimentConfig.claim_top_k
                ],
                "claim_dense": dense_claims[
                    : ExperimentConfig.claim_top_k
                ],
                "claim_rrf": ranked_claims,
            },
        }


def format_context(graph: dict, selection: dict) -> str:
    scopes = graph.get("scopes", {})
    states = graph.get("states", {})
    events = graph.get("events", {})
    claims = graph.get("claims", {})
    claims_by_event: dict[str, list[dict]] = {}
    for claim_id in selection["claim_ids"]:
        claim = claims[claim_id]
        for event_id in claim.get("event_ids", []):
            if event_id in events:
                claims_by_event.setdefault(event_id, []).append(claim)

    lines = ["Retrieved episodic evidence from the book", "", "Relevant Scopes"]
    for scope_id in selection["scope_ids"]:
        scope = scopes[scope_id]
        lines.extend([f"- {scope['title']}: {scope['summary']}"])
    lines.extend(["", "Supporting State threads"])
    for state_id in selection.get("state_ids", []):
        state = states[state_id]
        lines.append(
            f"- {state.get('title') or state_id}"
            f" | Time: {state.get('start_time') or 'unknown'}"
            f" to {state.get('end_time') or 'unknown'}"
            f" | Summary: {state.get('summary') or ''}"
        )
    lines.extend(["", "Source Events for selected Claims"])
    for event_id in selection.get("packed_event_ids", []):
        event = events[event_id]
        lines.extend(
            [
                "",
                f"Event time: {event.get('event_time_text') or 'unknown'}",
                f"Entities: {', '.join(event.get('entities') or [])}",
                f"Locations: {', '.join(event.get('locations') or [])}",
                f"Event type: {event.get('event_type') or 'unknown'}",
                f"Summary: {event.get('summary') or ''}",
                f"Detailed event: {event.get('event_description') or ''}",
                "Selected Claims:",
            ]
        )
        for claim in claims_by_event.get(event_id, []):
            lines.append(
                f"- [{claim.get('claim_type') or 'detail'}] "
                f"{claim.get('content') or ''}"
                f" | Time: {claim.get('temporal') or 'unknown'}"
                f" | Location: {claim.get('spatial') or 'unknown'}"
                f" | Entities: {', '.join(claim.get('entities') or [])}"
                f" | Evidence: {claim.get('evidence') or ''}"
            )
    return "\n".join(lines)

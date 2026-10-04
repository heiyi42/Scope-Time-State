"""
STS Evidence Retrieval

Features:
1. Claim-seed STS evidence retrieval
   - Route the question to relevant Scopes
   - Select Claim seeds inside those Scopes
   - For temporal questions, expand Claims in the same State TimeGroup
   - Map selected Claims back to source Events
   - Preserve ranked Claim evidence for answer generation
2. Supports BM25, vector, and RRF retrieval
3. Leverages relation information and weights for retrieval optimization

Data flow:
indexes → Scope → Claim seeds → conditional State/TimeGroup expansion
→ Event → State-organized answer context
"""

import sys
import pickle
import json
import asyncio
import hashlib
import os
from pathlib import Path
import nltk
import numpy as np
from typing import List, Tuple, Dict, Any, Set, Optional
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
from collections import defaultdict
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TimeElapsedColumn, TimeRemainingColumn
)
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sts.providers.embeddings import EmbeddingProvider
from sts.config import ExperimentConfig

console = Console()

# RRF (Reciprocal Rank Fusion) constant
RRF_K = 60  # k value in the RRF formula, typically set to 60


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON without exposing a partially written destination."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def build_query_checkpoint_key(qa_pair: Dict[str, Any]) -> str:
    """Create an order-independent identity for one retrieval query."""

    canonical = json.dumps(
        {
            "question": qa_pair.get("question", ""),
            "category": qa_pair.get("category"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reciprocal_rank_fusion(
    results_list: List[List[Tuple[Dict, float]]],
    top_n: int,
    k: int = RRF_K
) -> List[Tuple[Dict, float]]:
    """
    Fuse multiple retrieval result lists using Reciprocal Rank Fusion (RRF)

    RRF formula: RRF_score(d) = Σ 1 / (k + rank(d))

    Args:
        results_list: Multiple retrieval result lists, each containing (doc, score) tuples
        top_n: Return top N results
        k: RRF parameter, typically set to 60

    Returns:
        Fused result list [(doc, rrf_score), ...]
    """
    # Store RRF scores and document data for each document
    doc_scores = {}  # doc_id -> {"doc": doc, "score": rrf_score}

    for results in results_list:
        for rank, (doc, _) in enumerate(results):
            # Get document ID
            doc_id = doc.get("id")
            if doc_id is None:
                # If no id exists, use the hash of the document content as identifier
                doc_id = hash(str(doc))

            # Calculate RRF score
            rrf_score = 1.0 / (k + rank + 1)

            if doc_id in doc_scores:
                doc_scores[doc_id]["score"] += rrf_score
            else:
                doc_scores[doc_id] = {"doc": doc, "score": rrf_score}

    # Sort by RRF score
    sorted_results = sorted(
        [(item["doc"], item["score"]) for item in doc_scores.values()],
        key=lambda x: x[1],
        reverse=True
    )

    return sorted_results[:top_n]


def build_context_template(
    *,
    include_scopes: bool = False,
    include_source_events: bool = True,
    include_claims: bool = True,
) -> str:
    """
    Build the STS evidence context template.

    Args:
        include_scopes: Include retrieved Scope summaries in the QA context.
        include_source_events: Include source Event text reached from Claims.
        include_claims: Include selected Claim evidence.

    Returns:
        Formatted template string
    """
    template_parts = ["Memories for conversation between {speaker_1} and {speaker_2}:"]

    if include_scopes:
        template_parts.append("""
## Relevant Scopes:
{scopes}""")

    template_parts.append("""
## Relevant State Threads:
{states}""")

    if include_source_events:
        template_parts.append("""
## Relevant Source Events:
{events}""")

    if include_claims:
        template_parts.append("""
## Relevant Claims:
{claims}""")

    return "".join(template_parts)

# Temporal keywords (used to detect temporal questions)
TEMPORAL_KEYWORDS = [
    'when', 'what time', 'what date', 'which year', 'which month', 'which day',
    'how long', 'how many years', 'how many months', 'how many days',
    'since when', 'until when', 'before', 'after', 'during',
    'recently', 'last', 'next', 'ago', 'in the past', 'in the future',
    'date', 'time', 'year', 'month', 'week', 'day'
]

# Claimual question keywords
CLAIMUAL_KEYWORDS = [
    'what is', 'who is', 'who are', 'where is', 'where are',
    'what did', 'who did', "what's", "who's",
    'which', 'name', 'identity', 'called'
]

# Reasoning question keywords
REASONING_KEYWORDS = [
    'why', 'how', 'would', 'could', 'should',
    'likely', 'probably', 'consider', 'think',
    'reason', 'because', 'explain', 'infer'
]

# Commonsense question keywords
COMMONSENSE_KEYWORDS = [
    'usually', 'normally', 'typically', 'generally',
    'common', 'often', 'always', 'never',
    'most', 'least', 'best', 'worst'
]

TEMPORAL_PROGRESSION_KEYWORDS = [
    "change", "changed", "changing", "progress", "progressed",
    "develop", "developed", "evolve", "evolved", "over time",
    "timeline", "sequence",
]


def detect_question_type(query: str) -> str:
    """
    Detect question type

    Args:
        query: Query question

    Returns:
        Question type: 'temporal', 'factual', 'reasoning', 'commonsense', 'default'
    """
    query_lower = query.lower()

    # Priority 1: Detect temporal questions
    if any(keyword in query_lower for keyword in TEMPORAL_KEYWORDS):
        return 'temporal'

    # Priority 2: Detect reasoning questions
    if any(keyword in query_lower for keyword in REASONING_KEYWORDS):
        return 'reasoning'

    # Priority 3: Detect factual questions
    if any(keyword in query_lower for keyword in CLAIMUAL_KEYWORDS):
        return 'factual'

    # Priority 4: Detect commonsense questions
    if any(keyword in query_lower for keyword in COMMONSENSE_KEYWORDS):
        return 'commonsense'

    # Default
    return 'default'


def is_temporal_question(query: str) -> bool:
    """
    Determine whether the question is a temporal question

    Args:
        query: Query question

    Returns:
        True if temporal question, False otherwise
    """
    return detect_question_type(query) == 'temporal'


def should_expand_same_time_group(query: str) -> bool:
    """Return whether State TimeGroup context is useful for this query."""
    query_lower = query.lower()
    return is_temporal_question(query) or any(
        keyword in query_lower
        for keyword in TEMPORAL_PROGRESSION_KEYWORDS
    )


def ensure_nltk_data():
    """Ensure NLTK data is downloaded"""
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt", quiet=True)

    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        nltk.download("stopwords", quiet=True)


def tokenize(text: str, stemmer, stop_words: set) -> list[str]:
    """
    NLTK tokenization, consistent with index building

    Args:
        text: Text to tokenize
        stemmer: Stemmer
        stop_words: Set of stop words

    Returns:
        List of processed tokens
    """
    if not text:
        return []

    tokens = word_tokenize(text.lower())

    processed_tokens = [
        stemmer.stem(token)
        for token in tokens
        if token.isalpha() and len(token) >= 2 and token not in stop_words
    ]

    return processed_tokens


def search_with_bm25(
    query: str,
    bm25,
    docs: List[Dict],
    doc_type: str,
    top_n: int = 5
) -> List[Tuple[Dict, float]]:
    """
    Retrieve using BM25 index, filtered by type

    Args:
        query: Query text
        bm25: BM25 index object
        docs: Document list
        doc_type: Document type filter ("scope", "event", "claim")
        top_n: Return top N results

    Returns:
        List of (document data, score) tuples (returns content of the data field)
    """
    stemmer = PorterStemmer()
    stop_words = set(stopwords.words("english"))
    tokenized_query = tokenize(query, stemmer, stop_words)

    if not tokenized_query:
        print(f"Warning: Query is empty after tokenization for {doc_type}")
        return []

    # Get scores for all documents
    doc_scores = bm25.get_scores(tokenized_query)

    # Filter documents of the specified type and extract the data field
    filtered_results = [
        (doc.get("data", doc), score) for doc, score in zip(docs, doc_scores)
        if doc.get("type") == doc_type
    ]

    # Sort by score
    sorted_results = sorted(filtered_results, key=lambda x: x[1], reverse=True)

    return sorted_results[:top_n]


def search_with_emb(
    query: str,
    emb_index: List[Dict],
    embedding_provider: EmbeddingProvider,
    doc_type: str,
    top_n: int = 5
) -> List[Tuple[Dict, float]]:
    """
    Retrieve using vector embedding index, filtered by type

    Args:
        query: Query text
        emb_index: Vector index list
        embedding_provider: Embedding provider
        doc_type: Document type filter
        top_n: Return top N results

    Returns:
        List of (document data, score) tuples
    """
    query_vec = np.array(embedding_provider.embed([query])[0])

    # Filter documents of the specified type
    filtered_items = [
        item for item in emb_index
        if item.get("type") == doc_type
    ]

    if not filtered_items:
        return []

    # Extract vectors and corresponding data
    embeddings = [item["embedding"] for item in filtered_items]
    embeddings_np = np.array(embeddings)

    # L2 norm normalization
    query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    embeddings_np = embeddings_np / (np.linalg.norm(embeddings_np, axis=1, keepdims=True) + 1e-8)

    # Calculate cosine similarity
    scores = embedding_provider.cosine_similarity(query_vec, embeddings_np)

    # Build result list (return complete data dict)
    results_with_scores = [
        (filtered_items[i]["data"], scores[i])
        for i in range(len(filtered_items))
    ]

    # Sort by score
    sorted_results = sorted(results_with_scores, key=lambda x: x[1], reverse=True)

    return sorted_results[:top_n]


def get_claim_ids_for_scopes(
    scope_ids: Set[str],
    graph: Dict[str, Any],
) -> Set[str]:
    """Return Claims whose parent Scope was retrieved."""
    return {
        claim_id
        for claim_id, claim in graph.get("claims", {}).items()
        if claim.get("scope_id") in scope_ids
    }


def expand_same_time_group_claims(
    seed_claim_ids: List[str],
    ranked_claim_ids: List[str],
    graph: Dict[str, Any],
    claim_budget: int,
    max_claims_per_group: int = 3,
    max_claims_per_state: int = 6,
) -> List[str]:
    """Expand temporal seeds within their TimeGroups, then fill by Claim rank.

    The input seed order is immutable: structural expansion can add context but
    can never displace a direct retrieval seed.
    """
    claims = graph.get("claims", {})
    states = graph.get("states", {})
    claim_rank = {
        claim_id: rank
        for rank, claim_id in enumerate(ranked_claim_ids)
    }
    claim_to_group: Dict[str, str] = {}
    group_to_claims: Dict[str, List[str]] = {}
    for state in states.values():
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
    expansion_support: Dict[str, int] = {}
    for seed_rank, seed_id in enumerate(seed_claim_ids):
        group_id = claim_to_group.get(seed_id)
        if not group_id:
            continue
        for claim_id in group_to_claims.get(group_id, []):
            if claim_id not in selected_set:
                expansion_support[claim_id] = min(
                    expansion_support.get(claim_id, len(seed_claim_ids)),
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
            claim_to_group.get(item) == group_id for item in selected
        ) >= max_claims_per_group:
            continue
        state_id = claims.get(claim_id, {}).get("state_id")
        if state_id and sum(
            claims.get(item, {}).get("state_id") == state_id
            for item in selected
        ) >= max_claims_per_state:
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


def states_supported_by_claims(
    claim_ids: List[str],
    claim_scores: Dict[str, float],
    graph: Dict[str, Any],
    top_n: int,
) -> List[Tuple[Dict[str, Any], float]]:
    """Return State threads supported by selected Claims in evidence order."""
    claims = graph.get("claims", {})
    states = graph.get("states", {})
    state_scores: Dict[str, float] = {}
    state_first_rank: Dict[str, int] = {}
    for rank, claim_id in enumerate(claim_ids):
        state_id = claims.get(claim_id, {}).get("state_id")
        if not state_id or state_id not in states:
            continue
        state_first_rank.setdefault(state_id, rank)
        state_scores[state_id] = max(
            state_scores.get(state_id, float("-inf")),
            float(claim_scores.get(claim_id, 0.0)),
        )
    ranked_state_ids = sorted(
        state_scores,
        key=lambda state_id: (
            state_first_rank[state_id],
            -state_scores[state_id],
            state_id,
        ),
    )
    return [
        (states[state_id], state_scores[state_id])
        for state_id in ranked_state_ids[:top_n]
    ]


def get_source_events_for_claims(
    claim_ids: List[str],
    claim_scores: Dict[str, float],
    graph: Dict[str, Any],
) -> List[Tuple[Dict[str, Any], float]]:
    """Return every source Event in Claim evidence order, deduplicated."""
    events = graph.get("events", {})
    claim_to_events: Dict[str, List[str]] = defaultdict(list)
    for relation in graph.get("event_claim_relations", {}).values():
        event_id = relation.get("event_node_id")
        if not event_id or event_id not in events:
            continue
        for claim_id in (relation.get("relation") or {}):
            if event_id not in claim_to_events[claim_id]:
                claim_to_events[claim_id].append(event_id)

    ordered_results = []
    seen_event_ids = set()
    for claim_id in claim_ids:
        source_event_ids = sorted(
            claim_to_events.get(claim_id, []),
            key=lambda event_id: (
                str(events[event_id].get("timestamp", "")),
                event_id,
            ),
        )
        for event_id in source_event_ids:
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            ordered_results.append(
                (events[event_id], float(claim_scores.get(claim_id, 0.0)))
            )
    return ordered_results


def retrieve_sts_evidence(
    query: str,
    graph: Dict[str, Any],
    bm25=None,
    docs=None,
    emb_index=None,
    embedding_provider: EmbeddingProvider = None,
    config: ExperimentConfig = None
) -> Dict[str, List[Tuple[Dict, float]]]:
    """
    Retrieve Scope-Time-State evidence for one question.

    Args:
        query: Query question
        graph: Complete graph data structure
        bm25: BM25 index (if using BM25)
        docs: Document list (if using BM25)
        emb_index: Vector index (if using vector retrieval)
        embedding_provider: Embedding provider
        config: Experiment configuration

    Returns:
        Retrieved Scopes, State threads, source Events, Claims, and trace data.
    """
    results = {
        "scopes": [],
        "states": [],
        "events": [],
        "claims": []
    }

    # Retrieval log: captures the full retrieval flow for debugging
    retrieval_log = {
        "query": query,
        "config": {},
        "scope_search": {},
        "state_selection": {},
        "event_packaging": {},
        "claim_packaging": {},
    }

    include_source_events = getattr(
        config, "include_source_events", True
    )
    include_claims = getattr(config, "include_claims", True)

    # Detect question type
    question_type = detect_question_type(query)

    # One fixed budget is used for every question type.
    scope_top_k = config.retrieval_config["scope_top_k"]
    state_top_k = config.retrieval_config["state_top_k"]
    claim_top_k = config.retrieval_config["claim_top_k"]

    # Temporal enhancement detection
    is_temporal = (
        config.temporal_enhancement
        and should_expand_same_time_group(query)
    )
    if is_temporal:
        print("  [TEMPORAL] Temporal information enhancement enabled")

    # === Scope routing ===

    print("  [Scope] Retrieving relevant scopes...")
    retrieve_top_n = scope_top_k

    # Select dense-only retrieval or BM25+dense RRF fusion.
    retrieval_type = getattr(config, 'retrieval_type', 'rrf').lower()
    if retrieval_type not in ("vector", "rrf"):
        raise ValueError(
            f"unsupported retrieval_type={retrieval_type!r}; "
            "use 'vector' or 'rrf'"
        )
    use_rrf = retrieval_type == 'rrf'

    retrieval_log["config"] = {
        "question_type": question_type,
        "scope_top_k": scope_top_k,
        "state_top_k": state_top_k,
        "claim_top_k": claim_top_k,
        "include_source_events": include_source_events,
        "include_claims": include_claims,
        "retrieval_type": retrieval_type,
    }

    if use_rrf and emb_index and bm25 and docs:
        # RRF hybrid retrieval: use both BM25 and vector retrieval, then fuse
        bm25_scope_results = search_with_bm25(
            query=query,
            bm25=bm25,
            docs=docs,
            doc_type="scope",
            top_n=retrieve_top_n
        )
        emb_scope_results = search_with_emb(
            query=query,
            emb_index=emb_index,
            embedding_provider=embedding_provider,
            doc_type="scope",
            top_n=retrieve_top_n
        )
        scope_results = reciprocal_rank_fusion(
            [bm25_scope_results, emb_scope_results],
            top_n=retrieve_top_n
        )
        print(f"    [RRF] Fused BM25({len(bm25_scope_results)}) + Vector({len(emb_scope_results)}) → {len(scope_results)}")
        retrieval_log["scope_search"]["bm25"] = [(d.get("id",""), float(round(s,3))) for d,s in bm25_scope_results]
        retrieval_log["scope_search"]["emb"] = [(d.get("id",""), float(round(s,3))) for d,s in emb_scope_results]
        retrieval_log["scope_search"]["rrf"] = [(d.get("id",""), float(round(s,3))) for d,s in scope_results]
    else:
        scope_results = search_with_emb(
            query=query,
            emb_index=emb_index,
            embedding_provider=embedding_provider,
            doc_type="scope",
            top_n=retrieve_top_n
        )
        print(f"    [Vector] Retrieved {len(scope_results)} scopes")
        retrieval_log["scope_search"]["emb"] = [(d.get("id",""), float(round(s,3))) for d,s in scope_results]

    scope_results = scope_results[:scope_top_k]
    retrieval_log["scope_search"]["final"] = [(d.get("id",""), float(round(s,3))) for d,s in scope_results]
    retrieval_log["scope_search"]["final_titles"] = [d.get("title","")[:60] for d,s in scope_results]

    results["scopes"] = scope_results
    relevant_scope_ids = {scope_data["id"] for scope_data, _ in scope_results}
    print(f"    Found {len(relevant_scope_ids)} relevant scopes")

    if not relevant_scope_ids:
        print("    Warning: No relevant scopes found, skipping subsequent retrieval")
        results["retrieval_log"] = retrieval_log
        return results

    # === Claim seeds and State selection ===
    candidate_claim_ids = get_claim_ids_for_scopes(
        relevant_scope_ids, graph
    )
    if not candidate_claim_ids:
        results["retrieval_log"] = retrieval_log
        return results
    claim_seed_top_k = min(
        config.retrieval_config.get("claim_seed_top_k", 15),
        claim_top_k,
    )
    claim_candidate_top_n = claim_top_k

    def search_seed_claims_bm25():
        candidates = search_with_bm25(
            query=query,
            bm25=bm25,
            docs=docs,
            doc_type="claim",
            top_n=max(
                claim_candidate_top_n * 2,
                len(candidate_claim_ids),
            ),
        )
        return [
            (doc, score)
            for doc, score in candidates
            if doc.get("id") in candidate_claim_ids
        ][:claim_candidate_top_n]

    def search_seed_claims_emb():
        candidates = search_with_emb(
            query=query,
            emb_index=emb_index,
            embedding_provider=embedding_provider,
            doc_type="claim",
            top_n=max(
                claim_candidate_top_n * 2,
                len(candidate_claim_ids),
            ),
        )
        return [
            (doc, score)
            for doc, score in candidates
            if doc.get("id") in candidate_claim_ids
        ][:claim_candidate_top_n]

    if use_rrf and emb_index and bm25 and docs:
        bm25_seed_results = search_seed_claims_bm25()
        emb_seed_results = search_seed_claims_emb()
        seed_claim_results = reciprocal_rank_fusion(
            [bm25_seed_results, emb_seed_results],
            top_n=claim_candidate_top_n,
        )
        retrieval_log["state_selection"]["claim_bm25"] = [
            (doc.get("id", ""), float(round(score, 3)))
            for doc, score in bm25_seed_results
        ]
        retrieval_log["state_selection"]["claim_emb"] = [
            (doc.get("id", ""), float(round(score, 3)))
            for doc, score in emb_seed_results
        ]
    else:
        seed_claim_results = search_seed_claims_emb()

    seed_claim_results = seed_claim_results[:claim_top_k]

    ranked_claim_ids = [
        claim["id"] for claim, _ in seed_claim_results
    ]
    claim_scores = {
        claim["id"]: float(score)
        for claim, score in seed_claim_results
    }
    direct_seed_ids = ranked_claim_ids[:claim_seed_top_k]
    if is_temporal:
        selected_claim_ids_ordered = expand_same_time_group_claims(
            seed_claim_ids=direct_seed_ids,
            ranked_claim_ids=ranked_claim_ids,
            graph=graph,
            claim_budget=claim_top_k,
            max_claims_per_group=config.retrieval_config.get(
                "time_group_max_claims", 3
            ),
            max_claims_per_state=config.retrieval_config.get(
                "time_group_max_claims_per_state", 6
            ),
        )
        retrieval_mode = "claim_seed_same_time_group"
    else:
        selected_claim_ids_ordered = ranked_claim_ids[:claim_top_k]
        retrieval_mode = "claim_seed"
    state_results = states_supported_by_claims(
        selected_claim_ids_ordered,
        claim_scores,
        graph,
        state_top_k,
    )
    results["states"] = state_results
    retrieval_log["state_selection"] = {
        **retrieval_log["state_selection"],
        "mode": retrieval_mode,
        "candidate_claim_count": len(candidate_claim_ids),
        "direct_seed_count": len(direct_seed_ids),
        "selected_claim_count": len(selected_claim_ids_ordered),
        "direct_seeds": direct_seed_ids,
        "selected_claims": selected_claim_ids_ordered,
        "supporting_states": [
            state.get("id", "") for state, _ in state_results
        ],
    }

    # === Package Claim evidence and its source Events ===
    if not include_source_events and not include_claims:
        print("  [Evidence] Source Event and Claim packaging disabled")
        results["retrieval_log"] = retrieval_log
        return results

    if include_source_events:
        event_results = get_source_events_for_claims(
            selected_claim_ids_ordered,
            claim_scores,
            graph,
        )
        print(
            f"  [Evidence] Mapped {len(selected_claim_ids_ordered)} Claims to "
            f"{len(event_results)} unique source Events"
        )
        retrieval_log["event_packaging"]["mode"] = "claim_source_dedup"
        retrieval_log["event_packaging"]["connected_count"] = len(event_results)
        retrieval_log["event_packaging"]["final"] = [
            (d.get("id", "")[:25], float(round(s, 3)))
            for d, s in event_results
        ]
        retrieval_log["event_packaging"]["final_subjects"] = [
            d.get("subject", "")[:50] for d, _ in event_results
        ]
        results["events"] = event_results
    else:
        retrieval_log["event_packaging"]["mode"] = "disabled"
        print("  [Evidence] Source Event packaging disabled")

    if not include_claims:
        print("  [Evidence] Claim packaging disabled")
        results["retrieval_log"] = retrieval_log
        return results

    claims = graph.get("claims", {})
    claim_results = [
        (claims[claim_id], float(claim_scores.get(claim_id, 0.0)))
        for claim_id in selected_claim_ids_ordered
        if claim_id in claims
    ]
    retrieval_log["claim_packaging"]["mode"] = "preserve_selected_claims"
    retrieval_log["claim_packaging"]["connected_count"] = len(claim_results)
    retrieval_log["claim_packaging"]["final"] = [(d.get("id","")[:25], float(round(s,3))) for d,s in claim_results]
    retrieval_log["claim_packaging"]["final_contents"] = [d.get("content","")[:60] for d,s in claim_results]

    results["claims"] = claim_results
    results["retrieval_log"] = retrieval_log
    print(f"  [Evidence] Preserved {len(claim_results)} selected Claims")

    return results


def format_sts_context(
    results: Dict[str, List[Tuple[Dict, float]]],
    speaker_a: str,
    speaker_b: str,
    include_scopes: bool = False,
    include_source_events: bool = True,
    include_claims: bool = True,
    state_summary_max_chars: int = 600,
) -> str:
    """
    Format retrieved STS evidence into the QA context.

    Args:
        results: Retrieved STS evidence.
        speaker_a: Speaker A
        speaker_b: Speaker B
        include_scopes: Include Scope summaries.
        include_source_events: Include source Event text.
        include_claims: Include Claim evidence.

    Returns:
        Formatted context string
    """
    # Format scopes
    scope_texts = []
    for idx, (scope_data, score) in enumerate(results.get("scopes", []), 1):
        title = scope_data.get('title', '')
        summary = scope_data.get('summary', '')
        timestamp = scope_data.get('timestamp', '')
        keywords = scope_data.get('keywords', [])

        scope_text = f"[Scope {idx}] {title}"
        if timestamp:
            scope_text += f"\n  Time: {timestamp}"
        if summary:
            scope_text += f"\n  Summary: {summary}"
        if keywords:
            keywords_str = ", ".join(keywords[:5])  # Only display the first 5 keywords
            scope_text += f"\n  Keywords: {keywords_str}"

        scope_texts.append(scope_text)

    scopes_str = "\n\n".join(scope_texts) if scope_texts else "No relevant scopes found."

    # Format Claim-derived State threads. Source Events are reached separately
    # through EventClaimRelations; no direct State -> Event relation is materialized.
    state_texts = []
    for idx, (state_data, score) in enumerate(
        results.get("states", []), 1
    ):
        state_text = f"[State {idx}] {state_data.get('title', '')}"
        start_time = state_data.get("start_time")
        end_time = state_data.get("end_time")
        if start_time or end_time:
            state_text += (
                f"\n  Time: {start_time or '?'} -> {end_time or '?'}"
            )
        summary = state_data.get("summary", "")
        if summary:
            if len(summary) > state_summary_max_chars:
                summary = summary[:state_summary_max_chars].rstrip() + "…"
            state_text += f"\n  Summary: {summary}"
        state_texts.append(state_text)
    states_str = (
        "\n\n".join(state_texts)
        if state_texts
        else "No relevant State threads found."
    )

    # Format events
    event_texts = []
    for idx, (event_data, score) in enumerate(results.get("events", []), 1):
        event = event_data.get('event_description', '')
        timestamp = event_data.get('timestamp', '')

        event_text = f"[Memory {idx}] {event}"
        if timestamp:
            event_text += f"\n  Time: {timestamp}"

        event_texts.append(event_text)

    events_str = "\n\n".join(event_texts) if event_texts else "No relevant evidence claims found."

    # Format claims
    claim_texts = []
    for idx, (claim_data, score) in enumerate(results.get("claims", []), 1):
        content = claim_data.get('content', '')
        claim_text = f"[Claim {idx}] {content}"
        temporal = claim_data.get('temporal', '')
        spatial = claim_data.get('spatial', '')

        if temporal:
            claim_text += f"\n  Time: {temporal}"
        if spatial:
            claim_text += f"\n  Location: {spatial}"

        claim_texts.append(claim_text)

    claims_str = "\n\n".join(claim_texts) if claim_texts else "No relevant claims found."

    template = build_context_template(
        include_scopes=include_scopes,
        include_source_events=include_source_events,
        include_claims=include_claims,
    )

    # Prepare format arguments (only include fields needed by the template)
    format_args = {
        "speaker_1": speaker_a,
        "speaker_2": speaker_b,
        "states": states_str,
    }
    if "{scopes}" in template:
        format_args["scopes"] = scopes_str
    if "{events}" in template:
        format_args["events"] = events_str
    if "{claims}" in template:
        format_args["claims"] = claims_str

    context = template.format(**format_args)

    return context


def get_query_count(conversation_data: Dict[str, Any]) -> int:
    """
    Count the number of queries to process in a conversation (excluding category 5)

    Args:
        conversation_data: Conversation data

    Returns:
        Number of queries
    """
    if "qa" not in conversation_data:
        return 0

    count = 0
    for qa_pair in conversation_data["qa"]:
        if qa_pair.get("question") and qa_pair.get("category") != 5:
            count += 1
    return count


def process_single_conversation_retrieval(
    conv_id: int,
    conversation_data: Dict[str, Any],
    config: ExperimentConfig,
    graph_dir: Path,
    embedding_provider: Optional[EmbeddingProvider],
    progress_callback: Optional[callable] = None
) -> tuple[str, List[Dict[str, Any]]]:
    """
    Process retrieval task for a single conversation

    Args:
        conv_id: Conversation ID
        conversation_data: Conversation data
        config: Experiment configuration
        graph_dir: STSGraph directory
        embedding_provider: Embedding provider
        progress_callback: Progress callback function, called after each query is processed

    Returns:
        (conversation ID, list of retrieval results)
    """
    try:
        conv_id_str = f"locomo_exp_user_{conv_id}"
        speaker_a = conversation_data["conversation"].get("speaker_a", "Speaker A")
        speaker_b = conversation_data["conversation"].get("speaker_b", "Speaker B")

        if "qa" not in conversation_data:
            console.print(f"  [yellow][!] Conversation {conv_id}: 'qa' field not found[/yellow]")
            return (conv_id_str, [])

        # === Load graph data ===
        graph_file = graph_dir / f"graph_conv_{conv_id}.json"
        if not graph_file.exists():
            console.print(f"  [yellow][!] Conversation {conv_id}: STSGraph file not found[/yellow]")
            return (conv_id_str, [])

        with open(graph_file, "r", encoding="utf-8") as f:
            graph = json.load(f)

        # === Load indexes (hybrid retrieval requires loading both BM25 and vector indexes) ===
        bm25 = None
        docs = None
        emb_index = None

        # Always try to load BM25 index (for hybrid retrieval)
        bm25_index_dir = graph_dir.parent / "bm25_index"
        bm25_index_file = bm25_index_dir / f"graph_bm25_index_conv_{conv_id}.pkl"
        if bm25_index_file.exists():
            try:
                with open(bm25_index_file, "rb") as f:
                    index_data = pickle.load(f)
                bm25 = index_data["bm25"]
                docs = index_data["docs"]
            except (EOFError, pickle.UnpicklingError) as e:
                console.print(
                    f"  [red][!] Conversation {conv_id}: BM25 index file "
                    f"corrupted ({e}); rebuild the retrieval index[/red]"
                )

        # Vector indexes are mandatory for both supported retrieval modes.
        retrieval_type = getattr(config, 'retrieval_type', 'rrf').lower()
        emb_index_dir = graph_dir.parent / "vectors"
        emb_index_file = emb_index_dir / f"graph_embedding_index_conv_{conv_id}.pkl"
        if emb_index_file.exists():
            try:
                with open(emb_index_file, "rb") as f:
                    emb_index = pickle.load(f)
            except (EOFError, pickle.UnpicklingError) as e:
                console.print(
                    f"  [red][!] Conversation {conv_id}: Vector index file "
                    f"corrupted ({e}); rebuild the retrieval index[/red]"
                )
        if emb_index is None:
            console.print(f"  [yellow][!] Conversation {conv_id}: Vector index unavailable[/yellow]")
            return (conv_id_str, [])
        if retrieval_type == "rrf" and (bm25 is None or docs is None):
            console.print(f"  [yellow][!] Conversation {conv_id}: BM25 index unavailable for RRF[/yellow]")
            return (conv_id_str, [])

        # Retrieve STS evidence for each question.
        results_for_conv = []
        for qa_pair in conversation_data["qa"]:
            question = qa_pair.get("question")
            if not question:
                continue

            # Skip category 5 questions
            if qa_pair.get("category") == 5:
                continue

            evidence = retrieve_sts_evidence(
                query=question,
                graph=graph,
                bm25=bm25,
                docs=docs,
                emb_index=emb_index,
                embedding_provider=embedding_provider,
                config=config
            )

            context_str = format_sts_context(
                results=evidence,
                speaker_a=speaker_a,
                speaker_b=speaker_b,
                include_source_events=getattr(
                    config, "include_source_events", True
                ),
                include_claims=getattr(config, "include_claims", True),
            )

            # Save results
            results_for_conv.append({
                "query": question,
                "context": context_str,
                "evidence_counts": {
                    "scopes_count": len(evidence.get("scopes", [])),
                    "states_count": len(evidence.get("states", [])),
                    "events_count": len(evidence.get("events", [])),
                    "claims_count": len(evidence.get("claims", []))
                },
                "retrieval_log": evidence.get("retrieval_log", {}),
                "original_qa": qa_pair
            })

            # Call progress callback
            if progress_callback:
                progress_callback()

        return (conv_id_str, results_for_conv)

    except Exception as e:
        console.print(f"  [red][X] Conversation {conv_id}: Retrieval failed - {e}[/red]")
        import traceback
        traceback.print_exc()
        return (f"locomo_exp_user_{conv_id}", [])


async def main():
    """Execute batch STS evidence retrieval in parallel."""
    # === Configuration ===
    config = ExperimentConfig()

    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]STS retrieval[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")

    # Supported modes: dense vector or BM25+dense RRF fusion.
    retrieval_type = getattr(config, 'retrieval_type', 'rrf').lower()
    retrieval_mode_display = {
        'rrf': '[green]RRF Hybrid Retrieval (BM25 + Vector)[/green]',
        'vector': '[cyan]Vector Retrieval (Vector)[/cyan]',
    }.get(retrieval_type, f'[red]Unknown mode: {retrieval_type}[/red]')
    console.print(f"[bold]Retrieval mode:[/bold] {retrieval_mode_display}")

    # STSGraph data directory
    graph_dir = config.graph_dir()

    # Output directory
    save_dir = config.experiment_dir()
    save_dir.mkdir(parents=True, exist_ok=True)
    results_output_path = save_dir / "search_results.json"

    # Concurrency settings
    max_concurrent_tasks = 10

    # Dataset path
    dataset_path = Path(config.dataset_path)

    # Initialize services
    embedding_provider = None
    need_emb = retrieval_type in ('vector', 'rrf')
    if need_emb:
        embedding_provider = EmbeddingProvider(
            base_url=config.embedding_config["base_url"],
            model_name=config.embedding_config["model_name"],
            max_retries=config.embedding_max_retries,
            api_key=config.embedding_config.get("api_key", ""),
        )

    console.print(f"[bold]Concurrency:[/bold] {max_concurrent_tasks}\n")

    # Ensure NLTK data is available
    ensure_nltk_data()

    # Load dataset
    console.print(f"[bold]Loading dataset:[/bold] {dataset_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    console.print(f"[bold]Number of conversations:[/bold] {len(dataset)}\n")

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async def process_with_semaphore(conv_id: int, conversation_data: Dict, task_id: int, progress: Progress, query_count: int):
        """Processing function with semaphore-based concurrency control"""
        async with semaphore:
            progress.start_task(task_id)
            progress.update(task_id, status="Processing")

            # Get the event loop in the main coroutine (before entering the thread pool)
            main_loop = asyncio.get_running_loop()

            # Create thread-safe progress callback (capturing main_loop via closure)
            def progress_callback():
                # Use call_soon_threadsafe to ensure thread safety
                main_loop.call_soon_threadsafe(
                    progress.advance, task_id, 1
                )

            # Execute retrieval in thread pool (since retrieval involves CPU-intensive operations)
            result = await main_loop.run_in_executor(
                None,
                process_single_conversation_retrieval,
                conv_id,
                conversation_data,
                config,
                graph_dir,
                embedding_provider,
                progress_callback
            )

            conv_id_str, results_for_conv = result

            # Ensure progress bar is completed
            progress.update(
                task_id,
                completed=query_count,
                status="[green]Done[/green]",
            )

            return result

    # Create progress bar for parallel processing
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.completed:>3}/{task.total:<3}"),  # Right-align completed count, left-align total
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("•"),
        TextColumn("[bold]{task.fields[status]}"),
        console=console,
        transient=False
    ) as progress:
        # Create tasks for each conversation and count queries
        tasks = []
        for i, conversation_data in enumerate(dataset):
            query_count = get_query_count(conversation_data)
            task_id = progress.add_task(
                f"[cyan]Conv {i}[/cyan]",
                total=query_count if query_count > 0 else 1,
                status="Waiting",
                start=False
            )
            tasks.append((i, conversation_data, task_id, query_count))

        # Parallel processing
        coroutines = [
            process_with_semaphore(conv_id, conv_data, task_id, progress, query_count)
            for conv_id, conv_data, task_id, query_count in tasks
        ]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

    # Organize results
    all_search_results = {}
    for result in results:
        if isinstance(result, tuple):
            conv_id_str, results_for_conv = result
            all_search_results[conv_id_str] = results_for_conv
        elif isinstance(result, Exception):
            console.print(f"[red][X] Processing exception: {result}[/red]")

    # === Save all results ===
    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print(f"[bold]Saving retrieval results to:[/bold] {results_output_path}")
    with open(results_output_path, "w", encoding="utf-8") as f:
        json.dump(all_search_results, f, indent=2, ensure_ascii=False)

    # === Save retrieval logs separately for analysis ===
    retrieval_logs_path = save_dir / "retrieval_logs.json"
    all_logs = {}
    for conv_id, items in all_search_results.items():
        all_logs[conv_id] = [
            {"query": item.get("query", ""), "retrieval_log": item.get("retrieval_log", {})}
            for item in items
        ]
    with open(retrieval_logs_path, "w", encoding="utf-8") as f:
        json.dump(all_logs, f, indent=2, ensure_ascii=False)
    console.print(f"[bold]Saving retrieval logs to:[/bold] {retrieval_logs_path}")

    console.print(
        "[bold green][SUCCESS] STS evidence retrieval completed![/bold green]"
    )
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")


if __name__ == "__main__":
    asyncio.run(main())

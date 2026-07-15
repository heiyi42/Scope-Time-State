"""Adapter-driven pairwise state consolidation shared by STS graph builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple


STATE_MERGE_DECISIONS = frozenset(
    {
        "COMPATIBLE",
        "DIFFERENT_TARGET",
        "SUPERSEDES",
        "CORRECTS",
        "CONFLICTS_WITH",
    }
)


@dataclass(frozen=True)
class StateMergeAdapter:
    """Benchmark-owned projections required by the generic fold."""

    eligible: Callable[[Mapping[str, Any]], bool]
    owner_key: Callable[[Mapping[str, Any]], str]
    domain_key: Callable[[Mapping[str, Any]], str]
    dimension_key: Callable[[Mapping[str, Any]], str]
    chronology_key: Callable[[Mapping[str, Any]], Tuple[Any, ...]]
    lifecycle_winner_is_valid: Callable[[Mapping[str, Any], Mapping[str, Any], str], bool]


def _validated_decision(raw: Mapping[str, Any]) -> Dict[str, Any]:
    decision = str(raw.get("decision") or "").strip().upper()
    if decision not in STATE_MERGE_DECISIONS:
        raise ValueError(f"unsupported state merge decision: {decision!r}")
    winner = str(raw.get("winner") or "none").strip().lower()
    if decision in {"SUPERSEDES", "CORRECTS"}:
        if winner not in {"existing", "incoming"}:
            raise ValueError(f"{decision} requires winner=existing|incoming")
    elif winner != "none":
        raise ValueError(f"{decision} requires winner=none")
    reason = str(raw.get("reason") or "").strip()
    if not reason:
        raise ValueError("state merge decision requires a non-empty reason")
    raw_evidence = raw.get("evidence_event_ids", [])
    if not isinstance(raw_evidence, list):
        raise ValueError("state merge decision evidence_event_ids must be a list")
    evidence_event_ids = list(dict.fromkeys(str(item) for item in raw_evidence if str(item)))
    if not evidence_event_ids:
        raise ValueError("state merge decision requires endpoint evidence")
    return {
        "decision": decision,
        "winner": winner,
        "reason": reason,
        "evidence_event_ids": evidence_event_ids,
    }


def fold_state_claims(
    claims: Sequence[Mapping[str, Any]],
    adapter: StateMergeAdapter,
    decide: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    *,
    candidate_limit: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fold Claims by comparing each incoming Claim with active cluster representatives."""

    limit = int(candidate_limit)
    if limit < 1:
        raise ValueError("state merge candidate_limit must be positive")
    indexed_claims: List[Tuple[int, Mapping[str, Any], str, str, str, Tuple[Any, ...]]] = []
    seen_claim_ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not adapter.eligible(claim):
            continue
        claim_id = str(claim.get("claim_id") or "")
        owner_key = adapter.owner_key(claim)
        domain_key = adapter.domain_key(claim)
        dimension_key = adapter.dimension_key(claim)
        chronology_key = adapter.chronology_key(claim)
        if not all((claim_id, owner_key, domain_key, dimension_key)):
            raise ValueError("eligible state Claim is missing claim, owner, domain, or dimension identity")
        if claim_id in seen_claim_ids:
            raise ValueError(f"duplicate eligible state Claim ID: {claim_id!r}")
        if not isinstance(chronology_key, tuple):
            raise ValueError("state merge chronology_key must return a tuple")
        seen_claim_ids.add(claim_id)
        indexed_claims.append((index, claim, owner_key, domain_key, dimension_key, chronology_key))
    source_order_by_claim_id = {str(row[1].get("claim_id") or ""): row[0] for row in indexed_claims}

    grouped: Dict[Tuple[str, str], List[Tuple[int, Mapping[str, Any], str, Tuple[Any, ...]]]] = {}
    for index, claim, owner_key, domain_key, dimension_key, chronology_key in indexed_claims:
        grouped.setdefault((owner_key, domain_key), []).append(
            (index, claim, dimension_key, chronology_key)
        )

    clusters: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []
    for (owner_key, domain_key), group_rows in grouped.items():
        ordered = sorted(group_rows, key=lambda row: (*row[3], row[0]))
        group_clusters: List[Dict[str, Any]] = []
        for sequence_index, (_source_index, incoming, incoming_dimension, _chronology_key) in enumerate(ordered):
            incoming_id = str(incoming.get("claim_id") or "")
            candidates = [
                cluster
                for cluster in group_clusters
                if cluster["status"] != "historical" and cluster["dimension_key"] == incoming_dimension
            ]
            candidates.sort(key=lambda cluster: -int(cluster["last_sequence_index"]))
            if len(candidates) > limit:
                raise ValueError(
                    "state merge active-cluster limit exceeded; refine the adapter dimension instead of truncating"
                )

            evaluated: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
            for cluster in candidates:
                existing = cluster["primary_claim"]
                decision = _validated_decision(decide(existing, incoming))
                endpoint_event_ids = {
                    str(existing.get("source_event_id") or existing.get("dialog_id") or ""),
                    str(incoming.get("source_event_id") or incoming.get("dialog_id") or ""),
                }
                if any(event_id not in endpoint_event_ids for event_id in decision["evidence_event_ids"]):
                    raise ValueError("state merge decision used evidence outside its two endpoint Claims")
                if (
                    decision["decision"] in {"SUPERSEDES", "CORRECTS"}
                    and not adapter.lifecycle_winner_is_valid(existing, incoming, decision["winner"])
                ):
                    raise ValueError("state merge lifecycle winner contradicts adapter chronology")
                evaluated.append((cluster, decision))

            incoming_wins = [
                (cluster, decision)
                for cluster, decision in evaluated
                if decision["decision"] in {"SUPERSEDES", "CORRECTS"} and decision["winner"] == "incoming"
            ]
            existing_wins = [
                (cluster, decision)
                for cluster, decision in evaluated
                if decision["decision"] in {"SUPERSEDES", "CORRECTS"} and decision["winner"] == "existing"
            ]
            if incoming_wins and existing_wins:
                raise ValueError("state merge decisions give both the incoming and an existing Claim lifecycle victory")
            compatible_clusters = [
                cluster
                for cluster, decision in evaluated
                if decision["decision"] == "COMPATIBLE"
            ]
            if existing_wins and compatible_clusters:
                raise ValueError("incoming Claim cannot be both compatible with and retired by active state clusters")

            def append_relation(cluster: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
                existing = cluster["primary_claim"]
                existing_id = str(existing.get("claim_id") or "")
                decision_type = str(decision["decision"])
                relation = {
                    "type": decision_type,
                    "reason": decision["reason"],
                    "evidence_event_ids": decision["evidence_event_ids"],
                }
                if decision_type == "CONFLICTS_WITH":
                    relation.update({"from": incoming_id, "to": existing_id})
                elif decision["winner"] == "incoming":
                    relation.update({"from": incoming_id, "to": existing_id})
                else:
                    relation.update({"from": existing_id, "to": incoming_id})
                relations.append(relation)

            for cluster, decision in evaluated:
                if decision["decision"] == "CONFLICTS_WITH":
                    append_relation(cluster, decision)
            if existing_wins:
                for cluster, decision in existing_wins:
                    append_relation(cluster, decision)
                group_clusters.append(
                    {
                        "owner_key": owner_key,
                        "domain_key": domain_key,
                        "dimension_key": incoming_dimension,
                        "primary_claim_id": incoming_id,
                        "primary_claim": incoming,
                        "support_claim_ids": [incoming_id],
                        "support_claims": [incoming],
                        "status": "historical",
                        "last_sequence_index": sequence_index,
                    }
                )
                continue

            for cluster, decision in incoming_wins:
                cluster["status"] = "historical"
                append_relation(cluster, decision)

            if compatible_clusters:
                cluster = compatible_clusters[0]
                if len(compatible_clusters) > 1:
                    merged_claim_ids = {
                        claim_id
                        for compatible_cluster in compatible_clusters
                        for claim_id in compatible_cluster["support_claim_ids"]
                    }
                    relations[:] = [
                        relation
                        for relation in relations
                        if not (
                            relation["type"] == "CONFLICTS_WITH"
                            and str(relation["from"]) in merged_claim_ids
                            and str(relation["to"]) in merged_claim_ids
                        )
                    ]
                    merged_supports_by_id = {
                        str(support.get("claim_id") or ""): support
                        for compatible_cluster in compatible_clusters
                        for support in compatible_cluster["support_claims"]
                    }
                    merged_supports_by_id[incoming_id] = incoming
                    merged_supports = sorted(
                        merged_supports_by_id.values(),
                        key=lambda support: (
                            *adapter.chronology_key(support),
                            source_order_by_claim_id[str(support.get("claim_id") or "")],
                        ),
                    )
                    cluster["support_claims"] = merged_supports
                    cluster["support_claim_ids"] = [
                        str(support.get("claim_id") or "") for support in merged_supports
                    ]
                    for redundant_cluster in compatible_clusters[1:]:
                        group_clusters.remove(redundant_cluster)
                elif incoming_id not in cluster["support_claim_ids"]:
                    cluster["support_claim_ids"].append(incoming_id)
                    cluster["support_claims"].append(incoming)
                cluster["primary_claim_id"] = incoming_id
                cluster["primary_claim"] = incoming
                cluster["last_sequence_index"] = sequence_index
                cluster["status"] = "current"
                continue

            group_clusters.append(
                {
                    "owner_key": owner_key,
                    "domain_key": domain_key,
                    "dimension_key": incoming_dimension,
                    "primary_claim_id": incoming_id,
                    "primary_claim": incoming,
                    "support_claim_ids": [incoming_id],
                    "support_claims": [incoming],
                    "status": "current",
                    "last_sequence_index": sequence_index,
                }
            )
        clusters.extend(group_clusters)

    clusters_by_claim: Dict[str, Dict[str, Any]] = {}
    for cluster in clusters:
        for claim_id in cluster["support_claim_ids"]:
            if claim_id in clusters_by_claim:
                raise ValueError(f"state Claim belongs to multiple clusters: {claim_id!r}")
            clusters_by_claim[claim_id] = cluster
        if cluster["status"] != "historical":
            cluster["status"] = "current"
    for relation in relations:
        if relation["type"] != "CONFLICTS_WITH":
            continue
        source_cluster = clusters_by_claim[str(relation["from"])]
        target_cluster = clusters_by_claim[str(relation["to"])]
        if source_cluster is target_cluster:
            raise ValueError("state merge produced an internal conflict inside one compatible cluster")
        if source_cluster["status"] != "historical" and target_cluster["status"] != "historical":
            source_cluster["status"] = "ambiguous"
            target_cluster["status"] = "ambiguous"

    clean_clusters = [
        {
            key: value
            for key, value in cluster.items()
            if key not in {"primary_claim", "support_claims", "last_sequence_index"}
        }
        for cluster in clusters
    ]
    return clean_clusters, relations

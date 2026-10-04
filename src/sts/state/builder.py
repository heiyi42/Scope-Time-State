from __future__ import annotations

import uuid
from itertools import chain
from time import perf_counter
from typing import Mapping, Sequence

import numpy as np
import networkx as nx

from sts.state.claim_graph import ClaimGraphBuilder
from sts.state.config import StateThreadConfig
from sts.state.embedding_adapter import CachedEmbeddingService
from sts.state.feature_builder import ClaimThreadFeatureBuilder
from sts.state.semantic_distance import l2_normalize
from sts.state.models import (
    TemporalRelation,
    StateBuildResult,
    StateMembership,
)
from sts.state.pruning import ClaimGraphPruner
from sts.state.state_identity import StateIdentityBuilder
from sts.state.temporal_order import TemporalOrderBuilder
from sts.state.time_resolver import ClaimTimeResolver
from sts.graph.types import Claim, Event, State


class StateThreadBuilder:
    """Build deterministic STS Claim threads within one Scope."""

    def __init__(
        self,
        embedding_service: CachedEmbeddingService,
        config: StateThreadConfig | None = None,
    ):
        self.embedding_service = embedding_service
        self.config = config or StateThreadConfig()
        self.time_resolver = ClaimTimeResolver()
        self.feature_builder = ClaimThreadFeatureBuilder()
        self.graph_builder = ClaimGraphBuilder(self.config)
        self.temporal_order_builder = TemporalOrderBuilder()
        self.identity_builder = StateIdentityBuilder()
        self.partitioner = ClaimGraphPruner(
            self.config.prune_percentile,
            self.config.outdegree_limit,
        )

    def build_scope(
        self,
        scope_id: str,
        claims: Sequence[Claim],
        events_by_id: Mapping[str, Event],
    ) -> StateBuildResult:
        started = perf_counter()
        claims_by_id = {claim.claim_id: claim for claim in claims}
        if len(claims_by_id) != len(claims):
            raise ValueError("Claim IDs must be unique within a Scope")
        wrong_scope = [
            claim.claim_id for claim in claims if claim.scope_id != scope_id
        ]
        if wrong_scope:
            raise ValueError(
                f"Claims do not belong to Scope {scope_id}: {wrong_scope}"
            )

        pending_claim_ids = []
        untimed_claim_ids = []
        features = []
        for claim in claims:
            claim.state_id = None
            if claim.confidence < self.config.min_claim_confidence:
                pending_claim_ids.append(claim.claim_id)
                continue
            resolved = self.time_resolver.resolve(claim, events_by_id)
            if resolved is None:
                untimed_claim_ids.append(claim.claim_id)
                continue
            features.append(
                self.feature_builder.build(claim, resolved, events_by_id)
            )
        features.sort(key=lambda item: (item.resolved_time, item.claim_id))

        embedding_started = perf_counter()
        structured_vectors = self.embedding_service.embed(
            [feature.structured_text for feature in features],
            [f"{feature.claim_id}:structured" for feature in features],
            self.config.feature_version,
        )
        content_vectors = self.embedding_service.embed(
            [feature.content_text for feature in features],
            [f"{feature.claim_id}:content" for feature in features],
            self.config.feature_version,
        )
        embedding_seconds = perf_counter() - embedding_started
        structured_matrix = np.asarray(structured_vectors, dtype=float)
        content_matrix = np.asarray(content_vectors, dtype=float)
        if not features:
            structured_matrix = np.empty((0, 0), dtype=float)
            content_matrix = np.empty((0, 0), dtype=float)

        graph, candidate_edges = self.graph_builder.build(
            features, structured_matrix
        )
        pruned_graph = self.partitioner.prune(graph)
        communities = [
            set(component)
            for component in nx.weakly_connected_components(pruned_graph)
        ]
        communities.sort(
            key=lambda group: min(
                (
                    feature.resolved_time,
                    feature.claim_id,
                )
                for feature in features
                if feature.claim_id in group
            )
        )

        feature_by_id = {feature.claim_id: feature for feature in features}
        content_by_id = {
            feature.claim_id: vector
            for feature, vector in zip(
                features, l2_normalize(content_matrix)
            )
        }
        states = []
        memberships = []
        temporal_relations = []
        assigned_claim_ids = set()
        identities = self.identity_builder.build(
            communities,
            claims_by_id,
            feature_by_id,
            content_by_id,
        )

        for community, identity in zip(communities, identities):
            state_id = self._state_id(scope_id, sorted(community))
            time_groups, group_relations = self.temporal_order_builder.build(
                state_id,
                sorted(community),
                feature_by_id,
            )
            ordered_claim_ids = [
                claim_id
                for group in time_groups
                for claim_id in group.claim_ids
            ]
            distinct_event_ids = list(
                dict.fromkeys(
                    chain.from_iterable(
                        claims_by_id[claim_id].event_ids
                        for claim_id in ordered_claim_ids
                    )
                )
            )
            if (
                self.config.max_distinct_events_per_state is not None
                and len(distinct_event_ids)
                > self.config.max_distinct_events_per_state
                and self.config.oversize_policy == "recursive_split"
            ):
                raise NotImplementedError(
                    "recursive_split is a Phase-B optimization"
                )

            coherence = self._coherence(
                sorted(community), content_by_id
            )
            state_claims = [
                claims_by_id[claim_id] for claim_id in ordered_claim_ids
            ]
            state = State(
                state_id=state_id,
                scope_id=scope_id,
                title=identity.title,
                summary=self._fallback_summary(state_claims),
                claim_ids=ordered_claim_ids,
                event_ids=distinct_event_ids,
                start_time=min(
                    group.start_time for group in time_groups
                ),
                end_time=max(group.end_time for group in time_groups),
                coherence=coherence,
                construction_version=self.config.construction_version,
                construction_params=self.config.to_dict(),
                subject=identity.subject,
                dimension=identity.dimension,
                topic_terms=list(identity.topic_terms),
                identity_coverage=identity.coverage,
                identity_separation=identity.separation,
                is_mixed=identity.is_mixed,
                representative_claim_ids=list(
                    identity.representative_claim_ids
                ),
                time_groups=[
                    group.to_dict() for group in time_groups
                ],
            )
            states.append(state)
            for group in time_groups:
                for claim_id in group.claim_ids:
                    if claim_id in assigned_claim_ids:
                        raise RuntimeError(
                            f"Claim {claim_id} was assigned to multiple "
                            "States"
                        )
                    assigned_claim_ids.add(claim_id)
                    claims_by_id[claim_id].state_id = state_id
                    memberships.append(
                        StateMembership(
                            state_id,
                            claim_id,
                            group.group_id,
                            group.rank,
                        )
                    )
            for relation in group_relations:
                temporal_relations.append(
                    TemporalRelation(
                        state_id,
                        relation.source_group_id,
                        relation.target_group_id,
                    )
                )

        pending_claim_ids = sorted(set(pending_claim_ids))
        untimed_claim_ids = sorted(set(untimed_claim_ids))
        for claim_id in pending_claim_ids + untimed_claim_ids:
            claims_by_id[claim_id].state_id = None

        total_seconds = perf_counter() - started
        state_claim_counts = [len(state.claim_ids) for state in states]
        return StateBuildResult(
            scope_id=scope_id,
            states=states,
            pending_claim_ids=pending_claim_ids,
            untimed_claim_ids=untimed_claim_ids,
            graph_stats={
                "eligible_claim_count": len(features),
                "candidate_edge_count": graph.number_of_edges(),
                "pruned_edge_count": pruned_graph.number_of_edges(),
                "community_count": len(communities),
                "state_count": len(states),
            },
            diagnostics={
                "input_claim_count": len(claims),
                "assigned_claim_count": len(assigned_claim_ids),
                "pending_claim_count": len(pending_claim_ids),
                "untimed_claim_count": len(untimed_claim_ids),
                "singleton_community_count": sum(
                    len(community) == 1 for community in communities
                ),
                "average_claims_per_state": (
                    sum(state_claim_counts) / len(state_claim_counts)
                    if state_claim_counts
                    else 0.0
                ),
                "embedding_seconds": embedding_seconds,
                "total_seconds": total_seconds,
            },
            state_memberships=memberships,
            temporal_relations=temporal_relations,
            candidate_edges=(
                candidate_edges if self.config.export_claim_graph else []
            ),
            features=features if self.config.export_features else [],
        )

    def _state_id(self, scope_id: str, claim_ids: list[str]) -> str:
        key = "\0".join(
            [self.config.construction_version, scope_id, *claim_ids]
        )
        return f"state_{uuid.uuid5(uuid.NAMESPACE_URL, key)}"

    @staticmethod
    def _coherence(
        claim_ids: list[str],
        content_vectors: Mapping[str, np.ndarray],
    ) -> float | None:
        if len(claim_ids) < 2:
            return None
        matrix = np.asarray(
            [content_vectors[claim_id] for claim_id in claim_ids],
            dtype=float,
        )
        centroid = matrix.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm:
            centroid = centroid / norm
        return float(np.mean(matrix @ centroid))

    @staticmethod
    def _fallback_summary(claims: list[Claim]) -> str:
        return " ".join(claim.content for claim in claims[:4])

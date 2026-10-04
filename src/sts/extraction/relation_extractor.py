"""
STSGraph Builder

Features:
- Assemble the STS evidence graph from extractor results
- Convert Claim, Event, and Scope into graph nodes
- Connect relations into the graph, establishing bidirectional link relationships

Workflow:
1. Extract Events using ConvEventExtractor
2. Extract ScopeExtractResult and ScopeEventRelationExtractResult using ScopeExtractor
3. Extract ClaimExtractResult and EventClaimRelationExtractResult using ClaimExtractor
4. Use STSGraphBuilder to assemble the STS evidence graph

Example:
    extractor = STSGraphBuilder()

    graph = extractor.build_graph(
        events=[episode1, episode2],
        claim_results=[claim_result1],
        event_claim_relation_results=[event_claim_relation1, event_claim_relation2],
        scope_extract_result=scope_result,
        scope_event_relation_results=[scope_event_relation1]
    )
"""

from typing import List, Optional, Dict, Any
from sts.utils.logger import get_logger
from sts.graph.types import Event
from sts.graph.schema import (
    STSGraph,
    ClaimNode,
    EventNode,
    ScopeNode
)
from sts.extraction.claim_extractor import (
    ClaimExtractResult,
    EventClaimRelationExtractResult
)
from sts.extraction.scope_extractor import (
    ScopeExtractResult,
    ScopeEventRelationExtractResult
)

logger = get_logger(__name__)


class STSGraphBuilder:
    """
    STSGraph Builder

    Assemble Claims, Events, Scopes, and their explicit relations.
    """

    def __init__(self):
        """Initialize the graph builder"""
        pass

    def build_graph(
        self,
        events: List[Event],
        claim_results: List[ClaimExtractResult],
        event_claim_relation_results: List[EventClaimRelationExtractResult],
        scope_extract_result: Optional[ScopeExtractResult],
        scope_event_relation_results: List[ScopeEventRelationExtractResult]
    ) -> STSGraph:
        """
        Build one STS evidence graph from the extracted records.

        Args:
            events: List of Events
            claim_results: List of claim extraction results (one per scope)
            event_claim_relation_results: List of claim relation extraction results
            scope_extract_result: Scope extraction result
            scope_event_relation_results: List of Event relation extraction results

        Returns:
            Complete STS evidence graph
        """
        logger.info("[STSGraphBuilder] Starting STS evidence graph assembly")

        graph = STSGraph()

        # Add source Event records.
        for event in events:
            event_id = event.event_id

            event_node = EventNode.from_event(
                event=event,
                event_claim_relation_id="",
                relation={}
            )

            graph.events[event_id] = event_node
            logger.debug(f"  Events: added {event_id}")

        logger.info(f"  Events: added {len(events)} records")

        # Add Scope records and Scope-to-Event relations.
        scopes = []
        if scope_extract_result:
            scopes = scope_extract_result.scopes

        # Build event relation mapping
        scope_event_relation_map = {}  # scope_id -> ScopeEventRelation
        for result in scope_event_relation_results:
            if result.scope_event_relation:
                scope_id_val = result.scope_id
                scope_event_relation_map[scope_id_val] = result.scope_event_relation

        # Add scope nodes and event relations
        for scope in scopes:
            scope_id_val = scope.scope_id

            scope_event_relation = scope_event_relation_map.get(scope_id_val)

            if not scope_event_relation:
                logger.warning(f"  Scope {scope_id_val}: No event relation, skipping")
                continue

            # Add event relation
            graph.add_relation(
                layer="event",
                relation_id=scope_event_relation.id,
                relation=scope_event_relation.relation,
                weights=scope_event_relation.weights,
                scope_node_id=scope_event_relation.scope_node_id,
                created_at=scope_event_relation.created_at,
                coherence_score=scope_event_relation.coherence_score
            )

            # Create ScopeNode
            scope_node = ScopeNode.from_scope(
                scope=scope,
                scope_event_relation_id=scope_event_relation.id
            )

            graph.scopes[scope_id_val] = scope_node
            logger.debug(f"  Scopes: added {scope_id_val}")

        logger.info(f"  Scopes: added {len(scopes)} records")

        # Add Claims and Event-to-Claim relations.
        # Build claim relation mapping (the same event may have multiple relations that need merging)
        event_claim_relation_map = {}  # event_id -> EventClaimRelation (after merging)
        for result in event_claim_relation_results:
            if result.event_claim_relation:
                event_id = result.event_id
                new_relation = result.event_claim_relation

                if event_id in event_claim_relation_map:
                    # Merge relation and weights from multiple relations
                    existing_relation = event_claim_relation_map[event_id]
                    existing_relation.relation.update(new_relation.relation)
                    if existing_relation.weights and new_relation.weights:
                        existing_relation.weights.update(new_relation.weights)
                    elif new_relation.weights:
                        existing_relation.weights = new_relation.weights
                else:
                    event_claim_relation_map[event_id] = new_relation

        # Collect all claims
        all_claims = []
        for result in claim_results:
            all_claims.extend(result.claims)

        # Add claim nodes
        for claim in all_claims:
            claim_id = claim.claim_id

            # Build relation mapping {relation_id: role}
            relation_dict = {}
            for event_id in claim.event_ids:
                event_claim_relation = event_claim_relation_map.get(event_id)
                if event_claim_relation:
                    role = event_claim_relation.relation.get(claim_id, "detail")
                    relation_dict[event_claim_relation.id] = role

            # Create ClaimNode
            claim_node = ClaimNode.from_claim(
                claim=claim,
                relation=relation_dict
            )

            graph.claims[claim_id] = claim_node
            logger.debug(f"  Claims: added {claim_id}")

        logger.info(f"  Claims: added {len(all_claims)} records")

        # Add claim relations
        for event_id, event_claim_relation in event_claim_relation_map.items():
            graph.event_claim_relations[event_claim_relation.id] = event_claim_relation

            # Update event's event_claim_relation_id
            if event_id in graph.events:
                graph.events[event_id].event_claim_relation_id = event_claim_relation.id

        logger.info(
            "  Event-to-Claim relations: added "
            f"{len(event_claim_relation_map)} records"
        )

        # Validate explicit bidirectional references.
        validation_errors = graph.validate_bidirectional_links()
        if validation_errors:
            logger.warning("[STSGraphBuilder] STSGraph bidirectional link validation failed:")
            for error_type, error_list in validation_errors.items():
                logger.warning(f"  {error_type}:")
                for error in error_list:
                    logger.warning(f"    - {error}")
        else:
            logger.info("[STSGraphBuilder] STSGraph bidirectional link validation passed")

        logger.info(
            "[STSGraphBuilder] STS evidence graph assembled - "
            f"{graph.get_stats()}"
        )

        return graph

    def get_graph_summary(self, graph: STSGraph) -> Dict[str, Any]:
        """
        Get summary information of the graph

        Args:
            graph: STSGraph instance

        Returns:
            Dictionary containing statistics
        """
        stats = graph.get_stats()

        # Compute average degrees
        claim_degrees = [
            graph.get_node_degree("claim", node_id)
            for node_id in graph.claims.keys()
        ]
        event_degrees = [
            graph.get_node_degree("event", node_id)
            for node_id in graph.events.keys()
        ]

        event_claim_relation_degrees = [
            graph.get_relation_degree("claim", relation_id)
            for relation_id in graph.event_claim_relations.keys()
        ]
        scope_event_relation_degrees = [
            graph.get_relation_degree("event", relation_id)
            for relation_id in graph.scope_event_relations.keys()
        ]

        summary = {
            "stats": stats,
            "avg_claim_degree": sum(claim_degrees) / len(claim_degrees) if claim_degrees else 0,
            "avg_event_degree": sum(event_degrees) / len(event_degrees) if event_degrees else 0,
            "avg_event_claim_relation_degree": sum(event_claim_relation_degrees) / len(event_claim_relation_degrees) if event_claim_relation_degrees else 0,
            "avg_scope_event_relation_degree": sum(scope_event_relation_degrees) / len(scope_event_relation_degrees) if scope_event_relation_degrees else 0,
        }

        return summary

    def print_graph_structure(self, graph: STSGraph):
        """
        Print summary of the graph structure (for debugging)

        Args:
            graph: STSGraph instance
        """
        logger.info("=" * 80)
        logger.info("STSGraph Structure Summary")
        logger.info("=" * 80)

        summary = self.get_graph_summary(graph)

        logger.info("Node Statistics:")
        logger.info(f"  Claims: {summary['stats']['claims']} records")
        logger.info(f"  Events: {summary['stats']['events']} records")
        logger.info(f"  Scopes: {summary['stats']['scopes']} records")

        logger.info("\nRelation Statistics:")
        logger.info(
            "  Event-to-Claim relations: "
            f"{summary['stats']['event_claim_relations']}"
        )
        logger.info(
            "  Scope-to-Event relations: "
            f"{summary['stats']['scope_event_relations']}"
        )

        logger.info("\nAverage Degrees:")
        logger.info(f"  Claim node average degree: {summary['avg_claim_degree']:.2f}")
        logger.info(f"  Event node average degree: {summary['avg_event_degree']:.2f}")
        logger.info(f"  Claim relation average degree: {summary['avg_event_claim_relation_degree']:.2f}")
        logger.info(f"  Event relation average degree: {summary['avg_scope_event_relation_degree']:.2f}")

        logger.info("=" * 80)

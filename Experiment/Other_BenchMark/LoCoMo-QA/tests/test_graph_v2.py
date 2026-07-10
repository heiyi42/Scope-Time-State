from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sys
import unittest


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BENCHMARK_DIR.parents[2]
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from common.loader import DialogTurn  # noqa: E402
from ours_scope_time_state import graph_builder, graph_query_runner  # noqa: E402


class RoleAwareGraphBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.turn = DialogTurn(
            dia_id="D1:1",
            session_id="S1",
            session_index=1,
            session_date_time="2024-01-10 10:00:00",
            speaker="Caroline",
            text="I plan to start pottery next month.",
            image_caption="",
            image_query="",
        )

    def test_v2_materializes_semantic_time_role(self) -> None:
        nodes = {}
        edges = []
        graph_builder.materialize_base_event(nodes, edges, "conv-test", self.turn, "v2")
        claim = graph_builder.materialize_claim(
            nodes,
            edges,
            "conv-test",
            {self.turn.dia_id: self.turn},
            {
                "dialog_id": self.turn.dia_id,
                "subject": "Caroline",
                "facet_key": "plan",
                "value": "Caroline plans to start pottery",
                "time_role": "planned_for",
                "time_value": "next month",
                "scope_labels": ["pottery"],
            },
            1,
            "v2",
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim["time_role"], "planned_for")
        roles = {
            node["time_role"]
            for node in nodes.values()
            if node.get("node_type") == "Time"
        }
        self.assertEqual(roles, {"occurred_at", "planned_for", "current_after"})
        has_time = next(edge for edge in edges if edge["type"] == "HAS_TIME")
        self.assertEqual(has_time["time_role"], "planned_for")
        self.assertEqual(nodes[has_time["to"]]["value"], "next month")
        state = next(node for node in nodes.values() if node.get("node_type") == "StateFacet")
        self.assertEqual(state["current_after"], self.turn.session_date_time)
        self.assertEqual(graph_builder.validate_graph(nodes, edges, "v2"), [])

    def test_v1_keeps_legacy_time_shape(self) -> None:
        nodes = {}
        edges = []
        graph_builder.materialize_base_event(nodes, edges, "conv-test", self.turn, "v1")
        claim = graph_builder.materialize_claim(
            nodes,
            edges,
            "conv-test",
            {self.turn.dia_id: self.turn},
            {
                "dialog_id": self.turn.dia_id,
                "subject": "Caroline",
                "facet_key": "plan",
                "value": "Caroline plans to start pottery",
                "time_value": "next month",
                "scope_labels": ["pottery"],
            },
            1,
            "v1",
        )

        self.assertIsNotNone(claim)
        self.assertNotIn("time_role", claim)
        roles = {
            node["time_role"]
            for node in nodes.values()
            if node.get("node_type") == "Time"
        }
        self.assertEqual(roles, {"session_date_time", "claim_time"})
        self.assertEqual(graph_builder.validate_graph(nodes, edges, "v1"), [])

    def test_relative_time_ids_include_the_session_anchor(self) -> None:
        first = graph_builder.time_id("planned_for", "next month", "2024-01-10 10:00:00")
        second = graph_builder.time_id("planned_for", "next month", "2024-03-10 10:00:00")
        self.assertNotEqual(first, second)

    def test_empty_time_sentinels_do_not_become_time_nodes(self) -> None:
        self.assertEqual(graph_builder.normalize_time_value("empty"), "")
        self.assertEqual(graph_builder.normalize_time_value("N/A"), "")

    def test_past_time_cannot_be_planned_for(self) -> None:
        self.assertEqual(
            graph_builder.normalize_claim_time_role("planned_for", "last Tues"),
            "occurred_at",
        )


class RelationAwareExpansionTests(unittest.TestCase):
    def test_state_embedding_variant_targets_scope_event_and_state(self) -> None:
        self.assertEqual(
            graph_query_runner.embedding_targets_for_variant("graph_embedding_scope_event_state"),
            {"scope", "event", "state"},
        )

    def test_relation_expansion_reaches_related_claim_event_and_state(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        graph.events = {
            "D1:1": {"event_id": "D1:1"},
            "D2:1": {"event_id": "D2:1"},
        }
        graph.claims = {
            "claim-old": {"claim_id": "claim-old", "source_event_id": "D1:1", "value": "old"},
            "claim-new": {"claim_id": "claim-new", "source_event_id": "D2:1", "value": "new"},
        }
        graph.states = {
            "state-old": {
                "facet_id": "state-old",
                "support_claim_ids": ["claim-old"],
                "support_event_ids": ["D1:1"],
            },
            "state-new": {
                "facet_id": "state-new",
                "support_claim_ids": ["claim-new"],
                "support_event_ids": ["D2:1"],
            },
        }
        graph.claims_by_event = defaultdict(list, {"D1:1": ["claim-old"], "D2:1": ["claim-new"]})
        graph.states_by_claim = defaultdict(list, {"claim-old": ["state-old"], "claim-new": ["state-new"]})
        relation = {
            "type": "SUPERSEDES",
            "from": "claim-new",
            "to": "claim-old",
            "reason": "later update",
            "evidence_event_ids": ["D2:1"],
        }
        graph.relations_by_claim = defaultdict(
            list,
            {"claim-old": [relation], "claim-new": [relation]},
        )

        event_ids, state_ids, relation_lines, trace = graph._expand_relation_aware(
            ["D1:1"],
            [],
            max_context_events=8,
            max_state_lines=8,
        )

        self.assertEqual(event_ids, ["D1:1", "D2:1"])
        self.assertEqual(state_ids, ["state-old", "state-new"])
        self.assertEqual(trace["relation_edge_count"], 1)
        self.assertEqual(trace["visited_claim_ids"], ["claim-old", "claim-new"])
        self.assertEqual(len(relation_lines), 1)

    def test_auto_expansion_preserves_v1_and_enables_v2(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V1
        self.assertEqual(graph.resolve_graph_expansion("auto"), "legacy")
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        self.assertEqual(graph.resolve_graph_expansion("auto"), "relation-aware")


if __name__ == "__main__":
    unittest.main()

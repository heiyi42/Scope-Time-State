from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BENCHMARK_DIR.parents[2]
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from common.loader import DialogTurn  # noqa: E402
from ours_scope_time_state import graph_builder, graph_query_runner  # noqa: E402
from pipeline.external.temporal_grounding import (  # noqa: E402
    format_temporal_grounding,
    ground_temporal_expressions,
)
from pipeline.external.time_role_selection import select_time_roles  # noqa: E402
from pipeline.external.sts_v2.schema import SCHEMA_VERSION  # noqa: E402


class StubJsonClient:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, _system_prompt, _user_prompt):
        return self.payload


class FailingJsonClient:
    def complete_json(self, _system_prompt, _user_prompt):
        raise AssertionError("LLM should not be called for a deterministic high-precision rule")


class SequenceJsonClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.call_count = 0

    def complete_json(self, _system_prompt, _user_prompt):
        payload = self.payloads[min(self.call_count, len(self.payloads) - 1)]
        self.call_count += 1
        return payload


class StubEmbeddingIndex:
    def __init__(self, ranked_doc_ids):
        self.ranked_doc_ids = list(ranked_doc_ids)

    def search(self, _query, top_k, *, allowed_doc_ids=None):
        allowed = None if allowed_doc_ids is None else set(allowed_doc_ids)
        return [
            SimpleNamespace(doc_id=doc_id, score=1.0 / rank)
            for rank, doc_id in enumerate(self.ranked_doc_ids, start=1)
            if allowed is None or doc_id in allowed
        ][:top_k]


class TimeRoleSelectionTests(unittest.TestCase):
    def test_recent_activity_question_uses_rule_without_calling_llm(self) -> None:
        result = select_time_roles("What has Caroline been doing recently?", FailingJsonClient(), "llm-compatible")

        self.assertEqual(result["primary_roles"], ["occurred_at"])
        self.assertEqual(result["compatible_roles"], ["started_at", "updated_at"])
        self.assertEqual(result["ordering"], "newest_first")
        self.assertEqual(result["source"], "deterministic_high_precision_question_rule:recent")

    def test_explicit_completion_question_uses_rule_without_calling_llm(self) -> None:
        result = select_time_roles("When was the project completed?", FailingJsonClient(), "llm")

        self.assertEqual(result["time_roles"], ["completed_at"])
        self.assertTrue(result["source"].startswith("deterministic_high_precision_question_rule:"))


class SharedSTSGraphSchemaTests(unittest.TestCase):
    def test_builder_and_query_use_shared_v2_schema(self) -> None:
        self.assertEqual(graph_builder.GRAPH_SCHEMA_V2, SCHEMA_VERSION)
        self.assertEqual(graph_query_runner.ACTIVE_GRAPH_SCHEMA_V2, SCHEMA_VERSION)

    def test_non_temporal_question_can_leave_time_routing_inactive(self) -> None:
        result = select_time_roles(
            "What pets does Melanie have?",
            StubJsonClient({"time_applicable": False, "time_roles": [], "reason": "No time distinction."}),
            "llm",
        )

        self.assertFalse(result["time_applicable"])
        self.assertEqual(result["time_roles"], [])
        self.assertEqual(result["source"], "llm_question_only")

    def test_invalid_selector_output_falls_back_without_current_state_bias(self) -> None:
        result = select_time_roles(
            "What did Caroline paint?",
            StubJsonClient({"reason": "missing role field"}),
            "llm",
        )

        self.assertFalse(result["time_applicable"])
        self.assertEqual(result["time_roles"], [])
        self.assertEqual(result["source"], "selector_invalid_fallback")

    def test_compatible_selector_keeps_primary_and_bounded_compatible_roles(self) -> None:
        result = select_time_roles(
            "Where did Caroline move from four years ago?",
            StubJsonClient(
                {
                    "time_applicable": True,
                    "primary_roles": ["occurred_at"],
                    "compatible_roles": ["valid_from", "started_at", "mentioned_at"],
                    "reason": "A move may be represented as an occurrence or a starting boundary.",
                }
            ),
            "llm-compatible",
        )

        self.assertEqual(result["primary_roles"], ["occurred_at"])
        self.assertEqual(result["compatible_roles"], ["valid_from", "started_at"])
        self.assertEqual(result["time_roles"], ["occurred_at", "valid_from", "started_at"])
        self.assertEqual(result["source"], "llm_compatible_question_only")


class TemporalGroundingTests(unittest.TestCase):
    def test_yesterday_resolves_against_visible_event_anchor(self) -> None:
        rows = ground_temporal_expressions(
            "I went to the support group yesterday.",
            "1:56 pm on 8 May, 2023",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["expression"].lower(), "yesterday")
        self.assertEqual(rows[0]["normalized_value"], "7 May 2023")
        self.assertEqual(rows[0]["resolved_start"], "2023-05-07")

    def test_relative_weekday_keeps_relation_and_computes_date(self) -> None:
        rows = ground_temporal_expressions(
            "I went to the meeting last Friday.",
            "1:51 pm on 15 July, 2023",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["normalized_value"], "the Friday before 15 July 2023")
        self.assertEqual(rows[0]["resolved_start"], "2023-07-14")
        prompt_line = format_temporal_grounding({**rows[0], "event_id": "D1:1", "time_role": "occurred_at"})
        self.assertIn("normalized='the Friday before 15 July 2023'", prompt_line)
        self.assertNotIn("2023-07-14", prompt_line)

    def test_month_and_duration_resolution_are_question_agnostic(self) -> None:
        month = ground_temporal_expressions(
            "We are going camping next month.",
            "1:14 pm on 25 May, 2023",
        )
        duration = ground_temporal_expressions(
            "Seven years now, and art still matters.",
            "12:09 am on 13 September, 2023",
        )

        self.assertEqual(month[0]["normalized_value"], "June 2023")
        self.assertEqual(duration[0]["normalized_value"], "since 2016 (7 years)")

    def test_weekend_resolution_records_a_real_weekend_interval(self) -> None:
        rows = ground_temporal_expressions(
            "We went camping two weekends ago.",
            "2:31 pm on 17 July, 2023",
        )

        self.assertEqual(rows[0]["normalized_value"], "2 weekends before 17 July 2023")
        self.assertEqual(rows[0]["resolved_start"], "2023-07-08")
        self.assertEqual(rows[0]["resolved_end"], "2023-07-09")

    def test_answer_prompt_excludes_evaluator_labels(self) -> None:
        row = SimpleNamespace(
            sample_id="conv-test",
            question_id="conv-test::qa_0000",
            category=2,
            question_type="temporal",
            question="When did it happen?",
        )
        retrieval = graph_query_runner.RetrievalResult(
            candidate_dialog_ids=["D1:1"],
            temporal_lines=["event=D1:1 normalized='7 May 2023'"],
            claim_lines=["[supports] claim-1: D1:1 Caroline event: attended"],
            state_lines=[],
            relation_lines=[],
            context="<dialog id=\"D1:1\">yesterday</dialog>",
            trace={},
        )

        frame = {
            "entities": ["Caroline"],
            "required_bindings": [],
            "requested_slot": "date",
            "operation": "lookup",
            "count_unit": "none",
        }
        prompt = graph_query_runner.answer_user_prompt(row, retrieval, frame)

        self.assertNotIn("Official category", prompt)
        self.assertNotIn("Question type", prompt)
        self.assertNotIn("Question ID", prompt)
        self.assertNotIn("answer_shape", prompt)
        self.assertNotIn("inference_mode", prompt)
        self.assertIn('"operation": "lookup"', prompt)
        self.assertIn("7 May 2023", prompt)
        self.assertIn("[supports] claim-1", prompt)

        retrieval.trace["evidence_delivery"] = {
            "mode": "direct_graph_expansion",
            "selection_applied": False,
        }
        direct_prompt = graph_query_runner.answer_user_prompt(row, retrieval, frame)
        self.assertIn("Evidence handling mode:\ndirect_graph_expansion", direct_prompt)
        self.assertNotIn("selector failed twice", direct_prompt)


class RoleAwareGraphBuilderTests(unittest.TestCase):
    def test_v2_state_merge_is_the_default_build_schema(self) -> None:
        with patch.object(sys, "argv", ["graph_builder.py"]):
            args = graph_builder.parse_args()

        self.assertEqual(args.graph_schema, "v2")

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

    def test_v2_keeps_planned_claim_without_copying_a_state_facet(self) -> None:
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
                "value": "I plan to start pottery next month.",
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
        self.assertEqual(roles, {"occurred_at", "planned_for"})
        has_time = next(edge for edge in edges if edge["type"] == "HAS_TIME")
        self.assertEqual(has_time["time_role"], "planned_for")
        self.assertEqual(nodes[has_time["to"]]["value"], "next month")
        self.assertFalse(any(node.get("node_type") == "StateFacet" for node in nodes.values()))
        self.assertFalse(any(edge["type"] in {"SUPPORTS", "CURRENT_AFTER", "CURRENT_STATE_OF"} for edge in edges))
        self.assertEqual(graph_builder.validate_graph(nodes, edges, "v2"), [])

    def test_v2_defers_persistent_state_materialization_until_fold(self) -> None:
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
                "facet_key": "preference",
                "value": "Caroline likes pottery",
                "time_role": "",
                "time_value": "",
                "scope_labels": ["pottery"],
            },
            1,
            "v2",
        )

        self.assertIsNotNone(claim)
        self.assertFalse(any(node.get("node_type") == "StateFacet" for node in nodes.values()))
        self.assertFalse(any(edge["type"] == "SUPPORTS" for edge in edges))

    def test_v2_keeps_bounded_activity_as_claim_only(self) -> None:
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
                "facet_key": "activity",
                "value": "Caroline attended pottery class last Tuesday",
                "time_role": "occurred_at",
                "time_value": "last Tuesday",
                "scope_labels": ["pottery"],
            },
            1,
            "v2",
        )

        self.assertIsNotNone(claim)
        self.assertFalse(any(node.get("node_type") == "StateFacet" for node in nodes.values()))
        self.assertTrue(any(edge["type"] == "HAS_TIME" for edge in edges))
        self.assertEqual(graph_builder.validate_graph(nodes, edges, "v2"), [])

    def test_v2_keeps_explicitly_past_state_as_claim_only(self) -> None:
        self.assertFalse(
            graph_builder.v2_claim_is_persistent_state(
                {
                    "facet_key": "location",
                    "value": "Alex used to live in Paris",
                    "time_role": "",
                    "time_value": "",
                }
            )
        )
        self.assertTrue(
            graph_builder.v2_claim_is_persistent_state(
                {
                    "facet_key": "location",
                    "value": "Alex no longer lives in Paris",
                    "time_role": "",
                    "time_value": "",
                }
            )
        )

    def test_v2_subject_keys_merge_only_unambiguous_name_aliases(self) -> None:
        claims = [
            {"claim_id": "short", "subject": "Alex", "speaker": "Alex"},
            {"claim_id": "full", "subject": "Alex Morgan", "speaker": "Caroline"},
            {"claim_id": "family", "subject": "Alex's kids", "speaker": "Caroline"},
        ]

        graph_builder.assign_v2_subject_keys(claims)

        self.assertEqual(claims[0]["subject_key"], claims[1]["subject_key"])
        self.assertEqual(claims[0]["canonical_subject"], "Alex Morgan")
        self.assertEqual(claims[1]["canonical_subject"], "Alex Morgan")
        self.assertNotEqual(claims[2]["subject_key"], claims[0]["subject_key"])

    def test_v2_dimension_seed_separates_slot_from_current_value(self) -> None:
        occupation = graph_builder.v2_state_dimension_seed(
            {"facet_key": "work", "value": "Alex is a nurse", "scope_labels": []}
        )
        residence = graph_builder.v2_state_dimension_seed(
            {"facet_key": "place", "value": "Alex lives in Paris", "scope_labels": []}
        )
        pottery = graph_builder.v2_state_dimension_seed(
            {
                "facet_key": "preference",
                "value": "Alex likes pottery",
                "scope_labels": ["pottery"],
            }
        )
        unresolved = graph_builder.v2_state_dimension_seed(
            {"facet_key": "preference", "value": "Alex enjoys it", "scope_labels": []}
        )

        self.assertEqual(occupation["state_dimension"], "occupation:primary")
        self.assertEqual(residence["state_dimension"], "location:residence")
        self.assertEqual(pottery["state_dimension"], "preference:pottery")
        self.assertIsNone(unresolved)

    def test_v2_dimension_fallback_uses_one_claim_only(self) -> None:
        claim = {
            "claim_id": "music",
            "dialog_id": "D1:1",
            "subject": "Alex",
            "facet_key": "preference",
            "value": "Alex enjoys it",
            "scope_labels": [],
        }
        client = StubJsonClient(
            {
                "slot_type": "object_scoped",
                "state_target": "live music",
                "reason": "The preference is about live music.",
            }
        )

        dimension = graph_builder.resolve_v2_state_dimension(client, claim)

        self.assertEqual(dimension["state_dimension"], "preference:live_music")
        self.assertEqual(dimension["dimension_source"], "llm_single_claim")

    def test_v2_dimension_fallback_abstains_from_generic_owner_domain_target(self) -> None:
        first_claim = {
            "claim_id": "nate-books",
            "dialog_id": "D9:12",
            "subject": "Nate",
            "subject_key": "nate",
            "facet_key": "preference",
            "value": "the world building, battles, and storytelling always blow me away",
            "scope_labels": [],
        }
        second_claim = {
            **first_claim,
            "claim_id": "nate-small-things",
            "dialog_id": "D13:15",
            "value": "those little things",
        }
        client = StubJsonClient(
            {
                "slot_type": "object_scoped",
                "state_target": "Nate's preference",
                "reason": "The Claim describes Nate's preference.",
            }
        )

        first_dimension = graph_builder.resolve_v2_state_dimension(client, first_claim)
        second_dimension = graph_builder.resolve_v2_state_dimension(client, second_claim)

        self.assertEqual(first_dimension["dimension_source"], "deterministic_claim_local_abstention")
        self.assertTrue(first_dimension["state_dimension"].startswith("preference:claim_local_"))
        self.assertNotEqual(first_dimension["state_dimension"], second_dimension["state_dimension"])

    def test_v2_dimension_fallback_treats_health_condition_as_generic(self) -> None:
        claim = {
            "claim_id": "joanna-allergy",
            "dialog_id": "D24:6",
            "subject": "Joanna",
            "subject_key": "joanna",
            "facet_key": "health",
            "value": "I got allergic and we had to get rid of her",
            "scope_labels": [],
        }
        client = StubJsonClient(
            {
                "slot_type": "object_scoped",
                "state_target": "Joanna's health condition",
                "reason": "The Claim describes Joanna's health condition.",
            }
        )

        dimension = graph_builder.resolve_v2_state_dimension(client, claim)

        self.assertEqual(dimension["dimension_source"], "deterministic_claim_local_abstention")
        self.assertTrue(dimension["state_dimension"].startswith("health:claim_local_"))

    def test_v2_single_slot_cannot_split_into_different_targets(self) -> None:
        existing = {
            "claim_id": "paris",
            "dialog_id": "D1:1",
            "source_event_id": "D1:1",
            "slot_type": "single",
            "state_dimension": "location:residence",
        }
        incoming = {
            "claim_id": "berlin",
            "dialog_id": "D2:1",
            "source_event_id": "D2:1",
            "slot_type": "single",
            "state_dimension": "location:residence",
        }

        with self.assertRaisesRegex(ValueError, "single state slot"):
            graph_builder.normalize_v2_merge_decision(
                {
                    "decision": "DIFFERENT_TARGET",
                    "winner": "none",
                    "reason": "incorrect split",
                    "evidence_event_ids": ["D1:1", "D2:1"],
                },
                existing,
                incoming,
            )

        nodes = {
            state_id: {
                "node_type": "StateFacet",
                "facet_id": state_id,
                "slot_type": "single",
                "subject_key": "alex",
                "state_dimension": "location:residence",
            }
            for state_id in ("paris-state", "berlin-state")
        }
        self.assertIn(
            "v2_single_slot_active_count:alex:location:residence:2",
            graph_builder.validate_graph(nodes, [], "v2"),
        )

    def test_v2_merge_normalizer_clears_winner_for_non_lifecycle_decisions(self) -> None:
        existing = {"dialog_id": "D1:1", "source_event_id": "D1:1"}
        incoming = {"dialog_id": "D2:1", "source_event_id": "D2:1"}

        for decision in ("COMPATIBLE", "DIFFERENT_TARGET", "CONFLICTS_WITH"):
            with self.subTest(decision=decision):
                result = graph_builder.normalize_v2_merge_decision(
                    {
                        "decision": decision,
                        "winner": "incoming",
                        "reason": "synthetic malformed model output",
                        "evidence_event_ids": ["D1:1", "D2:1"],
                    },
                    existing,
                    incoming,
                )

                self.assertEqual(result["winner"], "none")

    def test_v2_fold_merges_support_and_tracks_lifecycle(self) -> None:
        claims = [
            {
                "claim_id": "pottery-old",
                "dialog_id": "D1:1",
                "source_event_id": "D1:1",
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "pottery",
                "state_dimension": "preference:pottery",
            },
            {
                "claim_id": "music",
                "dialog_id": "D2:1",
                "source_event_id": "D2:1",
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "live_music",
                "state_dimension": "preference:live_music",
            },
            {
                "claim_id": "pottery-detail",
                "dialog_id": "D3:1",
                "source_event_id": "D3:1",
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "pottery",
                "state_dimension": "preference:pottery",
            },
            {
                "claim_id": "pottery-new",
                "dialog_id": "D4:1",
                "source_event_id": "D4:1",
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "pottery",
                "state_dimension": "preference:pottery",
            },
        ]
        decisions = {
            ("pottery-old", "pottery-detail"): "COMPATIBLE",
            ("pottery-detail", "pottery-new"): "SUPERSEDES",
        }
        compared_pairs = []

        def decide(existing, incoming):
            compared_pairs.append((existing["claim_id"], incoming["claim_id"]))
            decision = decisions[(existing["claim_id"], incoming["claim_id"])]
            return {
                "decision": decision,
                "winner": "incoming" if decision == "SUPERSEDES" else "none",
                "reason": "synthetic merge decision",
                "evidence_event_ids": [existing["source_event_id"], incoming["source_event_id"]],
            }

        clusters, relations = graph_builder.fold_v2_state_claims(claims, decide, candidate_limit=24)

        pottery_clusters = [row for row in clusters if row["state_dimension"] == "preference:pottery"]
        music_cluster = next(row for row in clusters if row["state_dimension"] == "preference:live_music")
        historical = next(row for row in pottery_clusters if row["status"] == "historical")
        current = next(row for row in pottery_clusters if row["status"] == "current")
        self.assertEqual(historical["support_claim_ids"], ["pottery-old", "pottery-detail"])
        self.assertEqual(current["support_claim_ids"], ["pottery-new"])
        self.assertEqual(music_cluster["status"], "current")
        self.assertEqual(relations[0]["type"], "SUPERSEDES")
        self.assertEqual(relations[0]["from"], "pottery-new")
        self.assertEqual(relations[0]["to"], "pottery-detail")
        self.assertEqual(
            compared_pairs,
            [
                ("pottery-old", "pottery-detail"),
                ("pottery-detail", "pottery-new"),
            ],
        )

    def test_v2_fold_does_not_keep_conflict_ambiguous_after_one_branch_retires(self) -> None:
        claims = [
            {
                "claim_id": claim_id,
                "dialog_id": dialog_id,
                "source_event_id": dialog_id,
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "pottery",
                "state_dimension": "preference:pottery",
            }
            for claim_id, dialog_id in (("branch-a", "D1:1"), ("branch-b", "D2:1"), ("replacement", "D3:1"))
        ]
        decisions = {
            ("branch-a", "branch-b"): ("CONFLICTS_WITH", "none"),
            ("branch-b", "replacement"): ("DIFFERENT_TARGET", "none"),
            ("branch-a", "replacement"): ("SUPERSEDES", "incoming"),
        }

        def decide(existing, incoming):
            decision, winner = decisions[(existing["claim_id"], incoming["claim_id"])]
            return {
                "decision": decision,
                "winner": winner,
                "reason": "synthetic branch transition",
                "evidence_event_ids": [existing["source_event_id"], incoming["source_event_id"]],
            }

        clusters, _relations = graph_builder.fold_v2_state_claims(claims, decide, candidate_limit=24)
        by_primary = {cluster["primary_claim_id"]: cluster for cluster in clusters}

        self.assertEqual(by_primary["branch-a"]["status"], "historical")
        self.assertEqual(by_primary["branch-b"]["status"], "current")
        self.assertEqual(by_primary["replacement"]["status"], "current")

    def test_v2_fold_compares_incoming_with_current_cluster_representative_only(self) -> None:
        claims = [
            {
                "claim_id": claim_id,
                "dialog_id": dialog_id,
                "source_event_id": dialog_id,
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "pottery",
                "state_dimension": "preference:pottery",
            }
            for claim_id, dialog_id in (("support-a", "D1:1"), ("support-b", "D2:1"), ("incoming", "D3:1"))
        ]
        decisions = {
            ("support-a", "support-b"): "COMPATIBLE",
            ("support-b", "incoming"): "COMPATIBLE",
        }
        compared_pairs = []

        def decide(existing, incoming):
            compared_pairs.append((existing["claim_id"], incoming["claim_id"]))
            decision = decisions[(existing["claim_id"], incoming["claim_id"])]
            return {
                "decision": decision,
                "winner": "none",
                "reason": "synthetic support coherence check",
                "evidence_event_ids": [existing["source_event_id"], incoming["source_event_id"]],
            }

        clusters, relations = graph_builder.fold_v2_state_claims(claims, decide, candidate_limit=24)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["support_claim_ids"], ["support-a", "support-b", "incoming"])
        self.assertEqual(relations, [])
        self.assertEqual(compared_pairs, [("support-a", "support-b"), ("support-b", "incoming")])

    def test_v2_fold_compatible_bridge_reconciles_active_conflict_branches(self) -> None:
        claims = [
            {
                "claim_id": claim_id,
                "dialog_id": dialog_id,
                "source_event_id": dialog_id,
                "subject_key": "nate",
                "canonical_subject": "Nate",
                "state_domain": "occupation",
                "state_target": "primary",
                "state_dimension": "occupation:primary",
            }
            for claim_id, dialog_id in (("career-a", "D1:1"), ("career-b", "D2:1"), ("bridge", "D3:1"))
        ]
        decisions = {
            ("career-a", "career-b"): "CONFLICTS_WITH",
            ("career-b", "bridge"): "COMPATIBLE",
            ("career-a", "bridge"): "COMPATIBLE",
        }

        def decide(existing, incoming):
            decision = decisions[(existing["claim_id"], incoming["claim_id"])]
            return {
                "decision": decision,
                "winner": "none",
                "reason": "synthetic compatible bridge",
                "evidence_event_ids": [existing["source_event_id"], incoming["source_event_id"]],
            }

        clusters, relations = graph_builder.fold_v2_state_claims(claims, decide, candidate_limit=24)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["support_claim_ids"], ["career-a", "career-b", "bridge"])
        self.assertEqual(clusters[0]["primary_claim_id"], "bridge")
        self.assertEqual(clusters[0]["status"], "current")
        self.assertEqual(relations, [])

    def test_v2_fold_rejects_cross_dialog_existing_lifecycle_winner(self) -> None:
        claims = [
            {
                "claim_id": claim_id,
                "dialog_id": dialog_id,
                "source_event_id": dialog_id,
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "occupation",
                "state_target": "primary",
                "state_dimension": "occupation:primary",
            }
            for claim_id, dialog_id in (("earlier", "D1:1"), ("later", "D2:1"))
        ]

        def decide(existing, incoming):
            return {
                "decision": "SUPERSEDES",
                "winner": "existing",
                "reason": "invalid reverse chronology",
                "evidence_event_ids": [existing["source_event_id"], incoming["source_event_id"]],
            }

        with self.assertRaisesRegex(ValueError, "contradicts adapter chronology"):
            graph_builder.fold_v2_state_claims(claims, decide, candidate_limit=24)

    def test_v2_fold_fails_instead_of_silently_truncating_active_clusters(self) -> None:
        claims = [
            {
                "claim_id": claim_id,
                "dialog_id": dialog_id,
                "source_event_id": dialog_id,
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "pottery",
                "state_dimension": "preference:pottery",
            }
            for claim_id, dialog_id in (("target-a", "D1:1"), ("target-b", "D2:1"), ("third", "D3:1"))
        ]

        call_count = 0

        def decide(existing, incoming):
            nonlocal call_count
            call_count += 1
            return {
                "decision": "DIFFERENT_TARGET",
                "winner": "none",
                "reason": "synthetic target split",
                "evidence_event_ids": [existing["source_event_id"], incoming["source_event_id"]],
            }

        with self.assertRaisesRegex(ValueError, "active-cluster limit exceeded"):
            graph_builder.fold_v2_state_claims(claims, decide, candidate_limit=1)
        self.assertEqual(call_count, 1)

    def test_v2_fold_rejects_compatible_and_existing_winner_for_one_incoming_claim(self) -> None:
        claims = [
            {
                "claim_id": claim_id,
                "dialog_id": "D1:1",
                "source_event_id": "D1:1",
                "subject_key": "alex",
                "canonical_subject": "Alex",
                "state_domain": "preference",
                "state_target": "pottery",
                "state_dimension": "preference:pottery",
            }
            for claim_id in ("target-a", "target-b", "incoming")
        ]
        decisions = {
            ("target-a", "target-b"): ("DIFFERENT_TARGET", "none"),
            ("target-b", "incoming"): ("COMPATIBLE", "none"),
            ("target-a", "incoming"): ("SUPERSEDES", "existing"),
        }

        def decide(existing, incoming):
            decision, winner = decisions[(existing["claim_id"], incoming["claim_id"])]
            return {
                "decision": decision,
                "winner": winner,
                "reason": "synthetic inconsistent vector",
                "evidence_event_ids": ["D1:1"],
            }

        with self.assertRaisesRegex(ValueError, "both compatible with and retired"):
            graph_builder.fold_v2_state_claims(claims, decide, candidate_limit=24)

    def test_v2_materializes_and_validates_one_multi_support_state(self) -> None:
        second_turn = DialogTurn(
            dia_id="D2:1",
            session_id="S2",
            session_index=2,
            session_date_time="2024-02-10 10:00:00",
            speaker="Caroline",
            text="I still enjoy weekly pottery classes.",
            image_caption="",
            image_query="",
        )
        nodes = {}
        edges = []
        turns = {self.turn.dia_id: self.turn, second_turn.dia_id: second_turn}
        for turn in turns.values():
            graph_builder.materialize_base_event(nodes, edges, "conv-test", turn, "v2")
        claims = []
        for index, raw_claim in enumerate(
            (
                {
                    "dialog_id": self.turn.dia_id,
                    "subject": "Caroline",
                    "facet_key": "preference",
                    "value": "Caroline likes pottery",
                    "scope_labels": ["pottery"],
                },
                {
                    "dialog_id": second_turn.dia_id,
                    "subject": "Caroline",
                    "facet_key": "preference",
                    "value": "Caroline still enjoys weekly pottery classes",
                    "scope_labels": ["pottery"],
                },
            ),
            start=1,
        ):
            claim = graph_builder.materialize_claim(
                nodes,
                edges,
                "conv-test",
                turns,
                raw_claim,
                index,
                "v2",
            )
            self.assertIsNotNone(claim)
            claims.append(claim)

        client = StubJsonClient(
            {
                "decision": "COMPATIBLE",
                "winner": "none",
                "reason": "Both Claims describe the same continuing pottery preference.",
                "evidence_event_ids": ["D1:1", "D2:1"],
            }
        )
        persistent_claims, clusters, relations = graph_builder.resolve_v2_state_clusters(
            claims,
            client=client,
            candidate_limit=24,
        )
        facets = graph_builder.materialize_v2_state_facets(
            nodes,
            edges,
            "conv-test",
            persistent_claims,
            clusters,
        )

        self.assertEqual(relations, [])
        self.assertEqual(len(facets), 1)
        self.assertEqual(facets[0]["support_claim_ids"], [claims[0]["claim_id"], claims[1]["claim_id"]])
        self.assertEqual(facets[0]["primary_claim_id"], claims[1]["claim_id"])
        self.assertEqual(facets[0]["state_dimension"], "preference:pottery")
        self.assertEqual(graph_builder.validate_graph(nodes, edges, "v2"), [])
        facets[0]["status"] = "historical"
        self.assertIn(
            f'v2_state_status_relation_mismatch:{facets[0]["facet_id"]}:historical:expected=current',
            graph_builder.validate_graph(nodes, edges, "v2"),
        )

    def test_v2_build_path_uses_deterministic_singleton_without_resolver_call(self) -> None:
        raw_claim = {
            "dialog_id": self.turn.dia_id,
            "subject": "Caroline",
            "facet_key": "preference",
            "value": "Caroline likes pottery",
            "scope_labels": ["pottery"],
        }
        with (
            patch.object(
                graph_builder,
                "load_sample",
                return_value=SimpleNamespace(sample_id="conv-test", turns=(self.turn,)),
            ),
            patch.object(graph_builder, "extract_llm_claims", return_value=([raw_claim], [])),
            patch.object(graph_builder, "file_sha256", side_effect=["d" * 64, "b" * 64]),
        ):
            graph = graph_builder.build_sample_graph(
                data_path=Path("fixture.json"),
                sample_id="conv-test",
                claim_mode="llm",
                resolver_mode="none",
                client=FailingJsonClient(),
                runtime=None,
                provider=None,
                model=None,
                max_tokens=4096,
                message_chunk_size=16,
                claim_workers=1,
                resolver_workers=1,
                resolver_candidate_limit=24,
                max_claims_per_turn=2,
                event_limit=0,
                graph_schema="v2",
            )

        states = [node for node in graph["nodes"] if node.get("node_type") == "StateFacet"]
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["state_dimension"], "preference:pottery")
        self.assertEqual(graph["manifest"]["schema_version"], graph_builder.GRAPH_SCHEMA_V2)
        self.assertEqual(graph["summary"]["warnings"], [])
        self.assertEqual(graph_builder.default_output_dir("v2").name, "locomo_qa_sample_graph_v2_state_merge")
        self.assertEqual(
            graph_builder.default_cache_path("v2").name,
            "llm_cache.locomo_qa_graph_builder.v2_state_merge.json",
        )

    def test_v2_same_dialog_merge_uses_semantics_instead_of_claim_list_order(self) -> None:
        existing = {
            "claim_id": "state-new",
            "dialog_id": "D1:1",
            "source_event_id": "D1:1",
            "value": "Caroline no longer likes pottery",
        }
        incoming = {
            "claim_id": "state-old",
            "dialog_id": "D1:1",
            "source_event_id": "D1:1",
            "value": "Caroline likes pottery",
        }

        accepted = graph_builder.normalize_v2_merge_decision(
            {
                "decision": "SUPERSEDES",
                "winner": "existing",
                "reason": "The existing Claim explicitly ends the preference.",
                "evidence_event_ids": ["D1:1"],
            },
            existing,
            incoming,
        )

        self.assertEqual(accepted["winner"], "existing")
        self.assertIn(
            "list order does not prove clause chronology",
            graph_builder.v2_merge_user_prompt(existing, incoming),
        )

    def test_v2_old_relation_bucket_path_is_disabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "produced only by fold_v2_state_claims"):
            graph_builder.relation_buckets([], candidate_limit=24, graph_schema="v2")

    def test_v2_claim_prompt_uses_the_full_facet_ontology(self) -> None:
        prompt = graph_builder.claim_user_prompt(
            "conv-test",
            [self.turn],
            max_claims_per_turn=2,
            graph_schema="v2",
        )

        expected_enum = "|".join(sorted(graph_builder.FACET_KEYS))
        self.assertIn(f'"facet_key": "{expected_enum}"', prompt)

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
                "value": "I plan to start pottery next month.",
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
    def test_active_v2_query_contract_rejects_invalid_primary(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_query_runner.ACTIVE_GRAPH_SCHEMA_V2
        graph.manifest = {
            "state_resolution": {
                "mode": "ordered_state_fold",
                "dimension_key": "state_dimension",
            }
        }
        graph.claims = {"claim": {"source_event_id": "D1:1"}}
        graph.states = {
            "state": {
                "subject_key": "alex",
                "state_domain": "occupation",
                "slot_type": "single",
                "state_target": "primary",
                "state_dimension": "occupation:primary",
                "status": "current",
                "primary_claim_id": "missing",
                "support_claim_ids": ["claim"],
                "support_event_ids": ["D1:1"],
            }
        }
        graph.states_by_claim = defaultdict(list, {"claim": ["state"]})

        with self.assertRaisesRegex(ValueError, "primary_claim_id=missing"):
            graph._validate_state_merge_query_contract()

    def test_recent_event_rerank_adds_bounded_newest_first_score(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {
            "D1:1": {"event_id": "D1:1", "occurred_at": "2024-01-01"},
            "D2:1": {"event_id": "D2:1", "occurred_at": "2024-02-01"},
        }
        graph.claims = {}
        graph.states = {}
        graph.claims_by_event = defaultdict(list)
        graph.states_by_claim = defaultdict(list)
        graph.times_by_claim = defaultdict(list)
        graph.current_time_by_state = {}
        graph.occurred_time_by_event = {}
        graph.occurred_time_id_by_event = {}
        rows = [
            {"doc_id": "event::D1:1", "score": 1.0, "lexical_rank": 1, "embedding_rank": None},
            {"doc_id": "event::D2:1", "score": 1.0, "lexical_rank": 2, "embedding_rank": None},
        ]

        ranked = graph._rerank_event_rows(rows, ["occurred_at"], 2, "newest_first")

        self.assertEqual(ranked[0]["event_id"], "D2:1")
        self.assertEqual(ranked[0]["recency_score"], graph_query_runner.RECENCY_RANK_BOOST)

    def test_recent_event_rerank_prefers_semantic_fact_time_over_late_report_time(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {
            "D2:1": {"event_id": "D2:1", "occurred_at": "2024-12-15"},
            "D3:1": {"event_id": "D3:1", "occurred_at": "2025-06-01"},
        }
        graph.claims = {
            "recent-fact": {"time_role": "occurred_at", "resolved_time_start": "2024-12-01"},
            "late-old-report": {"time_role": "occurred_at", "resolved_time_start": "2020-01-01"},
        }
        graph.states = {}
        graph.claims_by_event = defaultdict(
            list,
            {"D2:1": ["recent-fact"], "D3:1": ["late-old-report"]},
        )
        graph.states_by_claim = defaultdict(list)
        graph.times_by_claim = defaultdict(list)
        graph.current_time_by_state = {}
        graph.occurred_time_by_event = {}
        graph.occurred_time_id_by_event = {}
        rows = [
            {"doc_id": "event::D2:1", "score": 1.0, "lexical_rank": 2, "embedding_rank": None},
            {"doc_id": "event::D3:1", "score": 1.0, "lexical_rank": 1, "embedding_rank": None},
        ]

        ranked = graph._rerank_event_rows(rows, ["occurred_at"], 2, "newest_first")

        self.assertEqual(ranked[0]["event_id"], "D2:1")

    def test_recent_event_rerank_compares_fact_and_report_fallback_on_one_timeline(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {
            "D1:1": {"event_id": "D1:1", "occurred_at": "2020-01-01"},
            "D2:1": {"event_id": "D2:1", "occurred_at": "2025-01-01"},
        }
        graph.claims = {
            "old-fact": {"time_role": "occurred_at", "resolved_time_start": "2010-01-01"},
            "new-report": {"time_role": "occurred_at"},
        }
        graph.states = {}
        graph.claims_by_event = defaultdict(list, {"D1:1": ["old-fact"], "D2:1": ["new-report"]})
        graph.states_by_claim = defaultdict(list)
        graph.times_by_claim = defaultdict(list)
        graph.current_time_by_state = {}
        graph.occurred_time_by_event = {}
        graph.occurred_time_id_by_event = {}
        rows = [
            {"doc_id": "event::D1:1", "score": 1.0, "lexical_rank": 2, "embedding_rank": None},
            {"doc_id": "event::D2:1", "score": 1.0, "lexical_rank": 1, "embedding_rank": None},
        ]

        ranked = graph._rerank_event_rows(rows, ["occurred_at"], 2, "newest_first")

        self.assertEqual(ranked[0]["event_id"], "D2:1")

    def test_state_evidence_uses_primary_and_relation_witness_not_redundant_supports(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_query_runner.ACTIVE_GRAPH_SCHEMA_V2
        graph.manifest = {}
        relation = {"type": "CONFLICTS_WITH", "from": "old-witness", "to": "other"}
        graph.states = {
            "state": {
                "primary_claim_id": "latest",
                "support_claim_ids": ["duplicate-1", "old-witness", "duplicate-2", "latest"],
            }
        }
        graph.claims = {
            "duplicate-1": {"source_event_id": "D1:1"},
            "old-witness": {"source_event_id": "D2:1"},
            "duplicate-2": {"source_event_id": "D3:1"},
            "latest": {"source_event_id": "D4:1"},
            "other": {"source_event_id": "D5:1"},
        }
        graph.events = {f"D{index}:1": {} for index in range(1, 6)}
        graph.claims_by_event = defaultdict(list)
        graph.relations_by_claim = defaultdict(list, {"old-witness": [relation]})

        self.assertEqual(
            graph._state_evidence_claim_ids("state"),
            ["latest", "old-witness", "other"],
        )
        self.assertEqual(graph._state_required_event_ids("state"), ["D4:1", "D2:1", "D5:1"])

    def test_v2_relation_continuity_uses_stable_state_dimension(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.claims = {
            "pottery": {
                "subject_key": "alex",
                "facet_key": "preference",
                "state_dimension": "preference:pottery",
            },
            "music": {
                "subject_key": "alex",
                "facet_key": "preference",
                "state_dimension": "preference:live_music",
            },
        }

        self.assertNotEqual(
            graph._claim_relation_continuity_key("pottery"),
            graph._claim_relation_continuity_key("music"),
        )

    def test_v2_subject_key_resolves_query_identity(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.claims = {
            "claim": {
                "subject": "Melanie",
                "canonical_subject": "Melanie and another person",
                "subject_key": "melanie_and_another_person",
            }
        }
        graph.states = {}

        self.assertEqual(
            graph.resolve_query_subject_ids(["Melanie"]),
            ["melanie_and_another_person"],
        )

    def test_v2_state_line_exposes_dimension_status_primary_and_compact_support_count(self) -> None:
        line = graph_query_runner.format_state_line(
            {
                "subject": "Alex",
                "subject_key": "alex",
                "facet_key": "occupation",
                "state_domain": "occupation",
                "state_target": "primary",
                "state_dimension": "occupation:primary",
                "slot_type": "single",
                "status": "ambiguous",
                "value": "nurse",
                "primary_claim_id": "claim-new",
                "support_claim_ids": ["claim-old", "claim-new"],
                "support_event_ids": ["D1:1", "D2:1"],
            }
        )

        self.assertIn("dimension=occupation:primary", line)
        self.assertIn("slot_type=single", line)
        self.assertIn("status=ambiguous", line)
        self.assertIn("primary_claim=claim-new", line)
        self.assertIn("support_count=2", line)
        self.assertNotIn("claim-old", line)

    def test_current_after_event_recency_uses_linked_state_time(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {"D1:1": {"occurred_at": "2020-01-01"}}
        graph.claims = {"claim": {"resolved_time_start": "2010-01-01", "time_role": "occurred_at"}}
        graph.states = {"state": {"fact_type": "state", "temporal_status": "ongoing", "intent": "none", "current_after": "2025-01-01"}}
        graph.claims_by_event = defaultdict(list, {"D1:1": ["claim"]})
        graph.states_by_claim = defaultdict(list, {"claim": ["state"]})
        graph.current_time_by_state = {}
        graph.occurred_time_by_event = {}

        key = graph._event_recency_key("D1:1", ["CURRENT_AFTER"])

        self.assertEqual(key[0], "2025-01-01T00:00:00")

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
            max_context_events=8,
            max_state_lines=8,
        )

        self.assertEqual(event_ids, ["D1:1", "D2:1"])
        self.assertEqual(state_ids, ["state-old", "state-new"])
        self.assertEqual(trace["relation_edge_count"], 1)
        self.assertEqual(trace["visited_claim_ids"], ["claim-old", "claim-new"])
        self.assertEqual(len(relation_lines), 1)

    def test_relation_expansion_ignores_unrelated_claim_in_same_seed_event(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        graph.events = {
            "D1:1": {"event_id": "D1:1"},
            "D2:1": {"event_id": "D2:1"},
        }
        graph.claims = {
            "relevant": {
                "claim_id": "relevant",
                "source_event_id": "D1:1",
                "value": "visited the LGBTQ support group",
                "canonical_state_group_id": "visit",
            },
            "unrelated": {
                "claim_id": "unrelated",
                "source_event_id": "D1:1",
                "value": "plans to work in counseling",
                "canonical_state_group_id": "career",
            },
            "career-old": {
                "claim_id": "career-old",
                "source_event_id": "D2:1",
                "value": "considered a counseling career",
                "canonical_state_group_id": "career",
            },
        }
        graph.states = {}
        graph.claims_by_event = defaultdict(
            list,
            {"D1:1": ["unrelated", "relevant"], "D2:1": ["career-old"]},
        )
        graph.states_by_claim = defaultdict(list)
        relation = {
            "type": "SUPERSEDES",
            "from": "unrelated",
            "to": "career-old",
            "evidence_event_ids": ["D2:1"],
        }
        graph.relations_by_claim = defaultdict(
            list,
            {"unrelated": [relation], "career-old": [relation]},
        )

        event_ids, _state_ids, relation_lines, trace = graph._expand_relation_aware(
            ["D1:1"],
            max_context_events=8,
            max_state_lines=8,
            retrieval_queries=["When did they visit the LGBTQ support group?"],
        )

        self.assertEqual(event_ids, ["D1:1"])
        self.assertEqual(relation_lines, [])
        self.assertEqual(trace["visited_claim_ids"], ["unrelated", "relevant"])
        self.assertEqual(trace["skipped_relation_claim_ids"], ["unrelated"])

    def test_relation_expansion_closes_the_query_anchored_state_group(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        graph.events = {
            f"D{index}:1": {"event_id": f"D{index}:1"}
            for index in range(1, 5)
        }
        graph.claims = {
            f"claim-{index}": {
                "claim_id": f"claim-{index}",
                "source_event_id": f"D{index}:1",
                "value": f"residence update {index}",
                "canonical_subject_id": "person",
                "canonical_state_group_id": "residence",
            }
            for index in range(1, 5)
        }
        graph.states = {}
        graph.claims_by_event = defaultdict(
            list,
            {f"D{index}:1": [f"claim-{index}"] for index in range(1, 5)},
        )
        graph.states_by_claim = defaultdict(list)
        graph.relations_by_claim = defaultdict(list)
        for index in range(1, 4):
            edge = {
                "type": "SUPERSEDES",
                "from": f"claim-{index}",
                "to": f"claim-{index + 1}",
                "evidence_event_ids": [f"D{index + 1}:1"],
            }
            graph.relations_by_claim[f"claim-{index}"].append(edge)
            graph.relations_by_claim[f"claim-{index + 1}"].append(edge)

        event_ids, _state_ids, _relation_lines, trace = graph._expand_relation_aware(
            ["D1:1"],
            max_context_events=8,
            max_state_lines=8,
            retrieval_queries=["What is the residence update?"],
        )

        self.assertEqual(event_ids, ["D1:1", "D2:1", "D3:1", "D4:1"])
        self.assertEqual(
            trace["relation_expansion_strategy"],
            "query-anchored-state-group-closure",
        )
        self.assertEqual(trace["max_observed_relation_hops"], 3)
        self.assertIn("claim-4", trace["visited_claim_ids"])

    def test_relation_expansion_stops_when_state_group_changes(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        graph.events = {
            "D1:1": {"event_id": "D1:1"},
            "D2:1": {"event_id": "D2:1"},
        }
        graph.claims = {
            "residence": {
                "claim_id": "residence",
                "source_event_id": "D1:1",
                "value": "lives in Paris",
                "canonical_subject_id": "person",
                "canonical_state_group_id": "residence-group",
            },
            "career": {
                "claim_id": "career",
                "source_event_id": "D2:1",
                "value": "works as a counselor",
                "canonical_subject_id": "person",
                "canonical_state_group_id": "career-group",
            },
        }
        graph.states = {}
        graph.claims_by_event = defaultdict(
            list,
            {"D1:1": ["residence"], "D2:1": ["career"]},
        )
        graph.states_by_claim = defaultdict(list)
        edge = {
            "type": "SUPERSEDES",
            "from": "residence",
            "to": "career",
            "evidence_event_ids": ["D2:1"],
        }
        graph.relations_by_claim = defaultdict(
            list,
            {"residence": [edge], "career": [edge]},
        )

        event_ids, _state_ids, relation_lines, trace = graph._expand_relation_aware(
            ["D1:1"],
            max_context_events=8,
            max_state_lines=8,
            retrieval_queries=["Where does the person live?"],
        )

        self.assertEqual(event_ids, ["D1:1"])
        self.assertEqual(relation_lines, [])
        self.assertEqual(len(trace["skipped_relation_edges"]), 1)
        self.assertEqual(
            trace["skipped_relation_edges"][0]["reason"],
            "relation_continuity_mismatch",
        )

    def test_statefacet_limit_uses_path_relevance_not_claim_storage_order(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        graph.events = {"D1:1": {"event_id": "D1:1"}}
        graph.claims = {
            "irrelevant": {
                "claim_id": "irrelevant",
                "source_event_id": "D1:1",
                "value": "likes painting",
            },
            "relevant": {
                "claim_id": "relevant",
                "source_event_id": "D1:1",
                "value": "currently lives in Paris",
                "state_object": "Paris residence",
            },
        }
        graph.states = {
            "painting-state": {
                "facet_id": "painting-state",
                "support_claim_ids": ["irrelevant"],
                "support_event_ids": ["D1:1"],
            },
            "residence-state": {
                "facet_id": "residence-state",
                "support_claim_ids": ["relevant"],
                "support_event_ids": ["D1:1"],
            },
        }
        graph.claims_by_event = defaultdict(
            list,
            {"D1:1": ["irrelevant", "relevant"]},
        )
        graph.states_by_claim = defaultdict(
            list,
            {"irrelevant": ["painting-state"], "relevant": ["residence-state"]},
        )
        graph.relations_by_claim = defaultdict(list)

        _event_ids, state_ids, _relation_lines, trace = graph._expand_relation_aware(
            ["D1:1"],
            max_context_events=8,
            max_state_lines=1,
            retrieval_queries=["Where does the person currently live? Paris residence"],
        )

        self.assertEqual(state_ids, ["residence-state"])
        self.assertGreater(
            trace["state_priority"]["residence-state"]["claim_relevance"],
            0.0,
        )

    def test_scope_coverage_expansion_adds_ranked_nonredundant_scope_neighbor(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        graph.event_state_enrichment = False
        graph.events = {
            "D1:1": {"event_id": "D1:1", "text": "Joanna writes screenplays"},
            "D2:1": {"event_id": "D2:1", "text": "Joanna writes screenplays for films"},
            "D3:1": {"event_id": "D3:1", "text": "Joanna keeps a journal"},
            "D4:1": {"event_id": "D4:1", "text": "Nate walks turtles"},
        }
        graph.claims = {
            "claim-1": {"claim_id": "claim-1", "source_event_id": "D1:1", "graph_text": "writes screenplays"},
            "claim-2": {"claim_id": "claim-2", "source_event_id": "D2:1", "graph_text": "writes screenplays for films"},
            "claim-3": {"claim_id": "claim-3", "source_event_id": "D3:1", "graph_text": "keeps a journal"},
            "claim-4": {"claim_id": "claim-4", "source_event_id": "D4:1", "graph_text": "walks turtles"},
        }
        graph.states = {
            f"state-{index}": {
                "facet_id": f"state-{index}",
                "support_claim_ids": [f"claim-{index}"],
                "support_event_ids": [f"D{index}:1"],
            }
            for index in range(1, 5)
        }
        graph.claims_by_event = defaultdict(
            list,
            {f"D{index}:1": [f"claim-{index}"] for index in range(1, 5)},
        )
        graph.states_by_claim = defaultdict(
            list,
            {f"claim-{index}": [f"state-{index}"] for index in range(1, 5)},
        )
        graph.relations_by_claim = defaultdict(list)
        graph.scopes_by_event = defaultdict(
            list,
            {"D1:1": ["scope-joanna"], "D2:1": ["scope-joanna"], "D3:1": ["scope-joanna"], "D4:1": ["scope-nate"]},
        )
        graph.scopes = {}

        event_ids, state_ids, _relation_lines, trace = graph._expand_scope_coverage(
            ["D1:1"],
            event_candidate_rows=[
                {"doc_id": "event::D1:1", "score": 1.0},
                {"doc_id": "event::D2:1", "score": 0.9},
                {"doc_id": "event::D3:1", "score": 0.8},
                {"doc_id": "event::D4:1", "score": 0.7},
            ],
            max_context_events=3,
            max_state_lines=3,
        )

        self.assertEqual(event_ids, ["D1:1", "D2:1", "D3:1"])
        self.assertEqual(state_ids, ["state-1", "state-2", "state-3"])
        self.assertNotIn("D4:1", event_ids)
        self.assertEqual(trace["mode"], "scope-coverage")
        self.assertEqual(trace["scope_neighbor_candidate_count"], 2)

    def test_event_time_routing_excludes_universal_dialog_timestamp(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.claims_by_event = defaultdict(list, {"D1:1": ["claim-1"], "D1:2": []})
        graph.claims = {"claim-1": {"time_role": "planned_for"}}
        graph.times_by_claim = defaultdict(list)
        graph.states_by_claim = defaultdict(list)

        self.assertEqual(graph._event_routing_time_roles("D1:1"), ["planned_for"])
        self.assertEqual(graph._event_routing_time_roles("D1:2"), [])

    def test_event_state_enrichment_uses_only_linked_statefacets(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.event_state_enrichment = True
        graph.claims_by_event = defaultdict(list, {"D1:1": ["claim-1"]})
        graph.claims = {"claim-1": {"graph_text": "Caroline owns a necklace"}}
        graph.states_by_claim = defaultdict(list, {"claim-1": ["state-1"]})
        graph.states = {
            "state-1": {"subject": "Caroline", "facet_key": "possession", "value": "necklace from Sweden"},
            "state-unlinked": {"subject": "Melanie", "facet_key": "place", "value": "beach"},
        }
        graph.scopes_by_event = defaultdict(list)
        graph.scopes = {}

        document = graph._enhanced_event_document(
            "D1:1",
            {"speaker": "Caroline", "text": "It reminds me of home."},
        )

        self.assertIn("Caroline possession necklace from Sweden", document)
        self.assertNotIn("Melanie", document)

    def test_auto_expansion_preserves_v1_and_enables_v2(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V1
        self.assertEqual(graph.resolve_graph_expansion("auto"), "legacy")
        graph.schema_version = graph_builder.GRAPH_SCHEMA_V2
        self.assertEqual(graph.resolve_graph_expansion("auto"), "relation-aware")


class RetrievalPipelineTests(unittest.TestCase):
    def test_default_query_path_and_scope_backoff_use_active_scope_first_v2(self) -> None:
        self.assertEqual(
            graph_query_runner.default_query_graph_dir("conv-26"),
            graph_query_runner.EXTERNAL_GRAPH_DIR
            / "locomo_qa_sample_graph_v2_state_merge"
            / "conv-26",
        )
        args = graph_query_runner.parse_args([])
        self.assertEqual(args.scope_backoff_k, 0)
        self.assertFalse(hasattr(args, "state_search_k"))
        self.assertEqual(
            graph_query_runner.embedding_targets_for_variant("graph_embedding_scope_statefacet"),
            {"scope", "state"},
        )
        for variant in set(graph_query_runner.SUPPORTED_VARIANTS) - {"graph_embedding_scope_statefacet"}:
            self.assertNotIn("state", graph_query_runner.embedding_targets_for_variant(variant))
        self.assertEqual(args.max_state_lines, 8)
        self.assertEqual(args.max_ledger_states, 8)
        self.assertEqual(args.evidence_selector, "llm-ledger")
        self.assertEqual(
            graph_query_runner.parse_args(
                ["--evidence-selector", "deterministic"]
            ).evidence_selector,
            "deterministic",
        )
        self.assertEqual(
            graph_query_runner.parse_args(
                ["--evidence-selector", "direct"]
            ).evidence_selector,
            "direct",
        )

    def test_session_scopes_remain_in_graph_but_are_not_semantic_retrieval_documents(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {}
        graph.states = {}
        graph.scopes = {
            "scope-speaker": {"scope_type": "speaker", "label": "Speaker(Alice)", "value": "Alice"},
            "scope-entity": {"scope_type": "entity", "label": "Alice", "value": "Alice"},
            "scope-topic": {"scope_type": "topic", "label": "pottery", "value": "pottery"},
            "scope-session": {"scope_type": "session", "label": "Session(S1)", "value": "S1"},
            "scope-sample": {"scope_type": "sample", "label": "sample", "value": "sample"},
        }

        _event_ids, _event_docs, scope_doc_ids, _scope_docs, _state_ids, _state_docs = graph._build_documents()

        self.assertEqual(
            scope_doc_ids,
            ["scope::scope-entity", "scope::scope-speaker", "scope::scope-topic"],
        )
        self.assertIn("scope-session", graph.scopes)
        self.assertEqual(
            graph_query_runner.parse_scope_types("speaker,entity,topic,session"),
            ["speaker", "entity", "topic"],
        )
        self.assertEqual(
            graph.resolve_anchor_scope_doc_ids(["Alice's son"]),
            ["scope::scope-entity", "scope::scope-speaker"],
        )
        self.assertEqual(
            graph.resolve_anchor_scope_doc_ids(["Alice's son"], ["topic"]),
            [],
        )
        self.assertEqual(graph.resolve_anchor_scope_doc_ids(["pottery"]), [])
        self.assertEqual(graph_query_runner.parse_args([]).scope_anchor_routing, "off")
        self.assertEqual(
            graph_query_runner.parse_args(
                ["--scope-anchor-routing", "reserve"]
            ).scope_anchor_routing,
            "reserve",
        )
        self.assertEqual(graph_query_runner.parse_args([]).binding_gate, "off")
        self.assertEqual(
            graph_query_runner.parse_args(
                ["--binding-gate", "participant"]
            ).binding_gate,
            "participant",
        )

    def test_participant_binding_gate_blocks_only_explicit_cross_participant_citations(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.scopes = {
            "speaker-alice": {"scope_type": "speaker", "value": "Alice"},
            "speaker-bob": {"scope_type": "speaker", "value": "Bob"},
        }
        graph.events = {
            "D1:1": {"event_id": "D1:1", "speaker": "Bob", "text": "My son had an accident."},
        }
        graph.claims = {
            "claim-bob-son": {
                "claim_id": "claim-bob-son",
                "source_event_id": "D1:1",
                "subject_key": "bob_s_son",
                "canonical_subject": "Bob's son",
                "speaker": "Bob",
            },
        }
        graph.claims_by_event = defaultdict(list, {"D1:1": ["claim-bob-son"]})

        contradicted = graph.evaluate_participant_binding(
            {
                "entities": ["Alice's son"],
                "required_bindings": [
                    {"subject": "Alice", "relation": "has_son", "object": "son"},
                ],
            },
            ["D1:1"],
        )
        supported = graph.evaluate_participant_binding(
            {
                "entities": ["Bob's son"],
                "required_bindings": [
                    {"subject": "Bob", "relation": "has_son", "object": "son"},
                ],
            },
            ["D1:1"],
        )
        no_named_participant = graph.evaluate_participant_binding(
            {"entities": ["the son"], "required_bindings": []},
            ["D1:1"],
        )

        self.assertEqual(contradicted["status"], "contradicted_participant")
        self.assertTrue(contradicted["blocked"])
        self.assertEqual(contradicted["question_participants"], ["alice"])
        self.assertEqual(contradicted["evidence_participants"], ["bob"])
        self.assertEqual(supported["status"], "supported_participant")
        self.assertFalse(supported["blocked"])
        self.assertEqual(no_named_participant["status"], "not_applicable")
        self.assertFalse(no_named_participant["blocked"])
        self.assertFalse(contradicted["uses_task_labels"])
        self.assertFalse(contradicted["uses_gold"])

    def test_graph_bm25_uses_scope_event_claim_state_single_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph_dir = Path(temp_dir)
            manifest = {
                "sample_id": "sample",
                "schema_version": graph_query_runner.ACTIVE_GRAPH_SCHEMA_V2,
                "state_resolution": {
                    "mode": "ordered_state_fold",
                    "dimension_key": "state_dimension",
                },
            }
            nodes = [
                {"node_type": "Episode/Event", "event_id": "D1:1", "speaker": "Alice", "text": "Alice likes pottery"},
                {"node_type": "Episode/Event", "event_id": "D2:1", "speaker": "Bob", "text": "Bob likes pottery"},
                {
                    "node_type": "Claim",
                    "claim_id": "claim-alice",
                    "source_event_id": "D1:1",
                    "subject": "Alice",
                    "canonical_subject": "Alice",
                    "subject_key": "alice",
                    "facet_key": "preference",
                    "state_domain": "preference",
                    "state_target": "pottery",
                    "state_dimension": "preference:pottery",
                    "slot_type": "object_scoped",
                    "value": "likes pottery",
                },
                {
                    "node_type": "Claim",
                    "claim_id": "claim-bob",
                    "source_event_id": "D2:1",
                    "subject": "Bob",
                    "canonical_subject": "Bob",
                    "subject_key": "bob",
                    "facet_key": "preference",
                    "state_domain": "preference",
                    "state_target": "pottery",
                    "state_dimension": "preference:pottery",
                    "slot_type": "object_scoped",
                    "value": "likes pottery",
                },
                {
                    "node_type": "StateFacet",
                    "facet_id": "state-alice",
                    "subject": "Alice",
                    "canonical_subject": "Alice",
                    "subject_key": "alice",
                    "facet_key": "preference",
                    "state_domain": "preference",
                    "state_target": "pottery",
                    "state_dimension": "preference:pottery",
                    "slot_type": "object_scoped",
                    "status": "current",
                    "primary_claim_id": "claim-alice",
                    "support_claim_ids": ["claim-alice"],
                    "support_event_ids": ["D1:1"],
                    "value": "likes pottery",
                    "fact_type": "state",
                    "temporal_status": "ongoing",
                    "intent": "none",
                },
                {
                    "node_type": "StateFacet",
                    "facet_id": "state-bob",
                    "subject": "Bob",
                    "canonical_subject": "Bob",
                    "subject_key": "bob",
                    "facet_key": "preference",
                    "state_domain": "preference",
                    "state_target": "pottery",
                    "state_dimension": "preference:pottery",
                    "slot_type": "object_scoped",
                    "status": "current",
                    "primary_claim_id": "claim-bob",
                    "support_claim_ids": ["claim-bob"],
                    "support_event_ids": ["D2:1"],
                    "value": "likes pottery",
                    "fact_type": "state",
                    "temporal_status": "ongoing",
                    "intent": "none",
                },
                {"node_type": "Entity/Scope", "scope_id": "scope-alice", "scope_type": "entity", "label": "Alice"},
                {"node_type": "Entity/Scope", "scope_id": "scope-bob", "scope_type": "entity", "label": "Bob"},
            ]
            edges = [
                {"type": "ASSERTS", "from": "D1:1", "to": "claim-alice"},
                {"type": "ASSERTS", "from": "D2:1", "to": "claim-bob"},
                {"type": "IN_SCOPE", "from": "D1:1", "to": "scope-alice"},
                {"type": "IN_SCOPE", "from": "D2:1", "to": "scope-bob"},
                {"type": "SUPPORTS", "from": "claim-alice", "to": "state-alice"},
                {"type": "SUPPORTS", "from": "claim-bob", "to": "state-bob"},
                {"type": "CURRENT_STATE_OF", "from": "state-alice", "to": "scope-alice"},
                {"type": "CURRENT_STATE_OF", "from": "state-bob", "to": "scope-bob"},
            ]
            (graph_dir / "manifest.json").write_text(json.dumps(manifest))
            (graph_dir / "nodes.jsonl").write_text("\n".join(json.dumps(node) for node in nodes) + "\n")
            (graph_dir / "edges.jsonl").write_text("\n".join(json.dumps(edge) for edge in edges) + "\n")
            graph = graph_query_runner.GraphEvidenceIndex.load(graph_dir)
            self.assertTrue(hasattr(graph, "state_bm25"))
            question = "What pottery does Alice like?"
            result = graph.retrieve(
                question,
                retrieval_queries=[question],
                variant="graph_bm25",
                top_k=2,
                candidate_k=4,
                scope_top_k=1,
                scope_backoff_k=0,
                max_context_events=4,
                max_state_lines=4,
                embedding_indices={},
                embedding_candidate_k=4,
                scope_types=["entity"],
                time_role_client=None,
                time_role_selector="none",
                event_time_routing="rerank",
                query_subject_ids=graph.resolve_query_subject_ids(["Alice"]),
            )
            no_scope_result = graph.retrieve(
                question,
                retrieval_queries=[question],
                variant="graph_bm25",
                top_k=2,
                candidate_k=4,
                scope_top_k=1,
                scope_backoff_k=0,
                max_context_events=4,
                max_state_lines=4,
                embedding_indices={},
                embedding_candidate_k=4,
                scope_types=["topic"],
                time_role_client=None,
                time_role_selector="none",
                event_time_routing="rerank",
                query_subject_ids=graph.resolve_query_subject_ids(["Alice"]),
            )
            state_first_result = graph.retrieve(
                question,
                retrieval_queries=[question],
                variant="graph_embedding_scope_statefacet",
                top_k=2,
                candidate_k=4,
                scope_top_k=1,
                scope_backoff_k=0,
                max_context_events=4,
                max_state_lines=4,
                embedding_indices={
                    "scope": StubEmbeddingIndex(["scope::scope-alice", "scope::scope-bob"]),
                    "state": StubEmbeddingIndex(["state::state-alice", "state::state-bob"]),
                },
                embedding_candidate_k=4,
                scope_types=["entity"],
                time_role_client=None,
                time_role_selector="none",
                event_time_routing="rerank",
                query_subject_ids=graph.resolve_query_subject_ids(["Alice"]),
            )

        self.assertEqual(result.trace["event_retrieval"]["routed_scope_ids"], ["scope-alice"])
        self.assertNotIn("state_search", result.trace)
        self.assertEqual(
            result.trace["statefacet_access"]["path"],
            ["Scope", "Event", "Claim", "StateFacet"],
        )
        self.assertEqual(
            result.trace["statefacet_access"]["mode"],
            "event-claim-graph-expansion-only",
        )
        self.assertEqual(result.trace["selected_state_ids"], ["state-alice"])
        self.assertEqual(result.trace["expanded_claim_ids"], ["claim-alice"])
        self.assertNotIn("D2:1", result.candidate_dialog_ids)
        self.assertEqual(no_scope_result.candidate_dialog_ids, [])
        self.assertEqual(no_scope_result.trace["event_retrieval"]["routing"], "no-routed-scope")
        self.assertEqual(state_first_result.candidate_dialog_ids, ["D1:1"])
        self.assertEqual(state_first_result.trace["selected_state_ids"], ["state-alice"])
        self.assertEqual(state_first_result.trace["expanded_claim_ids"], ["claim-alice"])
        self.assertEqual(
            state_first_result.trace["statefacet_access"]["path"],
            ["Scope", "StateFacet", "Claim", "Event"],
        )
        self.assertEqual(
            state_first_result.trace["statefacet_access"]["mode"],
            "scoped-statefacet-direct-retrieval",
        )
        self.assertFalse(
            state_first_result.trace["statefacet_retrieval"]["independent_event_retrieval"]
        )
        self.assertFalse(state_first_result.trace["statefacet_retrieval"]["sample_event_backoff"])

    def test_question_frame_normalization_uses_one_universal_schema(self) -> None:
        frame = graph_query_runner.normalize_question_frame(
            {
                "entities": ["Melanie", "Melanie"],
                "required_bindings": [{"subject": "Melanie", "relation": "went to", "object": "beach"}],
                "requested_slot": "number of visits",
                "operation": "count",
                "count_unit": "occurrences",
            }
        )

        self.assertEqual(frame["entities"], ["Melanie"])
        self.assertEqual(frame["operation"], "count")
        self.assertEqual(frame["count_unit"], "occurrences")

    def test_retrieval_queries_expand_bindings_without_task_labels(self) -> None:
        queries = graph_query_runner.build_retrieval_queries(
            "What subject have Caroline and Melanie both painted?",
            {
                "operation": "intersection",
                "required_bindings": [
                    {"subject": "Caroline", "relation": "painted", "object": "entity"},
                    {"subject": "Melanie", "relation": "painted", "object": "sunset"},
                ]
            },
        )

        self.assertEqual(
            queries,
            [
                "What subject have Caroline and Melanie both painted?",
                "Caroline painted",
                "Melanie painted sunset",
            ],
        )

        lookup_queries = graph_query_runner.build_retrieval_queries(
            "Would Melanie enjoy a classical song?",
            {
                "operation": "lookup",
                "required_bindings": [
                    {"subject": "Melanie", "relation": "enjoys", "object": "classical song"}
                ],
            },
        )
        self.assertEqual(lookup_queries, ["Would Melanie enjoy a classical song?"])

    def test_grounded_readout_compiles_count_and_enumeration_deterministically(self) -> None:
        counted = graph_query_runner.compile_grounded_answer(
            {"operation": "count", "count_unit": "occurrences"},
            {
                "answer": "once or twice",
                "values": [],
                "counted_event_ids": ["D1:1", "D2:1", "D2:1", "D9:9"],
                "evidence_dialog_ids": ["D1:1", "D2:1"],
            },
            ["D1:1", "D2:1"],
        )
        enumerated = graph_query_runner.compile_grounded_answer(
            {"operation": "enumerate", "count_unit": "none"},
            {
                "answer": "books",
                "values": ["Nothing is Impossible", "Charlotte's Web", "Nothing is Impossible"],
                "counted_event_ids": [],
                "evidence_dialog_ids": ["D1:1"],
            },
            ["D1:1"],
        )

        self.assertEqual(counted["answer"], "2")
        self.assertEqual(enumerated["answer"], "Nothing is Impossible, Charlotte's Web")

        lookup = graph_query_runner.compile_grounded_answer(
            {"operation": "lookup", "count_unit": "none", "requested_slot": "pet"},
            {
                "answer": "Oscar",
                "values": ["guinea pig"],
                "evidence_dialog_ids": ["D1:1"],
            },
            ["D1:1"],
        )
        generic_lookup = graph_query_runner.compile_grounded_answer(
            {"operation": "lookup", "count_unit": "none", "requested_slot": "short description"},
            {
                "answer": "complete grounded explanation",
                "values": ["truncated value"],
                "evidence_dialog_ids": ["D1:1"],
            },
            ["D1:1"],
        )
        self.assertEqual(lookup["answer"], "guinea pig")
        self.assertEqual(generic_lookup["answer"], "complete grounded explanation")

    def test_grounded_readout_normalizes_only_cited_temporal_expression(self) -> None:
        output = graph_query_runner.compile_grounded_answer(
            {"operation": "lookup", "count_unit": "none"},
            {
                "answer": "last Friday",
                "values": ["last Friday"],
                "evidence_dialog_ids": ["D1:1"],
            },
            ["D1:1", "D2:1"],
            [
                {
                    "event_id": "D1:1",
                    "expression": "Last Friday",
                    "normalized_value": "the Friday before 22 October 2023",
                },
                {
                    "event_id": "D2:1",
                    "expression": "last Friday",
                    "normalized_value": "the Friday before 15 July 2023",
                },
            ],
        )

        self.assertEqual(output["answer"], "the Friday before 22 October 2023")
        self.assertEqual(output["values"], ["the Friday before 22 October 2023"])
        self.assertEqual(output["temporal_normalization"]["event_id"], "D1:1")

    def test_hybrid_union_keeps_dense_only_candidates(self) -> None:
        rows = graph_query_runner.hybrid_union_rows(
            [("bm25-only", 2.0), ("both", 1.0)],
            [
                SimpleNamespace(doc_id="dense-only", score=0.9),
                SimpleNamespace(doc_id="both", score=0.7),
            ],
        )
        by_id = {row["doc_id"]: row for row in rows}

        self.assertEqual(set(by_id), {"bm25-only", "both", "dense-only"})
        self.assertEqual(by_id["dense-only"]["retrieval_source"], "embedding")
        self.assertEqual(by_id["both"]["retrieval_source"], "hybrid")

    def test_event_rrf_rewards_candidates_found_by_both_retrievers(self) -> None:
        rows = graph_query_runner.rrf_union_rows(
            [("bm25-only", 100.0), ("both", 0.1)],
            [
                SimpleNamespace(doc_id="dense-only", score=0.99),
                SimpleNamespace(doc_id="both", score=0.01),
            ],
        )

        self.assertEqual(rows[0]["doc_id"], "both")
        self.assertEqual(rows[0]["retrieval_source"], "hybrid")
        self.assertAlmostEqual(rows[0]["score"], 1.25 / 62, places=8)

    def test_event_document_enrichment_keeps_event_as_retrieval_unit(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {
            "D1:1": {
                "dialog_id": "D1:1",
                "session_id": "S1",
                "speaker": "Caroline",
                "text": "I went there.",
            }
        }
        graph.claims = {
            "claim-1": {
                "claim_id": "claim-1",
                "graph_text": "Caroline attended a pottery workshop",
            }
        }
        graph.states = {}
        graph.scopes = {
            "scope-1": {"scope_type": "topic", "label": "pottery", "value": "pottery"}
        }
        graph.claims_by_event = defaultdict(list, {"D1:1": ["claim-1"]})
        graph.scopes_by_event = defaultdict(list, {"D1:1": ["scope-1"]})

        event_ids, event_docs, *_rest = graph._build_documents()

        self.assertEqual(event_ids, ["event::D1:1"])
        self.assertIn("I went there", event_docs[0])
        self.assertIn("pottery workshop", event_docs[0])
        self.assertIn("topic pottery", event_docs[0])


    def test_deterministic_evidence_budget_keeps_closed_units_without_repair_or_fallback(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {
            "D1:1": {"event_id": "D1:1", "speaker": "Alice", "text": "Alice likes pottery"},
            "D1:2": {"event_id": "D1:2", "speaker": "Alice", "text": "Alice likes music"},
            "D1:3": {"event_id": "D1:3", "speaker": "Alice", "text": "Alice likes hiking"},
        }
        graph.claims = {
            "claim-1": {"claim_id": "claim-1", "source_event_id": "D1:1", "claim_text": "likes pottery"},
            "claim-2": {"claim_id": "claim-2", "source_event_id": "D1:2", "claim_text": "likes music"},
            "claim-3": {"claim_id": "claim-3", "source_event_id": "D1:3", "claim_text": "likes hiking"},
        }
        graph.states = {}
        graph.claims_by_event = defaultdict(
            list,
            {"D1:1": ["claim-1"], "D1:2": ["claim-2"], "D1:3": ["claim-3"]},
        )
        graph.states_by_claim = defaultdict(list)
        graph.relations_by_claim = defaultdict(list)
        retrieval = graph_query_runner.RetrievalResult(
            candidate_dialog_ids=["D1:1", "D1:2", "D1:3"],
            temporal_lines=[],
            claim_lines=[],
            state_lines=[],
            relation_lines=[],
            context=graph._context_text(["D1:1", "D1:2", "D1:3"]),
            trace={
                "pipeline_order": ["scope_routing", "graph_expansion"],
                "expanded_claim_ids": ["claim-1", "claim-2", "claim-3"],
                "selected_state_ids": [],
            },
        )

        packed = graph.apply_deterministic_evidence_budget(
            retrieval,
            max_claims=2,
            max_states=1,
            max_events=2,
            fallback_events=1,
        )
        ledger = packed.trace["evidence_ledger"]

        self.assertEqual(ledger["selection_source"], "deterministic_ranked_graph_units")
        self.assertEqual(ledger["selection_status"], "deterministic_budgeted")
        self.assertEqual(ledger["selected_claim_ids"], ["claim-1", "claim-2"])
        self.assertEqual(ledger["selected_event_ids"], ["D1:1", "D1:2"])
        self.assertEqual(ledger["rejected_units"][0]["id"], "claim-3")
        self.assertFalse(ledger["repair_required"])
        self.assertFalse(ledger["fallback_applied"])
        self.assertEqual(ledger["attempt"], 0)
        self.assertIn("deterministic_evidence_budget", packed.trace["pipeline_order"])

    def test_time_role_rerank_uses_event_graph_roles(self) -> None:
        graph = graph_query_runner.GraphEvidenceIndex.__new__(graph_query_runner.GraphEvidenceIndex)
        graph.events = {
            "started": {"event_id": "started", "occurred_at": "2024-01-01"},
            "completed": {"event_id": "completed", "occurred_at": "2024-01-02"},
        }
        graph.claims = {
            "claim-started": {"time_role": "started_at"},
            "claim-completed": {"time_role": "completed_at"},
        }
        graph.states = {}
        graph.claims_by_event = defaultdict(
            list,
            {"started": ["claim-started"], "completed": ["claim-completed"]},
        )
        graph.states_by_claim = defaultdict(list)
        graph.times_by_claim = defaultdict(list)
        graph.current_time_by_state = {}
        graph.occurred_time_by_event = {}
        graph.occurred_time_id_by_event = {}
        candidates = [
            {
                "doc_id": "event::started",
                "score": 1.0,
                "lexical_rank": 1,
                "embedding_rank": None,
            },
            {
                "doc_id": "event::completed",
                "score": 1.0,
                "lexical_rank": 2,
                "embedding_rank": None,
            },
        ]

        ranked = graph._rerank_event_rows(candidates, ["completed_at"], 2)

        self.assertEqual([row["event_id"] for row in ranked], ["completed", "started"])
        self.assertEqual(ranked[0]["matched_time_roles"], ["completed_at"])
        self.assertEqual(ranked[0]["time_role_score"], graph_query_runner.TIME_ROLE_MATCH_BOOST)


if __name__ == "__main__":
    unittest.main()

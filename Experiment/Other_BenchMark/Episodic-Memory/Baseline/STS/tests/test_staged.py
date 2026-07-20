from __future__ import annotations

import sys
import unittest
from pathlib import Path


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.staged import STSGraphIndex, build_question_frame, hybrid_rank, rrf_rank


class Hit:
    def __init__(self, doc_id, score=1.0):
        self.doc_id = doc_id
        self.score = score


class SearchStub:
    def __init__(self, doc_ids):
        self.doc_ids = doc_ids

    def search(self, _query, top_k, allowed_doc_ids=None):
        allowed = None if allowed_doc_ids is None else set(allowed_doc_ids)
        return [Hit(doc_id, 1.0) for doc_id in self.doc_ids if allowed is None or doc_id in allowed][:top_k]


class FrameClient:
    def __init__(
        self,
        time_values=None,
        entity_queries=None,
        location_queries=None,
        event_type_queries=None,
    ):
        self.time_values = [] if time_values is None else time_values
        self.entity_queries = ["Julian Ross"] if entity_queries is None else entity_queries
        self.location_queries = ["High Line"] if location_queries is None else location_queries
        self.event_type_queries = ["Tech Hackathon"] if event_type_queries is None else event_type_queries

    def complete_json(self, _system_prompt, _user_prompt):
        return {
            "time_values": self.time_values,
            "entity_queries": self.entity_queries,
            "location_queries": self.location_queries,
            "event_type_queries": self.event_type_queries,
        }


class FrameAndTimeClient(FrameClient):
    def __init__(self, *args, time_ordering="none", **kwargs):
        super().__init__(*args, **kwargs)
        self.time_ordering = time_ordering

    def complete_json(self, system_prompt, user_prompt):
        if "time-semantics router" in system_prompt:
            return {
                "time_applicable": True,
                "time_roles": ["planned_for", "occurred_at", "mentioned_at"],
                "time_role_confidences": {
                    "planned_for": 0.1,
                    "occurred_at": 0.95,
                    "mentioned_at": 0.8,
                },
                "ordering": self.time_ordering,
                "reason": "The question asks when events occurred.",
            }
        return super().complete_json(system_prompt, user_prompt)


class JsonModeEnforcingClient(FrameClient):
    def complete_json(self, system_prompt, user_prompt):
        if "json" not in f"{system_prompt} {user_prompt}".casefold():
            raise ValueError("JSON mode requires the prompt to mention JSON")
        return super().complete_json(system_prompt, user_prompt)


def synthetic_graph():
    nodes = []
    edges = []
    for chapter_id, date, entity, location, event_type in [
        (20, "March 23, 2024", "Julian Ross", "High Line", "Tech Hackathon"),
        (42, "April 2, 2024", "Morgan Lee", "Central Park", "Tech Hackathon"),
    ]:
        event_id = f"epbench::chapter::{chapter_id}"
        nodes.append({"node_id": event_id, "event_id": event_id, "node_type": "Episode/Event", "chapter_id": chapter_id, "graph_text": f"{entity} attended {event_type} at {location}", "raw_text": f"{entity} attended {event_type} at {location} on {date}."})
        time_id = f"time::{chapter_id}"
        nodes.append({"node_id": time_id, "node_type": "Time", "value": date, "graph_text": date})
        edges.append({"type": "OCCURRED_AT", "from": event_id, "to": time_id})
        for scope_type, value in (("entity", entity), ("location", location), ("event_type", event_type)):
            scope_id = f"scope::{scope_type}::{chapter_id}"
            nodes.append({"node_id": scope_id, "node_type": "Entity/Scope", "scope_type": scope_type, "value": value, "graph_text": f"{scope_type}: {value}"})
            edges.append({"type": "IN_SCOPE" if scope_type != "location" else "MENTIONS", "from": event_id, "to": scope_id})
        claim_id = f"claim::{chapter_id}"
        nodes.append({"node_id": claim_id, "claim_id": claim_id, "node_type": "Claim", "chapter_id": chapter_id, "source_event_id": event_id, "graph_text": f"{entity} attended {event_type}", "evidence_spans": [f"{entity} attended {event_type}"]})
        edges.append({"type": "ASSERTS", "from": event_id, "to": claim_id})
        edges.append({"type": "HAS_TIME", "from": claim_id, "to": time_id, "time_role": "occurred_at"})
    return {"schema_version": "scope-time-state-graph-v2-state-merge", "nodes": nodes, "edges": edges}


class StagedRetrievalTests(unittest.TestCase):
    def test_question_frame_prompt_is_json_mode_compatible(self):
        frame = build_question_frame("Who attended?", JsonModeEnforcingClient())
        self.assertEqual([], frame.time_values)

    def test_embedding_only_candidate_survives_union(self):
        hits = hybrid_rank("query", SearchStub(["lexical"]), SearchStub(["dense"]), top_k=2)
        self.assertEqual({"lexical", "dense"}, {hit.doc_id for hit in hits})

    def test_claim_rrf_preserves_both_retrieval_channels(self):
        hits = rrf_rank("query", SearchStub(["lexical"]), SearchStub(["dense"]), top_k=2)
        self.assertEqual({"lexical", "dense"}, {hit.doc_id for hit in hits})

    def test_distinct_scope_type_coverage_beats_one_coarse_scope(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        result = index.retrieve("Julian Ross Tech Hackathon at High Line", FrameClient(), final_chapter_k=2)
        self.assertEqual(20, result.ranked_chapters[0].chapter_id)
        self.assertEqual({"entity", "location", "event_type"}, set(result.ranked_chapters[0].matched_scope_types))

    def test_scope_event_and_claim_layers_all_contribute_without_scope_gate(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        index.claim_dense = SearchStub(list(index.claims))
        result = index.retrieve("Julian Ross Tech Hackathon at High Line", FrameClient(), final_chapter_k=2)
        self.assertEqual("anchor_constrained", result.retrieval_status)
        self.assertEqual(20, result.ranked_chapters[0].chapter_id)
        self.assertEqual([20, 42], [row.chapter_id for row in result.ranked_chapters])
        self.assertEqual(8, result.trace["scope_backoff_k"])

    def test_dense_scope_candidates_are_ranked_without_exact_admission(self):
        graph = synthetic_graph()
        graph["nodes"].append(
            {
                "node_id": "scope::event_type::generic",
                "node_type": "Entity/Scope",
                "scope_type": "event_type",
                "value": "Workshop",
                "graph_text": "event_type: Workshop",
            }
        )
        graph["edges"].append(
            {
                "type": "IN_SCOPE",
                "from": "epbench::chapter::42",
                "to": "scope::event_type::generic",
            }
        )
        index = STSGraphIndex.from_graph(graph)
        index.scope_dense = SearchStub(list(index.scopes))
        index.claim_dense = SearchStub(list(index.claims))
        frame = FrameClient(
            entity_queries=[],
            location_queries=[],
            event_type_queries=["3D Printing Workshop"],
        )
        result = index.retrieve("Events related to 3D Printing Workshop", frame, final_chapter_k=2)
        self.assertEqual("scope_routed", result.retrieval_status)
        self.assertTrue(result.ranked_chapters)

    def test_exact_time_anchor_constrains_events(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        frame = FrameClient(
            time_values=["April 2, 2024"],
            entity_queries=[],
            location_queries=[],
            event_type_queries=[],
        )
        result = index.retrieve("What happened on April 2, 2024?", frame, final_chapter_k=2)
        self.assertEqual("anchor_constrained", result.retrieval_status)
        self.assertEqual([42], [row.chapter_id for row in result.ranked_chapters])

    def test_latest_returns_newest_graph_time(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        result = index.retrieve(
            "What was the latest Tech Hackathon?",
            FrameAndTimeClient(
                time_ordering="newest_first",
                entity_queries=[],
                location_queries=[],
            ),
            final_chapter_k=2,
        )
        self.assertEqual([42], [row.chapter_id for row in result.ranked_chapters[:1]])
        self.assertTrue(result.trace["time_role_sorting"]["applied"])

    def test_chronological_orders_selected_chapters_oldest_first(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        result = index.retrieve(
            "List the Tech Hackathon events chronologically",
            FrameAndTimeClient(
                time_ordering="oldest_first",
                entity_queries=[],
                location_queries=[],
            ),
            final_chapter_k=2,
        )
        dates = [row.occurred_at for row in result.ranked_chapters]
        self.assertEqual(sorted(dates), dates)

    def test_top2_time_roles_hard_filter_claims_before_rrf(self):
        graph = synthetic_graph()
        for edge in graph["edges"]:
            if edge["type"] == "HAS_TIME" and edge["from"] == "claim::42":
                edge["time_role"] = "planned_for"
        index = STSGraphIndex.from_graph(graph)
        result = index.retrieve(
            "When did the Tech Hackathon events occur?",
            FrameAndTimeClient(entity_queries=[], location_queries=[]),
            final_chapter_k=2,
        )
        self.assertEqual(["occurred_at", "mentioned_at"], result.trace["time_role_selection"]["time_roles"])
        self.assertTrue(result.trace["time_hard_filter_applied"])
        self.assertEqual([20], [row.chapter_id for row in result.ranked_chapters])

    def test_claim_trace_records_rrf_and_relation_closure(self):
        graph = synthetic_graph()
        facet_id = "facet::julian"
        graph["nodes"].append({"node_id": facet_id, "node_type": "StateFacet", "graph_text": "Julian attendance"})
        graph["edges"].extend(
            [
                {"type": "SUPPORTS", "from": "claim::20", "to": facet_id},
                {"type": "SUPPORTS", "from": "claim::42", "to": facet_id},
                {"type": "SUPERSEDES", "from": "claim::20", "to": "claim::42"},
            ]
        )
        index = STSGraphIndex.from_graph(graph)
        result = index.retrieve(
            "What happened at the Tech Hackathon?",
            FrameClient(entity_queries=[], location_queries=[], event_type_queries=[]),
            final_chapter_k=2,
        )
        trace = result.trace
        self.assertEqual(
            "scope_time_hard_filter_bm25_dense_rrf_relation_closure",
            trace["claim_retrieval_mode"],
        )
        self.assertIn("claim::20", trace["claim_seed_ids"])
        self.assertIn("claim::42", trace["claim_closure_ids"])
        self.assertEqual([facet_id], trace["selected_state_ids"])
        self.assertEqual(
            {"epbench::chapter::20", "epbench::chapter::42"},
            set(trace["source_event_ids"]),
        )
        self.assertTrue(all(row.raw_text for row in result.ranked_chapters))

    def test_ablation_policies_gate_time_and_state_access(self):
        graph = synthetic_graph()
        facet_id = "facet::julian"
        graph["nodes"].append(
            {"node_id": facet_id, "node_type": "StateFacet", "graph_text": "Julian attended"}
        )
        graph["edges"].extend(
            [
                {"type": "SUPPORTS", "from": "claim::20", "to": facet_id},
                {"type": "SUPPORTS", "from": "claim::42", "to": facet_id},
                {"type": "SUPERSEDES", "from": "claim::20", "to": "claim::42"},
            ]
        )
        index = STSGraphIndex.from_graph(graph)
        frame = FrameAndTimeClient(entity_queries=[], location_queries=[])
        for policy in ("claim", "scope-claim", "scope-claim-time"):
            result = index.retrieve(
                "What happened at the Tech Hackathon?",
                frame,
                retrieval_policy=policy,
                final_chapter_k=2,
            )
            self.assertEqual(policy, result.trace["retrieval_policy"])
            self.assertEqual([], result.trace["selected_state_ids"])
            self.assertEqual([], result.trace["selected_relation_edges"])
        full = index.retrieve(
            "What happened at the Tech Hackathon?",
            frame,
            retrieval_policy="scope-claim-time-state",
            final_chapter_k=2,
        )
        self.assertEqual([facet_id], full.trace["selected_state_ids"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.staged import STSGraphIndex, build_question_frame, hybrid_rank


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
        ordering="none",
        time_values=None,
        entity_queries=None,
        location_queries=None,
        event_type_queries=None,
    ):
        self.ordering = ordering
        self.time_values = [] if time_values is None else time_values
        self.entity_queries = ["Julian Ross"] if entity_queries is None else entity_queries
        self.location_queries = ["High Line"] if location_queries is None else location_queries
        self.event_type_queries = ["Tech Hackathon"] if event_type_queries is None else event_type_queries

    def complete_json(self, _system_prompt, _user_prompt):
        return {
            "ordering": self.ordering,
            "time_values": self.time_values,
            "entity_queries": self.entity_queries,
            "location_queries": self.location_queries,
            "event_type_queries": self.event_type_queries,
        }


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
    return {"schema_version": "scope-time-state-graph-v2-state-merge", "nodes": nodes, "edges": edges}


class StagedRetrievalTests(unittest.TestCase):
    def test_question_frame_prompt_is_json_mode_compatible(self):
        frame = build_question_frame("Who attended?", JsonModeEnforcingClient())
        self.assertEqual("none", frame.ordering)

    def test_embedding_only_candidate_survives_union(self):
        hits = hybrid_rank("query", SearchStub(["lexical"]), SearchStub(["dense"]), top_k=2)
        self.assertEqual({"lexical", "dense"}, {hit.doc_id for hit in hits})

    def test_distinct_scope_type_coverage_beats_one_coarse_scope(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        result = index.retrieve("Julian Ross Tech Hackathon at High Line", FrameClient(), final_chapter_k=2)
        self.assertEqual(20, result.ranked_chapters[0].chapter_id)
        self.assertEqual({"entity", "location", "event_type"}, set(result.ranked_chapters[0].matched_scope_types))

    def test_scope_event_and_claim_layers_all_contribute_without_scope_gate(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        index.event_dense = SearchStub(list(index.events))
        index.claim_dense = SearchStub(list(index.claims))
        result = index.retrieve("Julian Ross Tech Hackathon at High Line", FrameClient(), final_chapter_k=2)
        self.assertEqual("anchor_constrained", result.retrieval_status)
        self.assertEqual(20, result.ranked_chapters[0].chapter_id)
        self.assertEqual([20], [row.chapter_id for row in result.ranked_chapters])

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
        index.event_dense = SearchStub(list(index.events))
        index.claim_dense = SearchStub(list(index.claims))
        frame = FrameClient(
            entity_queries=[],
            location_queries=[],
            event_type_queries=["3D Printing Workshop"],
        )
        result = index.retrieve("Events related to 3D Printing Workshop", frame, final_chapter_k=2)
        self.assertEqual("retrieved", result.retrieval_status)
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
            FrameClient(ordering="latest", entity_queries=[], location_queries=[]),
            final_chapter_k=2,
        )
        self.assertEqual([42], [row.chapter_id for row in result.ranked_chapters[:1]])

    def test_chronological_orders_selected_chapters_oldest_first(self):
        index = STSGraphIndex.from_graph(synthetic_graph())
        result = index.retrieve(
            "List the Tech Hackathon events chronologically",
            FrameClient(ordering="chronological", entity_queries=[], location_queries=[]),
            final_chapter_k=2,
        )
        dates = [row.occurred_at for row in result.ranked_chapters]
        self.assertEqual(sorted(dates), dates)


if __name__ == "__main__":
    unittest.main()

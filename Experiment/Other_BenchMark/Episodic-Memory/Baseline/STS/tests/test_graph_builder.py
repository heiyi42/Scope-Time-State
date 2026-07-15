from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.graph_builder import EXTRACTION_SYSTEM_PROMPT, build_graph, normalize_extraction, write_graph
from STS.loader import Chapter


CHAPTERS = [
    Chapter(1, "On March 23, 2024, Julian Ross attended a Tech Hackathon at High Line."),
    Chapter(2, "On April 2, 2024, Julian Ross attended a Robotics Workshop at Central Park."),
]
VALID_RECORDS = [
    {
        "chapter_id": 1,
        "concise_summary": "Julian Ross attended a Tech Hackathon.",
        "dates": [{"value": "March 23, 2024", "evidence_span": "March 23, 2024"}],
        "locations": [{"value": "High Line", "evidence_span": "High Line"}],
        "entities": [
            {"value": "Julian Ross", "role": "primary", "evidence_span": "Julian Ross"}
        ],
        "event_types": [{"value": "Tech Hackathon", "evidence_span": "Tech Hackathon"}],
        "claims": [
            {
                "subject": "Julian Ross",
                "predicate": "episodic_action",
                "value": "attended a Tech Hackathon",
                "evidence_span": "Julian Ross attended a Tech Hackathon",
            }
        ],
    },
    {
        "chapter_id": 2,
        "concise_summary": "Julian Ross attended a Robotics Workshop.",
        "dates": [{"value": "April 2, 2024", "evidence_span": "April 2, 2024"}],
        "locations": [{"value": "Central Park", "evidence_span": "Central Park"}],
        "entities": [
            {"value": "Julian Ross", "role": "primary", "evidence_span": "Julian Ross"}
        ],
        "event_types": [
            {"value": "Robotics Workshop", "evidence_span": "Robotics Workshop"}
        ],
        "claims": [
            {
                "subject": "Julian Ross",
                "predicate": "episodic_action",
                "value": "attended a Robotics Workshop",
                "evidence_span": "Julian Ross attended a Robotics Workshop",
            }
        ],
    },
]


STATE_CHAPTERS = [
    Chapter(1, "On March 23, 2024, Julian Ross lives in Seattle."),
    Chapter(2, "On April 2, 2024, Julian Ross still lives in Seattle."),
]
COMPATIBLE_STATE_RECORDS = [
    {
        "chapter_id": 1,
        "concise_summary": "Julian Ross lives in Seattle.",
        "dates": [{"value": "March 23, 2024", "evidence_span": "March 23, 2024"}],
        "locations": [{"value": "Seattle", "evidence_span": "Seattle"}],
        "entities": [{"value": "Julian Ross", "role": "primary", "evidence_span": "Julian Ross"}],
        "event_types": [],
        "claims": [{"subject": "Julian Ross", "predicate": "lives_in", "value": "Seattle", "evidence_span": "Julian Ross lives in Seattle"}],
    },
    {
        "chapter_id": 2,
        "concise_summary": "Julian Ross still lives in Seattle.",
        "dates": [{"value": "April 2, 2024", "evidence_span": "April 2, 2024"}],
        "locations": [{"value": "Seattle", "evidence_span": "Seattle"}],
        "entities": [{"value": "Julian Ross", "role": "primary", "evidence_span": "Julian Ross"}],
        "event_types": [],
        "claims": [{"subject": "Julian Ross", "predicate": "lives_in", "value": "Seattle", "evidence_span": "Julian Ross still lives in Seattle"}],
    },
]


class CompatibleClient:
    def complete_json(self, _system_prompt, _user_prompt):
        return {"decision": "COMPATIBLE", "winner": "none", "reason": "same residence", "evidence_event_ids": []}


class GraphBuilderTests(unittest.TestCase):
    def test_extraction_prompt_fixes_every_nested_item_shape(self):
        self.assertIn('"dates": [{"value":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"entities": [{"value":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"claims": [{"subject":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("Never return bare strings inside these lists", EXTRACTION_SYSTEM_PROMPT)

    def test_extraction_rejects_scope_without_exact_source_evidence(self):
        chapter = Chapter(1, "Julian attended a Tech Hackathon at High Line.")
        raw = {
            "chapter_id": 1,
            "concise_summary": "Julian attended a hackathon.",
            "dates": [],
            "locations": [{"value": "Central Park", "evidence_span": "Central Park"}],
            "entities": [],
            "event_types": [],
            "claims": [],
        }
        with self.assertRaisesRegex(ValueError, "evidence_span"):
            normalize_extraction(chapter, raw)

    def test_base_graph_uses_one_event_per_chapter(self):
        graph = build_graph(CHAPTERS, VALID_RECORDS, merge_client=None)
        events = [node for node in graph["nodes"] if node["node_type"] == "Episode/Event"]
        self.assertEqual([1, 2], [node["chapter_id"] for node in events])
        self.assertEqual(CHAPTERS[0].text, events[0]["raw_text"])

    def test_compatible_claims_share_statefacet_without_claim_edge(self):
        graph = build_graph(STATE_CHAPTERS, COMPATIBLE_STATE_RECORDS, merge_client=CompatibleClient())
        facets = [node for node in graph["nodes"] if node["node_type"] == "StateFacet"]
        self.assertEqual(1, len(facets))
        self.assertEqual(2, len(facets[0]["support_claim_ids"]))
        self.assertFalse(any(edge["type"] == "COMPATIBLE_WITH" for edge in graph["edges"]))

    def test_only_shared_claim_relations_are_materialized(self):
        graph = build_graph(STATE_CHAPTERS, COMPATIBLE_STATE_RECORDS, merge_client=CompatibleClient())
        relation_types = {
            edge["type"]
            for edge in graph["edges"]
            if edge["from"].startswith("claim::") and edge["to"].startswith("claim::")
        }
        self.assertLessEqual(relation_types, {"SUPERSEDES", "CORRECTS", "CONFLICTS_WITH"})

    def test_manifest_records_book_only_build_inputs(self):
        graph = build_graph(CHAPTERS, VALID_RECORDS, merge_client=None)
        self.assertEqual(["book.json"], graph["manifest"]["leakage_policy"]["graph_build_inputs"])
        self.assertFalse(graph["manifest"]["leakage_policy"]["qa_loaded"])

    def test_incompatible_existing_manifest_is_not_overwritten(self):
        graph = build_graph(CHAPTERS, VALID_RECORDS, merge_client=None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "book1"
            target.mkdir()
            (target / "manifest.json").write_text(json.dumps({"schema_version": "old"}))
            with self.assertRaisesRegex(ValueError, "incompatible"):
                write_graph(root, graph)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.graph_builder import build_graph, normalize_extraction
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


class GraphBuilderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

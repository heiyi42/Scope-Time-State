from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.graph_builder import (
    EXTRACTION_SYSTEM_PROMPT,
    _extract_chunk,
    build_graph,
    normalize_extraction,
    write_graph,
)
from STS.config import MESSAGE_CHUNK_SIZE
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


class RepairClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.user_prompts = []

    def complete_json(self, _system_prompt, user_prompt):
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


class GraphBuilderTests(unittest.TestCase):
    def test_epbench_build_defaults_to_one_chapter_per_request(self):
        self.assertEqual(1, MESSAGE_CHUNK_SIZE)

    def test_extraction_prompt_fixes_every_nested_item_shape(self):
        self.assertIn('"dates": [{"value":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"entities": [{"value":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"claims": [{"subject":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"predicate": "episodic_action"', EXTRACTION_SYSTEM_PROMPT)
        self.assertNotIn('"predicate": "allowed predicate"', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("Never return bare strings inside these lists", EXTRACTION_SYSTEM_PROMPT)

    def test_extraction_maps_quote_variation_back_to_exact_source_span(self):
        chapter = Chapter(
            1,
            'Cora Xiong proclaimed "Hoppy and I Know It," and joined the debate.',
        )
        raw = {
            "chapter_id": 1,
            "concise_summary": "Cora joined the debate.",
            "dates": [],
            "locations": [],
            "entities": [
                {
                    "value": "Cora Xiong",
                    "role": "primary",
                    "evidence_span": "Cora Xiong proclaimed 'Hoppy and I Know It,'",
                }
            ],
            "event_types": [],
            "claims": [
                {
                    "subject": "Cora Xiong",
                    "predicate": "has_status",
                    "value": "joined the debate",
                    "evidence_span": "Cora Xiong proclaimed 'Hoppy and I Know It,' and joined the debate",
                }
            ],
        }
        record = normalize_extraction(chapter, raw)
        self.assertEqual(
            'Cora Xiong proclaimed "Hoppy and I Know It,"',
            record["entities"][0]["evidence_span"],
        )
        self.assertEqual(
            'Cora Xiong proclaimed "Hoppy and I Know It," and joined the debate',
            record["claims"][0]["evidence_span"],
        )

    def test_claim_evidence_reanchors_across_source_insertions(self):
        chapter = Chapter(
            1,
            "Noa Middleton, the lead instructor, nodded approvingly, then continued.",
        )
        raw = {
            "chapter_id": 1,
            "concise_summary": "Noa approved.",
            "dates": [],
            "locations": [],
            "entities": [{
                "value": "Noa Middleton",
                "role": "primary",
                "evidence_span": "Noa Middleton",
            }],
            "event_types": [],
            "claims": [{
                "subject": "Noa Middleton",
                "predicate": "episodic_action",
                "value": "nodded approvingly",
                "evidence_span": "Noa Middleton nodded approvingly",
            }],
        }

        record = normalize_extraction(chapter, raw)

        self.assertEqual(
            "Noa Middleton, the lead instructor, nodded approvingly",
            record["claims"][0]["evidence_span"],
        )

    def test_claim_evidence_reanchor_rejects_unrelated_statement(self):
        chapter = Chapter(1, "Noah Williams discretely wrote observations in a notebook.")
        raw = {
            "chapter_id": 1,
            "concise_summary": "Noah recorded observations.",
            "dates": [],
            "locations": [],
            "entities": [{
                "value": "Noah Williams",
                "role": "primary",
                "evidence_span": "Noah Williams",
            }],
            "event_types": [],
            "claims": [{
                "subject": "Noah Williams",
                "predicate": "episodic_action",
                "value": "checked his watch",
                "evidence_span": "He checked his watch on September 22, 2026",
            }],
        }

        with self.assertRaisesRegex(ValueError, "evidence_span not found"):
            normalize_extraction(chapter, raw)

    def test_claim_evidence_reanchor_rejects_ambiguous_matches(self):
        chapter = Chapter(
            1,
            "Noa Middleton, the instructor, nodded approvingly. "
            "Noa Middleton, the organizer, nodded approvingly.",
        )
        raw = {
            "chapter_id": 1,
            "concise_summary": "Noa approved twice.",
            "dates": [],
            "locations": [],
            "entities": [{
                "value": "Noa Middleton",
                "role": "primary",
                "evidence_span": "Noa Middleton",
            }],
            "event_types": [],
            "claims": [{
                "subject": "Noa Middleton",
                "predicate": "episodic_action",
                "value": "nodded approvingly",
                "evidence_span": "Noa Middleton nodded approvingly",
            }],
        }

        with self.assertRaisesRegex(ValueError, "evidence_span not found"):
            normalize_extraction(chapter, raw)

    def test_scope_falls_back_to_exact_value_when_long_span_is_not_verbatim(self):
        chapter = Chapter(1, 'Cora Xiong wore a shirt reading "Hoppy and I Know It."')
        raw = {
            "chapter_id": 1,
            "concise_summary": "Cora wore a shirt.",
            "dates": [],
            "locations": [],
            "entities": [
                {
                    "value": "Cora Xiong",
                    "role": "primary",
                    "evidence_span": "Cora Xiong wore a funny beer shirt",
                }
            ],
            "event_types": [],
            "claims": [],
        }
        record = normalize_extraction(chapter, raw)
        self.assertEqual("Cora Xiong", record["entities"][0]["evidence_span"])

    def test_repair_prompt_includes_prior_invalid_json_and_rejected_span(self):
        chapter = Chapter(
            1,
            "Noa Middleton, the lead instructor, nodded approvingly.",
        )
        invalid = {
            "chapters": [{
                "chapter_id": 1,
                "concise_summary": "Noa approved.",
                "dates": [],
                "locations": [],
                "entities": [{
                    "value": "Noa Middleton",
                    "role": "primary",
                    "evidence_span": "Noa Middleton",
                }],
                "event_types": [],
                "claims": [{
                    "subject": "Noa Middleton",
                    "predicate": "episodic_action",
                    "value": "nodded approvingly",
                    "evidence_span": "Noa Middleton celebrated a victory",
                }],
            }],
        }
        repaired = json.loads(json.dumps(invalid))
        repaired["chapters"][0]["claims"][0]["evidence_span"] = (
            "Noa Middleton, the lead instructor, nodded approvingly"
        )
        client = RepairClient([invalid, repaired])

        records = _extract_chunk([chapter], client, max_claims_per_chapter=8)

        self.assertEqual(2, len(client.user_prompts))
        self.assertIn("Prior invalid JSON", client.user_prompts[1])
        self.assertIn("Noa Middleton celebrated a victory", client.user_prompts[1])
        self.assertIn("evidence_span not found", client.user_prompts[1])
        self.assertIn("Rejected evidence candidates", client.user_prompts[1])
        self.assertEqual(
            "Noa Middleton, the lead instructor, nodded approvingly",
            records[0]["claims"][0]["evidence_span"],
        )

    def test_final_repair_drops_only_ungrounded_nested_item(self):
        chapter = Chapter(
            1,
            "Noa Middleton, the lead instructor, nodded approvingly.",
        )
        invalid = {
            "chapters": [{
                "chapter_id": 1,
                "concise_summary": "Noa approved.",
                "dates": [],
                "locations": [],
                "entities": [{
                    "value": "Noa Middleton",
                    "role": "primary",
                    "evidence_span": "Noa Middleton",
                }],
                "event_types": [],
                "claims": [{
                    "subject": "Noa Middleton",
                    "predicate": "episodic_action",
                    "value": "nodded approvingly",
                    "evidence_span": "Noa Middleton celebrated a victory",
                }],
            }],
        }
        client = RepairClient([invalid, invalid])

        records = _extract_chunk([chapter], client, max_claims_per_chapter=8)

        self.assertEqual([], records[0]["claims"])
        self.assertEqual("Noa Middleton", records[0]["entities"][0]["value"])
        self.assertEqual(1, len(records[0]["normalization_warnings"]))
        self.assertIn("claims[0]", records[0]["normalization_warnings"][0])

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

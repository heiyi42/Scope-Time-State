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
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTION_SYSTEM_PROMPT,
    _extract_chunk,
    build_graph,
    chapter_sentences,
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
        "dates": [{"value": "March 23, 2024", "evidence_sentence_ids": [1]}],
        "locations": [{"value": "High Line", "evidence_sentence_ids": [1]}],
        "entities": [
            {"value": "Julian Ross", "role": "primary", "evidence_sentence_ids": [1]}
        ],
        "event_types": [{"value": "Tech Hackathon", "evidence_sentence_ids": [1]}],
        "claims": [
            {
                "subject": "Julian Ross",
                "predicate": "episodic_action",
                "value": "attended a Tech Hackathon",
                "evidence_sentence_ids": [1],
            }
        ],
    },
    {
        "chapter_id": 2,
        "concise_summary": "Julian Ross attended a Robotics Workshop.",
        "dates": [{"value": "April 2, 2024", "evidence_sentence_ids": [1]}],
        "locations": [{"value": "Central Park", "evidence_sentence_ids": [1]}],
        "entities": [
            {"value": "Julian Ross", "role": "primary", "evidence_sentence_ids": [1]}
        ],
        "event_types": [
            {"value": "Robotics Workshop", "evidence_sentence_ids": [1]}
        ],
        "claims": [
            {
                "subject": "Julian Ross",
                "predicate": "episodic_action",
                "value": "attended a Robotics Workshop",
                "evidence_sentence_ids": [1],
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
        "dates": [{"value": "March 23, 2024", "evidence_sentence_ids": [1]}],
        "locations": [{"value": "Seattle", "evidence_sentence_ids": [1]}],
        "entities": [{"value": "Julian Ross", "role": "primary", "evidence_sentence_ids": [1]}],
        "event_types": [],
        "claims": [{"subject": "Julian Ross", "predicate": "lives_in", "value": "Seattle", "evidence_sentence_ids": [1]}],
    },
    {
        "chapter_id": 2,
        "concise_summary": "Julian Ross still lives in Seattle.",
        "dates": [{"value": "April 2, 2024", "evidence_sentence_ids": [1]}],
        "locations": [{"value": "Seattle", "evidence_sentence_ids": [1]}],
        "entities": [{"value": "Julian Ross", "role": "primary", "evidence_sentence_ids": [1]}],
        "event_types": [],
        "claims": [{"subject": "Julian Ross", "predicate": "lives_in", "value": "Seattle", "evidence_sentence_ids": [1]}],
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

    def test_extraction_prompt_requires_sentence_ids_without_evidence_text(self):
        self.assertIn('"dates": [{"value":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"entities": [{"value":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"claims": [{"subject":', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"predicate": "episodic_action"', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"evidence_sentence_ids": [1]', EXTRACTION_SYSTEM_PROMPT)
        self.assertNotIn('"evidence_span":', EXTRACTION_SYSTEM_PROMPT)
        self.assertNotIn('"predicate": "allowed predicate"', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("1 to 5 unique sentence IDs", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("may be nonadjacent", EXTRACTION_SYSTEM_PROMPT)
        self.assertNotIn("contiguous", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("cited sentences jointly and explicitly support", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("Never return bare strings inside these lists", EXTRACTION_SYSTEM_PROMPT)

    def test_sentence_splitter_preserves_abbreviation_and_sentence_order(self):
        chapter = Chapter(1, "Mila entered St. Patrick's Cathedral. She joined the performance.")

        self.assertEqual(
            ["Mila entered St. Patrick's Cathedral.", "She joined the performance."],
            chapter_sentences(chapter),
        )

    def test_sentence_splitter_keeps_ellipsis_and_open_dialogue_together(self):
        chapter = Chapter(
            1,
            'She announced, "Please welcome... Zoe Brown!" Applause followed. '
            'Later she said, "Alright, everyone! Let\'s take five."',
        )

        self.assertEqual(
            [
                'She announced, "Please welcome... Zoe Brown!"',
                "Applause followed.",
                'Later she said, "Alright, everyone! Let\'s take five."',
            ],
            chapter_sentences(chapter),
        )

    def test_sentence_id_copies_the_complete_source_sentence(self):
        chapter = Chapter(1, "Noa arrived early. Noa Middleton nodded approvingly.")
        raw = {
            "chapter_id": 1,
            "concise_summary": "Noa approved.",
            "dates": [{"value": "today", "evidence_sentence_ids": [2]}],
            "locations": [{"value": "workshop", "evidence_sentence_ids": [2]}],
            "entities": [{
                "value": "Noa Middleton",
                "role": "primary",
                "evidence_sentence_ids": [2],
            }],
            "event_types": [{"value": "approval", "evidence_sentence_ids": [2]}],
            "claims": [{
                "subject": "Noa Middleton",
                "predicate": "episodic_action",
                "value": "nodded approvingly",
                "evidence_sentence_ids": [2, 1, 2],
            }],
        }

        record = normalize_extraction(chapter, raw)

        for field in ("dates", "locations", "entities", "event_types"):
            self.assertEqual([2], record[field][0]["evidence_sentence_ids"])
            self.assertEqual(
                ["Noa Middleton nodded approvingly."],
                record[field][0]["evidence_spans"],
            )
        self.assertEqual([1, 2], record["claims"][0]["evidence_sentence_ids"])
        self.assertEqual(
            ["Noa arrived early.", "Noa Middleton nodded approvingly."],
            record["claims"][0]["evidence_spans"],
        )

    def test_legacy_singular_sentence_id_is_rejected(self):
        chapter = Chapter(1, "Noa Middleton nodded approvingly.")
        raw = {
            "chapter_id": 1,
            "concise_summary": "Noa approved.",
            "dates": [],
            "locations": [],
            "entities": [{
                "value": "Noa Middleton",
                "role": "primary",
                "evidence_sentence_id": 1,
            }],
            "event_types": [],
            "claims": [],
        }

        with self.assertRaisesRegex(ValueError, "evidence_sentence_ids must be a non-empty list"):
            normalize_extraction(chapter, raw)

    def test_claim_evidence_sentences_are_deduplicated_sorted_and_limited_to_five(self):
        chapter = Chapter(
            1,
            "One happened. Two happened. Three happened. Four happened. Five happened. Six happened.",
        )
        base = {
            "chapter_id": 1,
            "concise_summary": "Several things happened.",
            "dates": [],
            "locations": [],
            "entities": [],
            "event_types": [],
            "claims": [{
                "subject": "Someone",
                "predicate": "episodic_action",
                "value": "did something",
                "evidence_sentence_ids": [3, 1, 3],
            }],
        }

        record = normalize_extraction(chapter, base)
        self.assertEqual([1, 3], record["claims"][0]["evidence_sentence_ids"])
        self.assertEqual(
            ["One happened.", "Three happened."],
            record["claims"][0]["evidence_spans"],
        )

        too_many = json.loads(json.dumps(base))
        too_many["claims"][0]["evidence_sentence_ids"] = [1, 2, 3, 4, 5, 6]
        with self.assertRaisesRegex(ValueError, "at most 5"):
            normalize_extraction(chapter, too_many)

    def test_repair_prompt_includes_prior_invalid_sentence_id(self):
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
                    "evidence_sentence_ids": [1],
                }],
                "event_types": [],
                "claims": [{
                    "subject": "Noa Middleton",
                    "predicate": "episodic_action",
                    "value": "nodded approvingly",
                    "evidence_sentence_ids": [9],
                }],
            }],
        }
        repaired = json.loads(json.dumps(invalid))
        repaired["chapters"][0]["claims"][0]["evidence_sentence_ids"] = [1]
        client = RepairClient([invalid, repaired])

        records = _extract_chunk([chapter], client, max_claims_per_chapter=8)

        self.assertEqual(2, len(client.user_prompts))
        self.assertIn("Prior invalid JSON", client.user_prompts[1])
        self.assertIn('"evidence_sentence_ids": [9]', client.user_prompts[1])
        self.assertIn("outside 1..1", client.user_prompts[1])
        self.assertEqual(
            "Noa Middleton, the lead instructor, nodded approvingly.",
            records[0]["claims"][0]["evidence_spans"][0],
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
                    "evidence_sentence_ids": [1],
                }],
                "event_types": [],
                "claims": [{
                    "subject": "Noa Middleton",
                    "predicate": "episodic_action",
                    "value": "nodded approvingly",
                    "evidence_sentence_ids": [9],
                }],
            }],
        }
        client = RepairClient([invalid, invalid])

        records = _extract_chunk([chapter], client, max_claims_per_chapter=8)

        self.assertEqual([], records[0]["claims"])
        self.assertEqual("Noa Middleton", records[0]["entities"][0]["value"])
        self.assertEqual(1, len(records[0]["normalization_warnings"]))
        self.assertIn("claims[0]", records[0]["normalization_warnings"][0])

    def test_extraction_rejects_scope_with_out_of_range_sentence_id(self):
        chapter = Chapter(1, "Julian attended a Tech Hackathon at High Line.")
        raw = {
            "chapter_id": 1,
            "concise_summary": "Julian attended a hackathon.",
            "dates": [],
            "locations": [{"value": "Central Park", "evidence_sentence_ids": [2]}],
            "entities": [],
            "event_types": [],
            "claims": [],
        }
        with self.assertRaisesRegex(ValueError, "outside 1..1"):
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

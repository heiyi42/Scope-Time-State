import json
import tempfile
import unittest
from pathlib import Path

from extraction import load_book_chapters, parse_extracted_event, prepare_qa
from answer_eval import LatestCorrectedARTMemorySystem
from retrieval import restore_post_entities


class EPBenchPipelineTest(unittest.TestCase):
    def test_fixed_book_and_qa_contract(self):
        chapters = load_book_chapters()
        self.assertEqual(196, len(chapters))
        self.assertEqual(1, chapters[0]["chapter"])
        self.assertEqual(196, chapters[-1]["chapter"])

        with tempfile.TemporaryDirectory() as temporary:
            qa_path = prepare_qa(Path(temporary))
            with qa_path.open("r", encoding="utf-8") as stream:
                qa = json.load(stream)
        self.assertEqual(686, len(qa))
        self.assertEqual(list(range(686)), [row["artem_query_index"] for row in qa])

    def test_event_parser_normalizes_artem_fields(self):
        event = parse_extracted_event(
            '{"date":"September 13, 2025","location":"New York",'
            '"entity":["Alice","Bob"],"content":"A workshop took place."}',
            1,
        )
        self.assertEqual(["September 13, 2025"], event["time"])
        self.assertEqual("New York", event["spaces"])
        self.assertEqual(["Alice", "Bob"], event["entities"])

        nested = parse_extracted_event(
            '{"date":[],"location":"Paris","entity":[{"name":"Chloe"}],'
            '"content":"A show took place."}',
            2,
        )
        self.assertEqual(["Chloe"], nested["entities"])

    def test_latest_uses_last_chronological_vigilant_event(self):
        memory = LatestCorrectedARTMemorySystem()
        memory.retrieval_data = {
            1: [
                {
                    "results": {
                        "all_vigilant_events_time_sorted": [
                            {"time": ["January 1, 2024"], "content": "oldest"},
                            {"time": ["January 1, 2025"], "content": "middle"},
                            {"time": ["January 1, 2026"], "content": "latest"},
                        ]
                    }
                }
            ]
        }
        result = memory.retrieve_events(
            question="latest?",
            question_index=0,
            retrieval_type="Event contents",
            question_type="latest",
            book_id=1,
        )
        self.assertEqual(1, len(result.retrieved_events))
        self.assertEqual("latest", result.retrieved_events[0].content)
        self.assertEqual(["January 1, 2026"], result.retrieved_events[0].time)

    def test_post_entities_are_restored_after_official_serialization(self):
        event = {
            "time": ["September 13, 2025"],
            "spaces": "Bethpage Black Course",
            "entities": "Ezra Edwards",
            "content": "Parkour Workshop",
        }
        result = {
            "retrieval_results": [
                {"results": {"all_vigilant_events_time_sorted": [dict(event)]}}
            ]
        }
        formatted = [
            {
                **event,
                "post_entities": ["Noa Middleton", "Mara Ledbetter"],
            }
        ]
        restore_post_entities(result, formatted)
        restored = result["retrieval_results"][0]["results"][
            "all_vigilant_events_time_sorted"
        ][0]
        self.assertEqual(
            ["Noa Middleton", "Mara Ledbetter"], restored["post_entities"]
        )


if __name__ == "__main__":
    unittest.main()

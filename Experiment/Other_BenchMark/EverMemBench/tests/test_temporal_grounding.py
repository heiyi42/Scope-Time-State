from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sys
import unittest


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[4]
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state.staged import STSGraphEvidenceIndex  # noqa: E402


def make_graph() -> STSGraphEvidenceIndex:
    graph = STSGraphEvidenceIndex.__new__(STSGraphEvidenceIndex)
    graph.events = {
        "E1": {
            "event_id": "E1",
            "occurred_at": "2025-01-10 09:00:00",
            "text": "The final report is due next week; yesterday we completed the draft.",
        }
    }
    graph.claims = {"C1": {"claim_id": "C1", "time_role": "deadline_at"}}
    graph.state_facets = {}
    graph.claims_by_event = defaultdict(list, {"E1": ["C1"]})
    graph.states_by_claim = defaultdict(list)
    graph.times_by_claim = defaultdict(
        list,
        {
            "C1": [
                {
                    "time_role": "deadline_at",
                    "value": "2025-01-17 17:55:00",
                    "time_id": "T1",
                    "time_value_source": "relative_text_time",
                }
            ]
        },
    )
    graph.occurred_time_by_event = {"E1": "2025-01-10 09:00:00"}
    graph.occurred_time_id_by_event = {"E1": "TE1"}
    graph.current_time_by_state = {}
    return graph


class EverMemBenchTemporalGroundingTests(unittest.TestCase):
    def test_question_only_grounding_combines_event_and_graph_time(self) -> None:
        rows = make_graph().temporal_grounding_rows(
            "When is the final report due?",
            ["E1"],
            ["deadline_at"],
        )

        normalized = {str(row["normalized_value"]) for row in rows}
        self.assertIn("the week after 10 January 2025", normalized)
        self.assertIn("17 January 2025 17:55:00", normalized)
        self.assertTrue(all(row["event_id"] == "E1" for row in rows))

    def test_non_temporal_question_does_not_activate_grounding(self) -> None:
        rows = make_graph().temporal_grounding_rows(
            "Who completed the final report?",
            ["E1"],
            ["completed_at"],
        )

        self.assertEqual(rows, [])

    def test_sequence_word_after_does_not_activate_a_non_temporal_answer(self) -> None:
        rows = make_graph().temporal_grounding_rows(
            "After SQL optimization, what was the peak CPU usage?",
            ["E1"],
            ["occurred_at"],
        )

        self.assertEqual(rows, [])

    def test_source_event_fallback_time_is_not_promoted(self) -> None:
        graph = make_graph()
        graph.times_by_claim["C1"] = [
            {
                "time_role": "deadline_at",
                "value": "2025-01-10 09:00:00",
                "time_id": "T-fallback",
                "time_value_source": "source_event_fallback",
            }
        ]

        rows = graph.temporal_grounding_rows(
            "When is the final report due?",
            ["E1"],
            ["deadline_at"],
        )

        self.assertFalse(any(row.get("time_id") == "T-fallback" for row in rows))


if __name__ == "__main__":
    unittest.main()

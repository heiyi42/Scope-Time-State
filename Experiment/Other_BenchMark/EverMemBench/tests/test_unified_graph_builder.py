from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
BASELINE_DIR = BENCHMARK_DIR / "Baseline"
PROJECT_DIR = BENCHMARK_DIR.parents[2]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state import graph_builder


class StubJsonClient:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, _system_prompt, _user_prompt):
        return self.payload


class UnifiedEverMemBenchGraphTests(unittest.TestCase):
    def _data_root(self, root: Path) -> Path:
        topic_dir = root / "01"
        topic_dir.mkdir(parents=True)
        (topic_dir / "dialogue.json").write_text(
            json.dumps(
                [
                    {
                        "topic_id": "01",
                        "date": "2026-01-01",
                        "dialogues": {
                            "group-a": [
                                {
                                    "message_index": 1,
                                    "speaker": "Alice",
                                    "time": "2026-01-01 09:00",
                                    "dialogue": "Alice is the project owner.",
                                },
                                {
                                    "message_index": 2,
                                    "speaker": "Alice",
                                    "time": "2026-01-01 10:00",
                                    "dialogue": "Alice is now the technical lead.",
                                },
                            ]
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        (topic_dir / "qa_1.json").write_text("not valid json", encoding="utf-8")
        return root

    def test_builder_emits_common_v2_schema_without_v6_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = graph_builder.build_topic_graph(
                topic_id="01",
                data_root=self._data_root(Path(tmp)),
                claim_mode="heuristic",
                resolver_mode="heuristic",
                max_claims_per_event=2,
                event_limit=0,
                client=None,
                runtime=None,
                provider=None,
                model=None,
                message_chunk_size=4,
                llm_event_filter="all",
                claim_workers=1,
                resolver_candidate_limit=24,
                resolver_bucket_limit=0,
                resolver_workers=1,
            )

        self.assertEqual(graph["manifest"]["schema_version"], "scope-time-state-graph-v2-state-merge")
        self.assertNotIn("RESPONSIBLE_FOR", graph["manifest"]["edge_types"])
        self.assertFalse(any(node.get("scope_type") == "task_object" for node in graph["nodes"]))
        self.assertFalse(any(edge.get("type") == "RESPONSIBLE_FOR" for edge in graph["edges"]))
        self.assertFalse(any("event_endpoint_" in str(node.get("extraction_method") or "") for node in graph["nodes"]))
        self.assertNotIn("task_object_scope_count", graph["summary"])
        self.assertEqual(graph["manifest"]["leakage_policy"]["graph_build_inputs"], ["dialogue.json"])

    def test_statefacets_record_primary_claim_and_multi_support_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = graph_builder.build_topic_graph(
                topic_id="01",
                data_root=self._data_root(Path(tmp)),
                claim_mode="heuristic",
                resolver_mode="heuristic",
                max_claims_per_event=2,
                event_limit=0,
                client=None,
                runtime=None,
                provider=None,
                model=None,
                message_chunk_size=4,
                llm_event_filter="all",
                claim_workers=1,
                resolver_candidate_limit=24,
                resolver_bucket_limit=0,
                resolver_workers=1,
            )

        facets = [node for node in graph["nodes"] if node.get("node_type") == "StateFacet"]
        self.assertTrue(facets)
        for facet in facets:
            self.assertIn(facet["primary_claim_id"], facet["support_claim_ids"])
            self.assertTrue(facet["state_dimension"])
            self.assertNotIn("resolver_mode", facet)

    def test_llm_merge_decider_clears_winner_for_non_lifecycle_decisions(self) -> None:
        existing = {"source_event_id": "event-old", "value": "old value"}
        incoming = {"source_event_id": "event-new", "value": "new value"}

        for decision in ("COMPATIBLE", "DIFFERENT_TARGET", "CONFLICTS_WITH"):
            with self.subTest(decision=decision):
                client = StubJsonClient(
                    {
                        "decision": decision,
                        "winner": "incoming",
                        "reason": "synthetic malformed model output",
                    }
                )

                result = graph_builder.merge_decider("llm", client)(existing, incoming)

                self.assertEqual(result["winner"], "none")
                self.assertEqual(result["evidence_event_ids"], ["event-old", "event-new"])


if __name__ == "__main__":
    unittest.main()

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

from ours_scope_time_state.staged import STSGraphEvidenceIndex


class UnifiedRetrievalContractTests(unittest.TestCase):
    def test_old_v6_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_dir = Path(tmp)
            (graph_dir / "manifest.json").write_text(
                json.dumps({"schema_version": "evermembench-sts-topic-graph-v6-endpoint-lifecycle"}),
                encoding="utf-8",
            )
            (graph_dir / "nodes.jsonl").write_text("", encoding="utf-8")
            (graph_dir / "edges.jsonl").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incompatible STS v2 graph schema"):
                STSGraphEvidenceIndex.load(graph_dir)

    def test_active_retrieval_source_has_no_v6_graph_vocabulary(self) -> None:
        sources = [
            BASELINE_DIR / "ours_scope_time_state" / "staged.py",
            BASELINE_DIR / "ours_scope_time_state" / "qa_eval_runner.py",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
        for forbidden in ("RESPONSIBLE_FOR", "task_object", "endpoint_lifecycle"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()

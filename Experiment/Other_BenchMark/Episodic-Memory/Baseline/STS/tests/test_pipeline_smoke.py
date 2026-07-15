from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.run import ClientBundle, main
from STS.graph_builder import EXTRACTION_SCHEMA_VERSION


class ExtractionClient:
    model = "gpt-4o-mini"

    def complete_json(self, _system_prompt, user_prompt):
        records = []
        for chapter_id, text in re.findall(r"<chapter id=(\d+)>\n(.*?)\n</chapter>", user_prompt, re.DOTALL):
            records.append(
                {
                    "chapter_id": int(chapter_id),
                    "concise_summary": " ".join(text.split())[:180],
                    "dates": [],
                    "locations": [],
                    "entities": [],
                    "event_types": [],
                    "claims": [],
                }
            )
        return {"chapters": records}


class FrameClient:
    model = "gpt-4o-mini"

    def complete_json(self, _system_prompt, _user_prompt):
        return {"ordering": "none", "time_values": [], "entity_queries": [], "location_queries": [], "event_type_queries": []}


class StaticClient:
    model = "gpt-4o-mini"

    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, _system_prompt, _user_prompt):
        return dict(self.payload)


FAKE_CLIENTS = ClientBundle(
    extraction=ExtractionClient(),
    merge=StaticClient({"decision": "COMPATIBLE", "winner": "none", "reason": "same"}),
    frame=FrameClient(),
    answer=StaticClient({"answer": "Not enough retrieved evidence."}),
    judge=StaticClient({"score": 0, "correct": False, "reason": "smoke"}),
    embedding_config=None,
)


class PipelineSmokeTests(unittest.TestCase):
    def test_all_stage_builds_retrieves_answers_and_judges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = main(
                ["--stage", "all", "--workers", "2", "--chapter-limit", "2", "--question-limit", "2", "--output-root", str(root)],
                clients=FAKE_CLIENTS,
            )
            self.assertEqual(0, code)
            self.assertTrue((root / "graph" / "book1" / "manifest.json").is_file())
            extraction_cache = json.loads((root / "cache" / "extraction_records.json").read_text())
            manifest = json.loads((root / "graph" / "book1" / "manifest.json").read_text())
            self.assertEqual(EXTRACTION_SCHEMA_VERSION, extraction_cache["schema_version"])
            self.assertEqual("sentence_id", manifest["runtime"]["evidence_mode"])
            self.assertEqual(2, len(json.loads((root / "results" / "qa.json").read_text())["rows"]))
            self.assertEqual(2, len(json.loads((root / "results" / "judged.json").read_text())["rows"]))

    def test_sts_runtime_has_no_artem_imports_or_gold_build_inputs(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in STS_DIR.glob("*.py"))
        self.assertNotIn("Baseline.ARTEM", source)
        self.assertNotIn("artem_epbench", source)
        builder = (STS_DIR / "graph_builder.py").read_text(encoding="utf-8")
        self.assertNotIn("df_qa.parquet", builder)
        self.assertNotIn("df_book_groundtruth.parquet", builder)


if __name__ == "__main__":
    unittest.main()

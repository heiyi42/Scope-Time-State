from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.loader import QAItem
from STS.qa_runner import run_judge, run_qa
from STS.staged import QuestionFrame, RankedChapter, RetrievalResult


QA_ITEM = QAItem(
    row_index=0,
    q_idx=11,
    question="Who attended the workshop?",
    correct_answer=["Julian Ross"],
    correct_answer_chapters=[1],
    retrieval_type="Entities",
    get="all",
)


class FakeIndex:
    def retrieve(self, question, frame_client, **_kwargs):
        return RetrievalResult(
            question=question,
            frame=QuestionFrame(entity_queries=["Julian Ross"]),
            ranked_chapters=[
                RankedChapter(
                    chapter_id=1,
                    score=3.0,
                    occurred_at="2024-03-23T00:00:00",
                    matched_scope_types=["entity", "event_type"],
                    selected_claim_ids=["claim::1"],
                    evidence_spans=["Julian Ross attended the workshop"],
                    raw_text="Julian Ross attended the workshop.",
                    contributions=[],
                )
            ],
            trace={"final_chapter_k": 20},
        )


class EmptyIndex:
    def retrieve(self, question, frame_client, **_kwargs):
        return RetrievalResult(
            question=question,
            frame=QuestionFrame(event_type_queries=["3D Printing Workshop"]),
            ranked_chapters=[],
            retrieval_status="no_grounded_scope",
            trace={"unmatched_anchors": [{"scope_type": "event_type", "query": "3D Printing Workshop"}]},
        )


class CapturingClient:
    def __init__(self, response):
        self.response = response
        self.user_prompts = []

    def complete_json(self, _system_prompt, user_prompt):
        self.user_prompts.append(user_prompt)
        return dict(self.response)


class QARunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_answer_prompt_does_not_receive_gold(self):
        answer_client = CapturingClient({"answer": "Julian Ross"})
        with patch("STS.qa_runner.load_qa", return_value=[QA_ITEM]), patch(
            "STS.qa_runner.STSGraphIndex.load", return_value=FakeIndex()
        ):
            run_qa(
                graph_dir=self.root / "graph",
                output_path=self.root / "qa.json",
                answer_client=answer_client,
                frame_client=CapturingClient({}),
                embedding_config=None,
                offset=0,
                limit=1,
                resume=False,
            )
        prompt = answer_client.user_prompts[0]
        self.assertNotIn("correct_answer", prompt)
        self.assertNotIn("correct_answer_chapters", prompt)

    def test_empty_grounded_retrieval_abstains_without_calling_answer_model(self):
        answer_client = CapturingClient({"answer": "A hallucinated event"})
        output_path = self.root / "qa.json"
        with patch("STS.qa_runner.load_qa", return_value=[QA_ITEM]), patch(
            "STS.qa_runner.STSGraphIndex.load", return_value=EmptyIndex()
        ):
            payload = run_qa(
                graph_dir=self.root / "graph",
                output_path=output_path,
                answer_client=answer_client,
                frame_client=CapturingClient({}),
                embedding_config=None,
                offset=0,
                limit=1,
                resume=False,
            )
        self.assertEqual([], answer_client.user_prompts)
        self.assertEqual("No matching event is present in the memory.", payload["rows"][0]["answer"])
        self.assertEqual("evidence_gate", payload["rows"][0]["answer_source"])

    def test_judge_preserves_raw_answer_and_trace(self):
        qa_path = self.root / "qa.json"
        qa_payload = {
            "rows": [
                {
                    "row_index": 0,
                    "q_idx": 11,
                    "question": QA_ITEM.question,
                    "answer": "Julian Ross",
                    "retrieval_trace": {"ranked_chapters": [1]},
                }
            ]
        }
        qa_path.write_text(json.dumps(qa_payload), encoding="utf-8")
        judge_client = CapturingClient({"score": 10, "correct": True, "reason": "exact"})
        with patch("STS.qa_runner.load_qa", return_value=[QA_ITEM]):
            judged = run_judge(
                qa_result_path=qa_path,
                output_path=self.root / "judged.json",
                judge_client=judge_client,
                resume=False,
            )
        qa_row = qa_payload["rows"][0]
        judged_row = judged["rows"][0]
        self.assertEqual(qa_row["answer"], judged_row["answer"])
        self.assertEqual(qa_row["retrieval_trace"], judged_row["retrieval_trace"])


if __name__ == "__main__":
    unittest.main()

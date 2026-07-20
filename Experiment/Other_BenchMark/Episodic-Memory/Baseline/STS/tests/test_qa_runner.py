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
from STS.qa_runner import _answer_context, run_official_artem_evaluation, run_qa
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
            retrieval_status="no_candidates",
            trace={},
        )


class RoleIndex:
    def retrieve(self, question, frame_client, **_kwargs):
        result = FakeIndex().retrieve(question, frame_client)
        result.ranked_chapters[0].entity_roles = {
            "primary": ["Julian Ross"],
            "participant": ["Morgan Lee"],
        }
        return result


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
                workers=2,
            )
        prompt = answer_client.user_prompts[0]
        self.assertNotIn("correct_answer", prompt)
        self.assertNotIn("correct_answer_chapters", prompt)

    def test_answer_context_keeps_full_source_event_and_state_evidence(self):
        result = FakeIndex().retrieve(QA_ITEM.question, None)
        chapter = result.ranked_chapters[0]
        chapter.raw_text = "source-start " + ("x" * 3000) + " source-end"
        chapter.state_evidence = ["workshop status completed"]
        chapter.relation_evidence = ["SUPERSEDES: planned -> completed"]
        context = _answer_context(result)
        self.assertIn("source-start", context)
        self.assertIn("source-end", context)
        self.assertIn("StateFacet: workshop status completed", context)
        self.assertIn("State relation: SUPERSEDES: planned -> completed", context)

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
                workers=2,
            )
        self.assertEqual([], answer_client.user_prompts)
        self.assertEqual("No matching event is present in the memory.", payload["rows"][0]["answer"])
        self.assertEqual("empty_retrieval", payload["rows"][0]["answer_source"])

    def test_entities_are_composed_from_primary_role_without_answer_model(self):
        answer_client = CapturingClient({"answer": "wrong"})
        with patch("STS.qa_runner.load_qa", return_value=[QA_ITEM]), patch(
            "STS.qa_runner.STSGraphIndex.load", return_value=RoleIndex()
        ):
            payload = run_qa(
                graph_dir=self.root / "graph",
                output_path=self.root / "qa.json",
                answer_client=answer_client,
                frame_client=CapturingClient({}),
                embedding_config=None,
                limit=1,
                resume=False,
                workers=2,
            )
        self.assertEqual([], answer_client.user_prompts)
        self.assertEqual("Julian Ross", payload["rows"][0]["answer"])
        self.assertEqual("graph_entity_roles", payload["rows"][0]["answer_source"])

    def test_official_evaluation_preserves_raw_answer_and_trace(self):
        qa_path = self.root / "qa.json"
        qa_payload = {
            "rows": [
                {
                    "row_index": 0,
                    "q_idx": 11,
                    "question": QA_ITEM.question,
                    "answer": "Julian Ross",
                    "selected_chapter_ids": [1],
                    "retrieval_trace": {"ranked_chapters": [1]},
                }
            ]
        }
        qa_path.write_text(json.dumps(qa_payload), encoding="utf-8")
        official_metric = {
            "predicted_items": ["Julian Ross"],
            "groundtruth_items": ["Julian Ross"],
            "matching_groundtruth_items_score": [{"Julian Ross": 1.0}],
            "explanation": "exact",
            "precision_lenient": 1.0,
            "precision_harsh": 1.0,
            "recall": 1.0,
            "f1_score_lenient": 1.0,
            "f1_score_harsh": 1.0,
        }
        with patch("STS.qa_runner.load_qa", return_value=[QA_ITEM]), patch(
            "STS.qa_runner._official_artem_evaluator", return_value=lambda **_kwargs: official_metric
        ):
            judged = run_official_artem_evaluation(
                qa_result_path=qa_path,
                output_path=self.root / "official_artem.json",
                judge_client=CapturingClient({}),
                resume=False,
                workers=2,
            )
        qa_row = qa_payload["rows"][0]
        judged_row = judged["rows"][0]
        self.assertEqual(qa_row["answer"], judged_row["answer"])
        self.assertEqual(qa_row["retrieval_trace"], judged_row["retrieval_trace"])
        self.assertEqual(1.0, judged_row["candidate_f1"])
        self.assertEqual(1.0, judged["summary"]["overall"]["mean_candidate_f1"])


if __name__ == "__main__":
    unittest.main()

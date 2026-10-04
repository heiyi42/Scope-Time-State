from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sts.extraction.epbench_event_extractor import generate_json


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def judge_prompt(
    retrieval_type: str,
    correct_answer: list[str],
    model_answer: str,
) -> str:
    score_shape = [
        {item: "score_between_0_and_1"} for item in correct_answer
    ]
    return f"""
You are an expert judge evaluating the accuracy of an AI-generated answer
against a known groundtruth. Questions can probe different aspects, such as
actions or events, people, dates, or locations.

Question type: {retrieval_type}
Groundtruth: {json.dumps(correct_answer, ensure_ascii=False)}
AI-generated answer: {model_answer}

Your task:
- Identify all unique items in the AI-generated answer relevant to the question
  type. Return [] if the answer contains negative information saying it cannot
  answer or that no information was found.
- Give each groundtruth item a matching score from 0 to 1. Use 1 when found,
  including synonyms, paraphrases, or close meanings; 0.5 when only related but
  not explicitly stated; and 0 when missing.
- Briefly explain the evaluation.

Return only this JSON object:
{{
  "identified_items_in_AI_answer": ["item_1", "item_2"],
  "matching_score": {json.dumps(score_shape, ensure_ascii=False)},
  "explanation": "Brief explanation"
}}
""".strip()


def _f1(precision: float | None, recall: float | None) -> float:
    if precision == 0 and recall == 0:
        return 0.0
    if precision is not None and recall is not None:
        return 2 * precision * recall / (precision + recall)
    if precision is None and recall is None:
        return 1.0
    return 0.0


def generate_metrics(
    correct_answer: list[str],
    evaluation: dict,
) -> dict:
    """Match the EPBench ARTEM lenient/harsh item-level metric semantics."""
    groundtruth = list(dict.fromkeys(str(item) for item in correct_answer))
    predictions = evaluation.get("identified_items_in_AI_answer")
    if not isinstance(predictions, list):
        raise ValueError("Judge identified_items_in_AI_answer must be a list")
    predictions = [str(item) for item in predictions]
    scores_raw = evaluation.get("matching_score")
    if not isinstance(scores_raw, list):
        raise ValueError("Judge matching_score must be a list")

    scores_by_item: dict[str, float] = {}
    for item in scores_raw:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            try:
                scores_by_item[str(key)] = min(
                    1.0, max(0.0, float(value))
                )
            except (TypeError, ValueError):
                scores_by_item[str(key)] = 0.0
    matching = [
        {item: scores_by_item.get(item, 0.0)}
        for item in groundtruth
    ]
    score_sum = min(
        sum(next(iter(item.values())) for item in matching),
        float(len(groundtruth)),
    )
    predicted_harsh = len(predictions)
    predicted_lenient = min(predicted_harsh, len(groundtruth))
    precision_lenient = (
        score_sum / predicted_lenient if predicted_lenient else None
    )
    precision_harsh = (
        score_sum / predicted_harsh if predicted_harsh else None
    )
    recall = (
        score_sum / len(groundtruth) if groundtruth else None
    )
    return {
        "predicted_items": predictions,
        "groundtruth_items": groundtruth,
        "matching_groundtruth_items_score": matching,
        "explanation": str(evaluation.get("explanation", "")),
        "nb_preds_lenient": predicted_lenient,
        "nb_preds_harsh": predicted_harsh,
        "nb_gt": len(groundtruth),
        "sum_scores": score_sum,
        "precision_lenient": precision_lenient,
        "precision_harsh": precision_harsh,
        "recall": recall,
        "f1_score_lenient": _f1(precision_lenient, recall),
        "f1_score_harsh": _f1(precision_harsh, recall),
        "diff_f1": (
            _f1(precision_lenient, recall)
            - _f1(precision_harsh, recall)
        ),
    }


class EPBenchJudgeRunner:
    def __init__(self, llm_provider, concurrency: int = 8):
        self.llm = llm_provider
        self.concurrency = max(1, concurrency)

    async def run(
        self,
        qa_path: str | Path,
        data_folder: str | Path,
        output_path: str | Path,
        *,
        limit: int | None = None,
    ) -> Path:
        qa_path = Path(qa_path)
        data_folder = Path(data_folder)
        output_path = Path(output_path)
        qa_bytes = qa_path.read_bytes()
        qa = json.loads(qa_bytes)
        if qa.get("schema_version") != "epbench_qa_v1":
            raise ValueError("Judge requires an epbench_qa_v1 QA file")
        rows = qa.get("rows", [])
        if limit is not None:
            rows = rows[:limit]

        frame = pd.read_parquet(data_folder / "df_qa.parquet")
        model = str(getattr(self.llm, "model", "unknown"))
        signature = hashlib.sha256(
            b"\0".join(
                [
                    hashlib.sha256(qa_bytes).hexdigest().encode(),
                    model.encode(),
                    b"epbench-artem-judge-v1",
                ]
            )
        ).hexdigest()
        completed: dict[int, dict] = {}
        if output_path.exists():
            previous = json.loads(output_path.read_text(encoding="utf-8"))
            if previous.get("judge_signature") == signature:
                completed = {
                    int(row["row_idx"]): row
                    for row in previous.get("rows", [])
                }

        semaphore = asyncio.Semaphore(self.concurrency)
        save_lock = asyncio.Lock()

        def payload(values: list[dict]) -> dict:
            ordered = sorted(values, key=lambda row: row["row_idx"])
            return {
                "schema_version": "epbench_judge_v1",
                "qa_path": str(qa_path.resolve()),
                "qa_sha256": hashlib.sha256(qa_bytes).hexdigest(),
                "judge_model": model,
                "judge_signature": signature,
                "summary": {
                    "count": len(ordered),
                    "f1_score_lenient": (
                        sum(row["f1_score_lenient"] for row in ordered)
                        / len(ordered)
                        if ordered
                        else None
                    ),
                    "f1_score_harsh": (
                        sum(row["f1_score_harsh"] for row in ordered)
                        / len(ordered)
                        if ordered
                        else None
                    ),
                },
                "rows": ordered,
            }

        async def one(qa_row: dict) -> dict:
            row_idx = int(qa_row["row_idx"])
            if row_idx in completed:
                return completed[row_idx]
            if row_idx < 0 or row_idx >= len(frame):
                raise IndexError(f"QA row_idx out of range: {row_idx}")
            gold = frame.iloc[row_idx]
            if int(gold.q_idx) != int(qa_row["qa_id"]):
                raise ValueError(
                    f"QA/gold q_idx mismatch at row {row_idx}"
                )
            correct_answer = [
                str(item) for item in _jsonable(gold.correct_answer)
            ]
            async with semaphore:
                evaluation = await generate_json(
                    self.llm,
                    judge_prompt(
                        str(gold.retrieval_type),
                        correct_answer,
                        str(qa_row["answer"]),
                    ),
                )
            metrics = generate_metrics(correct_answer, evaluation)
            result = {
                "row_idx": row_idx,
                "qa_id": int(qa_row["qa_id"]),
                "question": str(gold.question),
                "retrieval_type": str(gold.retrieval_type),
                "model_answer": str(qa_row["answer"]),
                "correct_answer": correct_answer,
                **metrics,
            }
            async with save_lock:
                completed[row_idx] = result
                _atomic_json(
                    output_path,
                    payload(list(completed.values())),
                )
                print(
                    f"[Judge] {len(completed)}/{len(rows)} "
                    f"row={row_idx} "
                    f"F1={result['f1_score_lenient']:.4f}",
                    flush=True,
                )
            return result

        evaluated = await asyncio.gather(*(one(row) for row in rows))
        _atomic_json(output_path, payload(evaluated))
        return output_path

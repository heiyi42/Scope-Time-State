"""Resumable EPBench STS answer and LLM-judge stages."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .config import ANSWER_MODEL, JUDGE_MODEL
from .loader import load_qa
from .staged import EmbeddingConfig, STSGraphIndex


ABSTENTION_ANSWER = "No matching event is present in the memory."
ANSWER_SYSTEM_PROMPT = f"""Answer the EPBench question using only facts explicitly supported by the retrieved STS evidence.
Do not infer a requested entity, location, time, event, or detail from semantic similarity alone. If the evidence does not explicitly establish the requested item, answer exactly: {ABSTENTION_ANSWER}
Return JSON with one field: {{\"answer\": \"concise answer\"}}. Do not mention retrieval."""
JUDGE_SYSTEM_PROMPT = """Judge a prediction against the reference answer for the supplied question.
Return JSON only: {\"score\": 0, \"correct\": false, \"reason\": \"short grounded reason\"}.
Score must be an integer from 0 to 10."""


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_result(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"rows": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError(f"invalid checkpoint: {path}")
    return payload


def _answer_context(result: Any, *, max_raw_chars: int = 2400) -> str:
    blocks: list[str] = []
    for row in result.ranked_chapters:
        evidence = "\n".join(f"- Evidence: {span}" for span in row.evidence_spans)
        raw_excerpt = row.raw_text[:max_raw_chars]
        blocks.append(
            f"[Chapter {row.chapter_id}; time={row.occurred_at or 'unknown'}]\n"
            f"{evidence}\n- Source excerpt: {raw_excerpt}"
        )
    return "\n\n".join(blocks)


def run_qa(
    graph_dir: Path,
    output_path: Path,
    answer_client: Any,
    frame_client: Any,
    embedding_config: EmbeddingConfig | None,
    offset: int = 0,
    limit: int = 686,
    resume: bool = True,
    **retrieval_kwargs: Any,
) -> dict[str, Any]:
    if offset < 0 or limit < 0:
        raise ValueError("offset and limit must be non-negative")
    qa_items = load_qa()
    selected = qa_items[offset : offset + limit]
    index = STSGraphIndex.load(Path(graph_dir), embedding_config=embedding_config)
    payload = _read_result(Path(output_path)) if resume else {"rows": []}
    completed = {int(row["row_index"]): row for row in payload["rows"]}
    for item in selected:
        if item.row_index in completed:
            continue
        retrieval = index.retrieve(item.question, frame_client, **retrieval_kwargs)
        context = _answer_context(retrieval)
        if retrieval.ranked_chapters:
            user_prompt = json.dumps(
                {"question": item.question, "retrieved_context": context},
                ensure_ascii=False,
                indent=2,
            )
            raw = dict(answer_client.complete_json(ANSWER_SYSTEM_PROMPT, user_prompt))
            answer = " ".join(str(raw.get("answer") or "").split())
            answer_source = "llm"
            if not answer:
                raise ValueError(f"answer model returned an empty answer for row {item.row_index}")
        else:
            answer = ABSTENTION_ANSWER
            answer_source = "evidence_gate"
            raw = {
                "answer": answer,
                "retrieval_status": retrieval.retrieval_status,
            }
        row = {
            "row_index": item.row_index,
            "q_idx": item.q_idx,
            "question": item.question,
            "retrieval_type": item.retrieval_type,
            "get": item.get,
            "selected_chapter_ids": [chapter.chapter_id for chapter in retrieval.ranked_chapters],
            "context": context,
            "answer": answer,
            "answer_source": answer_source,
            "raw_answer": raw,
            "answer_model": str(getattr(answer_client, "model", ANSWER_MODEL)),
            "retrieval_trace": retrieval.to_dict(),
        }
        completed[item.row_index] = row
        payload = {
            "answer_model": str(getattr(answer_client, "model", ANSWER_MODEL)),
            "rows": [completed[key] for key in sorted(completed)],
        }
        _write_atomic(Path(output_path), payload)
    return payload


def _judge_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        scores = [float(row["judge"]["score"]) for row in group]
        return {
            "count": len(group),
            "mean_score": sum(scores) / len(scores) if scores else 0.0,
            "accuracy": sum(bool(row["judge"]["correct"]) for row in group) / len(group) if group else 0.0,
        }

    return {
        "overall": summarize(rows),
        "all": summarize([row for row in rows if row.get("get") == "all"]),
        "latest": summarize([row for row in rows if row.get("get") == "latest"]),
        "chronological": summarize([row for row in rows if row.get("get") == "chronological"]),
    }


def run_judge(
    qa_result_path: Path,
    output_path: Path,
    judge_client: Any,
    resume: bool = True,
) -> dict[str, Any]:
    qa_payload = _read_result(Path(qa_result_path))
    qa_by_index = {item.row_index: item for item in load_qa()}
    payload = _read_result(Path(output_path)) if resume else {"rows": []}
    completed = {int(row["row_index"]): row for row in payload["rows"]}
    for qa_row in qa_payload["rows"]:
        row_index = int(qa_row["row_index"])
        if row_index in completed:
            continue
        item = qa_by_index.get(row_index)
        if item is None:
            raise ValueError(f"QA checkpoint references unknown EPBench row {row_index}")
        user_prompt = json.dumps(
            {
                "question": qa_row["question"],
                "reference_answer": item.correct_answer,
                "prediction": qa_row["answer"],
            },
            ensure_ascii=False,
            indent=2,
        )
        raw = dict(judge_client.complete_json(JUDGE_SYSTEM_PROMPT, user_prompt))
        try:
            score = int(round(float(raw.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        score = min(10, max(0, score))
        judged_row = dict(qa_row)
        judged_row["judge"] = {
            "score": score,
            "correct": bool(raw.get("correct")),
            "reason": " ".join(str(raw.get("reason") or "").split()),
        }
        completed[row_index] = judged_row
        rows = [completed[key] for key in sorted(completed)]
        payload = {
            "judge_model": str(getattr(judge_client, "model", JUDGE_MODEL)),
            "rows": rows,
            "summary": _judge_summary(rows),
        }
        _write_atomic(Path(output_path), payload)
    return payload


__all__ = ["run_judge", "run_qa"]

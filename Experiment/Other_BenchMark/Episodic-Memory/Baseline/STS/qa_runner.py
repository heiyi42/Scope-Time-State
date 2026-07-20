"""Resumable EPBench STS answer and official ARTEM evaluation stages."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from .config import ANSWER_MODEL
from .loader import load_qa
from .staged import EmbeddingConfig, STSGraphIndex


ABSTENTION_ANSWER = "No matching event is present in the memory."
ANSWER_SYSTEM_PROMPT = f"""Answer the EPBench question using only facts explicitly supported by the retrieved STS evidence.
Do not infer a requested entity, location, time, event, or detail from semantic similarity alone. If the evidence does not explicitly establish the requested item, answer exactly: {ABSTENTION_ANSWER}
Return JSON with one field: {{\"answer\": \"concise answer\"}}. Do not mention retrieval."""


def _official_artem_evaluator() -> Any:
    """Load EPBench's ARTEM evaluator rather than using a local surrogate judge."""
    artem_dir = Path(__file__).resolve().parent.parent / "ARTEM"
    if str(artem_dir) not in sys.path:
        sys.path.insert(0, str(artem_dir))
    from LLM_as_a_Judge import evaluate_answer_with_art  # type: ignore

    return evaluate_answer_with_art


class _OfficialJudgeWrapper:
    """Expose the official evaluator's LLM wrapper interface over our cached client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def generate(
        self,
        user_prompt: str,
        system_prompt: str = "",
        max_new_tokens: int = 4096,
    ) -> str:
        del max_new_tokens
        return json.dumps(self.client.complete_json(system_prompt, user_prompt), ensure_ascii=False)


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


def _answer_context(result: Any, *, max_raw_chars: int | None = None) -> str:
    blocks: list[str] = []
    for row in result.ranked_chapters:
        evidence = "\n".join(f"- Evidence: {span}" for span in row.evidence_spans)
        scopes = "\n".join(
            f"- {scope_type.title()} scopes: {', '.join(values)}"
            for scope_type, values in row.scope_values.items()
            if values
        )
        states = "\n".join(f"- StateFacet: {value}" for value in row.state_evidence)
        relations = "\n".join(
            f"- State relation: {value}" for value in row.relation_evidence
        )
        raw_excerpt = row.raw_text if max_raw_chars is None else row.raw_text[:max_raw_chars]
        blocks.append(
            f"[Chapter {row.chapter_id}; time={row.occurred_at or 'unknown'}]\n"
            f"{scopes}\n{evidence}\n{states}\n{relations}\n"
            f"- Source Event (raw chapter text): {raw_excerpt}"
        )
    return "\n\n".join(blocks)


def _role_answer(retrieval_type: str, question: str, ranked_chapters: list[Any]) -> list[str] | None:
    if retrieval_type == "Entities":
        roles = ("primary",)
    elif retrieval_type == "Other entities":
        roles = ("participant", "mentioned")
    else:
        return None
    seen: set[str] = set()
    values: list[str] = []
    normalized_question = question.casefold()
    for chapter in ranked_chapters:
        for role in roles:
            for value in chapter.entity_roles.get(role, []):
                normalized = value.casefold()
                if not normalized or normalized in seen:
                    continue
                if retrieval_type == "Other entities" and normalized in normalized_question:
                    continue
                seen.add(normalized)
                values.append(value)
    return values


def run_qa(
    graph_dir: Path,
    output_path: Path,
    answer_client: Any,
    frame_client: Any,
    embedding_config: EmbeddingConfig | None,
    offset: int = 0,
    limit: int = 686,
    resume: bool = True,
    question_gets: tuple[str, ...] = (),
    refresh_existing: bool = False,
    workers: int = 1,
    **retrieval_kwargs: Any,
) -> dict[str, Any]:
    if offset < 0 or limit < 0:
        raise ValueError("offset and limit must be non-negative")
    if workers < 1:
        raise ValueError("workers must be positive")
    qa_items = load_qa()
    selected = qa_items[offset : offset + limit]
    selected_gets = {value.strip().lower() for value in question_gets if value.strip()}
    if selected_gets:
        selected = [item for item in selected if item.get in selected_gets]
    index = STSGraphIndex.load(Path(graph_dir), embedding_config=embedding_config)
    payload = _read_result(Path(output_path)) if resume else {"rows": []}
    completed = {int(row["row_index"]): row for row in payload["rows"]}
    if refresh_existing:
        for item in selected:
            completed.pop(item.row_index, None)
    pending = [item for item in selected if item.row_index not in completed]

    def answer_item(item: Any) -> dict[str, Any]:
        retrieval = index.retrieve(item.question, frame_client, **retrieval_kwargs)
        context = _answer_context(retrieval)
        role_values = _role_answer(
            item.retrieval_type,
            item.question,
            retrieval.ranked_chapters,
        )
        if role_values:
            answer = ", ".join(role_values)
            answer_source = "graph_entity_roles"
            raw = {"answer": answer, "entity_roles": role_values}
        elif retrieval.ranked_chapters:
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
            answer_source = "empty_retrieval"
            raw = {
                "answer": answer,
                "retrieval_status": retrieval.retrieval_status,
            }
        return {
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

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(answer_item, item): item.row_index for item in pending}
        for future in as_completed(futures):
            row = future.result()
            completed[int(row["row_index"])] = row
            payload = {
                "answer_model": str(getattr(answer_client, "model", ANSWER_MODEL)),
                "rows": [completed[key] for key in sorted(completed)],
            }
            _write_atomic(Path(output_path), payload)
    return payload


def _official_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        def mean(key: str) -> float | None:
            values = [float(row[key]) for row in group if row.get(key) is not None]
            return sum(values) / len(values) if values else None

        return {
            "count": len(group),
            "mean_candidate_precision": mean("candidate_precision"),
            "mean_candidate_recall": mean("candidate_recall"),
            "mean_candidate_f1": mean("candidate_f1"),
            "mean_f1_lenient": mean("f1_score_lenient"),
            "mean_f1_harsh": mean("f1_score_harsh"),
            "mean_precision_lenient": mean("precision_lenient"),
            "mean_precision_harsh": mean("precision_harsh"),
            "mean_recall": mean("recall"),
        }

    return {
        "overall": summarize(rows),
        "all": summarize([row for row in rows if row.get("get") == "all"]),
        "latest": summarize([row for row in rows if row.get("get") == "latest"]),
        "chronological": summarize([row for row in rows if row.get("get") == "chronological"]),
    }


def _candidate_metrics(
    predicted_chapter_ids: list[Any], gold_chapter_ids: list[Any]
) -> dict[str, float]:
    """Score retrieved source Events as EPBench chapter candidates after QA completes."""
    predicted = {int(value) for value in predicted_chapter_ids}
    gold = {int(value) for value in gold_chapter_ids}
    overlap = len(predicted.intersection(gold))
    precision = overlap / len(predicted) if predicted else 0.0
    recall = overlap / len(gold) if gold else 0.0
    return {
        "candidate_precision": precision,
        "candidate_recall": recall,
        "candidate_f1": 2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0,
    }


def run_official_artem_evaluation(
    qa_result_path: Path,
    output_path: Path,
    judge_client: Any,
    resume: bool = True,
    question_gets: tuple[str, ...] = (),
    refresh_existing: bool = False,
    workers: int = 1,
) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be positive")
    qa_payload = _read_result(Path(qa_result_path))
    qa_by_index = {item.row_index: item for item in load_qa()}
    payload = _read_result(Path(output_path)) if resume else {"rows": []}
    completed = {int(row["row_index"]): row for row in payload["rows"]}
    selected_gets = {value.strip().lower() for value in question_gets if value.strip()}
    if refresh_existing:
        for qa_row in qa_payload["rows"]:
            if not selected_gets or str(qa_row.get("get") or "").lower() in selected_gets:
                completed.pop(int(qa_row["row_index"]), None)
    pending = []
    for qa_row in qa_payload["rows"]:
        if selected_gets and str(qa_row.get("get") or "").lower() not in selected_gets:
            continue
        row_index = int(qa_row["row_index"])
        if row_index in completed:
            continue
        item = qa_by_index.get(row_index)
        if item is None:
            raise ValueError(f"QA checkpoint references unknown EPBench row {row_index}")
        pending.append((qa_row, item))

    evaluate_answer_with_art = _official_artem_evaluator()
    official_judge = _OfficialJudgeWrapper(judge_client)

    def evaluate_item(qa_row: dict[str, Any], item: Any) -> dict[str, Any]:
        metric = evaluate_answer_with_art(
            llm_answer=qa_row["answer"],
            correct_answer=item.correct_answer,
            retrieval_type=item.retrieval_type,
            judge_model=official_judge,
        )
        return {
            **qa_row,
            **metric,
            **_candidate_metrics(
                list(qa_row.get("selected_chapter_ids") or []),
                list(item.correct_answer_chapters or []),
            ),
            "correct_answer": item.correct_answer,
            "correct_answer_chapters": item.correct_answer_chapters,
            "official_evaluator": "ARTEM",
        }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(evaluate_item, qa_row, item): int(qa_row["row_index"])
            for qa_row, item in pending
        }
        for future in as_completed(futures):
            evaluated_row = future.result()
            completed[int(evaluated_row["row_index"])] = evaluated_row
            rows = [completed[key] for key in sorted(completed)]
            payload = {
                "judge_model": str(getattr(judge_client, "model", "unknown")),
                "evaluator": "official_artem",
                "rows": rows,
                "summary": _official_summary(rows),
            }
            _write_atomic(Path(output_path), payload)
    return payload


__all__ = ["run_official_artem_evaluation", "run_qa"]

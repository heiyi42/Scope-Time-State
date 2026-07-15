"""Run official ARTEM answer generation and judging with gpt-4o-mini."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from config import (
    BOOK_ID,
    DEFAULT_OUTPUT_ROOT,
    OFFICIAL_ARTEM_DIR,
    REPO_ROOT,
    book_output_dir,
)


MODEL = "gpt-4o-mini"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(OFFICIAL_ARTEM_DIR) not in sys.path:
    sys.path.insert(0, str(OFFICIAL_ARTEM_DIR))

from Experiment.run.common.llm_client import LLMClient, provider_config  # noqa: E402
from LLM_as_a_Judge import (  # noqa: E402
    ARTRetrievalResult,
    ARTMemoryEvaluator,
    ARTMemorySystem,
    LLMWrapper,
    load_questions_from_json,
)


class LatestCorrectedARTMemorySystem(ARTMemorySystem):
    """Preserve official behavior except for the reversed latest-event index."""

    def retrieve_events(
        self,
        question: str,
        question_index: int,
        retrieval_type: str,
        question_type: str = "all",
        book_id: int = BOOK_ID,
        cue_completed: str | None = None,
    ) -> ARTRetrievalResult:
        if question_type != "latest":
            return super().retrieve_events(
                question,
                question_index,
                retrieval_type,
                question_type,
                book_id,
                cue_completed,
            )

        book_rows = self.retrieval_data.get(book_id, [])
        if question_index < 0 or question_index >= len(book_rows):
            return self._create_empty_result(question_index, retrieval_type, question_type)

        events = (
            book_rows[question_index]
            .get("results", {})
            .get("all_vigilant_events_time_sorted", [])
        )
        retrieved_events = (
            [self._parse_event_from_json(events[-1], question_index)] if events else []
        )
        return ARTRetrievalResult(
            qid=question_index,
            retrieved_events=retrieved_events,
            retrieval_type=retrieval_type,
            question_type=question_type,
        )


class CachedOpenAIWrapper(LLMWrapper):
    def __init__(self, client: LLMClient, json_output: bool) -> None:
        self.client = client
        self.json_output = json_output

    def generate(
        self,
        user_prompt: str,
        system_prompt: str = "",
        max_new_tokens: int = 4096,
    ) -> str:
        del max_new_tokens
        if self.json_output:
            return json.dumps(
                self.client.complete_json(system_prompt, user_prompt),
                ensure_ascii=False,
            )
        return self.client.complete_text(system_prompt, user_prompt)


def _client(cache_path: Path, use_cache: bool) -> LLMClient:
    load_dotenv(REPO_ROOT / ".env")
    api_key, _, api_base = provider_config("openai")
    return LLMClient(
        provider="openai",
        model=MODEL,
        api_key=api_key,
        api_base=api_base,
        cache_path=cache_path,
        use_cache=use_cache,
    )


def run_answer_and_eval(
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    question_offset: int = 0,
    limit_questions: int = 686,
    use_cache: bool = True,
) -> Path:
    """Use official ARTEM prompts/metrics with gpt-4o-mini for answer and judge."""
    book_dir = book_output_dir(output_root)
    qa_path = book_dir / f"qa_book{BOOK_ID}.json"
    retrieval_path = book_dir / f"match_based_retrieval_results_book{BOOK_ID}.json"
    missing = [path for path in (qa_path, retrieval_path) if not path.is_file()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"ARTEM answer/eval inputs are incomplete:\n{formatted}")

    questions = load_questions_from_json(str(qa_path), BOOK_ID)
    selected_questions = questions[question_offset : question_offset + limit_questions]
    with retrieval_path.open("r", encoding="utf-8") as stream:
        retrieval_count = len(json.load(stream).get("retrieval_results", []))
    if retrieval_count != len(selected_questions):
        raise ValueError(
            "Retrieval/answer selection mismatch: "
            f"retrieval rows={retrieval_count}, selected QA rows={len(selected_questions)}"
        )

    answer_client = _client(
        Path(output_root) / "llm_cache.answers.gpt-4o-mini.json",
        use_cache,
    )
    judge_client = _client(
        Path(output_root) / "llm_cache.judge.gpt-4o-mini.json",
        use_cache,
    )
    memory = LatestCorrectedARTMemorySystem(str(Path(output_root).resolve()))
    memory.load_retrieval_data_for_books([BOOK_ID])
    evaluator = ARTMemoryEvaluator(
        answering_model=CachedOpenAIWrapper(answer_client, json_output=False),
        judge_model=CachedOpenAIWrapper(judge_client, json_output=True),
        art_system=memory,
        output_dir=str(book_dir / "art_evaluation_results"),
    )
    results_df = evaluator.evaluate_questions(
        selected_questions,
        memory_type="ARTEM",
        model_name=MODEL,
    )
    for local_index, row in enumerate(evaluator.results):
        row["query_id"] = question_offset + local_index
    if "question_index" in results_df.columns:
        results_df["query_id"] = [question_offset + i for i in range(len(results_df))]

    experiment_name = (
        f"artem_gpt-4o-mini_q{question_offset}_"
        f"{question_offset + len(selected_questions) - 1}"
    )
    saved = evaluator.save_results_to_json(
        results_df,
        experiment_name=experiment_name,
        save_by_book=True,
        output_base_path=str(Path(output_root).resolve()),
    )
    detailed_path = Path(saved["overall"]["detailed_results"])
    print(f"ARTEM answer/eval ready: {detailed_path}")
    return detailed_path

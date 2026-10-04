"""STS's original three-vote LoCoMo LLM Judge, adapted for STS outputs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import statistics
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from sts.config import ExperimentConfig


console = Console()
NUM_RUNS = 3
REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("STS_JUDGE_TIMEOUT_SECONDS", "45")
)
CATEGORY_NAMES = {
    1: "Multi-Hop",
    2: "Temporal",
    3: "Open Domain",
    4: "Single-Hop",
}


def build_accuracy_prompt(question: str, gold_answer: str, response: str) -> str:
    """Return the historical STS three-vote accuracy prompt."""
    return f"""
    Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given the following data:
        (1) a question (posed by one user to another user),
        (2) a 'gold' (ground truth) answer,
        (3) a generated answer
    which you will score as CORRECT/WRONG.

    The point of the question is to ask about something one user should know about the other user based on their prior conversations.
    The gold answer will usually be a concise and short answer that includes the referenced topic, for example:
    Question: Do you remember what I got the last time I went to Hawaii?
    Gold answer: A shell necklace
    The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.

    For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like "last Tuesday" or "next month"), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it CORRECT if it's the same date.

    Now it's time for the real question:
    Question: {question}
    Gold answer: {gold_answer}
    Generated answer: {response}

    First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG.
    Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.

    Just return the label CORRECT or WRONG in a json format with the key as "label".
    """


def parse_judge_label(message_content: str) -> bool:
    """Parse the same JSON/text fallbacks accepted by the original evaluator."""
    try:
        label = json.loads(message_content)["label"]
    except (json.JSONDecodeError, KeyError, TypeError):
        json_match = re.search(
            r'\{[^{}]*"label"\s*:\s*"[^"]+"\s*[^{}]*\}',
            message_content,
        )
        if json_match:
            label = json.loads(json_match.group())["label"]
        else:
            upper = message_content.upper()
            if "CORRECT" in upper and "WRONG" not in upper:
                label = "CORRECT"
            elif "WRONG" in upper and "CORRECT" not in upper:
                label = "WRONG"
            else:
                raise ValueError(
                    f"Unable to extract label from response: {message_content[:200]}"
                )
    normalized = str(label).strip().lower()
    if normalized not in {"correct", "wrong"}:
        raise ValueError(f"Invalid judge label: {label!r}")
    return normalized == "correct"


async def locomo_grader(
    llm_client: AsyncOpenAI,
    model: str,
    semaphore: asyncio.Semaphore,
    question: str,
    gold_answer: str,
    response: str,
    max_retries: int = 5,
) -> bool:
    """Run one original STS CORRECT/WRONG judgment."""
    system_prompt = """
        You are an expert grader that determines if answers to questions match a gold standard answer
        """
    last_exception: Exception | None = None
    for attempt in range(max_retries):
        try:
            async with semaphore:
                api_response = await llm_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": build_accuracy_prompt(
                                question,
                                gold_answer,
                                response,
                            ),
                        },
                    ],
                    temperature=0,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            return parse_judge_label(
                api_response.choices[0].message.content or ""
            )
        except Exception as error:
            last_exception = error
            if attempt < max_retries - 1:
                wait_time = (2**attempt) * 0.5
                console.print(
                    f"[yellow]API call error "
                    f"({attempt + 1}/{max_retries}): "
                    f"{type(error).__name__}: {error}[/yellow]"
                )
                await asyncio.sleep(wait_time)
    assert last_exception is not None
    raise last_exception


def atomic_write_json(path: Path, data: Any) -> None:
    """Write a complete JSON file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def response_key(response: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "question": response.get("question", ""),
            "golden_answer": response.get("golden_answer", ""),
            "category": response.get("category"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def judge_signature(response_path: Path, model: str, base_url: str) -> str:
    payload = {
        "version": 1,
        "responses_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
        "model": model,
        "base_url": base_url,
        "num_runs": NUM_RUNS,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_checkpoint(path: Path, signature: str) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("version") != 1 or payload.get("signature") != signature:
        return {}
    results = payload.get("results")
    return results if isinstance(results, dict) else {}


def save_checkpoint(
    path: Path,
    signature: str,
    results: dict[str, dict[str, Any]],
) -> None:
    atomic_write_json(
        path,
        {"version": 1, "signature": signature, "results": results},
    )


def make_graded_response(
    response: dict[str, Any],
    judgments: list[bool],
) -> dict[str, Any]:
    return {
        "question": response.get("question"),
        "answer": response.get("answer"),
        "golden_answer": response.get("golden_answer"),
        "category": response.get("category"),
        "llm_judgments": {
            f"judgment_{index + 1}": value
            for index, value in enumerate(judgments)
        },
        "nlp_metrics": {},
        "response_duration_ms": response.get("response_duration_ms", 0.0),
        "search_duration_ms": response.get("search_duration_ms", 0.0),
        "total_duration_ms": (
            response.get("response_duration_ms", 0.0)
            + response.get("search_duration_ms", 0.0)
        ),
    }


async def judge_response(
    response: dict[str, Any],
    client: AsyncOpenAI,
    model: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    judgments = await asyncio.gather(
        *[
            locomo_grader(
                client,
                model,
                semaphore,
                str(response.get("question", "")),
                str(response.get("golden_answer", "")),
                str(response.get("answer", "")),
            )
            for _ in range(NUM_RUNS)
        ]
    )
    return make_graded_response(response, judgments)


def calculate_summary(
    all_grades: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    category_stats = {
        category: {"correct": 0, "total": 0}
        for category in CATEGORY_NAMES
    }
    run_scores: list[float] = []
    overall_correct = 0
    overall_total = 0
    for group in all_grades.values():
        for response in group:
            judgments = response["llm_judgments"]
            is_correct = sum(bool(value) for value in judgments.values()) >= 2
            category = int(response["category"])
            overall_total += 1
            overall_correct += int(is_correct)
            category_stats[category]["total"] += 1
            category_stats[category]["correct"] += int(is_correct)
    for run_index in range(1, NUM_RUNS + 1):
        key = f"judgment_{run_index}"
        values = [
            bool(response["llm_judgments"][key])
            for group in all_grades.values()
            for response in group
        ]
        if values:
            run_scores.append(sum(values) / len(values))
    return {
        "overall_correct": overall_correct,
        "overall_total": overall_total,
        "overall_accuracy": (
            overall_correct / overall_total if overall_total else None
        ),
        "category_stats": category_stats,
        "run_scores": run_scores,
        "mean_run_score": statistics.mean(run_scores) if run_scores else None,
        "std_run_score": statistics.pstdev(run_scores) if run_scores else None,
    }


def print_summary(summary: dict[str, Any]) -> None:
    console.print("\n[bold]LLM-as-a-Judge Results by Category:[/bold]\n")
    console.print("-" * 60)
    console.print(
        f"{'Category':<25} {'Correct':>10} {'Total':>10} {'Accuracy':>12}"
    )
    console.print("-" * 60)
    for category in (4, 1, 2, 3):
        stats = summary["category_stats"][category]
        accuracy = (
            f"{stats['correct'] / stats['total'] * 100:.2f}%"
            if stats["total"] else "N/A"
        )
        console.print(
            f"{CATEGORY_NAMES[category]:<25} "
            f"{stats['correct']:>10} {stats['total']:>10} {accuracy:>12}"
        )
    console.print("-" * 60)
    if summary["overall_total"]:
        console.print(
            f"{'Overall':<25} {summary['overall_correct']:>10} "
            f"{summary['overall_total']:>10} "
            f"{summary['overall_accuracy'] * 100:>11.2f}%"
        )
    console.print("-" * 60)
    if summary["run_scores"]:
        console.print(
            f"\n[bold green]LLM-as-a-Judge average score:[/bold green] "
            f"{summary['mean_run_score']:.4f}"
        )
        console.print(
            f"[bold]Standard deviation:[/bold] "
            f"{summary['std_run_score']:.4f}"
        )
        console.print(
            f"[bold]Evaluation details:[/bold] {NUM_RUNS} rounds, "
            f"{summary['overall_total']} questions"
        )
        console.print(
            f"[bold]Per-round scores:[/bold] "
            f"{[round(score, 4) for score in summary['run_scores']]}"
        )
    else:
        console.print("[yellow]No responses evaluated[/yellow]")


async def main() -> None:
    config = ExperimentConfig()
    results_dir = config.experiment_dir()
    response_path = results_dir / "responses.json"
    judged_path = results_dir / "judged.json"
    checkpoint_path = results_dir / "judge_checkpoint.json"
    if not response_path.is_file():
        raise FileNotFoundError(f"Response file not found: {response_path}")

    judge_config = config.judge_llm_config
    model = judge_config["model"]
    signature = judge_signature(
        response_path,
        model,
        judge_config["base_url"],
    )
    completed = load_checkpoint(checkpoint_path, signature)
    locomo_responses = json.loads(response_path.read_text(encoding="utf-8"))
    pending = [
        response
        for responses in locomo_responses.values()
        for response in responses
        if int(response.get("category", 0)) != 5
        and response.get("golden_answer") is not None
        and response_key(response) not in completed
    ]
    total = sum(
        1
        for responses in locomo_responses.values()
        for response in responses
        if int(response.get("category", 0)) != 5
        and response.get("golden_answer") is not None
    )

    console.print("\n[bold cyan]" + "=" * 80 + "[/bold cyan]")
    console.print("[bold cyan]STS Original Three-Vote LLM Judge[/bold cyan]")
    console.print("[bold cyan]" + "=" * 80 + "[/bold cyan]")
    console.print(f"[bold]Model:[/bold] {model}")
    console.print(f"[bold]Evaluation rounds:[/bold] {NUM_RUNS}")
    console.print(
        f"[bold]Global API concurrency:[/bold] "
        f"{config.max_concurrent_requests}"
    )
    console.print(
        f"[bold]Per-request timeout:[/bold] "
        f"{REQUEST_TIMEOUT_SECONDS:g}s"
    )
    console.print(
        f"[bold]Progress:[/bold] {total - len(pending)}/{total} "
        f"restored from checkpoint\n"
    )

    client = AsyncOpenAI(
        api_key=judge_config["api_key"],
        base_url=judge_config["base_url"],
    )
    semaphore = asyncio.Semaphore(config.max_concurrent_requests)
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Judge"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(
            "Judge",
            total=total,
            completed=total - len(pending),
        )
        tasks = [
            asyncio.create_task(
                judge_response(response, client, model, semaphore)
            )
            for response in pending
        ]
        for task in asyncio.as_completed(tasks):
            graded = await task
            completed[response_key(graded)] = graded
            save_checkpoint(checkpoint_path, signature, completed)
            progress.advance(task_id)

    all_grades = {
        group_id: [
            completed[response_key(response)]
            for response in responses
            if int(response.get("category", 0)) != 5
            and response.get("golden_answer") is not None
        ]
        for group_id, responses in locomo_responses.items()
    }
    atomic_write_json(judged_path, all_grades)
    summary = calculate_summary(all_grades)
    print_summary(summary)
    console.print(
        f"\n[bold]Saving detailed evaluation results to:[/bold] {judged_path}"
    )
    console.print(
        "[yellow]This is STS's internal LLM Judge metric, "
        "not LoCoMo official F1.[/yellow]"
    )
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())

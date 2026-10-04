import asyncio
import hashlib
import json
import sys
from pathlib import Path
from time import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
from openai import AsyncOpenAI
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TimeElapsedColumn, TimeRemainingColumn
)
from rich.console import Console

from sts.config import ExperimentConfig
from sts.retrieval.search import (
    atomic_write_json,
    build_query_checkpoint_key,
)
from sts.prompts.answer_prompts import ANSWER_PROMPT

console = Console()


def build_response_signature(
    search_path: Path,
    llm_config: dict,
) -> str:
    """Fingerprint the answer model and exact retrieval result input."""
    search_bytes = search_path.read_bytes()
    payload = {
        "version": 1,
        "model": llm_config["model"],
        "base_url": llm_config["base_url"],
        "answer_prompt_sha256": hashlib.sha256(
            ANSWER_PROMPT.encode("utf-8")
        ).hexdigest(),
        "search_path": str(search_path.resolve()),
        "search_sha256": hashlib.sha256(search_bytes).hexdigest(),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_response_checkpoint(path: Path, signature: str) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        console.print(f"[yellow][!] Ignoring unreadable checkpoint {path}: {error}[/yellow]")
        return {}
    if data.get("version") != 1 or data.get("signature") != signature:
        return {}
    results = data.get("results", {})
    if not isinstance(results, dict):
        return {}
    return {
        key: value
        for key, value in results.items()
        if (
            isinstance(key, str)
            and isinstance(value, dict)
            and isinstance(value.get("response"), dict)
            and isinstance(value.get("token_usage"), dict)
        )
    }


def save_response_checkpoint(path: Path, signature: str, results: dict) -> None:
    atomic_write_json(
        path,
        {
            "version": 1,
            "signature": signature,
            "results": results,
        },
    )


async def locomo_response(llm_client, llm_config, context: str, question: str, experiment_config: ExperimentConfig) -> str:
    prompt = ANSWER_PROMPT.format(
        context=context,
        question=question,
    )

    # Initialize result and token usage
    result = ""
    token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for i in range(experiment_config.llm_max_retries):
        try:
            response = await llm_client.chat.completions.create(
                model=llm_config["model"],
                messages=[
                    {"role": "system", "content": prompt},
                ],
                # temperature=llm_config["temperature"],
                temperature=0,
                # max_tokens=llm_config["max_tokens"],
                max_tokens=4096,
            )
            result = response.choices[0].message.content or ""
            # Record token usage
            if hasattr(response, 'usage') and response.usage:
                token_usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            parts = result.split("FINAL ANSWER:")
            if len(parts) > 1:
                result = parts[1].strip()
            else:
                print(
                    "Warning: 'FINAL ANSWER:' not found in response "
                    f"(attempt {i+1}/{experiment_config.llm_max_retries})"
                )
                print(f"Response preview: {result[:200]}...")
                continue
            if result == "":
                continue
            break
        except Exception as e:
            print(f"Error (attempt {i+1}/{experiment_config.llm_max_retries}): {e}")
            continue

    # If all retries fail, log a warning
    if result == "":
        print(f"ERROR: All {experiment_config.llm_max_retries} attempts failed. Returning empty string.")

    return result, token_usage


async def process_qa(qa, search_result, oai_client, llm_config, experiment_config):
    start = time()
    query = qa.get("question")
    gold_answer = qa.get("answer")
    qa_category = qa.get("category")

    answer, token_usage = await locomo_response(oai_client, llm_config, search_result.get("context"), query, experiment_config)

    response_duration_s = time() - start
    response_duration_ms = response_duration_s * 1000

    # Add duration to token_usage (in seconds)
    token_usage['duration'] = response_duration_s

    # Return response data and token_usage separately (token_usage is not saved to responses.json)
    response_data = {
        "question": query,
        "answer": answer,
        "category": qa_category,
        "golden_answer": gold_answer,
        "search_context": search_result.get("context", ""),
        "response_duration_ms": response_duration_ms,
        "search_duration_ms": search_result.get("duration_ms", 0),
    }
    return response_data, token_usage


async def main(search_path, save_path):
    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]Answer generation[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")

    search_path = Path(search_path)
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    llm_config = ExperimentConfig.llm_config["openai"]
    experiment_config = ExperimentConfig()
    response_signature = build_response_signature(
        search_path,
        llm_config,
    )
    checkpoint_dir = save_path.parent / "response_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    oai_client = AsyncOpenAI(
        api_key=llm_config["api_key"], base_url=llm_config["base_url"]
    )
    locomo_df = pd.read_json(experiment_config.dataset_path)
    with open(search_path, encoding='utf-8') as file:
        locomo_search_results = json.load(file)

    num_users = len(locomo_df)

    console.print(f"[bold]Number of conversations:[/bold] {num_users}")
    console.print("[bold]Answer prompt:[/bold] structured COT\n")

    all_responses = {}

    # Bound total QA requests across all conversations with one global limit.
    request_semaphore = asyncio.Semaphore(
        experiment_config.max_concurrent_requests
    )

    # First collect matched pairs for all conversations
    all_groups_data = []
    for group_idx in range(num_users):
        qa_set = locomo_df["qa"].iloc[group_idx]
        qa_set_filtered = [qa for qa in qa_set if qa.get("category") != 5]

        group_id = f"locomo_exp_user_{group_idx}"
        search_results = locomo_search_results.get(group_id)

        matched_pairs = []
        for qa in qa_set_filtered:
            question = qa.get("question")
            matching_result = next(
                (result for result in search_results if result.get("query") == question), None
            )
            if matching_result:
                matched_pairs.append((qa, matching_result))
            else:
                console.print(f"[yellow][!] Conversation {group_idx}: No matching search result found - {question[:50]}...[/yellow]")

        all_groups_data.append((group_idx, group_id, matched_pairs))

    async def process_group_with_semaphore(group_idx, group_id, matched_pairs, progress, task_id):
        """Conversation processing function with semaphore-based concurrency control"""
        progress.start_task(task_id)
        progress.update(task_id, status="Processing")
        checkpoint_path = checkpoint_dir / f"{group_id}.json"
        completed_results = load_response_checkpoint(
            checkpoint_path,
            response_signature,
        )
        if completed_results:
            console.print(
                f"[cyan][Checkpoint] {group_id}: resuming "
                f"{len(completed_results)} completed answers[/cyan]"
            )

        async def process_single_qa(qa, search_result):
            async with request_semaphore:
                response_data, token_usage = await process_qa(
                    qa,
                    search_result,
                    oai_client,
                    llm_config,
                    experiment_config,
                )
                return (
                    build_query_checkpoint_key(qa),
                    response_data,
                    token_usage,
                )

        pending_pairs = []
        for qa, search_result in matched_pairs:
            checkpoint_key = build_query_checkpoint_key(qa)
            if checkpoint_key in completed_results:
                progress.update(task_id, advance=1)
            else:
                pending_pairs.append((qa, search_result))

        tasks = [process_single_qa(qa, sr) for qa, sr in pending_pairs]
        for coro in asyncio.as_completed(tasks):
            checkpoint_key, response_data, token_usage = await coro
            completed_results[checkpoint_key] = {
                "response": response_data,
                "token_usage": token_usage,
            }
            save_response_checkpoint(
                checkpoint_path,
                response_signature,
                completed_results,
            )
            progress.update(task_id, advance=1)

        responses = []
        token_usages = []
        for qa, _ in matched_pairs:
            checkpoint_key = build_query_checkpoint_key(qa)
            completed = completed_results[checkpoint_key]
            response_data = dict(completed["response"])
            response_data["golden_answer"] = qa.get("answer")
            responses.append(response_data)
            token_usages.append(completed["token_usage"])

        progress.update(task_id, status="[green]Done[/green]")
        return (group_id, responses, token_usages)

    # Create progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.completed:>3}/{task.total:<3}"),  # Right-align completed count, left-align total
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("•"),
        TextColumn("[bold]{task.fields[status]}"),
        console=console,
        transient=False
    ) as progress:

        # Create progress tasks for each conversation
        coroutines = []
        for group_idx, group_id, matched_pairs in all_groups_data:
            task_id = progress.add_task(
                f"[cyan]Conv {group_idx}[/cyan]",
                total=len(matched_pairs),
                status="Waiting",
                start=False
            )
            coroutines.append(process_group_with_semaphore(group_idx, group_id, matched_pairs, progress, task_id))

        # Process all conversations in parallel
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # Collect results
        all_token_usages = {}  # group_id -> token_usages
        processing_errors = []
        for result in results:
            if isinstance(result, tuple) and len(result) == 3:
                group_id, responses, token_usages = result
                all_responses[group_id] = responses
                all_token_usages[group_id] = token_usages
            elif isinstance(result, Exception):
                console.print(f"[red][X] Processing exception: {result}[/red]")
                processing_errors.append(result)

    if processing_errors:
        raise RuntimeError(
            f"Answer generation failed for {len(processing_errors)} conversation(s); "
            "completed answer checkpoints were preserved"
        )

    console.print(f"\n[bold]Saving response results to:[/bold] {save_path}")
    atomic_write_json(save_path, all_responses)

    # Save token statistics to token_stats directory
    token_stats_dir = Path(save_path).parent / "token_stats"
    token_stats_dir.mkdir(parents=True, exist_ok=True)

    # Summarize token usage by conversation
    per_conv_token_stats = {}  # conv_id -> token_stats
    total_response_token_stats = {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
        'call_count': 0,
        'total_duration': 0.0
    }

    for group_id, token_usages in all_token_usages.items():
        # Extract conv_id from group_id, e.g., "locomo_exp_user_0" -> "0"
        conv_id = group_id.split("_")[-1]

        conv_token_stats = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
            'call_count': 0,
            'total_duration': 0.0
        }

        for token_usage in token_usages:
            prompt_tokens = token_usage.get('prompt_tokens', 0)
            completion_tokens = token_usage.get('completion_tokens', 0)
            duration = token_usage.get('duration', 0.0)

            conv_token_stats['prompt_tokens'] += prompt_tokens
            conv_token_stats['completion_tokens'] += completion_tokens
            conv_token_stats['total_tokens'] += prompt_tokens + completion_tokens
            conv_token_stats['call_count'] += 1
            conv_token_stats['total_duration'] += duration

            # Also accumulate to totals
            total_response_token_stats['prompt_tokens'] += prompt_tokens
            total_response_token_stats['completion_tokens'] += completion_tokens
            total_response_token_stats['total_tokens'] += prompt_tokens + completion_tokens
            total_response_token_stats['call_count'] += 1
            total_response_token_stats['total_duration'] += duration

        per_conv_token_stats[conv_id] = conv_token_stats

        # Update the token_stats_conv_*.json file for this conversation
        conv_stats_file = token_stats_dir / f"token_stats_conv_{conv_id}.json"
        if conv_stats_file.exists():
            try:
                with open(conv_stats_file, "r", encoding="utf-8") as f:
                    conv_stats_data = json.load(f)
            except Exception:
                conv_stats_data = {"conv_id": conv_id}
        else:
            conv_stats_data = {"conv_id": conv_id}

        # Add response_generation field
        conv_stats_data['response_generation'] = conv_token_stats

        # Calculate total after retrieval ends (including all stages)
        total_stats = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
            'call_count': 0,
            'total_duration': 0.0
        }

        # Accumulate token statistics from all stages
        for stage_key in ['scope_extraction', 'claim_extraction', 'response_generation']:
            stage_stats = conv_stats_data.get(stage_key)
            if stage_stats:
                total_stats['prompt_tokens'] += stage_stats.get('prompt_tokens', 0)
                total_stats['completion_tokens'] += stage_stats.get('completion_tokens', 0)
                total_stats['total_tokens'] += stage_stats.get('total_tokens', 0)
                total_stats['call_count'] += stage_stats.get('call_count', 0)
                total_stats['total_duration'] += stage_stats.get('total_duration', 0.0)

        conv_stats_data['total'] = total_stats

        atomic_write_json(conv_stats_file, conv_stats_data)

    # Print token statistics
    console.print("\n[bold yellow]Token Usage:[/bold yellow]")
    console.print(f"  prompt={total_response_token_stats['prompt_tokens']:,}, "
                  f"completion={total_response_token_stats['completion_tokens']:,}, "
                  f"total={total_response_token_stats['total_tokens']:,}, "
                  f"calls={total_response_token_stats['call_count']}")

    # Update summary.json
    summary_file = token_stats_dir / "summary.json"
    if summary_file.exists():
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
        except Exception:
            summary_data = {}
    else:
        summary_data = {}

    # Add response_generation to token_usage
    if 'token_usage' not in summary_data:
        summary_data['token_usage'] = {}

    summary_data['token_usage']['response_generation'] = total_response_token_stats

    # Calculate summary total after retrieval ends (including all stages)
    summary_total = {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
        'call_count': 0,
        'total_duration': 0.0
    }

    # Accumulate token statistics from all stages
    for stage_key in ['scope_extraction', 'claim_extraction', 'response_generation']:
        stage_stats = summary_data['token_usage'].get(stage_key)
        if stage_stats:
            summary_total['prompt_tokens'] += stage_stats.get('prompt_tokens', 0)
            summary_total['completion_tokens'] += stage_stats.get('completion_tokens', 0)
            summary_total['total_tokens'] += stage_stats.get('total_tokens', 0)
            summary_total['call_count'] += stage_stats.get('call_count', 0)
            summary_total['total_duration'] += stage_stats.get('total_duration', 0.0)

    summary_data['token_usage']['total'] = summary_total

    atomic_write_json(summary_file, summary_data)

    console.print(f"[dim]Token statistics updated to: {token_stats_dir}[/dim]")

    console.print("[bold green][SUCCESS] Response generation completed![/bold green]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")


if __name__ == "__main__":
    config = ExperimentConfig()
    search_result_path = str(config.experiment_dir() / "search_results.json")
    save_path = config.experiment_dir() / "responses.json"

    asyncio.run(main(search_result_path, save_path))

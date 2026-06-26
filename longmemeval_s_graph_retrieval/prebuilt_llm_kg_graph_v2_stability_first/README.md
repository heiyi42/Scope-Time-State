# Prebuilt LLM KG Graph V2: Stability First

## Purpose

This iteration keeps the existing high-quality LLM graph construction path, but
adds a stability layer around it.

It does **not** optimize speed and does **not** intentionally reduce prompt
context. The goal is to prevent a long graph-building run from becoming silent
or losing progress when one case fails or appears stuck.

```text
Candidate session retrieval
  -> existing LLM graph builder
  -> graph artifact per question_id
  -> graph retriever emits State_packet
  -> answer model
```

The main project pipeline is not modified.

## What Changed

Compared with `prebuilt_llm_kg_graph`, this version adds:

- `build_all.py`: a scheduler for multiple LongMemEval-S cases.
- `build_one_case.py`: an isolated worker for one case.
- `stable_client.py`: method-local OpenAI-compatible JSON client with retries,
  cache, request timeout, and `reasoning_content` fallback.
- `status_utils.py`: atomic status JSON writes and timestamp helpers.
- heartbeat output every configurable interval, default 120 seconds.
- per-case status files.
- per-case logs.
- per-case LLM cache.
- per-case input and build summaries.
- failed-case error snapshots.

It does not add automatic process killing.

If a case has not updated its status for longer than
`--stuck-timeout-seconds`, the scheduler marks it as `possible_stuck` in the
heartbeat output, but leaves the worker process alive.

## What Did Not Change

To preserve graph quality, this version does not change:

- the graph schema;
- the final graph artifact format;
- the `State_packet` retrieval contract;
- the existing `TaskSemanticsLocalGraphBuilder` graph-building logic;
- the existing LLM extraction prompts;
- the candidate session retrieval boundary;
- the answer-time graph retrieval pipeline.

This means the method is still expected to be slow. Stability and visibility are
the priority.

## Output Layout

Default artifact root:

```text
longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/
```

Important subdirectories:

```text
artifacts/graphs/
  knowledge-update/
    <question_id>.graph.json
  multi-session/
    <question_id>.graph.json
  single-session-assistant/
    <question_id>.graph.json
  single-session-preference/
    <question_id>.graph.json
  single-session-user/
    <question_id>.graph.json
  temporal-reasoning/
    <question_id>.graph.json

artifacts/status/
  <question_id>.status.json

artifacts/intermediate/<question_id>/
  case_input.json
  build_summary.json

artifacts/cache/
  <question_id>.llm_cache.json

artifacts/logs/
  <question_id>.log

artifacts/errors/
  <question_id>.error.json
```

One case produces one graph JSON.

For the 60-case sample:

```text
6 question types * 10 cases = 60 graph JSON files under 6 question-type folders
```

This repository snapshot already contains the 60 prebuilt graph artifacts under
`artifacts/graphs/`.

## Benchmark Results (60-case sample)

Construction: deepseek-v4-pro | Reader: gpt-4o-mini | Judge: gpt-4o

| Question Type | Graph ans_j | BM25-only ans_j | Δ |
|---|---|---|---|
| knowledge-update | **1.000** | 0.500 | +0.500 |
| multi-session | **0.700** | 0.400 | +0.300 |
| single-session-assistant | **1.000** | 0.900 | +0.100 |
| single-session-preference | **0.600** | 0.200 | +0.400 |
| single-session-user | **0.800** | 0.800 | 0 |
| temporal-reasoning | **0.900** | 0.500 | +0.400 |
| **Total** | **0.833** | **0.550** | **+0.283** |

BM25 baseline from `stamb_state_benchmark/output/results_4omini_60_judged_gpt4o.json` (same reader and judge models).

## Recommended Run Order

Start with a smoke test:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.build_all \
  --limit-per-type 1 \
  --dry-run
```

Then build one case per type with real API calls:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.build_all \
  --limit-per-type 1 \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash \
  --max-global-workers 1 \
  --heartbeat-seconds 120
```

Then build one complete question type:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.build_all \
  --question-types single-session-user \
  --limit-per-type 10 \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash \
  --max-global-workers 1 \
  --heartbeat-seconds 120
```

Finally build the full 60-case sample:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.build_all \
  --limit-per-type 10 \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash \
  --max-global-workers 1 \
  --heartbeat-seconds 120
```

Use a larger worker count only after the single-worker run is stable:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.build_all \
  --limit-per-type 10 \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash \
  --max-global-workers 2 \
  --parallel-per-type 2 \
  --heartbeat-seconds 120
```

## Heartbeat

The scheduler prints progress every `--heartbeat-seconds`.

Example:

```text
[Heartbeat] 2026-06-26T12:00:00+00:00
method: prebuilt_llm_kg_graph_v2_stability_first
total selected: 60
completed this run: 12
failed this run: 1
skipped existing: 3
running: 1
pending not launched: 44
running cases:
- temporal-reasoning / case_007 / stage=llm_request / elapsed=244s / last_update=31s
possible_stuck (not killed):
- single-session-preference / case_006 / stage=llm_request / last_update=731s ago
```

`possible_stuck` is only a warning. The scheduler does not terminate that
process.

## Resume Behavior

If a graph already exists, it is skipped unless `--overwrite` is set.

Per-case LLM cache is stored under:

```text
artifacts/cache/<question_id>.llm_cache.json
```

If a run is interrupted, rerun the same command without `--overwrite`. Completed
graphs are skipped, and cached LLM calls can be reused.

## Single-Case Worker

You can build one specific case directly:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.build_one_case \
  --question-id <question_id> \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash
```

This is useful for retrying a failed or suspicious case.

## Use Graphs For Retrieval

The v2 runner supports both flat graph directories and the question-type folder
layout used here.

Dry-run:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.run_longmemeval \
  --limit-per-type 1 \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs \
  --dry-run
```

Run benchmark using the prebuilt graphs:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.run_longmemeval \
  --limit-per-type 10 \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --judge \
  --judge-provider openai \
  --judge-model gpt-4o-2024-08-06 \
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/outputs/results_60_stability_first.json
```

## Stability Guarantees And Limits

This version improves stability by:

- keeping the scheduler non-blocking;
- isolating each case in a worker process;
- writing status files continuously;
- writing logs per case;
- retrying LLM calls;
- caching successful LLM JSON calls;
- saving completed graph artifacts per case;
- skipping already completed graphs on rerun.

Because automatic killing is disabled, the scheduler cannot force a permanently
hung worker to finish. It can only keep reporting the problem and preserve all
completed artifacts so the run can be resumed manually.

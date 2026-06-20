# LongMemEval-S External Benchmark

This directory keeps the LongMemEval-S adapter separate from the STAMB-State
benchmark contract.

## Data

Download the cleaned LongMemEval-S file from the official release:

```bash
mkdir -p Experiment/Other_BenchMark/LongMemEval-S/data
curl -L --fail --show-error \
  --output Experiment/Other_BenchMark/LongMemEval-S/data/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
```

The data file is intentionally ignored by git.

## Smoke Run

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py \
  --provider deepseek \
  --variants bm25_session oracle_sessions scope_time_state_public \
  --limit-cases 5 \
  --top-k 8
```

`oracle_sessions` uses gold evidence session IDs and is only a sanity upper bound.
Use `bm25_session` or other non-oracle variants for fair comparisons.

For a quick smoke that covers every LongMemEval-S question type once:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py \
  --provider deepseek \
  --variants bm25_session oracle_sessions scope_time_state_public \
  --limit-per-type 1 \
  --top-k 8 \
  --output stamb_state_benchmark/output/results_longmemeval_s_balanced_smoke.json \
  --cache stamb_state_benchmark/output/llm_cache.longmemeval_s_balanced_smoke.json
```

## Variants

- `bm25_session`: retrieves top-k sessions with lexical BM25 and asks the reader to answer.
- `recent_sessions`: passes the latest top-k sessions.
- `full_history`: passes the history subject to context truncation.
- `oracle_sessions`: passes gold evidence sessions; use only for sanity checks.
- `scope_time_state_public`: public/free-facet adaptation of the Scope-Time-State pipeline. It
  retrieves BM25 candidate sessions, asks the reader to build state facets, reject stale claims, cite
  evidence session IDs, and answer. It does not consume `answer_session_ids` except for evaluation.
- `scope_time_state_task_adapter`: two-stage task-adapted Scope-Time-State variant. It retrieves
  BM25 candidate sessions, extracts compact task-specific evidence snippets, then answers from that
  evidence JSON. It uses question-focused windows for long sessions so relevant turns in the middle
  of a session are not lost to prefix truncation. It uses the six task adapters for evidence and
  answer instructions.

## Task Adapters

`run_longmemeval_s.py` is a thin CLI wrapper. The executable pipeline and task adapters live under
`pipeline/external/longmemeval_s/`:

- `pipeline/external/longmemeval_s/runner.py`
- `pipeline/external/longmemeval_s/adapters/single_session_user/`
- `pipeline/external/longmemeval_s/adapters/single_session_assistant/`
- `pipeline/external/longmemeval_s/adapters/single_session_preference/`
- `pipeline/external/longmemeval_s/adapters/multi_session/`
- `pipeline/external/longmemeval_s/adapters/temporal_reasoning/`
- `pipeline/external/longmemeval_s/adapters/knowledge_update/`

Each adapter owns the task-specific instruction for its LongMemEval-S question type. Abstention
is handled as a cross-cutting `_abs` question-id suffix, not as a separate LongMemEval-S
`question_type`.

List configured adapters:

```bash
python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py --list-tasks
```

The runner reports candidate-session recall/precision, cited evidence-session recall/precision,
and a rough local answer match. The local answer match is only a smoke signal.

## Official-Style Judge

Use `--judge` for paper-facing answer accuracy. The runner uses the LongMemEval
task-specific yes/no judge prompts and defaults to `gpt-4o-2024-08-06` for
`--judge-provider openai`, matching the official LongMemEval evaluator.

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py \
  --provider deepseek \
  --variants scope_time_state_public scope_time_state_task_adapter \
  --limit-per-type 3 \
  --top-k 8 \
  --task-candidate-k 20 \
  --judge \
  --judge-provider openai \
  --output stamb_state_benchmark/output/results_longmemeval_s_adapter_compare_3.json \
  --cache stamb_state_benchmark/output/llm_cache.longmemeval_s_adapter_compare_3.json \
  --judge-cache stamb_state_benchmark/output/llm_cache.longmemeval_s_adapter_compare_3.openai_judge.json
```

For each variant, the runner writes:

- `*.hypotheses.jsonl`: `question_id` and `hypothesis`, suitable for the official
  `evaluate_qa.py` script.
- `*.judged.jsonl`: `question_id`, `hypothesis`, and `autoeval_label`, suitable
  for the official `print_qa_metrics.py` script when the judge model is
  `gpt-4o-2024-08-06`.

For a larger non-full stability check, run ten cases from each LongMemEval-S task:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=4 \
  python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py \
  --provider deepseek \
  --variants scope_time_state_task_adapter \
  --limit-per-type 10 \
  --top-k 8 \
  --task-candidate-k 20 \
  --judge \
  --judge-provider openai \
  --output stamb_state_benchmark/output/results_longmemeval_s_task_adapter_10_per_type_v2.json \
  --cache stamb_state_benchmark/output/llm_cache.longmemeval_s_task_adapter_10_per_type_v2.json \
  --judge-cache stamb_state_benchmark/output/llm_cache.longmemeval_s_task_adapter_10_per_type_v2.gpt4o_judge.json
```

## Full Run

A full 500-case run is expensive. Use a non-oracle variant for the main table:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py \
  --provider deepseek \
  --variants bm25_session scope_time_state_task_adapter \
  --top-k 8 \
  --task-candidate-k 20 \
  --judge \
  --judge-provider openai \
  --output stamb_state_benchmark/output/results_longmemeval_s_full.json \
  --cache stamb_state_benchmark/output/llm_cache.longmemeval_s_full.json \
  --judge-cache stamb_state_benchmark/output/llm_cache.longmemeval_s_full.openai_judge.json
```

The runner also writes per-variant `*.hypotheses.jsonl` files with `question_id` and
`hypothesis`, plus `*.judged.jsonl` files when `--judge` is enabled.

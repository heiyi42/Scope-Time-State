# LoCoMo QA External Benchmark

This directory keeps the LoCoMo QA adapter separate from the STAMB-State benchmark contract.
It is text-only: raw dialog text plus released image captions/search queries are allowed, but
multimodal generation is not run here.

## Data

Official release:

- Project page: https://snap-research.github.io/locomo/
- Repository: https://github.com/snap-research/LoCoMo
- Data file: `data/locomo10.json`

Download:

```bash
mkdir -p Experiment/Other_BenchMark/LoCoMo-QA/data
curl -L --fail --show-error \
  --output Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  https://raw.githubusercontent.com/snap-research/LoCoMo/main/data/locomo10.json
```

The data file is intentionally ignored by git.

## Task Adapters

`run_locomo_qa.py` is the single entrypoint, but it is only a thin wrapper. The real implementation
lives under `pipeline/external/locomo_qa/`, matching the LongMemEval-S external benchmark layout.

Official LoCoMo category mapping:

- `4`: `single-hop`
- `1`: `multi-hop`
- `2`: `temporal`
- `3`: `open-domain`
- `5`: `adversarial`

Configured adapter directories:

- `pipeline/external/locomo_qa/adapters/single_hop/`
- `pipeline/external/locomo_qa/adapters/multi_hop/`
- `pipeline/external/locomo_qa/adapters/temporal/`
- `pipeline/external/locomo_qa/adapters/open_domain/`
- `pipeline/external/locomo_qa/adapters/adversarial/`

List configured adapters:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_qa.py --list-tasks
```

## Variants

- `bm25_dialog`: retrieves top-k dialog turns with lexical BM25 and asks the reader to answer.
- `recent_dialog`: passes the latest top-k dialog turns.
- `full_history`: passes all dialog turns subject to context truncation.
- `oracle_dialog`: passes gold evidence dialog IDs; use only as a sanity upper bound.
- `scope_time_state_task_adapter`: two-stage task-adapted Scope-Time-State variant. It retrieves
  candidate dialog turns with a LoCoMo memory index over raw dialogs, public observations, and public
  session summaries, expands local dialog windows, passes the released public observation/session-summary
  memory records into task-specific evidence extraction, then answers from that evidence JSON. The
  formal path does not apply benchmark-specific answer rewrites after the model response. Use
  `--memory-router`, `--answer-contract`, `--answer-with-context`, or `--answer-verifier` only as explicit
  ablations over the same public candidates. `--answer-contract` creates a question-only subject/relation/
  answer-type contract and passes it to routing, evidence extraction, and answer composition; it does not
  read gold answers.

The runner reports public LoCoMo-style lexical answer F1, plus dialog-level evidence recall and
precision. Category `5` is adversarial/unanswerable-style and is scored as correct when the model
answers with `No information available` or `Not mentioned`.

By default, the context uses raw dialog text plus released image captions/search queries. Public
session summaries can be included with `--include-session-summary`, but that should be treated as
an explicit ablation.

## Smoke Run

Run the four QA types selected for the first pass:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 OPENAI_MODEL=gpt-4o-mini \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_qa.py \
  --provider openai \
  --variants bm25_dialog scope_time_state_task_adapter \
  --question-types single-hop multi-hop temporal adversarial \
  --limit-per-type 1 \
  --selection-strategy round_robin \
  --top-k 8 \
  --task-candidate-k 80 \
  --memory-top-n 48 \
  --context-window-turns 3 \
  --memory-context-window-turns 0 \
  --output stamb_state_benchmark/output/results_locomo_qa_smoke_4types.json \
  --cache stamb_state_benchmark/output/llm_cache.locomo_qa_smoke_4types.json
```

Use `--question-types single-hop multi-hop temporal open-domain adversarial` to include the full
official QA category set. `commonsense` remains accepted as a backward-compatible alias.

For a cross-conversation 10-case-per-task check:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 OPENAI_MODEL=gpt-4o-mini \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_qa.py \
  --provider openai \
  --variants scope_time_state_task_adapter \
  --question-types single-hop multi-hop temporal open-domain adversarial \
  --limit-per-type 10 \
  --selection-strategy round_robin \
  --top-k 8 \
  --task-candidate-k 80 \
  --memory-top-n 48 \
  --context-window-turns 3 \
  --memory-context-window-turns 0 \
  --memory-router \
  --router-raw-candidate-k 24 \
  --router-dialog-window-turns 1 \
  --output stamb_state_benchmark/output/results_locomo_qa_10_per_type_gpt4omini_memory_router_raw.json \
  --cache stamb_state_benchmark/output/llm_cache.locomo_qa_10_per_type_gpt4omini_memory_router_raw.json
```

For a focused target check on the three currently inspected task types:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 OPENAI_MODEL=gpt-4o-mini \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_qa.py \
  --provider openai \
  --variants scope_time_state_task_adapter \
  --question-types temporal open-domain multi-hop \
  --limit-per-type 10 \
  --selection-strategy round_robin \
  --top-k 8 \
  --task-candidate-k 80 \
  --memory-top-n 48 \
  --context-window-turns 3 \
  --memory-context-window-turns 0 \
  --memory-router \
  --router-raw-candidate-k 24 \
  --router-dialog-window-turns 1 \
  --output stamb_state_benchmark/output/results_locomo_qa_10_target_gpt4omini_memory_router_raw.json \
  --cache stamb_state_benchmark/output/llm_cache.locomo_qa_10_target_gpt4omini_memory_router_raw.json
```

For the answer-contract ablation on the current open-domain/multi-hop failure modes:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 OPENAI_MODEL=gpt-4o-mini \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_qa.py \
  --provider openai \
  --variants scope_time_state_task_adapter \
  --question-types open-domain multi-hop \
  --limit-per-type 10 \
  --selection-strategy round_robin \
  --top-k 8 \
  --task-candidate-k 80 \
  --memory-top-n 48 \
  --context-window-turns 3 \
  --memory-context-window-turns 0 \
  --memory-router \
  --answer-contract \
  --router-raw-candidate-k 24 \
  --router-dialog-window-turns 1 \
  --output stamb_state_benchmark/output/results_locomo_qa_10_open_multi_gpt4omini_answer_contract_v2_prompt_only.json \
  --cache stamb_state_benchmark/output/llm_cache.locomo_qa_10_open_multi_gpt4omini_answer_contract_v2_prompt_only.json
```

## Full Run

A full run over all QA items is larger than the smoke check. Use non-oracle variants for main
comparisons:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 OPENAI_MODEL=gpt-4o-mini \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_qa.py \
  --provider openai \
  --variants bm25_dialog scope_time_state_task_adapter \
  --question-types single-hop multi-hop temporal open-domain adversarial \
  --selection-strategy round_robin \
  --top-k 8 \
  --task-candidate-k 80 \
  --memory-top-n 48 \
  --context-window-turns 3 \
  --memory-context-window-turns 0 \
  --output stamb_state_benchmark/output/results_locomo_qa_full.json \
  --cache stamb_state_benchmark/output/llm_cache.locomo_qa_full.json
```

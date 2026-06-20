# STALE

Official benchmark adapter for STALE: State Tracking And Latent Evaluation.

Official sources:

- Code: https://github.com/icedreamc/STALE
- Dataset: https://huggingface.co/datasets/STALEproj/STALE
- Paper: arXiv:2605.06527

The downloaded official data file is ignored by git:

```bash
Experiment/Other_BenchMark/STALE/data/T1_T2_400_FULL.json
```

The runnable logic lives under `pipeline/external/stale/`; this directory keeps the benchmark entrypoint and local data.

```bash
python Experiment/Other_BenchMark/STALE/run_stale.py --list-tasks
python Experiment/Other_BenchMark/STALE/run_stale.py --dry-run --limit-cases 1
PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=2 LLM_REQUEST_TIMEOUT=90 \
  python Experiment/Other_BenchMark/STALE/run_stale.py \
  --provider openai \
  --variants scope_time_state_task_adapter \
  --limit-cases 1 \
  --judge \
  --judge-provider openai \
  --output stamb_state_benchmark/output/results_stale_scope_time_state_1_openai_judged.json \
  --cache stamb_state_benchmark/output/llm_cache.stale_scope_time_state_1_openai.json
```

By default, `scope_time_state_task_adapter` keeps all 50 official STALE sessions per
scenario (`--task-candidate-k 50`) and uses context/session budgets large enough for
the downloaded official file. For a cheaper retrieval smoke, pass smaller explicit
budgets such as `--task-candidate-k 32 --max-context-chars 140000 --task-max-session-chars 3500`;
that is not the faithful default.

The three official probing dimensions are exposed as task adapters:

- `state_resolution`: Dimension 1, explicit stale-state validation.
- `premise_resistance`: Dimension 2, false-premise robustness.
- `implicit_policy_adaptation`: Dimension 3, downstream behavior under the updated state.

For `scope_time_state_task_adapter`, the evidence stage also receives a heuristic
conflict scan derived only from the query and conversation history. It lists possible
old-premise sessions and later parent-state update candidates so T2 propagated
conflicts are easier to inspect; it does not use `M_old`, `M_new`, `explanation`, or
judge labels.

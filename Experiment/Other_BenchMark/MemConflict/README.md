# MemConflict Adapter

This directory contains the thin CLI entrypoint for the MemConflict external benchmark.
The implementation lives in `pipeline/external/memconflict/`.

Official source:

- Paper: https://arxiv.org/abs/2605.20926
- Code/data: https://github.com/TaoZhen1110/MemConflict
- Final released sample benchmark file: `Data/Step4_4.jsonl`

Download the released data:

```bash
mkdir -p Experiment/Other_BenchMark/MemConflict/data
curl -L --fail --max-time 60 \
  https://raw.githubusercontent.com/TaoZhen1110/MemConflict/main/Data/Step4_4.jsonl \
  -o Experiment/Other_BenchMark/MemConflict/data/Step4_4.jsonl
```

Validate the adapter without LLM calls:

```bash
python Experiment/Other_BenchMark/MemConflict/run_memconflict.py \
  --dry-run \
  --limit-per-type 2
```

Run a small balanced smoke sample:

```bash
PYTHONDONTWRITEBYTECODE=1 python Experiment/Other_BenchMark/MemConflict/run_memconflict.py \
  --provider deepseek \
  --variants scope_time_state_task_adapter \
  --limit-per-type 2 \
  --top-k 3 \
  --task-candidate-k 18 \
  --output stamb_state_benchmark/output/results_memconflict_smoke.json \
  --cache stamb_state_benchmark/output/llm_cache.memconflict_smoke.json
```

Use `--judge` for LLM-assisted MemConflict-style scoring. Without `--judge`, the
runner reports local smoke metrics for quick adapter validation.


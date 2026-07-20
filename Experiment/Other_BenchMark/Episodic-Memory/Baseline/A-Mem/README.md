# EPBench A-Mem Baseline

This adapter uses the official `agiresearch/A-mem` `AgenticMemorySystem` exactly
as the local LoCoMo baseline does: canonical-book paragraphs are supplied through
`add_note`, and each question retrieves evidence through `search_agentic` before
`gpt-4o-mini` answers from that evidence.

It never adds QA fields or gold answers to A-Mem. Gold fields are only copied to
the prediction record after generation so the official EPBench evaluator can score it.

Run from `Experiment/Other_BenchMark/Episodic-Memory`:

```bash
conda run -n py311 python -u Baseline/A-Mem/run.py \
  --ingest-limit 1 --limit 1 --reset \
  --out-dir artifacts/baselines/a_mem_smoke
```

The default official runtime is at `Graph/service_repos/epbench/A-mem`. Override
it with `--amem-repo-dir` if needed. Use `--limit -1 --ingest-limit -1` for the
full 1084-paragraph / 686-question run.

# EPBench Full-Context Baseline

`run.py` implements the paper-style full-context prompting baseline:

1. Load the canonical EPBench book and QA file.
2. Put the full book into the model context.
3. Ask each EPBench question with the paper-style prompt.
4. Answer with `gpt-4o-mini`.

The answer stage does not use gold answers or judge output. Gold fields are
kept only in the prediction JSONL so the post-hoc judge can score the answers.

Important: `--max-memory-chars -1` keeps the full book and disables truncation.

Default output:

```text
artifacts\baselines\full_context_llm\events200_gpt-4o-mini_paper_prompt_full_memory
```

Run from the `Episodic-Memory` project root:

```powershell
$fcOut = ".\artifacts\baselines\full_context_llm\events200_gpt-4o-mini_paper_prompt_full_memory"

& "C:\Anaconda\envs\py311\python.exe" -u ".\Baseline\full-context\run.py" `
  --limit -1 `
  --reset `
  --out-dir $fcOut `
  --max-memory-chars -1
```

Then score with:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u ".\Baseline\official_epbench_llm_judge_eval_strict.py" `
  --predictions_path "$fcOut\full_context_predictions.jsonl" `
  --out_dir "$fcOut\llm_judge_eval_strict" `
  --judge_model "gpt-4o-mini" `
  --resume
```

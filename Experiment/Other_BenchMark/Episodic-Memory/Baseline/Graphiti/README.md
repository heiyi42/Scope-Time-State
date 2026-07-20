# EPBench Graphiti Baseline

This is an EPBench-only data adapter for the open-source `graphiti-core`
package. It follows the same boundary as the other EPBench memory baselines:

- no gold answers, judge fields, QA labels, or evidence labels are indexed;
- no question-specific or answer-specific hard rules are used;
- the canonical EPBench book is the only memory corpus;
- `gpt-4o-mini` is the default answer model;
- `text-embedding-3-small` is the default embedding model.

The script writes predictions compatible with:

```powershell
.\Baseline\official_epbench_llm_judge_eval_strict.py
```

## Dependencies

Graphiti requires `graphiti-core` and a running Neo4j instance. If either is
missing, the script stops with an explicit error.

## Answer

Run from `Experiment\Other_BenchMark\Episodic-Memory`:

```powershell
$env:OPENAI_API_KEY = "your_key"
$env:OPENAI_BASE_URL = "https://api.gptsapi.net/v1"
$env:OPENAI_MODEL = "gpt-4o-mini"
$env:OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

$out = ".\artifacts\baselines\graphiti_gpt4omini_epbench"

& "C:\Anaconda\envs\py311\python.exe" -u ".\Baseline\graphiti\run.py" `
  --limit 20 `
  --reset `
  --out-dir $out
```

Use `--limit -1` for the full 686-question run after a smoke test looks sane.

For an end-to-end smoke test that ingests only one source episode and answers
one question, add `--ingest-limit 1 --limit 1`. Graphiti 0.29 treats its
`group_id` as the Neo4j database name, so isolation requires a dedicated
`--neo4j-database` rather than an arbitrary experiment group name.

The runner automatically loads the project-root `.env`, accepts either
`NEO4J_USERNAME` or `NEO4J_USER`, uses `NEO4J_DATABASE`, and reads
`OPENAI_EMBEDDING_BASE_URL` separately from the chat endpoint. It uses the
checked-in EPBench data under `Episodic-Memory/data` by default.

## Judge

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u ".\Baseline\official_epbench_llm_judge_eval_strict.py" `
  --predictions_path "$out\graphiti_predictions.jsonl" `
  --out_dir "$out\llm_judge_eval_strict" `
  --judge_model "gpt-4o-mini" `
  --resume
```

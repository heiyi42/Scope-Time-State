# V6 Build-Only Question-Independent Graphs

This version builds LongMemEval-S memory graphs without conditioning on the benchmark question. It keeps the v2 Scope-Time-State node and edge schema, but changes the construction pipeline to be checkpointed and resumable.

## What V6 Does

- Uses every haystack session for the selected case.
- Never passes `question`, `question_type`, `question_date`, answer, or gold evidence into graph extraction.
- Saves every LLM batch extraction under `artifacts/batches/<type>/<question_id>/`.
- Writes a partial graph under `artifacts/partial_graphs/<type>/` after each batch by default.
- Writes the final graph under `artifacts/graphs/<type>/` only after all batches are assembled.
- Does not implement retrieval or benchmark answering.

## Key Commands

Dry-run one case:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v6_build_only.build_one_case --question-id 6a1eabeb --dry-run
```

Build one case:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v6_build_only.build_one_case --question-id 6a1eabeb --construction-provider deepseek --construction-model deepseek-v4-flash
```

Build a small batch, one worker by default:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v6_build_only.build_all --question-types knowledge-update --limit-per-type 1
```

Resume is enabled by default. Use `--no-resume` to ignore existing batch checkpoints. Use `--run-state-reconcile` only when the claim graph is already stable; it adds an extra LLM state-facet pass.

## Artifact Layout

- `artifacts/batches/`: per-batch LLM claim checkpoints.
- `artifacts/partial_graphs/`: overwritten partial graph artifacts for inspection during long runs.
- `artifacts/graphs/`: completed final graph artifacts.
- `artifacts/status/`: live progress, including batch counts.
- `artifacts/errors/`: traceback and API failure records.
- `artifacts/intermediate/`: case inputs and build summaries.

## Differences From V5

V5 wrote no graph until all LLM calls and final assembly finished. V6 writes durable batch checkpoints and partial graphs during construction, so API failures do not discard completed work.


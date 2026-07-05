# V9 Scope-Time-State Graph Retrieval

LongMemEval-S graph retrieval variant with question-independent graph construction and LLM semantic scope selection.

## Pipeline

1. Build one question-independent graph per case from all haystack sessions.
2. At benchmark time, present scope node profiles to an LLM selector.
3. Expand selected scope nodes through the same scope-first event, claim, and session retrieval flow.
4. Compose the final answer with the shared LongMemEval-S task adapter prompts.

## Build Graphs

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v9.build_all ^
  --limit-per-type 10 ^
  --question-types knowledge-update ^
  --construction-provider deepseek ^
  --construction-model deepseek-v4-flash ^
  --max-global-workers 10 ^
  --parallel-per-type 10
```

Dry-run only validates selected rows and writes `artifacts/build_manifest.dry_run.json`; it does not launch workers or mark graphs as completed.

## Run Benchmark

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v9.run_longmemeval ^
  --limit-per-type 10 ^
  --question-types knowledge-update ^
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v9/artifacts/graphs ^
  --scope-provider openai --scope-model gpt-4o-mini ^
  --answer-provider openai --answer-model gpt-4o-mini ^
  --judge --judge-provider openai --judge-model gpt-4o ^
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v9/outputs/results_v9.json
```

## Scope Selector Defaults

These defaults are carried over from the tuned v8 scope search setup and should not be changed unless explicitly running a new ablation:

- `--scope-profile-events 3`
- `--scope-profile-claims 5`
- `--scope-profile-entities 5`
- `--scope-profile-facets 3`
- `--scope-profile-event-tokens 30`
- `--scope-profile-claim-tokens 40`
- `--scope-profile-facet-tokens 20`

The selector receives the question, question type, and a list of scope candidates with nearby events, claims, state facets, and entities. It returns JSON:

```json
{
  "selected_scopes": [
    {"node_id": "scope node id", "score": 0.0, "reason": "short semantic reason"}
  ]
}
```

The downstream packet uses `retrieval_strategy: "v9_llm_scope_first_expand"`.

## Files

| File | Purpose |
|---|---|
| `build_all.py` | Multi-worker graph prebuild scheduler |
| `build_one_case.py` | Single-case graph builder |
| `checkpoint_builder.py` | Checkpointed question-independent graph builder |
| `llm_extractor.py` | Question-independent graph extractor prompt |
| `stable_client.py` | Requests-based JSON LLM client for construction |
| `status_utils.py` | Atomic JSON writes and status tracking |
| `scope_retriever.py` | Scope-first expansion retriever |
| `llm_scope_retriever.py` | LLM semantic scope selector |
| `run_longmemeval.py` | Benchmark runner |

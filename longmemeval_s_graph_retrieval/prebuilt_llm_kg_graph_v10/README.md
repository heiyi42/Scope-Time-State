# V10 BM25 Scope Selection

LongMemEval-S graph retrieval variant with question-independent graph construction and zero-cost BM25 scope selection.

## Pipeline

1. Build one graph per case from all haystack sessions.
2. Build a compact text profile for each scope node.
3. Use BM25 to select the most relevant scope nodes.
4. Run the unchanged scope-first expansion flow: scopes -> events -> claims -> sessions.
5. Compose the final answer with the shared LongMemEval-S task adapter prompts.

## BM25 E4 Parameters

These are the fixed tuned defaults for V10:

- `scope_profile_events = 5`
- `scope_profile_claims = 10`
- `scope_label_weight = 3`
- `entity_label_weight = 2`
- `scope_profile_event_tokens = 80`
- `scope_profile_claim_tokens = 60`
- BM25 scoring uses `k1 = 1.5` and `b = 0.75`

The intent is to keep scope profiles small enough that broad generic scopes do not dominate smaller but more specific scopes.

## Build Graphs

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v10.build_all `
  --limit-per-type 10 `
  --question-types knowledge-update `
  --construction-provider deepseek `
  --construction-model deepseek-v4-flash `
  --max-global-workers 10 `
  --parallel-per-type 10
```

Dry-run validates the selected rows and writes `artifacts/build_manifest.dry_run.json`; it does not launch workers or write graph artifacts.

## Run Benchmark

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v10.run_longmemeval `
  --limit-per-type 10 `
  --question-types knowledge-update multi-session single-session-preference temporal-reasoning `
  --answer-provider openai --answer-model gpt-4o-mini `
  --judge --judge-provider openai --judge-model gpt-4o `
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v10/outputs/results_v10.json
```

The state packet uses:

```json
{
  "retrieval_strategy": "v10_bm25_scope_first_expand",
  "scope_ranker": "bm25_scope_profile"
}
```

## Files

| File | Purpose |
|---|---|
| `build_all.py` | Multi-worker graph prebuild scheduler |
| `build_one_case.py` | Single-case graph builder |
| `checkpoint_builder.py` | Checkpointed question-independent graph builder |
| `llm_extractor.py` | Question-independent graph extractor prompt |
| `stable_client.py` | Requests-based JSON LLM client for graph construction |
| `status_utils.py` | Atomic JSON writes and status tracking |
| `scope_retriever.py` | Scope-first expansion retriever |
| `bm25_scope_retriever.py` | BM25 scope selector |
| `run_longmemeval.py` | Benchmark runner |

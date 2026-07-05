# V10.1 BM25 Scope Selection + LLM Scope Filter

LongMemEval-S graph retrieval variant with the V10 question-independent graph and fixed BM25 E4 scope recall, followed by a conservative LLM filter over the recalled scope nodes.

## Pipeline

1. Build one graph per case from all haystack sessions.
2. Build a compact text profile for each scope node.
3. Use the fixed V10 BM25 configuration to recall top scope nodes.
4. Build compact scope cards for the BM25 candidates from existing graph neighborhoods.
5. Ask an LLM to reject only clearly unrelated scope candidates.
6. Run the unchanged V10 expansion flow: filtered scopes -> events -> claims -> sessions.
7. Compose the final answer with the shared LongMemEval-S task adapter prompts.

The graph is not rebuilt or changed by V10.1. The LLM receives the question and BM25 candidate scope cards only; it does not receive gold answers, gold session ids, or correctness labels.

## Fixed BM25 E4 Parameters

These defaults are inherited unchanged from V10:

- `scope_profile_events = 5`
- `scope_profile_claims = 10`
- `scope_label_weight = 3`
- `entity_label_weight = 2`
- `scope_profile_event_tokens = 80`
- `scope_profile_claim_tokens = 60`
- BM25 scoring uses `k1 = 1.5` and `b = 0.75`

## LLM Scope Filter

For each BM25 candidate scope, V10.1 sends a compact card with:

- `node_id`, `label`, `bm25_rank`, `bm25_score`, `degree`, `event_count`
- query terms matched by the V10 BM25 scope profile
- a small set of nearby events from that scope
- nearby claims supported by those events
- nearby state facets attached to those claims
- nearby entity labels mentioned by those events

The LLM returns strict JSON:

```json
{
  "selected_scopes": [{"node_id": "scope id", "keep_score": 0.8, "reason": "short reason"}],
  "rejected_scopes": [{"node_id": "scope id", "reason": "short reason"}]
}
```

The filter is conservative. If the LLM selects no valid scope, V10.1 falls back to the original BM25 top scopes. If the LLM selects fewer than `min_filtered_scopes`, the runner backfills the highest-ranked BM25 scopes.

## Build Graphs

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v10_1.build_all `
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
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v10_1.run_longmemeval `
  --limit-per-type 10 `
  --question-types knowledge-update multi-session single-session-preference temporal-reasoning `
  --scope-provider openai --scope-model gpt-4o-mini `
  --answer-provider openai --answer-model gpt-4o-mini `
  --judge --judge-provider openai --judge-model gpt-4o `
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v10_1/outputs/results_v10_1.json
```

The state packet uses:

```json
{
  "retrieval_strategy": "v10_1_bm25_llm_scope_filter_expand",
  "scope_ranker": "bm25_scope_profile_llm_filter",
  "llm_scope_filter": {}
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
| `bm25_llm_scope_filter_retriever.py` | BM25 top-scope LLM denoising layer |
| `run_longmemeval.py` | Benchmark runner |

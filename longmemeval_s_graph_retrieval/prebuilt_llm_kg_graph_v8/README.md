# V8 — Scope-Time-State Graph Retrieval

LongMemEval-S benchmark graph-based retrieval: question-independent graph construction with LLM semantic scope selection.

## Architecture

```
build_all.py ──→ v6 checkpoint builder ──→ artifacts/graphs/<type>/<id>.graph.json
                                          │
run_longmemeval.py ──→ LLM scope selector ──→ State_packet ──→ 4o-mini answer ──→ gpt-4o judge
```

## Pipeline

### 1. Build Graphs (offline)

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v8.build_all \
  --limit-per-type 10 \
  --question-types knowledge-update \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash \
  --max-global-workers 10 \
  --parallel-per-type 10
```

- Question-independent: all haystack sessions ingested, no BM25 pre-filter
- Batch checkpointing: resume on interruption without re-running LLM calls
- Supports `--question-ids` for single-case builds

### 2. Run Benchmark

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v8.run_longmemeval \
  --limit-per-type 10 \
  --question-types multi-session temporal-reasoning \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v8/artifacts/graphs \
  --answer-provider openai --answer-model gpt-4o-mini \
  --scope-provider openai --scope-model gpt-4o-mini \
  --judge --judge-provider openai --judge-model gpt-4o \
  --output outputs/results_v8.json
```

### Retrieval Strategy

**Scope selection** (LLM): 4o-mini semantically selects relevant scope nodes from the graph by examining scope neighborhood content (events, claims, entities, facets).

```
Question → LLM sees scope profiles → selects top 8 scopes
  → expand events → expand claims → State_packet
```

**Optimal params** (empirically tested on 60 cases):
- `--scope-profile-events 3 --scope-profile-claims 5`
- `--scope-profile-entities 5 --scope-profile-facets 3`
- `--scope-profile-event-tokens 30 --scope-profile-claim-tokens 40`

### Graph Schema

5 node types: Event, Claim, State Facet, Entity/Scope, Time
8 edge types: event_mentions_entity, event_in_scope, claim_supported_by_event,
              claim_supersedes_claim, claim_corrects_claim, claim_conflicts_with_claim,
              facet_supported_by_claim, facet_current_after_time

### State_packet Output

```json
{
  "relevant_session_ids": [...],
  "evidence_snippets": [...],
  "state_facets": [...],
  "rejected_claims": [...],
  "enough_evidence": true,
  "retrieval_strategy": "v7_5_llm_scope_first_expand",
  "matched_scopes": [...],
  "matched_entities": [...],
  "llm_scope_selection": {...}
}
```

## Results (LongMemEval-S, 60 cases)

| Type | Cases | V8 | TSM | Zep |
|---|---|---|---|---|
| knowledge-update | 10 | 0.700 | 0.808 | 0.744 |
| multi-session | 20 | 0.500 | 0.692 | 0.474 |
| single-session-preference | 20 | 0.500 | 0.400 | 0.533 |
| temporal-reasoning | 10 | **0.800** | 0.699 | 0.541 |

Missing: single-session-assistant, single-session-user (not yet built).

## Files

| File | Purpose |
|---|---|
| `build_all.py` | Multi-worker scheduler with heartbeat and checkpoint |
| `build_one_case.py` | Single-case builder (used by build_all) |
| `checkpoint_builder.py` | Checkpointed question-independent graph builder |
| `llm_extractor.py` | LLM extractor (question-independent prompt) |
| `stable_client.py` | LLM client with reasoning_content fallback |
| `status_utils.py` | Atomic JSON writes and status tracking |
| `scope_retriever.py` | V7 base scope-first retriever |
| `llm_scope_retriever.py` | V7.5 LLM semantic scope selector (extends base) |
| `run_longmemeval.py` | Full benchmark runner (scope + answer + judge) |

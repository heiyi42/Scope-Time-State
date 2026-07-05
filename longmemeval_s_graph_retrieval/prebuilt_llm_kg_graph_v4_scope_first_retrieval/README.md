# V4: Scope-First Retrieval Over Prebuilt LLM KG Graphs

## Purpose

This version is based on v2 and keeps the same graph construction process and
JSON graph artifact format. The iteration is only about graph retrieval.

```text
Same as v2:
  BM25 top-20 sessions -> LLM graph construction -> graph JSON

Changed in v4:
  graph retrieval becomes scope-first and pipeline-aligned
```

The output `State_packet` format is unchanged, so answer and judge logic remain
the same.

## Directory Layout

This folder follows the v2 structure:

```text
prebuilt_llm_kg_graph_v4_scope_first_retrieval/
  build_all.py
  build_one_case.py
  stable_client.py
  status_utils.py
  scope_first_retriever.py
  run_longmemeval.py
  artifacts/
    graphs/
    cache/
    errors/
    intermediate/
    logs/
    status/
  outputs/
```

All graph data copied from v2 is stored under:

```text
artifacts/graphs/
```

This includes every graph artifact currently present in v2, not only the
60-case pilot subset.

## What Is Unchanged From V2

- Graph construction prompts.
- Graph schema.
- JSON graph artifact format.
- BM25 top-20 session boundary.
- Stable builder with heartbeat / worker isolation / retry / cache.
- Answer model prompt and judge logic.

## What Changes In V4

v2 graph retrieval is state-first:

```text
latest Time
  -> active State Facet
  -> supporting Claim
  -> supporting Event
  -> State_packet
```

v4 graph retrieval is scope-first:

```text
Question + question_type
  -> match Scope / Entity nodes
  -> find related Event nodes
  -> find Claims supported by those Events
  -> resolve supersedes / corrects / conflicts
  -> select current State Facets
  -> backtrack Evidence
  -> State_packet
```

This is meant to better match the Scope-Time-State pipeline:

```text
scope first -> time/update resolution -> current state -> evidence
```

## Fallback

The v4 retriever falls back to the v2 state-first retriever when scope-first
retrieval cannot produce a complete packet.

Fallback triggers include:

- no matched scope/entity nodes;
- no scope-related events;
- no scope-related claims;
- no active claims after update resolution;
- no current state facets;
- no evidence snippets.

Fallback avoids empty packets when scope matching is too strict.

## Build JSON Graphs

The builder is kept for structural parity with v2. It writes into this v4
folder by default.

Dry-run:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.build_all \
  --limit-per-type 1 \
  --dry-run
```

Build selected graphs:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.build_all \
  --limit-per-type 10 \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash \
  --max-global-workers 1
```

## Run LongMemEval-S With Scope-First Retrieval

Dry-run with the copied graph artifacts:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.run_longmemeval \
  --limit-per-type 10 \
  --dry-run
```

Run answer generation:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.run_longmemeval \
  --limit-per-type 10 \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v4_scope_first_retrieval/outputs/results_60_v4_scope_first.json
```

Run with judge:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.run_longmemeval \
  --limit-per-type 10 \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --judge \
  --judge-provider openai \
  --judge-model gpt-4o-2024-08-06 \
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v4_scope_first_retrieval/outputs/results_60_v4_scope_first_judged.json
```

## Method Boundary

This version does not rebuild graphs differently. It reuses v2-style graph
artifacts and changes only the traversal strategy used to build `State_packet`.


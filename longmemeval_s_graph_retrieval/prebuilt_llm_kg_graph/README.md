# Prebuilt LLM KG Graph

## Method

This method separates graph construction from benchmark-time retrieval.

It keeps the same Scope-Time-State graph schema as
`task_semantics_local_graph`, but changes the build process:

```text
Offline build phase:
  BM25 top-20 sessions for each selected LongMemEval-S case
    -> strong LLM builds local KG
    -> graph artifact is saved per question_id

Benchmark phase:
  load prebuilt graph artifact
    -> graph retriever emits State_packet
    -> official small reader model answers from State_packet
    -> judge scores the answer
```

The intended comparison setting is:

```text
Construction model: stronger LLM, e.g. deepseek-v4-flash or another selected builder
Reader model: gpt-4o-mini
Judge model: gpt-4o-2024-08-06
```

This must be reported as a two-model memory setting, not as a strict
`gpt-4o-mini only` result.

## Graph Schema

Node types:

- `Episode/Event`
- `Claim`
- `State Facet`
- `Entity/Scope`
- `Time`

Directed edge types:

- `event_mentions_entity`
- `event_in_scope`
- `claim_supported_by_event`
- `claim_corrects_claim`
- `claim_supersedes_claim`
- `claim_conflicts_with_claim`
- `facet_supported_by_claim`
- `facet_current_after_time`

## Build Knowledge Graphs

Dry-run without API calls:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.build_graph \
  --limit-per-type 1 \
  --dry-run
```

Build graph artifacts for the 60-case sample:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.build_graph \
  --limit-per-type 10 \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph/artifacts/graphs_60_v4flash
```

Each case is saved as:

```text
artifacts/graphs_60_v4flash/<question_id>.graph.json
```

The build manifest is saved as:

```text
artifacts/graphs_60_v4flash/build_manifest.json
```

## Use Prebuilt Graphs For Retrieval

Dry-run without API calls:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.run_longmemeval \
  --limit-per-type 1 \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph/artifacts/graphs_60_v4flash \
  --dry-run
```

Run the 60-case benchmark using prebuilt graphs:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.run_longmemeval \
  --limit-per-type 10 \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph/artifacts/graphs_60_v4flash \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --judge \
  --judge-provider openai \
  --judge-model gpt-4o-2024-08-06 \
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph/outputs/results_60_prebuilt_graph_4omini.json
```

## Output Areas

Graph artifacts:

```text
artifacts/
```

Benchmark outputs:

```text
outputs/
```

Do not write intermediate graphs or prototype results into the main
`stamb_state_benchmark/output/` directory.


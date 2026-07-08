# LoCoMo QA External Benchmark

This directory keeps the LoCoMo graph build separate from the STAMB-State benchmark contract.
The active LoCoMo path is graph-first: build one persistent graph per `sample_id`, then reuse that
graph for all questions from the same sample.

## Data

Official release:

- Project page: https://snap-research.github.io/locomo/
- Repository: https://github.com/snap-research/LoCoMo
- Data file: `data/locomo10.json`

Download:

```bash
mkdir -p Experiment/Other_BenchMark/LoCoMo-QA/data
curl -L --fail --show-error \
  --output Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  https://raw.githubusercontent.com/snap-research/LoCoMo/main/data/locomo10.json
```

The data file is intentionally ignored by git.

## Graph Build

The graph builder reads only `sample_id` and `conversation` fields. The LoCoMo release colocates
QA fields with the conversation in one JSON file, so the manifest records that `qa`, `answer`, and
`evidence` fields are ignored and not used for graph construction.

Build one sample with DeepSeek:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --resolver-mode llm \
  --message-chunk-size 16 \
  --claim-workers 4 \
  --resolver-workers 4 \
  --resolver-candidate-limit 24 \
  --max-claims-per-turn 2 \
  --output-dir Graph/output/graph/locomo_qa_sample_graph_v1 \
  --cache Graph/output/cache/llm_cache.locomo_qa_graph_builder.conv-26.deepseek_v4_flash.json
```

Output layout:

```text
Graph/output/graph/locomo_qa_sample_graph_v1/<sample_id>/
  manifest.json
  graph_summary.json
  nodes.jsonl
  edges.jsonl
```

## Graph QA

Run the `conv-26` questions against the graph using the EverMemBench-style staged retrieval variants:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_query.py \
  --sample-id conv-26 \
  --graph-dir Graph/output/graph/locomo_qa_sample_graph_v1/conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --judge-provider deepseek \
  --judge-model deepseek-v4-flash \
  --variants graph_bm25 graph_embedding_event graph_embedding_scope_event graph_embedding_state_scope_event \
  --question-types multi-hop open-domain \
  --limit-per-type 10 \
  --top-k 12 \
  --scope-top-k 8 \
  --scope-types speaker,entity,topic,session \
  --state-search-k 12 \
  --candidate-k 80 \
  --embedding-candidate-k 80 \
  --answer-workers 4 \
  --output Graph/output/result/results_locomo_qa_graph_conv26_staged_embedding.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_graph_query.conv-26.deepseek_v4_flash.json \
  --judge-cache Graph/output/cache/llm_cache.locomo_qa_graph_query.conv-26.judge.deepseek_v4_flash.json \
  --embedding-cache Graph/output/cache/embedding_cache.locomo_qa_graph_query.conv-26.text_embedding_3_small.json
```

Retrieval order is `scope routing -> scoped event retrieval -> state/graph expansion -> answer -> judge`.

## Schema

Node types:

- `Episode/Event`: raw dialog turns, keyed by LoCoMo dialog IDs such as `D1:3`.
- `Claim`: atomic memory claims extracted from dialog turns.
- `StateFacet`: graph-searchable fact facets supported by claims.
- `Entity/Scope`: sample, session, speaker, entity, and topic scopes.
- `Time`: session date-times and extracted claim time expressions.

Edge types:

- `MENTIONS`, `IN_SCOPE`
- `ASSERTS`, `SUPPORTS`
- `CORRECTS`, `SUPERSEDES`, `CONFLICTS_WITH`
- `OCCURRED_AT`, `HAS_TIME`, `CURRENT_AFTER`
- `CURRENT_STATE_OF`

The deprecated text-only task-adapter runner has been removed from the active LoCoMo path.

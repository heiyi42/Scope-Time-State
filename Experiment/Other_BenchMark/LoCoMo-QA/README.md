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
  --graph-schema v2 \
  --resolver-mode llm \
  --message-chunk-size 16 \
  --claim-workers 4 \
  --resolver-workers 4 \
  --resolver-candidate-limit 24 \
  --max-claims-per-turn 2
```

Output layout:

```text
Graph/output/graph/locomo_qa_sample_graph_time_role_relation_v2/<sample_id>/
  manifest.json
  graph_summary.json
  nodes.jsonl
  edges.jsonl
```

The active STS default is the role-aware v2 graph. Its graph and cache paths are separate from the
legacy v1 reproduction path:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --resolver-mode llm \
  --message-chunk-size 16 \
  --claim-workers 4 \
  --resolver-workers 4
```

Without overrides, v2 writes to
`Graph/output/graph/locomo_qa_sample_graph_time_role_relation_v2/<sample_id>/` and uses
`Graph/output/cache/llm_cache.locomo_qa_graph_builder.time_role_relation_v2.json`. Use
`--graph-schema v1` only for legacy reproduction; the CLI refuses to write a v2 graph into a directory
whose name ends in `_v1`.

## Graph QA

Run the `conv-26` questions against the graph using the EverMemBench-style staged retrieval variants:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_query.py \
  --sample-id conv-26 \
  --graph-dir Graph/output/graph/locomo_qa_sample_graph_time_role_relation_v2/conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants graph_bm25 graph_embedding_event graph_embedding_scope_event \
  --question-types multi-hop open-domain \
  --limit-per-type 10 \
  --top-k 12 \
  --scope-top-k 8 \
  --scope-types speaker,entity,topic,session \
  --state-search-k 12 \
  --time-role-selector llm \
  --candidate-k 80 \
  --embedding-candidate-k 80 \
  --answer-workers 4 \
  --output Graph/output/results/locomo_qa/ours_scope_time_state/results_locomo_qa_graph_conv26_staged_embedding.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_graph_query.conv-26.deepseek_v4_flash.json \
  --embedding-cache Graph/output/cache/embedding_cache.locomo_qa_graph_query.conv-26.text_embedding_3_small.json
```

Retrieval order is `Scope routing -> scoped Event candidates -> question-only Time-role selection ->
Time-aware Event rerank -> Time/Validity-aware StateFacet selection -> graph expansion -> answer ->
optional open-domain mapping -> official-style scoring`. In the embedding variants, Scope and Event each
use independent BM25 and dense retrieval followed by a scored union; dense retrieval is no longer limited
to the BM25 candidate pool. The selector uses only the question and returns roles from a fixed STS ontology
such as `CURRENT_AFTER`, `planned_for`, `deadline_at`, and `completed_at`; it does not receive LoCoMo
question types, answers, evidence IDs, or task-specific templates. `--graph-expansion auto` preserves
the legacy one-hop expansion for v1 graphs. For v2 graphs it automatically traverses
`Event -> Claim -> StateFacet`, supporting claims/events, and `CORRECTS`/`SUPERSEDES`/
`CONFLICTS_WITH` claim neighbors.

The `graph_embedding_scope_event_state` variant additionally takes the union of independent BM25 and
dense StateFacet candidates before Time/Validity reranking. For a final 16-facet run, set both `--state-search-k 16` and
`--max-state-lines 16`; `max-state-lines` is the final prompt cap, while `state-search-k` controls
how many StateFacets enter graph expansion.

The mapping layer is only applied to `open-domain` questions after graph retrieval. It converts
cited conversation facts into a short commonsense bridge and answer hint, without writing those
inferred facts back into the graph. Use `--disable-open-domain-mapping` for an ablation that
answers directly from retrieved graph evidence.

## Memory Baselines

The comparison table baselines are tracked separately from the graph runner.
Implementation code lives under `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/`;
the LoCoMo-QA root keeps experiment entrypoints only.

Supported variants:

- `full_text`: direct full-conversation context, no external memory system.
- `rag`: OpenAI-compatible embedding retrieval over raw conversation turn chunks. It uses no BM25/hybrid prefilter; retrieved chunks are mapped back to original dialog IDs for evidence accounting.
- `tsm`: the local STAMB TSM reference implementation under `Experiment/Main_Baseline/tsm/`.
- `memory_bank`: official MemoryBank-SiliconFriend prompt + FAISS retrieval path. The official
  runtime runs in an isolated worker subprocess; LangChain compatibility shims are local to that
  worker and are not imported by the main runner.
- `a_mem`: official `agiresearch/A-mem` `AgenticMemorySystem.add_note/search(_agentic)` path.
- `memgpt`: official Letta Code CLI path, used as the current MemGPT/Letta implementation.
- `mem0_local`, `memos_local`, `memobase`, `graphiti_local`: official-service baselines using the same `BaseAdapter.add/search` interface and adapter layout as `Experiment/Other_BenchMark/EverMemBench/Baseline/`.

The memory baseline runner builds memory only from `sample.conversation`. It does not expose gold
answers, gold evidence IDs, official categories, or question-type labels to retrieval/controller/answer
prompts. Evidence metrics are computed from model-emitted `evidence_dialog_ids`; missing citations
are not backfilled from retrieved candidates.

The official-service variants convert one LoCoMo `sample_id` into an official group-chat `Dataset`
and embed dialog IDs in visible message text before calling the adapter. The adapter writes to the
official memory system with `add(dataset, user_id)` and retrieves with `search(question, user_id)`;
the LoCoMo runner only handles data conversion, answer prompting, metrics, and local ingest-state
bookkeeping.

Run directly callable baselines:

```bash
env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  conda run -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants full_text rag \
  --question-types multi-hop open-domain \
  --top-k 24 \
  --rag-chunk-target-chars 900 \
  --rag-chunk-overlap-turns 1 \
  --answer-workers 2 \
  --output Graph/output/results/locomo_qa/mixed/results_locomo_qa_memory_baselines_conv26_multi_open.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_memory_baselines.conv-26.deepseek_v4_flash.json
```

Official-service storage should be started from each upstream project's official local/self-host
instructions. Docker Compose is only a launcher, not part of the benchmark logic, but the backing
stores are required:

```text
mem0_local      -> official Mem0 server, Postgres + pgvector
memos_local     -> official MemOS server, Neo4j + Qdrant
memobase        -> official Memobase server, Postgres + Redis
graphiti_local  -> graphiti-core, Neo4j
```

Set service URLs and model endpoints through environment variables or `.env`:

```bash
MEM0_LOCAL_BASE_URL=http://localhost:8888
MEMOS_LOCAL_BASE_URL=http://localhost:8001
MEMOBASE_BASE_URL=http://localhost:8019
MEMOBASE_API_TOKEN=your_memobase_token

GRAPHITI_LLM_API_KEY=local
GRAPHITI_LLM_BASE_URL=http://127.0.0.1:8000/v1
GRAPHITI_LLM_MODEL=your-30b-model-name
GRAPHITI_EMBEDDING_API_KEY=your-openai-key
GRAPHITI_EMBEDDING_BASE_URL=https://api.openai.com/v1
GRAPHITI_EMBEDDING_MODEL=text-embedding-3-small
GRAPHITI_EMBEDDING_DIM=1536
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

Run official-service baselines after the services are healthy:

```bash
env PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false LLM_PARSE_RETRIES=6 \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants mem0_local memos_local memobase graphiti_local \
  --question-types multi-hop open-domain \
  --top-k 24 \
  --official-search-concurrency 1 \
  --answer-workers 2 \
  --output Graph/output/results/locomo_qa/mixed/results_locomo_qa_official_services_conv26_multi_open.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_official_services.conv-26.deepseek_v4_flash.json
```

The first run writes an ingest state under
`Graph/output/baseline_store/locomo_qa/official_services/<variant>/<sample_id>/`.
Use `--reuse-baseline-store` to skip repeated `add()` calls with the same local state, and use
`--force-official-ingest` when the service store was reset or when a fresh official-service ingest is
intended. Use `--official-user-id` only when intentionally querying an existing service-side namespace.

Official-source/CLI variants need their upstream repo paths or CLI entrypoints:

```bash
--memory-bank-official-repo Graph/output/service_repos/locomo_smoke/MemoryBank-SiliconFriend
--amem-repo-dir Graph/output/service_repos/locomo_smoke/A-mem
--letta-code-repo Graph/output/service_repos/locomo_smoke/letta-code
```

For local Ollama smoke tests with Letta Code, pass the provider-qualified model handle, for example
`--letta-model ollama/qwen2.5:7b`; the LoCoMo answer model can still be `--model qwen2.5:7b`.

Use `--dry-run` to validate selection and CLI wiring without building memories or calling LLM/embedding APIs:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  conda run -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --variants memory_bank a_mem memgpt mem0_local memos_local memobase graphiti_local \
  --question-types temporal \
  --limit-cases 1 \
  --dry-run
```

## Schema

Node types:

- `Episode/Event`: raw dialog turns, keyed by LoCoMo dialog IDs such as `D1:3`.
- `Claim`: atomic memory claims extracted from dialog turns.
- `StateFacet`: graph-searchable fact facets supported by claims.
- `Entity/Scope`: sample, session, speaker, entity, and topic scopes.
- `Time`: session date-times and extracted claim time expressions. In v2, `time_role` is a node
  attribute with values such as `occurred_at`, `planned_for`, `deadline_at`, `valid_from`,
  `started_at`, `completed_at`, `finalized_at`, and `current_after`; `TimeRole` is not a separate
  node type.

Edge types:

- `MENTIONS`, `IN_SCOPE`
- `ASSERTS`, `SUPPORTS`
- `CORRECTS`, `SUPERSEDES`, `CONFLICTS_WITH`
- `OCCURRED_AT`, `HAS_TIME`, `CURRENT_AFTER`
- `CURRENT_STATE_OF`

The deprecated text-only task-adapter runner has been removed from the active LoCoMo path.

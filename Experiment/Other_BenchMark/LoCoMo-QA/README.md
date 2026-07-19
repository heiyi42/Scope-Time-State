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

## Graph Ingest / Build

The graph builder reads only `sample_id` and `conversation` fields. The LoCoMo release colocates
QA fields with the conversation in one JSON file, so the manifest records that `qa`, `answer`, and
`evidence` fields are ignored and not used for graph construction.

The active LoCoMo path uses `gpt-4o-mini` for both Claim ingest and all LLM
identity/state resolution. Build one sample into an isolated candidate directory:

Before running either command below, configure `OPENAI_API_KEY` and
`OPENAI_API_BASE` (or `OPENAI_BASE_URL`) in `.env` or the environment. The
commands set both `OPENAI_MODEL=gpt-4o-mini` and `--model gpt-4o-mini` explicitly
so provider initialization and the recorded run configuration cannot drift.

```bash
env \
  PYTHONDONTWRITEBYTECODE=1 \
  OPENAI_MODEL=gpt-4o-mini \
  LLM_PARSE_RETRIES=3 \
  LLM_SEMANTIC_RETRIES=3 \
  LLM_REQUEST_TIMEOUT=120 \
  LLM_MAX_RETRIES=3 \
  LLM_RETRY_BASE_DELAY_SECONDS=2 \
  LLM_RETRY_MAX_DELAY_SECONDS=120 \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --graph-schema v2 \
  --claim-mode llm \
  --resolver-mode llm \
  --provider openai \
  --model gpt-4o-mini \
  --max-tokens 4096 \
  --message-chunk-size 4 \
  --claim-workers 4 \
  --resolver-workers 4 \
  --resolver-candidate-limit 24 \
  --max-claims-per-turn 2 \
  --event-limit 0 \
  --output-dir Graph/graph/locomo_qa_sample_graph_v2_state_merge \
  --cache Graph/cache/llm_cache.locomo_qa_graph_builder.v2_state_merge.json
```

Output layout:

```text
Graph/graph/locomo_qa_sample_graph_v2_state_merge/<sample_id>/
  manifest.json
  graph_summary.json
  nodes.jsonl
  edges.jsonl
```

The active v2 builder uses stable `subject_key + state_dimension` routing, an ordered local Claim fold, explicit
`primary_claim_id`, and multi-support StateFacets. Compatible support Claims are retained as provenance; query-time
proof closure uses the primary Claim plus only the relation witnesses required for lifecycle or ambiguity.

Without overrides, the active v2 state-merge builder writes to
`Graph/graph/locomo_qa_sample_graph_v2_state_merge/<sample_id>/` and uses
`Graph/cache/llm_cache.locomo_qa_graph_builder.v2_state_merge.json`. The CLI default is v2.
That default path replaces the same sample/schema only after a fully validated atomic write. Use the explicit isolated
`--output-dir` and per-sample `--cache` shown above for candidate rebuilds so retained graphs are not overwritten.
Pass `--graph-schema v1` only for legacy reproduction and A/B comparison.

## Graph QA

Run the `conv-26` questions against the active state-merge graph. Answer generation and the question-only Time-role selector
both use `gpt-4o-mini`; `text-embedding-3-small` is used only for dense retrieval:

The default STS order has one retrieval entry: retrieve Scope, recall and time-rerank Events only inside the routed
Scopes, then traverse `Event -> Claim -> StateFacet` during relation-aware graph expansion. StateFacet is never an
independent BM25 or dense retrieval target. `--scope-backoff-k 0` is the default; a sample-wide Event backoff is an
explicit ablation rather than part of the main chain.

```bash
env \
  PYTHONDONTWRITEBYTECODE=1 \
  OPENAI_MODEL=gpt-4o-mini \
  LLM_PARSE_RETRIES=3 \
  LLM_SEMANTIC_RETRIES=3 \
  LLM_REQUEST_TIMEOUT=120 \
  LLM_MAX_RETRIES=3 \
  LLM_RETRY_BASE_DELAY_SECONDS=2 \
  LLM_RETRY_MAX_DELAY_SECONDS=120 \
  LLM_MAX_TOKENS=2048 \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_query.py \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --graph-dir Graph/graph/locomo_qa_sample_graph_v2_state_merge/conv-26 \
  --provider openai \
  --model gpt-4o-mini \
  --variants graph_embedding_scope_event \
  --limit-cases 0 \
  --limit-per-type 0 \
  --top-k 12 \
  --scope-top-k 10 \
  --scope-backoff-k 0 \
  --scope-types speaker,entity,topic \
  --candidate-k 80 \
  --embedding-candidate-k 80 \
  --max-context-events 24 \
  --max-state-lines 8 \
  --max-ledger-claims 12 \
  --max-ledger-states 8 \
  --max-ledger-events 8 \
  --ledger-fallback-events 2 \
  --time-role-selector llm \
  --event-time-routing rerank \
  --graph-expansion relation-aware \
  --evidence-citation-source answer \
  --embedding-model text-embedding-3-small \
  --embedding-batch-size 64 \
  --answer-workers 4 \
  --output Graph/results/locomo_qa/ours_scope_time_state/results_locomo_qa_graph_conv26_v2_state_merge_gpt4omini.json \
  --cache Graph/cache/llm_cache.locomo_qa_graph_query.conv-26.v2_state_merge_gpt4omini.json \
  --embedding-cache Graph/cache/embedding_cache.locomo_qa_graph_query.conv-26.v2_state_merge.text_embedding_3_small.json
```

The embedding cache is stored under the same-named `.json.d/` directory. The
run also writes a sibling
`results_locomo_qa_graph_conv26_v2_state_merge_gpt4omini.graph_embedding_scope_event.hypotheses.jsonl`
trace beside the result JSON.

To ablate the LLM Ledger selector and its repair call, add
`--evidence-selector deterministic`. This keeps the same graph expansion and fixed proof budgets, greedily accepts
complete proof bundles in retrieved Event order, skips bundles that exceed a budget, and fills any remaining Event
capacity by retrieval rank. It does not invoke the Ledger or Ledger-repair prompts. The default
`--evidence-selector llm-ledger` is retained only as the explicit comparison baseline.

For the stricter no-selection ablation, use `--evidence-selector direct`. This passes the bounded output of graph
expansion directly to temporal readout and QA. It performs no evidence selection or repacking, and ignores all
`--max-ledger-*` and `--ledger-fallback-events` settings; the effective context bounds are the STS retrieval and graph
expansion settings such as `--max-context-events` and `--max-state-lines`.

When `--graph-dir` is omitted, it is derived from `--sample-id`. When `--output` is omitted, the filename includes
the sample, variants, provider, resolved model, and a semantic run-config fingerprint, so smoke runs and retrieval
ablations do not overwrite one another. An explicit `--output` keeps the caller-selected path.

Retrieval order is `question-only semantic Frame -> Scope routing -> question-only Time-role selection -> scoped Event candidates ->
bounded Time-aware rerank -> Event -> Claim -> StateFacet graph expansion ->
evidence selection -> deterministic complete-proof closure and budgeting -> graph-normalized temporal readout -> universal grounded-slot compiler -> official-style scoring`.
Evidence selection is either the comparison baseline's ordered Claim/StateFacet LLM Ledger or the deterministic
retrieval-ranked ablation described above.
First-stage Scope retrieval is limited to `speaker,entity,topic`. Session Scope nodes and their Event edges remain in the
graph for conversation segmentation and provenance, but are not indexed by BM25 or embeddings and cannot compete for
the shared semantic Scope top-k. With the default `--scope-backoff-k 0`, no routed Scope means no Event candidates; the runner
does not silently fall through to a sample-wide search.
`--scope-anchor-routing reserve` is a query-only ablation: exact conversation participants mentioned by the question
reserve their deduplicated Speaker and atomic Entity Scopes inside the same fixed Scope top-k, and the remaining slots
use the unchanged BM25/embedding ranking. It does not filter other entities, inspect task labels, or use gold data. The
comparison default is `--scope-anchor-routing off`.
`--binding-gate participant` is a separate answer-verification ablation. It leaves retrieval and the direct evidence
context unchanged, then rejects a non-abstaining answer only when all of its cited graph Claims belong to conversation
participants other than those explicitly named in the question frame. The gate uses no task labels, gold answers, or
gold evidence and makes no additional LLM call. Its comparison default is `--binding-gate off`.
This is one fixed STS path for every question; there is no question-type branch. Temporal readout deterministically
grounds the selected v1/v2 evidence at query time. It does not mutate the graph or receive task labels, answers, or
gold evidence. Time routing may return no role for questions where temporal semantics or
current-state validity is not needed. Explicit recent/current/deadline/start/completion/update/plan/finalization
questions use high-precision deterministic routing; ambiguous questions fall through to the question-only LLM
selector. Recent-activity questions route to occurred/start/update evidence with `newest_first` ordering rather
than treating `recent` as a synonym for `updated_at`. Time scores are a bounded rerank signal rather than a replacement for
semantic relevance. Recency uses normalized semantic fact time when available, then report time, then dialog order;
a late recollection of an old event is not treated as the newest fact. Setting `--scope-backoff-k` above zero explicitly
adds a sample-wide Event recall ablation using the same question; it is not part of the default STS method. In the
embedding variants, Scope and Event each use independent BM25 and dense retrieval. Event candidates use
max-RRF with a small fixed overlap bonus: a high rank from either retriever is preserved, while agreement still
helps without allowing low-ranked dual hits to bury dense-only semantic evidence. Raw lexical and embedding
score scales never mix. Each Event index document
contains the raw turn plus graph-derived Claim summaries and attached Scope labels, while the retrieval unit and
returned ID remain the Event. Dense retrieval is not limited to the BM25 candidate pool. The selector uses only
the question and returns roles from a fixed STS ontology
such as `CURRENT_AFTER`, `planned_for`, `deadline_at`, and `completed_at`; it does not receive LoCoMo
question types, answers, evidence IDs, or task-specific templates. `--graph-expansion auto` preserves
the legacy one-hop expansion for v1 graphs. For v2 graphs it automatically traverses
`Event -> Claim -> StateFacet`, supporting claims/events, and `CORRECTS`/`SUPERSEDES`/
`CONFLICTS_WITH` claim neighbors. Relation traversal is query-ranked at Claim level: all seed Event Claims
remain available as direct evidence, but only the most query-relevant Claim group in each seed Event can
open a relation chain. Once opened, traversal follows the complete same-subject, same-state-group relation
closure without a fixed hop count and stops at a subject/group boundary. The evidence closure retains visited Claims plus Claims
required by retained StateFacets and closed relation edges, rather than injecting every Claim attached to a
retained Event. Graph-expanded StateFacets are ranked by seed Event rank, relation distance, and supporting
Claim relevance before `--max-state-lines` is applied.

Every supported retrieval variant reaches StateFacets only through routed Event seeds and the graph's `ASSERTS` and
`SUPPORTS` edges. The runner checks this reachability invariant before constructing the prompt. `--max-state-lines`
is only the final cap over graph-expanded StateFacets.

After graph expansion, one uniform Ledger selects an ordered list of Claim and StateFacet units only from the expanded
allowlists; the prompt exposes short `C<n>` / `S<n>` handles and the runner deterministically maps them back to exact
candidate-whitelisted graph IDs. It cannot select Events, retrieve new evidence, or create IDs. The runner expands each unit
into a complete proof bundle: a Claim contributes its source Event; an active v2 StateFacet contributes its primary
Claim plus any lifecycle/conflict relation witnesses and their required Events, while compatible duplicate supports
remain provenance. A closed retained relation contributes its evidence Events. Fixed positive budgets are applied to
these complete bundles rather than to disconnected node lists. Any malformed, out-of-pool, incomplete, or over-budget
selection is rejected as a whole and receives one constrained LLM repair with validation feedback. A valid selection is
used exactly as selected and never receives rank-floor evidence. Only if the repair also fails does the runner retain the
top two candidate Events as an explicit `fallback_unresolved` pack. Invalid budget values fail explicitly.
The answer compiler and count logic share the resulting selected-Event whitelist rather than the larger pre-Ledger
candidate set. Exact Claim and StateFacet IDs remain explicit in the internal Ledger trace, while the LLM-facing contract
uses short handles to avoid long-ID transcription failures. The trace records ordered requests, accepted and rejected
units, deterministic closure, repair attempt, and fallback status.
This is evidence postprocessing rather than a second retrieval. The runner has no benchmark category or question-type branch. The QA controller and prompts
do not receive LoCoMo `question_type`, `category`, gold answers, or gold evidence. The answer compiler applies
one prompt to all questions and verifies its final wording against the selected source turns.

The answer compiler first parses every question into the same semantic frame: entities, required bindings,
requested slot, operation, and count unit. Operations are general language semantics (`lookup`, `enumerate`,
`count`, `intersection`, `compare`, `boolean`, or `inference`), not LoCoMo task labels. Enumerated and shared
values are compiled from grounded value rows, and occurrence counts are compiled from distinct cited Event IDs.
Coverage operations (`enumerate`, `count`, and `intersection`) add at most three Frame-derived atomic expressions
to the same Scope/Event BM25+embedding retrieval; other operations keep the original question unchanged.
For concrete lookup slots the controller uses the grounded value field, while generic description slots retain the
generated answer text. A relative-time answer is replaced only when it exactly matches an expression from the same
cited Event and that Event already has a deterministic normalized value.
The frame parser and answer prompt never receive benchmark categories or gold data.

### Current conv-26 ablation decision

The `gpt-4o-mini` grounded-slot v7 candidate is not promoted over the unified-ledger v6 report line because
it regresses open-domain and adversarial despite improving the weighted and task-averaged totals:

| Task | unified-ledger v6 | grounded-slot v7 |
|---|---:|---:|
| Open-domain | 0.2697 | 0.2644 |
| Single-hop | 0.5403 | 0.5436 |
| Temporal | 0.7311 | 0.8436 |
| Multi-hop | 0.3132 | 0.3749 |
| Adversarial | 0.3617 | 0.2766 |
| Overall | 0.4794 | 0.4910 |
| Task average | 0.4432 | 0.4606 |

## Memory Baselines

The comparison table baselines are tracked separately from the graph runner.
Implementation code lives under `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/`;
the LoCoMo-QA root keeps experiment entrypoints only.

Supported variants:

- `full_text`: direct full-conversation context, no external memory system.
- `rag`: OpenAI-compatible embedding retrieval over raw conversation turn chunks. It uses no BM25/hybrid prefilter; retrieved chunks are mapped back to original dialog IDs for evidence accounting.
- `memory_bank`: official MemoryBank-SiliconFriend prompt + FAISS retrieval path. The official
  runtime runs in an isolated worker subprocess; LangChain compatibility shims are local to that
  worker and are not imported by the main runner.
- `a_mem`: official `agiresearch/A-mem` `AgenticMemorySystem.add_note/search(_agentic)` path.
- `memgpt`: official Letta Code CLI path, used as the current MemGPT/Letta implementation.
- `memos_local`, `memobase`, `graphiti_local`: official-service baselines using the same `BaseAdapter.add/search` interface and adapter layout as `Experiment/Other_BenchMark/EverMemBench/Baseline/`.

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
  --output Graph/results/locomo_qa/mixed/results_locomo_qa_memory_baselines_conv26_multi_open.json \
  --cache Graph/cache/llm_cache.locomo_qa_memory_baselines.conv-26.deepseek_v4_flash.json
```

Official-service storage should be started from each upstream project's official local/self-host
instructions. Docker Compose is only a launcher, not part of the benchmark logic, but the backing
stores are required:

```text
memos_local     -> official MemOS server, Neo4j + Qdrant
memobase        -> official Memobase server, Postgres + Redis
graphiti_local  -> graphiti-core, Neo4j
```

Set service URLs and model endpoints through environment variables or `.env`:

```bash
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
  --variants memos_local memobase graphiti_local \
  --question-types multi-hop open-domain \
  --top-k 24 \
  --official-search-concurrency 1 \
  --answer-workers 2 \
  --output Graph/results/locomo_qa/mixed/results_locomo_qa_official_services_conv26_multi_open.json \
  --cache Graph/cache/llm_cache.locomo_qa_official_services.conv-26.deepseek_v4_flash.json
```

The first run writes an ingest state under
`Graph/baseline_store/locomo_qa/official_services/<variant>/<sample_id>/`.
Use `--reuse-baseline-store` to skip repeated `add()` calls with the same local state, and use
`--force-official-ingest` when the service store was reset or when a fresh official-service ingest is
intended. Use `--official-user-id` only when intentionally querying an existing service-side namespace.

Official-source/CLI variants need their upstream repo paths or CLI entrypoints:

```bash
--memory-bank-official-repo Graph/service_repos/locomo_smoke/MemoryBank-SiliconFriend
--amem-repo-dir Graph/service_repos/locomo_smoke/A-mem
--letta-code-repo Graph/service_repos/locomo_smoke/letta-code
```

For local Ollama smoke tests with Letta Code, pass the provider-qualified model handle, for example
`--letta-model ollama/qwen2.5:7b`; the LoCoMo answer model can still be `--model qwen2.5:7b`.

Use `--dry-run` to validate selection and CLI wiring without building memories or calling LLM/embedding APIs:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  conda run -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --variants memory_bank a_mem memgpt memos_local memobase graphiti_local \
  --question-types temporal \
  --limit-cases 1 \
  --dry-run
```

## Schema

Node types:

- `Episode/Event`: raw dialog turns, keyed by LoCoMo dialog IDs such as `D1:3`.
- `Claim`: atomic memory claims extracted from dialog turns.
- `StateFacet`: graph-searchable current or ambiguous ongoing/timeless states supported by Claims; simultaneous values may have separate facets.
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

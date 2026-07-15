# EPBench Unified STS v2 Design

## Goal

Add a native Scope-Time-State v2 pipeline for the fixed EPBench Long Book corpus while preserving the existing ARTEM implementation unchanged. The new implementation lives under:

`Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/`

The pipeline must build the same public STS v2 graph contract used by LoCoMo and EverMemBench, then run STS-native retrieval, QA, and judging without calling STEM or ARTEM evaluation code.

## Frozen Corpus and Models

The only supported corpus for this implementation is:

`Experiment/Other_BenchMark/Episodic-Memory/data/Udefault_Sdefault_seed0/books/model_claude-3-5-sonnet-20240620_itermax_10_Idefault_nbchapters_196_nbtokens_102870`

It contains one 196-chapter Long Book and 686 QA rows. The model contract is:

- graph extraction and state resolution: `gpt-4o-mini`;
- QA: `gpt-4o-mini`;
- judge: `gpt-4o-mini`;
- dense retrieval: `text-embedding-3-small`.

The graph builder may read only `book.json`. It must not open `df_qa.parquet`, `df_book_groundtruth.parquet`, or any derived gold artifact. QA and judge stages may read `df_qa.parquet` only after graph publication.

## Architecture

The implementation is an EPBench-owned adapter around benchmark-neutral shared components:

- `pipeline/external/sts_v2/schema.py` supplies the graph schema;
- `pipeline/external/state_merge.py` supplies ordered state folding;
- existing shared embedding and temporal-grounding utilities supply dense retrieval and time normalization;
- `Baseline/STS/` owns EPBench loading, extraction prompts, graph materialization, retrieval aggregation, QA, judge, CLI, and tests.

The official `Baseline/ARTEM/` and `adapters/artem_epbench/` trees remain unchanged.

The proposed package is:

```text
Baseline/STS/
  __init__.py
  config.py
  loader.py
  graph_builder.py
  staged.py
  qa_runner.py
  run.py
  tests/
```

## Event and Evidence Granularity

EPBench evaluates chapter IDs and its ground-truth table has one episodic event per chapter. The graph therefore creates exactly one `Episode/Event` per chapter:

```text
event_id = epbench::chapter::<chapter_id>
```

Each Event stores the full chapter as `raw_text` for final evidence rendering, but retrieval does not embed the entire chapter directly. Instead, `gpt-4o-mini` creates a compact event card used as `graph_text`:

```text
date + location + entities + event types + concise event summary
```

Fine-grained evidence is represented by multiple Claims per chapter. Every extracted Scope and Claim must carry an exact `evidence_span` that can be located in the source chapter. Text chunks are extraction windows only; they never become graph Event nodes. The default extraction batch contains four chapters, while outputs remain strictly chapter-bound.

## Extraction Contract

For each chapter, the extraction model returns:

```text
chapter_id
concise_summary
dates[]
locations[]
entities[{name, kind, role, evidence_span}]
event_types[{label, evidence_span}]
claims[{subject, predicate, value, time_role, time_value, evidence_span}]
```

The adapter rejects rows with unknown chapter IDs, empty required values, missing source evidence, or evidence spans not found in the associated chapter. Scope values are normalized and deduplicated by code; LLM output never owns node IDs or edge types.

## Scope Model

The fixed Scope categories are:

- `book`: structural membership only and excluded from semantic scope retrieval;
- `entity`: people and organizations, with primary/participant/organization roles stored on Event-Scope edges;
- `location`: event venues or places;
- `event_type`: normalized event/activity labels.

Time is never represented as Scope. Dates and other temporal expressions create first-class `Time` nodes.

Scope nodes remain atomic. The graph does not create composite nodes such as `entity|location|event_type`. Query-time multi-type coverage supplies the effective intersection, while Event and Claim retrieval provide fine semantic resolution.

## Graph Contract

The schema version remains exactly:

`scope-time-state-graph-v2-state-merge`

Node types remain:

- `Episode/Event`;
- `Claim`;
- `StateFacet`;
- `Entity/Scope`;
- `Time`.

Edge types remain:

- `MENTIONS`;
- `IN_SCOPE`;
- `ASSERTS`;
- `OCCURRED_AT`;
- `HAS_TIME`;
- `CORRECTS`;
- `SUPERSEDES`;
- `CONFLICTS_WITH`;
- `SUPPORTS`;
- `CURRENT_AFTER`;
- `CURRENT_STATE_OF`.

No EPBench-only graph edge is added.

Only durable or updateable Claims enter state folding. Ordinary episodic actions remain Claims. State folding groups eligible Claims by `subject_key`, `state_domain`, and `state_dimension`, orders them chronologically, and uses the current shared decisions:

- `COMPATIBLE` merges Claim support into one StateFacet and does not create a Claim-Claim edge;
- `DIFFERENT_TARGET` keeps separate state clusters and does not create a Claim-Claim edge;
- `SUPERSEDES`, `CORRECTS`, and `CONFLICTS_WITH` create the corresponding Claim-Claim edges.

StateFacet nodes retain `primary_claim_id`, `support_claim_ids`, `support_event_ids`, stable state identity, `current_after`, and `current|historical|ambiguous` status.

## Retrieval Flow

The STS-native retrieval path is:

```text
Question
-> question-only frame extraction with gpt-4o-mini
-> Scope BM25 and dense retrieval
-> Event BM25 and dense retrieval
-> Claim BM25 and dense retrieval
-> chapter-level score aggregation
-> deterministic Time filtering or latest/chronological ordering
-> STS graph expansion
-> evidence-span context assembly
-> gpt-4o-mini answer
-> gpt-4o-mini judge
```

BM25 and embedding searches produce independent candidates and use their union. Embedding is not restricted to reranking BM25 hits.

Default retrieval budgets are:

- semantic Scope top-k: 32;
- Event candidate pool: 64;
- Claim candidate pool: 64;
- final chapter budget: 20.

Chapter aggregation rewards coverage across distinct Scope types rather than treating any single coarse Scope as a hard gate. The final seed score combines Scope coverage, Event BM25/dense evidence, Claim BM25/dense evidence, and temporal compatibility. Exact coefficients must be named CLI/config constants and recorded in the output manifest rather than hidden in prompts.

The question frame is derived from question text only. It must not receive `retrieval_type`, `get`, `correct_answer`, `correct_answer_chapters`, or other evaluator metadata. `latest` and `chronological` behavior is inferred from question wording and executed deterministically over graph Time nodes.

## QA and Judge Output

The pipeline evaluates all 686 QA rows through one STS path. It does not call STEM, ARTEM, or their filtering functions.

QA output records include:

- source QA ID and question;
- retrieved chapter IDs and ranked scores;
- selected Scope/Event/Claim/Time evidence;
- graph expansion trace;
- final context;
- `gpt-4o-mini` answer;
- per-stage cache/checkpoint metadata.

The judge adds a separate verdict and score using the reference answer. It never mutates the raw generated answer or retrieval trace. Aggregate summaries are derived from stored per-row judge results.

## CLI and Outputs

The single entrypoint is:

`Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py`

It supports:

```text
--stage build
--stage retrieve
--stage qa
--stage judge
--stage all
```

Default artifact roots are:

```text
Graph/output/graph/epbench_long_book_sts_v2/book1/
Graph/output/cache/epbench_long_book_sts_v2/
Graph/output/results/epbench_long_book_sts_v2/
```

All paths and model/retrieval budgets remain explicit CLI parameters with the frozen values above as defaults.

## Failure Handling and Publication

- Extraction uses chapter-addressable cache records and checkpoints so interrupted builds resume safely.
- Invalid JSON receives one constrained repair attempt; unresolved invalid output fails the build.
- State-fold candidate overflow fails rather than truncating clusters.
- Graph validation checks schema, endpoint node types, stable identities, source references, and evidence spans.
- A pre-existing directory without a compatible manifest cannot be overwritten.
- `manifest.json`, `graph_summary.json`, `nodes.jsonl`, and `edges.jsonl` are written to a temporary directory and atomically published only after validation succeeds.
- QA and judge use per-row checkpoints and can resume independently.

## Tests and Acceptance Criteria

All validation runs use `conda py311`.

Required tests cover:

1. the loader emits exactly 196 chapter Events for the frozen corpus;
2. graph build cannot access QA or ground-truth files;
3. every node and edge follows the shared v2 schema and endpoint contract;
4. repeated atomic Scope values share stable IDs across chapters;
5. every extracted Scope and Claim evidence span resolves against its source chapter;
6. compatible Claims share a StateFacet without a new Claim-Claim edge;
7. only `SUPERSEDES`, `CORRECTS`, and `CONFLICTS_WITH` materialize Claim-Claim relations;
8. Scope, Event, and Claim retrieval each preserve independent BM25-only and embedding-only candidates;
9. multi-Scope coverage improves chapter ranking without composite Scope nodes;
10. latest and chronological ordering use graph Time nodes deterministically;
11. a bounded fake-client smoke completes build, retrieval, QA, and judge;
12. a bounded real `gpt-4o-mini` smoke can resume from cache;
13. the full published graph contains exactly 196 Episode/Event nodes and zero validation warnings.

Implementation is complete only when the active `Baseline/STS/` path satisfies these contracts without importing ARTEM runtime modules.

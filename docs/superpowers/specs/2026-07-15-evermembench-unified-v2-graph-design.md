# EverMemBench Unified STS v2 Graph Design

## 1. Goal

EverMemBench and LoCoMo must use one Scope-Time-State v2 graph-construction contract. The LoCoMo active
`v2-state-merge` behavior is the source contract: stable `subject_key + state_dimension` routing, ordered Claim
folding, explicit `primary_claim_id`, multi-support StateFacets, deterministic graph materialization, and shared
validation.

EverMemBench must stop producing or accepting the benchmark-specific
`evermembench-sts-topic-graph-v6-endpoint-lifecycle` schema. Its old v6 graph artifacts, matching QA results,
v6-only caches, and code paths are deleted rather than retained as compatibility branches.

## 2. Scope

This change includes:

- a shared STS v2 graph core used by both LoCoMo and EverMemBench;
- benchmark adapters that normalize visible dialogue into the shared build input;
- a common node, edge, Claim, Time, StateFacet, manifest, validation, and atomic-write contract;
- migration of EverMemBench graph construction to the shared core;
- adaptation of EverMemBench retrieval to consume the common schema;
- deletion of EverMemBench v6-only construction and retrieval logic;
- deletion of retained v6 graphs, corresponding QA results, and v6-only caches;
- documentation and tests for the unified path.

This change does not unify benchmark scoring, answer parsing, or judging. EverMemBench keeps its official task
loading, answer generation, multiple-choice parsing, open-ended judging, and metric aggregation.

## 3. Rejected Alternatives

### 3.1 Share only state folding

Keeping separate builders while sharing only `pipeline/external/state_merge.py` leaves Claim extraction, Time
normalization, StateFacet materialization, validation, and manifests free to drift. This is not a unified graph
construction method.

### 3.2 Call the LoCoMo builder from EverMemBench

This would couple EverMemBench to LoCoMo file formats and benchmark-local modules. Shared graph semantics belong in
a benchmark-neutral module, not in either benchmark adapter.

## 4. Architecture

### 4.1 Shared core

Create a benchmark-neutral shared v2 package under `pipeline/external/sts_v2/`. The core owns:

- canonical normalized Event and Scope input types;
- the common node and edge vocabulary;
- Claim extraction prompt contract and normalization;
- Time-role normalization and Time node materialization;
- stable subject and state-dimension resolution;
- ordered Claim folding through the shared state-merge algorithm;
- StateFacet and lifecycle/conflict edge materialization;
- graph invariants and summary generation;
- leakage manifest fields;
- validated atomic graph writes.

The common schema version is `scope-time-state-graph-v2-state-merge`. Dataset identity belongs in manifest metadata,
not in the schema version.

### 4.2 LoCoMo adapter

The LoCoMo adapter reads only `sample_id` and conversation turns. It maps sessions, speakers, source timestamps, and
dialog IDs to the normalized input contract. It does not pass QA, answers, evidence, summaries, or benchmark task
labels to the shared core.

### 4.3 EverMemBench adapter

The EverMemBench adapter reads only `dialogue.json`. It maps topic, day, group, speaker, message index, text, and
visible timestamps to the normalized input contract. It does not read `qa_*.json`, answers, options, task labels, or
gold evidence during graph construction.

Source-provided project, group, and person structure may become Scope nodes through deterministic adapter mapping.
LLM-derived task-object Scopes are not part of the common v2 contract.

## 5. Common Graph Contract

The unified graph uses these node types:

- `Episode/Event`
- `Claim`
- `StateFacet`
- `Entity/Scope`
- `Time`

The unified graph uses these edge types:

- `MENTIONS`
- `IN_SCOPE`
- `ASSERTS`
- `OCCURRED_AT`
- `HAS_TIME`
- `CORRECTS`
- `SUPERSEDES`
- `CONFLICTS_WITH`
- `SUPPORTS`
- `CURRENT_AFTER`
- `CURRENT_STATE_OF`

`RESPONSIBLE_FOR` is removed. Task-object Scope creation and task-object-specific StateFacet links are removed.

Every active StateFacet has one `primary_claim_id`, one or more `support_claim_ids`, matching support Events, a stable
owner identity, a stable state dimension, and a valid `CURRENT_AFTER` Time. Compatible repeated Claims remain
provenance. Superseded or corrected Claims remain in history through explicit relations instead of being erased.

## 6. EverMemBench v6 Deletion

Delete the following behavior rather than retaining flags or compatibility readers:

- `evermembench-sts-topic-graph-v6-endpoint-lifecycle` schema production and acceptance;
- event endpoint lifecycle Claim synthesis;
- task-object extraction, task-object Scope materialization, and task-object retrieval policies;
- `RESPONSIBLE_FOR` creation and traversal;
- v6-specific enrichment entrypoints and helpers;
- v6-specific summary and trace fields;
- v6 graph-directory defaults and README commands.

Delete the existing `Graph/output/graph/evermembench_topic_graph_llm_v6_endpoint_lifecycle/01..05` artifacts, QA
results produced from those graphs, and caches whose identity is tied only to that v6 schema. Deletion is limited by
manifest, path, and recorded graph-directory references so unrelated benchmark results are preserved.

## 7. Retrieval Boundary

EverMemBench keeps one STS retrieval chain for every question type:

1. normalize a question-only semantic frame;
2. retrieve Scope candidates;
3. retrieve and Time-rerank Event candidates inside the routed Scopes;
4. expand `Event -> Claim -> StateFacet` plus closed Claim relations;
5. enforce proof closure and fixed context budgets;
6. pass the resulting evidence to EverMemBench answer and judge logic.

StateFacet is reached through Event and Claim graph expansion; it is not an independent retrieval lane. Retrieval does
not inspect task labels, answers, options, or gold evidence. EverMemBench-specific final answer parsing and judging
remain outside the shared graph core.

## 8. Error Handling and Writes

- Invalid Claim or merge output fails the affected build stage with a precise error; it does not silently fall back to
  v6 heuristics.
- A graph is written only after schema and graph invariants pass.
- Output writes are atomic and refuse incompatible manifests.
- Cache identity includes the shared schema version, model, prompt contract, and normalized build configuration.
- Missing or malformed source timestamps remain explicit; they are not invented from QA data.

## 9. Verification

All Python verification uses the `py311` conda environment and the exact command prefix:

```bash
conda run --no-capture-output -n py311 ...
```

Verification includes:

1. unit tests for shared Claim folding, StateFacet materialization, relation closure, Time normalization, validation,
   manifest leakage fields, and atomic writes;
2. adapter tests proving LoCoMo QA fields and EverMemBench `qa_*.json` are not consumed during graph construction;
3. contract tests proving both adapters produce the same shared schema and invariants;
4. regression tests proving no v6 schema, task-object, lifecycle fallback, or `RESPONSIBLE_FOR` path remains callable;
5. `py_compile` or `compileall` for all changed modules through `py311`;
6. an EverMemBench topic-01 bounded smoke build through `py311`;
7. a bounded topic-01 QA smoke confirming every row uses the unified STS graph path and produces a complete trace;
8. filesystem checks confirming v6 graphs, matching QA results, and v6-only caches were deleted.

The full topic 01-05 rebuild is a separate expensive execution step after the bounded smoke passes. It must use the
same frozen construction configuration for every topic.

## 10. Completion Criteria

The migration is complete when:

- LoCoMo and EverMemBench both call the shared STS v2 core;
- EverMemBench no longer contains a v6 builder or compatibility reader;
- the common schema and graph invariants pass for both adapters;
- EverMemBench construction remains dialogue-only with explicit leakage proof;
- topic-01 construction and QA smoke tests pass under conda `py311`;
- old v6 graphs, matching QA results, and v6-only caches are absent;
- README commands point only to the unified v2 path;
- replaced EverMemBench code is deleted in the same change rather than left as dead code.

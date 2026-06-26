# Task-Semantics Local Graph

## Method

This method is a local graph layer for the current LongMemEval-S pipeline.

It does **not** replace the main pipeline and does **not** connect to Neo4j.
The intended boundary is:

```text
BM25 top-20 sessions
  -> build an in-memory task-semantics graph
  -> retrieve a State_packet from graph topology
  -> pass State_packet to the existing answer stage
```

The implementation uses an in-memory `networkx.MultiDiGraph`.

The intended benchmark path is **LLM-backed graph construction**:

```text
BM25 top-20 sessions
  -> LLM batch extraction of Claims / State Facets / claim relations
  -> in-memory graph assembly
  -> topology-driven State_packet retrieval
```

The repository also keeps a deterministic heuristic fallback for no-API sanity
checks. That fallback is not a meaningful scoring baseline; it only verifies
that the method interface and graph retriever can run.

## Graph Schema

Node types:

- `Episode/Event`: original turn-level evidence with `session_id`, `role`, text,
  date, and chronological order.
- `Claim`: atomic statement extracted from an Event.
- `State Facet`: task-level state item with `name` and `value`.
- `Entity/Scope`: entity or task scope node. The node carries `subtype=entity`
  or `subtype=scope`.
- `Time`: explicit time node used by `facet_current_after_time`.

Directed edge types:

- `event_mentions_entity`: `(Event) -> (Entity)`
- `event_in_scope`: `(Event) -> (Scope)`
- `claim_supported_by_event`: `(Claim) -> (Event)`
- `claim_corrects_claim`: `(new Claim) -> (old Claim)`
- `claim_supersedes_claim`: `(new Claim) -> (old Claim)`
- `claim_conflicts_with_claim`: `(Claim A) -> (Claim B)`
- `facet_supported_by_claim`: `(State Facet) -> (Claim)`
- `facet_current_after_time`: `(State Facet) -> (Time)`

## Retrieval

The retriever does not use blind k-hop expansion. It follows the State_packet
contract:

1. Lock the latest `Time` node and collect active `State Facet` nodes through
   `facet_current_after_time`.
2. Follow each facet to active Claims through `facet_supported_by_claim`.
3. Recover rejected historical Claims through `claim_supersedes_claim`,
   `claim_corrects_claim`, and `claim_conflicts_with_claim`.
4. Recover original evidence Events through `claim_supported_by_event`.
5. Return a State_packet-compatible JSON object.

## Run A Local Sanity Check

This is not a benchmark run and does not call an LLM. It only verifies that the
local graph path can build a graph and emit a State_packet:

```bash
python -m longmemeval_s_graph_retrieval.task_semantics_local_graph.demo
```

## Intended LLM Construction Entry

Use an existing project `LLMClient` or any object implementing
`complete_json(system_prompt, user_prompt)`:

```python
from longmemeval_s_graph_retrieval.task_semantics_local_graph import build_state_packet_with_llm_client

state_packet = build_state_packet_with_llm_client(
    sessions=bm25_top_20_sessions,
    question=row.question,
    question_type=row.question_type,
    question_date=row.question_date,
    llm_client=construction_client,
)
```

Recommended experiment setting for the next benchmark pass:

```text
Construction model: gpt-4o-mini
Reader model: gpt-4o-mini
Judge model: gpt-4o-2024-08-06
```

## LongMemEval-S Runner

Dry-run without API calls:

```bash
python -m longmemeval_s_graph_retrieval.task_semantics_local_graph.run_longmemeval \
  --limit-per-type 1 \
  --dry-run
```

60-case run, matching the current official comparison setting:

```bash
python -m longmemeval_s_graph_retrieval.task_semantics_local_graph.run_longmemeval \
  --limit-per-type 10 \
  --construction-provider openai \
  --construction-model gpt-4o-mini \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --judge \
  --judge-provider openai \
  --judge-model gpt-4o-2024-08-06 \
  --output longmemeval_s_graph_retrieval/task_semantics_local_graph/outputs/results_60_4omini_graph.json
```

## Output Area

Benchmark results for this method should be stored under:

```text
outputs/
```

Do not write prototype benchmark outputs into the main
`stamb_state_benchmark/output/` directory unless a result is promoted to a
documented canonical snapshot.

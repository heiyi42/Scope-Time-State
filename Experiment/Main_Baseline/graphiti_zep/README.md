# Graphiti / Zep Baseline

Status: fair main-table real-system adapter, not a full paper reproduction.

The runner uses Graphiti's bulk episode ingestion in small batches. This avoids the very slow
one-episode-at-a-time path and prints progress for each ingest batch.

This baseline adapts the public `graphiti-core` system to STAMB-State. It should be reported as a
Graphiti/Zep real-system baseline, not as a complete reproduction of the Zep/Graphiti paper. It now
uses Graphiti's advanced `search_()` path with the library's combined hybrid cross-encoder recipe,
which searches semantic edges, entity nodes, episode nodes, and community nodes. The stricter
paper-specific audit path, including message-style ingestion, n=4 previous-message context, BGE
embedding/reranking, and temporal/community conformance reports, lives under
`Experiment/Main_Baseline/graphiti_paper_reproduction/`.

If an earlier run was interrupted, use `--reset-benchmark-data` once before re-ingesting.
It deletes only STAMB benchmark episodes plus their benchmark-linked Graphiti edges and orphan
entities, rather than clearing the whole Neo4j database.

Official requirements:

- Python 3.10+
- `graphiti-core`
- Neo4j 5.26+ or FalkorDB 1.1.2+
- OpenAI-compatible LLM configuration

Target behavior:

- ingest each v1 raw benchmark event as a Graphiti episode;
- exclude annotation-only fields such as `status`, `corrects`, `supersedes`, and `state_relevant`
  from Graphiti episode payloads;
- query by `case.query` under the target `scope_id`;
- public End-to-End variants hide hidden `scope_id`, `time_role`, `output_slots`, gold states, and
  gold support, then free-generate `facets`, `evidence_events`, and `answer`;
- map Graphiti fact/episode UUIDs back to benchmark `event_id`;
- retrieve a larger Graphiti advanced-search candidate pool with BM25, cosine, BFS, and cross-encoder reranking;
- restrict returned Graphiti facts to edge UUIDs linked to the current run and target scope, avoiding leakage
  from older STAMB runs in the same Neo4j database;
- pass returned facts, entity summaries, and community summaries to the native Graphiti/Zep answer interface;
- filter returned facts to the case's target `scope_id`, then require `support_events` to come from those fact event IDs;
- convert returned graph facts/context into `evidence_events`, `state_slots`, `support_events`, and `answer`;
- evaluate with the same `sup_f1 / slot_j / ans_j` metrics.

Variants:

- `graphiti_zep`: real-system baseline. It answers from native Graphiti advanced-search facts plus
  entity/community summaries; support events must still come from returned fact event IDs.
- `graphiti_episode_context`: diagnostic enhanced baseline. It first uses Graphiti search to find facts,
  then maps those facts back to full benchmark episode payloads and gives those payloads to the same
  state extraction interface. This variant is not native Graphiti behavior; it diagnoses whether the
  native fact-only output loses task-relevant event metadata.
- `graphiti_global_public`: public End-to-End real-system baseline. It searches the current Graphiti
  run globally, constrained only to this run's Graphiti edges, and does not receive hidden scope or
  output slots.
- `graphiti_scope_routed_public`: stronger public End-to-End adaptation. It first routes scope from
  public `scope_profiles.json`, then searches only the routed scope's Graphiti edges; readout still
  free-generates facets without hidden output slots.

Run after installing dependencies and starting Neo4j:

```bash
conda run -n py311 pip install graphiti-core

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password
export NEO4J_DATABASE=neo4j
export OPENAI_EMBEDDING_BASE_URL=https://api.openai.com/v1
export OPENAI_EMBEDDING_MODEL=text-embedding-3-small
export OPENAI_EMBEDDING_DIM=1024

conda run -n py311 python Experiment/Main_Baseline/graphiti_zep/run_graphiti_baseline.py \
  --variant graphiti_zep \
  --provider deepseek \
  --graphiti-provider deepseek \
  --judge \
  --judge-provider openai \
  --reset-benchmark-data \
  --search-pool-limit 80 \
  --ingest-batch-size 8 \
  --ingest-timeout 600 \
  --output stamb_state_benchmark/output/results_graphiti_zep.json \
  --no-cache
```

`--embedder auto` and `--cross-encoder auto` are the defaults. They use BGE for `gpt-5*`
construction models and for `--graphiti-provider deepseek`, avoiding unstable OpenAI embedding and
`logprobs` / `logit_bias` reranker support. Use `--embedder openai` or `--cross-encoder openai`
only with endpoints that support those APIs.

Use `--graphiti-provider deepseek` when the OpenAI-compatible graph construction endpoint is
unavailable or returns authentication errors.

Run public End-to-End Graphiti smoke after data has been ingested, or with `--reset-run` to rebuild
one run:

```bash
conda run -n py311 python Experiment/Main_Baseline/graphiti_zep/run_graphiti_baseline.py \
  --variant graphiti_global_public \
  --data-version v1_1 \
  --provider deepseek \
  --graphiti-provider deepseek \
  --limit-cases 5 \
  --reset-run \
  --run-id stamb-graphiti-public-smoke \
  --search-pool-limit 80 \
  --output stamb_state_benchmark/output/results_graphiti_global_public_smoke.json

conda run -n py311 python Experiment/Main_Baseline/graphiti_zep/run_graphiti_baseline.py \
  --variant graphiti_scope_routed_public \
  --data-version v1_1 \
  --provider deepseek \
  --graphiti-provider deepseek \
  --limit-cases 5 \
  --skip-ingest \
  --run-id stamb-graphiti-public-smoke \
  --search-pool-limit 80 \
  --output stamb_state_benchmark/output/results_graphiti_scope_routed_public_smoke.json
```

Run the diagnostic Graphiti+Episode baseline after data has already been ingested:

```bash
conda run -n py311 python Experiment/Main_Baseline/graphiti_zep/run_graphiti_baseline.py \
  --variant graphiti_episode_context \
  --provider deepseek \
  --judge \
  --judge-provider openai \
  --run-id stamb-20260609033459 \
  --skip-ingest \
  --search-pool-limit 80 \
  --output stamb_state_benchmark/output/results_graphiti_episode_context.json
```

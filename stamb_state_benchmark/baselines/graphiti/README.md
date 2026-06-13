# Graphiti / Zep Baseline

Status: real-system baseline adapter scaffolded.

The runner uses Graphiti's bulk episode ingestion in small batches. This avoids the very slow
one-episode-at-a-time path and prints progress for each ingest batch.

If an earlier run was interrupted, use `--reset-benchmark-data` once before re-ingesting.
It deletes only STAMB benchmark episodes plus their benchmark-linked Graphiti edges and orphan
entities, rather than clearing the whole Neo4j database.

Official requirements:

- Python 3.10+
- `graphiti-core`
- Neo4j 5.26+ or FalkorDB 1.1.2+
- OpenAI-compatible LLM configuration

Target behavior:

- ingest each benchmark event as a Graphiti episode;
- query by `case.query` under the target `scope_id`;
- map Graphiti fact/episode UUIDs back to benchmark `event_id`;
- retrieve a larger Graphiti candidate pool, then filter returned facts to the case's target `scope_id`;
- convert returned graph facts/episodes into `evidence_events`, `state_slots`, `support_events`, and `answer`;
- evaluate with the same `sup_f1 / slot_j / ans_j` metrics.

Variants:

- `graphiti_zep`: real-system baseline. It answers only from the facts returned by native Graphiti search.
- `graphiti_episode_context`: diagnostic enhanced baseline. It first uses Graphiti search to find facts,
  then maps those facts back to full benchmark episode payloads and gives those payloads to the same
  state extraction interface. This variant is not native Graphiti behavior; it diagnoses whether the
  native fact-only output loses task-relevant event metadata.

Run after installing dependencies and starting Neo4j:

```bash
conda activate py311
pip install graphiti-core

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password
export NEO4J_DATABASE=neo4j
export OPENAI_EMBEDDING_BASE_URL=https://api.openai.com/v1
export OPENAI_EMBEDDING_MODEL=text-embedding-3-small
export OPENAI_EMBEDDING_DIM=1024

python stamb_state_benchmark/baselines/graphiti/run_graphiti_baseline.py \
  --variant graphiti_zep \
  --provider deepseek \
  --judge \
  --judge-provider openai \
  --reset-benchmark-data \
  --search-pool-limit 80 \
  --ingest-batch-size 8 \
  --ingest-timeout 600 \
  --output stamb_state_benchmark/output/results_graphiti_zep.json \
  --no-cache
```

Run the diagnostic Graphiti+Episode baseline after data has already been ingested:

```bash
python stamb_state_benchmark/baselines/graphiti/run_graphiti_baseline.py \
  --variant graphiti_episode_context \
  --provider deepseek \
  --judge \
  --judge-provider openai \
  --run-id stamb-20260609033459 \
  --skip-ingest \
  --search-pool-limit 80 \
  --output stamb_state_benchmark/output/results_graphiti_episode_context.json
```

# Graphiti / Zep Paper Reproduction Audit

Status: paper-structured reproduction and conformance audit for STAMB-State.

This runner is intentionally separate from `graphiti_zep`. The `graphiti_zep` runner is a
fair real-system adapter; this directory is for a closer Zep/Graphiti paper reproduction path.

Implemented paper-aligned pieces:

- sequential message-style episode ingestion;
- `previous_episode_uuids` window with default `n = 4`;
- `reference_time` on every episode for temporal extraction;
- dynamic community extension during ingestion is available with `--update-communities`, but disabled by
  default because the current `graphiti-core` release can fail in that path;
- a post-ingest community build for this run's `group_id`s, using Graphiti's lower-level community builder without
  clearing unrelated Graphiti communities;
- post-ingest community build is audited per scope group with bounded label propagation,
  `--community-label-max-iterations`, `--community-build-timeout`, and optional
  `--community-build-scope-limit`, so slow or failed community generation is reported instead of hanging the run;
- per-scope `group_id` so each STAMB stream behaves like a separate conversation/memory;
- explicit `Graphiti.search_` config over semantic edges, entity nodes, and community nodes;
- edge/node search methods: BM25, cosine similarity, breadth-first search;
- community search methods: BM25 and cosine similarity;
- default cross-encoder reranking;
- constructor-style context with facts and valid date ranges, entity summaries, and community summaries;
- top-level audit output for graph counts, temporal fields, community presence, search config, model config, and
  per-case returned facts/entities/communities.

STAMB adaptation choices:

- Input events come from `stamb_state_benchmark/data/v1/events_raw.json`.
- Annotation-only fields such as `status`, `corrects`, `supersedes`, and `state_relevant` are not ingested.
- Event IDs are kept in Graphiti source descriptions and mapped back from returned fact episode UUIDs for STAMB
  support-event evaluation.
- The query text is `case.query`; `scope_id` isolation is handled by Graphiti `group_id`, not by injecting gold labels.

Model fidelity:

- The paper used `gpt-4o-mini-2024-07-18` for graph construction and BGE-m3 family models for embedding/reranking.
- This runner defaults to `--embedder bge --cross-encoder bge`. That requires `sentence-transformers` and downloads
  `BAAI/bge-m3` / `BAAI/bge-reranker-v2-m3` on first use.
- Use `--embedder openai --cross-encoder openai` when local BGE dependencies or model downloads are unavailable.
  The audit output records this as a model deviation.

Run an audit-only smoke after installing dependencies and starting Neo4j:

```bash
conda run -n py311 pip install graphiti-core sentence-transformers

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password
export NEO4J_DATABASE=neo4j

export OPENAI_API_KEY=your_key
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini-2024-07-18

conda run -n py311 python Experiment/Main_Baseline/graphiti_paper_reproduction/run_graphiti_paper_audit.py \
  --audit-only \
  --limit-events 8 \
  --limit-cases 2 \
  --reset-run \
  --community-build-timeout 180 \
  --community-build-scope-limit 1 \
  --output stamb_state_benchmark/output/results_graphiti_paper_audit_smoke.json
```

To audit only the post-ingest community builder on an existing run:

```bash
conda run -n py311 python Experiment/Main_Baseline/graphiti_paper_reproduction/run_graphiti_paper_audit.py \
  --audit-only \
  --community-build-only \
  --skip-ingest \
  --run-id stamb-paper-smoke \
  --community-build-timeout 60 \
  --community-label-max-iterations 50 \
  --community-build-scope-limit 1 \
  --output stamb_state_benchmark/output/results_graphiti_paper_audit_communities.json
```

Run the full evaluated baseline:

```bash
conda run -n py311 python Experiment/Main_Baseline/graphiti_paper_reproduction/run_graphiti_paper_audit.py \
  --provider deepseek \
  --judge \
  --judge-provider openai \
  --reset-benchmark-data \
  --community-build-timeout 180 \
  --output stamb_state_benchmark/output/results_graphiti_paper_reproduction.json \
  --no-cache
```

If BGE dependencies or model downloads are unavailable:

```bash
conda run -n py311 python Experiment/Main_Baseline/graphiti_paper_reproduction/run_graphiti_paper_audit.py \
  --embedder openai \
  --cross-encoder openai \
  --audit-only \
  --limit-events 8 \
  --limit-cases 2 \
  --reset-run
```

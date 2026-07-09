# EverMemBench Server Todo

Goal: run the full local/self-host baseline matrix without learning each
database manually.

Important: "black-box" only means the storage processes are started by the
official service stack. It does not mean accepting hidden/default model
settings. A service baseline is fair only after its LLM and embedding settings
are explicitly pinned to the shared experiment settings below.

## First Question

On the server, run:

```bash
docker --version
docker compose version
```

If both commands work, use the official Docker/Compose setup in
`Baseline/SERVICE_SETUP.md`.

If Docker is not available, ask the lab/admin for one of these:

```text
preferred: Docker Compose access
fallback: managed Postgres+pgvector, Redis, Qdrant, and Neo4j endpoints
```

Without one of those, only `ours_scope_time_state`, `llm`, and possibly
`graphiti_local` can be smoked. The full four service baselines cannot run from
only one Neo4j URI.

## Decision Tree

### Case A: Docker Compose Works

This is the recommended path.

Do not manually install Postgres, Redis, Qdrant, or Neo4j. Use each official
service's compose file as described in `Baseline/SERVICE_SETUP.md`.

```text
Mem0 official stack     starts API + Postgres/pgvector + dashboard
MemOS official stack    starts API + Neo4j + Qdrant
Memobase official stack starts API + Postgres + Redis
Graphiti stack          starts Neo4j
```

After each service starts, pin its LLM and embedding settings. The storage is
black-box; the model configuration is not black-box.

### Case B: Docker Compose Is Not Available

Do not spend the lab slot trying to hand-install every database.

Ask the lab/admin/senior student for these managed endpoints:

```text
Postgres with pgvector enabled
Redis
Qdrant
Neo4j 5.26+
```

Then wire those endpoints into the official service configs. This is more
error-prone than Docker Compose and should be treated as the fallback.

### Case C: Only One Neo4j URI Is Available

You cannot run the full service-baseline matrix.

You can run:

```text
ours_scope_time_state
llm
graphiti_local, if the Neo4j URI is reachable and credentials work
```

You cannot fairly run:

```text
mem0_local, because it needs Postgres + pgvector
memos_local, because it still needs Qdrant even if Neo4j exists
memobase, because it needs Postgres + Redis
```

Use this case only for a partial smoke, not the final baseline table.

## Why Neo4j Alone Is Not Enough

```text
mem0_local      needs Postgres + pgvector
memos_local     needs Neo4j + Qdrant
memobase        needs Postgres + Redis
graphiti_local  needs Neo4j
```

Treat these as black-box storage dependencies. You do not need to operate the
databases manually; the official services do that after startup. The LLM and
embedding configuration must still be controlled explicitly.

## Base Environment

Put these in the project root `.env` file. The readiness script and
`run_official_baselines.sh` load it automatically. You can still override any
value in the shell before running a command.

```bash
LOCAL_API_BASE=http://127.0.0.1:8000/v1
LOCAL_API_KEY=local
LOCAL_MODEL=your-30b-model-name

LLM_BASE_URL=$LOCAL_API_BASE
LLM_API_KEY=$LOCAL_API_KEY
LLM_ANSWER_MODEL=$LOCAL_MODEL
LLM_JUDGE_MODEL=$LOCAL_MODEL

OPENAI_API_KEY=your-openai-key
OPENAI_EMBEDDING_API_KEY=$OPENAI_API_KEY
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIM=1536

LLM_ANSWER_CONCURRENCY=1
LLM_JUDGE_CONCURRENCY=2
EVERMEMBENCH_SEARCH_CONCURRENCY=2
EVERMEMBENCH_CLAIM_WORKERS=2
EVERMEMBENCH_RESOLVER_WORKERS=2
EVERMEMBENCH_ANSWER_WORKERS=2
EVERMEMBENCH_JUDGE_WORKERS=2

NO_PROXY=localhost,127.0.0.1,::1
no_proxy=$NO_PROXY
```

## Model Pinning Per Service

Every service must be configured to use:

```text
LLM:       $LOCAL_API_BASE + $LOCAL_MODEL
Embedding: OpenAI text-embedding-3-small, dim=1536
```

Concrete knobs:

```text
mem0_local:
  POST /configure
  llm.provider=openai
  llm.config.openai_base_url=$LOCAL_API_BASE
  llm.config.model=$LOCAL_MODEL
  embedder.provider=openai
  embedder.config.openai_base_url=https://api.openai.com/v1
  embedder.config.model=text-embedding-3-small
  embedder.config.embedding_dims=1536

memos_local:
  OPENAI_API_BASE=$LOCAL_API_BASE
  MOS_CHAT_MODEL=$LOCAL_MODEL
  MOS_CHAT_MODEL_PROVIDER=openai
  MOS_EMBEDDER_API_BASE=https://api.openai.com/v1
  MOS_EMBEDDER_MODEL=text-embedding-3-small
  EMBEDDING_DIMENSION=1536

memobase:
  api/config.yaml:
    llm_base_url=$LOCAL_API_BASE
    best_llm_model=$LOCAL_MODEL
    embedding_base_url=https://api.openai.com/v1
    embedding_model=text-embedding-3-small
    embedding_dim=1536

graphiti_local:
  GRAPHITI_LLM_BASE_URL=$LOCAL_API_BASE
  GRAPHITI_LLM_MODEL=$LOCAL_MODEL
  GRAPHITI_EMBEDDING_BASE_URL=https://api.openai.com/v1
  GRAPHITI_EMBEDDING_MODEL=text-embedding-3-small
  GRAPHITI_EMBEDDING_DIM=1536
```

If a service is running but these pins are not verifiable, do not include that
run in the fair baseline table.

## Message To Send If Docker Is Missing

```text
I need to run EverMemBench service baselines. The official self-host baselines
need Docker Compose or equivalent managed services:

- Mem0: Postgres with pgvector
- MemOS: Neo4j 5.26+ and Qdrant
- Memobase: Postgres and Redis
- Graphiti: Neo4j 5.26+

Can I get Docker Compose access on the server, or managed endpoints for these
services? I will pin all LLM calls to our local OpenAI-compatible model server
and all embeddings to OpenAI text-embedding-3-small, 1536 dimensions.
```

## Readiness Gate

Run this before spending time on a full experiment:

```bash
python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --check-llm
```

Do not start the full service-baseline experiment until every required item
passes.

## Minimal Smoke Order

1. Start the local 30B OpenAI-compatible LLM server.
2. Export the base environment above.
3. Run `run_evermembench_service_readiness.py --check-llm`.
4. Run the STS graph build and QA smoke.
5. Start the four official service baselines from `Baseline/SERVICE_SETUP.md`.
6. Re-run readiness.
7. Run:

```bash
EVERMEMBENCH_SMOKE=1 \
EVERMEMBENCH_SMOKE_DAYS=1 \
EVERMEMBENCH_QA_LIMIT=1 \
EVERMEMBENCH_TOPICS="01" \
EVERMEMBENCH_SYSTEMS="llm mem0_local memobase graphiti_local memos_local" \
EVERMEMBENCH_STAGES="add search answer evaluate" \
bash Experiment/Other_BenchMark/EverMemBench/run_official_baselines.sh
```

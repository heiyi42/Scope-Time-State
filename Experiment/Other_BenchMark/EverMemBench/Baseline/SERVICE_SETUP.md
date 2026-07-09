# EverMemBench Local Baseline Services

Checked against the official GitHub repositories on 2026-07-09:

- Mem0: https://github.com/mem0ai/mem0/tree/main/server
- MemOS: https://github.com/MemTensor/MemOS
- Memobase: https://github.com/memodb-io/memobase/tree/main/src/server
- Graphiti: https://github.com/getzep/graphiti

Runnable fair baseline matrix:

```text
llm mem0_local memobase graphiti_local memos_local
```

Do not use hosted/cloud memory services for this matrix. The memory systems
must be local or self-hosted. The only external API in the fair setup is
OpenAI `text-embedding-3-small`, pinned to 1536 dimensions.

## Shared Settings

Set the local OpenAI-compatible LLM endpoint and the OpenAI embedding endpoint:

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
```

These can live in the project root `.env`; `run_official_baselines.sh` and the
readiness checker load that file automatically.

For one local model server, start conservatively:

```bash
export LLM_ANSWER_CONCURRENCY=1
export LLM_JUDGE_CONCURRENCY=2
export EVERMEMBENCH_SEARCH_CONCURRENCY=2
```

Keep LLM and embedding base URLs separate inside every service. Do not point a
service-wide embedding client at the local LLM endpoint.

The service process can be treated as official infrastructure, but the model
configuration cannot be hidden. A baseline run is fair only if each service is
explicitly configured to use `$LOCAL_API_BASE/$LOCAL_MODEL` for LLM calls and
OpenAI `text-embedding-3-small` with 1536 dimensions for embeddings.

## Docker Is Optional, Storage Is Not

Docker Compose is the recommended path because it starts the official service
and its storage dependencies together. It is not conceptually required.

The required storage comes from each baseline's official architecture:

```text
mem0_local      -> Postgres + pgvector
memos_local     -> Neo4j + Qdrant
memobase        -> Postgres + Redis
graphiti_local  -> Neo4j
```

A single Neo4j URI is therefore not enough to run all four service baselines.
It can only cover `graphiti_local`, and part of `memos_local`; MemOS still
needs Qdrant for vector retrieval. Mem0 and Memobase do not use Neo4j as their
main memory store.

For paper-facing runs, use isolated local/self-host storage per baseline or
reset the backing stores between runs. Sharing one cloud Neo4j database across
baselines is acceptable only for a quick developer smoke if you use unique
run/user IDs and clean the graph afterward; it is not the recommended fair main
experiment setup.

## mem0_local

Official source: https://github.com/mem0ai/mem0/tree/main/server

The adapter calls the official self-host REST API:

```text
POST /memories
POST /search
```

Start the official server:

```bash
git clone https://github.com/mem0ai/mem0.git
cd mem0/server
cp .env.example .env
```

Edit `.env`:

```bash
POSTGRES_PASSWORD=choose-a-password
JWT_SECRET=choose-a-long-random-secret
OPENAI_API_KEY=placeholder-or-openai-key
MEM0_DEFAULT_LLM_MODEL=your-30b-model-name
MEM0_DEFAULT_EMBEDDER_MODEL=text-embedding-3-small
```

Then run:

```bash
make bootstrap
```

Official ports:

```text
Dashboard: http://localhost:3000
API:       http://localhost:8888
Docs:      http://localhost:8888/docs
```

Mem0's self-host image only bundles provider names `openai`, `anthropic`, and
`gemini` for LLMs, and `openai` and `gemini` for embedders. That is still
compatible with a local OpenAI-compatible LLM if it is configured as the
`openai` provider with `openai_base_url`.

After bootstrap, configure LLM and embedding separately:

```bash
curl -X POST http://localhost:8888/configure \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MEM0_LOCAL_API_KEY" \
  -d '{
    "llm": {
      "provider": "openai",
      "config": {
        "api_key": "'"$LOCAL_API_KEY"'",
        "model": "'"$LOCAL_MODEL"'",
        "openai_base_url": "'"$LOCAL_API_BASE"'",
        "temperature": 0.1,
        "max_tokens": 2000
      }
    },
    "embedder": {
      "provider": "openai",
      "config": {
        "api_key": "'"$OPENAI_API_KEY"'",
        "model": "text-embedding-3-small",
        "embedding_dims": 1536,
        "openai_base_url": "https://api.openai.com/v1"
      }
    }
  }'
```

Benchmark env:

```bash
export MEM0_LOCAL_BASE_URL=http://localhost:8888
export MEM0_LOCAL_API_KEY=the-api-key-printed-by-make-bootstrap
```

For throwaway local smoke only, `AUTH_DISABLED=true` can avoid API-key setup,
but do not use that on a shared server.

## memos_local

Official source: https://github.com/MemTensor/MemOS

The adapter calls the official REST API:

```text
POST /product/add
POST /product/search
```

MemOS supports OpenAI, Azure OpenAI, Qwen, DeepSeek, MiniMax, Ollama,
HuggingFace, and vLLM. For this benchmark, use its OpenAI-compatible settings
for the local LLM and OpenAI settings for embeddings.

Prepare:

```bash
git clone https://github.com/MemTensor/MemOS.git
cd MemOS
cp docker/.env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=$LOCAL_API_KEY
OPENAI_API_BASE=$LOCAL_API_BASE
MOS_CHAT_MODEL=$LOCAL_MODEL
MOS_CHAT_MODEL_PROVIDER=openai

MEMRADER_API_KEY=$LOCAL_API_KEY
MEMRADER_API_BASE=$LOCAL_API_BASE
MEMRADER_MODEL=$LOCAL_MODEL

MOS_EMBEDDER_BACKEND=universal_api
MOS_EMBEDDER_PROVIDER=openai
MOS_EMBEDDER_API_KEY=$OPENAI_API_KEY
MOS_EMBEDDER_API_BASE=https://api.openai.com/v1
MOS_EMBEDDER_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=12345678
DEFAULT_USE_REDIS_QUEUE=false
```

Docker launch:

```bash
cd docker
docker compose up -d
```

Official Docker examples use port `8000`:

```bash
export MEMOS_LOCAL_BASE_URL=http://localhost:8000
export MEMOS_LOCAL_API_KEY=
```

The direct uvicorn path defaults to port `8001` and requires Neo4j plus Qdrant
to already be running:

```bash
cd src
uvicorn memos.api.server_api:app --host 0.0.0.0 --port 8001 --workers 1
export MEMOS_LOCAL_BASE_URL=http://localhost:8001
```

## memobase

Official source: https://github.com/memodb-io/memobase/tree/main/src/server

The adapter uses the official Python SDK and expects a project URL and token:

```bash
export MEMOBASE_BASE_URL=http://localhost:8019
export MEMOBASE_API_TOKEN=secret
```

Start the official server:

```bash
git clone https://github.com/memodb-io/memobase.git
cd memobase/src/server
cp .env.example .env
cp ./api/config.yaml.example ./api/config.yaml
```

Edit `.env`:

```bash
API_EXPORT_PORT=8019
PROJECT_ID=memobase_dev
ACCESS_TOKEN=secret
```

Edit `api/config.yaml`:

```yaml
llm_api_key: local
llm_base_url: http://host.docker.internal:8000/v1
best_llm_model: your-30b-model-name

enable_event_embedding: true
embedding_provider: openai
embedding_api_key: your-openai-key
embedding_base_url: https://api.openai.com/v1
embedding_model: text-embedding-3-small
embedding_dim: 1536
```

Use `http://host.docker.internal:8000/v1` only when the local LLM endpoint runs
on the Docker host. If the LLM runs in another container or on another server,
use that reachable URL instead.

Launch:

```bash
docker compose build
docker compose up -d
```

## graphiti_local

Official source: https://github.com/getzep/graphiti

This adapter uses `graphiti-core` directly, not a Graphiti REST server. It only
needs a Neo4j 5.26+ database.

Start Neo4j using the official Graphiti compose file:

```bash
git clone https://github.com/getzep/graphiti.git
cd graphiti
docker compose up -d neo4j
```

Default official credentials:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
```

Adapter model settings:

```bash
export GRAPHITI_LLM_API_KEY=$LOCAL_API_KEY
export GRAPHITI_LLM_BASE_URL=$LOCAL_API_BASE
export GRAPHITI_LLM_MODEL=$LOCAL_MODEL
export GRAPHITI_STRUCTURED_OUTPUT_MODE=json_object

export GRAPHITI_EMBEDDING_API_KEY=$OPENAI_API_KEY
export GRAPHITI_EMBEDDING_BASE_URL=https://api.openai.com/v1
export GRAPHITI_EMBEDDING_MODEL=text-embedding-3-small
export GRAPHITI_EMBEDDING_DIM=1536
export SEMAPHORE_LIMIT=2
```

Graphiti explicitly supports OpenAI-compatible local LLM endpoints via
`OpenAIGenericClient`. Keep `SEMAPHORE_LIMIT` low for local models.

## Readiness Check

Run this before a full smoke:

```bash
python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --check-llm
```

Only run all service baselines after every readiness item passes.

## Official Baseline Smoke

```bash
EVERMEMBENCH_SMOKE=1 \
EVERMEMBENCH_SMOKE_DAYS=1 \
EVERMEMBENCH_QA_LIMIT=1 \
EVERMEMBENCH_TOPICS="01" \
EVERMEMBENCH_SYSTEMS="llm mem0_local memobase graphiti_local memos_local" \
EVERMEMBENCH_STAGES="add search answer evaluate" \
bash Experiment/Other_BenchMark/EverMemBench/run_official_baselines.sh
```

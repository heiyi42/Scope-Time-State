# EverMemBench Server Commands

Replace these placeholders first:

```text
USER@SERVER                 your SSH target
/data/USER/EpisodicMemory   target project directory on the server
YOUR_30B_MODEL_NAME         model name exposed by the local OpenAI-compatible server
YOUR_OPENAI_KEY             OpenAI key for text-embedding-3-small
```

## 1. Upload Code And Data From Mac

Run on the Mac:

```bash
SERVER=USER@SERVER
REMOTE=/data/USER/EpisodicMemory

ssh "$SERVER" "mkdir -p '$REMOTE'"

rsync -az --info=progress2 \
  --exclude='.git/' \
  --exclude='.env' \
  --exclude='**/__pycache__/' \
  --exclude='Graph/output/' \
  --exclude='Experiment/Other_BenchMark/EverMemBench/log/' \
  /Users/mac/Desktop/EpisodicMemory/ \
  "$SERVER:$REMOTE/"
```

Do not upload old `Graph/output` artifacts if the server will rebuild from
graph construction to QA/judge.

## 2. Create Conda Environment On Server

Run on the server:

```bash
REMOTE=/data/USER/EpisodicMemory
cd "$REMOTE"

source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null || true

conda create -n py311 python=3.11 -y
conda activate py311

python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Write `.env` On Server

Run on the server:

```bash
cd /data/USER/EpisodicMemory

cat > .env <<'EOF'
LOCAL_API_BASE=http://127.0.0.1:8000/v1
LOCAL_API_KEY=local
LOCAL_MODEL=YOUR_30B_MODEL_NAME

LLM_BASE_URL=$LOCAL_API_BASE
LLM_API_KEY=$LOCAL_API_KEY
LLM_ANSWER_MODEL=$LOCAL_MODEL
LLM_JUDGE_MODEL=$LOCAL_MODEL

OPENAI_API_KEY=YOUR_OPENAI_KEY
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

MEM0_LOCAL_BASE_URL=http://localhost:8888
MEMOS_LOCAL_BASE_URL=http://localhost:8001
MEMOBASE_BASE_URL=http://localhost:8019
MEMOBASE_API_TOKEN=secret

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

GRAPHITI_LLM_API_KEY=$LOCAL_API_KEY
GRAPHITI_LLM_BASE_URL=$LOCAL_API_BASE
GRAPHITI_LLM_MODEL=$LOCAL_MODEL
GRAPHITI_STRUCTURED_OUTPUT_MODE=json_object
GRAPHITI_EMBEDDING_API_KEY=$OPENAI_API_KEY
GRAPHITI_EMBEDDING_BASE_URL=https://api.openai.com/v1
GRAPHITI_EMBEDDING_MODEL=text-embedding-3-small
GRAPHITI_EMBEDDING_DIM=1536
EOF

chmod 600 .env
```

If Graphiti uses a cloud Neo4j database, replace only `NEO4J_URI`,
`NEO4J_USER`, and `NEO4J_PASSWORD`.

## 4. Check Local LLM And Basic Readiness

Run on the server after starting the local OpenAI-compatible 30B model server:

```bash
cd /data/USER/EpisodicMemory
source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null || true
conda activate py311

python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --check-llm
```

At this point, model/env checks should pass. Service checks for Mem0, MemOS,
Memobase, and Graphiti pass only after their local/self-host services are up.

## 5. Smoke STS: Build Graph -> QA -> Judge

Run on the server:

```bash
cd /data/USER/EpisodicMemory
source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null || true
conda activate py311
set -a
source .env
set +a

RUN_TAG=server_smoke_$(date +%Y%m%d_%H%M%S)
CLAIM_WORKERS=${EVERMEMBENCH_CLAIM_WORKERS:-2}
RESOLVER_WORKERS=${EVERMEMBENCH_RESOLVER_WORKERS:-2}
ANSWER_WORKERS=${EVERMEMBENCH_ANSWER_WORKERS:-2}
JUDGE_WORKERS=${EVERMEMBENCH_JUDGE_WORKERS:-2}
mkdir -p "Graph/output/cache/$RUN_TAG" "Graph/output/results/evermembench/$RUN_TAG"

python Experiment/Other_BenchMark/EverMemBench/run_evermembench_graph_builder.py \
  --topic 01 \
  --output-dir "Graph/output/graph/$RUN_TAG" \
  --claim-mode llm \
  --resolver-mode llm \
  --provider local \
  --model "$LOCAL_MODEL" \
  --cache "Graph/output/cache/$RUN_TAG/llm_cache.graph.json" \
  --message-chunk-size 4 \
  --claim-workers "$CLAIM_WORKERS" \
  --resolver-workers "$RESOLVER_WORKERS" \
  --llm-event-filter stateful \
  --max-claims-per-event 1 \
  --resolver-bucket-limit 1 \
  --event-limit 8

python Experiment/Other_BenchMark/EverMemBench/run_evermembench_qa_eval.py \
  --topic 01 \
  --graph-dir "Graph/output/graph/$RUN_TAG/01" \
  --limit-per-task 1 \
  --task-prefixes F_SH \
  --embedding-retrieval hybrid \
  --embedding-targets event,scope \
  --embedding-model text-embedding-3-small \
  --embedding-cache "Graph/output/cache/$RUN_TAG/embedding_cache.qa_event_scope.json" \
  --answer-provider local \
  --answer-model "$LOCAL_MODEL" \
  --judge-provider local \
  --judge-model "$LOCAL_MODEL" \
  --answer-workers "$ANSWER_WORKERS" \
  --judge-workers "$JUDGE_WORKERS" \
  --output "Graph/output/results/evermembench/$RUN_TAG/sts_topic01_F_SH_1.qa_judge.json" \
  --answer-cache "Graph/output/cache/$RUN_TAG/answer_cache.json" \
  --judge-cache "Graph/output/cache/$RUN_TAG/judge_cache.json"
```

## 6. Start Official Service Baselines

If Docker Compose is available, start the official services by following:

```bash
less Experiment/Other_BenchMark/EverMemBench/Baseline/SERVICE_SETUP.md
```

Then re-run:

```bash
python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --check-llm
```

Do not run the full service-baseline experiment until the relevant service
checks pass.

## 7. Smoke Official Baselines

Run on the server after service readiness passes:

```bash
cd /data/USER/EpisodicMemory
source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null || true
conda activate py311

RUN_TAG=official_smoke_$(date +%Y%m%d_%H%M%S)

CONDA_ENV=py311 \
EVERMEMBENCH_RUN_ID="$RUN_TAG" \
EVERMEMBENCH_OUTPUT_DIR="$PWD/Graph/output/results/evermembench/$RUN_TAG/official_baselines" \
EVERMEMBENCH_SMOKE=1 \
EVERMEMBENCH_SMOKE_DAYS=1 \
EVERMEMBENCH_QA_LIMIT=1 \
EVERMEMBENCH_TOPICS="01" \
EVERMEMBENCH_SYSTEMS="llm mem0_local memobase graphiti_local memos_local" \
EVERMEMBENCH_STAGES="add search answer evaluate" \
bash Experiment/Other_BenchMark/EverMemBench/run_official_baselines.sh
```

## 8. Start Full STS Experiment

Run after the smoke succeeds:

```bash
cd /data/USER/EpisodicMemory
source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null || true
conda activate py311
set -a
source .env
set +a

RUN_TAG=server_full_$(date +%Y%m%d_%H%M%S)
CLAIM_WORKERS=${EVERMEMBENCH_CLAIM_WORKERS:-2}
RESOLVER_WORKERS=${EVERMEMBENCH_RESOLVER_WORKERS:-2}
ANSWER_WORKERS=${EVERMEMBENCH_ANSWER_WORKERS:-2}
JUDGE_WORKERS=${EVERMEMBENCH_JUDGE_WORKERS:-2}
mkdir -p "Graph/output/cache/$RUN_TAG" "Graph/output/results/evermembench/$RUN_TAG"

for topic in 01 02 03 04 05; do
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_graph_builder.py \
    --topic "$topic" \
    --output-dir "Graph/output/graph/$RUN_TAG" \
    --claim-mode llm \
    --resolver-mode llm \
    --provider local \
    --model "$LOCAL_MODEL" \
    --cache "Graph/output/cache/$RUN_TAG/llm_cache.graph.json" \
    --message-chunk-size 4 \
    --claim-workers "$CLAIM_WORKERS" \
    --resolver-workers "$RESOLVER_WORKERS" \
    --llm-event-filter stateful \
    --max-claims-per-event 1 \
    --resolver-bucket-limit 0 \
    --event-limit 0
done

for topic in 01 02 03 04 05; do
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_qa_eval.py \
    --topic "$topic" \
    --graph-dir "Graph/output/graph/$RUN_TAG/$topic" \
    --limit-per-task 0 \
    --embedding-retrieval hybrid \
    --embedding-targets event,scope \
    --embedding-model text-embedding-3-small \
    --embedding-cache "Graph/output/cache/$RUN_TAG/embedding_cache.qa_event_scope.json" \
    --answer-provider local \
    --answer-model "$LOCAL_MODEL" \
    --judge-provider local \
    --judge-model "$LOCAL_MODEL" \
    --answer-workers "$ANSWER_WORKERS" \
    --judge-workers "$JUDGE_WORKERS" \
    --output "Graph/output/results/evermembench/$RUN_TAG/sts_topic${topic}_all.qa_judge.json" \
    --answer-cache "Graph/output/cache/$RUN_TAG/answer_cache.json" \
    --judge-cache "Graph/output/cache/$RUN_TAG/judge_cache.json"
done
```

## 9. Start Full Official Baseline Experiment

Run only after the official-baseline smoke succeeds:

```bash
cd /data/USER/EpisodicMemory
source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null || true
conda activate py311

RUN_TAG=official_full_$(date +%Y%m%d_%H%M%S)

CONDA_ENV=py311 \
EVERMEMBENCH_RUN_ID="$RUN_TAG" \
EVERMEMBENCH_OUTPUT_DIR="$PWD/Graph/output/results/evermembench/$RUN_TAG/official_baselines" \
EVERMEMBENCH_TOPICS="01 02 03 04 05" \
EVERMEMBENCH_SYSTEMS="llm mem0_local memobase graphiti_local memos_local" \
EVERMEMBENCH_STAGES="add search answer evaluate" \
bash Experiment/Other_BenchMark/EverMemBench/run_official_baselines.sh
```

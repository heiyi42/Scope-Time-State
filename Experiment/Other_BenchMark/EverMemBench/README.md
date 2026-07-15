# EverMemBench

This directory keeps the EverMemBench experiment entrypoints, dataset mirror, and upstream source checkout.
Baseline implementation code lives under the benchmark-local `Baseline/` directory.
When running or modifying experiments, treat `Baseline/*` as the source of truth
for our implementations. The `source/EverMemBench/eval/src/adapters/*_local_adapter.py`
files are compatibility wrappers for the official `python -m eval.cli` entrypoint;
do not edit or delete them as if they were duplicate implementations.

## Layout

- `run_evermembench_graph_builder.py`: entrypoint for building the local Scope-Time-State topic graph.
- `run_evermembench_qa_eval.py`: entrypoint for running QA over a built topic graph.
- `run_evermembench_qa_probe.py`: entrypoint for retrieval/probe diagnostics.
- `run_evermembench_baseline_adapters.py`: entrypoint for inspecting local/self-host baseline adapters.
- `run_official_baselines.sh`: conda `py311` runner for the fair local/self-host baseline matrix.

- `Baseline/ours_scope_time_state/`: local EverMemBench Scope-Time-State implementation.
- `Baseline/embedding_rag/`: dense embedding retrieval over deterministic dialogue chunks.
- `Baseline/mem0_local/`: Mem0 open-source self-host REST adapter.
- `Baseline/memos_local/`: MemOS open-source local server adapter.
- `Baseline/memobase/`: Memobase self-host/local server adapter via the official SDK.
- `Baseline/graphiti_local/`: Graphiti open-source local adapter for the Zep-style graph baseline.
- `Baseline/common/official_eval/`: official-first import shim plus standalone fallback support files.
- `dataset/`: local EverMemBench-Dynamic data mirror.
- `source/EverMemBench/`: upstream EverMemBench repository checkout.

The local implementation reads dialogue data for graph construction and does not read QA/gold files during
graph build.

EverMemBench and LoCoMo now use the same `scope-time-state-graph-v2-state-merge`
schema and state-merge core. Graph construction is a single build path with no
benchmark-specific post-build enrichment stage.

The fair main-table baseline set is local/self-host only:

```text
embedding_rag mem0_local memobase memos_local graphiti_local
```

`embedding_rag` replaces the former full-context control. It builds deterministic
day-and-group-local chunks (2400 target characters with one-message overlap), embeds
them with `text-embedding-3-small`, retrieves the top 10 chunks per question, and
passes only those retrieved chunks to the shared answer prompt.

Hosted/cloud adapters such as `mem0`, `memos`, `zep`, and legacy `evermemos` are intentionally not part of the
default runnable matrix because their internal model, embedding, and retrieval settings cannot be held fixed.
The upstream EverMemBench eval checkout under `source/` is kept as a reference. The local adapter implementations
live in `Baseline/*`; the `source/EverMemBench/eval/src/adapters/*_local_adapter.py` files are only compatibility
wrappers so `python -m eval.cli` can still run the benchmark.

## Model Routing

- QA and judge are expected to use a local OpenAI-compatible LLM endpoint.
- The official eval pipeline defaults to `LLM_BASE_URL=http://127.0.0.1:8000/v1`,
  `LLM_ANSWER_MODEL=Qwen2.5-1.5B-Instruct`, and `LLM_JUDGE_MODEL=Qwen2.5-1.5B-Instruct`.
  Override these on the server for the deployed 30B model.
- Embeddings are not local by default. Use `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`
  and `OPENAI_EMBEDDING_DIM=1536`; Graphiti local defaults to the same model/dimension.
- Embedding RAG caches document and query vectors under
  `Graph/output/cache/evermembench_embedding_rag`; override it with
  `EVERMEMBENCH_EMBEDDING_RAG_CACHE`.
- For Mem0/MemOS/Memobase, embedding happens inside the local service when that
  service owns retrieval, so configure each service with the same embedding model/dimension.
- For the STS QA runner, use `--answer-provider local --judge-provider local` with
  `LOCAL_API_KEY`, `LOCAL_MODEL`, and `LOCAL_API_BASE` pointing at the local LLM endpoint.
- For a single local 30B model server, start with conservative concurrency:
  graph build `--claim-workers 1 --resolver-workers 1`, STS QA `--answer-workers 1 --judge-workers 2`,
  and official eval `LLM_ANSWER_CONCURRENCY=1 LLM_JUDGE_CONCURRENCY=2 EVERMEMBENCH_SEARCH_CONCURRENCY=2`.
  Increase only after a smoke run shows the local endpoint has enough throughput and memory headroom.
- Run logs are written to `Experiment/Other_BenchMark/EverMemBench/log` by default. Override with
  `EVERMEMBENCH_LOG_DIR=/path/to/logs`. STS graph build logs use `sts_ingest_graph_*`, STS QA/judge logs use
  `sts_qa_judge_*`, and official baseline logs use `official_<system>_topic<topic>_*`.

## Examples

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_graph_builder.py \
  --topic 01 \
  --claim-mode llm \
  --resolver-mode llm \
  --provider deepseek \
  --model deepseek-v4-flash \
  --output-dir Graph/output/graph/evermembench_topic_graph_v2_state_merge
```

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_qa_eval.py \
  --topic 01 \
  --graph-dir Graph/output/graph/evermembench_topic_graph_v2_state_merge/01 \
  --scope-routing sts \
  --graph-expansion sts \
  --time-role-selector llm \
  --temporal-grounding question-only \
  --embedding-retrieval hybrid \
  --embedding-targets event,scope
```

With `--temporal-grounding question-only` (the default), the unified STS QA path resolves relative
expressions from selected Event text and graph Claim time values against visible source timestamps after
graph expansion and before answer generation. It does not read task prefixes, question-type labels, answers,
or gold evidence. Use `--temporal-grounding none` only for the explicit ablation.

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_baseline_adapters.py \
  --list
```

```bash
EVERMEMBENCH_SMOKE=1 \
EVERMEMBENCH_QA_LIMIT=2 \
EVERMEMBENCH_SYSTEMS="embedding_rag mem0_local" \
bash Experiment/Other_BenchMark/EverMemBench/run_official_baselines.sh
```

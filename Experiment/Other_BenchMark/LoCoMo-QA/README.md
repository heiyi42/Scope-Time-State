# LoCoMo QA External Benchmark

This directory keeps the LoCoMo graph build separate from the STAMB-State benchmark contract.
The active LoCoMo path is graph-first: build one persistent graph per `sample_id`, then reuse that
graph for all questions from the same sample.

## Data

Official release:

- Project page: https://snap-research.github.io/locomo/
- Repository: https://github.com/snap-research/LoCoMo
- Data file: `data/locomo10.json`

Download:

```bash
mkdir -p Experiment/Other_BenchMark/LoCoMo-QA/data
curl -L --fail --show-error \
  --output Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  https://raw.githubusercontent.com/snap-research/LoCoMo/main/data/locomo10.json
```

The data file is intentionally ignored by git.

## Graph Build

The graph builder reads only `sample_id` and `conversation` fields. The LoCoMo release colocates
QA fields with the conversation in one JSON file, so the manifest records that `qa`, `answer`, and
`evidence` fields are ignored and not used for graph construction.

Build one sample with DeepSeek:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --resolver-mode llm \
  --message-chunk-size 16 \
  --claim-workers 4 \
  --resolver-workers 4 \
  --resolver-candidate-limit 24 \
  --max-claims-per-turn 2 \
  --output-dir Graph/output/graph/locomo_qa_sample_graph_v1 \
  --cache Graph/output/cache/llm_cache.locomo_qa_graph_builder.conv-26.deepseek_v4_flash.json
```

Output layout:

```text
Graph/output/graph/locomo_qa_sample_graph_v1/<sample_id>/
  manifest.json
  graph_summary.json
  nodes.jsonl
  edges.jsonl
```

## Graph QA

Run the `conv-26` questions against the graph using the EverMemBench-style staged retrieval variants:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_query.py \
  --sample-id conv-26 \
  --graph-dir Graph/output/graph/locomo_qa_sample_graph_v1/conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants graph_bm25 graph_embedding_event graph_embedding_scope_event \
  --question-types multi-hop open-domain \
  --limit-per-type 10 \
  --top-k 12 \
  --scope-top-k 8 \
  --scope-types speaker,entity,topic,session \
  --state-search-k 12 \
  --candidate-k 80 \
  --embedding-candidate-k 80 \
  --answer-workers 4 \
  --output Graph/output/result/results_locomo_qa_graph_conv26_staged_embedding.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_graph_query.conv-26.deepseek_v4_flash.json \
  --embedding-cache Graph/output/cache/embedding_cache.locomo_qa_graph_query.conv-26.text_embedding_3_small.json
```

Retrieval order is `scope routing -> scoped event retrieval -> state/graph expansion -> optional open-domain mapping -> answer -> official-style scoring`.
`multi-hop` questions use the same graph retrieval path as the other task types; there is no
task-specific second-hop expansion or question-decomposition logic.

The mapping layer is only applied to `open-domain` questions after graph retrieval. It converts
cited conversation facts into a short commonsense bridge and answer hint, without writing those
inferred facts back into the graph. Use `--disable-open-domain-mapping` for an ablation that
answers directly from retrieved graph evidence.

## Memory Baselines

The comparison table baselines are tracked separately from the graph runner:

Implementation code lives under `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/` in baseline-shaped
directories such as `full_context_llm/`, `hybrid_rag/`, `ours_scope_time_state/`, `tsm/`,
`memory_bank/`, `memoryos/`, and `graphiti_zep/`. The LoCoMo-QA root keeps experiment entrypoints only.

- `Full Text`: direct full-conversation context, no retrieval paper required.
- `Naive RAG`: BM25 over raw dialog turns, no retrieval paper required.
- `Zep`: paper already stored at `RelatedWork/ZEP.pdf`; the `zep` variant runs the official `getzep/graphiti` runtime in a subprocess and reuses the local Graphiti client/driver construction from `Experiment/Main_Baseline/graphiti_zep/`.
- `TSM`: paper already stored at `RelatedWork/TSM.pdf`; local STAMB reference implementation is under `Experiment/Main_Baseline/tsm/`.
- `A-MEM`: paper stored at `RelatedWork/A-MEM.pdf`; official repositories are `WujiangXu/AgenticMemory` for paper reproduction and `agiresearch/A-mem` for the memory system.
- `MemoryOS`: paper stored at `RelatedWork/MemoryOS.pdf`; the `memoryos` variant imports official source from `BAI-LAB/MemoryOS` (`memoryos-pypi.Memoryos`) and uses official short/mid/long-term memory plus `Retriever.retrieve_context`.
- `Mem0`: paper stored at `RelatedWork/Mem0.pdf`; the LoCoMo runner has an optional official-SDK variant using qdrant vector storage and BM25 sparse support through `fastembed`. Run it from the main `py311` pydantic-2 environment.
- `MemGPT`: paper stored at `RelatedWork/MemGPT.pdf`. The default `memgpt` variant is an official Letta adapter. It runs the official Letta Code CLI (`letta-ai/letta-code`, or an installed `@letta-ai/letta-code`) in headless JSON mode, first ingests the LoCoMo conversation into an official agent, then asks each question as a separate query.
- `MemoryBank`: paper stored at `RelatedWork/MemoryBank.pdf`; official repository is `zhongwanjun/MemoryBank-SiliconFriend`. The `memory_bank` variant runs an isolated worker in `locomo_memorybank`, where the official legacy stack (`langchain==0.0.146`, pydantic 1) can load `memory_retrieval/forget_memory.py` `LocalMemoryRetrieval` and FAISS without breaking the main `py311` environment.

The memory baseline runner builds memory only from `sample.conversation`. It does not expose gold
answers, gold evidence IDs, official categories, or question-type labels to retrieval/controller/answer
prompts. Evidence metrics are computed from model-emitted `evidence_dialog_ids`; missing citations
are not backfilled from retrieved candidates.

Run directly callable baselines:

```bash
env PYTHONDONTWRITEBYTECODE=1 LLM_PARSE_RETRIES=6 \
  conda run -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants full_text naive_rag \
  --question-types multi-hop open-domain \
  --top-k 24 \
  --answer-workers 2 \
  --output Graph/output/results/results_locomo_qa_memory_baselines_conv26_multi_open.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_memory_baselines.conv-26.deepseek_v4_flash.json
```

The `mem0` variant is optional because it first ingests the full sample conversation into the SDK memory
store with LLM-based extraction. It runs from the main `py311` pydantic-2 environment:

```bash
env PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false LLM_PARSE_RETRIES=6 \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants mem0 \
  --question-types multi-hop open-domain \
  --top-k 24 \
  --mem0-vector-store-provider qdrant \
  --mem0-add-retries 6 \
  --mem0-retry-sleep 60 \
  --answer-workers 2 \
  --output Graph/output/results/results_locomo_qa_mem0_conv26_multi_open.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_mem0.conv-26.deepseek_v4_flash.json
```

Prepare official repositories:

```bash
git clone --depth 1 https://github.com/letta-ai/letta-code.git /path/to/letta-code
cd /path/to/letta-code && bun install

git clone --depth 1 https://github.com/zhongwanjun/MemoryBank-SiliconFriend.git /path/to/MemoryBank-SiliconFriend

git clone --depth 1 https://github.com/BAI-LAB/MemoryOS.git /path/to/MemoryOS

git clone --depth 1 https://github.com/getzep/graphiti.git /path/to/graphiti
```

MemoryBank's official runtime should stay isolated because its upstream FAISS/langchain code pins the old
pydantic-1 stack. This checkout uses an already-created `locomo_memorybank` worker environment
(`pydantic==1.10.26`, `langchain==0.0.146`) and keeps `py311` on pydantic 2 for mem0, MemoryOS, and Zep.
For a fresh machine, create the MemoryBank worker env with the official legacy deps instead of cloning the
current pydantic-2 `py311` environment:

```bash
conda create -n locomo_memorybank python=3.11 -y
conda run -n locomo_memorybank python -m pip install \
  'pydantic<2' 'SQLAlchemy<2' 'tenacity<9' 'langchain==0.0.146' \
  faiss-cpu sentence-transformers openai tiktoken unstructured
conda run -n locomo_memorybank python -c "import sys; sys.path.insert(0, '/path/to/MemoryBank-SiliconFriend/memory_bank'); import memory_retrieval.forget_memory as fm; print(fm.LocalMemoryRetrieval)"
```

Run official-priority MemGPT, MemoryBank, and MemoryOS variants:

```bash
env PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false LLM_PARSE_RETRIES=6 \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants memgpt memory_bank memoryos \
  --question-types multi-hop open-domain \
  --top-k 24 \
  --letta-code-repo /path/to/letta-code \
  --letta-backend local \
  --letta-ingest-chunk-turns 10 \
  --letta-toolset auto \
  --letta-base-tools memory \
  --memory-bank-official-repo /path/to/MemoryBank-SiliconFriend \
  --memory-bank-conda-env locomo_memorybank \
  --memory-bank-embedding-model minilm-l6 \
  --memory-bank-embedding-device cpu \
  --memoryos-official-repo /path/to/MemoryOS \
  --memoryos-embedding-model all-MiniLM-L6-v2 \
  --answer-workers 2 \
  --output Graph/output/results/results_locomo_qa_memgpt_memorybank_memoryos_conv26_multi_open.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_memgpt_memorybank_memoryos.conv-26.deepseek_v4_flash.json
```

Run Zep/Graphiti after Neo4j is available and the main `py311` environment has pydantic 2:

```bash
env PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false LLM_PARSE_RETRIES=6 \
  NEO4J_URI=bolt://localhost:7687 \
  NEO4J_USER=neo4j \
  NEO4J_PASSWORD=your_password \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --variants zep \
  --question-types multi-hop open-domain \
  --top-k 24 \
  --zep-official-repo /path/to/graphiti \
  --zep-conda-env py311 \
  --zep-graphiti-provider deepseek \
  --zep-search-config combined_cross_encoder \
  --answer-workers 2 \
  --output Graph/output/results/results_locomo_qa_zep_conv26_multi_open.json \
  --cache Graph/output/cache/llm_cache.locomo_qa_zep.conv-26.deepseek_v4_flash.json
```

Use `--dry-run` to validate selection and CLI wiring without building memories or calling LLM/embedding APIs:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  conda run -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --variants memgpt memory_bank memoryos zep \
  --question-types temporal \
  --limit-cases 1 \
  --dry-run
```

## Schema

Node types:

- `Episode/Event`: raw dialog turns, keyed by LoCoMo dialog IDs such as `D1:3`.
- `Claim`: atomic memory claims extracted from dialog turns.
- `StateFacet`: graph-searchable fact facets supported by claims.
- `Entity/Scope`: sample, session, speaker, entity, and topic scopes.
- `Time`: session date-times and extracted claim time expressions.

Edge types:

- `MENTIONS`, `IN_SCOPE`
- `ASSERTS`, `SUPPORTS`
- `CORRECTS`, `SUPERSEDES`, `CONFLICTS_WITH`
- `OCCURRED_AT`, `HAS_TIME`, `CURRENT_AFTER`
- `CURRENT_STATE_OF`

The deprecated text-only task-adapter runner has been removed from the active LoCoMo path.

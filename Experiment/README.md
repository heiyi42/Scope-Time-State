# Experiment

`Experiment/` 保存实验入口、baseline adapter、共享 LLM 工具和外部 benchmark 的薄封装。当前实验主线已经转向持久化图记忆 pipeline，不再以旧的 standalone prompt benchmark 作为主要运行面。

## 当前实验流程

```text
benchmark-visible chronological memory source
  -> graph build / ingest
  -> persistent graph artifact
  -> Scope routing (BM25 ∪ embedding)
  -> scoped Event candidates (BM25 ∪ embedding)
  -> question-only Time-role selection
  -> Time-aware Event rerank
  -> StateFacet validity resolution and graph expansion
  -> deterministic temporal readout over selected graph evidence
  -> answer
  -> optional judge and summary
```

图构建阶段只读取 benchmark 允许作为记忆的原始来源：对话 benchmark 使用对话、消息或日志；EPBench 一类叙事 benchmark 使用合成长文本/小说的段落、章节或事件流。不读取 QA、答案、gold evidence 或问题类型标签。查询阶段复用已经构建好的图；缓存、图文件、日志和结果统一放在 `Graph/` 或对应 benchmark 的日志目录下。

## 目录和职责

### 共享实验工具

- `run/common/`：当前 benchmark 复用的 LLM client 与环境加载工具；
- `Other_BenchMark/`：当前 benchmark 的入口、数据镜像、服务说明和 adapter。

## 当前 benchmark 入口

### EverMemBench

目录：`Experiment/Other_BenchMark/EverMemBench/`

- `run_evermembench_graph_builder.py`：构建 topic-level Scope-Time-State graph；
- `run_evermembench_qa_eval.py`：在已构建的 graph 上运行检索、回答和 judge；
- `run_evermembench_qa_probe.py`：检查 scope、time、event 和 StateFacet 检索；
- `run_evermembench_enrich_topic_graph.py`：图 enrichment 工具；
- `run_evermembench_baseline_adapters.py`：查看可用 baseline adapter；
- `run_official_baselines.sh`：运行公平的本地/self-host baseline 矩阵。

当前默认公平集合是：

```text
llm mem0_local memobase graphiti_local memos_local
```

云端 hosted adapter 不进入默认公平矩阵。服务依赖、模型/embedding 固定和服务器运行顺序见 [`EverMemBench/README.md`](Other_BenchMark/EverMemBench/README.md)、[`SERVER_COMMANDS.md`](Other_BenchMark/EverMemBench/SERVER_COMMANDS.md) 和 [`Baseline/SERVICE_SETUP.md`](Other_BenchMark/EverMemBench/Baseline/SERVICE_SETUP.md)。

最小入口：

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_graph_builder.py \
  --topic 01 \
  --claim-mode llm \
  --provider deepseek \
  --model deepseek-v4-flash

conda run -n py311 \
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_qa_eval.py \
  --topic 01 \
  --graph-dir Graph/evermembench_topic_graph_llm_v6_endpoint_lifecycle/01 \
  --scope-routing sts \
  --graph-expansion sts
```

### LoCoMo-QA

目录：`Experiment/Other_BenchMark/LoCoMo-QA/`

当前 LoCoMo 使用 graph-first 路径：每个 `sample_id` 构建一个持久化 graph，再回答该 sample 的全部问题。

- `run_locomo_graph_builder.py`：sample-level graph build；
- `run_locomo_graph_query.py`：graph retrieval、StateFacet expansion、相对时间 grounding 和回答；
- `run_locomo_memory_baselines.py`：full-text、RAG、MemoryBank、A-mem、MemGPT/Letta 和官方 service baseline。

图构建器只使用 `sample_id` 和 `conversation`。QA、答案、证据和类别字段不进入记忆构建或 retrieval/controller prompt。
当前主路径的 ingest/构图与 QA 均使用 OpenAI `gpt-4o-mini`；embedding 模型只服务于 query-time 稠密召回，不替代 ingest 或答案 LLM。
当前使用 v2 state-merge 图：Claim 以稳定的 `subject_key + state_dimension` 路由，局部有序 fold 负责合并兼容状态并保留 primary/support provenance。查询统一从 Scope 路由到 Event，再沿图边扩展到 Claim 和 StateFacet；不按 benchmark 题型分支。
默认 Scope 语义召回只使用 `speaker,entity,topic`。Session Scope 与 Event 边仍保留用于分段和 provenance，但 `S1` 等裸编号不再竞争共享的 Scope top-k；sample Event backoff 继续提供全 conversation 的小规模召回兜底。
运行前需在 `.env` 或环境中配置 `OPENAI_API_KEY` 与 `OPENAI_API_BASE`（或
`OPENAI_BASE_URL`）。下面的命令同时设置 `OPENAI_MODEL=gpt-4o-mini` 并显式传入
provider、model 与关键运行参数，以冻结可复验配置。

```bash
env \
  PYTHONDONTWRITEBYTECODE=1 \
  OPENAI_MODEL=gpt-4o-mini \
  LLM_PARSE_RETRIES=3 \
  LLM_SEMANTIC_RETRIES=3 \
  LLM_REQUEST_TIMEOUT=120 \
  LLM_MAX_RETRIES=3 \
  LLM_RETRY_BASE_DELAY_SECONDS=2 \
  LLM_RETRY_MAX_DELAY_SECONDS=120 \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --graph-schema v2 \
  --claim-mode llm \
  --resolver-mode llm \
  --provider openai \
  --model gpt-4o-mini \
  --max-tokens 4096 \
  --message-chunk-size 4 \
  --claim-workers 4 \
  --resolver-workers 4 \
  --resolver-candidate-limit 24 \
  --max-claims-per-turn 2 \
  --event-limit 0 \
  --output-dir Graph/graph/locomo_qa_sample_graph_v2_state_merge \
  --cache Graph/cache/llm_cache.locomo_qa_graph_builder.v2_state_merge.json

env \
  PYTHONDONTWRITEBYTECODE=1 \
  OPENAI_MODEL=gpt-4o-mini \
  LLM_PARSE_RETRIES=3 \
  LLM_SEMANTIC_RETRIES=3 \
  LLM_REQUEST_TIMEOUT=120 \
  LLM_MAX_RETRIES=3 \
  LLM_RETRY_BASE_DELAY_SECONDS=2 \
  LLM_RETRY_MAX_DELAY_SECONDS=120 \
  LLM_MAX_TOKENS=2048 \
  conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_query.py \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --graph-dir Graph/graph/locomo_qa_sample_graph_v2_state_merge/conv-26 \
  --provider openai \
  --model gpt-4o-mini \
  --variants graph_embedding_scope_event \
  --limit-cases 0 \
  --limit-per-type 0 \
  --top-k 12 \
  --scope-top-k 10 \
  --scope-backoff-k 8 \
  --scope-types speaker,entity,topic \
  --candidate-k 80 \
  --embedding-candidate-k 80 \
  --max-context-events 24 \
  --max-state-lines 16 \
  --max-ledger-claims 12 \
  --max-ledger-states 8 \
  --max-ledger-events 8 \
  --ledger-fallback-events 2 \
  --time-role-selector llm \
  --event-time-routing rerank \
  --graph-expansion relation-aware \
  --evidence-citation-source answer \
  --embedding-model text-embedding-3-small \
  --embedding-batch-size 64 \
  --answer-workers 4 \
  --output Graph/results/locomo_qa/ours_scope_time_state/results_locomo_qa_graph_conv26_v2_state_merge_gpt4omini.json \
  --cache Graph/cache/llm_cache.locomo_qa_graph_query.conv-26.v2_state_merge_gpt4omini.json \
  --embedding-cache Graph/cache/embedding_cache.locomo_qa_graph_query.conv-26.v2_state_merge.text_embedding_3_small.json
```

完整 STS 召回参数、输出安全语义和三个 sample 的重建方式见 [`LoCoMo-QA/README.md`](Other_BenchMark/LoCoMo-QA/README.md)。
v2 默认图扩展从 Event 进入 Claim/StateFacet；Claim 关系链按问题相关性选择入口，并沿同 subject、同状态组扩展到闭包，
证据闭包只保留实际访问或 StateFacet/关系闭包必需的 Claim，StateFacet 在最终截断前按路径相关性排序。

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --variants full_text rag \
  --question-types temporal \
  --limit-cases 1 \
  --dry-run
```

## Baseline 边界

- baseline 只能读取对应 benchmark 允许的原始记忆来源；
- gold answer、gold evidence、question type 和 evaluator-only metadata 不进入 graph build 或 retrieval prompt；
- hosted service 只有在 LLM、embedding、服务版本和检索配置可核对时，才进入公平比较；
- smoke output、cache、partial graph 和中间 judge 文件不能直接当作最终论文结果。

## 环境和输出

```bash
conda activate py311
pip install -r requirements.txt
```

本地模型、API key、embedding 和 service URL 通过项目根目录 `.env` 配置。不要提交 `.env` 或 API key。

默认输出位置：

```text
Graph/                         graph、cache、baseline store、result
Experiment/Other_BenchMark/EverMemBench/log/  EverMemBench stage logs
```

快速检查 CLI：

```bash
conda run -n py311 python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --help
conda run -n py311 python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py --help
```

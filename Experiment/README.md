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
  -> answer
  -> optional judge and summary
```

图构建阶段只读取 benchmark 允许作为记忆的原始来源：对话 benchmark 使用对话、消息或日志；EPBench 一类叙事 benchmark 使用合成长文本/小说的段落、章节或事件流。不读取 QA、答案、gold evidence 或问题类型标签。查询阶段复用已经构建好的图；缓存、图文件、日志和结果统一放在 `Graph/output/` 或对应 benchmark 的日志目录下。

## 目录和职责

### 共享实验工具

- `run/common/`：LLM client、模型配置、IO、缓存、指标和通用工具；
- `common.py`、`registry.py`：仍被部分 baseline 和外部 runner 复用的共享定义；
- `Main_Baseline/`：TSM、Graphiti/Zep、validity-aware 等 baseline 实现，以及 LoCoMo/其他外部 benchmark 需要的兼容实现；
- `Other_BenchMark/`：当前 benchmark 的入口、数据镜像、服务说明和 adapter。

`run/run_llm_benchmark.py`、`run/run_public_benchmark.py` 及其 Oracle/Public prompt 目录属于早期 STAMB prompt-runner 代码。它们保留用于兼容和历史复现实验，不是当前 EverMemBench、GroupMemBench 或 LoCoMo 主流程的入口。

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
  --graph-dir Graph/output/evermembench_topic_graph_llm_v6_endpoint_lifecycle/01 \
  --scope-routing sts \
  --graph-expansion sts
```

### GroupMemBench

GroupMemBench 的真实代码在 `pipeline/external/groupmembench/`，`Experiment/Other_BenchMark/GroupMemBench/` 主要保存数据和上游源码。

当前规范流程是域级离线图：

```text
domain corpus
  -> per-scope claim extraction
  -> per-scope StateFacet consolidation
  -> domain graph merge
  -> graph_query_runner
```

主要入口：

- `pipeline.external.groupmembench.domain_graph_builder`：构建可复用的域级 graph；
- `pipeline.external.groupmembench.domain_graph_merge`：合并 scope checkpoint；
- `pipeline.external.groupmembench.graph_query_runner`：复用 graph 进行查询、状态扩展和 judge；
- `pipeline.external.groupmembench.domain_graph_recipes`：生成可复现的构图命令。

`pipeline.external.groupmembench.graph_builder` 只保留为 query-conditioned smoke path，不作为域级主图构建入口。

```bash
conda run -n py311 \
  python -m pipeline.external.groupmembench.domain_graph_recipes \
  --domain Finance
```

GroupMemBench 的 embedding 只用于 query-time 的事件或 scope 候选重排；claim extraction、StateFacet consolidation 和 validity relation 是图构建阶段的独立步骤。

### LoCoMo-QA

目录：`Experiment/Other_BenchMark/LoCoMo-QA/`

当前 LoCoMo 使用 graph-first 路径：每个 `sample_id` 构建一个持久化 graph，再回答该 sample 的全部问题。

- `run_locomo_graph_builder.py`：sample-level graph build；
- `run_locomo_graph_query.py`：graph retrieval、StateFacet expansion 和回答；
- `run_locomo_memory_baselines.py`：full-text、RAG、TSM、MemoryBank、A-mem、MemGPT/Letta 和官方 service baseline。

图构建器只使用 `sample_id` 和 `conversation`。QA、答案、证据和类别字段不进入记忆构建或 retrieval/controller prompt。

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py \
  --sample-id conv-26 \
  --variants full_text rag \
  --question-types temporal \
  --limit-cases 1 \
  --dry-run
```

### LongMemEval-S

目录：`Experiment/Other_BenchMark/LongMemEval-S/`，真实 runner 在 `pipeline/external/longmemeval_s/`。

它用于验证 session retrieval、时间推理、knowledge update 和 abstention，不替代当前图 pipeline 的主实验。

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py \
  --provider deepseek \
  --variants bm25_session scope_time_state_task_adapter \
  --limit-per-type 1 \
  --dry-run
```

`oracle_sessions` 只用于 sanity upper bound，不应作为公平主结果。

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
Graph/output/                         graph、cache、baseline store、result
Experiment/Other_BenchMark/EverMemBench/log/  EverMemBench stage logs
```

快速检查 CLI：

```bash
conda run -n py311 python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --help
conda run -n py311 python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py --help
conda run -n py311 python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py --help
```

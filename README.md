# STS

本仓库用于研究长期对话记忆中的 Scope-Time-State（STS）问题：系统不只是检索与问题相关的历史片段，而是要在长时间、多主题、带有状态更新和时间变化的事件流中，构造当前仍然有效的状态，并据此回答问题。

当前代码已经从早期的 standalone benchmark 文档转向以外部 benchmark 为载体的可运行图记忆 pipeline。主要工作集中在 EverMemBench、GroupMemBench 和 LoCoMo-QA，LongMemEval-S 用于跨数据集验证。

## 当前 solution

当前方法的主线是：

```text
dialogue-only memory
  -> persistent graph construction
  -> scope routing
  -> time-role aware event retrieval
  -> claim extraction
  -> correction / supersession / conflict resolution
  -> StateFacet consolidation
  -> evidence-backed answer
```

图中保存的核心对象包括：

- `Episode/Event`：原始对话、日志或消息；
- `Entity/Scope`：项目、主题、频道、阶段、参与者等范围对象；
- `Claim`：从事件中抽取出的原子事实或状态判断；
- `StateFacet`：当前决策、风险、问题、计划、完成状态等状态维度；
- `Time`：事件发生时间以及状态有效性相关的时间角色。

主要关系包括 `IN_SCOPE`、`ASSERTS`、`CORRECTS`、`SUPERSEDES`、`CONFLICTS_WITH`、`SUPPORTS`、`CURRENT_AFTER` 和 `CURRENT_STATE_OF`。

查询阶段按以下顺序运行：

1. 根据问题路由到目标 scope；
2. 识别问题对应的 time role；
3. 在目标 scope 内召回候选事件；
4. 使用 claim 和 StateFacet 结构判断当前状态；
5. 只根据锁定的状态和证据生成答案。

BM25/词法检索负责候选召回，embedding 在需要时用于事件或 scope 的候选重排；embedding 不是图语义本身，也不替代后续的状态有效性判断。

图构建只读取对话或消息数据，不读取 QA、答案、gold evidence 或问题类型标签。问题查询阶段复用已经构建好的持久化图，避免把每个问题的答案信息带入图构建。

## 当前 benchmark 运行面

| Benchmark | 当前运行路径 | 作用 |
| --- | --- | --- |
| EverMemBench | `Experiment/Other_BenchMark/EverMemBench/` | 主题级对话图、STS QA 和本地/self-host baseline 矩阵 |
| GroupMemBench | `pipeline/external/groupmembench/` | 域级持久化图、scope/time/state 检索和状态 facet 解析 |
| LoCoMo-QA | `Experiment/Other_BenchMark/LoCoMo-QA/` | sample 级持久化图、多跳/开放域/时间问答和 memory baselines |
| LongMemEval-S | `pipeline/external/longmemeval_s/` | session retrieval、时间推理和知识更新的外部验证 |

### EverMemBench

主入口：

- `run_evermembench_graph_builder.py`：只用 dialogue 构建 topic graph；
- `run_evermembench_qa_eval.py`：在已构建的图上进行检索、回答和 judge；
- `run_evermembench_baseline_adapters.py`：检查本地/self-host baseline；
- `run_official_baselines.sh`：运行公平的本地 baseline 矩阵。

当前公平比较集合为：

```text
llm mem0_local memobase graphiti_local memos_local
```

云端或 hosted adapter 不属于默认公平矩阵。具体服务依赖、模型固定和服务器运行顺序见 [`Experiment/Other_BenchMark/EverMemBench/README.md`](Experiment/Other_BenchMark/EverMemBench/README.md) 和 [`SERVER_COMMANDS.md`](Experiment/Other_BenchMark/EverMemBench/SERVER_COMMANDS.md)。

### GroupMemBench

当前规范路径是离线域级图：

```text
domain dialogue corpus
  -> per-scope claim extraction
  -> per-scope StateFacet consolidation
  -> domain graph merge
  -> graph query runner
```

使用 `pipeline.external.groupmembench.domain_graph_builder` 构建可复用的域图，再由 `graph_query_runner` 查询。`graph_builder.py` 保留为 query-conditioned smoke path，不作为域级主图构建路径。

GroupMemBench 的检索链是：

```text
scope routing
  -> lexical/BM25 candidate filtering
  -> optional event/scope embedding rerank
  -> graph expansion
  -> StateFacet readout
  -> answer and optional judge
```

可复现的域图命令由下面的 recipe 生成：

```bash
conda run -n py311 python -m pipeline.external.groupmembench.domain_graph_recipes --domain Finance
```

### LoCoMo-QA

LoCoMo 当前采用 graph-first 路径：每个 `sample_id` 构建一个持久化图，然后复用该图回答同一 sample 的全部问题。查询链是：

```text
scope routing
  -> scoped event retrieval
  -> Event / Claim / StateFacet graph expansion
  -> optional open-domain mapping
  -> answer and official-style scoring
```

`open-domain mapping` 只在回答阶段使用，不把推断出的常识写回图中。图构建器只读取 `sample_id` 和 `conversation`，不会使用答案、证据或问题类型。

### LongMemEval-S

LongMemEval-S 作为外部验证使用，当前入口是：

```bash
conda run -n py311 \
  python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py \
  --provider deepseek \
  --variants bm25_session scope_time_state_task_adapter \
  --limit-per-type 1
```

其中 `oracle_sessions` 只用于 sanity upper bound，不能作为公平主结果。

## 仓库结构

- `pipeline/external/`：外部 benchmark 的真实 pipeline；
- `Experiment/Other_BenchMark/EverMemBench/`：EverMemBench 数据、入口和 baseline adapter；
- `Experiment/Other_BenchMark/GroupMemBench/`：GroupMemBench 数据和上游源码位置；
- `Experiment/Other_BenchMark/LoCoMo-QA/`：LoCoMo 图构建、图查询和 memory baseline 入口；
- `Experiment/Other_BenchMark/LongMemEval-S/`：LongMemEval-S 薄封装和数据位置；
- `Experiment/Main_Baseline/`：仍被外部 benchmark 复用的 baseline 实现；
- `Graph/output/`：图、缓存、baseline store、结果和运行产物；
- `Relatedwork/`：相关论文 PDF；
- `scripts/`：数据校验、审计和辅助脚本。

## 环境与运行约定

使用项目验证环境：

```bash
conda activate py311
pip install -r requirements.txt
```

本地模型服务和 embedding 配置通过项目根目录 `.env` 提供。`.env`、API key、缓存、图产物和日志不应提交到仓库。

日志默认写入：

```text
Experiment/Other_BenchMark/EverMemBench/log/
```

图和实验输出默认写入：

```text
Graph/output/
```

## 当前边界

- EverMemBench、GroupMemBench 和 LoCoMo-QA 的主 pipeline 需要分别遵守各自的数据边界，不能把一个 benchmark 的 gold 字段带入另一个 benchmark；
- 官方 service baseline 只有在 LLM、embedding 和服务依赖都明确固定后，才进入公平比较；
- smoke、cache 和中间 graph artifact 不能直接当作最终论文结果；
- 结果汇总应以对应 benchmark 的实际 runner 输出为准，不再依赖已经移出当前工程的旧 benchmark 结果文档。

## 快速验证

```bash
conda run -n py311 python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --check-llm
conda run -n py311 python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py --sample-id conv-26 --variants full_text rag --question-types temporal --limit-cases 1 --dry-run
conda run -n py311 python Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py --provider deepseek --variants bm25_session scope_time_state_task_adapter --limit-per-type 1 --dry-run
```

更完整的服务器上传、环境配置和 EverMemBench 全流程见 [`SERVER_COMMANDS.md`](Experiment/Other_BenchMark/EverMemBench/SERVER_COMMANDS.md)。

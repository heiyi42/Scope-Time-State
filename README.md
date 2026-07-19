# STS

本仓库用于研究长期记忆中的 Scope-Time-State（STS）问题：系统不只是检索与问题相关的历史片段，而是要在长时间、多主题、带有状态更新和时间变化的事件流中，构造当前仍然有效的状态，并据此回答问题。输入可以是对话、群组消息、日志，或 EPBench 一类按时间展开的合成长文本/小说。

当前代码已经从早期的 standalone benchmark 文档转向以外部 benchmark 为载体的可运行图记忆 pipeline。当前实验集中在 EverMemBench 和 LoCoMo-QA。

## 当前 solution

当前方法的主线是：

```text
benchmark-visible chronological memory source
  -> persistent graph construction
  -> Event / Claim / Time / StateFacet / validity relations
  -> Scope routing (BM25 ∪ embedding)
  -> scoped Event candidate retrieval (BM25 ∪ embedding)
  -> question-only Time-role selection
  -> Time-aware Event rerank
  -> StateFacet validity selection and graph expansion
  -> deterministic grounding of relative time against source Event timestamps
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

1. 用 BM25 与 embedding 两路独立召回并路由到目标 Scope；
2. 在目标 Scope 内用 BM25 与 embedding 两路独立召回候选 Event，并取并集；
3. 只根据问题文本选择通用 Time role；
4. 用图中的 `OCCURRED_AT`、`HAS_TIME` 和 `CURRENT_AFTER` 对候选 Event 做时间重排；
5. 按 Time role、`CURRENT_AFTER` 和 validity relation 选择 StateFacet，再沿图扩展证据；
6. 只根据已选图证据和源 Event 时间戳，将相对时间确定性地解析为规范化时间；
7. 只根据锁定的状态和证据生成答案。

Scope 和 Event 都采用 BM25 与 embedding 的独立召回并集，不再只用 embedding 重排 BM25 候选池。Time 是结构化图语义重排，不再做一套独立的文本 embedding；embedding 也不替代后续的状态有效性判断。

图构建只读取 benchmark 允许作为记忆的原始来源：对话 benchmark 读取 dialogue/message，叙事 benchmark 读取小说的段落、章节或事件流；不读取 QA、答案、gold evidence 或问题类型标签。time-role selector 也只读取问题文本，不读取 benchmark/task 标签、选项、答案或 gold evidence；temporal grounding 只读取问题已选中的图证据、相对时间表达和源 Event 时间戳。问题查询阶段复用已经构建好的持久化图，避免把每个问题的答案信息带入图构建。

## 当前 benchmark 运行面

| Benchmark | 当前运行路径 | 作用 |
| --- | --- | --- |
| EverMemBench | `Experiment/Other_BenchMark/EverMemBench/` | 主题级对话图、STS QA 和本地/self-host baseline 矩阵 |
| LoCoMo-QA | `Experiment/Other_BenchMark/LoCoMo-QA/` | sample 级持久化图、多跳/开放域/时间问答和 memory baselines |

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

EverMemBench 的统一 STS QA 在 graph expansion 后执行 question-only temporal grounding：只使用已选
Event/Claim 的时间表达和源时间戳，将相对时间确定性地转换为日期或区间，再交给统一 answer 阶段；
不设置 F_MH 专用分支。

### LoCoMo-QA

LoCoMo 当前采用 graph-first 路径：每个 `sample_id` 构建一个持久化图，然后复用该图回答同一 sample 的全部问题。查询链是：

```text
Scope routing (BM25 ∪ embedding)
  -> scoped Event candidates (BM25 ∪ embedding)
  -> question-only Time-role selection
  -> Time-aware Event rerank
  -> StateFacet validity selection and Event / Claim / StateFacet graph expansion
  -> answer
  -> optional open-domain mapping and official-style scoring
```

`open-domain mapping` 只在回答阶段使用，不把推断出的常识写回图中。图构建器只读取 `sample_id` 和 `conversation`，不会使用答案、证据或问题类型。

## 仓库结构

- `pipeline/external/`：外部 benchmark 的真实 pipeline；
- `Experiment/Other_BenchMark/EverMemBench/`：EverMemBench 数据、入口和 baseline adapter；
- `Experiment/Other_BenchMark/LoCoMo-QA/`：LoCoMo 图构建、图查询和 memory baseline 入口；
- `Graph/`：图、缓存、baseline store、结果和运行产物；
- `Relatedwork/`：相关论文 PDF；
- `scripts/`：当前 solution 文档的可复现生成脚本。

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
Graph/
```

## 当前边界

- EverMemBench 和 LoCoMo-QA 的主 pipeline 需要分别遵守各自的数据边界，不能把一个 benchmark 的 gold 字段带入另一个 benchmark；
- 官方 service baseline 只有在 LLM、embedding 和服务依赖都明确固定后，才进入公平比较；
- smoke、cache 和中间 graph artifact 不能直接当作最终论文结果；
- 结果汇总应以对应 benchmark 的实际 runner 输出为准，不再依赖已经移出当前工程的旧 benchmark 结果文档。

## 快速验证

```bash
conda run -n py311 python Experiment/Other_BenchMark/EverMemBench/run_evermembench_service_readiness.py --check-llm
conda run -n py311 python Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_memory_baselines.py --sample-id conv-26 --variants full_text rag --question-types temporal --limit-cases 1 --dry-run
```

更完整的服务器上传、环境配置和 EverMemBench 全流程见 [`SERVER_COMMANDS.md`](Experiment/Other_BenchMark/EverMemBench/SERVER_COMMANDS.md)。

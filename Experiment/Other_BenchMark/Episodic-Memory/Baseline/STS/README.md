# EPBench STS v2

这是一条独立于 ARTEM/STEM 的 EPBench 原生 Scope-Time-State 流水线。固定语料为：

`data/Udefault_Sdefault_seed0/books/model_claude-3-5-sonnet-20240620_itermax_10_Idefault_nbchapters_196_nbtokens_102870`

## 固定契约

- 每章对应一个 `Episode/Event`，196 章应生成 196 个 Event；抽取 chunk 只是 LLM 请求窗口，不改变图粒度。
- Scope 仅使用 `book`、`entity`、`location`、`event_type`；Time 是独立节点。
- Event 保存完整 `raw_text` 和紧凑 `graph_text`；Claim 保存原文中的精确 `evidence_span`。
- 图使用公共 schema `scope-time-state-graph-v2-state-merge`，状态折叠调用公共 `pipeline/external/state_merge.py`。
- `COMPATIBLE` 通过多个 Claim 共同 `SUPPORTS` 同一个 StateFacet 表示；`DIFFERENT_TARGET` 不连边；Claim-Claim 只允许 `SUPERSEDES`、`CORRECTS`、`CONFLICTS_WITH`。
- 构图阶段只读取 `book.json`。`df_qa.parquet` 仅在 retrieve/QA/judge 阶段显式加载，`df_book_groundtruth.parquet` 永不进入流水线。
- build、QA、judge 默认均为 `gpt-4o-mini`；embedding 默认是 `text-embedding-3-small`。
- 检索策略固定为 `scope-claim-time-state`。Question Frame 只抽取问题中显式出现的 anchor；精确 Scope anchor 可跨类型纠正 frame 分类误差，语义 Scope 扩展仍限制在预测类型内。
- Scope 取 top-14，并允许加入最多 8 个全局 Claim back-off 候选；精确日期仍是硬约束，back-off 不得跨越该日期。
- question-only Time selector 选择置信度最高的至多两个 time roles，并在 RRF 前硬筛 Scope 与 back-off Claim 候选。
- Claim 使用 BM25+dense RRF：候选池 80，前 16 个 Claim 作为 relation-aware seeds，扩展 Claim/StateFacet/状态关系后再次对 query 做 RRF，最终最多保留 24 个 Claims。
- StateFacet 不设数量上限，但仅保留其全部 SUPPORTS Claims 都进入最终 Claim 集合的闭包；StateFacet 只能由 relation-aware 扩展得到。
- Event 不作为独立检索种子。最终 Claim 的 source Events 作为原始证据闭包进入回答上下文，LLM 接收完整 `raw_text`，同时接收 Claim evidence spans、StateFacet 和状态关系。

## 一次跑通

在仓库根目录执行：

```bash
conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage all \
  --model gpt-4o-mini \
  --answer-model gpt-4o-mini \
  --judge-model gpt-4o-mini \
  --embedding-model text-embedding-3-small \
  --message-chunk-size 4 \
  --scope-top-k 14 \
  --claim-candidate-k 80 \
  --scope-backoff-k 8 \
  --final-claim-k 24 \
  --final-chapter-k 24 \
  --time-role-selector llm-top2
```

也可以分阶段运行：

```bash
conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage build --model gpt-4o-mini --message-chunk-size 4

conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage qa --answer-model gpt-4o-mini \
  --embedding-model text-embedding-3-small

conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage judge --judge-model gpt-4o-mini
```

`retrieve|qa|judge` 要求兼容的图已经存在，不会静默重建。默认启用章节抽取、QA 和 judge 检查点；使用 `--no-resume` 可忽略已有行，使用 `--no-cache` 可关闭 LLM 缓存。

## 默认产物

- 图：`Graph/graph/epbench_long_book_sts_v2/book1/{manifest.json,graph.json,nodes.jsonl,edges.jsonl}`
- 缓存：`Graph/cache/epbench_long_book_sts_v2/`
- 检索与评测：`Graph/results/epbench_long_book_sts_v2/{retrieval.json,qa.json,judged.json}`

`qa.json` 不保存 gold answer；judge 阶段再按 `row_index` 从 QA parquet 读取 reference，并完整保留 QA answer 和 retrieval trace。

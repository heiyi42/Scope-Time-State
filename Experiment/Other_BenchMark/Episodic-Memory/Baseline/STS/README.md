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
- Question Frame 只抽取问题中显式出现的 anchor。具体 anchor 的全部 token 必须由同类型 Scope 覆盖；dense-only 命中和通用短 Scope 不能证明事件存在。
- 有 anchor 时，Scope 对应 Event 集合取交集，Event/Claim 只在交集内做 BM25+dense 检索。没有可靠 Scope 时记录 `retrieval_status=no_grounded_scope`，不调用回答模型，统一返回 `No matching event is present in the memory.`。

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
  --scope-top-k 32 \
  --event-candidate-k 64 \
  --claim-candidate-k 64 \
  --final-chapter-k 20
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

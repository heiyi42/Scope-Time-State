# STAMB-State LLM Benchmark

这是一个小型可运行 benchmark，用来测试“最近事件”与“当前有效状态”的区别。
当前默认 v1 数据包含 10 个 scope、42 个查询 case；v1.1 扩展版包含 16 个 scope、72 个查询 case；v1.2 升级版包含 16 个 scope、288 条 public events、124 个查询 case；v1.3 final-size 版包含 24 个 scope、480 条 public events、240 个查询 case，并显式标注 difficulty level、public-safe scope taxonomy 与 balanced subsets；legacy v0 保留 30 个查询 case。数据覆盖旧判断被纠正、最新事件只是复述、执行日志无状态变化、计划时间与更新时间冲突、多 scope 状态查询等场景。

## 当前交接状态

- v1.3 数据层和 public/evaluator contract 已经落地。
- STAMB-State 人工标注尚未完成；`stamb_state_benchmark/annotation/v1_3_sample/` 只是 annotation packet、gold reference、readable cases 和 sample manifest，不能当作独立 annotator 输出、agreement report 或 adjudication 证据。
- v1.3 canonical scored table 尚未完成。当前结果层仍以 v1/v1.1 checkpoint 和 v1.1 public half diagnostic 为主。
- Public End-to-End 是论文主实验方向；Oracle-Facet 是 controlled diagnostic track，用来隔离 state construction 能力。
- 外部 benchmark 已有 LongMemEval-S、LoCoMo-QA、STALE adapters；MemConflict 还需要先做小样本 diagnostic。

## 文件

- `Design/BenchMark/Scope-Time-State_Graph_Formal_Definition.md`: Scope-Time-State Graph 的节点、边和单智能体状态解析函数定义。
- `Design/BenchMark/STSGraph_Top_Level_Modeling_CN.md`: 面向导师讨论的中文顶层科学问题建模草稿。
- `Design/BenchMark/Scope-Time-State_Graph_Case_Figures.md`: 基于 graph trace 的论文案例图草稿。
- `Design/BenchMark/STAMB-State_TASK_DEFINITION.md`: 固定任务、输入输出、主指标和诊断指标。
- `Design/BenchMark/STAMB-State_Annotation_Guidelines.md`: evaluator-only gold state、support、hard negative subtype、answerability 和 public contract 标注协议。
- `Design/BenchMark/STAMB-State_v1_1_UPGRADE_SPEC.md`: v1.1 扩展原则、覆盖范围和校验命令。
- `stamb_state_benchmark/data/v1_2/README.md`: v1.2 长事件流、scope taxonomy、难度分层、answerability 和 balanced subset 分布。
- `stamb_state_benchmark/data/v1_3/README.md`: v1.3 final-size 规模、scope taxonomy、难度分层、answerability 和 balanced subset 分布。
- `stamb_state_benchmark/data/`: legacy v0 与 v1 benchmark 数据。
- `stamb_state_benchmark/output/`: canonical 结果快照和轻量校验报告；cache、smoke、audit、rerun 输出默认不入库。
- `stamb_state_benchmark/output/openai_embedding_duplicate_report_v1_3.json`: v1.3 `text-embedding-3-large` semantic near-duplicate 筛查报告，用于论文级人工复核。
- `stamb_state_benchmark/annotation/v1_3_sample/`: v1.3 annotation packet、gold reference、readable cases 和 sample manifest；人工标注、agreement 和 adjudication 尚未完成。
- `Experiment/`: LLM runner、metric analyzer、main/appendix baseline adapter。
- `Experiment/run/run_public_benchmark.py`: v1/v1.1/v1.2/v1.3 public End-to-End runner with scope-profile routing, balanced subset selection, and free-facet alignment evaluation；当前支持 `full_context_llm`、`hybrid_rag`、`tsm_global_public`、`tsm_scope_routed_public`、`validity_global_public`、`validity_scope_routed_public` 和 `ours_scope_time_state`。`tsm_global_public` 在全部 public events 上运行 TSM；`tsm_scope_routed_public` 先用 public scope profiles 路由 scope，再按 TSM 论文流程在 routed scoped history 上构建和检索。
- `scripts/`: v0 audit、v1 build、v1 validate、public track 生成脚本、v1.3 文本重复/模板泄漏质量审计脚本、annotation packet 导出和 agreement scoring 脚本。
- `Experiment/Other_BenchMark/LongMemEval-S/`: LongMemEval-S external benchmark wrapper；real pipeline lives in `pipeline/external/longmemeval_s/`。
- `Experiment/Other_BenchMark/LoCoMo-QA/`: LoCoMo-QA external benchmark wrapper；real pipeline lives in `pipeline/external/locomo_qa/`。
- `Experiment/Other_BenchMark/STALE/`: STALE external benchmark wrapper；real pipeline lives in `pipeline/external/stale/`。

## 运行

建议在项目验证环境运行：

```bash
conda activate py311
```

脚本使用 OpenAI 官方 Python SDK，并通过 `base_url` 兼容 OpenAI-style API。`py311` 环境里需要有 `openai` 包。

示例：

```dotenv
OPENAI_API_BASE=https://api.gptsapi.net
DEEPSEEK_API_BASE=https://api.deepseek.com
```

在项目根目录运行：

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py --dry-run
```

默认运行 v1 `oracle_facet` diagnostic track：模型输入来自 `stamb_state_benchmark/data/v1/events_raw.json`，评分使用 evaluator-only 的 `stamb_state_benchmark/data/v1/cases.json`。

Oracle-Facet 只给 `scope_id`、`time_role` 和 `output_slots`，用来隔离 latest-valid-state construction；它不提供 `gold_state_slots`、`gold_slot_support`、`gold_events` 或最终答案。它适合做 ablation 和错误定位，不应作为 Public End-to-End 主表。

运行 v1.1 扩展版：

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py --data-version v1_1 --dry-run
```

运行 v1.2 升级版。正式 public 半量实验使用 balanced subset，不再用文件前 36 个 case 代表 half：

```bash
conda run -n py311 python Experiment/run/run_public_benchmark.py \
  --data-version v1_2 \
  --case-subset balanced_half \
  --dry-run
```

v1.2 全量 operation 分布为 `state_lookup=73`、`state_summary=27`、`next_action=24`；`balanced_half` 为 63 cases，难度 `easy/medium/hard=21/21/21`，operation 分布为 `state_lookup=38`、`state_summary=14`、`next_action=11`。

运行 v1.3 final-size 版：

```bash
conda run -n py311 python Experiment/run/run_public_benchmark.py \
  --data-version v1_3 \
  --case-subset balanced_half \
  --dry-run
```

v1.3 全量为 24 scopes、480 public events、240 cases，operation 分布为 `state_lookup=145`、`state_summary=47`、`next_action=48`；answerability 分布为 `answerable=180`、`unknown_current=30`、`insufficient_evidence=30`。`balanced_half` 为 120 cases，难度 `easy/medium/hard=40/40/40`。v1.3 从原始 curated rows 加 scope-specific 场景扩展生成，并用 `scripts/audit_benchmark_quality.py` 检查 normalized event/query/slot 重复、通用模板泄漏、char n-gram cosine 近重复和可选 OpenAI embedding 语义近重复。char n-gram 是 deterministic lexical proxy，用来抓模板化表达；`text-embedding-3-large` 报告是更强的语义筛查证据，但仍需人工判断命中 pair 是真实重复还是同一 scope 下合理共享状态。evaluator-only `operation_subtype` 和 `hard_negative_types` 用于论文 breakdown，不暴露给 public cases。

运行 graph-guided readout ablation。主表默认仍是 `two_stage`；这个分支会在 Answer Composer 前生成 `graph_trace`，再由 `graph_trace.state_facets` 派生 `state_slots`：

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py \
  --data-version v1_1 \
  --variants ours_scope_time_state \
  --ours-pipeline graph_trace
```

跑 DeepSeek：

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py --provider deepseek
```

只跑少量 case 做 smoke test：

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py --provider deepseek --limit-cases 2
```

加入 LLM-as-a-judge 评测。默认用 OpenAI 做 judge：

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py --provider deepseek --judge --judge-provider openai
```

其中 `--provider` 是被测模型，`--judge-provider` 是语义评分模型。正式实验应尽量让二者不同，避免 self-judging bias。

## 指标

任务和指标以 `TASK_DEFINITION.md` 为准。当前主指标是：

- `sup_f1`: slot-level complete evidence support F1。
- `slot_j`: 状态字段语义正确性。
- `ans_j`: 最终回答完整正确性。

诊断指标包括 `support / ev_f1 / req_f1 / ev_p / ev_r / ctx_r`。不要只根据 `ev_f1` 判断方法优劣。

## 不能直接 claim 的内容

- 不能说 v1.3 已经完成人工标注。
- 不能说 v1.3 canonical public scored table 已经完成。
- 不能把 Oracle-Facet 结果当作 public 主实验。
- 不能把 Graphiti/Zep real-system adapter 写成 Graphiti paper reproduction；`graphiti_paper_reproduction` 是单独的 audit/reproduction runner。
- 不能把外部 benchmark 小样本 diagnostic 写成 full benchmark result。

重算已有结果文件的指标：

```bash
conda run -n py311 python Experiment/analyze_metrics.py \
  stamb_state_benchmark/output/results_v1_oracle_facet.json \
  --show-breakdown
```

## Variants

- `full_context_llm`: 给 LLM 完整事件流和基础关系字段，但不提供外部检索、KG 或状态构造规则。
- `hybrid_rag`: 给按时间排序的 top-k 事件，作为轻量 generic RAG-style baseline。
- `tsm`: paper-structured Temporal Semantic Memory reproduction；Oracle-Facet 使用 case 的 scoped history 和 output slots。Public End-to-End 里拆成 `tsm_global_public` 和 `tsm_scope_routed_public`：前者最接近原 TSM 算法，后者是给 TSM 同样 public scope routing 的 stronger adapted baseline。
- `validity_aware_consolidation`: paper-structured STALE/CUPMem reproduction；Oracle-Facet 使用 scoped history 和 output slots。Public End-to-End 里拆成 `validity_global_public` 和 `validity_scope_routed_public`：前者在全 public 事件流上做 typed state candidate/adjudication/readout，后者先 public scope routing，再在 scoped history 内做 active/stale/unknown-current 判别和 free-facet readout。
- `graphiti_zep`: real-system Graphiti/Zep runner；Oracle-Facet 仍用独立 Graphiti runner。Public End-to-End 里拆成 `graphiti_global_public` 和 `graphiti_scope_routed_public`：前者在当前 Graphiti run 全图 search，后者先 public scope routing 再 scoped Graphiti search；两者 readout 都不接收 hidden output slots。
- `ours_scope_time_state`: 先锚定 scope，再按 query time_role 在该 scope 内组织候选事件，之后做 validity/state-relevance 判断并生成可溯源状态答案。
- `latest_event_only`: 只给最新一条事件。
- `temporal_fact_graph`: 给时间事实和部分纠错/覆盖关系，但不给状态答案规范。
- `temporal_kg_oracle_schema`: 给完整 metadata 和显式有效性规则，只作为 upper-bound / diagnostic。
- `tremu_style`: 按 occurrence time 组织 timeline memory，模拟 TReMu 的 temporal reasoning 方向。

旧 variant 名仍作为 CLI alias 兼容，但新文档和结果文件统一使用上面的 canonical variant 名。

这些 variants 的 prompt adapter 已经拆到独立目录：

```text
Experiment/Main_Baseline/full_context_llm/
Experiment/Main_Baseline/hybrid_rag/
Experiment/Main_Baseline/ours_scope_time_state/
Experiment/Appendix_Baseline/latest_event_only/
Experiment/Appendix_Baseline/temporal_fact_graph/
Experiment/Appendix_Baseline/temporal_kg_oracle_schema/
Experiment/Appendix_Baseline/tremu_style/
```

真实系统或 paper-inspired baseline 预留目录：

```text
Experiment/Main_Baseline/graphiti_zep/
```

这些 variants 仍然是 prompt-level 近似，不是 ARTEM、TReMu、Graphiti、Zep 等系统的论文级复现。

# Scope-Time-State Handoff

本仓库包含 STAMB-State benchmark，以及面向长期智能体记忆场景的 Scope-Time-State pipeline。当前核心任务是：在带有时间、状态更新、纠错、计划和作用域变化的事件流中，检索“当前最新有效状态”。

## 当前状态

- STAMB-State v1.3 数据和协议已经构建完成：24 个 scope、480 条 public event、240 个 evaluator case，以及 120 个 case 的 `balanced_half` 子集。
- 人工标注还没有完成。当前 annotation 文件主要是协议、样例和参考材料，不是完整的 annotator agreement 或 adjudication 证据。
- v1.3 的 canonical scored table 还没有完成，暂时不能把 v1.3 当作最终论文结果汇报。
- Public End-to-End 是面向论文主表的主要设置；Oracle-Facet 是用于隔离 state construction 能力的受控诊断设置。
- 外部 benchmark adapter 已经放在 `pipeline/external/` 下，包括 LongMemEval-S、LoCoMo-QA 和 STALE；MemConflict 仍是计划中的小样本诊断。
- 当前 worktree 有意保持为活跃开发状态，提交或推送 GitHub 前需要检查 generated outputs、缓存和本地敏感配置。

## 目录结构

- `Design/BenchMark/`：任务定义、graph formalism、标注指南和 benchmark 文档。
- `Experiment/run/`：CLI 入口和 prompt runner 胶水层。
- `pipeline/oracle/`：Oracle-Facet 实现。
- `pipeline/public/`：STAMB-State Public End-to-End 实现。
- `pipeline/external/`：外部 benchmark adapter。
- `Experiment/Main_Baseline/`：主要 baseline 实现和外部系统 runner。
- `Experiment/Other_BenchMark/`：外部 benchmark 的薄封装和本地数据位置。
- `stamb_state_benchmark/data/`：benchmark 数据。
- `stamb_state_benchmark/output/`：经过筛选的结果快照，以及默认忽略的本地输出和缓存。

## 关键文档

- 任务定义：`Design/BenchMark/STAMB-State_TASK_DEFINITION.md`
- Benchmark 总览：`Design/BenchMark/STAMB-State_Benchmark_README.md`
- 实验 runner 说明：`Experiment/README.md`
- 结果状态：`Experiment/RESULTS.md`
- Obsidian 研究笔记：`/Users/mac/Documents/Obsidian Vault/NewIdea/Scope-Time-State Ambiguity/Scope-Time-State Ambiguity.md`

## 快速验证

使用 `py311` 环境。

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py --dry-run
conda run -n py311 python Experiment/run/run_public_benchmark.py --data-version v1_3 --case-subset balanced_half --dry-run
conda run -n py311 python scripts/validate_v1.py --v1-dir stamb_state_benchmark/data/v1_3 --out stamb_state_benchmark/output/validation_report_v1_3.json
```

质量审计：

```bash
conda run -n py311 python scripts/audit_benchmark_quality.py \
  --v1-dir stamb_state_benchmark/data/v1_3 \
  --out stamb_state_benchmark/output/quality_report_v1_3.json \
  --semantic-out stamb_state_benchmark/output/semantic_duplicate_report_v1_3.json \
  --openai-embedding-model text-embedding-3-large \
  --openai-embedding-out stamb_state_benchmark/output/openai_embedding_duplicate_report_v1_3.json \
  --fail-on-warnings
```

## 结果状态

当前已经记录的结果证据还不完整：

- v1/v1.1 的 canonical checkpoint 已经记录在 `Experiment/RESULTS.md`。
- 当前最完整的 STAMB baseline checkpoint 是 v1.1 public half，共 36 个 case，位于 `stamb_state_benchmark/output/results_v1_1_public_half_*.json`。
- LongMemEval-S 有一个 60-case 的 judged diagnostic 结果：`results_longmemeval_s_task_adapter_10_per_type_v2.json`。
- LoCoMo-QA 有一个 50-case per-type diagnostic 结果：`results_locomo_qa_10_per_type_gpt4omini_memory_router_raw.json`。
- STALE 有 10-scenario judged diagnostic 结果，目前 prompt v2 最强：`results_stale_scope_time_state_10_balanced_deepseek_prompt_v2_judged.json`。

## 当前不要宣称

- 不要宣称 STAMB-State 已经完全达到论文发布级别。
- 不要宣称人工标注已经完成。
- 不要宣称 v1.3 public results 是最终结果。
- 不要把 Oracle-Facet 当作 public 主表使用。
- 不要混淆 Graphiti/Zep 真实系统 adapter 结果和 Graphiti 论文复现/审计结果。
- 不要把新的 prompt tweak 静默替换为默认路径；如果效果和语义还没有充分确认，应先保留为 measured ablation。

## 下一步优先级

1. 完成 STAMB-State 人工标注：独立 annotator 输出、agreement report 和 adjudication records。
2. 跑完 v1.3 Public End-to-End canonical scored table，优先从 `balanced_half` 开始。
3. 添加外部 adapter 后，运行小样本 MemConflict diagnostic。
4. 产出统一 baseline provenance table，覆盖 TSM、STALE/CUPMem、Graphiti/Zep、Full-context、Hybrid RAG 和 Ours。
5. 降低 public Ours 的 `hard_neg` 和 `over_ev`，同时保持 `unknown_current` 能力。
6. 扩展外部 benchmark 检查：LongMemEval-S official-judge run、LoCoMo-QA open-domain/multi-hop 修复，以及 STALE T2 propagation 修复。

## Git 注意事项

生成输出和缓存默认不应该提交。只提交已经写入 `Experiment/RESULTS.md` 的 curated snapshot，或者在 `.gitignore` 中明确允许追踪的文件。

推送 GitHub 前需要额外确认本地敏感文件没有进入提交，尤其是 `.env`、API key、私有数据路径和大体积临时输出。

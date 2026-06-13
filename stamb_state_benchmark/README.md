# STAMB-State LLM Benchmark

这是一个小型可运行 benchmark，用来测试“最近事件”与“当前有效状态”的区别。
当前数据包含 10 个 scope、30 个查询 case，覆盖旧判断被纠正、最新事件只是复述、执行日志无状态变化、计划时间与更新时间冲突、多 scope 状态查询等场景。

## 文件

- `TASK_DEFINITION.md`: 固定任务、输入输出、主指标和诊断指标。
- `baselines/`: 每个 baseline 的独立 adapter 目录。
- `data/events.json`: 模拟长期记忆事件。
- `data/cases.json`: 查询、目标 scope、输出 slots、gold evidence 和 gold state。
- `run_llm_benchmark.py`: 调用 `.env` 中配置的 LLM，跑 prompt-level variants 并计算指标。
- `output/results.json`: 运行后生成的结果。
- `output/llm_cache.json`: LLM 调用缓存，避免重复花费。

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
python3 stamb_state_benchmark/run_llm_benchmark.py --dry-run
```

跑 DeepSeek：

```bash
python3 stamb_state_benchmark/run_llm_benchmark.py --provider deepseek
```

只跑少量 case 做 smoke test：

```bash
python3 stamb_state_benchmark/run_llm_benchmark.py --provider deepseek --limit-cases 2
```

加入 LLM-as-a-judge 评测。默认用 OpenAI 做 judge：

```bash
python3 stamb_state_benchmark/run_llm_benchmark.py --provider deepseek --judge --judge-provider openai
```

其中 `--provider` 是被测模型，`--judge-provider` 是语义评分模型。正式实验应尽量让二者不同，避免 self-judging bias。

## 指标

任务和指标以 `TASK_DEFINITION.md` 为准。当前主指标是：

- `sup_f1`: slot-level complete evidence support F1。
- `slot_j`: 状态字段语义正确性。
- `ans_j`: 最终回答完整正确性。

诊断指标包括 `support / ev_f1 / req_f1 / ev_p / ev_r / ctx_r`。不要只根据 `ev_f1` 判断方法优劣。

重算已有结果文件的指标：

```bash
python3 stamb_state_benchmark/analyze_metrics.py \
  stamb_state_benchmark/output/results_judge.json \
  stamb_state_benchmark/output/results_ours_two_stage.json
```

## Variants

- `llm_only_full_context`: 给 LLM 完整事件流和基础关系字段，但不提供外部检索、KG 或状态构造规则。
- `latest_event_only`: 只给最新一条事件。
- `recent_rag_topk`: 给按 `updated_at` 排序的 top-k 事件。
- `temporal_fact_graph`: 给时间事实和部分纠错/覆盖关系，但不给状态答案规范。
- `kg_schema_with_validity_rules`: 给完整 metadata 和显式有效性规则。
- `tremu_lite`: 按 occurrence time 组织 timeline memory，模拟 TReMu 的 temporal reasoning 方向。
- `scope_time_state_pipeline`: 先做 scope/time/validity/state-relevance 过滤，再让 LLM 生成状态答案。

这些 variants 的 prompt adapter 已经拆到独立目录：

```text
baselines/latest_event_only/
baselines/llm_only_full_context/
baselines/recent_rag_topk/
baselines/temporal_fact_graph/
baselines/kg_schema_with_validity_rules/
baselines/tremu_lite/
baselines/scope_time_state_pipeline/
```

真实系统或 paper-inspired baseline 预留目录：

```text
baselines/graphiti/
```

这些 variants 仍然是 prompt-level 近似，不是 ARTEM、TReMu、Graphiti、Zep 等系统的论文级复现。

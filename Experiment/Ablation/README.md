# LoCoMo Scope-Time-State 严格消融

这里固定同一张 LoCoMo STS 图、同一回答模型、同一 embedding、同一回答提示和同一证据上限，只改变查询时允许使用的结构。无需重建图。

| `--retrieval-policy` | 查询链 | 禁用的能力 | 要回答的问题 |
| --- | --- | --- | --- |
| `event-rag` | 在整个 conversation 的 Event 上做 BM25 ∪ dense，取 Event 种子后走固定图扩展，最终只读原始 Event | Scope、Time | 无 Scope/Time 路由下，图扩展能利用的 Event 种子质量如何？ |
| `scope-event` | 先路由 Scope，再取 Event 种子并走固定图扩展，最终只读原始 Event | Time | Scope 是否减少跨对象和跨主题干扰？ |
| `scope-event-time` | Scope 路由、问题侧 Time role、Event 时间重排，取 Event 种子后走固定图扩展，最终只读原始 Event | 无 | Temporal 增益是否来自问题时间语义？ |
| `sts` | Scope、Time、Event、Claim/StateFacet 和修正/替代关系的完整链 | 无 | 状态有效性解析带来多少额外收益？ |

## 固定协议

- `candidate_k=80`
- `embedding_candidate_k=80`
- `top_k=12` 个 Event 种子，固定图扩展后最多 `max_context_events=24` 个 Event
- `scope_top_k=10`
- `embedding_model=text-embedding-3-small`
- `variant=graph_embedding_scope_event`
- `scope_backoff_k=0`
- `evidence_selector=direct`
- 相同回答模型、回答 prompt、温度和输出配置
- 每个 policy 使用独立答案缓存和结果文件，embedding 缓存共享

所有 policy 使用同一张图和同一 `graph_expansion`；Claim、StateFacet 与关系只用于从 Event 种子扩展和保留闭合证据链。前三档不会向回答模型提供 Claim、StateFacet 或状态关系，回答证据只能来自原始 Event。`event-rag` 不执行 Scope 路由，`scope-event` 不调用 Time selector，前两档也不执行 query-time temporal grounding。

## 运行

先对一个样本做 smoke test：

```bash
python Experiment/Ablation/run_locomo_scope_time_state.py all \
  --sample-id conv-26 \
  --graph-dir Graph/graph/locomo_qa_sample_graph_v2_state_merge/conv-26 \
  --limit-cases 5
```

确认 trace 后去掉 `--limit-cases 5` 跑完整样本：

```bash
python Experiment/Ablation/run_locomo_scope_time_state.py all \
  --sample-id conv-26 \
  --graph-dir Graph/graph/locomo_qa_sample_graph_v2_state_merge/conv-26
```

也可只跑一个策略，例如：

```bash
python Experiment/Ablation/run_locomo_scope_time_state.py event-rag \
  --sample-id conv-26 \
  --graph-dir Graph/graph/locomo_qa_sample_graph_v2_state_merge/conv-26
```

一次跑完十个 conversations 的四档消融：

```bash
python Experiment/Ablation/run_locomo_scope_time_state.py all --all-samples
```

结果写入：

```text
Graph/results/locomo_qa/scope_time_state_ablation/<policy>/<sample-id>/<policy>.json
```

正式实验必须对相同的 LoCoMo conversations 运行全部四个策略，再跨 conversation 聚合；不能只挑单个 conversation 报告。每条结果的 `retrieval_trace.retrieval_policy`、`scope_routing`、`time_role_selection`、`selected_state_ids` 和 `expanded_claim_ids` 可用于检查组件是否越界。

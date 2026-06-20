# STAMB-State Annotation Guidelines

本文档定义 STAMB-State benchmark 的 evaluator-only 标注规则。public track 只暴露事件流、case id、query 和 operation；以下字段只用于评测、分析和论文附录。

## Core Task

每个 case 要求模型基于同一 scope 内的事件流回答当前有效状态，而不是简单返回最近提到的文本。标注员需要区分三类对象：

- `gold_state_slots`: query 需要回答的状态字段和值。
- `gold_events`: 支撑这些状态字段的最小事件集合。
- `hard_negative_events`: 与 query 相似、较新、或容易误导模型，但不应作为 gold support 的事件。

## Operation Types

benchmark 只保留三类 query operation：

- `state_lookup`: 查询一个或少数当前有效状态字段。
- `state_summary`: 汇总一个 scope 当前状态，通常包含多个 facet。
- `next_action`: 查询下一步应该做什么，必须区分计划、完成信号和当前风险。

`operation_subtype` 是 evaluator-only breakdown 字段，用于论文分析，不提供给 public runner。当前子类型包括：

- `latest_valid_state_lookup`
- `correction_aware_lookup`
- `stale_state_invalidation`
- `partial_evidence_lookup`
- `compact_state_summary`
- `multi_facet_summary`
- `plan_continuation`
- `risk_mitigation_planning`
- `finish_condition_verification`
- `completion_unknown`
- `insufficient_evidence`

## Answerability

`answerability` 标注模型是否能从 public events 中得到确定状态。

- `answerable`: 有足够证据给出当前有效状态。答案必须追溯到 `gold_events`。
- `unknown_current`: 有计划、待办、草稿、排期、owner assignment 等记录，但没有完成/通过/上线/提交等完成证据。答案应保留“尚不能确认完成”。
- `insufficient_evidence`: query 所问的最终批准、验收、发布、用户确认、全量完成等状态没有任何足够直接的证据。`gold_events` 通常为空。

区分规则：

- 如果事件明确说“计划做 X”，但没有完成记录，标 `unknown_current`。
- 如果事件只提供背景、扫描、截图、样例、排期，无法判断 query 所问目标是否发生，标 `insufficient_evidence`。
- 如果 query 问旧判断是否仍有效，而后续 correction 已经推翻旧判断，仍是 `answerable`，gold 应包含旧判断和 correction。

## Gold Support

`gold_events` 应满足最小充分原则：

- 包含所有 `gold_slot_support` 中引用的事件。
- 不包含只提供背景、格式、会议流程、截图归档、无状态变化执行日志的事件。
- 对 correction-aware case，通常同时包含被纠正的旧判断和有效 correction。
- 对 `state_summary`，每个输出 slot 应有独立 support；不要用一个宽泛事件支撑所有 slot。
- 对 `next_action`，support 应优先来自明确 plan、risk、completion criterion 或 active decision。

## Hard Negative Subtypes

每个 `hard_negative_events` 都应有 `hard_negative_types[event_id]`。一个事件可以属于多个 subtype。

- `stale_mention`: 旧周报、旧截图、旧方案、历史风险被再次转发或复述，但不代表当前状态。
- `non_update_latest`: 最新事件只是执行日志、格式调整、目录清理、权限修复等，不改变状态。
- `corrected_old_state`: 曾经有效但已被 correction 或 active decision 替代的旧状态。
- `cross_scope_collision`: 其他项目、其他工单、其他实验或邻近 scope 的状态被混入当前 scope。
- `plan_not_done`: 只有计划、排期、owner、todo，没有完成证据。
- `partial_evidence`: 只覆盖局部 facet 的证据，例如截图、抽样、火焰图、局部日志、一次通过率。
- `procedural_noise`: 会议记录、命名、附件、模板、目录、排班、联系人等流程信息。
- `insufficient_evidence_distractor`: 明确指出证据缺口或只确认日程/背景，不能支持最终状态。
- `other_in_scope_distractor`: 同 scope 相关但不属于上述类型的干扰事件。

## Quality Checks

构建或修改 benchmark 后必须运行：

```bash
python scripts/validate_v1.py --v1-dir stamb_state_benchmark/data/v1_3 --out stamb_state_benchmark/output/validation_report_v1_3.json
python scripts/audit_benchmark_quality.py --v1-dir stamb_state_benchmark/data/v1_3 --out stamb_state_benchmark/output/quality_report_v1_3.json --semantic-out stamb_state_benchmark/output/semantic_duplicate_report_v1_3.json --fail-on-warnings
python scripts/export_annotation_packet.py --v1-dir stamb_state_benchmark/data/v1_3 --out-dir stamb_state_benchmark/annotation/v1_3_sample --sample-size 60 --seed 13
```

`validate_v1.py` 检查引用完整性、gold support、hard-negative subtype 合法性和 public/evaluator contract。`audit_benchmark_quality.py` 检查 normalized event/query/slot 重复、通用模板词泄漏，以及 char n-gram cosine 近重复。n-gram 近重复是 lexical proxy，只用于自动筛查模板化表达；论文中的语义质量证明应来自人工 double annotation 和 adjudication。

收到标注员输出后，用以下命令评分：

```bash
python scripts/score_annotation_agreement.py \
  --gold stamb_state_benchmark/annotation/v1_3_sample/gold_reference.jsonl \
  --annotations stamb_state_benchmark/annotation/v1_3_sample/annotator_a.jsonl \
  --second-annotations stamb_state_benchmark/annotation/v1_3_sample/annotator_b.jsonl \
  --out stamb_state_benchmark/annotation/v1_3_sample/agreement_report.json
```

## Public Contract

public cases 不得包含以下 evaluator-only 信息：

- `scope_id`
- `time_roles`
- `difficulty_tags`
- `difficulty_level`
- `operation_subtype`
- `gold_events`
- `gold_state_slots`
- `gold_slot_support`
- `hard_negative_events`
- `hard_negative_types`
- `answerability`
- `output_slots`
- `gold_fields_usage`

这保证 public E2E runner 必须从 public event stream 和 public scope profiles 中恢复 scope、time role、state facets 和 support，而不是读取 gold labels。

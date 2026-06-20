# STAMB-State v1.3 Annotation Packet

Annotators should read `Design/BenchMark/STAMB-State_Annotation_Guidelines.md` first.

- `annotation_packet.jsonl`: public events plus query and an empty annotation template.
- `annotation_workbook.md`: single-file human-readable annotation workbook without Markdown tables.
- `annotation_packet_readable.md`: human-readable index linking to one Markdown file per case.
- `readable_cases/`: split human-readable case files without Markdown tables.
- `gold_reference.jsonl`: evaluator-only labels for scoring/adjudication; do not give this file to annotators.
- `sample_manifest.json`: deterministic sample coverage summary.

Expected annotator output format is one JSON object per line matching `annotation_template`.

## 标注原则

论文级标注的目标不是把答案写得漂亮，而是做到可复现、可追溯、可一致判定。

1. 只看 public evidence

   标注员只能看 `annotation_workbook.md` 里的 query 和 events。不要看
   `gold_reference.jsonl`，否则 inter-annotator agreement 没有意义。

2. 先判断 answerability

   每个 case 先判断能不能从事件中确定回答：

   - `answerable`: 有明确当前状态证据。
   - `unknown_current`: 有计划、排期、todo、owner assignment，但没有完成证据。
   - `insufficient_evidence`: query 问最终批准、验收、发布、用户确认、全量完成等状态，但事件里没有直接证据。

3. 标 latest valid state，不标 latest mention

   不能把最近一条事件直接当答案。需要判断旧状态是否被 correction 替代、最新事件是否只是 execution log/dry-run/格式调整、计划是否真的完成。

4. Gold support 要最小充分

   `gold_slot_support` 只放真正支撑对应 slot 的事件 ID。不要把背景、会议记录、格式信息、无状态变化日志、旧 mention 塞进 gold support。

5. Hard negative 要主动标

   论文级 benchmark 需要证明任务不是简单检索，所以要标出“看起来相关但不该作为证据”的事件，并写明 subtype。

6. Slot 写法要短、具体、可追溯

   `gold_state_slots` 不要写长篇解释。每个 slot value 都应该能被 `gold_slot_support` 里的事件追溯到。

## 论文级流程

1. 两个标注员独立标同一批 60 cases。
2. 标注员只读 `README.md`、`annotation_workbook.md` 和必要时的 `STAMB-State_Annotation_Guidelines.md`。
3. 两个标注员分别输出 `annotator_a.jsonl` 和 `annotator_b.jsonl`。
4. 用 `scripts/score_annotation_agreement.py` 计算 answerability agreement、gold support F1、hard negative type agreement。
5. 对不一致 case 做 adjudication，记录为什么保留或修改 gold。
6. 论文中报告 annotation protocol、sample coverage、agreement 和 adjudication 后的 gold 版本。

核心标准：每个答案都必须能指回最小事件证据；每个 hard negative 都必须说明为什么不能作为证据。

## 怎么填

人工标注时建议只打开 `annotation_workbook.md`。每个 case 末尾都有一个
`Annotation Template`，把里面的空字段填好即可。填完后再把每个 case 的 JSON
对象合并到 `annotator_a.jsonl` 或 `annotator_b.jsonl`，一行一个 JSON object。

不要改：

- `case_id`
- `gold_reference.jsonl`
- `annotation_packet.jsonl`

需要填：

- `answerability`: `answerable` / `unknown_current` / `insufficient_evidence` 三选一。
- `gold_state_slots`: query 要回答的状态字段和值。
- `gold_slot_support`: 每个 slot 对应的最小支撑事件 ID。
- `hard_negative_events`: 容易误导但不该作为 gold support 的事件 ID。
- `hard_negative_types`: 每个 hard negative 的原因类型。
- `notes`: 一句话解释标注理由。

## 模板 1: Answerable

有足够事件能回答 query 时使用。

```json
{
  "case_id": "aaai_risk",
  "answerability": "answerable",
  "gold_state_slots": {
    "risk": "TSM 已覆盖多时间角色，原来的 mentioned_at vs occurred_at 卖点不足"
  },
  "gold_slot_support": {
    "risk": ["aaai_e3"]
  },
  "hard_negative_events": [
    "aaai_e5"
  ],
  "hard_negative_types": {
    "aaai_e5": ["stale_mention"]
  },
  "notes": "aaai_e3 直接说明相关工作风险；aaai_e5 只是提到 ARTEM 可作 baseline，不是当前研究主线。"
}
```

## 模板 2: Unknown Current

有计划、排期、todo、owner，但没有完成证据时使用。

```json
{
  "case_id": "...",
  "answerability": "unknown_current",
  "gold_state_slots": {
    "completion_status": "当前只有计划/排期记录，不能确认已经完成"
  },
  "gold_slot_support": {
    "completion_status": ["相关的_plan_event_id"]
  },
  "hard_negative_events": [
    "容易误导的_event_id"
  ],
  "hard_negative_types": {
    "容易误导的_event_id": ["plan_not_done"]
  },
  "notes": "有计划但没有完成证据。"
}
```

## 模板 3: Insufficient Evidence

query 问的是最终批准、验收、发布、完成确认等，但事件里没有直接证据时使用。

```json
{
  "case_id": "...",
  "answerability": "insufficient_evidence",
  "gold_state_slots": {
    "evidence_status": "现有事件不足以证明 query 所问目标已经完成"
  },
  "gold_slot_support": {
    "evidence_status": []
  },
  "hard_negative_events": [
    "容易误导的_event_id"
  ],
  "hard_negative_types": {
    "容易误导的_event_id": ["insufficient_evidence_distractor"]
  },
  "notes": "没有直接完成/批准/验收证据。"
}
```

## Hard Negative 类型速查

- `stale_mention`: 旧方案、旧截图、旧周报被再次复述，但不是当前状态。
- `non_update_latest`: 最新事件只是执行日志、格式调整、dry-run 等，不改变状态。
- `corrected_old_state`: 曾经有效但已被后续 correction 替代的旧状态。
- `cross_scope_collision`: 其他 scope 的信息混进来。
- `plan_not_done`: 只有计划/排期，没有完成证据。
- `partial_evidence`: 只支持局部 facet，不能回答完整 query。
- `procedural_noise`: 会议、命名、目录、附件、联系人等流程噪声。
- `insufficient_evidence_distractor`: 明确暴露证据缺口，不能支持最终状态。
- `other_in_scope_distractor`: 同 scope 相关但不属于上面类型的干扰事件。

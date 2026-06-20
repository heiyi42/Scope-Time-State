# Case 17/60: v13_aaai_memory_side_signal

## Query

- case_id: `v13_aaai_memory_side_signal`
- scope_id: `aaai_memory`
- operation: `state_lookup`
- query: 判断AAAI 记忆论文时，“ARTEM baseline 备注”应不应该覆盖“latest-valid-state 建模主线”？

## Events

1. `aaai_e1`
   - type: `paper_reading`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 阅读 ARTEM，发现其使用单一时间线做 episodic memory。

2. `aaai_e2`
   - type: `idea`
   - updated_at: `2026-06-03T10:00:00`
   - planned_for: `none`
   - content: 提出“多时间字段 + KG-RAG”作为改进方向。

3. `aaai_e3`
   - type: `related_work`
   - updated_at: `2026-06-05T10:00:00`
   - planned_for: `none`
   - content: 发现 TSM 已覆盖 dialogue time vs occurrence time，因此不能只主打 mentioned_at vs occurred_at。

4. `aaai_e4`
   - type: `decision`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `none`
   - content: 判断 scope-time routing 也不够强，核心应转向 latest valid state retrieval；下一步构造 STAMB-State 小型 benchmark。

5. `aaai_e5`
   - type: `mention`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 随口又提到 ARTEM 可以作为 baseline，这不是新的研究主线。

6. `v13_aaai_memory_01`
   - type: `decision`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 曾按“沿用单时间线记忆叙事”推进，并把“早期 related-work 草稿”当成默认依据。

7. `v13_aaai_memory_02`
   - type: `issue`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 新发现：TSM 已覆盖多时间角色，原卖点不足；当前状态需要重新按有效证据判断。

8. `v13_aaai_memory_03`
   - type: `correction`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 复盘确认：主线改为 Scope-Time-State Graph 下的有效状态追踪；旧判断不再作为当前状态。

9. `v13_aaai_memory_04`
   - type: `observation`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 补充观察到：ARTEM 仍可放进相关工作对比表；它只影响“ARTEM baseline 备注”，不改变“latest-valid-state 建模主线”。

10. `v13_aaai_memory_05`
   - type: `plan`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `2026-06-10T21:00:00`
   - content: AAAI 记忆论文 安排“补一版 STSGraph 问题定义和可追溯例子”，目前只有排期，还没有完成记录。

11. `v13_aaai_memory_06`
   - type: `mention`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 的“早期 related-work 草稿”又声称“单时间线记忆就是主要创新点”，但备注说明这只是历史转述。

12. `v13_aaai_memory_07`
   - type: `risk`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 当前风险集中在：把已有底层 pipeline 误包装成顶层科学问题。


## Annotation Template

```json
{
  "case_id": "v13_aaai_memory_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

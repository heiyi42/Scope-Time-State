# Case 35/60: v13_labeling_guideline_side_signal

## Query

- case_id: `v13_labeling_guideline_side_signal`
- scope_id: `labeling_guideline`
- operation: `state_lookup`
- query: 标注规范 的“batch A 一轮标注”现在会改变“合并为 ambiguous 的 v2 规范”吗？

## Events

1. `label_e1`
   - type: `guideline`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v1 将 uncertain 与 partial 分开。

2. `label_e2`
   - type: `guideline`
   - updated_at: `2026-06-03T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v2 将 uncertain 与 partial 合并为 ambiguous。

3. `label_e3`
   - type: `issue`
   - updated_at: `2026-06-04T17:00:00`
   - planned_for: `none`
   - content: QC 发现 batch A 标注分歧率 12%。

4. `label_e4`
   - type: `plan`
   - updated_at: `2026-06-05T17:00:00`
   - planned_for: `2026-06-08T10:00:00`
   - content: 计划 6月8日用 v2 规范重新培训标注员。

5. `label_e5`
   - type: `progress`
   - updated_at: `2026-06-06T17:00:00`
   - planned_for: `none`
   - content: batch A 已完成一轮标注，但还没复核。

6. `label_e6`
   - type: `mention`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: Slack 里有人转发 v1 规范截图，但管理员说明已作废。

7. `v13_labeling_guideline_01`
   - type: `decision`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 标注规范 曾按“uncertain 与 partial 分开标”推进，并把“v1 规范截图”当成默认依据。

8. `v13_labeling_guideline_02`
   - type: `issue`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 标注规范 新发现：batch A 分歧率达到 12%；当前状态需要重新按有效证据判断。

9. `v13_labeling_guideline_03`
   - type: `correction`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 标注规范 复盘确认：管理员确认 v1 作废，当前按 v2 重新培训；旧判断不再作为当前状态。

10. `v13_labeling_guideline_04`
   - type: `observation`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 标注规范 补充观察到：一轮标注完成但还没复核；它只影响“batch A 一轮标注”，不改变“合并为 ambiguous 的 v2 规范”。

11. `v13_labeling_guideline_05`
   - type: `plan`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `2026-06-10T22:00:00`
   - content: 标注规范 安排“用 v2 规范重新培训标注员”，目前只有排期，还没有完成记录。

12. `v13_labeling_guideline_06`
   - type: `mention`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 标注规范 的“v1 规范截图”又声称“uncertain 和 partial 仍需分开”，但备注说明这只是历史转述。

13. `v13_labeling_guideline_07`
   - type: `risk`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: 标注规范 当前风险集中在：旧截图让标注员继续使用 v1。

14. `v13_labeling_guideline_08`
   - type: `plan`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `2026-06-11T01:00:00`
   - content: 标注规范 下一步是：先完成 v2 培训，再复核 batch A。

15. `v13_labeling_guideline_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 标注规范 例会只同步了“标注员排班、样例编号和工单链接”，没有更新“标注规则”。

16. `v13_labeling_guideline_10`
   - type: `mention`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: 有人把标注规范与“情感标注项目”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_labeling_guideline_11`
   - type: `note`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 标注规范 新增“标注平台标签颜色调整”，仅属流程记录，不影响状态判断。

18. `v13_labeling_guideline_12`
   - type: `mention`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 标注规范 的旧阻塞“v1/v2 截图混用”被转述，但没有证据说明它仍然有效。


## Annotation Template

```json
{
  "case_id": "v13_labeling_guideline_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

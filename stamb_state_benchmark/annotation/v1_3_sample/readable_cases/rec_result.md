# Case 12/60: rec_result

## Query

- case_id: `rec_result`
- scope_id: `recsys_ablation`
- operation: `state_lookup`
- query: NCF 现在到底比 LightGCN 好还是差？

## Events

1. `rec_e1`
   - type: `experiment`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 初次实验显示 NCF baseline 比 LightGCN 高 2%。

2. `rec_e2`
   - type: `issue`
   - updated_at: `2026-06-03T18:00:00`
   - planned_for: `none`
   - content: 发现 NCF 初次实验存在数据泄漏。

3. `rec_e3`
   - type: `experiment`
   - updated_at: `2026-06-04T18:00:00`
   - planned_for: `none`
   - content: 修正泄漏后，NCF 比 LightGCN 低 1%。

4. `rec_e4`
   - type: `decision`
   - updated_at: `2026-06-05T18:00:00`
   - planned_for: `none`
   - content: 决定下一轮加入 SASRec 对比。

5. `rec_e5`
   - type: `plan`
   - updated_at: `2026-06-06T18:00:00`
   - planned_for: `none`
   - content: 计划补 cold-start split 测试。

6. `rec_e6`
   - type: `execution_log`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 夜间重跑日志完成，没有新指标变化。

7. `v13_recsys_ablation_01`
   - type: `decision`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 曾按“按初次 NCF 高 2% 解读”推进，并把“NCF 初次结果表”当成默认依据。

8. `v13_recsys_ablation_02`
   - type: `issue`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 新发现：初次实验存在数据泄漏；当前状态需要重新按有效证据判断。

9. `v13_recsys_ablation_03`
   - type: `correction`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 复盘确认：修正后 NCF 低于 LightGCN，下一轮加入 SASRec；旧判断不再作为当前状态。

10. `v13_recsys_ablation_04`
   - type: `observation`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 补充观察到：夜间重跑没有产生新指标变化；它只影响“夜间重跑日志”，不改变“修正泄漏后 LightGCN 优于 NCF”。

11. `v13_recsys_ablation_05`
   - type: `plan`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `2026-06-10T23:00:00`
   - content: 推荐消融实验 安排“补 cold-start split 测试”，目前只有排期，还没有完成记录。

12. `v13_recsys_ablation_06`
   - type: `mention`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 的“NCF 初次结果表”又声称“NCF baseline 比 LightGCN 更好”，但备注说明这只是历史转述。

13. `v13_recsys_ablation_07`
   - type: `risk`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 当前风险集中在：继续引用泄漏结果会误导方法排序。

14. `v13_recsys_ablation_08`
   - type: `plan`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `2026-06-11T02:00:00`
   - content: 推荐消融实验 下一步是：先完成 cold-start split，再加入 SASRec 对比。

15. `v13_recsys_ablation_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 例会只同步了“随机种子、数据切分和表格配色”，没有更新“模型对比结论”。

16. `v13_recsys_ablation_10`
   - type: `mention`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 有人把推荐消融实验与“另一个召回实验”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_recsys_ablation_11`
   - type: `note`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 新增“实验目录和 seed 表整理”，仅属流程记录，不影响状态判断。

18. `v13_recsys_ablation_12`
   - type: `mention`
   - updated_at: `2026-06-08T06:00:00`
   - planned_for: `none`
   - content: 推荐消融实验 的旧阻塞“数据泄漏未修正”被转述，但没有证据说明它仍然有效。


## Annotation Template

```json
{
  "case_id": "rec_result",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

# Case 19/60: v13_amp_project_side_signal

## Query

- case_id: `v13_amp_project_side_signal`
- scope_id: `amp_project`
- operation: `state_lookup`
- query: AMP 级间匹配项目最近关于“第一级输入匹配日志”的记录能作为主状态吗？

## Events

1. `amp_e2`
   - type: `diagnosis`
   - updated_at: `2026-06-03T11:00:00`
   - planned_for: `none`
   - content: 判断 S11 问题出在输入匹配。

2. `amp_e3`
   - type: `correction`
   - updated_at: `2026-06-05T11:00:00`
   - planned_for: `none`
   - content: 纠正：S11 问题主要出在级间匹配。

3. `amp_e4`
   - type: `plan`
   - updated_at: `2026-06-06T11:00:00`
   - planned_for: `2026-06-09T09:00:00`
   - content: 计划 6月9日重算级间匹配网络线长。

4. `amp_e1`
   - type: `progress`
   - updated_at: `2026-06-07T09:00:00`
   - planned_for: `none`
   - content: 完成第一级输入匹配。

5. `amp_e5`
   - type: `mention`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 复盘时又提到之前怀疑输入匹配有问题，但这只是回顾旧判断。

6. `v13_amp_project_01`
   - type: `decision`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: AMP 级间匹配项目 曾按“继续排查第一级输入匹配”推进，并把“S11 旧诊断表”当成默认依据。

7. `v13_amp_project_02`
   - type: `issue`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: AMP 级间匹配项目 新发现：复核发现瓶颈集中在级间匹配；当前状态需要重新按有效证据判断。

8. `v13_amp_project_03`
   - type: `correction`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: AMP 级间匹配项目 复盘确认：S11 线长异常改按级间匹配处理；旧判断不再作为当前状态。

9. `v13_amp_project_04`
   - type: `observation`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: AMP 级间匹配项目 补充观察到：第一级输入匹配结果已归档为辅助证据；它只影响“第一级输入匹配日志”，不改变“级间匹配网络”。

10. `v13_amp_project_05`
   - type: `plan`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `2026-06-10T22:00:00`
   - content: AMP 级间匹配项目 安排“重算级间匹配网络线长”，目前只有排期，还没有完成记录。

11. `v13_amp_project_06`
   - type: `mention`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: AMP 级间匹配项目 的“S11 旧诊断表”又声称“主要问题在输入匹配”，但备注说明这只是历史转述。

12. `v13_amp_project_07`
   - type: `risk`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: AMP 级间匹配项目 当前风险集中在：继续围绕输入匹配调参会错过真正瓶颈。


## Annotation Template

```json
{
  "case_id": "v13_amp_project_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

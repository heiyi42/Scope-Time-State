# Case 47/60: v13_robot_nav_side_signal

## Query

- case_id: `v13_robot_nav_side_signal`
- scope_id: `robot_nav`
- operation: `state_lookup`
- query: 判断机器人导航方案时，“夜间仿真日志”应不应该覆盖“激光雷达加深度相机融合”？

## Events

1. `robot_e1`
   - type: `decision`
   - updated_at: `2026-06-01T09:00:00`
   - planned_for: `none`
   - content: 最初决定采用 lidar-only 导航方案。

2. `robot_e2`
   - type: `experiment`
   - updated_at: `2026-06-02T09:00:00`
   - planned_for: `none`
   - content: 仿真导航成功率达到 92%。

3. `robot_e3`
   - type: `issue`
   - updated_at: `2026-06-04T09:00:00`
   - planned_for: `none`
   - content: 真机在玻璃走廊场景失败，定位漂移明显。

4. `robot_e4`
   - type: `decision`
   - updated_at: `2026-06-05T09:00:00`
   - planned_for: `none`
   - content: 决定从 lidar-only 转向 lidar + depth camera 融合。

5. `robot_e5`
   - type: `plan`
   - updated_at: `2026-06-06T09:00:00`
   - planned_for: `2026-06-08T14:00:00`
   - content: 计划 6月8日标定 depth camera 外参。

6. `robot_e6`
   - type: `execution_log`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 夜间又跑了一次仿真日志，没有新结论。

7. `v13_robot_nav_01`
   - type: `decision`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 曾按“继续使用纯激光雷达导航”推进，并把“纯激光雷达方案纪要”当成默认依据。

8. `v13_robot_nav_02`
   - type: `issue`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 新发现：玻璃走廊真机定位漂移明显；当前状态需要重新按有效证据判断。

9. `v13_robot_nav_03`
   - type: `correction`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 复盘确认：方案转向激光雷达与深度相机融合；旧判断不再作为当前状态。

10. `v13_robot_nav_04`
   - type: `observation`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 补充观察到：夜间仿真没有覆盖玻璃走廊真机问题；它只影响“夜间仿真日志”，不改变“激光雷达加深度相机融合”。

11. `v13_robot_nav_05`
   - type: `plan`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `2026-06-11T04:00:00`
   - content: 机器人导航方案 安排“标定深度相机外参”，目前只有排期，还没有完成记录。

12. `v13_robot_nav_06`
   - type: `mention`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 的“纯激光雷达方案纪要”又声称“仿真成功率足以支持纯激光雷达上线”，但备注说明这只是历史转述。

13. `v13_robot_nav_07`
   - type: `risk`
   - updated_at: `2026-06-08T06:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 当前风险集中在：只看仿真成功率会掩盖真机漂移。

14. `v13_robot_nav_08`
   - type: `plan`
   - updated_at: `2026-06-08T07:00:00`
   - planned_for: `2026-06-11T07:00:00`
   - content: 机器人导航方案 下一步是：先完成外参标定，再复测玻璃走廊。

15. `v13_robot_nav_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T08:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 例会只同步了“场地预约、机器人编号和电池检查”，没有更新“导航传感器方案”。

16. `v13_robot_nav_10`
   - type: `mention`
   - updated_at: `2026-06-08T09:00:00`
   - planned_for: `none`
   - content: 有人把机器人导航方案与“仓库避障演示”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_robot_nav_11`
   - type: `note`
   - updated_at: `2026-06-08T10:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 新增“传感器支架采购记录”，仅属流程记录，不影响状态判断。

18. `v13_robot_nav_12`
   - type: `mention`
   - updated_at: `2026-06-08T11:00:00`
   - planned_for: `none`
   - content: 机器人导航方案 的旧阻塞“纯激光雷达地图还未清理”被转述，但没有证据说明它仍然有效。


## Annotation Template

```json
{
  "case_id": "v13_robot_nav_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

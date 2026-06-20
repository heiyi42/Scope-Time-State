# Case 15/60: sql_latest_non_update

## Query

- case_id: `sql_latest_non_update`
- scope_id: `sql_lab_q6`
- operation: `state_lookup`
- query: 第六题 SQL 最近一次运行有没有改变逻辑？

## Events

1. `sql_e1`
   - type: `draft`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 完成第六题 SQL 初稿。

2. `sql_e2`
   - type: `issue`
   - updated_at: `2026-06-02T13:00:00`
   - planned_for: `none`
   - content: 发现第六题 SQL 的 Department 与 Project 连接条件有问题。

3. `sql_e3`
   - type: `fix`
   - updated_at: `2026-06-04T13:00:00`
   - planned_for: `none`
   - content: 修改 Department 和 Project 的连接逻辑，第六题 SQL 的连接逻辑已修正。

4. `sql_e4`
   - type: `execution_log`
   - updated_at: `2026-06-07T13:00:00`
   - planned_for: `none`
   - content: 运行了一次 SQL，但没有新逻辑变化。

5. `sql_e5`
   - type: `mention`
   - updated_at: `2026-06-07T15:00:00`
   - planned_for: `none`
   - content: 答疑时又提到初稿版本，但没有采用初稿逻辑。

6. `v13_sql_lab_q6_01`
   - type: `decision`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 第六题 SQL 曾按“沿用初稿连接条件”推进，并把“SQL 初稿截图”当成默认依据。

7. `v13_sql_lab_q6_02`
   - type: `issue`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 第六题 SQL 新发现：连接条件把部门项目关系连错；当前状态需要重新按有效证据判断。

8. `v13_sql_lab_q6_03`
   - type: `correction`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 第六题 SQL 复盘确认：连接逻辑已按正确外键修正；旧判断不再作为当前状态。

9. `v13_sql_lab_q6_04`
   - type: `observation`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 第六题 SQL 补充观察到：一次执行日志只证明 SQL 能跑通；它只影响“一次无逻辑变更的运行日志”，不改变“Department 与 Project 连接逻辑”。

10. `v13_sql_lab_q6_05`
   - type: `plan`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `2026-06-10T20:00:00`
   - content: 第六题 SQL 安排“重新跑结果集并核对样例输出”，目前只有排期，还没有完成记录。

11. `v13_sql_lab_q6_06`
   - type: `mention`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 第六题 SQL 的“SQL 初稿截图”又声称“初稿已经可以提交”，但备注说明这只是历史转述。

12. `v13_sql_lab_q6_07`
   - type: `risk`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: 第六题 SQL 当前风险集中在：把能执行误判为逻辑正确。


## Annotation Template

```json
{
  "case_id": "sql_latest_non_update",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

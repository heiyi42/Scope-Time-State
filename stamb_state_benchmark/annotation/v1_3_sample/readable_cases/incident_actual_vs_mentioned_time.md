# Case 10/60: incident_actual_vs_mentioned_time

## Query

- case_id: `incident_actual_vs_mentioned_time`
- scope_id: `deployment_incident`
- operation: `state_lookup`
- query: 线上事故 14:05 发生、14:10 才记录的事情是什么？

## Events

1. `inc_e1`
   - type: `incident`
   - updated_at: `2026-06-05T14:10:00`
   - planned_for: `none`
   - content: 线上推荐服务 14:05 出现 5xx 峰值。

2. `inc_e2`
   - type: `mitigation`
   - updated_at: `2026-06-05T14:45:00`
   - planned_for: `none`
   - content: 已通过回滚缓解 5xx，服务恢复。

3. `inc_e3`
   - type: `diagnosis`
   - updated_at: `2026-06-05T15:00:00`
   - planned_for: `none`
   - content: 初步判断根因是数据库连接池耗尽。

4. `inc_e4`
   - type: `root_cause`
   - updated_at: `2026-06-06T10:00:00`
   - planned_for: `none`
   - content: 复盘确认根因是缓存击穿导致下游被打爆，不是数据库连接池耗尽。

5. `inc_e5`
   - type: `plan`
   - updated_at: `2026-06-06T16:00:00`
   - planned_for: `none`
   - content: 计划增加热点 key 限流和缓存预热。

6. `inc_e6`
   - type: `mention`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `none`
   - content: 状态页模板又复制了 5xx 告警文字，但没有新的故障。

7. `v13_deployment_incident_01`
   - type: `decision`
   - updated_at: `2026-06-07T11:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 曾按“按数据库连接池耗尽处置”推进，并把“数据库连接池初判”当成默认依据。

8. `v13_deployment_incident_02`
   - type: `issue`
   - updated_at: `2026-06-07T12:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 新发现：热点 key 缓存击穿导致下游被打爆；当前状态需要重新按有效证据判断。

9. `v13_deployment_incident_03`
   - type: `correction`
   - updated_at: `2026-06-07T13:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 复盘确认：根因修正为缓存击穿，服务已通过回滚缓解；旧判断不再作为当前状态。

10. `v13_deployment_incident_04`
   - type: `observation`
   - updated_at: `2026-06-07T14:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 补充观察到：状态页复制告警文字没有新增故障；它只影响“状态页模板文字”，不改变“缓存击穿根因”。

11. `v13_deployment_incident_05`
   - type: `plan`
   - updated_at: `2026-06-07T15:00:00`
   - planned_for: `2026-06-10T15:00:00`
   - content: 线上推荐事故 安排“增加热点 key 限流和缓存预热”，目前只有排期，还没有完成记录。

12. `v13_deployment_incident_06`
   - type: `mention`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 的“数据库连接池初判”又声称“事故根因是连接池耗尽”，但备注说明这只是历史转述。

13. `v13_deployment_incident_07`
   - type: `risk`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 当前风险集中在：误按数据库方向复盘会漏掉缓存防护。

14. `v13_deployment_incident_08`
   - type: `plan`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `2026-06-10T18:00:00`
   - content: 线上推荐事故 下一步是：先落地热点 key 限流，再做缓存预热演练。

15. `v13_deployment_incident_09`
   - type: `meeting_note`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 例会只同步了“on-call 轮值、状态页模板和截图归档”，没有更新“事故根因和后续动作”。

16. `v13_deployment_incident_10`
   - type: `mention`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 有人把线上推荐事故与“支付服务 5xx 告警”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_deployment_incident_11`
   - type: `note`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 新增“事故复盘模板字段补齐”，仅属流程记录，不影响状态判断。

18. `v13_deployment_incident_12`
   - type: `mention`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: 线上推荐事故 的旧阻塞“连接池指标异常”被转述，但没有证据说明它仍然有效。


## Annotation Template

```json
{
  "case_id": "incident_actual_vs_mentioned_time",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

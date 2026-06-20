# Case 32/60: v13_grant_app_next_domain_action

## Query

- case_id: `v13_grant_app_next_domain_action`
- scope_id: `grant_app`
- operation: `next_action`
- query: 围绕经费申请，现在最该先做哪个动作？

## Events

1. `grant_e1`
   - type: `budget`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 经费预算初版为 80k。

2. `grant_e2`
   - type: `budget`
   - updated_at: `2026-06-03T16:00:00`
   - planned_for: `none`
   - content: 经费预算改为 95k，并已按设备费重算。

3. `grant_e3`
   - type: `team_change`
   - updated_at: `2026-06-04T16:00:00`
   - planned_for: `none`
   - content: 合作方 B 退出申请。

4. `grant_e4`
   - type: `team_change`
   - updated_at: `2026-06-05T16:00:00`
   - planned_for: `none`
   - content: 合作方 C 加入，替代合作方 B 的实验条件支持。

5. `grant_e5`
   - type: `progress`
   - updated_at: `2026-06-06T16:00:00`
   - planned_for: `none`
   - content: 已上传申请书草稿到系统，待补预算说明。

6. `grant_e6`
   - type: `mention`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 邮件里又引用了 80k 旧预算表，但附件已标为作废。

7. `v13_grant_app_01`
   - type: `decision`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 经费申请 曾按“沿用 80k 初版预算”推进，并把“80k 旧预算表”当成默认依据。

8. `v13_grant_app_02`
   - type: `issue`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 经费申请 新发现：预算说明还没补齐；当前状态需要重新按有效证据判断。

9. `v13_grant_app_03`
   - type: `correction`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 经费申请 复盘确认：预算改为 95k，合作方 C 替代 B；旧判断不再作为当前状态。

10. `v13_grant_app_04`
   - type: `observation`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 经费申请 补充观察到：邮件引用旧预算但附件已标作废；它只影响“作废预算附件”，不改变“95k 设备费预算和合作方 C”。

11. `v13_grant_app_05`
   - type: `plan`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `2026-06-10T21:00:00`
   - content: 经费申请 安排“补预算说明并重新上传”，目前只有排期，还没有完成记录。

12. `v13_grant_app_06`
   - type: `mention`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: 经费申请 的“80k 旧预算表”又声称“预算仍按 80k 提交”，但备注说明这只是历史转述。

13. `v13_grant_app_07`
   - type: `risk`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 经费申请 当前风险集中在：旧预算附件被误作为当前金额。

14. `v13_grant_app_08`
   - type: `plan`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `2026-06-11T00:00:00`
   - content: 经费申请 下一步是：先补 95k 预算说明，再检查合作方信息。

15. `v13_grant_app_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `none`
   - content: 经费申请 例会只同步了“系统账号、盖章流程和附件编号”，没有更新“申请材料状态”。

16. `v13_grant_app_10`
   - type: `mention`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 有人把经费申请与“另一个校内设备申请”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_grant_app_11`
   - type: `note`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: 经费申请 新增“申请书命名和版本号清理”，仅属流程记录，不影响状态判断。

18. `v13_grant_app_12`
   - type: `mention`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 经费申请 的旧阻塞“合作方 B 退出”被转述，但没有证据说明它仍然有效。


## Annotation Template

```json
{
  "case_id": "v13_grant_app_next_domain_action",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

# Case 6/60: bill_deadline

## Query

- case_id: `bill_deadline`
- scope_id: `billing_migration`
- operation: `next_action`
- query: billing 这边现在最近的明确 deadline 是什么？

## Events

1. `bill_e1`
   - type: `decision`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: Billing migration 最初决定把订阅计费迁到 Stripe。

2. `bill_e2`
   - type: `deadline`
   - updated_at: `2026-06-02T09:00:00`
   - planned_for: `none`
   - content: 财务要求 6 月 12 日前确认本季度发票导出格式。

3. `bill_e3`
   - type: `issue`
   - updated_at: `2026-06-03T15:00:00`
   - planned_for: `none`
   - content: 测试环境发现税费 rounding 和旧账单有 1-2 cent 偏差。

4. `bill_e4`
   - type: `correction`
   - updated_at: `2026-06-06T10:00:00`
   - planned_for: `none`
   - content: 企业合同限制导致 Stripe migration 被阻塞，团队转为评估 Paddle。

5. `bill_e5`
   - type: `execution_log`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 发票 CSV 导出已完成，但这只是财务报表导出，不代表计费 migration 已完成。

6. `bill_e6`
   - type: `mention`
   - updated_at: `2026-06-08T09:00:00`
   - planned_for: `none`
   - content: 旧迁移文档里写着 Stripe migration done，但文档没有同步企业合同限制。

7. `bill_e7`
   - type: `decision`
   - updated_at: `2026-06-09T11:00:00`
   - planned_for: `none`
   - content: 最终决定暂时保留现有 provider，Paddle 只做 prototype，不进入生产迁移。

8. `bill_e8`
   - type: `plan`
   - updated_at: `2026-06-10T16:00:00`
   - planned_for: `2026-06-13T10:00:00`
   - content: 下一步安排 6 月 13 日做 legal review，目前没有 review 完成记录。

9. `v13_billing_migration_01`
   - type: `decision`
   - updated_at: `2026-06-10T17:00:00`
   - planned_for: `none`
   - content: 计费迁移 曾按“把订阅计费迁到 Stripe”推进，并把“Stripe migration done 文档”当成默认依据。

10. `v13_billing_migration_02`
   - type: `issue`
   - updated_at: `2026-06-10T18:00:00`
   - planned_for: `none`
   - content: 计费迁移 新发现：企业合同限制阻塞生产迁移；当前状态需要重新按有效证据判断。

11. `v13_billing_migration_03`
   - type: `correction`
   - updated_at: `2026-06-10T19:00:00`
   - planned_for: `none`
   - content: 计费迁移 复盘确认：生产迁移暂停，Paddle 只进入 prototype；旧判断不再作为当前状态。

12. `v13_billing_migration_04`
   - type: `observation`
   - updated_at: `2026-06-10T20:00:00`
   - planned_for: `none`
   - content: 计费迁移 补充观察到：发票导出完成不代表计费迁移完成；它只影响“发票 CSV 导出”，不改变“保留现有 provider 并只做 Paddle prototype”。

13. `v13_billing_migration_05`
   - type: `plan`
   - updated_at: `2026-06-10T21:00:00`
   - planned_for: `2026-06-13T21:00:00`
   - content: 计费迁移 安排“做 legal review”，目前只有排期，还没有完成记录。

14. `v13_billing_migration_06`
   - type: `mention`
   - updated_at: `2026-06-10T22:00:00`
   - planned_for: `none`
   - content: 计费迁移 的“Stripe migration done 文档”又声称“Stripe 迁移已经完成”，但备注说明这只是历史转述。

15. `v13_billing_migration_07`
   - type: `risk`
   - updated_at: `2026-06-10T23:00:00`
   - planned_for: `none`
   - content: 计费迁移 当前风险集中在：把报表导出误当成 provider 迁移。

16. `v13_billing_migration_08`
   - type: `plan`
   - updated_at: `2026-06-11T00:00:00`
   - planned_for: `2026-06-14T00:00:00`
   - content: 计费迁移 下一步是：先完成 legal review，再决定是否继续 Paddle prototype。

17. `v13_billing_migration_09`
   - type: `meeting_note`
   - updated_at: `2026-06-11T01:00:00`
   - planned_for: `none`
   - content: 计费迁移 例会只同步了“财务字段、税率备注和账单样例”，没有更新“计费 provider 决策”。

18. `v13_billing_migration_10`
   - type: `mention`
   - updated_at: `2026-06-11T02:00:00`
   - planned_for: `none`
   - content: 有人把计费迁移与“发票导出专项”混在一起，随后更正说这不是本 scope 的证据。

19. `v13_billing_migration_11`
   - type: `note`
   - updated_at: `2026-06-11T03:00:00`
   - planned_for: `none`
   - content: 计费迁移 新增“供应商联系人和合同附件整理”，仅属流程记录，不影响状态判断。

20. `v13_billing_migration_12`
   - type: `mention`
   - updated_at: `2026-06-11T04:00:00`
   - planned_for: `none`
   - content: 计费迁移 的旧阻塞“税费 rounding 与旧账单偏差”被转述，但没有证据说明它仍然有效。

21. `v13_billing_migration_13`
   - type: `task_note`
   - updated_at: `2026-06-11T05:00:00`
   - planned_for: `none`
   - content: 计费迁移 加入低优先级事项“统一发票 CSV 列名”，不改变“保留现有 provider 并只做 Paddle prototype”。

22. `v13_billing_migration_14`
   - type: `mention`
   - updated_at: `2026-06-11T06:00:00`
   - planned_for: `none`
   - content: 计费迁移 的历史风险“Stripe 文档未同步合同限制”被复制到新文档，负责人确认只是背景。

23. `v13_billing_migration_15`
   - type: `meeting_note`
   - updated_at: `2026-06-11T07:00:00`
   - planned_for: `none`
   - content: 计费迁移 交接记录列出“Stripe、Paddle、合同限制和发票导出”，没有新增决策。

24. `v13_billing_migration_16`
   - type: `observation`
   - updated_at: `2026-06-11T08:00:00`
   - planned_for: `none`
   - content: 计费迁移 的指标快照写着“CSV 导出通过率不代表迁移完成率”，它不能单独改变当前结论。

25. `v13_billing_migration_17`
   - type: `execution_log`
   - updated_at: `2026-06-11T09:00:00`
   - planned_for: `none`
   - content: 计费迁移 最近一次操作是“一次字段重命名没有改变 provider 决策”，没有产生新的状态证据。

26. `v13_billing_migration_18`
   - type: `note`
   - updated_at: `2026-06-11T10:00:00`
   - planned_for: `none`
   - content: 计费迁移 仍存在证据缺口：没有证据说明 legal review 已完成。

27. `v13_billing_migration_19`
   - type: `note`
   - updated_at: `2026-06-11T11:00:00`
   - planned_for: `none`
   - content: 计费迁移 的完成信号被定义为：合同侧确认 provider 路径。

28. `v13_billing_migration_20`
   - type: `check`
   - updated_at: `2026-06-11T12:00:00`
   - planned_for: `none`
   - content: 计费迁移 当前需要围绕“计费 provider 决策”保留可追溯证据，不能只看最新噪声。

29. `v13_billing_migration_21`
   - type: `message`
   - updated_at: `2026-06-11T13:00:00`
   - planned_for: `none`
   - content: 计费迁移 依赖方只确认了日程，没有确认“合同侧确认 provider 路径”。

30. `v13_billing_migration_22`
   - type: `progress`
   - updated_at: `2026-06-11T14:00:00`
   - planned_for: `none`
   - content: 计费迁移 已得到一个局部结果，但它只覆盖“发票 CSV 导出”。

31. `v13_billing_migration_23`
   - type: `feedback`
   - updated_at: `2026-06-11T15:00:00`
   - planned_for: `none`
   - content: 计费迁移 评审意见要求把“把报表导出误当成 provider 迁移”写入当前风险说明。

32. `v13_billing_migration_24`
   - type: `mention`
   - updated_at: `2026-06-11T16:00:00`
   - planned_for: `none`
   - content: 计费迁移 群聊再次复述“把订阅计费迁到 Stripe”，随后被标记为旧口径。


## Annotation Template

```json
{
  "case_id": "bill_deadline",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

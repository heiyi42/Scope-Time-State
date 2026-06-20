# Case 40/60: v13_onboarding_flow_corrected_decision

## Query

- case_id: `v13_onboarding_flow_corrected_decision`
- scope_id: `onboarding_flow`
- operation: `state_lookup`
- query: 当前判断新用户引导流程时，能不能继续引用“把教程弹窗直接推全量”？

## Events

1. `v13_onboarding_flow_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 曾按“把教程弹窗直接推全量”推进，并把“全量弹窗上线计划”当成默认依据。

2. `v13_onboarding_flow_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 新发现：手机号校验错误导致第二步流失异常；当前状态需要重新按有效证据判断。

3. `v13_onboarding_flow_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 复盘确认：全量发布暂停，先修手机号校验；旧判断不再作为当前状态。

4. `v13_onboarding_flow_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 补充观察到：漏斗截图定位流失点但不代表修复完成；它只影响“漏斗截图”，不改变“先修复手机号校验，再小流量实验”。

5. `v13_onboarding_flow_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 新用户引导流程 安排“修复校验后开 5% 小流量实验”，目前只有排期，还没有完成记录。

6. `v13_onboarding_flow_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 的“全量弹窗上线计划”又声称“教程弹窗已准备全量发布”，但备注说明这只是历史转述。

7. `v13_onboarding_flow_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 当前风险集中在：直接推弹窗会掩盖校验 bug。

8. `v13_onboarding_flow_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 新用户引导流程 下一步是：先修手机号校验，再启动 5% 实验。

9. `v13_onboarding_flow_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 例会只同步了“实验分桶、文案版本和设计走查”，没有更新“引导实验状态”。

10. `v13_onboarding_flow_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把新用户引导流程与“老用户召回弹窗”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_onboarding_flow_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 新增“实验命名和埋点字典整理”，仅属流程记录，不影响状态判断。

12. `v13_onboarding_flow_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 的旧阻塞“教程弹窗文案未定”被转述，但没有证据说明它仍然有效。

13. `v13_onboarding_flow_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 加入低优先级事项“整理引导页插画资源”，不改变“先修复手机号校验，再小流量实验”。

14. `v13_onboarding_flow_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 的历史风险“全量发布计划被继续引用”被复制到新文档，负责人确认只是背景。

15. `v13_onboarding_flow_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 交接记录列出“手机号校验、漏斗、实验分桶和小流量计划”，没有新增决策。

16. `v13_onboarding_flow_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 的指标快照写着“漏斗截图显示流失但没有修复证据”，它不能单独改变当前结论。

17. `v13_onboarding_flow_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 最近一次操作是“一次文案调整没有改变校验逻辑”，没有产生新的状态证据。

18. `v13_onboarding_flow_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 新用户引导流程 仍存在证据缺口：没有证据说明 5% 实验已经开始。


## Annotation Template

```json
{
  "case_id": "v13_onboarding_flow_corrected_decision",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

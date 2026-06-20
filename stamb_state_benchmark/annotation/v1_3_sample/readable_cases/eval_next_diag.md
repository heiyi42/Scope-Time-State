# Case 8/60: eval_next_diag

## Query

- case_id: `eval_next_diag`
- scope_id: `eval_harness`
- operation: `state_lookup`
- query: v1.1 新诊断指标实现了吗？

## Events

1. `eval_e1`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 评测脚本最初只按 event_f1 给方法排序。

2. `eval_e2`
   - type: `decision`
   - updated_at: `2026-06-02T10:00:00`
   - planned_for: `none`
   - content: 正式实验约定 DeepSeek 用来回答，GPT judge 用来语义评分。

3. `eval_e3`
   - type: `decision`
   - updated_at: `2026-06-03T14:00:00`
   - planned_for: `none`
   - content: 任务定义冻结：主排序看 sup_f1、slot_j、ans_j，event_f1 只作为诊断。

4. `eval_e4`
   - type: `issue`
   - updated_at: `2026-06-04T12:00:00`
   - planned_for: `none`
   - content: Graphiti 还有 3 个 judge hole，Validity-aware 还有 2 个 judge hole。

5. `eval_e5`
   - type: `execution_log`
   - updated_at: `2026-06-05T19:00:00`
   - planned_for: `none`
   - content: 重新跑 judge 后主表所有方法都达到 42/42 judge coverage。

6. `eval_e6`
   - type: `mention`
   - updated_at: `2026-06-06T09:00:00`
   - planned_for: `none`
   - content: 会议纪要里有人仍说 event_f1 第一就代表最好，但这是旧口径。

7. `eval_e7`
   - type: `plan`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `2026-06-09T10:00:00`
   - content: 下一步计划给 v1.1 增加 over-evidence rate 和 unknown-current accuracy 诊断，还没有正式实现。

8. `eval_e8`
   - type: `risk`
   - updated_at: `2026-06-08T11:00:00`
   - planned_for: `none`
   - content: 当前主要风险是扩 benchmark 时不小心过拟合 Ours，而不是只追求更高分。

9. `v13_eval_harness_01`
   - type: `decision`
   - updated_at: `2026-06-08T12:00:00`
   - planned_for: `none`
   - content: 评测 harness 曾按“按 event_f1 排序所有方法”推进，并把“event_f1 第一旧口径纪要”当成默认依据。

10. `v13_eval_harness_02`
   - type: `issue`
   - updated_at: `2026-06-08T13:00:00`
   - planned_for: `none`
   - content: 评测 harness 新发现：扩 benchmark 容易过拟合 Ours；当前状态需要重新按有效证据判断。

11. `v13_eval_harness_03`
   - type: `correction`
   - updated_at: `2026-06-08T14:00:00`
   - planned_for: `none`
   - content: 评测 harness 复盘确认：任务定义冻结，event_f1 只作诊断；旧判断不再作为当前状态。

12. `v13_eval_harness_04`
   - type: `observation`
   - updated_at: `2026-06-08T15:00:00`
   - planned_for: `none`
   - content: 评测 harness 补充观察到：judge coverage 已补齐但不改变主排序口径；它只影响“judge coverage 补跑”，不改变“sup_f1、slot_j、ans_j 主排序”。

13. `v13_eval_harness_05`
   - type: `plan`
   - updated_at: `2026-06-08T16:00:00`
   - planned_for: `2026-06-11T16:00:00`
   - content: 评测 harness 安排“增加 over-evidence rate 和 unknown-current accuracy 诊断”，目前只有排期，还没有完成记录。

14. `v13_eval_harness_06`
   - type: `mention`
   - updated_at: `2026-06-08T17:00:00`
   - planned_for: `none`
   - content: 评测 harness 的“event_f1 第一旧口径纪要”又声称“event_f1 最高即可判最好”，但备注说明这只是历史转述。

15. `v13_eval_harness_07`
   - type: `risk`
   - updated_at: `2026-06-08T18:00:00`
   - planned_for: `none`
   - content: 评测 harness 当前风险集中在：为了分数修改 benchmark 语义。

16. `v13_eval_harness_08`
   - type: `plan`
   - updated_at: `2026-06-08T19:00:00`
   - planned_for: `2026-06-11T19:00:00`
   - content: 评测 harness 下一步是：先固定指标解释，再补诊断统计。

17. `v13_eval_harness_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T20:00:00`
   - planned_for: `none`
   - content: 评测 harness 例会只同步了“表格列顺序、cache 路径和 appendix baseline”，没有更新“评测口径”。

18. `v13_eval_harness_10`
   - type: `mention`
   - updated_at: `2026-06-08T21:00:00`
   - planned_for: `none`
   - content: 有人把评测 harness与“oracle pipeline appendix baseline”混在一起，随后更正说这不是本 scope 的证据。

19. `v13_eval_harness_11`
   - type: `note`
   - updated_at: `2026-06-08T22:00:00`
   - planned_for: `none`
   - content: 评测 harness 新增“实验结果文件命名规范”，仅属流程记录，不影响状态判断。

20. `v13_eval_harness_12`
   - type: `mention`
   - updated_at: `2026-06-08T23:00:00`
   - planned_for: `none`
   - content: 评测 harness 的旧阻塞“Graphiti judge hole 未补齐”被转述，但没有证据说明它仍然有效。

21. `v13_eval_harness_13`
   - type: `task_note`
   - updated_at: `2026-06-09T00:00:00`
   - planned_for: `none`
   - content: 评测 harness 加入低优先级事项“整理旧输出目录”，不改变“sup_f1、slot_j、ans_j 主排序”。

22. `v13_eval_harness_14`
   - type: `mention`
   - updated_at: `2026-06-09T01:00:00`
   - planned_for: `none`
   - content: 评测 harness 的历史风险“只追求更高 answer_score”被复制到新文档，负责人确认只是背景。

23. `v13_eval_harness_15`
   - type: `meeting_note`
   - updated_at: `2026-06-09T02:00:00`
   - planned_for: `none`
   - content: 评测 harness 交接记录列出“public E2E、DeepSeek judge、Graphiti 和 TSM cache”，没有新增决策。

24. `v13_eval_harness_16`
   - type: `observation`
   - updated_at: `2026-06-09T03:00:00`
   - planned_for: `none`
   - content: 评测 harness 的指标快照写着“主表 coverage 42/42 但 over-evidence 还没算”，它不能单独改变当前结论。

25. `v13_eval_harness_17`
   - type: `execution_log`
   - updated_at: `2026-06-09T04:00:00`
   - planned_for: `none`
   - content: 评测 harness 最近一次操作是“一次 dry-run 没有产生新 judge 结果”，没有产生新的状态证据。

26. `v13_eval_harness_18`
   - type: `note`
   - updated_at: `2026-06-09T05:00:00`
   - planned_for: `none`
   - content: 评测 harness 仍存在证据缺口：没有证据说明 over-evidence 诊断已经实现。

27. `v13_eval_harness_19`
   - type: `note`
   - updated_at: `2026-06-09T06:00:00`
   - planned_for: `none`
   - content: 评测 harness 的完成信号被定义为：主表和诊断表口径一致。

28. `v13_eval_harness_20`
   - type: `check`
   - updated_at: `2026-06-09T07:00:00`
   - planned_for: `none`
   - content: 评测 harness 当前需要围绕“评测口径”保留可追溯证据，不能只看最新噪声。

29. `v13_eval_harness_21`
   - type: `message`
   - updated_at: `2026-06-09T08:00:00`
   - planned_for: `none`
   - content: 评测 harness 依赖方只确认了日程，没有确认“主表和诊断表口径一致”。

30. `v13_eval_harness_22`
   - type: `progress`
   - updated_at: `2026-06-09T09:00:00`
   - planned_for: `none`
   - content: 评测 harness 已得到一个局部结果，但它只覆盖“judge coverage 补跑”。

31. `v13_eval_harness_23`
   - type: `feedback`
   - updated_at: `2026-06-09T10:00:00`
   - planned_for: `none`
   - content: 评测 harness 评审意见要求把“为了分数修改 benchmark 语义”写入当前风险说明。

32. `v13_eval_harness_24`
   - type: `mention`
   - updated_at: `2026-06-09T11:00:00`
   - planned_for: `none`
   - content: 评测 harness 群聊再次复述“按 event_f1 排序所有方法”，随后被标记为旧口径。


## Annotation Template

```json
{
  "case_id": "eval_next_diag",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

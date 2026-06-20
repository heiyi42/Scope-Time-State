# Case 3/60: api_rebuild_status

## Query

- case_id: `api_rebuild_status`
- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: Graphiti 图重建和全量 run 做完了吗？

## Events

1. `api_e1`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 实验最初计划用 DeepSeek 回答、GPT judge 评分。

2. `api_e2`
   - type: `issue`
   - updated_at: `2026-06-02T12:00:00`
   - planned_for: `none`
   - content: 全量构图时 DeepSeek 额度不稳定，Graphiti ingestion 需要换到 OpenAI-compatible provider。

3. `api_e3`
   - type: `decision`
   - updated_at: `2026-06-03T13:00:00`
   - planned_for: `none`
   - content: 决定 Graphiti 构图使用 OpenAI-compatible provider，回答仍用 DeepSeek，judge 仍用 GPT。

4. `api_e4`
   - type: `mention`
   - updated_at: `2026-06-04T09:00:00`
   - planned_for: `none`
   - content: 旧日志显示 OpenAI-compatible endpoint token invalid。

5. `api_e5`
   - type: `fix`
   - updated_at: `2026-06-05T10:00:00`
   - planned_for: `none`
   - content: 最小 API ping 已通过，说明 endpoint 当前可用。

6. `api_e6`
   - type: `plan`
   - updated_at: `2026-06-06T10:00:00`
   - planned_for: `2026-06-06T14:00:00`
   - content: 计划用可用 endpoint 重建 Graphiti 图。

7. `api_e7`
   - type: `execution_log`
   - updated_at: `2026-06-06T20:00:00`
   - planned_for: `none`
   - content: Graphiti 全量 run 已完成 42 个 case，并写出 repaired adapter 结果。

8. `api_e8`
   - type: `risk`
   - updated_at: `2026-06-07T12:00:00`
   - planned_for: `none`
   - content: 剩余风险是 judge 调用成本和 endpoint 抖动，所以后续实验要保留 cache。

9. `v13_api_rate_limit_01`
   - type: `decision`
   - updated_at: `2026-06-07T13:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 曾按“DeepSeek 同时负责回答和构图”推进，并把“invalid token 旧日志”当成默认依据。

10. `v13_api_rate_limit_02`
   - type: `issue`
   - updated_at: `2026-06-07T14:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 新发现：judge 成本和 endpoint 抖动仍需 cache；当前状态需要重新按有效证据判断。

11. `v13_api_rate_limit_03`
   - type: `correction`
   - updated_at: `2026-06-07T15:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 复盘确认：最小 ping 已通过，构图 provider 当前可用；旧判断不再作为当前状态。

12. `v13_api_rate_limit_04`
   - type: `observation`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 补充观察到：旧 invalid token 日志早于最新 ping；它只影响“旧 token invalid 日志”，不改变“DeepSeek 回答、OpenAI-compatible 构图、GPT judge”。

13. `v13_api_rate_limit_05`
   - type: `plan`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `2026-06-10T17:00:00`
   - content: API 额度和 provider 安排“保留 cache 后跑公共 E2E”，目前只有排期，还没有完成记录。

14. `v13_api_rate_limit_06`
   - type: `mention`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 的“invalid token 旧日志”又声称“OpenAI-compatible endpoint 当前不可用”，但备注说明这只是历史转述。

15. `v13_api_rate_limit_07`
   - type: `risk`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 当前风险集中在：额度不稳定导致 graph construction 中断。

16. `v13_api_rate_limit_08`
   - type: `plan`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `2026-06-10T20:00:00`
   - content: API 额度和 provider 下一步是：先确认 cache 命中，再继续 public E2E。

17. `v13_api_rate_limit_09`
   - type: `meeting_note`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 例会只同步了“环境变量、cache 文件和 run id”，没有更新“provider 分工”。

18. `v13_api_rate_limit_10`
   - type: `mention`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: 有人把API 额度和 provider与“Graphiti appendix baseline”混在一起，随后更正说这不是本 scope 的证据。

19. `v13_api_rate_limit_11`
   - type: `note`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 新增“provider 配置表整理”，仅属流程记录，不影响状态判断。

20. `v13_api_rate_limit_12`
   - type: `mention`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 的旧阻塞“DeepSeek 额度不稳定”被转述，但没有证据说明它仍然有效。

21. `v13_api_rate_limit_13`
   - type: `task_note`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 加入低优先级事项“整理 API key 命名”，不改变“DeepSeek 回答、OpenAI-compatible 构图、GPT judge”。

22. `v13_api_rate_limit_14`
   - type: `mention`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 的历史风险“invalid token 旧日志被当成当前状态”被复制到新文档，负责人确认只是背景。

23. `v13_api_rate_limit_15`
   - type: `meeting_note`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 交接记录列出“DeepSeek、OpenAI-compatible、GPT judge 和 cache”，没有新增决策。

24. `v13_api_rate_limit_16`
   - type: `observation`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 的指标快照写着“42 个 case run 完成但不代表全量主表完成”，它不能单独改变当前结论。

25. `v13_api_rate_limit_17`
   - type: `execution_log`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 最近一次操作是“一次 dry-run 没有消耗 judge 额度”，没有产生新的状态证据。

26. `v13_api_rate_limit_18`
   - type: `note`
   - updated_at: `2026-06-08T06:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 仍存在证据缺口：没有证据说明全量 public E2E 已跑完。

27. `v13_api_rate_limit_19`
   - type: `note`
   - updated_at: `2026-06-08T07:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 的完成信号被定义为：public E2E 和 appendix baseline 都有缓存结果。

28. `v13_api_rate_limit_20`
   - type: `check`
   - updated_at: `2026-06-08T08:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 当前需要围绕“provider 分工”保留可追溯证据，不能只看最新噪声。

29. `v13_api_rate_limit_21`
   - type: `message`
   - updated_at: `2026-06-08T09:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 依赖方只确认了日程，没有确认“public E2E 和 appendix baseline 都有缓存结果”。

30. `v13_api_rate_limit_22`
   - type: `progress`
   - updated_at: `2026-06-08T10:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 已得到一个局部结果，但它只覆盖“旧 token invalid 日志”。

31. `v13_api_rate_limit_23`
   - type: `feedback`
   - updated_at: `2026-06-08T11:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 评审意见要求把“额度不稳定导致 graph construction 中断”写入当前风险说明。

32. `v13_api_rate_limit_24`
   - type: `mention`
   - updated_at: `2026-06-08T12:00:00`
   - planned_for: `none`
   - content: API 额度和 provider 群聊再次复述“DeepSeek 同时负责回答和构图”，随后被标记为旧口径。


## Annotation Template

```json
{
  "case_id": "api_rebuild_status",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```

# STAMB-State v1.3 Annotation Workbook

这个文件按 case 顺序展开，供人工标注阅读。填写时只需要参考每个 case 末尾的 `Annotation Template`。

## Case 1/60: aaai_risk

### Query

- case_id: `aaai_risk`
- scope_id: `aaai_memory`
- operation: `state_lookup`
- query: AAAI 这个想法现在最大的相关工作风险是什么？

### Events

1. `aaai_e1`
   - type: `paper_reading`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 阅读 ARTEM，发现其使用单一时间线做 episodic memory。

2. `aaai_e2`
   - type: `idea`
   - updated_at: `2026-06-03T10:00:00`
   - planned_for: `none`
   - content: 提出“多时间字段 + KG-RAG”作为改进方向。

3. `aaai_e3`
   - type: `related_work`
   - updated_at: `2026-06-05T10:00:00`
   - planned_for: `none`
   - content: 发现 TSM 已覆盖 dialogue time vs occurrence time，因此不能只主打 mentioned_at vs occurred_at。

4. `aaai_e4`
   - type: `decision`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `none`
   - content: 判断 scope-time routing 也不够强，核心应转向 latest valid state retrieval；下一步构造 STAMB-State 小型 benchmark。

5. `aaai_e5`
   - type: `mention`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 随口又提到 ARTEM 可以作为 baseline，这不是新的研究主线。

6. `v13_aaai_memory_01`
   - type: `decision`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 曾按“沿用单时间线记忆叙事”推进，并把“早期 related-work 草稿”当成默认依据。

7. `v13_aaai_memory_02`
   - type: `issue`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 新发现：TSM 已覆盖多时间角色，原卖点不足；当前状态需要重新按有效证据判断。

8. `v13_aaai_memory_03`
   - type: `correction`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 复盘确认：主线改为 Scope-Time-State Graph 下的有效状态追踪；旧判断不再作为当前状态。

9. `v13_aaai_memory_04`
   - type: `observation`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 补充观察到：ARTEM 仍可放进相关工作对比表；它只影响“ARTEM baseline 备注”，不改变“latest-valid-state 建模主线”。

10. `v13_aaai_memory_05`
   - type: `plan`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `2026-06-10T21:00:00`
   - content: AAAI 记忆论文 安排“补一版 STSGraph 问题定义和可追溯例子”，目前只有排期，还没有完成记录。

11. `v13_aaai_memory_06`
   - type: `mention`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 的“早期 related-work 草稿”又声称“单时间线记忆就是主要创新点”，但备注说明这只是历史转述。

12. `v13_aaai_memory_07`
   - type: `risk`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 当前风险集中在：把已有底层 pipeline 误包装成顶层科学问题。


### Annotation Template

```json
{
  "case_id": "aaai_risk",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 2/60: amp_planned_recalc

### Query

- case_id: `amp_planned_recalc`
- scope_id: `amp_project`
- operation: `next_action`
- query: 微波放大器 6月9日计划重算什么？

### Events

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


### Annotation Template

```json
{
  "case_id": "amp_planned_recalc",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 3/60: api_rebuild_status

### Query

- case_id: `api_rebuild_status`
- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: Graphiti 图重建和全量 run 做完了吗？

### Events

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


### Annotation Template

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


---

## Case 4/60: api_token_status

### Query

- case_id: `api_token_status`
- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: OpenAI-compatible endpoint 现在还是 invalid token 吗？

### Events

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


### Annotation Template

```json
{
  "case_id": "api_token_status",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 5/60: auth_audit_log_completion_unknown

### Query

- case_id: `auth_audit_log_completion_unknown`
- scope_id: `mobile_auth`
- operation: `state_lookup`
- query: magic link 登录审计日志已经补了吗？

### Events

1. `auth_e1`
   - type: `decision`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 登录方案最初采用短信 OTP。

2. `auth_e2`
   - type: `decision`
   - updated_at: `2026-06-03T12:00:00`
   - planned_for: `none`
   - content: 登录方案改为 email magic link，替代短信 OTP。

3. `auth_e3`
   - type: `issue`
   - updated_at: `2026-06-04T12:00:00`
   - planned_for: `none`
   - content: 发现 magic link 重发接口没有限流。

4. `auth_e4`
   - type: `fix`
   - updated_at: `2026-06-05T12:00:00`
   - planned_for: `none`
   - content: 已上线 magic link 重发限流修复。

5. `auth_e5`
   - type: `issue`
   - updated_at: `2026-06-06T12:00:00`
   - planned_for: `none`
   - content: 当前剩余问题是 iOS 端重发按钮偶尔不刷新倒计时。

6. `auth_e6`
   - type: `plan`
   - updated_at: `2026-06-07T12:00:00`
   - planned_for: `none`
   - content: 计划补 magic link 登录审计日志。

7. `auth_e7`
   - type: `mention`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 会议纪要里又复制了短信 OTP 旧方案，没有重新启用。

8. `v13_mobile_auth_01`
   - type: `decision`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 移动端登录 曾按“继续使用短信验证码”推进，并把“短信验证码方案纪要”当成默认依据。

9. `v13_mobile_auth_02`
   - type: `issue`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 移动端登录 新发现：iOS 重发按钮倒计时偶尔不刷新；当前状态需要重新按有效证据判断。

10. `v13_mobile_auth_03`
   - type: `correction`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: 移动端登录 复盘确认：短信验证码已被邮箱魔法链接替代；旧判断不再作为当前状态。

11. `v13_mobile_auth_04`
   - type: `observation`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 移动端登录 补充观察到：重发限流已经上线但不等于审计日志完成；它只影响“重发限流修复”，不改变“邮箱魔法链接登录”。

12. `v13_mobile_auth_05`
   - type: `plan`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `2026-06-11T00:00:00`
   - content: 移动端登录 安排“补登录审计日志”，目前只有排期，还没有完成记录。

13. `v13_mobile_auth_06`
   - type: `mention`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `none`
   - content: 移动端登录 的“短信验证码方案纪要”又声称“短信验证码仍是默认方案”，但备注说明这只是历史转述。

14. `v13_mobile_auth_07`
   - type: `risk`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 移动端登录 当前风险集中在：旧短信方案被会议纪要误认为重新启用。

15. `v13_mobile_auth_08`
   - type: `plan`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `2026-06-11T03:00:00`
   - content: 移动端登录 下一步是：先补审计日志并复查 iOS 倒计时。

16. `v13_mobile_auth_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 移动端登录 例会只同步了“登录页文案、按钮尺寸和埋点命名”，没有更新“登录方案”。

17. `v13_mobile_auth_10`
   - type: `mention`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 有人把移动端登录与“Web 端单点登录排期”混在一起，随后更正说这不是本 scope 的证据。

18. `v13_mobile_auth_11`
   - type: `note`
   - updated_at: `2026-06-08T06:00:00`
   - planned_for: `none`
   - content: 移动端登录 新增“风控白名单导出”，仅属流程记录，不影响状态判断。


### Annotation Template

```json
{
  "case_id": "auth_audit_log_completion_unknown",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 6/60: bill_deadline

### Query

- case_id: `bill_deadline`
- scope_id: `billing_migration`
- operation: `next_action`
- query: billing 这边现在最近的明确 deadline 是什么？

### Events

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


### Annotation Template

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


---

## Case 7/60: cache_status

### Query

- case_id: `cache_status`
- scope_id: `cache_refactor`
- operation: `state_summary`
- query: cache/refactor 现在状态怎样？

### Events

1. `cache_e1`
   - type: `issue`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: LLM cache 会返回同一个 parsed object，后续 trace mutation 可能污染缓存。

2. `cache_e2`
   - type: `fix`
   - updated_at: `2026-06-02T12:00:00`
   - planned_for: `none`
   - content: 修复 cache：命中、写入和返回都使用 deepcopy，并改为 transactional write。

3. `cache_e3`
   - type: `issue`
   - updated_at: `2026-06-03T10:00:00`
   - planned_for: `none`
   - content: Graphiti verifier trace 把 raw 自身写入 pipeline_trace，导致 JSON dump 出现 circular reference。

4. `cache_e4`
   - type: `fix`
   - updated_at: `2026-06-04T10:00:00`
   - planned_for: `none`
   - content: 修复 Graphiti trace：draft 和 verifier output 先 deepcopy，再写入 pipeline_trace。

5. `cache_e5`
   - type: `execution_log`
   - updated_at: `2026-06-05T09:00:00`
   - planned_for: `none`
   - content: py_compile 验证时重新生成了 Experiment 下的 __pycache__。

6. `cache_e6`
   - type: `cleanup`
   - updated_at: `2026-06-05T09:30:00`
   - planned_for: `none`
   - content: __pycache__ 已经清理，Experiment 目录没有残留运行产物。

7. `cache_e7`
   - type: `plan`
   - updated_at: `2026-06-06T11:00:00`
   - planned_for: `2026-06-08T10:00:00`
   - content: 计划之后补一个 cache mutation regression test，但目前还没有测试落地记录。

8. `cache_e8`
   - type: `mention`
   - updated_at: `2026-06-07T08:00:00`
   - planned_for: `none`
   - content: 旧错误日志还写着 circular reference 未解决，但日志时间早于 trace deepcopy fix。

9. `v13_cache_refactor_01`
   - type: `decision`
   - updated_at: `2026-06-07T09:00:00`
   - planned_for: `none`
   - content: 缓存重构 曾按“只修 circular reference trace”推进，并把“circular reference 旧错误日志”当成默认依据。

10. `v13_cache_refactor_02`
   - type: `issue`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `none`
   - content: 缓存重构 新发现：regression test 还没有落地；当前状态需要重新按有效证据判断。

11. `v13_cache_refactor_03`
   - type: `correction`
   - updated_at: `2026-06-07T11:00:00`
   - planned_for: `none`
   - content: 缓存重构 复盘确认：cache 返回和 trace 写入都已 deepcopy；旧判断不再作为当前状态。

12. `v13_cache_refactor_04`
   - type: `observation`
   - updated_at: `2026-06-07T12:00:00`
   - planned_for: `none`
   - content: 缓存重构 补充观察到：__pycache__ 已清理但不代表测试已补；它只影响“py_compile 生成物清理”，不改变“deepcopy cache 和 transactional write”。

13. `v13_cache_refactor_05`
   - type: `plan`
   - updated_at: `2026-06-07T13:00:00`
   - planned_for: `2026-06-10T13:00:00`
   - content: 缓存重构 安排“补 cache mutation regression test”，目前只有排期，还没有完成记录。

14. `v13_cache_refactor_06`
   - type: `mention`
   - updated_at: `2026-06-07T14:00:00`
   - planned_for: `none`
   - content: 缓存重构 的“circular reference 旧错误日志”又声称“trace 仍无法 JSON dump”，但备注说明这只是历史转述。

15. `v13_cache_refactor_07`
   - type: `risk`
   - updated_at: `2026-06-07T15:00:00`
   - planned_for: `none`
   - content: 缓存重构 当前风险集中在：把 py_compile 通过误判为行为测试覆盖。

16. `v13_cache_refactor_08`
   - type: `plan`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `2026-06-10T16:00:00`
   - content: 缓存重构 下一步是：先补 mutation regression test，再跑公共 E2E。

17. `v13_cache_refactor_09`
   - type: `meeting_note`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 缓存重构 例会只同步了“输出目录、cache 文件名和 dry-run 命令”，没有更新“cache/refactor 状态”。

18. `v13_cache_refactor_10`
   - type: `mention`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 有人把缓存重构与“Graphiti verifier trace 修复”混在一起，随后更正说这不是本 scope 的证据。


### Annotation Template

```json
{
  "case_id": "cache_status",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 8/60: eval_next_diag

### Query

- case_id: `eval_next_diag`
- scope_id: `eval_harness`
- operation: `state_lookup`
- query: v1.1 新诊断指标实现了吗？

### Events

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


### Annotation Template

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


---

## Case 9/60: eval_primary_metrics

### Query

- case_id: `eval_primary_metrics`
- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 现在主表到底按什么指标判断方法？

### Events

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


### Annotation Template

```json
{
  "case_id": "eval_primary_metrics",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 10/60: incident_actual_vs_mentioned_time

### Query

- case_id: `incident_actual_vs_mentioned_time`
- scope_id: `deployment_incident`
- operation: `state_lookup`
- query: 线上事故 14:05 发生、14:10 才记录的事情是什么？

### Events

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


### Annotation Template

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


---

## Case 11/60: incident_root_cause

### Query

- case_id: `incident_root_cause`
- scope_id: `deployment_incident`
- operation: `state_lookup`
- query: 线上事故根因到底是数据库连接池还是缓存问题？

### Events

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


### Annotation Template

```json
{
  "case_id": "incident_root_cause",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 12/60: rec_result

### Query

- case_id: `rec_result`
- scope_id: `recsys_ablation`
- operation: `state_lookup`
- query: NCF 现在到底比 LightGCN 好还是差？

### Events

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


### Annotation Template

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


---

## Case 13/60: robot_calibration_completion_unknown

### Query

- case_id: `robot_calibration_completion_unknown`
- scope_id: `robot_nav`
- operation: `state_lookup`
- query: 机器人导航 depth camera 外参已经标定完成了吗？

### Events

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


### Annotation Template

```json
{
  "case_id": "robot_calibration_completion_unknown",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 14/60: robot_planned_calibration

### Query

- case_id: `robot_planned_calibration`
- scope_id: `robot_nav`
- operation: `next_action`
- query: 机器人导航 6月8日计划做什么？

### Events

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


### Annotation Template

```json
{
  "case_id": "robot_planned_calibration",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 15/60: sql_latest_non_update

### Query

- case_id: `sql_latest_non_update`
- scope_id: `sql_lab_q6`
- operation: `state_lookup`
- query: 第六题 SQL 最近一次运行有没有改变逻辑？

### Events

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


### Annotation Template

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


---

## Case 16/60: sql_status

### Query

- case_id: `sql_status`
- scope_id: `sql_lab_q6`
- operation: `state_summary`
- query: 第六题 SQL 最近改到哪了？

### Events

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


### Annotation Template

```json
{
  "case_id": "sql_status",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 17/60: v13_aaai_memory_side_signal

### Query

- case_id: `v13_aaai_memory_side_signal`
- scope_id: `aaai_memory`
- operation: `state_lookup`
- query: 判断AAAI 记忆论文时，“ARTEM baseline 备注”应不应该覆盖“latest-valid-state 建模主线”？

### Events

1. `aaai_e1`
   - type: `paper_reading`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 阅读 ARTEM，发现其使用单一时间线做 episodic memory。

2. `aaai_e2`
   - type: `idea`
   - updated_at: `2026-06-03T10:00:00`
   - planned_for: `none`
   - content: 提出“多时间字段 + KG-RAG”作为改进方向。

3. `aaai_e3`
   - type: `related_work`
   - updated_at: `2026-06-05T10:00:00`
   - planned_for: `none`
   - content: 发现 TSM 已覆盖 dialogue time vs occurrence time，因此不能只主打 mentioned_at vs occurred_at。

4. `aaai_e4`
   - type: `decision`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `none`
   - content: 判断 scope-time routing 也不够强，核心应转向 latest valid state retrieval；下一步构造 STAMB-State 小型 benchmark。

5. `aaai_e5`
   - type: `mention`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 随口又提到 ARTEM 可以作为 baseline，这不是新的研究主线。

6. `v13_aaai_memory_01`
   - type: `decision`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 曾按“沿用单时间线记忆叙事”推进，并把“早期 related-work 草稿”当成默认依据。

7. `v13_aaai_memory_02`
   - type: `issue`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 新发现：TSM 已覆盖多时间角色，原卖点不足；当前状态需要重新按有效证据判断。

8. `v13_aaai_memory_03`
   - type: `correction`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 复盘确认：主线改为 Scope-Time-State Graph 下的有效状态追踪；旧判断不再作为当前状态。

9. `v13_aaai_memory_04`
   - type: `observation`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 补充观察到：ARTEM 仍可放进相关工作对比表；它只影响“ARTEM baseline 备注”，不改变“latest-valid-state 建模主线”。

10. `v13_aaai_memory_05`
   - type: `plan`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `2026-06-10T21:00:00`
   - content: AAAI 记忆论文 安排“补一版 STSGraph 问题定义和可追溯例子”，目前只有排期，还没有完成记录。

11. `v13_aaai_memory_06`
   - type: `mention`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 的“早期 related-work 草稿”又声称“单时间线记忆就是主要创新点”，但备注说明这只是历史转述。

12. `v13_aaai_memory_07`
   - type: `risk`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: AAAI 记忆论文 当前风险集中在：把已有底层 pipeline 误包装成顶层科学问题。


### Annotation Template

```json
{
  "case_id": "v13_aaai_memory_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 18/60: v13_amp_project_brief_state

### Query

- case_id: `v13_amp_project_brief_state`
- scope_id: `amp_project`
- operation: `state_summary`
- query: AMP 级间匹配项目 当前可以怎样概括“线长异常定位”？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_amp_project_brief_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 19/60: v13_amp_project_side_signal

### Query

- case_id: `v13_amp_project_side_signal`
- scope_id: `amp_project`
- operation: `state_lookup`
- query: AMP 级间匹配项目最近关于“第一级输入匹配日志”的记录能作为主状态吗？

### Events

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


### Annotation Template

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


---

## Case 20/60: v13_api_rate_limit_brief_state

### Query

- case_id: `v13_api_rate_limit_brief_state`
- scope_id: `api_rate_limit`
- operation: `state_summary`
- query: API 额度和 provider 当前可以怎样概括“provider 分工”？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_api_rate_limit_brief_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 21/60: v13_api_rate_limit_corrected_current_state

### Query

- case_id: `v13_api_rate_limit_corrected_current_state`
- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: API 额度和 provider 当前是否已经不再适用“DeepSeek 同时负责回答和构图”？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_api_rate_limit_corrected_current_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 22/60: v13_api_rate_limit_final_evidence_insufficient

### Query

- case_id: `v13_api_rate_limit_final_evidence_insufficient`
- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: 能不能判断API 额度和 provider已经拿到“全 baseline 主表”？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_api_rate_limit_final_evidence_insufficient",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 23/60: v13_billing_migration_brief_state

### Query

- case_id: `v13_billing_migration_brief_state`
- scope_id: `billing_migration`
- operation: `state_summary`
- query: 计费迁移 当前可以怎样概括“计费 provider 决策”？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_billing_migration_brief_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 24/60: v13_billing_migration_final_evidence_insufficient

### Query

- case_id: `v13_billing_migration_final_evidence_insufficient`
- scope_id: `billing_migration`
- operation: `state_lookup`
- query: 能不能判断计费迁移已经拿到“生产迁移签字”？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_billing_migration_final_evidence_insufficient",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 25/60: v13_billing_migration_planned_item_unknown

### Query

- case_id: `v13_billing_migration_planned_item_unknown`
- scope_id: `billing_migration`
- operation: `state_lookup`
- query: 计费迁移 关于“legal review”有没有完成记录？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_billing_migration_planned_item_unknown",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 26/60: v13_cache_refactor_brief_state

### Query

- case_id: `v13_cache_refactor_brief_state`
- scope_id: `cache_refactor`
- operation: `state_summary`
- query: 如果只说当前有效状态，缓存重构 应该怎么总结？

### Events

1. `cache_e1`
   - type: `issue`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: LLM cache 会返回同一个 parsed object，后续 trace mutation 可能污染缓存。

2. `cache_e2`
   - type: `fix`
   - updated_at: `2026-06-02T12:00:00`
   - planned_for: `none`
   - content: 修复 cache：命中、写入和返回都使用 deepcopy，并改为 transactional write。

3. `cache_e3`
   - type: `issue`
   - updated_at: `2026-06-03T10:00:00`
   - planned_for: `none`
   - content: Graphiti verifier trace 把 raw 自身写入 pipeline_trace，导致 JSON dump 出现 circular reference。

4. `cache_e4`
   - type: `fix`
   - updated_at: `2026-06-04T10:00:00`
   - planned_for: `none`
   - content: 修复 Graphiti trace：draft 和 verifier output 先 deepcopy，再写入 pipeline_trace。

5. `cache_e5`
   - type: `execution_log`
   - updated_at: `2026-06-05T09:00:00`
   - planned_for: `none`
   - content: py_compile 验证时重新生成了 Experiment 下的 __pycache__。

6. `cache_e6`
   - type: `cleanup`
   - updated_at: `2026-06-05T09:30:00`
   - planned_for: `none`
   - content: __pycache__ 已经清理，Experiment 目录没有残留运行产物。

7. `cache_e7`
   - type: `plan`
   - updated_at: `2026-06-06T11:00:00`
   - planned_for: `2026-06-08T10:00:00`
   - content: 计划之后补一个 cache mutation regression test，但目前还没有测试落地记录。

8. `cache_e8`
   - type: `mention`
   - updated_at: `2026-06-07T08:00:00`
   - planned_for: `none`
   - content: 旧错误日志还写着 circular reference 未解决，但日志时间早于 trace deepcopy fix。

9. `v13_cache_refactor_01`
   - type: `decision`
   - updated_at: `2026-06-07T09:00:00`
   - planned_for: `none`
   - content: 缓存重构 曾按“只修 circular reference trace”推进，并把“circular reference 旧错误日志”当成默认依据。

10. `v13_cache_refactor_02`
   - type: `issue`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `none`
   - content: 缓存重构 新发现：regression test 还没有落地；当前状态需要重新按有效证据判断。

11. `v13_cache_refactor_03`
   - type: `correction`
   - updated_at: `2026-06-07T11:00:00`
   - planned_for: `none`
   - content: 缓存重构 复盘确认：cache 返回和 trace 写入都已 deepcopy；旧判断不再作为当前状态。

12. `v13_cache_refactor_04`
   - type: `observation`
   - updated_at: `2026-06-07T12:00:00`
   - planned_for: `none`
   - content: 缓存重构 补充观察到：__pycache__ 已清理但不代表测试已补；它只影响“py_compile 生成物清理”，不改变“deepcopy cache 和 transactional write”。

13. `v13_cache_refactor_05`
   - type: `plan`
   - updated_at: `2026-06-07T13:00:00`
   - planned_for: `2026-06-10T13:00:00`
   - content: 缓存重构 安排“补 cache mutation regression test”，目前只有排期，还没有完成记录。

14. `v13_cache_refactor_06`
   - type: `mention`
   - updated_at: `2026-06-07T14:00:00`
   - planned_for: `none`
   - content: 缓存重构 的“circular reference 旧错误日志”又声称“trace 仍无法 JSON dump”，但备注说明这只是历史转述。

15. `v13_cache_refactor_07`
   - type: `risk`
   - updated_at: `2026-06-07T15:00:00`
   - planned_for: `none`
   - content: 缓存重构 当前风险集中在：把 py_compile 通过误判为行为测试覆盖。

16. `v13_cache_refactor_08`
   - type: `plan`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `2026-06-10T16:00:00`
   - content: 缓存重构 下一步是：先补 mutation regression test，再跑公共 E2E。

17. `v13_cache_refactor_09`
   - type: `meeting_note`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 缓存重构 例会只同步了“输出目录、cache 文件名和 dry-run 命令”，没有更新“cache/refactor 状态”。

18. `v13_cache_refactor_10`
   - type: `mention`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 有人把缓存重构与“Graphiti verifier trace 修复”混在一起，随后更正说这不是本 scope 的证据。


### Annotation Template

```json
{
  "case_id": "v13_cache_refactor_brief_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 27/60: v13_data_retention_policy_current_obstacle

### Query

- case_id: `v13_data_retention_policy_current_obstacle`
- scope_id: `data_retention_policy`
- operation: `state_lookup`
- query: 在数据保留政策里，哪个问题决定了当前状态？

### Events

1. `v13_data_retention_policy_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 数据保留政策 曾按“按 180 天默认保留日志”推进，并把“180 天默认政策草案”当成默认依据。

2. `v13_data_retention_policy_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 数据保留政策 新发现：敏感字段不能套用默认期限；当前状态需要重新按有效证据判断。

3. `v13_data_retention_policy_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 数据保留政策 复盘确认：政策拆分为敏感字段和聚合指标两类；旧判断不再作为当前状态。

4. `v13_data_retention_policy_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 数据保留政策 补充观察到：法务注释提示风险但不是最终批准；它只影响“法务注释”，不改变“敏感字段 30 天脱敏、聚合指标 180 天保留”。

5. `v13_data_retention_policy_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 数据保留政策 安排“提交分层保留策略审批”，目前只有排期，还没有完成记录。

6. `v13_data_retention_policy_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的“180 天默认政策草案”又声称“所有日志都可保留 180 天”，但备注说明这只是历史转述。

7. `v13_data_retention_policy_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 数据保留政策 当前风险集中在：默认期限覆盖敏感字段会带来合规风险。

8. `v13_data_retention_policy_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 数据保留政策 下一步是：先提交分层策略审批，再同步数据平台执行规则。

9. `v13_data_retention_policy_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 数据保留政策 例会只同步了“政策编号、数据表名和审批流节点”，没有更新“保留期限决策”。

10. `v13_data_retention_policy_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把数据保留政策与“产品埋点保留讨论”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_data_retention_policy_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 数据保留政策 新增“政策目录和版本号整理”，仅属流程记录，不影响状态判断。

12. `v13_data_retention_policy_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的旧阻塞“默认 180 天口径未拆分”被转述，但没有证据说明它仍然有效。

13. `v13_data_retention_policy_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 数据保留政策 加入低优先级事项“统一政策文档页眉”，不改变“敏感字段 30 天脱敏、聚合指标 180 天保留”。

14. `v13_data_retention_policy_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的历史风险“旧草案继续被作为执行依据”被复制到新文档，负责人确认只是背景。

15. `v13_data_retention_policy_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 数据保留政策 交接记录列出“敏感字段、聚合指标、审批流和执行规则”，没有新增决策。

16. `v13_data_retention_policy_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的指标快照写着“日志量统计不说明保留期限合法”，它不能单独改变当前结论。

17. `v13_data_retention_policy_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 数据保留政策 最近一次操作是“一次表名整理没有改变保留期限”，没有产生新的状态证据。

18. `v13_data_retention_policy_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 数据保留政策 仍存在证据缺口：没有证据说明审批流已通过。


### Annotation Template

```json
{
  "case_id": "v13_data_retention_policy_current_obstacle",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 28/60: v13_data_retention_policy_planned_followup

### Query

- case_id: `v13_data_retention_policy_planned_followup`
- scope_id: `data_retention_policy`
- operation: `next_action`
- query: 数据保留政策 的下一轮追踪应聚焦什么？

### Events

1. `v13_data_retention_policy_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 数据保留政策 曾按“按 180 天默认保留日志”推进，并把“180 天默认政策草案”当成默认依据。

2. `v13_data_retention_policy_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 数据保留政策 新发现：敏感字段不能套用默认期限；当前状态需要重新按有效证据判断。

3. `v13_data_retention_policy_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 数据保留政策 复盘确认：政策拆分为敏感字段和聚合指标两类；旧判断不再作为当前状态。

4. `v13_data_retention_policy_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 数据保留政策 补充观察到：法务注释提示风险但不是最终批准；它只影响“法务注释”，不改变“敏感字段 30 天脱敏、聚合指标 180 天保留”。

5. `v13_data_retention_policy_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 数据保留政策 安排“提交分层保留策略审批”，目前只有排期，还没有完成记录。

6. `v13_data_retention_policy_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的“180 天默认政策草案”又声称“所有日志都可保留 180 天”，但备注说明这只是历史转述。

7. `v13_data_retention_policy_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 数据保留政策 当前风险集中在：默认期限覆盖敏感字段会带来合规风险。

8. `v13_data_retention_policy_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 数据保留政策 下一步是：先提交分层策略审批，再同步数据平台执行规则。

9. `v13_data_retention_policy_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 数据保留政策 例会只同步了“政策编号、数据表名和审批流节点”，没有更新“保留期限决策”。

10. `v13_data_retention_policy_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把数据保留政策与“产品埋点保留讨论”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_data_retention_policy_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 数据保留政策 新增“政策目录和版本号整理”，仅属流程记录，不影响状态判断。

12. `v13_data_retention_policy_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的旧阻塞“默认 180 天口径未拆分”被转述，但没有证据说明它仍然有效。

13. `v13_data_retention_policy_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 数据保留政策 加入低优先级事项“统一政策文档页眉”，不改变“敏感字段 30 天脱敏、聚合指标 180 天保留”。

14. `v13_data_retention_policy_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的历史风险“旧草案继续被作为执行依据”被复制到新文档，负责人确认只是背景。

15. `v13_data_retention_policy_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 数据保留政策 交接记录列出“敏感字段、聚合指标、审批流和执行规则”，没有新增决策。

16. `v13_data_retention_policy_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 数据保留政策 的指标快照写着“日志量统计不说明保留期限合法”，它不能单独改变当前结论。

17. `v13_data_retention_policy_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 数据保留政策 最近一次操作是“一次表名整理没有改变保留期限”，没有产生新的状态证据。

18. `v13_data_retention_policy_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 数据保留政策 仍存在证据缺口：没有证据说明审批流已通过。


### Annotation Template

```json
{
  "case_id": "v13_data_retention_policy_planned_followup",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 29/60: v13_eval_harness_final_evidence_insufficient

### Query

- case_id: `v13_eval_harness_final_evidence_insufficient`
- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 评测 harness 是否已有“完整 baseline 主表”的可靠记录？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_eval_harness_final_evidence_insufficient",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 30/60: v13_eval_harness_planned_item_unknown

### Query

- case_id: `v13_eval_harness_planned_item_unknown`
- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 评测 harness 的“over-evidence 诊断”已经完成了吗？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_eval_harness_planned_item_unknown",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 31/60: v13_eval_harness_side_signal

### Query

- case_id: `v13_eval_harness_side_signal`
- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 评测 harness 的“judge coverage 补跑”现在会改变“sup_f1、slot_j、ans_j 主排序”吗？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_eval_harness_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 32/60: v13_grant_app_next_domain_action

### Query

- case_id: `v13_grant_app_next_domain_action`
- scope_id: `grant_app`
- operation: `next_action`
- query: 围绕经费申请，现在最该先做哪个动作？

### Events

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


### Annotation Template

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


---

## Case 33/60: v13_labeling_guideline_corrected_current_state

### Query

- case_id: `v13_labeling_guideline_corrected_current_state`
- scope_id: `labeling_guideline`
- operation: `state_lookup`
- query: 标注规范 还能按“uncertain 与 partial 分开标”理解当前状态吗？

### Events

1. `label_e1`
   - type: `guideline`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v1 将 uncertain 与 partial 分开。

2. `label_e2`
   - type: `guideline`
   - updated_at: `2026-06-03T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v2 将 uncertain 与 partial 合并为 ambiguous。

3. `label_e3`
   - type: `issue`
   - updated_at: `2026-06-04T17:00:00`
   - planned_for: `none`
   - content: QC 发现 batch A 标注分歧率 12%。

4. `label_e4`
   - type: `plan`
   - updated_at: `2026-06-05T17:00:00`
   - planned_for: `2026-06-08T10:00:00`
   - content: 计划 6月8日用 v2 规范重新培训标注员。

5. `label_e5`
   - type: `progress`
   - updated_at: `2026-06-06T17:00:00`
   - planned_for: `none`
   - content: batch A 已完成一轮标注，但还没复核。

6. `label_e6`
   - type: `mention`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: Slack 里有人转发 v1 规范截图，但管理员说明已作废。

7. `v13_labeling_guideline_01`
   - type: `decision`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 标注规范 曾按“uncertain 与 partial 分开标”推进，并把“v1 规范截图”当成默认依据。

8. `v13_labeling_guideline_02`
   - type: `issue`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 标注规范 新发现：batch A 分歧率达到 12%；当前状态需要重新按有效证据判断。

9. `v13_labeling_guideline_03`
   - type: `correction`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 标注规范 复盘确认：管理员确认 v1 作废，当前按 v2 重新培训；旧判断不再作为当前状态。

10. `v13_labeling_guideline_04`
   - type: `observation`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 标注规范 补充观察到：一轮标注完成但还没复核；它只影响“batch A 一轮标注”，不改变“合并为 ambiguous 的 v2 规范”。

11. `v13_labeling_guideline_05`
   - type: `plan`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `2026-06-10T22:00:00`
   - content: 标注规范 安排“用 v2 规范重新培训标注员”，目前只有排期，还没有完成记录。

12. `v13_labeling_guideline_06`
   - type: `mention`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 标注规范 的“v1 规范截图”又声称“uncertain 和 partial 仍需分开”，但备注说明这只是历史转述。

13. `v13_labeling_guideline_07`
   - type: `risk`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: 标注规范 当前风险集中在：旧截图让标注员继续使用 v1。

14. `v13_labeling_guideline_08`
   - type: `plan`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `2026-06-11T01:00:00`
   - content: 标注规范 下一步是：先完成 v2 培训，再复核 batch A。

15. `v13_labeling_guideline_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 标注规范 例会只同步了“标注员排班、样例编号和工单链接”，没有更新“标注规则”。

16. `v13_labeling_guideline_10`
   - type: `mention`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: 有人把标注规范与“情感标注项目”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_labeling_guideline_11`
   - type: `note`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 标注规范 新增“标注平台标签颜色调整”，仅属流程记录，不影响状态判断。

18. `v13_labeling_guideline_12`
   - type: `mention`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 标注规范 的旧阻塞“v1/v2 截图混用”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_labeling_guideline_corrected_current_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 34/60: v13_labeling_guideline_next_domain_action

### Query

- case_id: `v13_labeling_guideline_next_domain_action`
- scope_id: `labeling_guideline`
- operation: `next_action`
- query: 标注规范 继续推进前需要先处理什么？

### Events

1. `label_e1`
   - type: `guideline`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v1 将 uncertain 与 partial 分开。

2. `label_e2`
   - type: `guideline`
   - updated_at: `2026-06-03T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v2 将 uncertain 与 partial 合并为 ambiguous。

3. `label_e3`
   - type: `issue`
   - updated_at: `2026-06-04T17:00:00`
   - planned_for: `none`
   - content: QC 发现 batch A 标注分歧率 12%。

4. `label_e4`
   - type: `plan`
   - updated_at: `2026-06-05T17:00:00`
   - planned_for: `2026-06-08T10:00:00`
   - content: 计划 6月8日用 v2 规范重新培训标注员。

5. `label_e5`
   - type: `progress`
   - updated_at: `2026-06-06T17:00:00`
   - planned_for: `none`
   - content: batch A 已完成一轮标注，但还没复核。

6. `label_e6`
   - type: `mention`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: Slack 里有人转发 v1 规范截图，但管理员说明已作废。

7. `v13_labeling_guideline_01`
   - type: `decision`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 标注规范 曾按“uncertain 与 partial 分开标”推进，并把“v1 规范截图”当成默认依据。

8. `v13_labeling_guideline_02`
   - type: `issue`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 标注规范 新发现：batch A 分歧率达到 12%；当前状态需要重新按有效证据判断。

9. `v13_labeling_guideline_03`
   - type: `correction`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 标注规范 复盘确认：管理员确认 v1 作废，当前按 v2 重新培训；旧判断不再作为当前状态。

10. `v13_labeling_guideline_04`
   - type: `observation`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 标注规范 补充观察到：一轮标注完成但还没复核；它只影响“batch A 一轮标注”，不改变“合并为 ambiguous 的 v2 规范”。

11. `v13_labeling_guideline_05`
   - type: `plan`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `2026-06-10T22:00:00`
   - content: 标注规范 安排“用 v2 规范重新培训标注员”，目前只有排期，还没有完成记录。

12. `v13_labeling_guideline_06`
   - type: `mention`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 标注规范 的“v1 规范截图”又声称“uncertain 和 partial 仍需分开”，但备注说明这只是历史转述。

13. `v13_labeling_guideline_07`
   - type: `risk`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: 标注规范 当前风险集中在：旧截图让标注员继续使用 v1。

14. `v13_labeling_guideline_08`
   - type: `plan`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `2026-06-11T01:00:00`
   - content: 标注规范 下一步是：先完成 v2 培训，再复核 batch A。

15. `v13_labeling_guideline_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 标注规范 例会只同步了“标注员排班、样例编号和工单链接”，没有更新“标注规则”。

16. `v13_labeling_guideline_10`
   - type: `mention`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: 有人把标注规范与“情感标注项目”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_labeling_guideline_11`
   - type: `note`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 标注规范 新增“标注平台标签颜色调整”，仅属流程记录，不影响状态判断。

18. `v13_labeling_guideline_12`
   - type: `mention`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 标注规范 的旧阻塞“v1/v2 截图混用”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_labeling_guideline_next_domain_action",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 35/60: v13_labeling_guideline_side_signal

### Query

- case_id: `v13_labeling_guideline_side_signal`
- scope_id: `labeling_guideline`
- operation: `state_lookup`
- query: 标注规范 的“batch A 一轮标注”现在会改变“合并为 ambiguous 的 v2 规范”吗？

### Events

1. `label_e1`
   - type: `guideline`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v1 将 uncertain 与 partial 分开。

2. `label_e2`
   - type: `guideline`
   - updated_at: `2026-06-03T17:00:00`
   - planned_for: `none`
   - content: 标注规范 v2 将 uncertain 与 partial 合并为 ambiguous。

3. `label_e3`
   - type: `issue`
   - updated_at: `2026-06-04T17:00:00`
   - planned_for: `none`
   - content: QC 发现 batch A 标注分歧率 12%。

4. `label_e4`
   - type: `plan`
   - updated_at: `2026-06-05T17:00:00`
   - planned_for: `2026-06-08T10:00:00`
   - content: 计划 6月8日用 v2 规范重新培训标注员。

5. `label_e5`
   - type: `progress`
   - updated_at: `2026-06-06T17:00:00`
   - planned_for: `none`
   - content: batch A 已完成一轮标注，但还没复核。

6. `label_e6`
   - type: `mention`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: Slack 里有人转发 v1 规范截图，但管理员说明已作废。

7. `v13_labeling_guideline_01`
   - type: `decision`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 标注规范 曾按“uncertain 与 partial 分开标”推进，并把“v1 规范截图”当成默认依据。

8. `v13_labeling_guideline_02`
   - type: `issue`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 标注规范 新发现：batch A 分歧率达到 12%；当前状态需要重新按有效证据判断。

9. `v13_labeling_guideline_03`
   - type: `correction`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 标注规范 复盘确认：管理员确认 v1 作废，当前按 v2 重新培训；旧判断不再作为当前状态。

10. `v13_labeling_guideline_04`
   - type: `observation`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 标注规范 补充观察到：一轮标注完成但还没复核；它只影响“batch A 一轮标注”，不改变“合并为 ambiguous 的 v2 规范”。

11. `v13_labeling_guideline_05`
   - type: `plan`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `2026-06-10T22:00:00`
   - content: 标注规范 安排“用 v2 规范重新培训标注员”，目前只有排期，还没有完成记录。

12. `v13_labeling_guideline_06`
   - type: `mention`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 标注规范 的“v1 规范截图”又声称“uncertain 和 partial 仍需分开”，但备注说明这只是历史转述。

13. `v13_labeling_guideline_07`
   - type: `risk`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `none`
   - content: 标注规范 当前风险集中在：旧截图让标注员继续使用 v1。

14. `v13_labeling_guideline_08`
   - type: `plan`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `2026-06-11T01:00:00`
   - content: 标注规范 下一步是：先完成 v2 培训，再复核 batch A。

15. `v13_labeling_guideline_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 标注规范 例会只同步了“标注员排班、样例编号和工单链接”，没有更新“标注规则”。

16. `v13_labeling_guideline_10`
   - type: `mention`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `none`
   - content: 有人把标注规范与“情感标注项目”混在一起，随后更正说这不是本 scope 的证据。

17. `v13_labeling_guideline_11`
   - type: `note`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 标注规范 新增“标注平台标签颜色调整”，仅属流程记录，不影响状态判断。

18. `v13_labeling_guideline_12`
   - type: `mention`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 标注规范 的旧阻塞“v1/v2 截图混用”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_labeling_guideline_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 36/60: v13_mobile_auth_brief_state

### Query

- case_id: `v13_mobile_auth_brief_state`
- scope_id: `mobile_auth`
- operation: `state_summary`
- query: 如果只说当前有效状态，移动端登录 应该怎么总结？

### Events

1. `auth_e1`
   - type: `decision`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 登录方案最初采用短信 OTP。

2. `auth_e2`
   - type: `decision`
   - updated_at: `2026-06-03T12:00:00`
   - planned_for: `none`
   - content: 登录方案改为 email magic link，替代短信 OTP。

3. `auth_e3`
   - type: `issue`
   - updated_at: `2026-06-04T12:00:00`
   - planned_for: `none`
   - content: 发现 magic link 重发接口没有限流。

4. `auth_e4`
   - type: `fix`
   - updated_at: `2026-06-05T12:00:00`
   - planned_for: `none`
   - content: 已上线 magic link 重发限流修复。

5. `auth_e5`
   - type: `issue`
   - updated_at: `2026-06-06T12:00:00`
   - planned_for: `none`
   - content: 当前剩余问题是 iOS 端重发按钮偶尔不刷新倒计时。

6. `auth_e6`
   - type: `plan`
   - updated_at: `2026-06-07T12:00:00`
   - planned_for: `none`
   - content: 计划补 magic link 登录审计日志。

7. `auth_e7`
   - type: `mention`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 会议纪要里又复制了短信 OTP 旧方案，没有重新启用。

8. `v13_mobile_auth_01`
   - type: `decision`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `none`
   - content: 移动端登录 曾按“继续使用短信验证码”推进，并把“短信验证码方案纪要”当成默认依据。

9. `v13_mobile_auth_02`
   - type: `issue`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 移动端登录 新发现：iOS 重发按钮倒计时偶尔不刷新；当前状态需要重新按有效证据判断。

10. `v13_mobile_auth_03`
   - type: `correction`
   - updated_at: `2026-06-07T22:00:00`
   - planned_for: `none`
   - content: 移动端登录 复盘确认：短信验证码已被邮箱魔法链接替代；旧判断不再作为当前状态。

11. `v13_mobile_auth_04`
   - type: `observation`
   - updated_at: `2026-06-07T23:00:00`
   - planned_for: `none`
   - content: 移动端登录 补充观察到：重发限流已经上线但不等于审计日志完成；它只影响“重发限流修复”，不改变“邮箱魔法链接登录”。

12. `v13_mobile_auth_05`
   - type: `plan`
   - updated_at: `2026-06-08T00:00:00`
   - planned_for: `2026-06-11T00:00:00`
   - content: 移动端登录 安排“补登录审计日志”，目前只有排期，还没有完成记录。

13. `v13_mobile_auth_06`
   - type: `mention`
   - updated_at: `2026-06-08T01:00:00`
   - planned_for: `none`
   - content: 移动端登录 的“短信验证码方案纪要”又声称“短信验证码仍是默认方案”，但备注说明这只是历史转述。

14. `v13_mobile_auth_07`
   - type: `risk`
   - updated_at: `2026-06-08T02:00:00`
   - planned_for: `none`
   - content: 移动端登录 当前风险集中在：旧短信方案被会议纪要误认为重新启用。

15. `v13_mobile_auth_08`
   - type: `plan`
   - updated_at: `2026-06-08T03:00:00`
   - planned_for: `2026-06-11T03:00:00`
   - content: 移动端登录 下一步是：先补审计日志并复查 iOS 倒计时。

16. `v13_mobile_auth_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T04:00:00`
   - planned_for: `none`
   - content: 移动端登录 例会只同步了“登录页文案、按钮尺寸和埋点命名”，没有更新“登录方案”。

17. `v13_mobile_auth_10`
   - type: `mention`
   - updated_at: `2026-06-08T05:00:00`
   - planned_for: `none`
   - content: 有人把移动端登录与“Web 端单点登录排期”混在一起，随后更正说这不是本 scope 的证据。

18. `v13_mobile_auth_11`
   - type: `note`
   - updated_at: `2026-06-08T06:00:00`
   - planned_for: `none`
   - content: 移动端登录 新增“风控白名单导出”，仅属流程记录，不影响状态判断。


### Annotation Template

```json
{
  "case_id": "v13_mobile_auth_brief_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 37/60: v13_model_serving_latency_planned_followup

### Query

- case_id: `v13_model_serving_latency_planned_followup`
- scope_id: `model_serving_latency`
- operation: `next_action`
- query: 模型服务延迟 的下一轮追踪应聚焦什么？

### Events

1. `v13_model_serving_latency_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 曾按“按原始批量大小全量发布”推进，并把“全量发布排期单”当成默认依据。

2. `v13_model_serving_latency_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 新发现：p99 延迟在高峰流量下超过 SLA；当前状态需要重新按有效证据判断。

3. `v13_model_serving_latency_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 复盘确认：全量发布暂停，先改批量大小和降级缓存；旧判断不再作为当前状态。

4. `v13_model_serving_latency_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 补充观察到：火焰图定位瓶颈但不是发布批准；它只影响“压测火焰图”，不改变“降低批量大小并启用降级缓存”。

5. `v13_model_serving_latency_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 模型服务延迟 安排“用新批量大小做 10% 流量灰度”，目前只有排期，还没有完成记录。

6. `v13_model_serving_latency_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的“全量发布排期单”又声称“延迟已经满足全量发布”，但备注说明这只是历史转述。

7. `v13_model_serving_latency_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前风险集中在：低峰压测结果被误用到高峰流量。

8. `v13_model_serving_latency_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 模型服务延迟 下一步是：先做 10% 灰度并监控 p99，再决定扩量。

9. `v13_model_serving_latency_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 例会只同步了“压测窗口、机器规格和 dashboard 权限”，没有更新“serving 发布策略”。

10. `v13_model_serving_latency_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把模型服务延迟与“离线 embedding 任务”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_model_serving_latency_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 新增“压测报告目录和 run id 整理”，仅属流程记录，不影响状态判断。

12. `v13_model_serving_latency_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的旧阻塞“GPU 利用率波动”被转述，但没有证据说明它仍然有效。

13. `v13_model_serving_latency_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 加入低优先级事项“整理火焰图截图”，不改变“降低批量大小并启用降级缓存”。

14. `v13_model_serving_latency_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的历史风险“全量发布排期单继续被引用”被复制到新文档，负责人确认只是背景。

15. `v13_model_serving_latency_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 交接记录列出“p99、批量大小、降级缓存和灰度比例”，没有新增决策。

16. `v13_model_serving_latency_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的指标快照写着“低峰平均延迟不能代表高峰 p99”，它不能单独改变当前结论。

17. `v13_model_serving_latency_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 最近一次操作是“一次 dashboard 权限修复没有新压测”，没有产生新的状态证据。

18. `v13_model_serving_latency_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 仍存在证据缺口：没有证据说明 10% 灰度已经完成。

19. `v13_model_serving_latency_19`
   - type: `note`
   - updated_at: `2026-06-02T04:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的完成信号被定义为：灰度 p99 稳定低于 SLA。

20. `v13_model_serving_latency_20`
   - type: `check`
   - updated_at: `2026-06-02T05:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前需要围绕“serving 发布策略”保留可追溯证据，不能只看最新噪声。

21. `v13_model_serving_latency_21`
   - type: `message`
   - updated_at: `2026-06-02T06:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 依赖方只确认了日程，没有确认“灰度 p99 稳定低于 SLA”。

22. `v13_model_serving_latency_22`
   - type: `progress`
   - updated_at: `2026-06-02T07:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 已得到一个局部结果，但它只覆盖“压测火焰图”。

23. `v13_model_serving_latency_23`
   - type: `feedback`
   - updated_at: `2026-06-02T08:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 评审意见要求把“低峰压测结果被误用到高峰流量”写入当前风险说明。

24. `v13_model_serving_latency_24`
   - type: `mention`
   - updated_at: `2026-06-02T09:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 群聊再次复述“按原始批量大小全量发布”，随后被标记为旧口径。

25. `v13_model_serving_latency_25`
   - type: `task_note`
   - updated_at: `2026-06-02T10:00:00`
   - planned_for: `2026-06-05T10:00:00`
   - content: 模型服务延迟 已指定负责人跟进“用新批量大小做 10% 流量灰度”。

26. `v13_model_serving_latency_26`
   - type: `note`
   - updated_at: `2026-06-02T11:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的 scope 边界排除了“离线 embedding 任务”的证据。

27. `v13_model_serving_latency_27`
   - type: `note`
   - updated_at: `2026-06-02T12:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 证据包优先收集“p99 延迟在高峰流量下超过 SLA”和“全量发布暂停，先改批量大小和降级缓存”。

28. `v13_model_serving_latency_28`
   - type: `plan`
   - updated_at: `2026-06-02T13:00:00`
   - planned_for: `2026-06-05T13:00:00`
   - content: 模型服务延迟 排期改为先处理“先做 10% 灰度并监控 p99，再决定扩量”，再检查“灰度 p99 稳定低于 SLA”。

29. `v13_model_serving_latency_29`
   - type: `message`
   - updated_at: `2026-06-02T14:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 下游通知只同步背景，没有确认“10% 流量灰度”完成。

30. `v13_model_serving_latency_30`
   - type: `note`
   - updated_at: `2026-06-02T15:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 最终可接受状态必须看到“灰度 p99 稳定低于 SLA”的明确证据。

31. `v13_model_serving_latency_31`
   - type: `mention`
   - updated_at: `2026-06-02T16:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 已把“全量发布排期单”归档，避免继续作为当前依据。

32. `v13_model_serving_latency_32`
   - type: `note`
   - updated_at: `2026-06-02T17:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前回答应追溯到“serving 发布策略”的有效事件，而不是最近一条无更新记录。


### Annotation Template

```json
{
  "case_id": "v13_model_serving_latency_planned_followup",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 38/60: v13_model_serving_latency_primary_next_action

### Query

- case_id: `v13_model_serving_latency_primary_next_action`
- scope_id: `model_serving_latency`
- operation: `next_action`
- query: 模型服务延迟 暂时不能直接收尾的话，应先做什么？

### Events

1. `v13_model_serving_latency_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 曾按“按原始批量大小全量发布”推进，并把“全量发布排期单”当成默认依据。

2. `v13_model_serving_latency_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 新发现：p99 延迟在高峰流量下超过 SLA；当前状态需要重新按有效证据判断。

3. `v13_model_serving_latency_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 复盘确认：全量发布暂停，先改批量大小和降级缓存；旧判断不再作为当前状态。

4. `v13_model_serving_latency_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 补充观察到：火焰图定位瓶颈但不是发布批准；它只影响“压测火焰图”，不改变“降低批量大小并启用降级缓存”。

5. `v13_model_serving_latency_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 模型服务延迟 安排“用新批量大小做 10% 流量灰度”，目前只有排期，还没有完成记录。

6. `v13_model_serving_latency_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的“全量发布排期单”又声称“延迟已经满足全量发布”，但备注说明这只是历史转述。

7. `v13_model_serving_latency_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前风险集中在：低峰压测结果被误用到高峰流量。

8. `v13_model_serving_latency_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 模型服务延迟 下一步是：先做 10% 灰度并监控 p99，再决定扩量。

9. `v13_model_serving_latency_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 例会只同步了“压测窗口、机器规格和 dashboard 权限”，没有更新“serving 发布策略”。

10. `v13_model_serving_latency_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把模型服务延迟与“离线 embedding 任务”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_model_serving_latency_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 新增“压测报告目录和 run id 整理”，仅属流程记录，不影响状态判断。

12. `v13_model_serving_latency_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的旧阻塞“GPU 利用率波动”被转述，但没有证据说明它仍然有效。

13. `v13_model_serving_latency_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 加入低优先级事项“整理火焰图截图”，不改变“降低批量大小并启用降级缓存”。

14. `v13_model_serving_latency_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的历史风险“全量发布排期单继续被引用”被复制到新文档，负责人确认只是背景。

15. `v13_model_serving_latency_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 交接记录列出“p99、批量大小、降级缓存和灰度比例”，没有新增决策。

16. `v13_model_serving_latency_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的指标快照写着“低峰平均延迟不能代表高峰 p99”，它不能单独改变当前结论。

17. `v13_model_serving_latency_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 最近一次操作是“一次 dashboard 权限修复没有新压测”，没有产生新的状态证据。

18. `v13_model_serving_latency_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 仍存在证据缺口：没有证据说明 10% 灰度已经完成。

19. `v13_model_serving_latency_19`
   - type: `note`
   - updated_at: `2026-06-02T04:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的完成信号被定义为：灰度 p99 稳定低于 SLA。

20. `v13_model_serving_latency_20`
   - type: `check`
   - updated_at: `2026-06-02T05:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前需要围绕“serving 发布策略”保留可追溯证据，不能只看最新噪声。

21. `v13_model_serving_latency_21`
   - type: `message`
   - updated_at: `2026-06-02T06:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 依赖方只确认了日程，没有确认“灰度 p99 稳定低于 SLA”。

22. `v13_model_serving_latency_22`
   - type: `progress`
   - updated_at: `2026-06-02T07:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 已得到一个局部结果，但它只覆盖“压测火焰图”。

23. `v13_model_serving_latency_23`
   - type: `feedback`
   - updated_at: `2026-06-02T08:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 评审意见要求把“低峰压测结果被误用到高峰流量”写入当前风险说明。

24. `v13_model_serving_latency_24`
   - type: `mention`
   - updated_at: `2026-06-02T09:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 群聊再次复述“按原始批量大小全量发布”，随后被标记为旧口径。

25. `v13_model_serving_latency_25`
   - type: `task_note`
   - updated_at: `2026-06-02T10:00:00`
   - planned_for: `2026-06-05T10:00:00`
   - content: 模型服务延迟 已指定负责人跟进“用新批量大小做 10% 流量灰度”。

26. `v13_model_serving_latency_26`
   - type: `note`
   - updated_at: `2026-06-02T11:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的 scope 边界排除了“离线 embedding 任务”的证据。

27. `v13_model_serving_latency_27`
   - type: `note`
   - updated_at: `2026-06-02T12:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 证据包优先收集“p99 延迟在高峰流量下超过 SLA”和“全量发布暂停，先改批量大小和降级缓存”。

28. `v13_model_serving_latency_28`
   - type: `plan`
   - updated_at: `2026-06-02T13:00:00`
   - planned_for: `2026-06-05T13:00:00`
   - content: 模型服务延迟 排期改为先处理“先做 10% 灰度并监控 p99，再决定扩量”，再检查“灰度 p99 稳定低于 SLA”。

29. `v13_model_serving_latency_29`
   - type: `message`
   - updated_at: `2026-06-02T14:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 下游通知只同步背景，没有确认“10% 流量灰度”完成。

30. `v13_model_serving_latency_30`
   - type: `note`
   - updated_at: `2026-06-02T15:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 最终可接受状态必须看到“灰度 p99 稳定低于 SLA”的明确证据。

31. `v13_model_serving_latency_31`
   - type: `mention`
   - updated_at: `2026-06-02T16:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 已把“全量发布排期单”归档，避免继续作为当前依据。

32. `v13_model_serving_latency_32`
   - type: `note`
   - updated_at: `2026-06-02T17:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前回答应追溯到“serving 发布策略”的有效事件，而不是最近一条无更新记录。


### Annotation Template

```json
{
  "case_id": "v13_model_serving_latency_primary_next_action",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 39/60: v13_model_serving_latency_risk_summary

### Query

- case_id: `v13_model_serving_latency_risk_summary`
- scope_id: `model_serving_latency`
- operation: `state_summary`
- query: 模型服务延迟 当前风险和下一步如何一起说明？

### Events

1. `v13_model_serving_latency_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 曾按“按原始批量大小全量发布”推进，并把“全量发布排期单”当成默认依据。

2. `v13_model_serving_latency_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 新发现：p99 延迟在高峰流量下超过 SLA；当前状态需要重新按有效证据判断。

3. `v13_model_serving_latency_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 复盘确认：全量发布暂停，先改批量大小和降级缓存；旧判断不再作为当前状态。

4. `v13_model_serving_latency_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 补充观察到：火焰图定位瓶颈但不是发布批准；它只影响“压测火焰图”，不改变“降低批量大小并启用降级缓存”。

5. `v13_model_serving_latency_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 模型服务延迟 安排“用新批量大小做 10% 流量灰度”，目前只有排期，还没有完成记录。

6. `v13_model_serving_latency_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的“全量发布排期单”又声称“延迟已经满足全量发布”，但备注说明这只是历史转述。

7. `v13_model_serving_latency_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前风险集中在：低峰压测结果被误用到高峰流量。

8. `v13_model_serving_latency_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 模型服务延迟 下一步是：先做 10% 灰度并监控 p99，再决定扩量。

9. `v13_model_serving_latency_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 例会只同步了“压测窗口、机器规格和 dashboard 权限”，没有更新“serving 发布策略”。

10. `v13_model_serving_latency_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把模型服务延迟与“离线 embedding 任务”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_model_serving_latency_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 新增“压测报告目录和 run id 整理”，仅属流程记录，不影响状态判断。

12. `v13_model_serving_latency_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的旧阻塞“GPU 利用率波动”被转述，但没有证据说明它仍然有效。

13. `v13_model_serving_latency_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 加入低优先级事项“整理火焰图截图”，不改变“降低批量大小并启用降级缓存”。

14. `v13_model_serving_latency_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的历史风险“全量发布排期单继续被引用”被复制到新文档，负责人确认只是背景。

15. `v13_model_serving_latency_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 交接记录列出“p99、批量大小、降级缓存和灰度比例”，没有新增决策。

16. `v13_model_serving_latency_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的指标快照写着“低峰平均延迟不能代表高峰 p99”，它不能单独改变当前结论。

17. `v13_model_serving_latency_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 最近一次操作是“一次 dashboard 权限修复没有新压测”，没有产生新的状态证据。

18. `v13_model_serving_latency_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 仍存在证据缺口：没有证据说明 10% 灰度已经完成。

19. `v13_model_serving_latency_19`
   - type: `note`
   - updated_at: `2026-06-02T04:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的完成信号被定义为：灰度 p99 稳定低于 SLA。

20. `v13_model_serving_latency_20`
   - type: `check`
   - updated_at: `2026-06-02T05:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前需要围绕“serving 发布策略”保留可追溯证据，不能只看最新噪声。

21. `v13_model_serving_latency_21`
   - type: `message`
   - updated_at: `2026-06-02T06:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 依赖方只确认了日程，没有确认“灰度 p99 稳定低于 SLA”。

22. `v13_model_serving_latency_22`
   - type: `progress`
   - updated_at: `2026-06-02T07:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 已得到一个局部结果，但它只覆盖“压测火焰图”。

23. `v13_model_serving_latency_23`
   - type: `feedback`
   - updated_at: `2026-06-02T08:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 评审意见要求把“低峰压测结果被误用到高峰流量”写入当前风险说明。

24. `v13_model_serving_latency_24`
   - type: `mention`
   - updated_at: `2026-06-02T09:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 群聊再次复述“按原始批量大小全量发布”，随后被标记为旧口径。

25. `v13_model_serving_latency_25`
   - type: `task_note`
   - updated_at: `2026-06-02T10:00:00`
   - planned_for: `2026-06-05T10:00:00`
   - content: 模型服务延迟 已指定负责人跟进“用新批量大小做 10% 流量灰度”。

26. `v13_model_serving_latency_26`
   - type: `note`
   - updated_at: `2026-06-02T11:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 的 scope 边界排除了“离线 embedding 任务”的证据。

27. `v13_model_serving_latency_27`
   - type: `note`
   - updated_at: `2026-06-02T12:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 证据包优先收集“p99 延迟在高峰流量下超过 SLA”和“全量发布暂停，先改批量大小和降级缓存”。

28. `v13_model_serving_latency_28`
   - type: `plan`
   - updated_at: `2026-06-02T13:00:00`
   - planned_for: `2026-06-05T13:00:00`
   - content: 模型服务延迟 排期改为先处理“先做 10% 灰度并监控 p99，再决定扩量”，再检查“灰度 p99 稳定低于 SLA”。

29. `v13_model_serving_latency_29`
   - type: `message`
   - updated_at: `2026-06-02T14:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 下游通知只同步背景，没有确认“10% 流量灰度”完成。

30. `v13_model_serving_latency_30`
   - type: `note`
   - updated_at: `2026-06-02T15:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 最终可接受状态必须看到“灰度 p99 稳定低于 SLA”的明确证据。

31. `v13_model_serving_latency_31`
   - type: `mention`
   - updated_at: `2026-06-02T16:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 已把“全量发布排期单”归档，避免继续作为当前依据。

32. `v13_model_serving_latency_32`
   - type: `note`
   - updated_at: `2026-06-02T17:00:00`
   - planned_for: `none`
   - content: 模型服务延迟 当前回答应追溯到“serving 发布策略”的有效事件，而不是最近一条无更新记录。


### Annotation Template

```json
{
  "case_id": "v13_model_serving_latency_risk_summary",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 40/60: v13_onboarding_flow_corrected_decision

### Query

- case_id: `v13_onboarding_flow_corrected_decision`
- scope_id: `onboarding_flow`
- operation: `state_lookup`
- query: 当前判断新用户引导流程时，能不能继续引用“把教程弹窗直接推全量”？

### Events

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


### Annotation Template

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


---

## Case 41/60: v13_privacy_audit_compact_summary

### Query

- case_id: `v13_privacy_audit_compact_summary`
- scope_id: `privacy_audit`
- operation: `state_summary`
- query: 隐私审计 当前状态用一句话怎么概括？

### Events

1. `v13_privacy_audit_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 隐私审计 曾按“沿用旧数据保留例外”推进，并把“旧例外审批邮件”当成默认依据。

2. `v13_privacy_audit_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 隐私审计 新发现：审批邮件没有覆盖新增日志字段；当前状态需要重新按有效证据判断。

3. `v13_privacy_audit_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 隐私审计 复盘确认：旧例外失效，新增日志字段需重新评估；旧判断不再作为当前状态。

4. `v13_privacy_audit_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 隐私审计 补充观察到：目录扫描只列出字段，不构成审批；它只影响“数据目录扫描”，不改变“删除无依据的长期保留例外”。

5. `v13_privacy_audit_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 隐私审计 安排“补做新增字段的隐私影响评估”，目前只有排期，还没有完成记录。

6. `v13_privacy_audit_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 隐私审计 的“旧例外审批邮件”又声称“长期保留例外仍然有效”，但备注说明这只是历史转述。

7. `v13_privacy_audit_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 隐私审计 当前风险集中在：旧审批被误用于新字段。

8. `v13_privacy_audit_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 隐私审计 下一步是：先完成隐私影响评估，再决定是否保留字段。

9. `v13_privacy_audit_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 隐私审计 例会只同步了“审计会议编号、DPO 日程和表格模板”，没有更新“审计整改状态”。

10. `v13_privacy_audit_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把隐私审计与“安全漏洞扫描”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_privacy_audit_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 隐私审计 新增“证据包目录和截图编号”，仅属流程记录，不影响状态判断。

12. `v13_privacy_audit_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 隐私审计 的旧阻塞“旧例外审批边界不清”被转述，但没有证据说明它仍然有效。

13. `v13_privacy_audit_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 隐私审计 加入低优先级事项“整理审计证据包目录”，不改变“删除无依据的长期保留例外”。

14. `v13_privacy_audit_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 隐私审计 的历史风险“旧审批邮件继续被转发”被复制到新文档，负责人确认只是背景。

15. `v13_privacy_audit_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 隐私审计 交接记录列出“新增日志字段、例外审批和 DPO 评估”，没有新增决策。

16. `v13_privacy_audit_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 隐私审计 的指标快照写着“扫描通过率不代表隐私审批通过”，它不能单独改变当前结论。

17. `v13_privacy_audit_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 隐私审计 最近一次操作是“一次目录扫描没有新增审批结论”，没有产生新的状态证据。

18. `v13_privacy_audit_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 隐私审计 仍存在证据缺口：没有证据说明 DPO 已批准。


### Annotation Template

```json
{
  "case_id": "v13_privacy_audit_compact_summary",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 42/60: v13_privacy_audit_current_obstacle

### Query

- case_id: `v13_privacy_audit_current_obstacle`
- scope_id: `privacy_audit`
- operation: `state_lookup`
- query: 隐私审计 当前真正需要处理的问题是什么？

### Events

1. `v13_privacy_audit_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 隐私审计 曾按“沿用旧数据保留例外”推进，并把“旧例外审批邮件”当成默认依据。

2. `v13_privacy_audit_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 隐私审计 新发现：审批邮件没有覆盖新增日志字段；当前状态需要重新按有效证据判断。

3. `v13_privacy_audit_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 隐私审计 复盘确认：旧例外失效，新增日志字段需重新评估；旧判断不再作为当前状态。

4. `v13_privacy_audit_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 隐私审计 补充观察到：目录扫描只列出字段，不构成审批；它只影响“数据目录扫描”，不改变“删除无依据的长期保留例外”。

5. `v13_privacy_audit_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 隐私审计 安排“补做新增字段的隐私影响评估”，目前只有排期，还没有完成记录。

6. `v13_privacy_audit_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 隐私审计 的“旧例外审批邮件”又声称“长期保留例外仍然有效”，但备注说明这只是历史转述。

7. `v13_privacy_audit_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 隐私审计 当前风险集中在：旧审批被误用于新字段。

8. `v13_privacy_audit_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 隐私审计 下一步是：先完成隐私影响评估，再决定是否保留字段。

9. `v13_privacy_audit_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 隐私审计 例会只同步了“审计会议编号、DPO 日程和表格模板”，没有更新“审计整改状态”。

10. `v13_privacy_audit_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把隐私审计与“安全漏洞扫描”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_privacy_audit_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 隐私审计 新增“证据包目录和截图编号”，仅属流程记录，不影响状态判断。

12. `v13_privacy_audit_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 隐私审计 的旧阻塞“旧例外审批边界不清”被转述，但没有证据说明它仍然有效。

13. `v13_privacy_audit_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 隐私审计 加入低优先级事项“整理审计证据包目录”，不改变“删除无依据的长期保留例外”。

14. `v13_privacy_audit_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 隐私审计 的历史风险“旧审批邮件继续被转发”被复制到新文档，负责人确认只是背景。

15. `v13_privacy_audit_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 隐私审计 交接记录列出“新增日志字段、例外审批和 DPO 评估”，没有新增决策。

16. `v13_privacy_audit_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 隐私审计 的指标快照写着“扫描通过率不代表隐私审批通过”，它不能单独改变当前结论。

17. `v13_privacy_audit_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 隐私审计 最近一次操作是“一次目录扫描没有新增审批结论”，没有产生新的状态证据。

18. `v13_privacy_audit_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 隐私审计 仍存在证据缺口：没有证据说明 DPO 已批准。


### Annotation Template

```json
{
  "case_id": "v13_privacy_audit_current_obstacle",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 43/60: v13_release_notes_final_evidence_insufficient

### Query

- case_id: `v13_release_notes_final_evidence_insufficient`
- scope_id: `release_notes`
- operation: `state_lookup`
- query: 发布说明 是否已有“发布负责人签字”的可靠记录？

### Events

1. `v13_release_notes_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 发布说明 曾按“直接发布自动生成 changelog”推进，并把“机器人生成的 changelog 草稿”当成默认依据。

2. `v13_release_notes_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 发布说明 新发现：迁移步骤缺少配置字段重命名说明；当前状态需要重新按有效证据判断。

3. `v13_release_notes_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 发布说明 复盘确认：发布说明改为先人工核对再发布；旧判断不再作为当前状态。

4. `v13_release_notes_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 发布说明 补充观察到：自动条目只覆盖 commit 标题；它只影响“自动生成条目”，不改变“手动核对 breaking changes 和迁移步骤”。

5. `v13_release_notes_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 发布说明 安排“补配置字段迁移说明”，目前只有排期，还没有完成记录。

6. `v13_release_notes_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 发布说明 的“机器人生成的 changelog 草稿”又声称“所有 breaking changes 已覆盖”，但备注说明这只是历史转述。

7. `v13_release_notes_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 发布说明 当前风险集中在：用户按旧字段升级会启动失败。

8. `v13_release_notes_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 发布说明 下一步是：先补迁移步骤，再让负责人复核 release notes。

9. `v13_release_notes_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 发布说明 例会只同步了“版本号、发布日期和截图尺寸”，没有更新“发布说明准确性”。

10. `v13_release_notes_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把发布说明与“内部 SDK 预发公告”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_release_notes_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 发布说明 新增“release checklist 复选框整理”，仅属流程记录，不影响状态判断。

12. `v13_release_notes_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 发布说明 的旧阻塞“自动 changelog 漏掉破坏性变更”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_release_notes_final_evidence_insufficient",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 44/60: v13_release_notes_finish_condition_next

### Query

- case_id: `v13_release_notes_finish_condition_next`
- scope_id: `release_notes`
- operation: `next_action`
- query: 要判断发布说明可以收尾，接下来需要看哪个完成信号？

### Events

1. `v13_release_notes_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 发布说明 曾按“直接发布自动生成 changelog”推进，并把“机器人生成的 changelog 草稿”当成默认依据。

2. `v13_release_notes_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 发布说明 新发现：迁移步骤缺少配置字段重命名说明；当前状态需要重新按有效证据判断。

3. `v13_release_notes_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 发布说明 复盘确认：发布说明改为先人工核对再发布；旧判断不再作为当前状态。

4. `v13_release_notes_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 发布说明 补充观察到：自动条目只覆盖 commit 标题；它只影响“自动生成条目”，不改变“手动核对 breaking changes 和迁移步骤”。

5. `v13_release_notes_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 发布说明 安排“补配置字段迁移说明”，目前只有排期，还没有完成记录。

6. `v13_release_notes_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 发布说明 的“机器人生成的 changelog 草稿”又声称“所有 breaking changes 已覆盖”，但备注说明这只是历史转述。

7. `v13_release_notes_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 发布说明 当前风险集中在：用户按旧字段升级会启动失败。

8. `v13_release_notes_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 发布说明 下一步是：先补迁移步骤，再让负责人复核 release notes。

9. `v13_release_notes_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 发布说明 例会只同步了“版本号、发布日期和截图尺寸”，没有更新“发布说明准确性”。

10. `v13_release_notes_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把发布说明与“内部 SDK 预发公告”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_release_notes_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 发布说明 新增“release checklist 复选框整理”，仅属流程记录，不影响状态判断。

12. `v13_release_notes_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 发布说明 的旧阻塞“自动 changelog 漏掉破坏性变更”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_release_notes_finish_condition_next",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 45/60: v13_release_notes_planned_followup

### Query

- case_id: `v13_release_notes_planned_followup`
- scope_id: `release_notes`
- operation: `next_action`
- query: 发布说明 的下一轮追踪应聚焦什么？

### Events

1. `v13_release_notes_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 发布说明 曾按“直接发布自动生成 changelog”推进，并把“机器人生成的 changelog 草稿”当成默认依据。

2. `v13_release_notes_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 发布说明 新发现：迁移步骤缺少配置字段重命名说明；当前状态需要重新按有效证据判断。

3. `v13_release_notes_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 发布说明 复盘确认：发布说明改为先人工核对再发布；旧判断不再作为当前状态。

4. `v13_release_notes_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 发布说明 补充观察到：自动条目只覆盖 commit 标题；它只影响“自动生成条目”，不改变“手动核对 breaking changes 和迁移步骤”。

5. `v13_release_notes_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 发布说明 安排“补配置字段迁移说明”，目前只有排期，还没有完成记录。

6. `v13_release_notes_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 发布说明 的“机器人生成的 changelog 草稿”又声称“所有 breaking changes 已覆盖”，但备注说明这只是历史转述。

7. `v13_release_notes_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 发布说明 当前风险集中在：用户按旧字段升级会启动失败。

8. `v13_release_notes_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 发布说明 下一步是：先补迁移步骤，再让负责人复核 release notes。

9. `v13_release_notes_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 发布说明 例会只同步了“版本号、发布日期和截图尺寸”，没有更新“发布说明准确性”。

10. `v13_release_notes_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把发布说明与“内部 SDK 预发公告”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_release_notes_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 发布说明 新增“release checklist 复选框整理”，仅属流程记录，不影响状态判断。

12. `v13_release_notes_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 发布说明 的旧阻塞“自动 changelog 漏掉破坏性变更”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_release_notes_planned_followup",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 46/60: v13_robot_nav_final_evidence_insufficient

### Query

- case_id: `v13_robot_nav_final_evidence_insufficient`
- scope_id: `robot_nav`
- operation: `state_lookup`
- query: 机器人导航方案 的“最终场地验收”现在有明确证据吗？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_robot_nav_final_evidence_insufficient",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 47/60: v13_robot_nav_side_signal

### Query

- case_id: `v13_robot_nav_side_signal`
- scope_id: `robot_nav`
- operation: `state_lookup`
- query: 判断机器人导航方案时，“夜间仿真日志”应不应该覆盖“激光雷达加深度相机融合”？

### Events

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


### Annotation Template

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


---

## Case 48/60: v13_search_index_rollout_next_domain_action

### Query

- case_id: `v13_search_index_rollout_next_domain_action`
- scope_id: `search_index_rollout`
- operation: `next_action`
- query: 围绕搜索索引上线，现在最该先做哪个动作？

### Events

1. `idx_e1`
   - type: `decision`
   - updated_at: `2026-06-01T09:00:00`
   - planned_for: `none`
   - content: 搜索索引项目最初决定上线 BM25 patch，并把 tokenizer v1 作为默认方案。

2. `idx_e2`
   - type: `issue`
   - updated_at: `2026-06-02T10:00:00`
   - planned_for: `none`
   - content: 线上抽样发现中文长查询召回下降，主要集中在 synonym expansion 后的多词问题。

3. `idx_e3`
   - type: `plan`
   - updated_at: `2026-06-03T09:30:00`
   - planned_for: `2026-06-06T09:00:00`
   - content: 计划 6 月 6 日先部署 BM25 patch，再观察 recall dashboard。

4. `idx_e4`
   - type: `mention`
   - updated_at: `2026-06-04T11:00:00`
   - planned_for: `none`
   - content: 旧 dashboard 截图显示 BM25 patch 已经 rollout finished，但截图来自过期环境。

5. `idx_e5`
   - type: `correction`
   - updated_at: `2026-06-05T16:00:00`
   - planned_for: `none`
   - content: 复盘确认 BM25 patch 没有部署，方案改为 hybrid sparse+dense 检索；旧 dashboard 截图作废。

6. `idx_e6`
   - type: `issue`
   - updated_at: `2026-06-06T17:00:00`
   - planned_for: `none`
   - content: hybrid 检索召回恢复，但 reranker p95 延迟超过预算 180ms。

7. `idx_e7`
   - type: `plan`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `2026-06-10T10:00:00`
   - content: 下一步计划在 6 月 10 日评估更小的 cross-encoder，目前还没有完成记录。

8. `idx_e8`
   - type: `mention`
   - updated_at: `2026-06-08T12:00:00`
   - planned_for: `none`
   - content: 有人再次询问 BM25 patch 是否已经上线，回复是没有上线，只保留 hybrid 方向。

9. `v13_search_index_rollout_01`
   - type: `decision`
   - updated_at: `2026-06-08T13:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 曾按“上线 BM25 patch”推进，并把“BM25 rollout 截图”当成默认依据。

10. `v13_search_index_rollout_02`
   - type: `issue`
   - updated_at: `2026-06-08T14:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 新发现：reranker p95 延迟超过 180ms 预算；当前状态需要重新按有效证据判断。

11. `v13_search_index_rollout_03`
   - type: `correction`
   - updated_at: `2026-06-08T15:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 复盘确认：BM25 patch 未部署，方向改为 hybrid 检索；旧判断不再作为当前状态。

12. `v13_search_index_rollout_04`
   - type: `observation`
   - updated_at: `2026-06-08T16:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 补充观察到：旧截图来自过期环境；它只影响“旧 dashboard 截图”，不改变“hybrid sparse+dense 检索”。

13. `v13_search_index_rollout_05`
   - type: `plan`
   - updated_at: `2026-06-08T17:00:00`
   - planned_for: `2026-06-11T17:00:00`
   - content: 搜索索引上线 安排“评估更小的 cross-encoder”，目前只有排期，还没有完成记录。

14. `v13_search_index_rollout_06`
   - type: `mention`
   - updated_at: `2026-06-08T18:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 的“BM25 rollout 截图”又声称“BM25 patch 已上线完成”，但备注说明这只是历史转述。

15. `v13_search_index_rollout_07`
   - type: `risk`
   - updated_at: `2026-06-08T19:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 当前风险集中在：过期截图会被误读成已上线。

16. `v13_search_index_rollout_08`
   - type: `plan`
   - updated_at: `2026-06-08T20:00:00`
   - planned_for: `2026-06-11T20:00:00`
   - content: 搜索索引上线 下一步是：先压低 reranker 延迟，再决定上线窗口。

17. `v13_search_index_rollout_09`
   - type: `meeting_note`
   - updated_at: `2026-06-08T21:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 例会只同步了“索引命名、dashboard 链接和回滚联系人”，没有更新“检索上线方案”。

18. `v13_search_index_rollout_10`
   - type: `mention`
   - updated_at: `2026-06-08T22:00:00`
   - planned_for: `none`
   - content: 有人把搜索索引上线与“广告搜索索引项目”混在一起，随后更正说这不是本 scope 的证据。

19. `v13_search_index_rollout_11`
   - type: `note`
   - updated_at: `2026-06-08T23:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 新增“索引别名和监控链接整理”，仅属流程记录，不影响状态判断。

20. `v13_search_index_rollout_12`
   - type: `mention`
   - updated_at: `2026-06-09T00:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 的旧阻塞“BM25 patch 排期未确认”被转述，但没有证据说明它仍然有效。

21. `v13_search_index_rollout_13`
   - type: `task_note`
   - updated_at: `2026-06-09T01:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 加入低优先级事项“清理旧 dashboard 收藏夹”，不改变“hybrid sparse+dense 检索”。

22. `v13_search_index_rollout_14`
   - type: `mention`
   - updated_at: `2026-06-09T02:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 的历史风险“中文长查询召回下降”被复制到新文档，负责人确认只是背景。

23. `v13_search_index_rollout_15`
   - type: `meeting_note`
   - updated_at: `2026-06-09T03:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 交接记录列出“BM25、hybrid、reranker 延迟和 cross-encoder 评估”，没有新增决策。

24. `v13_search_index_rollout_16`
   - type: `observation`
   - updated_at: `2026-06-09T04:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 的指标快照写着“旧 dashboard 仍显示 rollout finished”，它不能单独改变当前结论。

25. `v13_search_index_rollout_17`
   - type: `execution_log`
   - updated_at: `2026-06-09T05:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 最近一次操作是“一次 dashboard 权限修复没有新召回结果”，没有产生新的状态证据。

26. `v13_search_index_rollout_18`
   - type: `note`
   - updated_at: `2026-06-09T06:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 仍存在证据缺口：没有证据说明小 cross-encoder 评估完成。

27. `v13_search_index_rollout_19`
   - type: `note`
   - updated_at: `2026-06-09T07:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 的完成信号被定义为：hybrid 方案满足召回和延迟门槛。

28. `v13_search_index_rollout_20`
   - type: `check`
   - updated_at: `2026-06-09T08:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 当前需要围绕“检索上线方案”保留可追溯证据，不能只看最新噪声。

29. `v13_search_index_rollout_21`
   - type: `message`
   - updated_at: `2026-06-09T09:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 依赖方只确认了日程，没有确认“hybrid 方案满足召回和延迟门槛”。

30. `v13_search_index_rollout_22`
   - type: `progress`
   - updated_at: `2026-06-09T10:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 已得到一个局部结果，但它只覆盖“旧 dashboard 截图”。

31. `v13_search_index_rollout_23`
   - type: `feedback`
   - updated_at: `2026-06-09T11:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 评审意见要求把“过期截图会被误读成已上线”写入当前风险说明。

32. `v13_search_index_rollout_24`
   - type: `mention`
   - updated_at: `2026-06-09T12:00:00`
   - planned_for: `none`
   - content: 搜索索引上线 群聊再次复述“上线 BM25 patch”，随后被标记为旧口径。


### Annotation Template

```json
{
  "case_id": "v13_search_index_rollout_next_domain_action",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 49/60: v13_sensor_firmware_corrected_decision

### Query

- case_id: `v13_sensor_firmware_corrected_decision`
- scope_id: `sensor_firmware`
- operation: `state_lookup`
- query: 传感器固件 还应该沿用“按 1.4.2 固件直接量产”吗？

### Events

1. `v13_sensor_firmware_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 传感器固件 曾按“按 1.4.2 固件直接量产”推进，并把“1.4.2 量产候选记录”当成默认依据。

2. `v13_sensor_firmware_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 传感器固件 新发现：低温场景零点漂移超过阈值；当前状态需要重新按有效证据判断。

3. `v13_sensor_firmware_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 传感器固件 复盘确认：1.4.2 量产暂停，需修温漂补偿；旧判断不再作为当前状态。

4. `v13_sensor_firmware_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 传感器固件 补充观察到：温箱日志暴露漂移但不是修复结果；它只影响“实验室温箱日志”，不改变“修正温漂补偿后再做量产候选”。

5. `v13_sensor_firmware_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 传感器固件 安排“重算温漂补偿系数并烧录 1.4.3 候选”，目前只有排期，还没有完成记录。

6. `v13_sensor_firmware_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 传感器固件 的“1.4.2 量产候选记录”又声称“1.4.2 已可量产”，但备注说明这只是历史转述。

7. `v13_sensor_firmware_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 传感器固件 当前风险集中在：忽略低温漂移会导致量产返工。

8. `v13_sensor_firmware_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 传感器固件 下一步是：先重算补偿系数，再跑低温回归。

9. `v13_sensor_firmware_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 传感器固件 例会只同步了“设备编号、烧录批次和测试台账”，没有更新“固件发布状态”。

10. `v13_sensor_firmware_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把传感器固件与“电池管理固件”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_sensor_firmware_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 传感器固件 新增“烧录记录和设备标签整理”，仅属流程记录，不影响状态判断。

12. `v13_sensor_firmware_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 传感器固件 的旧阻塞“1.4.2 量产窗口已排期”被转述，但没有证据说明它仍然有效。

13. `v13_sensor_firmware_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 传感器固件 加入低优先级事项“整理温箱曲线截图”，不改变“修正温漂补偿后再做量产候选”。

14. `v13_sensor_firmware_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 传感器固件 的历史风险“1.4.2 候选记录继续被引用”被复制到新文档，负责人确认只是背景。

15. `v13_sensor_firmware_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 传感器固件 交接记录列出“温漂补偿、低温回归和烧录批次”，没有新增决策。

16. `v13_sensor_firmware_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 传感器固件 的指标快照写着“常温通过率不覆盖低温漂移”，它不能单独改变当前结论。

17. `v13_sensor_firmware_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 传感器固件 最近一次操作是“一次台账整理没有新固件”，没有产生新的状态证据。

18. `v13_sensor_firmware_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 传感器固件 仍存在证据缺口：没有证据说明 1.4.3 已通过低温回归。


### Annotation Template

```json
{
  "case_id": "v13_sensor_firmware_corrected_decision",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 50/60: v13_sensor_firmware_finish_condition_next

### Query

- case_id: `v13_sensor_firmware_finish_condition_next`
- scope_id: `sensor_firmware`
- operation: `next_action`
- query: 要判断传感器固件可以收尾，接下来需要看哪个完成信号？

### Events

1. `v13_sensor_firmware_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 传感器固件 曾按“按 1.4.2 固件直接量产”推进，并把“1.4.2 量产候选记录”当成默认依据。

2. `v13_sensor_firmware_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 传感器固件 新发现：低温场景零点漂移超过阈值；当前状态需要重新按有效证据判断。

3. `v13_sensor_firmware_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 传感器固件 复盘确认：1.4.2 量产暂停，需修温漂补偿；旧判断不再作为当前状态。

4. `v13_sensor_firmware_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 传感器固件 补充观察到：温箱日志暴露漂移但不是修复结果；它只影响“实验室温箱日志”，不改变“修正温漂补偿后再做量产候选”。

5. `v13_sensor_firmware_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 传感器固件 安排“重算温漂补偿系数并烧录 1.4.3 候选”，目前只有排期，还没有完成记录。

6. `v13_sensor_firmware_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 传感器固件 的“1.4.2 量产候选记录”又声称“1.4.2 已可量产”，但备注说明这只是历史转述。

7. `v13_sensor_firmware_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 传感器固件 当前风险集中在：忽略低温漂移会导致量产返工。

8. `v13_sensor_firmware_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 传感器固件 下一步是：先重算补偿系数，再跑低温回归。

9. `v13_sensor_firmware_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 传感器固件 例会只同步了“设备编号、烧录批次和测试台账”，没有更新“固件发布状态”。

10. `v13_sensor_firmware_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把传感器固件与“电池管理固件”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_sensor_firmware_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 传感器固件 新增“烧录记录和设备标签整理”，仅属流程记录，不影响状态判断。

12. `v13_sensor_firmware_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 传感器固件 的旧阻塞“1.4.2 量产窗口已排期”被转述，但没有证据说明它仍然有效。

13. `v13_sensor_firmware_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 传感器固件 加入低优先级事项“整理温箱曲线截图”，不改变“修正温漂补偿后再做量产候选”。

14. `v13_sensor_firmware_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 传感器固件 的历史风险“1.4.2 候选记录继续被引用”被复制到新文档，负责人确认只是背景。

15. `v13_sensor_firmware_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 传感器固件 交接记录列出“温漂补偿、低温回归和烧录批次”，没有新增决策。

16. `v13_sensor_firmware_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 传感器固件 的指标快照写着“常温通过率不覆盖低温漂移”，它不能单独改变当前结论。

17. `v13_sensor_firmware_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 传感器固件 最近一次操作是“一次台账整理没有新固件”，没有产生新的状态证据。

18. `v13_sensor_firmware_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 传感器固件 仍存在证据缺口：没有证据说明 1.4.3 已通过低温回归。


### Annotation Template

```json
{
  "case_id": "v13_sensor_firmware_finish_condition_next",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 51/60: v13_sql_lab_q6_planned_item_unknown

### Query

- case_id: `v13_sql_lab_q6_planned_item_unknown`
- scope_id: `sql_lab_q6`
- operation: `state_lookup`
- query: 第六题 SQL 的“样例输出核对”已经完成了吗？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_sql_lab_q6_planned_item_unknown",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 52/60: v13_sql_lab_q6_side_signal

### Query

- case_id: `v13_sql_lab_q6_side_signal`
- scope_id: `sql_lab_q6`
- operation: `state_lookup`
- query: 第六题 SQL 的“一次无逻辑变更的运行日志”现在会改变“Department 与 Project 连接逻辑”吗？

### Events

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


### Annotation Template

```json
{
  "case_id": "v13_sql_lab_q6_side_signal",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 53/60: v13_support_escalation_compact_summary

### Query

- case_id: `v13_support_escalation_compact_summary`
- scope_id: `support_escalation`
- operation: `state_summary`
- query: 客服升级工单 当前状态用一句话怎么概括？

### Events

1. `v13_support_escalation_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 客服升级工单 曾按“按普通退款问题处理”推进，并把“普通退款模板回复”当成默认依据。

2. `v13_support_escalation_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新发现：支付成功但权益没有入账；当前状态需要重新按有效证据判断。

3. `v13_support_escalation_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 客服升级工单 复盘确认：工单升级为支付回调排查，不再走普通退款模板；旧判断不再作为当前状态。

4. `v13_support_escalation_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 客服升级工单 补充观察到：截图帮助定位订单但不代表问题关闭；它只影响“用户补充截图”，不改变“支付回调丢失导致的账户权益缺失”。

5. `v13_support_escalation_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 客服升级工单 安排“让支付平台补发回调并核对权益”，目前只有排期，还没有完成记录。

6. `v13_support_escalation_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的“普通退款模板回复”又声称“用户只是要求退款”，但备注说明这只是历史转述。

7. `v13_support_escalation_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 客服升级工单 当前风险集中在：继续套退款模板会错过真实故障。

8. `v13_support_escalation_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 客服升级工单 下一步是：先补发回调，再确认用户权益到账。

9. `v13_support_escalation_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 客服升级工单 例会只同步了“工单标签、客服班次和 SLA 备注”，没有更新“工单升级状态”。

10. `v13_support_escalation_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把客服升级工单与“另一个优惠券退款工单”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_support_escalation_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新增“工单标签和宏回复清理”，仅属流程记录，不影响状态判断。

12. `v13_support_escalation_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的旧阻塞“客服无法看到支付平台回调”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_support_escalation_compact_summary",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 54/60: v13_support_escalation_corrected_decision

### Query

- case_id: `v13_support_escalation_corrected_decision`
- scope_id: `support_escalation`
- operation: `state_lookup`
- query: 当前判断客服升级工单时，能不能继续引用“按普通退款问题处理”？

### Events

1. `v13_support_escalation_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 客服升级工单 曾按“按普通退款问题处理”推进，并把“普通退款模板回复”当成默认依据。

2. `v13_support_escalation_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新发现：支付成功但权益没有入账；当前状态需要重新按有效证据判断。

3. `v13_support_escalation_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 客服升级工单 复盘确认：工单升级为支付回调排查，不再走普通退款模板；旧判断不再作为当前状态。

4. `v13_support_escalation_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 客服升级工单 补充观察到：截图帮助定位订单但不代表问题关闭；它只影响“用户补充截图”，不改变“支付回调丢失导致的账户权益缺失”。

5. `v13_support_escalation_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 客服升级工单 安排“让支付平台补发回调并核对权益”，目前只有排期，还没有完成记录。

6. `v13_support_escalation_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的“普通退款模板回复”又声称“用户只是要求退款”，但备注说明这只是历史转述。

7. `v13_support_escalation_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 客服升级工单 当前风险集中在：继续套退款模板会错过真实故障。

8. `v13_support_escalation_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 客服升级工单 下一步是：先补发回调，再确认用户权益到账。

9. `v13_support_escalation_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 客服升级工单 例会只同步了“工单标签、客服班次和 SLA 备注”，没有更新“工单升级状态”。

10. `v13_support_escalation_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把客服升级工单与“另一个优惠券退款工单”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_support_escalation_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新增“工单标签和宏回复清理”，仅属流程记录，不影响状态判断。

12. `v13_support_escalation_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的旧阻塞“客服无法看到支付平台回调”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_support_escalation_corrected_decision",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 55/60: v13_support_escalation_current_obstacle

### Query

- case_id: `v13_support_escalation_current_obstacle`
- scope_id: `support_escalation`
- operation: `state_lookup`
- query: 客服升级工单 当前真正需要处理的问题是什么？

### Events

1. `v13_support_escalation_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 客服升级工单 曾按“按普通退款问题处理”推进，并把“普通退款模板回复”当成默认依据。

2. `v13_support_escalation_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新发现：支付成功但权益没有入账；当前状态需要重新按有效证据判断。

3. `v13_support_escalation_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 客服升级工单 复盘确认：工单升级为支付回调排查，不再走普通退款模板；旧判断不再作为当前状态。

4. `v13_support_escalation_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 客服升级工单 补充观察到：截图帮助定位订单但不代表问题关闭；它只影响“用户补充截图”，不改变“支付回调丢失导致的账户权益缺失”。

5. `v13_support_escalation_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 客服升级工单 安排“让支付平台补发回调并核对权益”，目前只有排期，还没有完成记录。

6. `v13_support_escalation_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的“普通退款模板回复”又声称“用户只是要求退款”，但备注说明这只是历史转述。

7. `v13_support_escalation_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 客服升级工单 当前风险集中在：继续套退款模板会错过真实故障。

8. `v13_support_escalation_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 客服升级工单 下一步是：先补发回调，再确认用户权益到账。

9. `v13_support_escalation_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 客服升级工单 例会只同步了“工单标签、客服班次和 SLA 备注”，没有更新“工单升级状态”。

10. `v13_support_escalation_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把客服升级工单与“另一个优惠券退款工单”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_support_escalation_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新增“工单标签和宏回复清理”，仅属流程记录，不影响状态判断。

12. `v13_support_escalation_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的旧阻塞“客服无法看到支付平台回调”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_support_escalation_current_obstacle",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 56/60: v13_support_escalation_finish_condition_next

### Query

- case_id: `v13_support_escalation_finish_condition_next`
- scope_id: `support_escalation`
- operation: `next_action`
- query: 客服升级工单 要接近完成状态，下一步应验证什么？

### Events

1. `v13_support_escalation_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 客服升级工单 曾按“按普通退款问题处理”推进，并把“普通退款模板回复”当成默认依据。

2. `v13_support_escalation_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新发现：支付成功但权益没有入账；当前状态需要重新按有效证据判断。

3. `v13_support_escalation_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 客服升级工单 复盘确认：工单升级为支付回调排查，不再走普通退款模板；旧判断不再作为当前状态。

4. `v13_support_escalation_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 客服升级工单 补充观察到：截图帮助定位订单但不代表问题关闭；它只影响“用户补充截图”，不改变“支付回调丢失导致的账户权益缺失”。

5. `v13_support_escalation_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 客服升级工单 安排“让支付平台补发回调并核对权益”，目前只有排期，还没有完成记录。

6. `v13_support_escalation_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的“普通退款模板回复”又声称“用户只是要求退款”，但备注说明这只是历史转述。

7. `v13_support_escalation_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 客服升级工单 当前风险集中在：继续套退款模板会错过真实故障。

8. `v13_support_escalation_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 客服升级工单 下一步是：先补发回调，再确认用户权益到账。

9. `v13_support_escalation_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 客服升级工单 例会只同步了“工单标签、客服班次和 SLA 备注”，没有更新“工单升级状态”。

10. `v13_support_escalation_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把客服升级工单与“另一个优惠券退款工单”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_support_escalation_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 客服升级工单 新增“工单标签和宏回复清理”，仅属流程记录，不影响状态判断。

12. `v13_support_escalation_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 客服升级工单 的旧阻塞“客服无法看到支付平台回调”被转述，但没有证据说明它仍然有效。


### Annotation Template

```json
{
  "case_id": "v13_support_escalation_finish_condition_next",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 57/60: v13_thesis_ch2_brief_state

### Query

- case_id: `v13_thesis_ch2_brief_state`
- scope_id: `thesis_ch2`
- operation: `state_summary`
- query: 论文第二章 当前可以怎样概括“第二章修订状态”？

### Events

1. `thesis_e1`
   - type: `draft`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 完成第二章初始提纲。

2. `thesis_e2`
   - type: `deadline`
   - updated_at: `2026-06-02T15:00:00`
   - planned_for: `2026-06-08T18:00:00`
   - content: 原计划 6月8日交第二章。

3. `thesis_e3`
   - type: `feedback`
   - updated_at: `2026-06-04T15:00:00`
   - planned_for: `none`
   - content: 导师反馈第二章要重点补动机和研究空白。

4. `thesis_e4`
   - type: `deadline`
   - updated_at: `2026-06-05T15:00:00`
   - planned_for: `2026-06-10T18:00:00`
   - content: 第二章提交时间改到 6月10日。

5. `thesis_e5`
   - type: `progress`
   - updated_at: `2026-06-06T15:00:00`
   - planned_for: `none`
   - content: 完成第二章语法通读，但内容结构还未改完。

6. `thesis_e6`
   - type: `mention`
   - updated_at: `2026-06-07T15:00:00`
   - planned_for: `none`
   - content: 群聊里又有人提到 6月8日这个旧截止时间，但没有改变当前计划。

7. `v13_thesis_ch2_01`
   - type: `decision`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 论文第二章 曾按“按 6 月 8 日提交旧提纲”推进，并把“旧截止日期群聊”当成默认依据。

8. `v13_thesis_ch2_02`
   - type: `issue`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 论文第二章 新发现：导师要求补动机和研究空白；当前状态需要重新按有效证据判断。

9. `v13_thesis_ch2_03`
   - type: `correction`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 论文第二章 复盘确认：提交节奏改到 6 月 10 日，内容结构仍需改；旧判断不再作为当前状态。

10. `v13_thesis_ch2_04`
   - type: `observation`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 论文第二章 补充观察到：语法通读没有解决结构问题；它只影响“语法通读记录”，不改变“动机和研究空白补写”。

11. `v13_thesis_ch2_05`
   - type: `plan`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `2026-06-10T20:00:00`
   - content: 论文第二章 安排“重写动机段和研究空白段”，目前只有排期，还没有完成记录。

12. `v13_thesis_ch2_06`
   - type: `mention`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 论文第二章 的“旧截止日期群聊”又声称“第二章已经可以提交”，但备注说明这只是历史转述。


### Annotation Template

```json
{
  "case_id": "v13_thesis_ch2_brief_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 58/60: v13_thesis_ch2_planned_item_unknown

### Query

- case_id: `v13_thesis_ch2_planned_item_unknown`
- scope_id: `thesis_ch2`
- operation: `state_lookup`
- query: 论文第二章 关于“动机段补写”有没有完成记录？

### Events

1. `thesis_e1`
   - type: `draft`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 完成第二章初始提纲。

2. `thesis_e2`
   - type: `deadline`
   - updated_at: `2026-06-02T15:00:00`
   - planned_for: `2026-06-08T18:00:00`
   - content: 原计划 6月8日交第二章。

3. `thesis_e3`
   - type: `feedback`
   - updated_at: `2026-06-04T15:00:00`
   - planned_for: `none`
   - content: 导师反馈第二章要重点补动机和研究空白。

4. `thesis_e4`
   - type: `deadline`
   - updated_at: `2026-06-05T15:00:00`
   - planned_for: `2026-06-10T18:00:00`
   - content: 第二章提交时间改到 6月10日。

5. `thesis_e5`
   - type: `progress`
   - updated_at: `2026-06-06T15:00:00`
   - planned_for: `none`
   - content: 完成第二章语法通读，但内容结构还未改完。

6. `thesis_e6`
   - type: `mention`
   - updated_at: `2026-06-07T15:00:00`
   - planned_for: `none`
   - content: 群聊里又有人提到 6月8日这个旧截止时间，但没有改变当前计划。

7. `v13_thesis_ch2_01`
   - type: `decision`
   - updated_at: `2026-06-07T16:00:00`
   - planned_for: `none`
   - content: 论文第二章 曾按“按 6 月 8 日提交旧提纲”推进，并把“旧截止日期群聊”当成默认依据。

8. `v13_thesis_ch2_02`
   - type: `issue`
   - updated_at: `2026-06-07T17:00:00`
   - planned_for: `none`
   - content: 论文第二章 新发现：导师要求补动机和研究空白；当前状态需要重新按有效证据判断。

9. `v13_thesis_ch2_03`
   - type: `correction`
   - updated_at: `2026-06-07T18:00:00`
   - planned_for: `none`
   - content: 论文第二章 复盘确认：提交节奏改到 6 月 10 日，内容结构仍需改；旧判断不再作为当前状态。

10. `v13_thesis_ch2_04`
   - type: `observation`
   - updated_at: `2026-06-07T19:00:00`
   - planned_for: `none`
   - content: 论文第二章 补充观察到：语法通读没有解决结构问题；它只影响“语法通读记录”，不改变“动机和研究空白补写”。

11. `v13_thesis_ch2_05`
   - type: `plan`
   - updated_at: `2026-06-07T20:00:00`
   - planned_for: `2026-06-10T20:00:00`
   - content: 论文第二章 安排“重写动机段和研究空白段”，目前只有排期，还没有完成记录。

12. `v13_thesis_ch2_06`
   - type: `mention`
   - updated_at: `2026-06-07T21:00:00`
   - planned_for: `none`
   - content: 论文第二章 的“旧截止日期群聊”又声称“第二章已经可以提交”，但备注说明这只是历史转述。


### Annotation Template

```json
{
  "case_id": "v13_thesis_ch2_planned_item_unknown",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 59/60: v13_ui_accessibility_corrected_current_state

### Query

- case_id: `v13_ui_accessibility_corrected_current_state`
- scope_id: `ui_accessibility`
- operation: `state_lookup`
- query: UI 可访问性 还能按“保留大卡片和装饰性渐变背景”理解当前状态吗？

### Events

1. `ui_e1`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 前端初版使用大卡片布局，并计划保留装饰性渐变背景。

2. `ui_e2`
   - type: `issue`
   - updated_at: `2026-06-02T14:00:00`
   - planned_for: `none`
   - content: 移动端 QA 发现 toolbar 文本会和后续控件重叠。

3. `ui_e3`
   - type: `plan`
   - updated_at: `2026-06-03T09:00:00`
   - planned_for: `2026-06-04T12:00:00`
   - content: 计划用 responsive constraints 修 toolbar，并在 6 月 4 日回归移动端。

4. `ui_e4`
   - type: `fix`
   - updated_at: `2026-06-04T15:00:00`
   - planned_for: `none`
   - content: toolbar label wrapping 和固定尺寸已修复，移动端不再重叠。

5. `ui_e5`
   - type: `issue`
   - updated_at: `2026-06-05T11:00:00`
   - planned_for: `none`
   - content: 二级按钮 contrast 仍低于目标，需要重新调色。

6. `ui_e6`
   - type: `mention`
   - updated_at: `2026-06-06T09:30:00`
   - planned_for: `none`
   - content: 群里转发旧截图，说 toolbar 仍然重叠，但截图来自修复前。

7. `ui_e7`
   - type: `decision`
   - updated_at: `2026-06-07T10:00:00`
   - planned_for: `none`
   - content: 设计决定删掉装饰性渐变背景，按钮使用功能性图标和更克制的布局。

8. `ui_e8`
   - type: `plan`
   - updated_at: `2026-06-08T16:00:00`
   - planned_for: `2026-06-10T09:00:00`
   - content: 计划 6 月 10 日做最终 mobile accessibility audit，目前还没有 audit 完成记录。

9. `v13_ui_accessibility_01`
   - type: `decision`
   - updated_at: `2026-06-08T17:00:00`
   - planned_for: `none`
   - content: UI 可访问性 曾按“保留大卡片和装饰性渐变背景”推进，并把“修复前移动端截图”当成默认依据。

10. `v13_ui_accessibility_02`
   - type: `issue`
   - updated_at: `2026-06-08T18:00:00`
   - planned_for: `none`
   - content: UI 可访问性 新发现：二级按钮 contrast 仍低于目标；当前状态需要重新按有效证据判断。

11. `v13_ui_accessibility_03`
   - type: `correction`
   - updated_at: `2026-06-08T19:00:00`
   - planned_for: `none`
   - content: UI 可访问性 复盘确认：toolbar 重叠已修复，渐变背景被删掉；旧判断不再作为当前状态。

12. `v13_ui_accessibility_04`
   - type: `observation`
   - updated_at: `2026-06-08T20:00:00`
   - planned_for: `none`
   - content: UI 可访问性 补充观察到：旧截图不能代表当前 toolbar 状态；它只影响“旧 toolbar 截图”，不改变“克制布局、功能图标和 contrast 修复”。

13. `v13_ui_accessibility_05`
   - type: `plan`
   - updated_at: `2026-06-08T21:00:00`
   - planned_for: `2026-06-11T21:00:00`
   - content: UI 可访问性 安排“做最终 mobile accessibility audit”，目前只有排期，还没有完成记录。

14. `v13_ui_accessibility_06`
   - type: `mention`
   - updated_at: `2026-06-08T22:00:00`
   - planned_for: `none`
   - content: UI 可访问性 的“修复前移动端截图”又声称“toolbar 仍然重叠”，但备注说明这只是历史转述。

15. `v13_ui_accessibility_07`
   - type: `risk`
   - updated_at: `2026-06-08T23:00:00`
   - planned_for: `none`
   - content: UI 可访问性 当前风险集中在：旧截图会误导为重叠问题仍存在。

16. `v13_ui_accessibility_08`
   - type: `plan`
   - updated_at: `2026-06-09T00:00:00`
   - planned_for: `2026-06-12T00:00:00`
   - content: UI 可访问性 下一步是：先重调二级按钮 contrast，再做最终 audit。

17. `v13_ui_accessibility_09`
   - type: `meeting_note`
   - updated_at: `2026-06-09T01:00:00`
   - planned_for: `none`
   - content: UI 可访问性 例会只同步了“组件命名、断点截图和设计 token 表”，没有更新“移动端可访问性状态”。

18. `v13_ui_accessibility_10`
   - type: `mention`
   - updated_at: `2026-06-09T02:00:00`
   - planned_for: `none`
   - content: 有人把UI 可访问性与“营销首页视觉改版”混在一起，随后更正说这不是本 scope 的证据。


### Annotation Template

```json
{
  "case_id": "v13_ui_accessibility_corrected_current_state",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

## Case 60/60: v13_warehouse_backfill_risk_summary

### Query

- case_id: `v13_warehouse_backfill_risk_summary`
- scope_id: `warehouse_backfill`
- operation: `state_summary`
- query: 数仓回填 当前风险和下一步如何一起说明？

### Events

1. `v13_warehouse_backfill_01`
   - type: `decision`
   - updated_at: `2026-06-01T10:00:00`
   - planned_for: `none`
   - content: 数仓回填 曾按“直接回填最近 90 天订单表”推进，并把“90 天回填完成公告”当成默认依据。

2. `v13_warehouse_backfill_02`
   - type: `issue`
   - updated_at: `2026-06-01T11:00:00`
   - planned_for: `none`
   - content: 数仓回填 新发现：分区水位缺口导致部分日期重复写入；当前状态需要重新按有效证据判断。

3. `v13_warehouse_backfill_03`
   - type: `correction`
   - updated_at: `2026-06-01T12:00:00`
   - planned_for: `none`
   - content: 数仓回填 复盘确认：完成公告作废，回填改为按分区水位分批执行；旧判断不再作为当前状态。

4. `v13_warehouse_backfill_04`
   - type: `observation`
   - updated_at: `2026-06-01T13:00:00`
   - planned_for: `none`
   - content: 数仓回填 补充观察到：抽样报表只覆盖部分日期；它只影响“抽样校验报表”，不改变“先修复分区水位再分批回填”。

5. `v13_warehouse_backfill_05`
   - type: `plan`
   - updated_at: `2026-06-01T14:00:00`
   - planned_for: `2026-06-04T14:00:00`
   - content: 数仓回填 安排“修复分区水位并先回填 7 天样本”，目前只有排期，还没有完成记录。

6. `v13_warehouse_backfill_06`
   - type: `mention`
   - updated_at: `2026-06-01T15:00:00`
   - planned_for: `none`
   - content: 数仓回填 的“90 天回填完成公告”又声称“订单表已经全部回填完成”，但备注说明这只是历史转述。

7. `v13_warehouse_backfill_07`
   - type: `risk`
   - updated_at: `2026-06-01T16:00:00`
   - planned_for: `none`
   - content: 数仓回填 当前风险集中在：重复写入会污染收入看板。

8. `v13_warehouse_backfill_08`
   - type: `plan`
   - updated_at: `2026-06-01T17:00:00`
   - planned_for: `2026-06-04T17:00:00`
   - content: 数仓回填 下一步是：先修分区水位，再跑 7 天样本回填。

9. `v13_warehouse_backfill_09`
   - type: `meeting_note`
   - updated_at: `2026-06-01T18:00:00`
   - planned_for: `none`
   - content: 数仓回填 例会只同步了“DAG 名称、调度窗口和下游通知名单”，没有更新“回填执行状态”。

10. `v13_warehouse_backfill_10`
   - type: `mention`
   - updated_at: `2026-06-01T19:00:00`
   - planned_for: `none`
   - content: 有人把数仓回填与“用户维表补数任务”混在一起，随后更正说这不是本 scope 的证据。

11. `v13_warehouse_backfill_11`
   - type: `note`
   - updated_at: `2026-06-01T20:00:00`
   - planned_for: `none`
   - content: 数仓回填 新增“调度备注和 on-call 表整理”，仅属流程记录，不影响状态判断。

12. `v13_warehouse_backfill_12`
   - type: `mention`
   - updated_at: `2026-06-01T21:00:00`
   - planned_for: `none`
   - content: 数仓回填 的旧阻塞“90 天窗口资源不足”被转述，但没有证据说明它仍然有效。

13. `v13_warehouse_backfill_13`
   - type: `task_note`
   - updated_at: `2026-06-01T22:00:00`
   - planned_for: `none`
   - content: 数仓回填 加入低优先级事项“整理补数公告模板”，不改变“先修复分区水位再分批回填”。

14. `v13_warehouse_backfill_14`
   - type: `mention`
   - updated_at: `2026-06-01T23:00:00`
   - planned_for: `none`
   - content: 数仓回填 的历史风险“完成公告继续被下游引用”被复制到新文档，负责人确认只是背景。

15. `v13_warehouse_backfill_15`
   - type: `meeting_note`
   - updated_at: `2026-06-02T00:00:00`
   - planned_for: `none`
   - content: 数仓回填 交接记录列出“分区水位、重复写入、7 天样本和收入看板”，没有新增决策。

16. `v13_warehouse_backfill_16`
   - type: `observation`
   - updated_at: `2026-06-02T01:00:00`
   - planned_for: `none`
   - content: 数仓回填 的指标快照写着“抽样通过率不覆盖全部分区”，它不能单独改变当前结论。

17. `v13_warehouse_backfill_17`
   - type: `execution_log`
   - updated_at: `2026-06-02T02:00:00`
   - planned_for: `none`
   - content: 数仓回填 最近一次操作是“一次 DAG 备注修改没有触发回填”，没有产生新的状态证据。

18. `v13_warehouse_backfill_18`
   - type: `note`
   - updated_at: `2026-06-02T03:00:00`
   - planned_for: `none`
   - content: 数仓回填 仍存在证据缺口：没有证据说明 7 天样本回填已完成。

19. `v13_warehouse_backfill_19`
   - type: `note`
   - updated_at: `2026-06-02T04:00:00`
   - planned_for: `none`
   - content: 数仓回填 的完成信号被定义为：分区水位和样本回填均通过校验。

20. `v13_warehouse_backfill_20`
   - type: `check`
   - updated_at: `2026-06-02T05:00:00`
   - planned_for: `none`
   - content: 数仓回填 当前需要围绕“回填执行状态”保留可追溯证据，不能只看最新噪声。

21. `v13_warehouse_backfill_21`
   - type: `message`
   - updated_at: `2026-06-02T06:00:00`
   - planned_for: `none`
   - content: 数仓回填 依赖方只确认了日程，没有确认“分区水位和样本回填均通过校验”。

22. `v13_warehouse_backfill_22`
   - type: `progress`
   - updated_at: `2026-06-02T07:00:00`
   - planned_for: `none`
   - content: 数仓回填 已得到一个局部结果，但它只覆盖“抽样校验报表”。

23. `v13_warehouse_backfill_23`
   - type: `feedback`
   - updated_at: `2026-06-02T08:00:00`
   - planned_for: `none`
   - content: 数仓回填 评审意见要求把“重复写入会污染收入看板”写入当前风险说明。

24. `v13_warehouse_backfill_24`
   - type: `mention`
   - updated_at: `2026-06-02T09:00:00`
   - planned_for: `none`
   - content: 数仓回填 群聊再次复述“直接回填最近 90 天订单表”，随后被标记为旧口径。

25. `v13_warehouse_backfill_25`
   - type: `task_note`
   - updated_at: `2026-06-02T10:00:00`
   - planned_for: `2026-06-05T10:00:00`
   - content: 数仓回填 已指定负责人跟进“修复分区水位并先回填 7 天样本”。

26. `v13_warehouse_backfill_26`
   - type: `note`
   - updated_at: `2026-06-02T11:00:00`
   - planned_for: `none`
   - content: 数仓回填 的 scope 边界排除了“用户维表补数任务”的证据。

27. `v13_warehouse_backfill_27`
   - type: `note`
   - updated_at: `2026-06-02T12:00:00`
   - planned_for: `none`
   - content: 数仓回填 证据包优先收集“分区水位缺口导致部分日期重复写入”和“完成公告作废，回填改为按分区水位分批执行”。

28. `v13_warehouse_backfill_28`
   - type: `plan`
   - updated_at: `2026-06-02T13:00:00`
   - planned_for: `2026-06-05T13:00:00`
   - content: 数仓回填 排期改为先处理“先修分区水位，再跑 7 天样本回填”，再检查“分区水位和样本回填均通过校验”。

29. `v13_warehouse_backfill_29`
   - type: `message`
   - updated_at: `2026-06-02T14:00:00`
   - planned_for: `none`
   - content: 数仓回填 下游通知只同步背景，没有确认“7 天样本回填”完成。

30. `v13_warehouse_backfill_30`
   - type: `note`
   - updated_at: `2026-06-02T15:00:00`
   - planned_for: `none`
   - content: 数仓回填 最终可接受状态必须看到“分区水位和样本回填均通过校验”的明确证据。

31. `v13_warehouse_backfill_31`
   - type: `mention`
   - updated_at: `2026-06-02T16:00:00`
   - planned_for: `none`
   - content: 数仓回填 已把“90 天回填完成公告”归档，避免继续作为当前依据。

32. `v13_warehouse_backfill_32`
   - type: `note`
   - updated_at: `2026-06-02T17:00:00`
   - planned_for: `none`
   - content: 数仓回填 当前回答应追溯到“回填执行状态”的有效事件，而不是最近一条无更新记录。


### Annotation Template

```json
{
  "case_id": "v13_warehouse_backfill_risk_summary",
  "answerability": "",
  "gold_state_slots": {},
  "gold_slot_support": {},
  "hard_negative_events": [],
  "hard_negative_types": {},
  "notes": ""
}
```


---

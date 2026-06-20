# Case 48/60: v13_search_index_rollout_next_domain_action

## Query

- case_id: `v13_search_index_rollout_next_domain_action`
- scope_id: `search_index_rollout`
- operation: `next_action`
- query: 围绕搜索索引上线，现在最该先做哪个动作？

## Events

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


## Annotation Template

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

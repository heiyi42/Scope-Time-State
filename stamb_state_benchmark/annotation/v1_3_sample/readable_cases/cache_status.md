# Case 7/60: cache_status

## Query

- case_id: `cache_status`
- scope_id: `cache_refactor`
- operation: `state_summary`
- query: cache/refactor 现在状态怎样？

## Events

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


## Annotation Template

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

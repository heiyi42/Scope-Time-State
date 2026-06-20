# STAMB-State v1.3 Readable Annotation Packet

这个文件是人工阅读索引。不要读 `annotation_packet.jsonl`，那是给脚本用的。

如果想在一个文件里连续阅读所有 case，打开 `annotation_workbook.md`。

## Summary

- sample_size: 60
- operation: `{'next_action': 13, 'state_lookup': 35, 'state_summary': 12}`
- answerability: `{'answerable': 48, 'insufficient_evidence': 7, 'unknown_current': 5}`
- difficulty_level: `{'easy': 18, 'hard': 16, 'medium': 26}`

## Case Index

### 1. [`aaai_risk`](readable_cases/aaai_risk.md)

- scope_id: `aaai_memory`
- operation: `state_lookup`
- query: AAAI 这个想法现在最大的相关工作风险是什么？

### 2. [`amp_planned_recalc`](readable_cases/amp_planned_recalc.md)

- scope_id: `amp_project`
- operation: `next_action`
- query: 微波放大器 6月9日计划重算什么？

### 3. [`api_rebuild_status`](readable_cases/api_rebuild_status.md)

- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: Graphiti 图重建和全量 run 做完了吗？

### 4. [`api_token_status`](readable_cases/api_token_status.md)

- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: OpenAI-compatible endpoint 现在还是 invalid token 吗？

### 5. [`auth_audit_log_completion_unknown`](readable_cases/auth_audit_log_completion_unknown.md)

- scope_id: `mobile_auth`
- operation: `state_lookup`
- query: magic link 登录审计日志已经补了吗？

### 6. [`bill_deadline`](readable_cases/bill_deadline.md)

- scope_id: `billing_migration`
- operation: `next_action`
- query: billing 这边现在最近的明确 deadline 是什么？

### 7. [`cache_status`](readable_cases/cache_status.md)

- scope_id: `cache_refactor`
- operation: `state_summary`
- query: cache/refactor 现在状态怎样？

### 8. [`eval_next_diag`](readable_cases/eval_next_diag.md)

- scope_id: `eval_harness`
- operation: `state_lookup`
- query: v1.1 新诊断指标实现了吗？

### 9. [`eval_primary_metrics`](readable_cases/eval_primary_metrics.md)

- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 现在主表到底按什么指标判断方法？

### 10. [`incident_actual_vs_mentioned_time`](readable_cases/incident_actual_vs_mentioned_time.md)

- scope_id: `deployment_incident`
- operation: `state_lookup`
- query: 线上事故 14:05 发生、14:10 才记录的事情是什么？

### 11. [`incident_root_cause`](readable_cases/incident_root_cause.md)

- scope_id: `deployment_incident`
- operation: `state_lookup`
- query: 线上事故根因到底是数据库连接池还是缓存问题？

### 12. [`rec_result`](readable_cases/rec_result.md)

- scope_id: `recsys_ablation`
- operation: `state_lookup`
- query: NCF 现在到底比 LightGCN 好还是差？

### 13. [`robot_calibration_completion_unknown`](readable_cases/robot_calibration_completion_unknown.md)

- scope_id: `robot_nav`
- operation: `state_lookup`
- query: 机器人导航 depth camera 外参已经标定完成了吗？

### 14. [`robot_planned_calibration`](readable_cases/robot_planned_calibration.md)

- scope_id: `robot_nav`
- operation: `next_action`
- query: 机器人导航 6月8日计划做什么？

### 15. [`sql_latest_non_update`](readable_cases/sql_latest_non_update.md)

- scope_id: `sql_lab_q6`
- operation: `state_lookup`
- query: 第六题 SQL 最近一次运行有没有改变逻辑？

### 16. [`sql_status`](readable_cases/sql_status.md)

- scope_id: `sql_lab_q6`
- operation: `state_summary`
- query: 第六题 SQL 最近改到哪了？

### 17. [`v13_aaai_memory_side_signal`](readable_cases/v13_aaai_memory_side_signal.md)

- scope_id: `aaai_memory`
- operation: `state_lookup`
- query: 判断AAAI 记忆论文时，“ARTEM baseline 备注”应不应该覆盖“latest-valid-state 建模主线”？

### 18. [`v13_amp_project_brief_state`](readable_cases/v13_amp_project_brief_state.md)

- scope_id: `amp_project`
- operation: `state_summary`
- query: AMP 级间匹配项目 当前可以怎样概括“线长异常定位”？

### 19. [`v13_amp_project_side_signal`](readable_cases/v13_amp_project_side_signal.md)

- scope_id: `amp_project`
- operation: `state_lookup`
- query: AMP 级间匹配项目最近关于“第一级输入匹配日志”的记录能作为主状态吗？

### 20. [`v13_api_rate_limit_brief_state`](readable_cases/v13_api_rate_limit_brief_state.md)

- scope_id: `api_rate_limit`
- operation: `state_summary`
- query: API 额度和 provider 当前可以怎样概括“provider 分工”？

### 21. [`v13_api_rate_limit_corrected_current_state`](readable_cases/v13_api_rate_limit_corrected_current_state.md)

- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: API 额度和 provider 当前是否已经不再适用“DeepSeek 同时负责回答和构图”？

### 22. [`v13_api_rate_limit_final_evidence_insufficient`](readable_cases/v13_api_rate_limit_final_evidence_insufficient.md)

- scope_id: `api_rate_limit`
- operation: `state_lookup`
- query: 能不能判断API 额度和 provider已经拿到“全 baseline 主表”？

### 23. [`v13_billing_migration_brief_state`](readable_cases/v13_billing_migration_brief_state.md)

- scope_id: `billing_migration`
- operation: `state_summary`
- query: 计费迁移 当前可以怎样概括“计费 provider 决策”？

### 24. [`v13_billing_migration_final_evidence_insufficient`](readable_cases/v13_billing_migration_final_evidence_insufficient.md)

- scope_id: `billing_migration`
- operation: `state_lookup`
- query: 能不能判断计费迁移已经拿到“生产迁移签字”？

### 25. [`v13_billing_migration_planned_item_unknown`](readable_cases/v13_billing_migration_planned_item_unknown.md)

- scope_id: `billing_migration`
- operation: `state_lookup`
- query: 计费迁移 关于“legal review”有没有完成记录？

### 26. [`v13_cache_refactor_brief_state`](readable_cases/v13_cache_refactor_brief_state.md)

- scope_id: `cache_refactor`
- operation: `state_summary`
- query: 如果只说当前有效状态，缓存重构 应该怎么总结？

### 27. [`v13_data_retention_policy_current_obstacle`](readable_cases/v13_data_retention_policy_current_obstacle.md)

- scope_id: `data_retention_policy`
- operation: `state_lookup`
- query: 在数据保留政策里，哪个问题决定了当前状态？

### 28. [`v13_data_retention_policy_planned_followup`](readable_cases/v13_data_retention_policy_planned_followup.md)

- scope_id: `data_retention_policy`
- operation: `next_action`
- query: 数据保留政策 的下一轮追踪应聚焦什么？

### 29. [`v13_eval_harness_final_evidence_insufficient`](readable_cases/v13_eval_harness_final_evidence_insufficient.md)

- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 评测 harness 是否已有“完整 baseline 主表”的可靠记录？

### 30. [`v13_eval_harness_planned_item_unknown`](readable_cases/v13_eval_harness_planned_item_unknown.md)

- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 评测 harness 的“over-evidence 诊断”已经完成了吗？

### 31. [`v13_eval_harness_side_signal`](readable_cases/v13_eval_harness_side_signal.md)

- scope_id: `eval_harness`
- operation: `state_lookup`
- query: 评测 harness 的“judge coverage 补跑”现在会改变“sup_f1、slot_j、ans_j 主排序”吗？

### 32. [`v13_grant_app_next_domain_action`](readable_cases/v13_grant_app_next_domain_action.md)

- scope_id: `grant_app`
- operation: `next_action`
- query: 围绕经费申请，现在最该先做哪个动作？

### 33. [`v13_labeling_guideline_corrected_current_state`](readable_cases/v13_labeling_guideline_corrected_current_state.md)

- scope_id: `labeling_guideline`
- operation: `state_lookup`
- query: 标注规范 还能按“uncertain 与 partial 分开标”理解当前状态吗？

### 34. [`v13_labeling_guideline_next_domain_action`](readable_cases/v13_labeling_guideline_next_domain_action.md)

- scope_id: `labeling_guideline`
- operation: `next_action`
- query: 标注规范 继续推进前需要先处理什么？

### 35. [`v13_labeling_guideline_side_signal`](readable_cases/v13_labeling_guideline_side_signal.md)

- scope_id: `labeling_guideline`
- operation: `state_lookup`
- query: 标注规范 的“batch A 一轮标注”现在会改变“合并为 ambiguous 的 v2 规范”吗？

### 36. [`v13_mobile_auth_brief_state`](readable_cases/v13_mobile_auth_brief_state.md)

- scope_id: `mobile_auth`
- operation: `state_summary`
- query: 如果只说当前有效状态，移动端登录 应该怎么总结？

### 37. [`v13_model_serving_latency_planned_followup`](readable_cases/v13_model_serving_latency_planned_followup.md)

- scope_id: `model_serving_latency`
- operation: `next_action`
- query: 模型服务延迟 的下一轮追踪应聚焦什么？

### 38. [`v13_model_serving_latency_primary_next_action`](readable_cases/v13_model_serving_latency_primary_next_action.md)

- scope_id: `model_serving_latency`
- operation: `next_action`
- query: 模型服务延迟 暂时不能直接收尾的话，应先做什么？

### 39. [`v13_model_serving_latency_risk_summary`](readable_cases/v13_model_serving_latency_risk_summary.md)

- scope_id: `model_serving_latency`
- operation: `state_summary`
- query: 模型服务延迟 当前风险和下一步如何一起说明？

### 40. [`v13_onboarding_flow_corrected_decision`](readable_cases/v13_onboarding_flow_corrected_decision.md)

- scope_id: `onboarding_flow`
- operation: `state_lookup`
- query: 当前判断新用户引导流程时，能不能继续引用“把教程弹窗直接推全量”？

### 41. [`v13_privacy_audit_compact_summary`](readable_cases/v13_privacy_audit_compact_summary.md)

- scope_id: `privacy_audit`
- operation: `state_summary`
- query: 隐私审计 当前状态用一句话怎么概括？

### 42. [`v13_privacy_audit_current_obstacle`](readable_cases/v13_privacy_audit_current_obstacle.md)

- scope_id: `privacy_audit`
- operation: `state_lookup`
- query: 隐私审计 当前真正需要处理的问题是什么？

### 43. [`v13_release_notes_final_evidence_insufficient`](readable_cases/v13_release_notes_final_evidence_insufficient.md)

- scope_id: `release_notes`
- operation: `state_lookup`
- query: 发布说明 是否已有“发布负责人签字”的可靠记录？

### 44. [`v13_release_notes_finish_condition_next`](readable_cases/v13_release_notes_finish_condition_next.md)

- scope_id: `release_notes`
- operation: `next_action`
- query: 要判断发布说明可以收尾，接下来需要看哪个完成信号？

### 45. [`v13_release_notes_planned_followup`](readable_cases/v13_release_notes_planned_followup.md)

- scope_id: `release_notes`
- operation: `next_action`
- query: 发布说明 的下一轮追踪应聚焦什么？

### 46. [`v13_robot_nav_final_evidence_insufficient`](readable_cases/v13_robot_nav_final_evidence_insufficient.md)

- scope_id: `robot_nav`
- operation: `state_lookup`
- query: 机器人导航方案 的“最终场地验收”现在有明确证据吗？

### 47. [`v13_robot_nav_side_signal`](readable_cases/v13_robot_nav_side_signal.md)

- scope_id: `robot_nav`
- operation: `state_lookup`
- query: 判断机器人导航方案时，“夜间仿真日志”应不应该覆盖“激光雷达加深度相机融合”？

### 48. [`v13_search_index_rollout_next_domain_action`](readable_cases/v13_search_index_rollout_next_domain_action.md)

- scope_id: `search_index_rollout`
- operation: `next_action`
- query: 围绕搜索索引上线，现在最该先做哪个动作？

### 49. [`v13_sensor_firmware_corrected_decision`](readable_cases/v13_sensor_firmware_corrected_decision.md)

- scope_id: `sensor_firmware`
- operation: `state_lookup`
- query: 传感器固件 还应该沿用“按 1.4.2 固件直接量产”吗？

### 50. [`v13_sensor_firmware_finish_condition_next`](readable_cases/v13_sensor_firmware_finish_condition_next.md)

- scope_id: `sensor_firmware`
- operation: `next_action`
- query: 要判断传感器固件可以收尾，接下来需要看哪个完成信号？

### 51. [`v13_sql_lab_q6_planned_item_unknown`](readable_cases/v13_sql_lab_q6_planned_item_unknown.md)

- scope_id: `sql_lab_q6`
- operation: `state_lookup`
- query: 第六题 SQL 的“样例输出核对”已经完成了吗？

### 52. [`v13_sql_lab_q6_side_signal`](readable_cases/v13_sql_lab_q6_side_signal.md)

- scope_id: `sql_lab_q6`
- operation: `state_lookup`
- query: 第六题 SQL 的“一次无逻辑变更的运行日志”现在会改变“Department 与 Project 连接逻辑”吗？

### 53. [`v13_support_escalation_compact_summary`](readable_cases/v13_support_escalation_compact_summary.md)

- scope_id: `support_escalation`
- operation: `state_summary`
- query: 客服升级工单 当前状态用一句话怎么概括？

### 54. [`v13_support_escalation_corrected_decision`](readable_cases/v13_support_escalation_corrected_decision.md)

- scope_id: `support_escalation`
- operation: `state_lookup`
- query: 当前判断客服升级工单时，能不能继续引用“按普通退款问题处理”？

### 55. [`v13_support_escalation_current_obstacle`](readable_cases/v13_support_escalation_current_obstacle.md)

- scope_id: `support_escalation`
- operation: `state_lookup`
- query: 客服升级工单 当前真正需要处理的问题是什么？

### 56. [`v13_support_escalation_finish_condition_next`](readable_cases/v13_support_escalation_finish_condition_next.md)

- scope_id: `support_escalation`
- operation: `next_action`
- query: 客服升级工单 要接近完成状态，下一步应验证什么？

### 57. [`v13_thesis_ch2_brief_state`](readable_cases/v13_thesis_ch2_brief_state.md)

- scope_id: `thesis_ch2`
- operation: `state_summary`
- query: 论文第二章 当前可以怎样概括“第二章修订状态”？

### 58. [`v13_thesis_ch2_planned_item_unknown`](readable_cases/v13_thesis_ch2_planned_item_unknown.md)

- scope_id: `thesis_ch2`
- operation: `state_lookup`
- query: 论文第二章 关于“动机段补写”有没有完成记录？

### 59. [`v13_ui_accessibility_corrected_current_state`](readable_cases/v13_ui_accessibility_corrected_current_state.md)

- scope_id: `ui_accessibility`
- operation: `state_lookup`
- query: UI 可访问性 还能按“保留大卡片和装饰性渐变背景”理解当前状态吗？

### 60. [`v13_warehouse_backfill_risk_summary`](readable_cases/v13_warehouse_backfill_risk_summary.md)

- scope_id: `warehouse_backfill`
- operation: `state_summary`
- query: 数仓回填 当前风险和下一步如何一起说明？


## Output Reminder

标注完成后，把每个 case 的 `Annotation Template` 填好，合并成一行一个 JSON object 的 `annotator_a.jsonl` 或 `annotator_b.jsonl`。

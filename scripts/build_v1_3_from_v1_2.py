from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from v1_common import (
    RAW_EVENT_FIELDS,
    build_scope_profiles,
    normalize_id_list,
    read_json,
    write_json,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_V1_2_DIR = PROJECT_DIR / "stamb_state_benchmark" / "data" / "v1_2"
DEFAULT_V1_3_DIR = PROJECT_DIR / "stamb_state_benchmark" / "data" / "v1_3"

TARGET_SCOPE_EVENT_COUNTS = {
    "aaai_memory": 12,
    "amp_project": 12,
    "sql_lab_q6": 12,
    "thesis_ch2": 12,
    "release_notes": 12,
    "support_escalation": 12,
    "grant_app": 18,
    "labeling_guideline": 18,
    "cache_refactor": 18,
    "mobile_auth": 18,
    "robot_nav": 18,
    "recsys_ablation": 18,
    "deployment_incident": 18,
    "ui_accessibility": 18,
    "privacy_audit": 18,
    "data_retention_policy": 18,
    "onboarding_flow": 18,
    "sensor_firmware": 18,
    "search_index_rollout": 32,
    "billing_migration": 32,
    "eval_harness": 32,
    "api_rate_limit": 32,
    "model_serving_latency": 32,
    "warehouse_backfill": 32,
}

NEW_SCOPE_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "release_notes": {
        "scope_type": "docs_release",
        "task_family": ["release_status", "doc_accuracy", "publication_planning"],
        "domain": "documentation",
    },
    "support_escalation": {
        "scope_type": "customer_support",
        "task_family": ["escalation_status", "root_cause", "response_planning"],
        "domain": "support",
    },
    "privacy_audit": {
        "scope_type": "privacy_compliance",
        "task_family": ["audit_status", "policy_exception", "remediation_planning"],
        "domain": "privacy",
    },
    "data_retention_policy": {
        "scope_type": "governance_policy",
        "task_family": ["policy_status", "exception_tracking", "approval_status"],
        "domain": "governance",
    },
    "onboarding_flow": {
        "scope_type": "product_growth",
        "task_family": ["funnel_issue", "experiment_tracking", "next_step_planning"],
        "domain": "product",
    },
    "sensor_firmware": {
        "scope_type": "embedded_system",
        "task_family": ["firmware_status", "calibration_status", "risk_tracking"],
        "domain": "embedded",
    },
    "model_serving_latency": {
        "scope_type": "ml_infra",
        "task_family": ["latency_risk", "rollout_status", "mitigation_tracking"],
        "domain": "machine_learning_infra",
    },
    "warehouse_backfill": {
        "scope_type": "data_pipeline",
        "task_family": ["backfill_status", "data_quality", "completion_unknown"],
        "domain": "data_platform",
    },
}

NEW_SPLIT_SCOPES = {
    "train": [
        "model_serving_latency",
        "warehouse_backfill",
        "data_retention_policy",
        "release_notes",
        "support_escalation",
    ],
    "dev": ["privacy_audit", "onboarding_flow"],
    "test": ["sensor_firmware"],
}

NEW_SCOPE_DIFFICULTY_PATTERNS = {
    "model_serving_latency": ["easy", "easy", "medium", "hard", "hard", "hard", "medium", "hard", "easy"],
    "warehouse_backfill": ["easy", "easy", "medium", "hard", "hard", "hard", "medium", "hard", "easy"],
    "privacy_audit": ["easy", "easy", "medium", "hard", "hard", "hard", "medium", "hard", "easy"],
    "onboarding_flow": ["easy", "easy", "medium", "hard", "hard", "hard", "medium", "hard", "easy"],
    "data_retention_policy": ["easy", "easy", "easy", "medium", "medium", "hard", "hard", "hard", "easy"],
    "sensor_firmware": ["easy", "easy", "easy", "medium", "medium", "hard", "hard", "hard", "easy"],
    "release_notes": ["easy", "easy", "easy", "medium", "medium", "hard", "hard", "medium", "easy"],
    "support_escalation": ["easy", "easy", "easy", "medium", "medium", "hard", "hard", "medium", "easy"],
}

HARD_NEGATIVE_SUBTYPE_VALUES = {
    "stale_mention",
    "non_update_latest",
    "corrected_old_state",
    "cross_scope_collision",
    "plan_not_done",
    "partial_evidence",
    "procedural_noise",
    "insufficient_evidence_distractor",
    "other_in_scope_distractor",
}

SCENARIOS: Dict[str, Dict[str, str]] = {
    "aaai_memory": {
        "label": "AAAI 记忆论文",
        "old_plan": "沿用单时间线记忆叙事",
        "state_object": "科学问题表述",
        "main_facet": "latest-valid-state 建模主线",
        "side_facet": "ARTEM baseline 备注",
        "stale_artifact": "早期 related-work 草稿",
        "stale_claim": "单时间线记忆就是主要创新点",
        "current_issue": "TSM 已覆盖多时间角色，原卖点不足",
        "correction_result": "主线改为 Scope-Time-State Graph 下的有效状态追踪",
        "side_observation": "ARTEM 仍可放进相关工作对比表",
        "meeting_noise": "投稿格式、页数和参考文献顺序",
        "planned_action": "补一版 STSGraph 问题定义和可追溯例子",
        "risk": "把已有底层 pipeline 误包装成顶层科学问题",
        "collision": "KG-RAG baseline 讨论",
        "procedural_noise": "AAAI 模板和匿名检查清单",
        "next_action": "先写清楚 scope-time-state 三元状态如何约束 query",
        "old_blocker": "只能讲 mentioned_at 与 occurred_at 差异",
        "low_priority_task": "把 ARTEM 表格挪到 appendix",
        "stale_risk": "相关工作不足",
        "handoff_note": "导师意见、方法命名和实验表格位置",
        "metric_snapshot": "草稿里 answer_score 表格还没有替换成 slot-level 指标",
        "non_update_latest": "一次格式检查只改了引用顺序",
        "evidence_gap": "没有证据说明 graphiti 对比已经跑完",
        "insufficient_target": "正式 rebuttal 版本",
        "unknown_target": "STSGraph 小节补写",
        "final_signal": "问题建模小节通过导师确认",
    },
    "amp_project": {
        "label": "AMP 级间匹配项目",
        "old_plan": "继续排查第一级输入匹配",
        "state_object": "线长异常定位",
        "main_facet": "级间匹配网络",
        "side_facet": "第一级输入匹配日志",
        "stale_artifact": "S11 旧诊断表",
        "stale_claim": "主要问题在输入匹配",
        "current_issue": "复核发现瓶颈集中在级间匹配",
        "correction_result": "S11 线长异常改按级间匹配处理",
        "side_observation": "第一级输入匹配结果已归档为辅助证据",
        "meeting_noise": "板卡编号、仿真目录和截图命名",
        "planned_action": "重算级间匹配网络线长",
        "risk": "继续围绕输入匹配调参会错过真正瓶颈",
        "collision": "另一个 S12 输入实验",
        "procedural_noise": "仿真脚本参数表归档",
        "next_action": "先重算级间匹配线长，再决定是否改布局",
        "old_blocker": "输入匹配配置未确认",
        "low_priority_task": "整理第一级输入匹配截图",
        "stale_risk": "S11 输入端口可能接错",
        "handoff_note": "S11、S12、线长表和仿真目录映射",
        "metric_snapshot": "旧版线长表仍把输入匹配列标红",
        "non_update_latest": "一次脚本 dry-run 没有生成新线长",
        "evidence_gap": "没有证据说明级间重算已经完成",
        "insufficient_target": "版图最终验收",
        "unknown_target": "级间线长重算",
        "final_signal": "新版线长表被用于后续布局修改",
    },
    "sql_lab_q6": {
        "label": "第六题 SQL",
        "old_plan": "沿用初稿连接条件",
        "state_object": "查询逻辑",
        "main_facet": "Department 与 Project 连接逻辑",
        "side_facet": "一次无逻辑变更的运行日志",
        "stale_artifact": "SQL 初稿截图",
        "stale_claim": "初稿已经可以提交",
        "current_issue": "连接条件把部门项目关系连错",
        "correction_result": "连接逻辑已按正确外键修正",
        "side_observation": "一次执行日志只证明 SQL 能跑通",
        "meeting_noise": "作业命名、提交路径和截图格式",
        "planned_action": "重新跑结果集并核对样例输出",
        "risk": "把能执行误判为逻辑正确",
        "collision": "第五题的 join 模板",
        "procedural_noise": "实验报告封面和学号格式",
        "next_action": "先核对样例输出，再提交最终 SQL",
        "old_blocker": "初稿连接条件不确定",
        "low_priority_task": "整理 SQL 缩进",
        "stale_risk": "初稿可能仍在被复制",
        "handoff_note": "题号、表名和截图目录",
        "metric_snapshot": "运行时间记录没有说明结果集是否正确",
        "non_update_latest": "一次重新执行没有改查询逻辑",
        "evidence_gap": "没有证据说明老师已经批改通过",
        "insufficient_target": "课程平台最终得分",
        "unknown_target": "样例输出核对",
        "final_signal": "样例输出与标准答案一致",
    },
    "robot_nav": {
        "label": "机器人导航方案",
        "old_plan": "继续使用纯激光雷达导航",
        "state_object": "导航传感器方案",
        "main_facet": "激光雷达加深度相机融合",
        "side_facet": "夜间仿真日志",
        "stale_artifact": "纯激光雷达方案纪要",
        "stale_claim": "仿真成功率足以支持纯激光雷达上线",
        "current_issue": "玻璃走廊真机定位漂移明显",
        "correction_result": "方案转向激光雷达与深度相机融合",
        "side_observation": "夜间仿真没有覆盖玻璃走廊真机问题",
        "meeting_noise": "场地预约、机器人编号和电池检查",
        "planned_action": "标定深度相机外参",
        "risk": "只看仿真成功率会掩盖真机漂移",
        "collision": "仓库避障演示",
        "procedural_noise": "传感器支架采购记录",
        "next_action": "先完成外参标定，再复测玻璃走廊",
        "old_blocker": "纯激光雷达地图还未清理",
        "low_priority_task": "整理仿真视频文件名",
        "stale_risk": "仿真地图分辨率偏低",
        "handoff_note": "真机场景、外参标定板和日志目录",
        "metric_snapshot": "92% 仿真成功率仍来自旧传感器方案",
        "non_update_latest": "一次仿真重跑没有新增真机证据",
        "evidence_gap": "没有证据说明外参标定已经完成",
        "insufficient_target": "最终场地验收",
        "unknown_target": "深度相机外参标定",
        "final_signal": "玻璃走廊复测通过",
    },
    "thesis_ch2": {
        "label": "论文第二章",
        "old_plan": "按 6 月 8 日提交旧提纲",
        "state_object": "第二章修订状态",
        "main_facet": "动机和研究空白补写",
        "side_facet": "语法通读记录",
        "stale_artifact": "旧截止日期群聊",
        "stale_claim": "第二章已经可以提交",
        "current_issue": "导师要求补动机和研究空白",
        "correction_result": "提交节奏改到 6 月 10 日，内容结构仍需改",
        "side_observation": "语法通读没有解决结构问题",
        "meeting_noise": "参考文献格式、图编号和目录层级",
        "planned_action": "重写动机段和研究空白段",
        "risk": "只改语法会误判为内容完成",
        "collision": "第三章实验设计讨论",
        "procedural_noise": "章节标题样式统一",
        "next_action": "先补动机和研究空白，再做最终通读",
        "old_blocker": "6 月 8 日旧截止日期压力",
        "low_priority_task": "统一图表题注格式",
        "stale_risk": "旧提纲被继续沿用",
        "handoff_note": "导师反馈、提交日期和章节结构",
        "metric_snapshot": "语法通读清单显示完成但不代表结构完成",
        "non_update_latest": "一次目录刷新没有改正文内容",
        "evidence_gap": "没有证据说明第二章已经提交",
        "insufficient_target": "导师最终签字",
        "unknown_target": "动机段补写",
        "final_signal": "导师确认第二章结构可用",
    },
    "mobile_auth": {
        "label": "移动端登录",
        "old_plan": "继续使用短信验证码",
        "state_object": "登录方案",
        "main_facet": "邮箱魔法链接登录",
        "side_facet": "重发限流修复",
        "stale_artifact": "短信验证码方案纪要",
        "stale_claim": "短信验证码仍是默认方案",
        "current_issue": "iOS 重发按钮倒计时偶尔不刷新",
        "correction_result": "短信验证码已被邮箱魔法链接替代",
        "side_observation": "重发限流已经上线但不等于审计日志完成",
        "meeting_noise": "登录页文案、按钮尺寸和埋点命名",
        "planned_action": "补登录审计日志",
        "risk": "旧短信方案被会议纪要误认为重新启用",
        "collision": "Web 端单点登录排期",
        "procedural_noise": "风控白名单导出",
        "next_action": "先补审计日志并复查 iOS 倒计时",
        "old_blocker": "重发接口没有限流",
        "low_priority_task": "整理登录页错误文案",
        "stale_risk": "短信验证码成本偏高",
        "handoff_note": "魔法链接、限流、审计日志和 iOS 复现路径",
        "metric_snapshot": "重发成功率截图没有覆盖审计日志",
        "non_update_latest": "一次文案同步没有改变登录方案",
        "evidence_gap": "没有证据说明审计日志已经补齐",
        "insufficient_target": "安全评审最终通过",
        "unknown_target": "登录审计日志",
        "final_signal": "安全评审确认登录链路闭环",
    },
    "search_index_rollout": {
        "label": "搜索索引上线",
        "old_plan": "上线 BM25 patch",
        "state_object": "检索上线方案",
        "main_facet": "hybrid sparse+dense 检索",
        "side_facet": "旧 dashboard 截图",
        "stale_artifact": "BM25 rollout 截图",
        "stale_claim": "BM25 patch 已上线完成",
        "current_issue": "reranker p95 延迟超过 180ms 预算",
        "correction_result": "BM25 patch 未部署，方向改为 hybrid 检索",
        "side_observation": "旧截图来自过期环境",
        "meeting_noise": "索引命名、dashboard 链接和回滚联系人",
        "planned_action": "评估更小的 cross-encoder",
        "risk": "过期截图会被误读成已上线",
        "collision": "广告搜索索引项目",
        "procedural_noise": "索引别名和监控链接整理",
        "next_action": "先压低 reranker 延迟，再决定上线窗口",
        "old_blocker": "BM25 patch 排期未确认",
        "low_priority_task": "清理旧 dashboard 收藏夹",
        "stale_risk": "中文长查询召回下降",
        "handoff_note": "BM25、hybrid、reranker 延迟和 cross-encoder 评估",
        "metric_snapshot": "旧 dashboard 仍显示 rollout finished",
        "non_update_latest": "一次 dashboard 权限修复没有新召回结果",
        "evidence_gap": "没有证据说明小 cross-encoder 评估完成",
        "insufficient_target": "生产上线批准",
        "unknown_target": "小 cross-encoder 评估",
        "final_signal": "hybrid 方案满足召回和延迟门槛",
    },
    "billing_migration": {
        "label": "计费迁移",
        "old_plan": "把订阅计费迁到 Stripe",
        "state_object": "计费 provider 决策",
        "main_facet": "保留现有 provider 并只做 Paddle prototype",
        "side_facet": "发票 CSV 导出",
        "stale_artifact": "Stripe migration done 文档",
        "stale_claim": "Stripe 迁移已经完成",
        "current_issue": "企业合同限制阻塞生产迁移",
        "correction_result": "生产迁移暂停，Paddle 只进入 prototype",
        "side_observation": "发票导出完成不代表计费迁移完成",
        "meeting_noise": "财务字段、税率备注和账单样例",
        "planned_action": "做 legal review",
        "risk": "把报表导出误当成 provider 迁移",
        "collision": "发票导出专项",
        "procedural_noise": "供应商联系人和合同附件整理",
        "next_action": "先完成 legal review，再决定是否继续 Paddle prototype",
        "old_blocker": "税费 rounding 与旧账单偏差",
        "low_priority_task": "统一发票 CSV 列名",
        "stale_risk": "Stripe 文档未同步合同限制",
        "handoff_note": "Stripe、Paddle、合同限制和发票导出",
        "metric_snapshot": "CSV 导出通过率不代表迁移完成率",
        "non_update_latest": "一次字段重命名没有改变 provider 决策",
        "evidence_gap": "没有证据说明 legal review 已完成",
        "insufficient_target": "生产迁移签字",
        "unknown_target": "legal review",
        "final_signal": "合同侧确认 provider 路径",
    },
    "eval_harness": {
        "label": "评测 harness",
        "old_plan": "按 event_f1 排序所有方法",
        "state_object": "评测口径",
        "main_facet": "sup_f1、slot_j、ans_j 主排序",
        "side_facet": "judge coverage 补跑",
        "stale_artifact": "event_f1 第一旧口径纪要",
        "stale_claim": "event_f1 最高即可判最好",
        "current_issue": "扩 benchmark 容易过拟合 Ours",
        "correction_result": "任务定义冻结，event_f1 只作诊断",
        "side_observation": "judge coverage 已补齐但不改变主排序口径",
        "meeting_noise": "表格列顺序、cache 路径和 appendix baseline",
        "planned_action": "增加 over-evidence rate 和 unknown-current accuracy 诊断",
        "risk": "为了分数修改 benchmark 语义",
        "collision": "oracle pipeline appendix baseline",
        "procedural_noise": "实验结果文件命名规范",
        "next_action": "先固定指标解释，再补诊断统计",
        "old_blocker": "Graphiti judge hole 未补齐",
        "low_priority_task": "整理旧输出目录",
        "stale_risk": "只追求更高 answer_score",
        "handoff_note": "public E2E、DeepSeek judge、Graphiti 和 TSM cache",
        "metric_snapshot": "主表 coverage 42/42 但 over-evidence 还没算",
        "non_update_latest": "一次 dry-run 没有产生新 judge 结果",
        "evidence_gap": "没有证据说明 over-evidence 诊断已经实现",
        "insufficient_target": "完整 baseline 主表",
        "unknown_target": "over-evidence 诊断",
        "final_signal": "主表和诊断表口径一致",
    },
    "grant_app": {
        "label": "经费申请",
        "old_plan": "沿用 80k 初版预算",
        "state_object": "申请材料状态",
        "main_facet": "95k 设备费预算和合作方 C",
        "side_facet": "作废预算附件",
        "stale_artifact": "80k 旧预算表",
        "stale_claim": "预算仍按 80k 提交",
        "current_issue": "预算说明还没补齐",
        "correction_result": "预算改为 95k，合作方 C 替代 B",
        "side_observation": "邮件引用旧预算但附件已标作废",
        "meeting_noise": "系统账号、盖章流程和附件编号",
        "planned_action": "补预算说明并重新上传",
        "risk": "旧预算附件被误作为当前金额",
        "collision": "另一个校内设备申请",
        "procedural_noise": "申请书命名和版本号清理",
        "next_action": "先补 95k 预算说明，再检查合作方信息",
        "old_blocker": "合作方 B 退出",
        "low_priority_task": "整理设备报价截图",
        "stale_risk": "80k 表格继续被转发",
        "handoff_note": "预算、合作方和系统上传状态",
        "metric_snapshot": "系统显示草稿已上传但预算说明缺失",
        "non_update_latest": "一次附件重命名没有改变预算金额",
        "evidence_gap": "没有证据说明正式提交已经完成",
        "insufficient_target": "学院盖章确认",
        "unknown_target": "预算说明补齐",
        "final_signal": "系统显示正式提交成功",
    },
    "labeling_guideline": {
        "label": "标注规范",
        "old_plan": "uncertain 与 partial 分开标",
        "state_object": "标注规则",
        "main_facet": "合并为 ambiguous 的 v2 规范",
        "side_facet": "batch A 一轮标注",
        "stale_artifact": "v1 规范截图",
        "stale_claim": "uncertain 和 partial 仍需分开",
        "current_issue": "batch A 分歧率达到 12%",
        "correction_result": "管理员确认 v1 作废，当前按 v2 重新培训",
        "side_observation": "一轮标注完成但还没复核",
        "meeting_noise": "标注员排班、样例编号和工单链接",
        "planned_action": "用 v2 规范重新培训标注员",
        "risk": "旧截图让标注员继续使用 v1",
        "collision": "情感标注项目",
        "procedural_noise": "标注平台标签颜色调整",
        "next_action": "先完成 v2 培训，再复核 batch A",
        "old_blocker": "v1/v2 截图混用",
        "low_priority_task": "整理样例库标签颜色",
        "stale_risk": "旧规范截图在 Slack 继续传播",
        "handoff_note": "v2 规范、batch A、分歧率和复核计划",
        "metric_snapshot": "一轮完成率不代表复核完成",
        "non_update_latest": "一次平台颜色修改没有改变规范定义",
        "evidence_gap": "没有证据说明 batch A 已经复核完",
        "insufficient_target": "全量标注验收",
        "unknown_target": "batch A 复核",
        "final_signal": "batch A 复核按 v2 关闭",
    },
    "cache_refactor": {
        "label": "缓存重构",
        "old_plan": "只修 circular reference trace",
        "state_object": "cache/refactor 状态",
        "main_facet": "deepcopy cache 和 transactional write",
        "side_facet": "py_compile 生成物清理",
        "stale_artifact": "circular reference 旧错误日志",
        "stale_claim": "trace 仍无法 JSON dump",
        "current_issue": "regression test 还没有落地",
        "correction_result": "cache 返回和 trace 写入都已 deepcopy",
        "side_observation": "__pycache__ 已清理但不代表测试已补",
        "meeting_noise": "输出目录、cache 文件名和 dry-run 命令",
        "planned_action": "补 cache mutation regression test",
        "risk": "把 py_compile 通过误判为行为测试覆盖",
        "collision": "Graphiti verifier trace 修复",
        "procedural_noise": "旧运行产物清理记录",
        "next_action": "先补 mutation regression test，再跑公共 E2E",
        "old_blocker": "JSON dump circular reference",
        "low_priority_task": "整理 cache 文件命名",
        "stale_risk": "旧错误日志被当成当前状态",
        "handoff_note": "deepcopy、transactional write、trace 输出和测试缺口",
        "metric_snapshot": "py_compile 通过不代表 mutation regression 覆盖",
        "non_update_latest": "一次目录清理没有新增测试",
        "evidence_gap": "没有证据说明 regression test 已经补上",
        "insufficient_target": "生产发布确认",
        "unknown_target": "mutation regression test",
        "final_signal": "新增测试稳定通过",
    },
    "recsys_ablation": {
        "label": "推荐消融实验",
        "old_plan": "按初次 NCF 高 2% 解读",
        "state_object": "模型对比结论",
        "main_facet": "修正泄漏后 LightGCN 优于 NCF",
        "side_facet": "夜间重跑日志",
        "stale_artifact": "NCF 初次结果表",
        "stale_claim": "NCF baseline 比 LightGCN 更好",
        "current_issue": "初次实验存在数据泄漏",
        "correction_result": "修正后 NCF 低于 LightGCN，下一轮加入 SASRec",
        "side_observation": "夜间重跑没有产生新指标变化",
        "meeting_noise": "随机种子、数据切分和表格配色",
        "planned_action": "补 cold-start split 测试",
        "risk": "继续引用泄漏结果会误导方法排序",
        "collision": "另一个召回实验",
        "procedural_noise": "实验目录和 seed 表整理",
        "next_action": "先完成 cold-start split，再加入 SASRec 对比",
        "old_blocker": "数据泄漏未修正",
        "low_priority_task": "整理旧 NCF 日志",
        "stale_risk": "NCF 高 2% 结论被复用",
        "handoff_note": "NCF、LightGCN、SASRec 和 cold-start split",
        "metric_snapshot": "夜间重跑只复用了修正后配置",
        "non_update_latest": "一次日志归档没有新指标",
        "evidence_gap": "没有证据说明 cold-start split 已跑完",
        "insufficient_target": "最终模型选择签字",
        "unknown_target": "cold-start split 测试",
        "final_signal": "SASRec 对比表和 cold-start 表都完成",
    },
    "deployment_incident": {
        "label": "线上推荐事故",
        "old_plan": "按数据库连接池耗尽处置",
        "state_object": "事故根因和后续动作",
        "main_facet": "缓存击穿根因",
        "side_facet": "状态页模板文字",
        "stale_artifact": "数据库连接池初判",
        "stale_claim": "事故根因是连接池耗尽",
        "current_issue": "热点 key 缓存击穿导致下游被打爆",
        "correction_result": "根因修正为缓存击穿，服务已通过回滚缓解",
        "side_observation": "状态页复制告警文字没有新增故障",
        "meeting_noise": "on-call 轮值、状态页模板和截图归档",
        "planned_action": "增加热点 key 限流和缓存预热",
        "risk": "误按数据库方向复盘会漏掉缓存防护",
        "collision": "支付服务 5xx 告警",
        "procedural_noise": "事故复盘模板字段补齐",
        "next_action": "先落地热点 key 限流，再做缓存预热演练",
        "old_blocker": "连接池指标异常",
        "low_priority_task": "整理状态页截图",
        "stale_risk": "连接池初判继续传播",
        "handoff_note": "回滚、缓存击穿、限流和预热计划",
        "metric_snapshot": "5xx 峰值图不单独证明根因",
        "non_update_latest": "一次状态页文案修正没有新增故障",
        "evidence_gap": "没有证据说明限流已经上线",
        "insufficient_target": "事故关闭评审",
        "unknown_target": "热点 key 限流",
        "final_signal": "复盘 action items 全部关闭",
    },
    "ui_accessibility": {
        "label": "UI 可访问性",
        "old_plan": "保留大卡片和装饰性渐变背景",
        "state_object": "移动端可访问性状态",
        "main_facet": "克制布局、功能图标和 contrast 修复",
        "side_facet": "旧 toolbar 截图",
        "stale_artifact": "修复前移动端截图",
        "stale_claim": "toolbar 仍然重叠",
        "current_issue": "二级按钮 contrast 仍低于目标",
        "correction_result": "toolbar 重叠已修复，渐变背景被删掉",
        "side_observation": "旧截图不能代表当前 toolbar 状态",
        "meeting_noise": "组件命名、断点截图和设计 token 表",
        "planned_action": "做最终 mobile accessibility audit",
        "risk": "旧截图会误导为重叠问题仍存在",
        "collision": "营销首页视觉改版",
        "procedural_noise": "图标库和按钮命名整理",
        "next_action": "先重调二级按钮 contrast，再做最终 audit",
        "old_blocker": "toolbar 文本换行问题",
        "low_priority_task": "整理断点截图",
        "stale_risk": "装饰性渐变重新被加回",
        "handoff_note": "toolbar、contrast、图标按钮和 audit 计划",
        "metric_snapshot": "旧截图显示重叠但早于修复",
        "non_update_latest": "一次 token 重命名没有改变 contrast",
        "evidence_gap": "没有证据说明最终 audit 已完成",
        "insufficient_target": "设计验收签字",
        "unknown_target": "mobile accessibility audit",
        "final_signal": "最终 audit 通过 contrast 与布局检查",
    },
    "api_rate_limit": {
        "label": "API 额度和 provider",
        "old_plan": "DeepSeek 同时负责回答和构图",
        "state_object": "provider 分工",
        "main_facet": "DeepSeek 回答、OpenAI-compatible 构图、GPT judge",
        "side_facet": "旧 token invalid 日志",
        "stale_artifact": "invalid token 旧日志",
        "stale_claim": "OpenAI-compatible endpoint 当前不可用",
        "current_issue": "judge 成本和 endpoint 抖动仍需 cache",
        "correction_result": "最小 ping 已通过，构图 provider 当前可用",
        "side_observation": "旧 invalid token 日志早于最新 ping",
        "meeting_noise": "环境变量、cache 文件和 run id",
        "planned_action": "保留 cache 后跑公共 E2E",
        "risk": "额度不稳定导致 graph construction 中断",
        "collision": "Graphiti appendix baseline",
        "procedural_noise": "provider 配置表整理",
        "next_action": "先确认 cache 命中，再继续 public E2E",
        "old_blocker": "DeepSeek 额度不稳定",
        "low_priority_task": "整理 API key 命名",
        "stale_risk": "invalid token 旧日志被当成当前状态",
        "handoff_note": "DeepSeek、OpenAI-compatible、GPT judge 和 cache",
        "metric_snapshot": "42 个 case run 完成但不代表全量主表完成",
        "non_update_latest": "一次 dry-run 没有消耗 judge 额度",
        "evidence_gap": "没有证据说明全量 public E2E 已跑完",
        "insufficient_target": "全 baseline 主表",
        "unknown_target": "public E2E balanced_half",
        "final_signal": "public E2E 和 appendix baseline 都有缓存结果",
    },
    "release_notes": {
        "label": "发布说明",
        "old_plan": "直接发布自动生成 changelog",
        "state_object": "发布说明准确性",
        "main_facet": "手动核对 breaking changes 和迁移步骤",
        "side_facet": "自动生成条目",
        "stale_artifact": "机器人生成的 changelog 草稿",
        "stale_claim": "所有 breaking changes 已覆盖",
        "current_issue": "迁移步骤缺少配置字段重命名说明",
        "correction_result": "发布说明改为先人工核对再发布",
        "side_observation": "自动条目只覆盖 commit 标题",
        "meeting_noise": "版本号、发布日期和截图尺寸",
        "planned_action": "补配置字段迁移说明",
        "risk": "用户按旧字段升级会启动失败",
        "collision": "内部 SDK 预发公告",
        "procedural_noise": "release checklist 复选框整理",
        "next_action": "先补迁移步骤，再让负责人复核 release notes",
        "old_blocker": "自动 changelog 漏掉破坏性变更",
        "low_priority_task": "统一 markdown heading 层级",
        "stale_risk": "机器人草稿被当成终稿",
        "handoff_note": "breaking changes、迁移步骤和发布窗口",
        "metric_snapshot": "commit 数量统计不代表说明完整",
        "non_update_latest": "一次拼写修正没有补迁移步骤",
        "evidence_gap": "没有证据说明负责人已经复核",
        "insufficient_target": "发布负责人签字",
        "unknown_target": "配置字段迁移说明",
        "final_signal": "发布说明通过负责人复核",
    },
    "support_escalation": {
        "label": "客服升级工单",
        "old_plan": "按普通退款问题处理",
        "state_object": "工单升级状态",
        "main_facet": "支付回调丢失导致的账户权益缺失",
        "side_facet": "用户补充截图",
        "stale_artifact": "普通退款模板回复",
        "stale_claim": "用户只是要求退款",
        "current_issue": "支付成功但权益没有入账",
        "correction_result": "工单升级为支付回调排查，不再走普通退款模板",
        "side_observation": "截图帮助定位订单但不代表问题关闭",
        "meeting_noise": "工单标签、客服班次和 SLA 备注",
        "planned_action": "让支付平台补发回调并核对权益",
        "risk": "继续套退款模板会错过真实故障",
        "collision": "另一个优惠券退款工单",
        "procedural_noise": "工单标签和宏回复清理",
        "next_action": "先补发回调，再确认用户权益到账",
        "old_blocker": "客服无法看到支付平台回调",
        "low_priority_task": "整理用户截图命名",
        "stale_risk": "普通退款模板继续被引用",
        "handoff_note": "订单号、支付回调、权益状态和 SLA",
        "metric_snapshot": "客服首次响应达标不代表工单解决",
        "non_update_latest": "一次标签修改没有触发回调",
        "evidence_gap": "没有证据说明权益已经到账",
        "insufficient_target": "用户确认解决",
        "unknown_target": "支付回调补发",
        "final_signal": "用户权益到账并关闭工单",
    },
    "privacy_audit": {
        "label": "隐私审计",
        "old_plan": "沿用旧数据保留例外",
        "state_object": "审计整改状态",
        "main_facet": "删除无依据的长期保留例外",
        "side_facet": "数据目录扫描",
        "stale_artifact": "旧例外审批邮件",
        "stale_claim": "长期保留例外仍然有效",
        "current_issue": "审批邮件没有覆盖新增日志字段",
        "correction_result": "旧例外失效，新增日志字段需重新评估",
        "side_observation": "目录扫描只列出字段，不构成审批",
        "meeting_noise": "审计会议编号、DPO 日程和表格模板",
        "planned_action": "补做新增字段的隐私影响评估",
        "risk": "旧审批被误用于新字段",
        "collision": "安全漏洞扫描",
        "procedural_noise": "证据包目录和截图编号",
        "next_action": "先完成隐私影响评估，再决定是否保留字段",
        "old_blocker": "旧例外审批边界不清",
        "low_priority_task": "整理审计证据包目录",
        "stale_risk": "旧审批邮件继续被转发",
        "handoff_note": "新增日志字段、例外审批和 DPO 评估",
        "metric_snapshot": "扫描通过率不代表隐私审批通过",
        "non_update_latest": "一次目录扫描没有新增审批结论",
        "evidence_gap": "没有证据说明 DPO 已批准",
        "insufficient_target": "DPO 最终批准",
        "unknown_target": "隐私影响评估",
        "final_signal": "DPO 确认字段处理方案",
    },
    "data_retention_policy": {
        "label": "数据保留政策",
        "old_plan": "按 180 天默认保留日志",
        "state_object": "保留期限决策",
        "main_facet": "敏感字段 30 天脱敏、聚合指标 180 天保留",
        "side_facet": "法务注释",
        "stale_artifact": "180 天默认政策草案",
        "stale_claim": "所有日志都可保留 180 天",
        "current_issue": "敏感字段不能套用默认期限",
        "correction_result": "政策拆分为敏感字段和聚合指标两类",
        "side_observation": "法务注释提示风险但不是最终批准",
        "meeting_noise": "政策编号、数据表名和审批流节点",
        "planned_action": "提交分层保留策略审批",
        "risk": "默认期限覆盖敏感字段会带来合规风险",
        "collision": "产品埋点保留讨论",
        "procedural_noise": "政策目录和版本号整理",
        "next_action": "先提交分层策略审批，再同步数据平台执行规则",
        "old_blocker": "默认 180 天口径未拆分",
        "low_priority_task": "统一政策文档页眉",
        "stale_risk": "旧草案继续被作为执行依据",
        "handoff_note": "敏感字段、聚合指标、审批流和执行规则",
        "metric_snapshot": "日志量统计不说明保留期限合法",
        "non_update_latest": "一次表名整理没有改变保留期限",
        "evidence_gap": "没有证据说明审批流已通过",
        "insufficient_target": "合规审批通过",
        "unknown_target": "分层保留策略审批",
        "final_signal": "审批流通过并下发执行规则",
    },
    "onboarding_flow": {
        "label": "新用户引导流程",
        "old_plan": "把教程弹窗直接推全量",
        "state_object": "引导实验状态",
        "main_facet": "先修复手机号校验，再小流量实验",
        "side_facet": "漏斗截图",
        "stale_artifact": "全量弹窗上线计划",
        "stale_claim": "教程弹窗已准备全量发布",
        "current_issue": "手机号校验错误导致第二步流失异常",
        "correction_result": "全量发布暂停，先修手机号校验",
        "side_observation": "漏斗截图定位流失点但不代表修复完成",
        "meeting_noise": "实验分桶、文案版本和设计走查",
        "planned_action": "修复校验后开 5% 小流量实验",
        "risk": "直接推弹窗会掩盖校验 bug",
        "collision": "老用户召回弹窗",
        "procedural_noise": "实验命名和埋点字典整理",
        "next_action": "先修手机号校验，再启动 5% 实验",
        "old_blocker": "教程弹窗文案未定",
        "low_priority_task": "整理引导页插画资源",
        "stale_risk": "全量发布计划被继续引用",
        "handoff_note": "手机号校验、漏斗、实验分桶和小流量计划",
        "metric_snapshot": "漏斗截图显示流失但没有修复证据",
        "non_update_latest": "一次文案调整没有改变校验逻辑",
        "evidence_gap": "没有证据说明 5% 实验已经开始",
        "insufficient_target": "全量上线批准",
        "unknown_target": "5% 小流量实验",
        "final_signal": "小流量实验指标达标",
    },
    "sensor_firmware": {
        "label": "传感器固件",
        "old_plan": "按 1.4.2 固件直接量产",
        "state_object": "固件发布状态",
        "main_facet": "修正温漂补偿后再做量产候选",
        "side_facet": "实验室温箱日志",
        "stale_artifact": "1.4.2 量产候选记录",
        "stale_claim": "1.4.2 已可量产",
        "current_issue": "低温场景零点漂移超过阈值",
        "correction_result": "1.4.2 量产暂停，需修温漂补偿",
        "side_observation": "温箱日志暴露漂移但不是修复结果",
        "meeting_noise": "设备编号、烧录批次和测试台账",
        "planned_action": "重算温漂补偿系数并烧录 1.4.3 候选",
        "risk": "忽略低温漂移会导致量产返工",
        "collision": "电池管理固件",
        "procedural_noise": "烧录记录和设备标签整理",
        "next_action": "先重算补偿系数，再跑低温回归",
        "old_blocker": "1.4.2 量产窗口已排期",
        "low_priority_task": "整理温箱曲线截图",
        "stale_risk": "1.4.2 候选记录继续被引用",
        "handoff_note": "温漂补偿、低温回归和烧录批次",
        "metric_snapshot": "常温通过率不覆盖低温漂移",
        "non_update_latest": "一次台账整理没有新固件",
        "evidence_gap": "没有证据说明 1.4.3 已通过低温回归",
        "insufficient_target": "量产放行签字",
        "unknown_target": "1.4.3 低温回归",
        "final_signal": "低温回归通过并形成量产候选",
    },
    "model_serving_latency": {
        "label": "模型服务延迟",
        "old_plan": "按原始批量大小全量发布",
        "state_object": "serving 发布策略",
        "main_facet": "降低批量大小并启用降级缓存",
        "side_facet": "压测火焰图",
        "stale_artifact": "全量发布排期单",
        "stale_claim": "延迟已经满足全量发布",
        "current_issue": "p99 延迟在高峰流量下超过 SLA",
        "correction_result": "全量发布暂停，先改批量大小和降级缓存",
        "side_observation": "火焰图定位瓶颈但不是发布批准",
        "meeting_noise": "压测窗口、机器规格和 dashboard 权限",
        "planned_action": "用新批量大小做 10% 流量灰度",
        "risk": "低峰压测结果被误用到高峰流量",
        "collision": "离线 embedding 任务",
        "procedural_noise": "压测报告目录和 run id 整理",
        "next_action": "先做 10% 灰度并监控 p99，再决定扩量",
        "old_blocker": "GPU 利用率波动",
        "low_priority_task": "整理火焰图截图",
        "stale_risk": "全量发布排期单继续被引用",
        "handoff_note": "p99、批量大小、降级缓存和灰度比例",
        "metric_snapshot": "低峰平均延迟不能代表高峰 p99",
        "non_update_latest": "一次 dashboard 权限修复没有新压测",
        "evidence_gap": "没有证据说明 10% 灰度已经完成",
        "insufficient_target": "全量发布批准",
        "unknown_target": "10% 流量灰度",
        "final_signal": "灰度 p99 稳定低于 SLA",
    },
    "warehouse_backfill": {
        "label": "数仓回填",
        "old_plan": "直接回填最近 90 天订单表",
        "state_object": "回填执行状态",
        "main_facet": "先修复分区水位再分批回填",
        "side_facet": "抽样校验报表",
        "stale_artifact": "90 天回填完成公告",
        "stale_claim": "订单表已经全部回填完成",
        "current_issue": "分区水位缺口导致部分日期重复写入",
        "correction_result": "完成公告作废，回填改为按分区水位分批执行",
        "side_observation": "抽样报表只覆盖部分日期",
        "meeting_noise": "DAG 名称、调度窗口和下游通知名单",
        "planned_action": "修复分区水位并先回填 7 天样本",
        "risk": "重复写入会污染收入看板",
        "collision": "用户维表补数任务",
        "procedural_noise": "调度备注和 on-call 表整理",
        "next_action": "先修分区水位，再跑 7 天样本回填",
        "old_blocker": "90 天窗口资源不足",
        "low_priority_task": "整理补数公告模板",
        "stale_risk": "完成公告继续被下游引用",
        "handoff_note": "分区水位、重复写入、7 天样本和收入看板",
        "metric_snapshot": "抽样通过率不覆盖全部分区",
        "non_update_latest": "一次 DAG 备注修改没有触发回填",
        "evidence_gap": "没有证据说明 7 天样本回填已完成",
        "insufficient_target": "90 天全量回填完成确认",
        "unknown_target": "7 天样本回填",
        "final_signal": "分区水位和样本回填均通过校验",
    },
}


def require_unique(rows: Iterable[Mapping[str, Any]], key: str, owner: str) -> None:
    values = [str(row.get(key)) for row in rows]
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise RuntimeError(f"{owner} duplicate {key}: {duplicates}")


def event_time(row: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(str(row["updated_at"]))


def raw_event(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: row.get(field) for field in RAW_EVENT_FIELDS}


def event_annotation(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "updates_state": bool(row.get("updates_state", True)),
        "event_status": str(row.get("event_status", "active")),
        "corrects": normalize_id_list(row.get("corrects")),
        "supersedes": normalize_id_list(row.get("supersedes")),
        "notes": "Generated by v1.3 scope-specific benchmark expansion.",
    }


def slug_scope(scope_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", scope_id.lower()).strip("_")


def role(
    name: str,
    event_type: str,
    status: str,
    updates_state: bool,
    content: str,
) -> Dict[str, Any]:
    return {
        "role": name,
        "event_type": event_type,
        "event_status": status,
        "updates_state": updates_state,
        "content": content,
    }


def scenario(scope_id: str) -> Mapping[str, str]:
    try:
        return SCENARIOS[scope_id]
    except KeyError as exc:
        raise RuntimeError(f"missing v1.3 scenario for scope={scope_id}") from exc


def role_templates(scope_id: str) -> List[Dict[str, Any]]:
    item = scenario(scope_id)
    label = item["label"]
    return [
        role("baseline_decision", "decision", "superseded", True, f"{label} 曾按“{item['old_plan']}”推进，并把“{item['stale_artifact']}”当成默认依据。"),
        role("current_issue", "issue", "superseded", True, f"{label} 新发现：{item['current_issue']}；当前状态需要重新按有效证据判断。"),
        role("correction", "correction", "active", True, f"{label} 复盘确认：{item['correction_result']}；旧判断不再作为当前状态。"),
        role("side_observation", "observation", "active", True, f"{label} 补充观察到：{item['side_observation']}；它只影响“{item['side_facet']}”，不改变“{item['main_facet']}”。"),
        role("planned_review", "plan", "active", True, f"{label} 安排“{item['planned_action']}”，目前只有排期，还没有完成记录。"),
        role("stale_completion_mention", "mention", "historical_only", False, f"{label} 的“{item['stale_artifact']}”又声称“{item['stale_claim']}”，但备注说明这只是历史转述。"),
        role("risk_update", "risk", "active", True, f"{label} 当前风险集中在：{item['risk']}。"),
        role("next_plan", "plan", "active", True, f"{label} 下一步是：{item['next_action']}。"),
        role("background_meeting", "meeting_note", "active", False, f"{label} 例会只同步了“{item['meeting_noise']}”，没有更新“{item['state_object']}”。"),
        role("scope_collision", "mention", "historical_only", False, f"有人把{label}与“{item['collision']}”混在一起，随后更正说这不是本 scope 的证据。"),
        role("procedural_note", "note", "active", False, f"{label} 新增“{item['procedural_noise']}”，仅属流程记录，不影响状态判断。"),
        role("old_blocker_mention", "mention", "historical_only", False, f"{label} 的旧阻塞“{item['old_blocker']}”被转述，但没有证据说明它仍然有效。"),
        role("low_priority_side_task", "task_note", "active", True, f"{label} 加入低优先级事项“{item['low_priority_task']}”，不改变“{item['main_facet']}”。"),
        role("stale_risk_mention", "mention", "historical_only", False, f"{label} 的历史风险“{item['stale_risk']}”被复制到新文档，负责人确认只是背景。"),
        role("handoff_note", "meeting_note", "active", False, f"{label} 交接记录列出“{item['handoff_note']}”，没有新增决策。"),
        role("metric_snapshot", "observation", "active", False, f"{label} 的指标快照写着“{item['metric_snapshot']}”，它不能单独改变当前结论。"),
        role("non_update_latest", "execution_log", "active", False, f"{label} 最近一次操作是“{item['non_update_latest']}”，没有产生新的状态证据。"),
        role("evidence_gap_note", "note", "active", False, f"{label} 仍存在证据缺口：{item['evidence_gap']}。"),
        role("final_signal_definition", "note", "active", True, f"{label} 的完成信号被定义为：{item['final_signal']}。"),
        role("quality_gate", "check", "active", True, f"{label} 当前需要围绕“{item['state_object']}”保留可追溯证据，不能只看最新噪声。"),
        role("dependency_ping", "message", "active", False, f"{label} 依赖方只确认了日程，没有确认“{item['final_signal']}”。"),
        role("partial_result", "progress", "active", True, f"{label} 已得到一个局部结果，但它只覆盖“{item['side_facet']}”。"),
        role("review_comment", "feedback", "active", True, f"{label} 评审意见要求把“{item['risk']}”写入当前风险说明。"),
        role("old_plan_echo", "mention", "historical_only", False, f"{label} 群聊再次复述“{item['old_plan']}”，随后被标记为旧口径。"),
        role("owner_assignment", "task_note", "active", True, f"{label} 已指定负责人跟进“{item['planned_action']}”。"),
        role("scope_boundary", "note", "active", False, f"{label} 的 scope 边界排除了“{item['collision']}”的证据。"),
        role("evidence_packet", "note", "active", True, f"{label} 证据包优先收集“{item['current_issue']}”和“{item['correction_result']}”。"),
        role("schedule_change", "plan", "active", True, f"{label} 排期改为先处理“{item['next_action']}”，再检查“{item['final_signal']}”。"),
        role("downstream_notice", "message", "active", False, f"{label} 下游通知只同步背景，没有确认“{item['unknown_target']}”完成。"),
        role("acceptance_marker", "note", "active", True, f"{label} 最终可接受状态必须看到“{item['final_signal']}”的明确证据。"),
        role("stale_artifact_archive", "mention", "historical_only", False, f"{label} 已把“{item['stale_artifact']}”归档，避免继续作为当前依据。"),
        role("traceability_note", "note", "active", True, f"{label} 当前回答应追溯到“{item['state_object']}”的有效事件，而不是最近一条无更新记录。"),
    ]


def generated_event_rows(scope_id: str, existing: Sequence[Mapping[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    missing = max(0, target_count - len(existing))
    if missing == 0:
        return []
    base_time = max((event_time(row) for row in existing), default=datetime(2026, 6, 1, 9, 0, 0))
    slug = slug_scope(scope_id)
    rows: List[Dict[str, Any]] = []
    templates = role_templates(scope_id)
    for index in range(missing):
        template = templates[index] if index < len(templates) else templates[-1]
        updated_at = base_time + timedelta(hours=index + 1)
        role_name = str(template["role"])
        planned_for = None
        if role_name in {"planned_review", "next_plan", "schedule_change", "owner_assignment"}:
            planned_for = (updated_at + timedelta(days=3)).isoformat(timespec="seconds")
        rows.append(
            {
                "event_id": f"v13_{slug}_{index + 1:02d}",
                "scope_id": scope_id,
                "content": template["content"],
                "event_type": template["event_type"],
                "occurred_at": updated_at.isoformat(timespec="seconds"),
                "mentioned_at": updated_at.isoformat(timespec="seconds"),
                "updated_at": updated_at.isoformat(timespec="seconds"),
                "planned_for": planned_for,
                "deadline_at": None,
                "source_id": None,
                "metadata": {},
                "event_status": template["event_status"],
                "updates_state": template["updates_state"],
                "corrects": [],
                "supersedes": [],
                "v1_3_role": role_name,
            }
        )
    event_ids_by_role = {str(row["v1_3_role"]): str(row["event_id"]) for row in rows}
    correction = event_ids_by_role.get("correction")
    if correction:
        for row in rows:
            if row["event_id"] == correction:
                if "stale_completion_mention" in event_ids_by_role:
                    row["corrects"] = [event_ids_by_role["stale_completion_mention"]]
                row["supersedes"] = [
                    event_ids_by_role[role_name]
                    for role_name in ("baseline_decision", "current_issue")
                    if role_name in event_ids_by_role
                ]
    return rows


def infer_existing_roles(events: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]:
    roles: Dict[str, Dict[str, str]] = defaultdict(dict)
    for event in events:
        scope_id = str(event["scope_id"])
        event_id = str(event["event_id"])
        event_type = str(event.get("event_type", ""))
        if event_type == "decision" and "baseline_decision" not in roles[scope_id]:
            roles[scope_id]["baseline_decision"] = event_id
        if event_type in {"correction", "fix"} and "correction" not in roles[scope_id]:
            roles[scope_id]["correction"] = event_id
        if event_type in {"issue", "risk", "incident"} and "current_issue" not in roles[scope_id]:
            roles[scope_id]["current_issue"] = event_id
        if event_type == "plan" and "planned_review" not in roles[scope_id]:
            roles[scope_id]["planned_review"] = event_id
        if event_type == "mention" and "stale_completion_mention" not in roles[scope_id]:
            roles[scope_id]["stale_completion_mention"] = event_id
    return {scope_id: dict(scope_roles) for scope_id, scope_roles in roles.items()}


def add_generated_roles(role_map: Dict[str, Dict[str, str]], generated_rows: Sequence[Mapping[str, Any]]) -> None:
    for row in generated_rows:
        scope_id = str(row["scope_id"])
        role_name = str(row.get("v1_3_role", ""))
        if role_name:
            role_map.setdefault(scope_id, {})[role_name] = str(row["event_id"])


def event_id(scope_roles: Mapping[str, str], role_name: str) -> str:
    if role_name in scope_roles:
        return scope_roles[role_name]
    fallback_order = [
        "correction",
        "current_issue",
        "planned_review",
        "side_observation",
        "baseline_decision",
        "stale_completion_mention",
    ]
    for fallback in fallback_order:
        if fallback in scope_roles:
            return scope_roles[fallback]
    raise RuntimeError(f"missing event role={role_name}; available={sorted(scope_roles)}")


def ordered_scoped_event_ids(
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    scope_id: str,
) -> List[str]:
    rows = sorted(events_by_scope.get(scope_id, []), key=lambda row: str(row.get("updated_at", "")), reverse=True)
    return [str(row["event_id"]) for row in rows]


def hard_negatives(
    scope_id: str,
    scope_roles: Mapping[str, str],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations_by_id: Mapping[str, Mapping[str, Any]],
    gold_ids: Sequence[str],
    limit: int,
) -> List[str]:
    if limit <= 0:
        return []
    blocked = set(str(event_id_value) for event_id_value in gold_ids)
    negative_roles = [
        "stale_completion_mention",
        "non_update_latest",
        "scope_collision",
        "planned_review",
        "evidence_gap_note",
        "procedural_note",
        "metric_snapshot",
        "dependency_ping",
        "old_blocker_mention",
        "stale_risk_mention",
        "background_meeting",
        "handoff_note",
        "downstream_notice",
        "old_plan_echo",
        "scope_boundary",
        "partial_result",
        "side_observation",
        "stale_artifact_archive",
        "low_priority_side_task",
    ]
    ids: List[str] = []

    def add(candidate: str | None) -> None:
        if candidate and candidate not in blocked and candidate not in ids and len(ids) < limit:
            ids.append(candidate)

    for role_name in negative_roles:
        add(scope_roles.get(role_name))

    for event_id_value in ordered_scoped_event_ids(events_by_scope, scope_id):
        annotation = annotations_by_id.get(event_id_value, {})
        if annotation.get("updates_state") is False or annotation.get("event_status") == "historical_only":
            add(event_id_value)
    for event_id_value in ordered_scoped_event_ids(events_by_scope, scope_id):
        add(event_id_value)
    return ids[:limit]


def scoped_event_by_id(
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    scope_id: str,
    event_id_value: str,
) -> Mapping[str, Any] | None:
    for event in events_by_scope.get(scope_id, []):
        if str(event.get("event_id")) == event_id_value:
            return event
    return None


def infer_hard_negative_types(
    event_id_value: str,
    scope_id: str,
    scope_roles: Mapping[str, str],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations_by_id: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    role_by_event_id = {event_id: role_name for role_name, event_id in scope_roles.items()}
    role_name = role_by_event_id.get(event_id_value, "")
    event = scoped_event_by_id(events_by_scope, scope_id, event_id_value) or {}
    annotation = annotations_by_id.get(event_id_value, {})
    types: set[str] = set()
    if role_name in {"stale_completion_mention", "old_blocker_mention", "stale_risk_mention", "old_plan_echo", "stale_artifact_archive"}:
        types.add("stale_mention")
    if role_name in {"non_update_latest"}:
        types.add("non_update_latest")
    if role_name in {"baseline_decision", "current_issue"} or annotation.get("event_status") == "superseded":
        types.add("corrected_old_state")
    if role_name in {"scope_collision", "scope_boundary"}:
        types.add("cross_scope_collision")
    if role_name in {"planned_review", "next_plan", "schedule_change", "owner_assignment"}:
        types.add("plan_not_done")
    if role_name in {"side_observation", "partial_result", "metric_snapshot"}:
        types.add("partial_evidence")
    if role_name in {"procedural_note", "background_meeting", "handoff_note", "low_priority_side_task"}:
        types.add("procedural_noise")
    if role_name in {"evidence_gap_note", "dependency_ping", "downstream_notice"}:
        types.add("insufficient_evidence_distractor")
    if annotation.get("event_status") == "historical_only":
        types.add("stale_mention")
    if annotation.get("updates_state") is False and str(event.get("event_type")) == "execution_log":
        types.add("non_update_latest")
    if annotation.get("updates_state") is False and not types:
        types.add("procedural_noise")
    if not types:
        types.add("other_in_scope_distractor")
    return sorted(types)


def hard_negative_type_map(
    case: Mapping[str, Any],
    scope_roles: Mapping[str, str],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, List[str]]:
    scope_id = str(case["scope_id"])
    return {
        event_id_value: infer_hard_negative_types(
            event_id_value,
            scope_id,
            scope_roles,
            events_by_scope,
            annotations_by_id,
        )
        for event_id_value in normalize_id_list(case.get("hard_negative_events"))
    }


def operation_subtype(
    case_id: str,
    operation: str,
    difficulty_tags: Sequence[str],
    answerability: str,
    output_slot_count: int,
) -> str:
    tags = set(str(tag) for tag in difficulty_tags)
    if answerability == "unknown_current":
        return "completion_unknown"
    if answerability == "insufficient_evidence":
        return "insufficient_evidence"
    if operation == "next_action":
        if "finish_condition" in case_id:
            return "finish_condition_verification"
        if "risk" in case_id:
            return "risk_mitigation_planning"
        return "plan_continuation"
    if operation == "state_summary":
        return "multi_facet_summary" if output_slot_count > 1 or "multi_facet_summary" in tags else "compact_state_summary"
    if "correction_aware" in tags or "corrected" in case_id:
        return "correction_aware_lookup"
    if "stale_mention_distractor" in tags or "old" in case_id:
        return "stale_state_invalidation"
    if "side" in case_id:
        return "partial_evidence_lookup"
    return "latest_valid_state_lookup"


def make_case(
    case_id: str,
    query: str,
    scope_id: str,
    operation: str,
    difficulty_level: str,
    difficulty_tags: Sequence[str],
    gold_state_slots: Mapping[str, str],
    gold_slot_support: Mapping[str, Sequence[str]],
    hard_negative_events: Sequence[str],
    answerability: str = "answerable",
    time_roles: Sequence[str] = ("updated_at",),
) -> Dict[str, Any]:
    gold_events: List[str] = []
    for event_ids in gold_slot_support.values():
        for support_event_id in event_ids:
            if support_event_id and support_event_id not in gold_events:
                gold_events.append(str(support_event_id))
    return {
        "case_id": case_id,
        "query": query,
        "scope_id": scope_id,
        "operation": operation,
        "time_roles": list(time_roles),
        "difficulty_tags": list(difficulty_tags),
        "difficulty_level": difficulty_level,
        "gold_events": gold_events,
        "hard_negative_events": list(hard_negative_events),
        "gold_state_slots": dict(gold_state_slots),
        "gold_slot_support": {slot: list(event_ids) for slot, event_ids in gold_slot_support.items()},
        "output_slots": list(gold_state_slots.keys()),
        "answerability": answerability,
        "operation_subtype": operation_subtype(
            case_id,
            operation,
            difficulty_tags,
            answerability,
            len(gold_state_slots),
        ),
        "hard_negative_types": {},
        "gold_fields_usage": "evaluation_only",
    }


SOURCE_CASE_SLOT_REWRITES: Dict[str, Dict[str, str]] = {
    "sql_status": {
        "latest_fix": "当前有效进展是第六题 SQL 的表连接已按正确关系修好",
    },
    "sql_issue_resolution": {
        "fix": "修正版已更正 Department 与 Project 的 join 条件",
    },
    "robot_status": {
        "next_step": "下一步排期是做 depth camera 外参标定",
    },
    "robot_planned_calibration": {
        "planned_work": "6月8日这项计划对应 depth camera 外参标定，还不是完成记录。",
    },
    "thesis_status": {
        "remaining_work": "第二章结构层面仍缺动机和研究空白补写",
    },
    "thesis_remaining_work": {
        "remaining_work": "当前待补的是动机段和研究空白论证，语法通读不再是阻塞项",
    },
    "label_status": {
        "current_guideline": "标注规范已切到 v2，核心变化是把 uncertain/partial 统一归入 ambiguous",
    },
    "label_guideline": {
        "current_guideline": "处理 uncertain 和 partial 时应按 v2 统一标为 ambiguous",
    },
}


def polish_source_case_gold_wording(case: Mapping[str, Any]) -> Dict[str, Any]:
    row = dict(case)
    rewrites = SOURCE_CASE_SLOT_REWRITES.get(str(row.get("case_id")))
    if not rewrites:
        return row
    slots = dict(row.get("gold_state_slots", {}))
    for slot, value in rewrites.items():
        if slot in slots:
            slots[slot] = value
    row["gold_state_slots"] = slots
    return row


def insufficient_evidence_status(item: Mapping[str, str]) -> str:
    return (
        f"当前缺口是“{item['evidence_gap']}”；"
        f"因此不能把现有记录当成“{item['insufficient_target']}”已完成的证据。"
    )


def compact_state_summary(item: Mapping[str, str]) -> str:
    return (
        f"当前问题是“{item['current_issue']}”，"
        f"有效状态落在“{item['main_facet']}”；"
        f"后续应先做“{item['next_action']}”。"
    )


def query_text(scope_id: str, kind: str, templates: Sequence[str]) -> str:
    item = scenario(scope_id)
    index = sum(ord(char) for char in f"{scope_id}:{kind}") % len(templates)
    return templates[index].format(**item)


def add_case_with_negatives(
    case: Dict[str, Any],
    scope_roles: Mapping[str, str],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations_by_id: Mapping[str, Mapping[str, Any]],
    negative_limit: int,
) -> Dict[str, Any]:
    case["hard_negative_events"] = hard_negatives(
        str(case["scope_id"]),
        scope_roles,
        events_by_scope,
        annotations_by_id,
        normalize_id_list(case.get("gold_events")),
        negative_limit,
    )
    case["hard_negative_types"] = hard_negative_type_map(case, scope_roles, events_by_scope, annotations_by_id)
    return case


def repair_source_case_hard_negatives(
    case: Mapping[str, Any],
    scope_roles: Mapping[str, str],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    row = polish_source_case_gold_wording(case)
    scope_id = str(row["scope_id"])
    available_event_ids = {str(event["event_id"]) for event in events_by_scope[scope_id]}
    gold_ids = normalize_id_list(row.get("gold_events"))
    blocked = set(gold_ids)
    valid_hard_negatives: List[str] = []
    for event_id_value in normalize_id_list(row.get("hard_negative_events")):
        if event_id_value in available_event_ids and event_id_value not in blocked and event_id_value not in valid_hard_negatives:
            valid_hard_negatives.append(event_id_value)
    target = {"easy": 1, "medium": 3, "hard": 5}.get(str(row.get("difficulty_level")), 3)
    if len(valid_hard_negatives) < target:
        fill = hard_negatives(
            scope_id,
            scope_roles,
            events_by_scope,
            annotations_by_id,
            gold_ids + valid_hard_negatives,
            target - len(valid_hard_negatives),
        )
        valid_hard_negatives.extend(fill)
    row["hard_negative_events"] = valid_hard_negatives[:target]
    row["hard_negative_types"] = hard_negative_type_map(row, scope_roles, events_by_scope, annotations_by_id)
    row["operation_subtype"] = operation_subtype(
        str(row["case_id"]),
        str(row["operation"]),
        [str(tag) for tag in row.get("difficulty_tags", [])],
        str(row.get("answerability")),
        len(row.get("output_slots", [])),
    )
    return row


def existing_scope_cases(
    scope_id: str,
    scope_roles: Mapping[str, str],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations_by_id: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    item = scenario(scope_id)
    slug = slug_scope(scope_id)
    side = event_id(scope_roles, "side_observation")
    plan = event_id(scope_roles, "planned_review")
    correction = event_id(scope_roles, "correction")
    baseline = event_id(scope_roles, "baseline_decision")
    current_issue = event_id(scope_roles, "current_issue")
    label = item["label"]
    rows = [
        (
            make_case(
                f"v13_{slug}_side_signal",
                query_text(
                    scope_id,
                    "existing_side",
                    [
                        "{label} 的“{side_facet}”现在会改变“{main_facet}”吗？",
                        "判断{label}时，“{side_facet}”应不应该覆盖“{main_facet}”？",
                        "{label}最近关于“{side_facet}”的记录能作为主状态吗？",
                    ],
                ),
                scope_id,
                "state_lookup",
                "easy",
                ["long_context_noise", "facet_specific_validity"],
                {"side_signal_status": f"{item['side_observation']}，只影响“{item['side_facet']}”，不改变“{item['main_facet']}”。"},
                {"side_signal_status": [side]},
                [],
            ),
            0,
        ),
        (
            make_case(
                f"v13_{slug}_brief_state",
                query_text(
                    scope_id,
                    "existing_summary",
                    [
                        "{label} 当前可以怎样概括“{state_object}”？",
                        "如果只说当前有效状态，{label} 应该怎么总结？",
                        "{label} 的“{state_object}”现在落在哪条主线上？",
                    ],
                ),
                scope_id,
                "state_summary",
                "easy",
                ["long_context_noise", "multi_facet_summary"],
                {"brief_state_summary": f"当前围绕“{item['main_facet']}”判断；“{item['side_facet']}”只是补充观察。"},
                {"brief_state_summary": [side]},
                [],
            ),
            1,
        ),
        (
            make_case(
                f"v13_{slug}_next_domain_action",
                query_text(
                    scope_id,
                    "existing_next",
                    [
                        "{label} 下一步应先推进哪件事？",
                        "围绕{label}，现在最该先做哪个动作？",
                        "{label} 继续推进前需要先处理什么？",
                    ],
                ),
                scope_id,
                "next_action",
                "medium",
                ["plan_not_done", "next_action", "long_context_noise"],
                {"next_action": item["next_action"]},
                {"next_action": [plan]},
                [],
                time_roles=("planned_for", "updated_at"),
            ),
            3,
        ),
        (
            make_case(
                f"v13_{slug}_planned_item_unknown",
                query_text(
                    scope_id,
                    "existing_unknown",
                    [
                        "{label} 的“{unknown_target}”已经完成了吗？",
                        "现在能确认{label}的“{unknown_target}”已经落地了吗？",
                        "{label} 关于“{unknown_target}”有没有完成记录？",
                    ],
                ),
                scope_id,
                "state_lookup",
                "medium",
                ["unknown_current", "plan_not_done", "long_context_noise"],
                {"planned_item_status": f"只有“{item['planned_action']}”的安排，没有“{item['unknown_target']}”完成记录。"},
                {"planned_item_status": [plan]},
                [],
                answerability="unknown_current",
                time_roles=("planned_for", "updated_at"),
            ),
            3,
        ),
        (
            make_case(
                f"v13_{slug}_final_evidence_insufficient",
                query_text(
                    scope_id,
                    "existing_insufficient",
                    [
                        "{label} 的“{insufficient_target}”现在有明确证据吗？",
                        "能不能判断{label}已经拿到“{insufficient_target}”？",
                        "{label} 是否已有“{insufficient_target}”的可靠记录？",
                    ],
                ),
                scope_id,
                "state_lookup",
                "medium",
                ["insufficient_evidence", "answerability", "long_context_noise"],
                {"evidence_status": insufficient_evidence_status(item)},
                {"evidence_status": []},
                [],
                answerability="insufficient_evidence",
            ),
            3,
        ),
        (
            make_case(
                f"v13_{slug}_corrected_current_state",
                query_text(
                    scope_id,
                    "existing_corrected",
                    [
                        "{label} 还能按“{old_plan}”理解当前状态吗？",
                        "关于{label}，“{old_plan}”这个旧判断还成立吗？",
                        "{label} 当前是否已经不再适用“{old_plan}”？",
                    ],
                ),
                scope_id,
                "state_lookup",
                "hard",
                ["correction_aware", "facet_specific_validity", "stale_mention_distractor"],
                {"current_state": item["correction_result"]},
                {"current_state": [baseline, current_issue, correction]},
                [],
            ),
            5,
        ),
    ]
    return [
        add_case_with_negatives(case, scope_roles, events_by_scope, annotations_by_id, negative_limit)
        for case, negative_limit in rows
    ]


def new_scope_cases(
    scope_id: str,
    scope_roles: Mapping[str, str],
    events_by_scope: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations_by_id: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    item = scenario(scope_id)
    slug = slug_scope(scope_id)
    label = item["label"]
    pattern = NEW_SCOPE_DIFFICULTY_PATTERNS[scope_id]
    plan = event_id(scope_roles, "planned_review")
    next_plan = event_id(scope_roles, "next_plan")
    correction = event_id(scope_roles, "correction")
    baseline = event_id(scope_roles, "baseline_decision")
    current_issue = event_id(scope_roles, "current_issue")
    risk = event_id(scope_roles, "risk_update")
    final_signal = event_id(scope_roles, "final_signal_definition")
    rows = [
        (
            make_case(
                f"v13_{slug}_final_evidence_insufficient",
                query_text(
                    scope_id,
                    "new_insufficient",
                    [
                        "{label} 的“{insufficient_target}”现在有明确证据吗？",
                        "能不能判断{label}已经拿到“{insufficient_target}”？",
                        "{label} 是否已有“{insufficient_target}”的可靠记录？",
                    ],
                ),
                scope_id,
                "state_lookup",
                "medium",
                ["insufficient_evidence", "answerability", "long_context_noise"],
                {"evidence_status": insufficient_evidence_status(item)},
                {"evidence_status": []},
                [],
                answerability="insufficient_evidence",
            ),
            3,
        ),
        (
            make_case(
                f"v13_{slug}_compact_summary",
                query_text(
                    scope_id,
                    "new_summary",
                    [
                        "{label} 当前状态用一句话怎么概括？",
                        "如果压缩成状态摘要，{label} 现在应怎么说？",
                        "{label} 的有效状态和下一步可以合并概括成什么？",
                    ],
                ),
                scope_id,
                "state_summary",
                pattern[1],
                ["multi_facet_summary", "long_context_noise"],
                {"compact_summary": compact_state_summary(item)},
                {"compact_summary": [correction, next_plan]},
                [],
            ),
            1 if pattern[1] == "easy" else 3,
        ),
        (
            make_case(
                f"v13_{slug}_primary_next_action",
                query_text(
                    scope_id,
                    "new_next",
                    [
                        "{label} 现在最该先执行什么动作？",
                        "为了推进{label}，下一步应先落哪件事？",
                        "{label} 暂时不能直接收尾的话，应先做什么？",
                    ],
                ),
                scope_id,
                "next_action",
                pattern[2],
                ["next_action", "plan_not_done", "long_context_noise"],
                {"next_action": item["next_action"]},
                {"next_action": [plan, next_plan]},
                [],
                time_roles=("planned_for", "updated_at"),
            ),
            3 if pattern[2] == "medium" else 5 if pattern[2] == "hard" else 1,
        ),
        (
            make_case(
                f"v13_{slug}_current_obstacle",
                query_text(
                    scope_id,
                    "new_obstacle",
                    [
                        "{label} 当前真正需要处理的问题是什么？",
                        "在{label}里，哪个问题决定了当前状态？",
                        "{label} 目前不能继续按旧口径推进的原因是什么？",
                    ],
                ),
                scope_id,
                "state_lookup",
                pattern[3],
                ["latest_event_vs_state", "stale_mention_distractor"],
                {"current_obstacle": item["current_issue"]},
                {"current_obstacle": [current_issue, correction]},
                [],
            ),
            3 if pattern[3] == "medium" else 5 if pattern[3] == "hard" else 1,
        ),
        (
            make_case(
                f"v13_{slug}_risk_summary",
                query_text(
                    scope_id,
                    "new_risk_summary",
                    [
                        "{label} 当前风险和下一步如何一起说明？",
                        "汇报{label}时，风险和后续动作应怎么成对表达？",
                        "{label} 的风险点与下一步分别是什么？",
                    ],
                ),
                scope_id,
                "state_summary",
                pattern[4],
                ["multi_facet_summary", "correction_aware", "long_context_noise"],
                {"risk": item["risk"], "next_action": item["next_action"]},
                {"risk": [risk], "next_action": [next_plan]},
                [],
            ),
            3 if pattern[4] == "medium" else 5 if pattern[4] == "hard" else 1,
        ),
        (
            make_case(
                f"v13_{slug}_corrected_decision",
                query_text(
                    scope_id,
                    "new_corrected",
                    [
                        "{label} 还应该沿用“{old_plan}”吗？",
                        "{label} 的旧方案“{old_plan}”现在是否已经被替代？",
                        "当前判断{label}时，能不能继续引用“{old_plan}”？",
                    ],
                ),
                scope_id,
                "state_lookup",
                pattern[5],
                ["correction_aware", "facet_specific_validity", "stale_mention_distractor"],
                {"current_decision": item["correction_result"]},
                {"current_decision": [baseline, correction]},
                [],
            ),
            3 if pattern[5] == "medium" else 5 if pattern[5] == "hard" else 1,
        ),
        (
            make_case(
                f"v13_{slug}_planned_item_unknown",
                query_text(
                    scope_id,
                    "new_unknown",
                    [
                        "{label} 的“{unknown_target}”已经完成了吗？",
                        "现在能确认{label}的“{unknown_target}”已经落地了吗？",
                        "{label} 关于“{unknown_target}”有没有完成记录？",
                    ],
                ),
                scope_id,
                "state_lookup",
                "medium",
                ["unknown_current", "plan_not_done", "long_context_noise"],
                {"planned_item_status": f"只有“{item['planned_action']}”的安排，没有“{item['unknown_target']}”完成记录。"},
                {"planned_item_status": [plan]},
                [],
                answerability="unknown_current",
                time_roles=("planned_for", "updated_at"),
            ),
            3,
        ),
        (
            make_case(
                f"v13_{slug}_finish_condition_next",
                query_text(
                    scope_id,
                    "new_finish_condition",
                    [
                        "{label} 要接近完成状态，下一步应验证什么？",
                        "要判断{label}可以收尾，接下来需要看哪个完成信号？",
                        "{label} 离完成还差哪类明确证据？",
                    ],
                ),
                scope_id,
                "next_action",
                pattern[7],
                ["next_action", "cross_time_constraint", "long_context_noise"],
                {"next_action": f"验证是否出现“{item['final_signal']}”的明确证据。"},
                {"next_action": [final_signal, next_plan]},
                [],
                time_roles=("planned_for", "updated_at"),
            ),
            3 if pattern[7] == "medium" else 5 if pattern[7] == "hard" else 1,
        ),
        (
            make_case(
                f"v13_{slug}_planned_followup",
                query_text(
                    scope_id,
                    "new_followup",
                    [
                        "{label} 后续动作应该围绕哪个状态对象展开？",
                        "继续跟进{label}时，应该盯住哪个状态对象？",
                        "{label} 的下一轮追踪应聚焦什么？",
                    ],
                ),
                scope_id,
                "next_action",
                pattern[8],
                ["next_action", "facet_specific_validity"],
                {"followup_focus": f"后续应围绕“{item['state_object']}”推进，具体动作是“{item['next_action']}”。"},
                {"followup_focus": [next_plan]},
                [],
                time_roles=("planned_for", "updated_at"),
            ),
            0 if pattern[8] == "easy" else 3,
        ),
    ]
    return [
        add_case_with_negatives(case, scope_roles, events_by_scope, annotations_by_id, negative_limit)
        for case, negative_limit in rows
    ]


def public_case(case: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "query": str(case["query"]),
        "operation": str(case["operation"]),
    }


def case_split(case: Mapping[str, Any], splits: Mapping[str, Sequence[str]]) -> str:
    scope_id = str(case["scope_id"])
    for split, scopes in splits.items():
        if scope_id in set(scopes):
            return split
    return "unknown"


def pick_round_robin_by_split(
    candidates: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Sequence[str]],
    count: int,
) -> List[Mapping[str, Any]]:
    buckets: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for case in candidates:
        buckets[case_split(case, splits)].append(case)
    picked: List[Mapping[str, Any]] = []
    split_order = ["test", "dev", "train"]
    while len(picked) < count and sum(len(bucket) for bucket in buckets.values()) > 0:
        progressed = False
        for split in split_order:
            bucket = buckets.get(split, [])
            if bucket and len(picked) < count:
                picked.append(bucket.pop(0))
                progressed = True
        if not progressed:
            break
    return picked


def choose_balanced_subset(cases: Sequence[Mapping[str, Any]], splits: Mapping[str, Sequence[str]]) -> List[str]:
    total = 120
    per_level = total // 3
    difficulty_remaining = {"easy": per_level, "medium": per_level, "hard": per_level}
    selected: List[Mapping[str, Any]] = []
    selected_ids: set[str] = set()

    def add_from_candidates(candidates: Sequence[Mapping[str, Any]], count: int) -> None:
        if count <= 0:
            return
        ordered = pick_round_robin_by_split(
            [case for case in candidates if str(case["case_id"]) not in selected_ids],
            splits,
            count,
        )
        added = 0
        for case in ordered:
            level = str(case.get("difficulty_level"))
            if difficulty_remaining.get(level, 0) <= 0:
                continue
            selected.append(case)
            selected_ids.add(str(case["case_id"]))
            difficulty_remaining[level] -= 1
            added += 1
            if added >= count:
                break

    def selected_operation_count(operation: str) -> int:
        return sum(1 for case in selected if case.get("operation") == operation)

    add_from_candidates(
        [case for case in cases if case.get("difficulty_level") == "medium" and case.get("answerability") == "unknown_current"],
        12,
    )
    add_from_candidates(
        [case for case in cases if case.get("difficulty_level") == "medium" and case.get("answerability") == "insufficient_evidence"],
        12,
    )
    for level in ["hard", "medium", "easy"]:
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level and case.get("operation") == "next_action"],
            24 - selected_operation_count("next_action"),
        )
    for level in ["hard", "easy", "medium"]:
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level and case.get("operation") == "state_summary"],
            24 - selected_operation_count("state_summary"),
        )
    for level in ["easy", "medium", "hard"]:
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level and case.get("operation") == "state_lookup"],
            difficulty_remaining[level],
        )
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level],
            difficulty_remaining[level],
        )
    if len(selected) != total or any(value != 0 for value in difficulty_remaining.values()):
        raise RuntimeError(f"could not build balanced subset: selected={len(selected)} remaining={difficulty_remaining}")
    return [str(case["case_id"]) for case in cases if str(case["case_id"]) in selected_ids]


def choose_smoke_subset(cases: Sequence[Mapping[str, Any]], splits: Mapping[str, Sequence[str]]) -> List[str]:
    total = 12
    difficulty_remaining = {"easy": 4, "medium": 4, "hard": 4}
    selected: List[Mapping[str, Any]] = []
    selected_ids: set[str] = set()

    def add_from_candidates(candidates: Sequence[Mapping[str, Any]], count: int) -> None:
        if count <= 0:
            return
        ordered = pick_round_robin_by_split(
            [case for case in candidates if str(case["case_id"]) not in selected_ids],
            splits,
            count,
        )
        added = 0
        for case in ordered:
            level = str(case.get("difficulty_level"))
            if difficulty_remaining.get(level, 0) <= 0:
                continue
            selected.append(case)
            selected_ids.add(str(case["case_id"]))
            difficulty_remaining[level] -= 1
            added += 1
            if added >= count:
                break

    def selected_operation_count(operation: str) -> int:
        return sum(1 for case in selected if case.get("operation") == operation)

    add_from_candidates(
        [case for case in cases if case.get("difficulty_level") == "medium" and case.get("answerability") == "unknown_current"],
        1,
    )
    add_from_candidates(
        [case for case in cases if case.get("difficulty_level") == "medium" and case.get("answerability") == "insufficient_evidence"],
        1,
    )
    for level in ["hard", "medium", "easy"]:
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level and case.get("operation") == "next_action"],
            2 - selected_operation_count("next_action"),
        )
    for level in ["hard", "easy", "medium"]:
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level and case.get("operation") == "state_summary"],
            3 - selected_operation_count("state_summary"),
        )
    for level in ["easy", "medium", "hard"]:
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level and case.get("operation") == "state_lookup"],
            difficulty_remaining[level],
        )
        add_from_candidates(
            [case for case in cases if case.get("difficulty_level") == level],
            difficulty_remaining[level],
        )
    if len(selected) != total or any(value != 0 for value in difficulty_remaining.values()):
        raise RuntimeError(f"could not build smoke subset: selected={len(selected)} remaining={difficulty_remaining}")
    return [str(case["case_id"]) for case in cases if str(case["case_id"]) in selected_ids]


def count_bins(values: Iterable[int], bins: Sequence[tuple[str, int | None, int | None]]) -> Dict[str, int]:
    counts = {name: 0 for name, _, _ in bins}
    for value in values:
        for name, low, high in bins:
            if (low is None or value >= low) and (high is None or value <= high):
                counts[name] += 1
                break
    return counts


def normalized_text_counter(
    values: Iterable[str],
    scope_ids: Sequence[str],
) -> Counter[str]:
    scope_pattern = re.compile("|".join(re.escape(scope_id) for scope_id in sorted(scope_ids, key=len, reverse=True)))
    counter: Counter[str] = Counter()
    for value in values:
        text = scope_pattern.sub("<scope>", str(value))
        text = re.sub(r"\d+", "<n>", text)
        text = re.sub(r"\s+", " ", text).strip()
        counter[text] += 1
    return counter


def slot_values(cases: Sequence[Mapping[str, Any]]) -> List[str]:
    values: List[str] = []
    for case in cases:
        slots = case.get("gold_state_slots", {})
        if isinstance(slots, Mapping):
            values.extend(str(value) for value in slots.values())
    return values


def quality_audit(events: Sequence[Mapping[str, Any]], cases: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    scope_ids = sorted({str(event["scope_id"]) for event in events})
    event_counter = normalized_text_counter([str(event.get("content", "")) for event in events], scope_ids)
    query_counter = normalized_text_counter([str(case.get("query", "")) for case in cases], scope_ids)
    slot_counter = normalized_text_counter(slot_values(cases), scope_ids)
    generic_markers = ["旁路日志采样", "轻量复查", "旧完成状态", "主线阻塞", "approval", "acceptance"]
    combined_text = "\n".join(
        [str(event.get("content", "")) for event in events]
        + [str(case.get("query", "")) for case in cases]
        + slot_values(cases)
    )
    return {
        "max_normalized_event_repeat": max(event_counter.values(), default=0),
        "max_normalized_query_repeat": max(query_counter.values(), default=0),
        "max_normalized_slot_value_repeat": max(slot_counter.values(), default=0),
        "event_repeats_over_8": {text: count for text, count in event_counter.items() if count > 8},
        "query_repeats_over_8": {text: count for text, count in query_counter.items() if count > 8},
        "slot_value_repeats_over_8": {text: count for text, count in slot_counter.items() if count > 8},
        "generic_marker_counts": {marker: combined_text.count(marker) for marker in generic_markers},
    }


def build_audit(
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Sequence[str]],
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        by_scope[str(event["scope_id"])].append(event)
    scope_sizes = {scope: len(rows) for scope, rows in sorted(by_scope.items())}
    case_scope_sizes = [scope_sizes[str(case["scope_id"])] for case in cases]
    hard_negative_counts = [len(normalize_id_list(case.get("hard_negative_events"))) for case in cases]
    gold_counts = [len(normalize_id_list(case.get("gold_events"))) for case in cases]
    hard_negative_type_counter: Counter[str] = Counter()
    for case in cases:
        for labels in case.get("hard_negative_types", {}).values():
            hard_negative_type_counter.update(str(label) for label in labels)
    audit = {
        "events": len(events),
        "cases": len(cases),
        "scopes": len(by_scope),
        "scope_event_counts": scope_sizes,
        "scope_event_bins": count_bins(scope_sizes.values(), [("short_<=12", None, 12), ("medium_13_18", 13, 18), ("long_19+", 19, None)]),
        "case_scope_event_bins": count_bins(case_scope_sizes, [("short_<=12", None, 12), ("medium_13_18", 13, 18), ("long_19+", 19, None)]),
        "difficulty_level": dict(sorted(Counter(str(case.get("difficulty_level", "unset")) for case in cases).items())),
        "answerability": dict(sorted(Counter(str(case.get("answerability")) for case in cases).items())),
        "operation": dict(sorted(Counter(str(case.get("operation")) for case in cases).items())),
        "operation_subtype": dict(sorted(Counter(str(case.get("operation_subtype", "unset")) for case in cases).items())),
        "gold_event_count": dict(sorted(Counter(gold_counts).items())),
        "hard_negative_count": dict(sorted(Counter(hard_negative_counts).items())),
        "hard_negative_type": dict(sorted(hard_negative_type_counter.items())),
        "hard_negative_total": sum(hard_negative_counts),
        "gold_event_total": sum(gold_counts),
        "split_cases": dict(sorted(Counter(case_split(case, splits) for case in cases).items())),
        "scope_type": dict(sorted(Counter(str(taxonomy.get(str(scope), {}).get("scope_type", "unknown")) for scope in by_scope).items())),
        "case_scope_type": dict(sorted(Counter(str(taxonomy.get(str(case["scope_id"]), {}).get("scope_type", "unknown")) for case in cases).items())),
        "answerability_by_scope": {
            scope: dict(sorted(Counter(str(case.get("answerability")) for case in cases if str(case["scope_id"]) == scope).items()))
            for scope in sorted(by_scope)
        },
        "difficulty_by_split": {
            split: dict(sorted(Counter(str(case.get("difficulty_level")) for case in cases if case_split(case, splits) == split).items()))
            for split in sorted(splits)
        },
    }
    audit["quality"] = quality_audit(events, cases)
    return audit


def taxonomy_rows(taxonomy: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [{"scope_id": scope_id, **values} for scope_id, values in sorted(taxonomy.items())]


def enriched_scope_profiles(events: Sequence[Mapping[str, Any]], taxonomy: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    profiles = build_scope_profiles(events)
    for profile in profiles:
        profile.update(taxonomy.get(str(profile.get("scope_id")), {}))
    return profiles


def write_public_track(
    out_dir: Path,
    events: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    subsets: Mapping[str, Sequence[str]],
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> None:
    public_dir = out_dir / "public"
    write_json(public_dir / "events.json", list(events))
    write_json(public_dir / "cases.json", [public_case(case) for case in cases])
    write_json(public_dir / "scope_profiles.json", enriched_scope_profiles(events, taxonomy))
    write_json(public_dir / "scope_taxonomy.json", taxonomy_rows(taxonomy))
    write_json(public_dir / "subsets.json", subsets)
    (public_dir / "README.md").write_text(
        "# STAMB-State v1_3 Public Track\n\n"
        "`events.json`, `cases.json`, `scope_profiles.json`, `scope_taxonomy.json`, and `subsets.json` are the no-gold end-to-end input files.\n"
        "`scope_taxonomy.json` contains public-safe scope type, task family, and domain labels for routing and breakdown analysis.\n"
        "`subsets.json` contains only case ids, not gold labels or difficulty metadata.\n"
        "Evaluator-only fields are retained only in `../cases.json` and annotation files.\n",
        encoding="utf-8",
    )


def build_readme(audit: Mapping[str, Any]) -> str:
    quality = audit["quality"]
    return "\n".join(
        [
            "# STAMB-State v1.3",
            "",
            "v1.3 is the final-size public benchmark. It keeps the latest-valid-state retrieval contract while replacing template-style expansion with scope-specific event streams and cases.",
            "",
            "## Counts",
            "",
            f"- events: {audit['events']}",
            f"- cases: {audit['cases']}",
            f"- scopes: {audit['scopes']}",
            f"- scope_event_bins: {audit['scope_event_bins']}",
            f"- case_scope_event_bins: {audit['case_scope_event_bins']}",
            f"- difficulty_level: {audit['difficulty_level']}",
            f"- answerability: {audit['answerability']}",
            f"- operations: {audit['operation']}",
            f"- operation_subtype: {audit['operation_subtype']}",
            f"- scope_type: {audit['scope_type']}",
            f"- hard_negative_count: {audit['hard_negative_count']}",
            f"- hard_negative_type: {audit['hard_negative_type']}",
            f"- hard_negative_total: {audit['hard_negative_total']}",
            f"- gold_event_total: {audit['gold_event_total']}",
            "",
            "## Quality Audit",
            "",
            f"- max_normalized_event_repeat: {quality['max_normalized_event_repeat']}",
            f"- max_normalized_query_repeat: {quality['max_normalized_query_repeat']}",
            f"- max_normalized_slot_value_repeat: {quality['max_normalized_slot_value_repeat']}",
            f"- generic_marker_counts: {quality['generic_marker_counts']}",
            "",
            "## Added Coverage",
            "",
            "- 24 public scope streams and 480 public events;",
            "- 240 evaluator cases with operation mix near 60/20/20;",
            "- public-safe scope taxonomy expanded to 24 scope domains;",
            "- balanced half subset with 120 cases for cheaper public E2E runs;",
            "- domain-specific hard negatives and answerability cases instead of cross-scope boilerplate.",
            "",
            "## Validation",
            "",
            "```bash",
            "python scripts/validate_v1.py --v1-dir /Users/mac/Desktop/EpisodicMemory/stamb_state_benchmark/data/v1_3",
            "python scripts/audit_benchmark_quality.py --v1-dir /Users/mac/Desktop/EpisodicMemory/stamb_state_benchmark/data/v1_3 --fail-on-warnings",
            "python Experiment/run/run_public_benchmark.py --data-version v1_3 --case-subset balanced_half --dry-run",
            "```",
            "",
        ]
    )


def only_original_rows(rows: Sequence[Mapping[str, Any]], key: str) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows if not str(row.get(key, "")).startswith("v12_")]


def build_v1_3(source_dir: Path, out_dir: Path) -> Dict[str, Any]:
    source_events = only_original_rows(read_json(source_dir / "events_raw.json"), "event_id")
    source_annotations = only_original_rows(read_json(source_dir / "event_annotations.json"), "event_id")
    source_cases = only_original_rows(read_json(source_dir / "cases.json"), "case_id")
    source_splits = read_json(source_dir / "splits.json")
    source_claims = read_json(source_dir / "claim_annotations.json")
    source_taxonomy = {
        row["scope_id"]: {key: value for key, value in row.items() if key != "scope_id"}
        for row in read_json(source_dir / "scope_taxonomy.json")
    }
    taxonomy = {**source_taxonomy, **NEW_SCOPE_TAXONOMY}

    by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in source_events:
        by_scope[str(row["scope_id"])].append(row)

    generated_rows: List[Dict[str, Any]] = []
    for scope_id, target_count in TARGET_SCOPE_EVENT_COUNTS.items():
        generated_rows.extend(generated_event_rows(scope_id, by_scope.get(scope_id, []), target_count))

    role_map = infer_existing_roles(source_events)
    add_generated_roles(role_map, generated_rows)

    events = [dict(row) for row in source_events] + [raw_event(row) for row in generated_rows]
    annotations = [dict(row) for row in source_annotations] + [event_annotation(row) for row in generated_rows]
    events_by_scope: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_scope[str(event["scope_id"])].append(event)
    annotations_by_id = {str(row["event_id"]): row for row in annotations}

    cases: List[Dict[str, Any]] = [
        repair_source_case_hard_negatives(row, role_map[str(row["scope_id"])], events_by_scope, annotations_by_id)
        for row in source_cases
    ]
    original_scopes = sorted({str(event["scope_id"]) for event in source_events})
    new_scopes = [scope_id for scope_id in TARGET_SCOPE_EVENT_COUNTS if scope_id not in set(original_scopes)]
    for scope_id in original_scopes:
        cases.extend(existing_scope_cases(scope_id, role_map[scope_id], events_by_scope, annotations_by_id))
    for scope_id in new_scopes:
        cases.extend(new_scope_cases(scope_id, role_map[scope_id], events_by_scope, annotations_by_id))

    splits = {split: list(scopes) + NEW_SPLIT_SCOPES.get(split, []) for split, scopes in source_splits.items()}
    require_unique(events, "event_id", "events")
    require_unique(annotations, "event_id", "event_annotations")
    require_unique(cases, "case_id", "cases")
    if len(events) != 480 or len(cases) != 240:
        raise RuntimeError(f"unexpected v1.3 size: events={len(events)} cases={len(cases)}")
    if set(taxonomy) != {str(event["scope_id"]) for event in events}:
        missing = sorted({str(event["scope_id"]) for event in events} - set(taxonomy))
        extra = sorted(set(taxonomy) - {str(event["scope_id"]) for event in events})
        raise RuntimeError(f"taxonomy mismatch: missing={missing} extra={extra}")

    subsets = {
        "balanced_half": choose_balanced_subset(cases, splits),
        "smoke_12": choose_smoke_subset(cases, splits),
    }
    audit = build_audit(events, cases, splits, taxonomy)

    write_json(out_dir / "events_raw.json", events)
    write_json(out_dir / "event_annotations.json", annotations)
    write_json(out_dir / "claim_annotations.json", source_claims)
    write_json(out_dir / "cases.json", cases)
    write_json(out_dir / "splits.json", splits)
    write_json(out_dir / "scope_taxonomy.json", taxonomy_rows(taxonomy))
    write_json(out_dir / "subsets.json", subsets)
    write_json(out_dir / "benchmark_audit.json", audit)
    write_json(out_dir / "quality_audit.json", audit["quality"])
    write_public_track(out_dir, events, cases, subsets, taxonomy)
    (out_dir / "README.md").write_text(build_readme(audit), encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Build STAMB-State v1.3 from v1.2 original rows plus scope-specific expansion.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_V1_2_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_V1_3_DIR)
    args = parser.parse_args()

    audit = build_v1_3(args.source_dir, args.out_dir)
    print(f"wrote {args.out_dir}")
    print(f"events={audit['events']} cases={audit['cases']} scopes={audit['scopes']}")
    print(f"difficulty_level={audit['difficulty_level']}")
    print(f"operations={audit['operation']}")
    print(f"answerability={audit['answerability']}")
    print(f"quality={audit['quality']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# LoCoMo v3 状态与身份修复设计

## 目的

修复 LoCoMo v3 构图器，使 `StateFacet` 表达经过解析的持久状态，而不是基本等同于
“一条 Claim 对应一个 Facet”的投影。设计必须保持在 Scope-Time-State 边界内：
Subject identity 只负责确定状态归属者，不承担开放世界实体消歧。

这是两个独立改动中的第一部分。本设计只覆盖 Subject 归属、语义状态分组、状态解析、
验证和死代码删除。Time role 与绝对时间规范化改进明确推迟到第二部分，并且只有在本设计
完成实现和验证后才开始。

## 当前故障

当前构图器先规范化原始 `state_slot` 标签，再按 slot 切分 Claim，之后才调用语义状态组
resolver。因此，slot alias 阶段一旦出现假阴性就无法恢复：本应比较的 Claim 永远不会进入
同一次 resolver 调用。现有产物中，`conv-26` 的 85 条 persistent Claim 生成了 85 个
StateFacet；`conv-42` 的 126 条 persistent Claim 生成了 124 个 StateFacet。

尚未完成的全局 Subject reconciler 是另一个独立回归。它把“状态归属”扩展成了 Claim
级全局实体消歧，并引入 qualifier span、内部 cluster ID、分页 reconciliation 和局部 ID
命名空间。其协议已经与四个现有测试不一致，同时也没有阻止 `Nate's pets` 被粗粒度合并到
`Nate`。

## 目标

1. 即使原始 `state_slot` 标签不同，语义相关的 persistent Claim 也能进入同一次最终分组。
2. 即使共享原始 slot 或主题，不同状态维度仍必须保持分离。
3. 仅使用 STS 所需的最小身份机制解析 Subject 归属。
4. 允许同一状态维度的正值和负值相互比较，但不能把它们合成一个 value。
5. 要求 LLM assignment 完整且通过验证，并保持图产物的原子写入。
6. 删除被新路径替代的 Subject 和 slot 代码；不保留 legacy fallback、兼容开关或第二套活跃实现。
7. 在新实现通过完整测试并输出到新目录之前，保留现有图产物不变。

## 非目标

- 开放世界实体消歧或跨对话身份关联。
- Claim 提取重构或 Claim 召回率优化。
- 修改 Time role、增加新 Time role 或扩展时间 grounding。
- 追求某个固定合并比例。验收依据是正负 golden fixture 的正确性，而不是为了合并而合并。
- 静默截断、损失性窗口处理或 `latest Claim = current` fallback。

## 选定架构

```text
grounded Claims
  -> 最小 Subject 归属解析
  -> 高召回临时状态候选族
  -> 候选族内 Object identity
  -> 最终语义 slot/group/cardinality/value assignment
  -> 最终状态 bucket
  -> 当前状态解析与显式 validity relation
  -> StateFacets
```

临时候选族不是图中的 canonical identity。它唯一的作用是提高最终语义 resolver 的召回，
从而恢复原始 slot 表达差异造成的漏分组。最终 resolver 仍负责拆开不同状态维度。

## Subject 归属

`canonical_subject` 是 grounded Claim 提取阶段给出的状态归属者。Subject 解析遵循以下规则：

1. 规范化后 Subject 标签相同的 Claim 使用同一个确定性 owner ID，不调用 LLM。
2. 存在不同标签时，只允许一次有界的标签级 LLM alias assignment，用于合并
   `Caro`/`Caroline`、`Melanie's kids`/`Melanie's children` 等明确别名。
3. LLM 只返回标签的完整分区。构图器根据通过验证的分组确定性生成 canonical subject ID，
   因而模型不能在不同运行间自由创造或漂移 canonical ID。
4. 只有整个 assignment 通过验证后，结果才会写回 Claim。
5. owner/possessed-entity guard 必须拒绝把裸 owner 与其所有物合并，例如
   `Nate` 与 `Nate's pets`。
6. 完全同名但实际不同的实体不在这一层处理。对话要求区分时，Claim 提取阶段必须给出有
   原文依据的限定归属者，例如 `coworker Alex` 与 `cousin Alex`。

构图器不对 Subject cluster 做分页、分片或全局 reconciliation；不再存在 qualifier-span
协议或 response-local Subject 命名空间。

## 候选族

对于每个 canonical subject，一次 Subject 级 LLM assignment 跨原始 slot 标签建立临时
候选族。候选族追求高召回：可能描述同一状态维度的 Claim 应进入同一候选族；明显无关的
维度可以提前分开。

候选族 assignment 接收 Claim 上下文，包括原始 slot、object、answer span、完整 grounded
evidence、memory kind、modality、polarity 和 reported time。它必须让每条符合条件的
persistent Claim 恰好出现一次。候选族 ID 只是临时 ID，不得写入 node、edge、canonical ID
或图 provenance。

原始 `state_slot` 只是候选族判断的证据，不再是硬分桶键。旧 slot-alias 结果不作为 fallback
保留。

## 候选族内 Object identity

候选族通过验证后，在每个候选族内部独立执行现有的 Claim 级 Object assignment。它接收该
候选族的全部成员及其 grounded evidence，并为每条 Claim 返回一个 canonical object ID。
它可以合并明确别名，同时必须保持同名异物分离；在完整覆盖候选族之前不得修改任何 Claim。

Object identity 不得再次把候选族切成硬状态 bucket。最终语义 resolver 仍会看到候选族内的
全部 Claim 及其已分配的 object ID，并负责决定最终状态维度。

## 最终语义状态 assignment

每个候选族由一次语义 assignment 输出一个或多个最终 group。每个最终 group 必须包含：

- `canonical_state_slot`
- `canonical_state_group_id`
- `state_cardinality`，且只能是 `single` 或 `multi`
- 完整的成员 Claim ID
- 每条成员 Claim 对应的一个 `canonical_state_value_id`

validator 要求每条输入 Claim 恰好出现在一个最终 group 中；同一 Subject 的所有候选族之间
group ID 也必须唯一；每个成员必须具备全部 canonical 字段；每个最终 group 只能声明一次
cardinality。完整结果通过验证后才会写回 Claim。

最终 resolver 可以把不同原始 slot 合并为同一状态维度，也可以把相同原始 slot 拆成不同
维度。`screenplay_theme` 与 `screenplay_status` 等相关但不同的维度必须保持分离。

正值和负值 Claim 可以属于同一个最终状态 group。polarity 仍是 canonical state-value key
的一部分，因此相反断言不能成为同一个 value 的 support。需要淘汰旧值时，后续 resolver
必须显式给出 `CORRECTS`、`SUPERSEDES` 或 `CONFLICTS_WITH` relation。

## 当前状态解析

最终状态 bucket 仍由 canonical subject、最终 state group 和最终 state slot 共同确定。
当前状态 resolver 必须：

- 把同一 canonical value 的 Claim 合并到一个 StateFacet support 集合；
- 只有 `multi` group 才允许多个同时有效的 value；
- `single` group 必须输出且只输出一个 current 或 ambiguous value；
- 不得把已被 corrected 或 superseded 的 Claim 保留为 current primary；
- 不得把不同 value 隐藏在同一个 support list 中；
- 每条未 materialize 为当前状态的 Claim 都必须通过显式 validity relation 与已 materialize
  状态保持连通；
- 语义解析不完整时，绝不能默认使用最新 Claim。

## 大输入与失败语义

数字 24 不是语义边界。修复后的 v3 路径不会仅仅因为候选族或状态 bucket 超过 24 条 Claim
就失败。

只要完整输入能够进入所配置模型的 context，resolver 就必须看到全部输入。返回结果仍必须
完整覆盖所有 Claim 且不得重复。只有完整请求确实无法进入模型容量、provider 调用失败，或
在配置的重试次数后语义验证仍不完整时，构图才失败。

构图器不得截断候选族、丢弃 Claim、静默拆开 equivalence class，也不得重新引入带 anchor
的分页 reconciliation。所有失败都必须发生在替换输出之前，并保留原图目录。

## 验证与原子性

语义边界继续执行 fail-closed 验证：

- Subject 标签必须形成完整合法分区；
- 候选族必须恰好覆盖每条符合条件的 persistent Claim；
- 最终 group 必须恰好覆盖所属候选族的每个成员；
- 所有 canonical state/object 字段必须非空且合法；
- 每个最终 group 只能声明一次且内部一致的 cardinality；
- StateFacet support list 与 `SUPPORTS` edge 必须完全一致；
- obsolete 与 conflicting value 必须遵守显式 relation 语义；
- 所有 Claim 和 StateFacet provenance 必须能追溯到源 Event。

任何部分验证通过的 assignment 都不能写进 Claim dictionary。图输出继续使用同级临时目录
分阶段写入，并且只有在完整图验证成功后才替换目标目录。

## 死代码删除

实现中必须删除被替代的 Subject 机制，包括 qualifier 常量与验证、Claim 级 Subject
assignment、全局 initial/batch/page reconciliation、内部 cluster ID、local-ID namespace、
Subject shard cache stage，以及 `llm_global_subject_identity_reconciliation` provenance。

同时删除旧 slot representative、slot alias、canonical-slot 预分桶路径及其专用 provenance；
删除只用于维持 qualifier、分页或 local-ID 架构的测试。

通用 label 与 Claim-ID assignment helper 只有在 Object 或最终语义 assignment 路径中仍有
活跃调用者时才可保留。未使用 helper、import、prompt builder、cache stage 和兼容分支必须在
同一改动中删除。

## 测试驱动验收

每个生产代码改动都必须先由失败的回归测试证明目标行为。必须覆盖以下 fixture：

1. 完全相同的 Subject 标签无需 LLM 即可确定性合并。
2. `Caro` 与 `Caroline` 可以通过标签级 alias assignment 合并。
3. 即使 LLM 建议合并，`Nate` 与 `Nate's pets` 也不能共享 canonical subject ID。
4. `coworker Alex` 与 `cousin Alex` 等 grounded 限定归属者保持分离。
5. 描述同一生命周期的不同原始 slot 能进入同一最终 group，并能产生显式 supersession。
6. 同一原始 slot 用于不同状态维度时，必须拆成不同最终 group。
7. 相关但不同的状态维度不得合并。
8. `multi` group 中多个兼容 value 必须保持为不同的 current StateFacet。
9. 正值和负值可以共享 group，但不能共享一个 support value；淘汰其中一个时必须存在 relation。
10. 超过 24 条 Claim 时，完整输入必须进入 resolver，而不是被拒绝或截断。
11. assignment 遗漏、重复或字段非法时，必须在修改 Claim 或替换输出之前失败。

全部现有 LoCoMo graph 测试与新增 fixture 都必须通过。验收依据是 fixture 正确性和图 invariant，
而不是强迫总体 consolidation rate 达到某个数值。

## 产物验证

完整测试通过后，使用指定的 `gpt-4o-mini` 配置把 `conv-26`、`conv-42`、`conv-43` 构建到
新的图目录，不覆盖当前 v3 产物。

新产物必须审计：

- Claim 到 StateFacet 的 support-size 分布；
- 多 Claim 语义 group 及其 evidence；
- 跨 owner、object 和 state dimension 的错误合并；
- 显式状态 `CORRECTS`、`SUPERSEDES` 与 `CONFLICTS_WITH` relation；
- 完整 provenance 与零图验证 warning。

只有这些语义检查与 golden fixture 和人工 evidence 检查一致时，新图才通过验收。更高的合并
比例本身不能证明构图正确。

## 推迟的 Time 改动

后续独立的 Time 设计将处理：可唯一解析表达的确定性 grounding、根据 role 判断 weekday
方向、句首 lifecycle 时间表达，以及绝对时间无法解析时正确的 null 字段语义。这些改动均不
属于本次实现。

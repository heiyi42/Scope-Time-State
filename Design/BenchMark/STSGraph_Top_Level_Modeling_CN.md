# Scope-Time-State Graph 顶层科学问题建模草稿

这份中文稿先用于和导师讨论。它的目标不是替换现有 benchmark，也不是立刻把系统改成图数据库，而是把 STAMB-State 的顶层科学问题、图模型和 solution 路径先讲清楚。后续可以再把其中稳定的部分翻成英文论文 section。

## 1. 对导师意见的理解

导师意见的核心是：现在已有底层技术方案，例如事件检索、两阶段 state construction、graph trace、benchmark 指标等，但论文还缺一个更高层的科学问题建模。

也就是说，我们不能只说“我们设计了一个 pipeline，效果比 baseline 好”。更强的表达应该是：

> 长期记忆中的状态查询，本质上不是检索最近事件，也不是普通 temporal KG 查询，而是在一个由 scope、time role、claim validity 和 state facet 共同约束的图上，构造当前有效状态。

因此，Scope-Time-State Graph 应该承担两个作用：

1. 问题分析建模：解释长期记忆为什么会出现“最近事件”和“当前状态”不一致的问题。
2. solution 可解释和可溯源：让系统在生成答案前显式构造 state packet / graph trace，使每个答案都能追溯到 event、claim、validity edge 和 state facet。

## 2. 核心判断

我认为这个方向是对的，而且不需要推翻当前 benchmark。

更稳的定位是：

> STAMB-State benchmark 评测的是 latest valid state construction；Scope-Time-State Graph 是这个任务背后的科学模型和 solution 中间表示。

这和 `STSGraph_Pipeline_Benchmark_Codex_Spec.md` 的建议是一致的：论文需要图模型，但 benchmark MVP 不需要依赖 Neo4j、Graphiti 或 Zep 这类图数据库。当前阶段用 JSON / Python object / in-memory graph 表示 graph trace 就够了。

换句话说：

- Graph model 是理论层；
- state packet / graph trace 是方法层；
- `state_slots + support_events + answer` 是 benchmark 输出层；
- `sup_f1 / slot_j / ans_j` 是评测层。

这四层要分开写，不能混在一起。

## 3. 顶层科学问题

可以把科学问题定义为：

```text
Given a long-term memory event stream and a state-oriented query,
construct the latest valid multi-facet state of the target scope,
with explicit evidence and validity trace.
```

中文表述可以是：

> 给定一个长期记忆事件流和一个状态型查询，系统需要确定查询所指向的 scope、应该使用的 time role、仍然有效的 evidence claims，以及当前应该返回的 state facets，并生成有证据支撑、可追溯的答案。

这里的难点不只是“找相关事件”，而是四类歧义叠加：

1. Scope ambiguity：用户问“这个项目最近怎么样”，系统要知道是哪个项目、任务、子任务或会话线程。
2. Time-role ambiguity：同一事件可能有 `occurred_at`、`mentioned_at`、`updated_at`、`planned_for`、`deadline_at`，而“最近”“当前”“原计划”“截止时间”对应的时间角色不同。
3. Validity ambiguity：最近事件可能只是复述、旧计划、无状态更新日志，也可能是纠错、覆盖或真正的新状态。
4. State-facet ambiguity：状态不是一个单一事实，而是由多个 facet 组成，例如 `current_decision`、`risk`、`next_step`、`current_issue`、`completion_status`。

所以论文的问题不应该写成“episodic memory retrieval”，而应该写成：

> Latest Valid State Construction under Scope-Time-State Ambiguity.

## 4. 为什么需要图模型

普通 RAG 通常把记忆看成 chunk 或 event，然后做相关性检索；temporal RAG 会额外考虑时间；temporal KG 会把事实和时间关系结构化。但这些还不够，因为状态查询要求系统判断：

- 哪些事件只是历史记录；
- 哪些 claim 已经被纠正或覆盖；
- 哪些最近出现的内容只是 mention，不代表状态变化；
- 哪些计划不能被当作已经完成；
- 哪些 facet 需要多条证据共同支撑；
- 最终答案中每句话来自哪个 state facet 和哪些 evidence events。

这就是 Scope-Time-State Graph 的位置。

它不是为了说明“我们用了图数据库”，而是为了说明：状态查询的正确输出必须经过一个图上的状态解析过程。

## 5. 和 Graphiti / Zep 的关系

可以借鉴 Graphiti / Zep 的表达方式：它们强调 agent memory 不是静态文档检索，而是一个随时间演化的 temporal knowledge graph。

但我们的贡献不能写成“复现 Graphiti”或“做一个类似 Graphiti 的系统”。更准确的边界是：

> Graphiti / Zep 关注通用 temporal context graph 的构建和查询；我们关注 state-oriented query 下的 latest valid state construction，即如何从事件、claim、validity relation 中构造当前有效的多 facet 状态。

也就是说，Graphiti / Zep 可以作为 related work 或 baseline，但 STSGraph 的贡献应放在 query-conditioned state construction：

- 它不是只返回 temporal facts；
- 它不是只维护历史关系；
- 它必须根据当前 query 的 scope、time role 和 facet 需求，构造一个当前有效的 state packet。

## 6. Scope-Time-State Graph 的基本建模

可以把图定义为：

```text
G = (V, E)
```

节点包括：

```text
V = V_scope ∪ V_event ∪ V_claim ∪ V_facet ∪ V_time ∪ V_source
```

主要节点类型：

- Scope node：项目、任务、子任务、实体或会话线程。
- Event node：原始记忆事件，例如聊天记录、日志、工具输出、计划、纠错记录。
- Claim node：从 event 中抽取出的原子状态断言。
- State facet node：某个 scope 当前或历史上的状态维度。
- Time node：不同时间角色，例如发生时间、提及时间、更新时间、计划时间、截止时间。
- Source node：用户、工具、系统、文档或日志来源。

主要边类型：

- `BELONGS_TO(Event, Scope)`：事件属于哪个 scope。
- `ASSERTS(Event, Claim)`：事件断言了哪个 claim。
- `SUPPORTS(Claim, StateFacet)`：claim 支撑哪个状态 facet。
- `CORRECTS(Claim_i, Claim_j)`：一个 claim 纠正另一个 claim。
- `SUPERSEDES(Claim_i, Claim_j)`：一个 claim 覆盖另一个 claim。
- `INVALIDATES(Claim_i, Claim_j)`：一个 claim 使另一个 claim 不再是当前有效状态。
- `OCCURRED_AT / MENTIONED_AT / UPDATED_AT / PLANNED_FOR / DEADLINE_AT`：事件或 claim 的时间角色。
- `CURRENT_STATE_OF(StateFacet, Scope)`：某个 facet 是当前 scope 的有效状态。

关键点是：validity 应该尽量是 claim-level，而不是 event-level。

一个事件作为历史记录可以是真的，但它里面的某个 claim 可能已经不是当前状态。例如：

```text
事件：原计划 6 月 8 日交第二章。
claim：deadline = 6 月 8 日。
后来事件：截止时间改到 6 月 10 日。
结论：旧事件仍然是历史事实，但旧 deadline claim 已经被 superseded。
```

## 7. Query-conditioned State Packet

针对一个查询 `q`，系统不是直接生成答案，而是先构造：

```text
StatePacket(q, G)
```

它应该包含：

- predicted scope；
- inferred time roles；
- candidate events；
- extracted claims；
- validity relations；
- current state facets；
- supporting event ids；
- rejected stale / distractor events；
- final answer trace。

可以写成：

```text
q
  -> ScopeAnchor(q)
  -> TimeRoleResolver(q)
  -> FacetPlanner(q)
  -> CandidateEvents(q)
  -> Claims(q)
  -> ValidityEdges(q)
  -> CurrentStateFacets(q)
  -> Answer(q)
```

这个 state packet 是 solution 的核心中间态。它让方法不是黑盒 answer generation，而是先做状态解析，再做答案表达。

## 8. 方法路径

结合当前 repo 和 md spec，方法可以写成以下 chain：

```text
public query + public events
  -> Query Analyzer
       - scope routing
       - time-role inference
       - operation / facet intent inference
  -> Scoped Event Selection
  -> STS Subgraph Constructor
       - claim extraction
       - validity edge inference
       - state facet aggregation
  -> Evidence & Coverage Verifier
  -> Answer Composer
```

其中最重要的是 STS Subgraph Constructor。它是我们的核心方法，而不是普通 retrieval。

它解决三个问题：

1. Claim extraction：把 event 拆成和状态相关的原子 claim。
2. Validity edge inference：判断 claim 之间是否存在 corrects、supersedes、invalidates、conflicts。
3. State facet aggregation：从仍然有效的 claims 中汇总当前状态 facet。

Answer Composer 只能 verbalize 已经验证过的 state packet，不能再搜索新证据，也不能临时改 evidence 或 state slots。

## 9. 和现有 benchmark 的关系

当前 benchmark 不需要推翻。

Oracle-Facet track 中，`scope_id`、`time_role` 和 `output_slots` 是给定的，目的是隔离 state construction 能力。这里的 `output_slots` 可以理解成 benchmark 控制下的 `F_q`，也就是查询需要返回哪些 state facets。

Public End-to-End track 中，这些东西不能直接给模型，需要系统自己从 public events 和 query 中推断：

- scope；
- time role；
- facet intents；
- candidate events；
- current state facets。

因此，图模型和 benchmark 的对应关系可以这样写：

| 图模型概念 | Benchmark 对应项 |
| --- | --- |
| `ScopeAnchor(q)` | Oracle-Facet 的 `scope_id`；Public track 中需要预测 |
| `TimeRoleResolver(q)` | `time_role` 或 public 推断结果 |
| `FacetPlanner(q)` | `output_slots` / free facet intents |
| valid claims | 支撑当前状态的 evidence events 和 slot support |
| state facets | `state_slots` / `gold_state_slots` |
| provenance trace | `support_events` / `gold_slot_support` |
| final answer | `answer` |

指标上也要保持现有判断：

- `sup_f1`：证据支撑是否完整；
- `slot_j`：state facet 值是否语义正确；
- `ans_j`：最终答案是否完整正确。

不要用 `event_f1` 作为主指标，因为它混合了直接支撑、上下文和可选相关事件，不能单独代表 state construction 的质量。

## 10. 当前实现如何支撑这个故事

现有实现里已经有两个可用支点：

1. 默认 two-stage pipeline：先构造 locked state slots，再生成 answer。
2. `graph_trace` ablation：在 answer 前生成 claims、relations、rejected_claims、state_facets，再由 `graph_trace.state_facets` 派生 `state_slots`。

这正好可以服务论文叙事：

- 主表可以继续用稳定的 two-stage 结果；
- graph_trace 可以作为 graph-guided readout / explainability ablation；
- case figure 可以展示为什么最新事件不是当前状态，以及旧 claim 如何被新 claim 覆盖；
- 不需要改变 gold benchmark contract。

这点很重要：导师建议构建图模型，不等于马上修改 benchmark gold 或把系统改成图数据库。

## 11. 论文贡献可以这样写

可以暂定三条贡献：

1. We formulate long-term agent memory QA as Latest Valid State Construction under Scope-Time-State Ambiguity.
   中文：我们将长期智能体记忆中的状态型问答建模为 Scope-Time-State 歧义下的当前有效状态构造问题。

2. We propose Scope-Time-State Graph, a graph formalism that represents scopes, events, claims, validity relations, time roles, and state facets for query-conditioned state construction.
   中文：我们提出 Scope-Time-State Graph，用于建模 scope、event、claim、validity relation、time role 和 state facet，并支持 query-conditioned 的状态解析。

3. We introduce STAMB-State, a benchmark and evaluation protocol that separately evaluates evidence support, state facet correctness, and final answer quality.
   中文：我们提出 STAMB-State benchmark，将证据支撑、状态字段正确性和最终答案质量分开评测，避免模型只靠流畅答案掩盖 stale 或 unsupported 状态。

## 12. 建议下一步

我建议按这个顺序推进：

1. 先把这份中文建模稿和导师对齐，确认顶层科学问题是否成立。
2. 再把 `Scope-Time-State_Graph_Formal_Definition.md` 改成论文英文版。
3. 把 graph trace case figure 做成论文图，至少展示：
   - latest event is stale mention；
   - plan-only does not imply completion；
   - correction / supersession chain。
4. 保持现有 benchmark contract 不变，新增的图逻辑只作为 runner branch、ablation 或 v1.1/v2 protocol 设计。
5. 如果后续要对标 Graphiti/Zep，先把它放在 related work；只有真实跑出数字时再放进 baseline table。

当前最应该避免的是两种偏差：

- 偏成工程系统：讲太多图数据库、存储和系统实现，反而削弱科学问题。
- 偏成 prompt pipeline：只讲每一步 prompt 怎么做，没有顶层模型支撑。

更合适的主线是：

```text
Scope-Time-State Ambiguity
  -> Scope-Time-State Graph
  -> Query-conditioned State Packet
  -> Evidence-backed State Answer
  -> STAMB-State Benchmark
```


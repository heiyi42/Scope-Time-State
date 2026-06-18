# Scope-Time-State Graph Formal Definition

This document defines the graph-level formalism behind STAMB-State. It is a paper-facing model, not a replacement for the frozen benchmark output contract in `STAMB-State_TASK_DEFINITION.md`.

## 1. Motivation

Long-term agent memory often stores many event records, but a state-oriented query asks for the current valid state of a scope. The central ambiguity is that the same query can fail along four axes:

- Scope: which project, task, entity, or conversation thread should be used.
- Time role: whether "recent", "current", "planned", or "before" should be interpreted by `occurred_at`, `mentioned_at`, `updated_at`, `planned_for`, or `deadline_at`.
- Validity: whether an event is still active, superseded, corrected, stale, or only a mention.
- State: which state facets should be returned, and which evidence supports each facet.

Scope-Time-State Graph models these axes explicitly so that latest valid state retrieval is not reduced to latest-event retrieval or generic temporal KG lookup.

## 2. Graph Definition

Let a Scope-Time-State Graph be:

```text
G = (V, A, phi, psi)
```

where `V` is a typed node set, `A` is a typed directed edge set, `phi` maps each node to attributes, and `psi` maps each edge to attributes such as confidence, timestamp, and provenance.

### 2.1 Node Types

```text
V = S union E union C union Z union U
```

| Symbol | Node type | Meaning |
| --- | --- | --- |
| `S` | Scope nodes | Projects, tasks, subtasks, topics, entities, or conversation threads. |
| `E` | Event nodes | Raw memory events from chats, logs, tools, or documents. |
| `C` | Claim nodes | Atomic state claims extracted from events. |
| `Z` | State facet nodes | Current or historical state facets derived from claims. |
| `U` | Source nodes | Users, tools, systems, documents, or logs that produced events. |

An event node is:

```text
e = (event_id, scope_id, content, event_type, tau, source_id, metadata)
```

where:

```text
tau(e) = {
  occurred_at,
  mentioned_at,
  updated_at,
  planned_for,
  deadline_at
}
```

A claim node is:

```text
c = (claim_id, facet_type, value, polarity, modality, source_event, source_id)
```

Examples of `facet_type` include `current_decision`, `current_issue`, `risk`, `next_step`, `completion_status`, `deadline`, and `invalidated_direction`.

A state facet node is:

```text
z = (scope_id, facet_type, value, status, valid_from, valid_until, support_events)
```

where `status` is one of:

```text
active | superseded | corrected | stale | unknown_current | insufficient_evidence | conflict_unresolved
```

### 2.2 Edge Types

The graph contains the following edge types:

| Edge | Meaning |
| --- | --- |
| `IN_SCOPE(e, s)` | Event `e` belongs to scope `s`. |
| `SUBSCOPE_OF(s_i, s_j)` | Scope `s_i` is a sub-scope or stage under `s_j`. |
| `OBSERVED_BY(e, u)` | Source `u` produced or observed event `e`. |
| `ASSERTS(e, c)` | Event `e` contains atomic claim `c`. |
| `SUPPORTS(c, z)` | Claim `c` supports state facet `z`. |
| `DERIVES_STATE(z, C_z)` | State facet `z` is derived from a set of claims `C_z`. |
| `CORRECTS(c_i, c_j)` | Claim `c_i` corrects claim `c_j`. |
| `SUPERSEDES(c_i, c_j)` | Claim `c_i` replaces claim `c_j`. |
| `CONFLICTS_WITH(c_i, c_j)` | Claims cannot both be active for the same scope and facet. |

`CORRECTS`, `SUPERSEDES`, and `CONFLICTS_WITH` are claim-level relations. Event-level relations in the benchmark can be lifted to claim-level relations by applying them to the claims extracted from the related events.

## 3. Query Interpretation

Given a query `q`, the system first interprets the query into a scope, time-role constraint, and target facets:

```text
s_q = ScopeAnchor(q, G)
r_q = TimeRoleResolver(q)
F_q = FacetPlanner(q, s_q, G)
```

where:

- `s_q in S` is the target scope.
- `r_q subseteq R` and `R = {occurred_at, mentioned_at, updated_at, planned_for, deadline_at}`.
- `F_q` is the set of state facets required by the query.

In the Oracle-Facet track, `s_q`, `r_q`, and `F_q` are supplied by the case to isolate state construction. In the Public End-to-End track, they must be inferred from raw input.

## 4. Candidate Evidence Selection

For a query `q`, target scope `s_q`, and time-role set `r_q`, candidate events are:

```text
Cand(q) = {
  e in E :
    ReachableScope(e, s_q)
    and TimeOK(e, q, r_q)
    and Relevant(e, q)
}
```

`ReachableScope(e, s_q)` is true when `e` is directly in `s_q` or belongs to an allowed sub-scope through `SUBSCOPE_OF`.

`TimeOK(e, q, r_q)` applies query-specific time constraints over the selected time roles. For example, a query asking "actually happened at 14:05 but was recorded at 14:10" constrains both `occurred_at` and `mentioned_at`.

`Relevant(e, q)` can be implemented by lexical, embedding, graph, or LLM scoring, but the score only selects candidates; it does not decide current validity.

## 5. Claim Extraction

Each candidate event is decomposed into atomic claims:

```text
Claims(q) = union_{e in Cand(q)} ClaimExtractor(e, q)
```

The extractor should preserve:

- the source event id;
- the source user, tool, log, or document;
- the facet type;
- the asserted value;
- the time role used by the assertion;
- whether the claim is a plan, completion, observation, correction, risk, decision, or mention.

Claim extraction is not the main contribution of STAMB-State. The benchmark can use raw events, generated claim candidates, or evaluator-only annotations, but state resolution must not consume gold labels at inference time.

## 6. Validity Resolution

For a claim `c`, define its invalidators:

```text
Inv(c) = {
  c' in Claims(q) :
    CORRECTS(c', c)
    or SUPERSEDES(c', c)
    or ConflictWinner(c', c) = c'
}
```

`ConflictWinner` resolves contradictions between active-looking claims:

```text
ConflictWinner(c_i, c_j) =
  argmax_c (RelationPriority(c),
            EvidenceClassPriority(c),
            TimeRank(c, r_q),
            confidence(c))
```

`RelationPriority(c)` prefers explicit correction and supersession evidence over unrelated mentions. `EvidenceClassPriority(c)` prefers direct observations, tool logs, and completed executions over plans, drafts, todos, and speculative notes. For example, a test log or execution record should outrank a planned action when resolving `completion_status`.

A claim is valid for `q` if:

```text
Valid(c, q, G) =
  c in Claims(q)
  and not MentionOnly(c)
  and not PlanOnlyAsCompletion(c, q)
  and no accepted c' in Inv(c)
```

`MentionOnly(c)` prevents a recent mention from becoming current state. `PlanOnlyAsCompletion(c, q)` prevents a planned or todo event from being treated as completion, submission, review completion, or rollout completion.

If two claims conflict and no winner can be chosen by relation priority, evidence class, time, or confidence, the corresponding facet is marked `conflict_unresolved` rather than silently selecting one side.

## 7. State Resolution Function

For each requested facet `f in F_q`, collect valid supporting claims:

```text
V_f(q) = { c in Claims(q) : facet(c) = f and Valid(c, q, G) }
```

Then derive the state facet:

```text
z_f = ResolveState(q, s_q, f, V_f(q), G)
```

The resolver returns one of four forms:

```text
active_state(value, support_events)
invalidated_state(old_value, current_value, support_events)
unknown_current(reason, support_events)
insufficient_evidence(reason, support_events)
```

The general state resolution rule is:

```text
ResolveState(q, s, f, V_f, G) =
  if V_f contains accepted current claim:
      active_state(ComposeValue(V_f), MinimalSupport(V_f))
  else if f asks whether an old state still holds and there is accepted invalidating evidence:
      invalidated_state(OldValue(f), NewValue(f), MinimalSupport(old_claims union invalidators))
  else if evidence only contains plan/draft/todo/unreviewed records:
      unknown_current(PlanOnlyReason(V_f), MinimalSupport(V_f))
  else:
      insufficient_evidence(NoCurrentEvidenceReason(q, f), MinimalSupport(V_f))
```

The support set must be minimal but sufficient:

```text
MinimalSupport(V_f) = smallest event set P
such that P entails the value of z_f under validity and evidence-priority rules.
```

Correction, supersession, invalidation, and old/new comparison facets usually require both the old event and the later correcting or superseding event.

## 8. Answer Function

The final answer is composed only from locked state facets:

```text
Z_q = { z_f : f in F_q }
A_q = AnswerComposer(q, Z_q)
```

The answer composer must not add new evidence, change support events, or revise slot values. This preserves the benchmark distinction between:

- evidence support quality;
- state facet correctness;
- final answer completeness.

This maps directly to the STAMB-State output contract:

```json
{
  "evidence_events": ["event_id"],
  "state_slots": {
    "facet_type": {
      "value": "state value",
      "support_event": "main_event_id",
      "support_events": ["event_id"]
    }
  },
  "answer": "user-facing answer"
}
```

## 9. Explainability and Traceability

Scope-Time-State Graph is not only a retrieval structure. Its second role is to make every state answer explainable and traceable.

### 9.1 Explainability

For each state facet `z_f`, the system should be able to explain:

- which query facet `f` triggered this state;
- which candidate events were considered;
- which claims were extracted from those events;
- which claims were accepted as current valid claims;
- which claims were rejected as stale, corrected, superseded, mention-only, plan-only, or conflicting;
- which support events minimally entail the final state value.

The explanation path is:

```text
q -> s_q, r_q, F_q
  -> Cand(q)
  -> Claims(q)
  -> Valid claims and rejected claims
  -> StateFacet z_f
  -> Answer sentence
```

For an invalidated state, the explanation must include both the old claim and the correcting or superseding claim:

```text
old event -> old claim
new event -> new claim
new claim SUPERSEDES/CORRECTS old claim
state facet = old state no longer holds; current state is new value
```

This lets the system answer not only "what is the current state?" but also "why is this the current state instead of the latest mention or the old plan?"

### 9.2 Traceability

Traceability requires every generated state value and every final answer sentence to be backed by event-level provenance.

For each state facet `z_f`, the graph must preserve:

```text
Trace(z_f) = {
  scope_id,
  facet_type,
  value,
  status,
  support_events,
  support_claims,
  rejected_claims,
  relation_path,
  time_roles_used,
  source_ids
}
```

The required invariant is:

```text
For every output state facet z_f,
support_events(z_f) is not empty unless status is insufficient_evidence,
and every support event is reachable through:
Event -> ASSERTS -> Claim -> SUPPORTS/DERIVES_STATE -> StateFacet.
```

The answer composer must preserve this trace:

```text
For every answer sentence a_i,
there exists at least one state facet z_f
such that a_i is entailed by z_f.value and z_f.support_events.
```

This prevents unsupported final-answer additions and makes hallucinated state claims auditable.

### 9.3 Runtime Trace Schema

A lightweight implementation can store the graph trace as JSON without using a graph database:

```json
{
  "scope": "scope_id",
  "time_roles": ["updated_at"],
  "candidate_events": ["event_id"],
  "claims": [
    {
      "claim_id": "c1",
      "event_id": "event_id",
      "facet_type": "current_decision",
      "value": "claim text",
      "claim_type": "decision"
    }
  ],
  "relations": [
    {
      "type": "SUPERSEDES",
      "from": "new_claim_id",
      "to": "old_claim_id",
      "reason": "later decision replaces earlier direction"
    }
  ],
  "rejected_claims": [
    {
      "claim_id": "c_old",
      "reason": "superseded"
    }
  ],
  "state_facets": {
    "current_decision": {
      "value": "current state value",
      "status": "active",
      "support_claims": ["claim_id"],
      "support_events": ["event_id"]
    }
  },
  "answer_trace": [
    {
      "sentence": "answer sentence",
      "state_facets": ["current_decision"],
      "support_events": ["event_id"]
    }
  ]
}
```

This trace can be used for case studies, error analysis, and paper figures. It also supports debugging without changing the benchmark scoring contract.

### 9.4 Runtime Graph-Guided Pipeline

The implemented graph-guided readout treats `graph_trace` as a runtime intermediate, not only as a post-hoc visualization. The execution order is:

```text
candidate events
  -> retriever locked evidence
  -> graph_trace: claims, relations, rejected_claims, state_facets
  -> state_slots derived from graph_trace.state_facets
  -> answer composer
  -> answer_trace attached to the same graph_trace
```

This means the composer consumes state slots that are materialized from `state_facets`. The final answer trace is attached after composition, but the claims, relations, rejected claims, and state facets are created before answer generation.

## 10. Scientific Problem Statement

Scope-Time-State Ambiguity can be stated as:

```text
Given a long-term memory graph G and a state-oriented query q,
determine the target scope, relevant time role, valid evidence claims,
and current state facets such that the answer is both current and evidence-backed.
```

This differs from prior retrieval and temporal-memory settings:

- Latest-event retrieval returns the most recent event, but that event may be a stale mention or non-update.
- Temporal retrieval selects time-appropriate evidence, but selected evidence may still need validity adjudication and state aggregation.
- Temporal KG systems store facts and validity intervals, but a user query often requires facet-level state construction, not a fact list.
- State consolidation systems address stale memories, but Scope-Time-State Graph also models scope anchoring, time-role ambiguity, support minimality, explainable state derivation, and traceable state-facet answers.

## 11. Benchmark Mapping

The current STAMB-State benchmark evaluates this graph formalism through observable outputs:

| Graph concept | Benchmark field or metric |
| --- | --- |
| `ScopeAnchor(q, G)` | `scope_id` in Oracle-Facet; hidden in Public End-to-End. |
| `TimeRoleResolver(q)` | `time_roles` in cases; hidden or inferred in public track. |
| `F_q` target facets | `output_slots` and `gold_state_slots`. |
| `MinimalSupport(V_f)` | `gold_slot_support`, evaluated by `sup_f1`. |
| State facet value | `state_slots[*].value`, evaluated by `slot_j`. |
| Locked final answer | `answer`, evaluated by `ans_j`. |
| Invalid or stale evidence | `hard_negative_events`, `hard_neg`, and `over_ev`. |
| Plan-only current uncertainty | `answerability`, `unknown_current`, and `unk_cur`. |

Therefore, the graph is the scientific model, and the benchmark output schema is the operational interface used to evaluate it.

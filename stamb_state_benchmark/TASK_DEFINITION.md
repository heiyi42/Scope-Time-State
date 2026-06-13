# STAMB-State Task Definition

This document fixes the task and metric definition for the current benchmark. Do not change prompts or pipelines to chase a single metric before updating this document.

## 1. Task

STAMB-State evaluates latest valid state retrieval for long-term agent memory.

Given an event stream under multiple scopes, the system must answer state-oriented queries such as:

- "这个项目最近怎么样？"
- "现在还卡在哪里？"
- "旧方案还有效吗？"
- "下一步要做什么？"

The target is not the latest mentioned event. The target is the current valid state under the query scope, backed by explicit evidence.

## 2. Input

Each memory event may contain:

- `event_id`: unique event identifier.
- `scope_id`: project/task/topic scope.
- `content`: event text.
- `event_type`: progress, issue, correction, decision, plan, execution log, mention, etc.
- `occurred_at`: when the event happened.
- `mentioned_at`: when it was mentioned to the agent.
- `updated_at`: when memory was updated.
- `planned_for`: future planned time, if any.
- `status`: active or superseded.
- `corrects`: old events corrected by this event.
- `supersedes`: old events replaced by this event.
- `state_relevant`: whether the event should update state.

The query case provides:

- `query`: user question.
- `scope_id`: target scope.
- `operation`: query type, such as `state_summary`, `state_lookup`, or `next_action`.
- `time_role`: time field used for retrieval/order decisions.
- `output_slots`: required state fields.
- `gold_state_slots`: gold state value for each slot.
- `gold_slot_support`: gold support events for each slot.
- `gold_events`: related gold evidence set used for diagnostic event scoring.

## 3. Output

The system output must include:

```json
{
  "evidence_events": ["event_id"],
  "state_slots": {
    "slot_name": {
      "value": "current valid state text",
      "support_event": "main event_id or null",
      "support_events": ["event_id"]
    }
  },
  "coverage_check": {
    "slot_name": true
  },
  "answer": "final answer to user"
}
```

Field meanings:

- `evidence_events`: all events the system uses as state evidence.
- `state_slots[*].value`: current valid state for that slot.
- `support_event`: the single most direct support event for the slot.
- `support_events`: complete support set for the slot. This should include multiple events when the state depends on a correction chain, supersession, old/new comparison, or multiple parallel next steps.
- `answer`: user-facing answer, written only from `state_slots`.

## 4. Main Metrics

Use these metrics for primary ranking:

- `sup_f1`: average slot-level F1 between predicted `support_events` and gold slot support events. This measures complete evidence support.
- `slot_j`: LLM-as-a-judge semantic correctness of each predicted state slot value.
- `ans_j`: LLM-as-a-judge correctness of the final answer as a complete response.

Primary conclusion order:

1. `sup_f1`
2. `slot_j`
3. `ans_j`

A method should not be considered better if it only improves event recall while hurting `slot_j` and `ans_j`.

## 5. Diagnostic Metrics

Use these metrics for error analysis, not as primary ranking:

- `support`: single-main-evidence accuracy. It checks whether `support_event` is acceptable for each slot. This is useful but too lenient for multi-event support.
- `ev_f1`: F1 between predicted `evidence_events` and `gold_events`.
- `req_f1`: F1 between predicted `evidence_events` and the union of gold slot support events.
- `ev_p`: precision of predicted `evidence_events` against `gold_events`.
- `ev_r`: recall of `gold_events`.
- `ctx_r`: recall of optional context events when explicitly annotated. In the current data this is usually not available.

Diagnostic metrics explain why a method fails. They should not override `sup_f1 / slot_j / ans_j`.

## 6. Current Method To Keep

The default `scope_time_state_pipeline` should use the two-stage support-events form:

1. Scope-Time-State Retriever:
   - route to target scope;
   - apply time role, validity, supersession/correction, and state relevance;
   - output `evidence_events`, `state_slots`, `support_event`, and `support_events`;
   - do not write the final answer.
2. Answer Composer and Coverage Verifier:
   - write and verify `answer` from locked `state_slots`;
   - do not change evidence or slots.

The three-stage decoupled version is not the default method because it improved evidence recall but reduced support accuracy and answer quality in the current experiment.

## 7. Current Evidence From The Demo

Saved result files show:

```text
two-stage:
ev_f1  0.885
req_f1 0.885
support 0.972
sup_f1 0.880
slot_j 0.936
ans_j  0.833

support_events:
ev_f1  0.949
req_f1 0.949
support 0.972
sup_f1 0.941
slot_j 0.892
ans_j  0.733

decoupled_pipeline:
ev_f1  0.954
req_f1 0.954
support 0.900
sup_f1 0.919
slot_j 0.875
ans_j  0.700
```

Interpretation:

- `support_events` improves complete evidence coverage.
- `two-stage` has better semantic state and answer quality.
- Over-decoupling retrieval and aggregation is not currently justified.

## 8. What This Demo Can And Cannot Claim

This demo can support:

- latest event retrieval is insufficient;
- evidence support, state slot quality, and final answer quality should be evaluated separately;
- multi-event support is needed for correction, supersession, invalidation, and parallel next-step cases.

This demo cannot yet claim:

- paper-faithful superiority over ARTEM, TReMu, TSM, Zep, Graphiti, or other systems;
- AAAI-level empirical strength;
- that the pipeline design is final.

Before making paper claims, replace prompt-level baseline approximations with paper/code-faithful baselines and expand the benchmark beyond hand-crafted examples.

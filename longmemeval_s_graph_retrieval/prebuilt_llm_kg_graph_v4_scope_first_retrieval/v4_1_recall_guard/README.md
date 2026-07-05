# V4.1: Scope-First Retrieval With Recall Guard

## Purpose

V4 changed retrieval from state-first to scope-first:

```text
Question -> Scope / Entity -> Event / Claim -> State Facet -> Evidence
```

This made retrieval more focused, but in some cases it removed too much
evidence. V4.1 keeps scope-first as the main retrieval method, then uses the v2
state-first result only as a recall guard.

## Core Idea

```text
v4 scope-first = primary result
v2 state-first = backup evidence source
```

If v4 finds enough evidence, use v4 directly.

If v4 is structurally much smaller than v2, merge in non-duplicate parts from
v2.

This is not a per-question-type rule. It applies to any question where v4 looks
under-recalled.

## Under-Recall Signals

V4.1 can trigger recall guard when:

```text
len(v4.evidence_snippets) is much smaller than len(v2.evidence_snippets)
len(v4.state_facets) is much smaller than len(v2.state_facets)
len(v4.relevant_session_ids) is much smaller than len(v2.relevant_session_ids)
v4 already fell back to state-first
```

The first implementation should use conservative thresholds, for example:

```text
v4 evidence < 60% of v2 evidence
or v4 facets < 60% of v2 facets
or v4 relevant sessions < 60% of v2 relevant sessions
```

## Merge Rule

The final packet should prefer v4 content:

```text
final = v4
```

Then add only non-duplicate v2 content:

```text
final.evidence_snippets += v2 evidence not already present
final.state_facets += v2 facets not already present
final.rejected_claims += v2 rejected_claims not already present
final.relevant_session_ids = union(v4, v2)
```

Deduplication should be based on stable keys:

```text
evidence: session_id + date + role + content
state_facet: name + value
rejected_claim: claim + reason
```

## Expected Behavior

V4.1 should preserve the scope-first advantage when it works:

```text
focused evidence
higher precision
pipeline-aligned traversal
```

But it should reduce cases where scope-first drops necessary evidence:

```text
better recall
fewer overly small state_packets
less risk for aggregation / counting / list questions
```

## Not The Goal

V4.1 should not:

```text
change graph construction
change graph schema
change answer / judge prompts
special-case one question type
use gold answer sessions
use judge feedback
```

## Files

This folder contains the v4.1 implementation:

```text
recall_guard_retriever.py
run_longmemeval.py
README.md
outputs/
```

`recall_guard_retriever.py` should wrap:

```text
ScopeFirstGraphRetriever
StatePacketGraphRetriever
```

`run_longmemeval.py` should be the same as v4's runner except it uses the
recall-guard retriever.

## Run

Dry-run:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.v4_1_recall_guard.run_longmemeval \
  --limit-per-type 10 \
  --dry-run
```

Run answer generation:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.v4_1_recall_guard.run_longmemeval \
  --limit-per-type 10 \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v4_scope_first_retrieval/v4_1_recall_guard/outputs/results_60_v4_1.json
```

Run with judge:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v4_scope_first_retrieval.v4_1_recall_guard.run_longmemeval \
  --limit-per-type 10 \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --judge \
  --judge-provider openai \
  --judge-model gpt-4o-2024-08-06 \
  --output longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v4_scope_first_retrieval/v4_1_recall_guard/outputs/results_60_v4_1_judged.json
```

Optional thresholds:

```bash
--evidence-ratio-threshold 0.60
--facet-ratio-threshold 0.60
--session-ratio-threshold 0.60
```

The default graph directory is the parent v4 graph artifact directory:

```text
prebuilt_llm_kg_graph_v4_scope_first_retrieval/artifacts/graphs/
```

# V7 Scope-First Retrieval

V7 is a retrieval-only iteration for question-independent graphs produced by V6. It does not build or modify graphs. Its purpose is to test whether a question can first match the graph's `scope` nodes, then expand from those scopes to the relevant events, claims, and sessions.

## Core Idea

The graph schema stores both entities and scopes as:

```text
node_type = "Entity/Scope"
subtype = "scope" or "entity"
```

V7 ranks only `subtype == "scope"` nodes as the first retrieval step. It then expands:

```text
Scope node <- event_in_scope - Event <- claim_supported_by_event - Claim
```

The expanded claims and events are ranked and converted into a reader-compatible state packet.

## Files

- `scope_retriever.py`: scope matching, graph expansion, session/evidence ranking.
- `run_scope_eval.py`: evaluates retrieval only, with no answer-generation LLM calls.
- `run_longmemeval.py`: runs the existing LongMemEval-S reader on V7 retrieved evidence.

## Retrieval Pipeline

1. Parse question terms and map them to scope hints.
2. Rank graph scope nodes using scope label match, question-type prior, query hints, and graph degree.
3. Expand from matched scopes to events and claims.
4. Optionally add matched entity nodes and lexical event fallback.
5. Expand correction/supersession/conflict claim relations.
6. Add nearby turns in the same session.
7. Rank sessions and evidence snippets.

## Retrieval-Only Evaluation

Use this first. It checks whether V7 scopes into the answer sessions:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval --question-types knowledge-update --limit-per-type 5
```

Dry-run:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval --question-types knowledge-update --limit-per-type 5 --dry-run
```

The default graph directory is V6's `artifacts/graphs`.

## Full Answer Evaluation

After scope recall looks acceptable:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_longmemeval --question-types knowledge-update --limit-per-type 5
```

## V7.2 Scope-Time-State Retrieval

V7.2 keeps the V7.0 scope ranking unchanged, then replaces the downstream expansion with a Scope-Time-State traversal inspired by V2:

```text
Question -> V7.0 Scope -> candidate Events/Claims -> latest Time -> State Facets -> Claims -> Evidence
```

The scope step is still query-based retrieval over question-independent V6 graphs. Graph construction is unchanged and remains question-independent.

Retrieval-only evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval_v7_2 --question-types multi-session temporal-reasoning --limit-per-type 10
```

Full answer evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_longmemeval_v7_2 --question-types multi-session temporal-reasoning --limit-per-type 10
```

Compared with V7.0, V7.2 uses selected `State Facet` nodes and their supporting claims to reduce noisy evidence. It keeps fallback claims for multi-session and temporal questions so the Time/State layer does not collapse multi-evidence answers into a single current state.

## V7.3 Hybrid Scope-Time-State Retrieval

V7.3 keeps V7.2's Scope-Time-State route for current-state style questions, but uses a hybrid claim pool for `multi-session` and `temporal-reasoning` so aggregation and date-difference questions are not over-filtered by current-state facets.

Key changes:

- temporal questions keep `question_date` as the time anchor in the state packet;
- current-state facet gating is only strict for knowledge/update and single-session current-state style tasks;
- multi-session and temporal tasks start from the V7-style candidate claim pool, then use state facets only as a soft bonus;
- evidence snippets are reranked with light session diversity.

Retrieval-only evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval_v7_3 --question-types multi-session temporal-reasoning --limit-per-type 10
```

Full answer evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_longmemeval_v7_3 --question-types multi-session temporal-reasoning --limit-per-type 10
```

## V7.4 BM25 Scope-First Retrieval

V7.4 is a narrow ablation over V7.0. It keeps the V7.0 downstream traversal unchanged and replaces only the first step, `Question -> Scope`, with BM25 retrieval over graph-derived scope profiles.

Each scope profile is built from graph-local content:

- scope label;
- connected event text;
- claims supported by connected events;
- entity labels mentioned by connected events.

The profile builder uses generic field weighting and size caps only. It does not use question-type priors, query hint maps, benchmark-specific keywords, answer sessions, or gold answers.

Retrieval-only evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval_v7_4 --data _v7_21_data.json --limit-cases 21
```

Full answer evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_longmemeval_v7_4 --data _v7_21_data.json --limit-cases 21
```

## V7.5 LLM Scope-First Retrieval

V7.5 is the LLM semantic counterpart to V7.4. It keeps the V7.0 downstream traversal unchanged and replaces only the first step, `Question -> Scope`, with an LLM selector over graph-neighborhood scope profiles.

The LLM sees only graph-derived scope candidates:

- scope node id, label, and degree;
- nearby event text from `Event -> Scope`;
- nearby claim text from `Claim -> Event`;
- nearby state facets from `StateFacet -> Claim`;
- nearby entity labels from `Event -> Entity`.

The selector must return candidate scope node ids only. It does not receive gold answers, answer sessions, benchmark-specific keyword lists, question-type priors, or BM25 scores. Reasons returned by the LLM are recorded for audit only and are not passed to the downstream reader.

Retrieval-only dry-run:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval_v7_5 --data _v7_21_data.json --limit-cases 21 --dry-run
```

Retrieval-only evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval_v7_5 --data _v7_21_data.json --limit-cases 21
```

Full answer evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_longmemeval_v7_5 --data _v7_21_data.json --limit-cases 21
```

## Main Metrics

V7 should be judged first by retrieval quality:

- `evidence_session_recall`
- `evidence_session_precision`
- matched scope labels
- scoped event/claim/session counts

Final answer accuracy is secondary until scope recall is strong.

## Deprecated V7.1 Scope Profile / IDF

V7.1 is kept only as an ablation record. It performed worse than the V7.0 scope-first ranking and should not be used as the default method.

Use V7.0 commands above for the current retrieval route.

V7.1 only changes the scope ranking step. The downstream expansion, claim ranking, session ranking, and reader packet format remain the same as V7.

V7.1 does not use benchmark-specific domain hints, error-case word lists, or hand-written mappings from topic words to scope labels. It ranks scope nodes with graph-derived statistics:

- scope IDF from `total_events / events_in_scope`;
- a scope profile built from connected event text, connected entity labels, and connected claim text;
- question terms matched against that scope profile with cross-scope term IDF;
- a reduced question-type prior, applied only when the scope already has lexical support from the question.

This was intended to test whether scope nodes become more precise before changing later retrieval stages.

Retrieval-only evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_scope_eval_v7_1 --question-types multi-session temporal-reasoning --limit-per-type 10
```

Full answer evaluation:

```powershell
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v7_scope_first_retrieval.run_longmemeval_v7_1 --question-types multi-session temporal-reasoning --limit-per-type 10
```

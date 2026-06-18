# TSM

This baseline implements the paper-structured Temporal Semantic Memory pipeline from
`Relatedwork/TSM.pdf` for STAMB-State.

By default, `Experiment/run/run_llm_benchmark.py` injects the target LLM into the TSM construction
stage. The adapter uses that model for:

- per-turn entity and temporal fact extraction with a preceding-turn context window;
- TKG update operation selection over candidate existing edges (`DUPLICATE`, `ADD`,
  `INVALIDATE`, `UPDATE`);
- sleep-time `topic` and `persona` summary consolidation.

The implementation then builds:

- Temporal Knowledge Graph episodic memory with `valid_time`, `invalid_time`, and
  `DUPLICATE` / `ADD` / `INVALIDATE` / `UPDATE` operations.
- Monthly durative `topic` and `persona` memories using GMM-style clustering over entity summaries.
- Semantic-time guided utilization: query time parsing, Top-K dense retrieval over raw/topic/persona
  memory, temporal filtering for durative memory, TKG temporal retrieval, and lexicographic reranking
  by temporal alignment before semantic similarity.

`--tsm-construction-mode heuristic` is available only as an explicit offline/debug fallback. It uses
event fields, marker rules, and lexical similarity to construct the TKG, so it should not be reported
as the main paper-faithful TSM result.

The runner exposes only raw STAMB event IDs as valid support IDs. Synthetic TSM memory IDs are
included as retrieval context but must not be returned as `support_event`.

In the Oracle-Facet track, the benchmark case supplies `scope_id` and `output_slots`, so TSM runs on
that scoped history and answers the requested slots.

The public End-to-End runner exposes two TSM variants:

- `tsm_global_public`: passes only `query` and `operation`; TSM constructs and retrieves over all
  public events. This is closest to the paper algorithm because TSM itself has no explicit Scope
  Anchor.
- `tsm_scope_routed_public`: first routes scope from `public/scope_profiles.json`, then passes
  `query`, `operation`, and the routed `scope_id` into TSM. This is the stronger adapted baseline
  for the multi-scope STAMB-State setting.

Hidden `output_slots`, gold states, and gold support are not passed in either public variant; TSM
must free-generate facets from its retrieved temporal context.

For efficiency, the public runner caches TSM construction indexes within a run. The global variant
builds one all-event index, while the scope-routed variant builds at most one TSM index per routed
scope. Each query then only runs TSM utilization plus answer generation over the retrieved visible
events.

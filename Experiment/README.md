# Experiment

Experiment code lives here. `stamb_state_benchmark/` is reserved for generated data and output artifacts.

## Code Layout

- `run/run_llm_benchmark.py` and `run/run_public_benchmark.py` are the only prompt-runner
  experiment entry scripts.
- `run/common/` holds shared benchmark primitives: models, IO, metrics, utilities, paths, and
  the LLM client.
- Project-root `pipeline/oracle/` and `pipeline/public/` hold the current Oracle-Facet and public
  End-to-End pipeline implementations.
- `run/run_oracle_benchmark/` holds Oracle-Facet CLI glue, prompts, judging, and graph-trace helpers.
- `run/run_public_benchmark/` holds public End-to-End CLI glue, prompts, routing, types, and utilities.

## Main Baseline

- `full_context_llm`: full-context LLM control.
- `hybrid_rag`: lightweight generic RAG-style prompt baseline migrated from the previous recent top-k adapter.
- `tsm`: paper-structured Temporal Semantic Memory reproduction: LLM construction for entity/fact
  extraction, TKG update operations, and topic/persona summary consolidation, plus semantic-time
  filtering and temporal reranking.
- `graphiti_zep`: fair real-system Graphiti/Zep adapter runner.
- `graphiti_paper_reproduction`: separate paper-structured Graphiti/Zep reproduction and audit runner.
- `validity_aware_consolidation`: paper-structured STALE/CUPMem reproduction with typed state
  schema, write-side adjudication, propagation-aware stale-state search, and constrained readout.
- `ours_scope_time_state`: proposed Scope-Time-State pipeline.

`Memory-T1` is intentionally deferred for now. `graphiti_zep` and `graphiti_paper_reproduction`
remain external-system runners rather than `run/run_llm_benchmark.py` prompt adapters because they
require Graphiti, Neo4j, and graph construction/search audit state.

## Appendix Baseline

- `latest_event_only`: latest-event diagnostic.
- `temporal_fact_graph`: temporal fact graph prompt diagnostic.
- `temporal_kg_oracle_schema`: oracle-schema diagnostic; exposes validity metadata and should not be used as a fair main baseline.
- `tremu_style`: TReMu-inspired prompt adapter, not an official TReMu reproduction.

## External Benchmarks

These adapters are external validation targets, not replacements for the STAMB-State main benchmark.
Keep them outside `pipeline.public` because STAMB public runners depend on `PublicCase`,
`scope_profiles`, hidden `output_slots`, and `gold_state_slots`.

- `Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py` is a thin wrapper over
  `pipeline/external/longmemeval_s/`. Current diagnostic evidence includes a 60-case judged
  `scope_time_state_task_adapter` run.
- `Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py` builds one persistent
  sample-level graph with implementations under `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/`.
  The old text-only task-adapter
  runner is no longer the active LoCoMo path.
- `Experiment/Other_BenchMark/STALE/run_stale.py` is a thin wrapper over
  `pipeline/external/stale/`. Current diagnostic evidence includes 10-scenario judged runs;
  T2 propagation and false-premise resistance remain weak.
- `MemConflict` is not adapted yet. Add it as a small-sample diagnostic first, then optimize before
  considering a full run.

## Validation

Use the project validation environment:

```bash
conda run -n py311 python Experiment/run/run_llm_benchmark.py --dry-run
conda run -n py311 python Experiment/run/run_public_benchmark.py --dry-run
conda run -n py311 python scripts/validate_v1.py
conda run -n py311 python scripts/validate_v1.py --v1-dir stamb_state_benchmark/data/v1_1 --out stamb_state_benchmark/output/validation_report_v1_1.json
conda run -n py311 python scripts/validate_v1.py --v1-dir stamb_state_benchmark/data/v1_2 --out stamb_state_benchmark/output/validation_report_v1_2.json
conda run -n py311 python scripts/validate_v1.py --v1-dir stamb_state_benchmark/data/v1_3 --out stamb_state_benchmark/output/validation_report_v1_3.json
conda run -n py311 python scripts/audit_benchmark_quality.py --v1-dir stamb_state_benchmark/data/v1_3 --out stamb_state_benchmark/output/quality_report_v1_3.json --semantic-out stamb_state_benchmark/output/semantic_duplicate_report_v1_3.json --openai-embedding-model text-embedding-3-large --openai-embedding-out stamb_state_benchmark/output/openai_embedding_duplicate_report_v1_3.json --fail-on-warnings
conda run -n py311 python scripts/export_annotation_packet.py --v1-dir stamb_state_benchmark/data/v1_3 --out-dir stamb_state_benchmark/annotation/v1_3_sample --sample-size 60 --seed 13
```

The TSM reproduction uses the target LLM for construction by default. It also uses `numpy`,
`scikit-learn`, `spacy`, and `dateparser` in the `py311` environment for GMM-style clustering
and query-time parsing. `--tsm-construction-mode heuristic` is an explicit offline/debug fallback
and should not be reported as the main paper-faithful TSM score.

The Graphiti paper reproduction uses `graphiti-core`, Neo4j, and `sentence-transformers` when
running the default BGE embedding/reranking path. Its entrypoint is
`Experiment/Main_Baseline/graphiti_paper_reproduction/run_graphiti_paper_audit.py`.

By default, `Experiment/run/run_llm_benchmark.py` runs v1 `oracle_facet` diagnostics with the runnable
`Main_Baseline` variants: `full_context_llm`, `hybrid_rag`, `tsm`,
`validity_aware_consolidation`, and `ours_scope_time_state`. Appendix baselines must be requested
explicitly with `--variants`.

Use `--data-version v1_1` to run the expanded 72-case benchmark generated by
`scripts/build_v1_1_from_v1.py`.

Use `--data-version v1_2` to run the upgraded 124-case benchmark generated by
`scripts/build_v1_2_from_v1_1.py`. v1.2 keeps the same task contract but expands the
visible public event stream to 288 events, adds evaluator-only `difficulty_level`, and
ships `subsets.json` plus public-safe `scope_taxonomy.json`. Scope profiles include
`scope_type`, `task_family`, and `domain` so routing and result breakdowns can distinguish
research, ML/product, infrastructure, incident, UI, security, robotics, and admin scopes.
For partial public runs, prefer `--case-subset balanced_half` over `--limit-cases`; the
balanced subset has 63 cases with 21 easy, 21 medium, and 21 hard cases plus explicit
unknown-current and insufficient-evidence coverage. The full v1.2 operation mix is
`state_lookup=73`, `state_summary=27`, and `next_action=24`; balanced half keeps the
same intent with `state_lookup=38`, `state_summary=14`, and `next_action=11`.

Use `--data-version v1_3` to run the final-size 240-case benchmark generated by
`scripts/build_v1_3_from_v1_2.py`. v1.3 has 24 scopes, 480 public events, and
240 evaluator cases. The full operation mix is `state_lookup=145`, `state_summary=47`,
and `next_action=48`; full answerability is `answerable=180`, `unknown_current=30`,
and `insufficient_evidence=30`. `balanced_half` has 120 cases with
`easy/medium/hard=40/40/40`. v1.3 is built from the original curated rows plus
scope-specific expansion; evaluator-only `operation_subtype` and `hard_negative_types`
support paper breakdowns. `scripts/audit_benchmark_quality.py` checks exact normalized
event/query/slot repetition, stale generic marker leakage, char n-gram cosine
near-duplicates, and optional OpenAI embedding near-duplicates. The n-gram pass is a
deterministic lexical proxy for template-like wording; the `text-embedding-3-large` report
is the stronger semantic screen for manual review, not an automatic deletion rule. Use
`scripts/export_annotation_packet.py` to prepare a double-annotation sample and
`scripts/score_annotation_agreement.py` to score annotator output against
`gold_reference.jsonl` or against another annotator.

The v1/v1.1/v1.2/v1.3 public End-to-End prompt track lives in `Experiment/run/run_public_benchmark.py`. Public cases hide `scope_id`, `output_slots`, gold states, gold support, hard-negative labels, and operation subtypes; public scope routing uses `public/scope_profiles.json`, which is derived only from raw public events. Current public prompt variants are `full_context_llm`, `hybrid_rag`, `tsm_global_public`, `tsm_scope_routed_public`, `validity_global_public`, `validity_scope_routed_public`, and `ours_scope_time_state`. `tsm_global_public` runs paper-structured TSM over all public events. `tsm_scope_routed_public` first routes scope from public profiles, then runs TSM construction/utilization inside the routed scoped history and free-generates facets. Public TSM construction indexes are cached within a run: one global index for `tsm_global_public` and one index per routed scope for `tsm_scope_routed_public`. `validity_global_public` runs the STALE/CUPMem-style typed state candidate stream over all public events. `validity_scope_routed_public` first routes scope from public profiles, then applies CUPMem-style active/stale/unknown-current adjudication and free-facet readout inside that scoped history. `ours_scope_time_state` first routes scope and time role, then constructs a public Scope-Time-State `state_packet` with candidate events, claims, validity relations, rejected claims, and state facets; the runner derives public `facets` from `state_packet.state_facets` before answer composition so the evaluator interface stays unchanged. The legacy public variant names `tsm`, `validity_aware_consolidation`, `validity_aware`, `stale_cupmem`, and `cupmem_style` are accepted as aliases for their scope-routed public variants. The runner uses a free-facet alignment judge for evaluation.

Graphiti/Zep public End-to-End is implemented in its real-system runner, not the prompt-only public runner, because it requires Graphiti graph ingestion/search state. Use `Experiment/Main_Baseline/graphiti_zep/run_graphiti_baseline.py --variant graphiti_global_public` for all-run Graphiti search and `--variant graphiti_scope_routed_public` for public scope routing followed by scoped Graphiti search. Both hide hidden `scope_id`, `time_role`, `output_slots`, gold states, and gold support from readout. The Graphiti runner also accepts `--case-subset balanced_half` for v1.2/v1.3 partial runs.

## Diagnostics

Main ranking should still use `sup_f1`, `slot_j`, and `ans_j`. The runners also report
diagnostics that should be read as failure modes rather than ranking replacements:

- `hard_neg`: fraction of declared evidence that hits evaluator-only hard-negative events.
- `over_ev`: fraction of declared evidence/support events that are not required gold support,
  including optional context events. Lower is better; this catches over-stuffing support.
- `unk_cur`: accuracy on `unknown_current` cases, where the model must preserve that only a
  plan/draft/todo/no-review record exists and must not claim completion/submission/review happened.

## Results

The current v1 Oracle-Facet and public End-to-End results are documented in `Experiment/RESULTS.md`.
The canonical machine-readable snapshots are:

- `stamb_state_benchmark/output/results_v1_oracle_facet.json`
- `stamb_state_benchmark/output/results_v1_end_to_end.json`
- `stamb_state_benchmark/output/results_v1_1_public_e2e_staged_full_20260617.json`

Generated output files are ignored by default. Add a new output snapshot to `.gitignore` only after
it becomes a documented canonical result in `Experiment/RESULTS.md`.

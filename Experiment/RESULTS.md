# STAMB-State Results

This file records the current result status. It separates dated checkpoints, current diagnostic results, and unfinished paper-facing result work.

## Current Status

- Main data/protocol version: STAMB-State v1.3, with 24 scopes, 480 public events, and 240 evaluator cases.
- Human annotation is not complete. The current annotation packet and gold reference are not a completed annotator agreement/adjudication artifact.
- Public End-to-End is the paper-facing setting because it hides `scope_id`, `time_role`, `output_slots`, gold states, gold support, hard negatives, and answerability.
- Oracle-Facet is a diagnostic track. It gives `scope_id`, `time_role`, and `output_slots` to isolate latest-valid-state construction; it must not be used as the final public main table.
- Canonical v1.3 scored tables are still missing. Current v1/v1.1 results are useful checkpoints, not final paper claims.

## Current STAMB Checkpoint

The most complete current baseline suite is the v1.1 Public End-to-End half checkpoint from 2026-06-18. It is not a v1.3 canonical table, but it reflects the newer baseline set better than the older v1/v1.1 three-method tables.

Settings:

- data version: `v1_1`
- track: public End-to-End
- cases: 36
- target model: `deepseek-v4-flash`
- judge: `deepseek-v4-flash`
- files: `stamb_state_benchmark/output/results_v1_1_public_half_*.json`

| Method | n | ev_sup | facet_r | facet_p | ans_j | ans_10 | hard_neg | over_ev | unk_cur |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_context_llm` | 36 | 0.789 | 0.833 | 0.851 | 0.722 | 8.833 | 0.131 | 0.225 | 0.000 |
| `hybrid_rag` | 36 | 0.545 | 0.509 | 0.667 | 0.306 | 5.361 | 0.225 | 0.331 | 0.500 |
| `tsm_global_public` | 36 | 0.691 | 0.778 | 0.739 | 0.528 | 7.400 | 0.171 | 0.253 | 0.000 |
| `tsm_scope_routed_public` | 36 | 0.764 | 0.810 | 0.765 | 0.556 | 7.583 | 0.161 | 0.256 | 0.000 |
| `validity_global_public` | 36 | 0.581 | 0.618 | 0.803 | 0.389 | 6.472 | 0.167 | 0.214 | 1.000 |
| `validity_scope_routed_public` | 36 | 0.768 | 0.815 | 0.722 | 0.528 | 7.818 | 0.118 | 0.188 | 0.500 |
| `graphiti_global_public` | 36 | 0.545 | 0.491 | 0.600 | 0.306 | 5.306 | 0.165 | 0.306 | 1.000 |
| `graphiti_scope_routed_public` | 36 | 0.757 | 0.900 | 0.742 | 0.583 | 8.500 | 0.175 | 0.256 | 1.000 |
| `ours_scope_time_state` | 36 | 0.626 | 0.824 | 0.687 | 0.694 | 8.114 | 0.227 | 0.345 | 0.500 |
| `ours_scope_time_state` repair checkpoint | 36 | 0.765 | 0.914 | 0.763 | 0.750 | 9.111 | 0.196 | 0.297 | 1.000 |

Interpretation:

- The repaired Ours state-packet checkpoint is strongest on `ans_j`, `ans_10`, and `facet_r`.
- It still has high `hard_neg` and `over_ev`, so precision and support minimization remain the main method problems.
- Full-context is still a strong control in this small public setting.
- Validity scope-routed has the best hard-negative and over-evidence rates, so STALE/CUPMem-style baselines need serious comparison.
- Scope routing helps TSM, Graphiti, and Validity-aware baselines, not only Ours.

## Dated Canonical Snapshots

These are tracked snapshots and remain useful as reproducible checkpoints, but they predate the current v1.3 data, public state-packet path, and several paper-structured baselines.

### v1 Oracle-Facet

File: `stamb_state_benchmark/output/results_v1_oracle_facet.json`

| Variant | n | sup_f1 | slot_j | ans_j | hard_neg |
| --- | ---: | ---: | ---: | ---: | ---: |
| `full_context_llm` | 42 | 0.936 | 0.869 | 0.833 | 0.036 |
| `hybrid_rag` | 42 | 0.717 | 0.738 | 0.571 | 0.156 |
| `ours_scope_time_state` | 42 | 0.959 | 0.879 | 0.786 | 0.037 |

Use this only for diagnostic claims about state construction under known `scope_id / time_role / output_slots`.

### v1 Public End-to-End

File: `stamb_state_benchmark/output/results_v1_end_to_end.json`

| Variant | n | ev_sup | facet_r | facet_p | ans_j | hard_neg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_context_llm` | 42 | 0.769 | 0.940 | 0.863 | 0.786 | 0.125 |
| `hybrid_rag` | 42 | 0.690 | 0.675 | 0.781 | 0.500 | 0.193 |
| `ours_scope_time_state` | 42 | 0.768 | 0.964 | 0.783 | 0.857 | 0.181 |

### v1.1 Public End-to-End Staged Full

File: `stamb_state_benchmark/output/results_v1_1_public_e2e_staged_full_20260617.json`

This table predates the neutral baseline prompt change and current graded `ans_10` schema.

| Variant | n | ev_sup | ev_p | ev_r | facet_r | facet_p | ans_j | unsup | hard_neg | over_ev | unk_cur |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_context_llm` | 72 | 0.761 | 0.780 | 0.845 | 0.949 | 0.804 | 0.806 | 0.196 | 0.099 | 0.223 | 1.000 |
| `hybrid_rag` | 72 | 0.685 | 0.723 | 0.712 | 0.750 | 0.700 | 0.611 | 0.300 | 0.134 | 0.226 | 0.900 |
| `ours_scope_time_state` | 72 | 0.744 | 0.689 | 0.933 | 0.968 | 0.740 | 0.764 | 0.260 | 0.159 | 0.311 | 1.000 |

## External Benchmark Diagnostics

External benchmarks are generalization evidence, not replacements for the STAMB-State main table.

### LongMemEval-S

Runner: `Experiment/Other_BenchMark/LongMemEval-S/run_longmemeval_s.py`

| File | Variant | n | official acc | candidate recall | evidence recall | evidence precision |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `results_longmemeval_s_adapter_compare_3.json` | `scope_time_state_public` | 18 | 0.333 | 0.861 | 0.477 | 0.923 |
| `results_longmemeval_s_adapter_compare_3.json` | `scope_time_state_task_adapter` | 18 | 0.889 | 0.986 | 0.875 | 0.944 |
| `results_longmemeval_s_task_adapter_10_per_type_v2.json` | `scope_time_state_task_adapter` | 60 | 0.850 | 0.996 | 0.826 | 0.964 |

Weak spots: `single-session-preference`, `multi-session`, and answer composition under larger multi-session histories.

### LoCoMo-QA

Active graph builder: `Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py`

The table below is legacy text-adapter diagnostic evidence and is no longer the active LoCoMo path.

File: `stamb_state_benchmark/output/results_locomo_qa_10_per_type_gpt4omini_memory_router_raw.json`

| Type | n | answer F1 | exact match | candidate dialog recall | evidence F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| adversarial | 10 | 0.700 | n/a | 1.000 | 0.540 |
| multi-hop | 10 | 0.612 | 0.200 | 0.961 | 0.485 |
| open-domain | 10 | 0.341 | 0.100 | 0.800 | 0.309 |
| single-hop | 10 | 0.867 | 0.600 | 0.867 | 0.613 |
| temporal | 10 | 0.739 | 0.500 | 1.000 | 0.600 |
| overall | 50 | 0.652 | 0.350 | 0.926 | 0.509 |

Weak spots: open-domain answer typing/canonicalization and multi-hop composition. Candidate recall is already high enough that more retrieval alone is unlikely to solve the problem.

### STALE

Runner: `Experiment/Other_BenchMark/STALE/run_stale.py`

| File | n scenarios | conflict split | overall | dim1 | dim2 | dim3 |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `results_stale_scope_time_state_10_balanced_deepseek_judged.json` | 10 | T1=5, T2=5 | 0.633 | 0.500 | 0.700 | 0.700 |
| `results_stale_scope_time_state_10_balanced_deepseek_prompt_v2_judged.json` | 10 | T1=5, T2=5 | 0.767 | 0.800 | 0.600 | 0.900 |
| `results_stale_scope_time_state_10_balanced_deepseek_prompt_v3_chrono_judged.json` | 10 | T1=5, T2=5 | 0.467 | 0.400 | 0.200 | 0.800 |
| `results_stale_scope_time_state_10_deepseek_judged.json` | 10 | T1=10 | 0.667 | 0.700 | 0.700 | 0.600 |

Weak spot: T2 propagation and false-premise resistance. Chronology-only prompting regressed and should remain a negative ablation.

## Baseline Provenance Table To Add

This table is not complete yet and should be added before paper writing:

| Baseline | Source type | Runner | Track | Scope-routed | Paper-structured | Real-system adapter | Diagnostic/main |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Full-context LLM | control | `Experiment/run/run_public_benchmark.py` | public | no | no | no | main control |
| Hybrid RAG | generic baseline | `Experiment/run/run_public_benchmark.py` | public | no | no | no | main baseline |
| TSM | paper reproduction | `Experiment/run/run_public_benchmark.py` | public | global / scope-routed variants | yes | no | main baseline |
| STALE/CUPMem | paper reproduction | `Experiment/run/run_public_benchmark.py` | public | global / scope-routed variants | yes | no | main baseline |
| Graphiti/Zep | external system | `Experiment/Main_Baseline/graphiti_zep/run_graphiti_baseline.py` | public | global / scope-routed variants | no | yes | main baseline |
| Graphiti paper reproduction | paper audit | `Experiment/Main_Baseline/graphiti_paper_reproduction/run_graphiti_paper_audit.py` | oracle/audit | scope group ids | yes | yes | diagnostic |
| Ours | proposed method | `Experiment/run/run_public_benchmark.py` | public | yes | n/a | no | main / ablation |

## Next Result Work

1. Complete human annotation and agreement/adjudication reports.
2. Run v1.3 Public End-to-End canonical scored table, starting with `balanced_half`.
3. Add and run a small-sample MemConflict diagnostic.
4. Produce the full baseline provenance table.
5. Reduce Ours public `hard_neg` and `over_ev` without losing `unknown_current`.
6. Expand LongMemEval-S, LoCoMo-QA, and STALE diagnostics only after each small-sample failure mode is understood.

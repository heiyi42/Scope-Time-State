# STAMB-State Results

## Current Status

- Data: STAMB-State v1, 58 raw events, 42 cases; STAMB-State v1.1, 106 raw events, 72 cases.
- Oracle-Facet runner: `Experiment/run/run_llm_benchmark.py`.
- Oracle-Facet evaluator: `Experiment/analyze_metrics.py`.
- Public End-to-End runner/evaluator: `Experiment/run/run_public_benchmark.py`.
- Target model: DeepSeek `deepseek-v4-flash`.
- Judge model: OpenAI `gpt-5.4-mini`.
- Canonical Oracle-Facet result file: `stamb_state_benchmark/output/results_v1_oracle_facet.json`.
- Canonical public End-to-End result file: `stamb_state_benchmark/output/results_v1_end_to_end.json`.
- Current v1.1 public End-to-End staged result file before neutralizing the baseline prompt:
  `stamb_state_benchmark/output/results_v1_1_public_e2e_staged_full_20260617.json`.
- After the 2026-06-17 neutral baseline prompt change, rerun the full v1.1 public End-to-End
  table with the current `ans_j` + `ans_10` judge schema before reporting final baseline comparisons.
- The v1 canonical result snapshots predate the paper-structured `tsm`,
  `validity_aware_consolidation`, and `graphiti_paper_reproduction` work.

`stamb_state_benchmark/` is intentionally limited to `data/` and `output/`.
Experiment code and baseline adapters live under `Experiment/`; benchmark build and validation scripts live under top-level `scripts/`.

## Main Table

Public End-to-End staged full v1.1 run, 2026-06-17, before neutralizing the baseline prompt:

This table predates the current graded `ans_10` field, so it only reports strict `ans_j`.

| Variant | n | ev_sup | ev_p | ev_r | facet_r | facet_p | ans_j | unsup | hard_neg | over_ev | unk_cur |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `full_context_llm` | 72 | 0.761 | 0.780 | 0.845 | 0.949 | 0.804 | 0.806 | 0.196 | 0.099 | 0.223 | 1.000 |
| `hybrid_rag` | 72 | 0.685 | 0.723 | 0.712 | 0.750 | 0.700 | 0.611 | 0.300 | 0.134 | 0.226 | 0.900 |
| `ours_scope_time_state` | 72 | 0.744 | 0.689 | 0.933 | 0.968 | 0.740 | 0.764 | 0.260 | 0.159 | 0.311 | 1.000 |

Oracle-Facet full v1 run:

| Variant | n | sup_f1 | slot_j | ans_j | hard_neg |
|---|---:|---:|---:|---:|---:|
| `full_context_llm` | 42 | 0.936 | 0.869 | 0.833 | 0.036 |
| `hybrid_rag` | 42 | 0.717 | 0.738 | 0.571 | 0.156 |
| `ours_scope_time_state` | 42 | 0.959 | 0.879 | 0.786 | 0.037 |

Public End-to-End full v1 run:

| Variant | n | ev_sup | facet_r | facet_p | ans_j | unsup | hard_neg |
|---|---:|---:|---:|---:|---:|---:|---:|
| `full_context_llm` | 42 | 0.769 | 0.940 | 0.863 | 0.786 | 0.137 | 0.125 |
| `hybrid_rag` | 42 | 0.690 | 0.675 | 0.781 | 0.500 | 0.219 | 0.193 |
| `ours_scope_time_state` | 42 | 0.768 | 0.964 | 0.783 | 0.857 | 0.217 | 0.181 |

## Interpretation

The public End-to-End v1.1 run is the right setting for claims about the usable pipeline under
hidden `scope_id`, hidden `output_slots`, and hidden gold support. In this setting,
`ours_scope_time_state` is not yet a clean win over every baseline:

- It has the best state recall signals: `ev_r=0.933` and `facet_r=0.968`.
- It beats `hybrid_rag` on `ev_sup`, `ev_r`, `facet_r`, `facet_p`, `ans_j`, `unsup`,
  and `unknown_current`.
- It does not beat `full_context_llm` on `ans_j`, `facet_p`, `hard_neg`, or `over_ev`.

The main current weakness is over-broad state retrieval under public free-facet output. Ours
recovers more gold state facets but also emits more unsupported or stale facets, which hurts
precision and final answer grading. The next method work should reduce extra facets and
hard-negative evidence while preserving the high recall and `unknown_current` behavior.

In the older Oracle-Facet v1 run, `ours_scope_time_state` is strongest on evidence support and
state-slot semantics:

- Highest `sup_f1`: 0.959.
- Highest `slot_j`: 0.879.
- Low hard-negative rate: 0.037.

`full_context_llm` still has the best final answer score (`ans_j=0.833`). The current gap is mostly an answer-composition issue rather than a retrieval issue: `ours_scope_time_state` often identifies the right supporting state, but the final natural-language answer can still omit or compress required facets.

The recent prompt fix specifically addressed plan-not-done and unknown-current cases. After that fix:

- `plan_not_done`: `slot_j=1.000`, `ans_j=1.000`.
- `unknown_current`: `slot_j=1.000`, `ans_j=1.000`.

The older public End-to-End v1 run remains useful as a dated checkpoint, but the v1.1 staged
public run above should be used for current public-pipeline claims.

## Reproduction

Smoke validation:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/run/run_llm_benchmark.py --dry-run
```

Run the canonical Oracle-Facet main table:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/run/run_llm_benchmark.py \
  --provider deepseek \
  --judge \
  --judge-provider openai
```

Recompute metrics and breakdowns:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/analyze_metrics.py \
  stamb_state_benchmark/output/results_v1_oracle_facet.json \
  --show-breakdown
```

Run a public End-to-End smoke test:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/run/run_public_benchmark.py \
  --provider deepseek \
  --judge \
  --judge-provider openai \
  --limit-cases 5 \
  --variants full_context_llm ours_scope_time_state \
  --output stamb_state_benchmark/output/results_v1_end_to_end_smoke.json \
  --cache stamb_state_benchmark/output/llm_cache.v1_end_to_end_smoke.json
```

Run the canonical public End-to-End table:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/run/run_public_benchmark.py \
  --provider deepseek \
  --judge \
  --judge-provider openai
```

Run the current v1.1 public End-to-End staged table:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/run/run_public_benchmark.py \
  --data-version v1_1 \
  --provider deepseek \
  --judge \
  --judge-provider openai \
  --variants full_context_llm hybrid_rag ours_scope_time_state \
  --output stamb_state_benchmark/output/results_v1_1_public_e2e_staged_full_20260617.json \
  --cache stamb_state_benchmark/output/llm_cache.v1_1_public_e2e_staged_full_20260617.json
```

## Commit Policy

Recommended to commit:

- `Experiment/` code and docs.
- `scripts/` benchmark build/validation scripts.
- `Design/BenchMark/` task and benchmark docs.
- `stamb_state_benchmark/data/`.
- `stamb_state_benchmark/output/results_v1_oracle_facet.json` as the canonical current experiment snapshot.
- `stamb_state_benchmark/output/results_v1_end_to_end.json` as the canonical public End-to-End snapshot.
- `stamb_state_benchmark/output/results_v1_1_public_e2e_staged_full_20260617.json` as the
  current v1.1 public End-to-End staged snapshot.
- `stamb_state_benchmark/output/validation_report*.json` only as lightweight data-validation
  snapshots.

Recommended not to commit:

- API cache files under `stamb_state_benchmark/output/`.
- Smoke, audit, pairwise-analysis, and temporary rerun outputs under `stamb_state_benchmark/output/`.
- `.DS_Store` and Python bytecode caches.

## Next Work

1. Improve `ours_scope_time_state` public precision: reduce unsupported extra facets, stale mention evidence, over-evidence, and hard-negative evidence without losing high `facet_r`.
2. Improve Oracle-Facet answer composition so final answers preserve all required facets.
3. Rerun the expanded Oracle-Facet main table with `tsm`, `validity_aware_consolidation`, and the
   Graphiti/Zep runners.
4. Run `graphiti_paper_reproduction` audit-only first, then the full judged run after Neo4j and BGE
   model downloads are confirmed.
5. Decide later whether `Memory-T1` is feasible enough to reproduce.

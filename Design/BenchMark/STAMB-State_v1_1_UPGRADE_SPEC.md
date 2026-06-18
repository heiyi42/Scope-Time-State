# STAMB-State v1.1 Upgrade Spec

## Goal

v1.1 expands STAMB-State without changing the frozen task definition: latest valid state retrieval over scoped event streams.

The upgrade is for robustness, not score chasing. v1 remains the reproducible 42-case benchmark. v1.1 adds harder cases around the known semantic failure modes while preserving the same output contract:

```json
{
  "evidence_events": ["event_id"],
  "state_slots": {
    "slot_name": {
      "value": "current valid state text",
      "support_event": "event_id or null",
      "support_events": ["event_id"]
    }
  },
  "coverage_check": {
    "slot_name": true
  },
  "answer": "final answer"
}
```

## Versioning

- v1 is frozen under `stamb_state_benchmark/data/v1`.
- v1.1 is generated under `stamb_state_benchmark/data/v1_1`.
- v1.1 must be rebuilt from `scripts/build_v1_1_from_v1.py`, not hand-edited as loose JSON.
- The public track remains no-gold: `scope_id`, `output_slots`, gold states, support events, hard negatives, difficulty tags, and answerability stay hidden.

## Coverage Added

v1.1 appends 6 scopes, 48 events, and 30 cases to v1:

- `search_index_rollout`: stale dashboard mention, cancelled rollout, hybrid rerank latency, planned but unfinished cross-encoder evaluation.
- `billing_migration`: Stripe/Paddle/provider pivot, invoice-export false completion, legal review unknown-current, deadline lookup.
- `eval_harness`: metric semantics, judge coverage holes, planned diagnostics, benchmark-bias guard.
- `cache_refactor`: deepcopy/cache fixes, circular-reference trace fix, cleanup status, planned regression test, insufficient evidence for production rollout.
- `ui_accessibility`: stale screenshot vs fixed overlap, remaining contrast issue, visual policy pivot, planned audit, insufficient evidence for customer acceptance.
- `api_rate_limit`: provider split, stale invalid-token log, Graphiti run completion, cache/cost risk.

## Target Counts

- v1: 58 events, 42 cases, 10 scopes.
- v1.1: 106 events, 72 cases, 16 scopes.

The 72-case size is intentional: large enough to stress the task taxonomy, small enough to manually audit before using it as a paper result.

## Required Validation

Run these before reporting v1.1 results:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 python scripts/build_v1_1_from_v1.py
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 python scripts/validate_v1.py \
  --v1-dir stamb_state_benchmark/data/v1_1 \
  --out stamb_state_benchmark/output/validation_report_v1_1.json
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 python Experiment/run/run_llm_benchmark.py \
  --data-version v1_1 --dry-run
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 python Experiment/run/run_public_benchmark.py \
  --data-version v1_1 --dry-run
```

## Metrics

Keep v1 metric semantics:

1. `sup_f1`
2. `slot_j`
3. `ans_j`

Keep `event_f1`, `req_f1`, precision/recall, hard-negative hit rate, answerability, and future over-evidence diagnostics as analysis metrics. Do not rank methods by `event_f1` alone.

## Anti-Bias Rules

- Do not add cases because one method fails them.
- Add cases only when they instantiate a task-level phenomenon already listed in this spec.
- Keep multi-event support when a state depends on a correction, supersession, stale mention, or old/new comparison.
- Keep `unknown_current` distinct from completed plans: a planned action without a completion event should not be marked done.
- Keep insufficient-evidence cases answerable only as "not enough evidence"; do not invent hidden state.

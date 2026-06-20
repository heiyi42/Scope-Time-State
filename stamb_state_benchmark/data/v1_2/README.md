# STAMB-State v1.2

v1.2 upgrades v1.1 without overwriting it. The task remains latest-valid-state retrieval, but the data now has longer per-scope event streams, explicit difficulty levels, more answerability cases, and balanced subset files for partial public runs.

## Counts

- events: 288
- cases: 124
- scopes: 16
- scope_event_bins: {'short_<=12': 4, 'medium_13_18': 8, 'long_19+': 4}
- case_scope_event_bins: {'short_<=12': 26, 'medium_13_18': 64, 'long_19+': 34}
- difficulty_level: {'easy': 30, 'hard': 34, 'medium': 60}
- answerability: {'answerable': 104, 'insufficient_evidence': 10, 'unknown_current': 10}
- operations: {'next_action': 24, 'state_lookup': 73, 'state_summary': 27}
- scope_type: {'admin_funding': 1, 'api_platform': 1, 'benchmark_eval': 1, 'business_infra': 1, 'coursework_debugging': 1, 'data_ops': 1, 'frontend_accessibility': 1, 'incident_response': 1, 'infra_refactor': 1, 'ml_product': 2, 'research_writing': 2, 'robotics_system': 1, 'search_infra': 1, 'security_product': 1}
- hard_negative_count: {0: 52, 1: 2, 3: 36, 5: 34}

## Added Coverage

- explicit `difficulty_level` on every evaluator case;
- public-safe `scope_taxonomy.json` and scope profile fields for domain/task-family breakdowns;
- longer target-scope streams, with 12/18/24-event scope bins;
- in-scope no-update and stale-mention distractors beyond the original hard negatives;
- additional unknown-current and insufficient-evidence cases;
- additional next-action and state-summary cases while keeping the three-operation contract fixed;
- `subsets.json` with `balanced_half` and `smoke_12` case-id lists.

## Files

- `events_raw.json`: visible event stream without evaluator-only validity fields.
- `event_annotations.json`: evaluator/oracle-only state relevance, status, correction, and supersession annotations.
- `cases.json`: evaluator-only query cases with gold state slots, difficulty levels, and support events.
- `subsets.json`: named case-id subsets for balanced partial runs.
- `scope_taxonomy.json`: public-safe scope type, task family, and domain labels.
- `benchmark_audit.json`: reproducible distribution audit.
- `public/`: no-gold public input generated from the same events/cases.

## Validation

```bash
python scripts/validate_v1.py --v1-dir /Users/mac/Desktop/EpisodicMemory/stamb_state_benchmark/data/v1_2
python Experiment/run/run_public_benchmark.py --data-version v1_2 --case-subset balanced_half --dry-run
```

# STAMB-State v1.3

v1.3 is the final-size public benchmark. It keeps the latest-valid-state retrieval contract while replacing template-style expansion with scope-specific event streams and cases.

## Counts

- events: 480
- cases: 240
- scopes: 24
- scope_event_bins: {'short_<=12': 6, 'medium_13_18': 12, 'long_19+': 6}
- case_scope_event_bins: {'short_<=12': 57, 'medium_13_18': 121, 'long_19+': 62}
- difficulty_level: {'easy': 54, 'hard': 72, 'medium': 114}
- answerability: {'answerable': 180, 'insufficient_evidence': 30, 'unknown_current': 30}
- operations: {'next_action': 48, 'state_lookup': 145, 'state_summary': 47}
- operation_subtype: {'completion_unknown': 30, 'correction_aware_lookup': 39, 'finish_condition_verification': 8, 'insufficient_evidence': 30, 'latest_valid_state_lookup': 12, 'multi_facet_summary': 47, 'partial_evidence_lookup': 16, 'plan_continuation': 40, 'stale_state_invalidation': 18}
- scope_type: {'admin_funding': 1, 'api_platform': 1, 'benchmark_eval': 1, 'business_infra': 1, 'coursework_debugging': 1, 'customer_support': 1, 'data_ops': 1, 'data_pipeline': 1, 'docs_release': 1, 'embedded_system': 1, 'frontend_accessibility': 1, 'governance_policy': 1, 'incident_response': 1, 'infra_refactor': 1, 'ml_infra': 1, 'ml_product': 2, 'privacy_compliance': 1, 'product_growth': 1, 'research_writing': 2, 'robotics_system': 1, 'search_infra': 1, 'security_product': 1}
- hard_negative_count: {0: 24, 1: 30, 3: 114, 5: 72}
- hard_negative_type: {'corrected_old_state': 44, 'cross_scope_collision': 126, 'insufficient_evidence_distractor': 26, 'non_update_latest': 81, 'other_in_scope_distractor': 40, 'partial_evidence': 23, 'plan_not_done': 80, 'procedural_noise': 80, 'stale_mention': 359}
- hard_negative_total: 732
- gold_event_total: 367

## Quality Audit

- max_normalized_event_repeat: 1
- max_normalized_query_repeat: 1
- max_normalized_slot_value_repeat: 2
- generic_marker_counts: {'旁路日志采样': 0, '轻量复查': 0, '旧完成状态': 0, '主线阻塞': 0, 'approval': 0, 'acceptance': 0}

## Added Coverage

- 24 public scope streams and 480 public events;
- 240 evaluator cases with operation mix near 60/20/20;
- public-safe scope taxonomy expanded to 24 scope domains;
- balanced half subset with 120 cases for cheaper public E2E runs;
- domain-specific hard negatives and answerability cases instead of cross-scope boilerplate.

## Validation

```bash
python scripts/validate_v1.py --v1-dir /Users/mac/Desktop/EpisodicMemory/stamb_state_benchmark/data/v1_3
python scripts/audit_benchmark_quality.py --v1-dir /Users/mac/Desktop/EpisodicMemory/stamb_state_benchmark/data/v1_3 --fail-on-warnings
python Experiment/run/run_public_benchmark.py --data-version v1_3 --case-subset balanced_half --dry-run
```

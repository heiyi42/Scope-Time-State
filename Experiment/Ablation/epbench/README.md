# EPBench Claim--Scope--Time--State Ablation

This is the EPBench adaptation of the LoCoMo additive retrieval ablation. It
uses one fixed STS graph and one fixed answer model for all policies.

| Policy | Claim retrieval document | Candidate routing | Answer evidence |
| --- | --- | --- | --- |
| `claim` | `Claim.graph_text` only | global Claims | Claim + source Event raw text |
| `scope-claim` | `Claim.graph_text` only | routed Scope Claims + 8 global back-off Claims | Claim + source Event raw text |
| `scope-claim-time` | all semantic Claim fields + `Time.value` | Scope routing, explicit-date constraint, Event-time ordering | Claim + source Event raw text |
| `scope-claim-time-state` | same as above | same as above; top-16 final Claim anchors fetch StateFacets through `SUPPORTS` only | Claim + source Event raw text + closed StateFacet |

All policies use BM25 and dense Claim retrieval with RRF. Event `graph_text` and
`event_summary` and Scope values are masked from every Claim retrieval document;
Event `raw_text` is used only after Claim selection as answer evidence. The fixed budget is
80 lexical candidates, 80 dense candidates, 14 Scope routes, 8 global back-off
Claims, 24 final Claims, and at most 24 deduplicated source Events. Only the
full policy reads `SUPPORTS` from its top-16 Claim anchors; it never traverses
Claim--Claim state relations or lets StateFacets change Claim ranking.
StateFacets have no numerical cap, but are included only when every supporting
Claim survives the final 24-Claim selection.

Time-role equality is never used as a Claim hard filter because the EPBench
`HAS_TIME` edges do not store reliable role labels. The Time policies use exact
`Time.value` constraints and sort the top-80 RRF candidates by source-Event time
before truncating to the final 24 Claims. Non-Time policies ignore question time
anchors so the additive ablation does not leak temporal routing.

Run QA for one policy (four answer calls in parallel by default):

```bash
python Experiment/Ablation/epbench/run_epbench_claim_scope_time_state.py scope-claim-time --stage qa
```

Run all four policies:

```bash
python Experiment/Ablation/epbench/run_epbench_claim_scope_time_state.py all --stage qa
```

Score a completed policy with the official EPBench ARTEM evaluator:

```bash
python Experiment/Ablation/epbench/run_epbench_claim_scope_time_state.py scope-claim-time-state --stage official
```

Outputs are isolated in `Experiment/Ablation/epbench/results/clean_v2/<policy>/`:
`retrieval.json`, `qa.json`, and `official_artem.json`. The official file is
the comparison metric; its `summary.overall.mean_f1_lenient` is ARTEM's Mean F1,
not a locally computed proxy.

# EPBench Claim--Scope--Time--State Ablation

This is the EPBench adaptation of the LoCoMo additive retrieval ablation. It
uses one fixed STS graph and one fixed answer model for all policies.

| Policy | Claim candidate space | Time role filter | Relation-aware expansion | Answer evidence |
| --- | --- | --- | --- | --- |
| `claim` | all Claims | no | no | Claim + source Event |
| `scope-claim` | routed Scope Claims + 8 global back-off Claims | no | no | Claim + source Event |
| `scope-claim-time` | routed Scope Claims + 8 global back-off Claims | top-2 roles, before RRF | no | Claim + source Event |
| `scope-claim-time-state` | same as above | top-2 roles, before RRF | top-16 seeds only | Claim + source Event + closed StateFacet + Claim relations |

All policies use BM25 and dense Claim retrieval with RRF. The fixed budget is
80 lexical candidates, 80 dense candidates, 14 Scope routes, 8 global back-off
Claims, 24 final Claims, and at most 24 deduplicated source Events. Only the
full policy reads `SUPPORTS`, `SUPERSEDES`, `CORRECTS`, or `CONFLICTS_WITH`.
StateFacets have no numerical cap, but are included only when every supporting
Claim survives the final 24-Claim selection.

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

Outputs are isolated in `Experiment/Ablation/epbench/results/<policy>/`:
`retrieval.json`, `qa.json`, and `official_artem.json`. The official file is
the comparison metric; its `summary.overall.mean_f1_lenient` is ARTEM's Mean F1,
not a locally computed proxy.

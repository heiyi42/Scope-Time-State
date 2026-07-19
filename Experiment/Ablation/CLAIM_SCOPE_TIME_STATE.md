# LoCoMo Claim-Scope-Time-State Ablation

This experiment is additive. It does not replace or modify the existing
`event-rag`, `scope-event`, `scope-event-time`, or `sts` policies and writes to a
separate result root:

`Graph/results/locomo_qa/claim_scope_time_state_ablation`

## Policies

| Policy | Scope routing | Time-role filter | Relation-aware expansion | StateFacet access |
| --- | --- | --- | --- | --- |
| `claim` | No | No | No | No |
| `scope-claim` | Yes | No | No | No |
| `scope-claim-time` | Yes | Yes | No | No |
| `scope-claim-time-state` | Yes | Yes | Yes | Only through Claim relation expansion |

All policies retrieve Claims with BM25 and dense retrieval and combine the two
rankings using RRF. Scope-enabled policies primarily search Claims attached to
the routed semantic scopes and may add at most eight globally retrieved Claims
as back-off candidates before the final query RRF.

For the two time-enabled policies, the question-only selector returns at most
two time roles ordered by confidence. Claims matching neither selected role are
removed before Claim retrieval and RRF.

The first three policies return at most 24 Claims and their source Events. They
cannot retrieve StateFacet nodes or relation rows. The full policy starts from
the top 16 Claims, performs relation-aware Claim/StateFacet expansion, reranks
all expanded Claims against the query with BM25+dense RRF, and retains at most
24 Claims. StateFacets have no numerical cap, but each retained StateFacet must
have its complete Claim evidence inside the final Claim set.

## Entry point

Run one policy on `conv-26`:

```bash
python Experiment/Ablation/run_locomo_claim_scope_time_state.py scope-claim-time --sample-id conv-26
```

Run all four policies on all ten LoCoMo conversations:

```bash
python Experiment/Ablation/run_locomo_claim_scope_time_state.py all --all-samples
```

The fixed defaults are 80 BM25 candidates, 80 dense candidates, 14 routed
scopes, 8 global back-off Claims, 16 full-policy seed Claims, 24 final Claims, 24 source Events,
`gpt-4o-mini`, and `text-embedding-3-small`.

Each output reports Answer F1, BLEU-1, Exact Match, Candidate Recall,
Candidate Precision, Candidate F1, and final cited-evidence metrics.

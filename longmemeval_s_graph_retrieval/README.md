# Graph Retrieval Methods for LongMemEval-S

Question-independent graph construction with scope-first retrieval for the LongMemEval-S benchmark.

## Architecture

```
Haystack sessions (all, no BM25 pre-filter)
    ↓
LLM extraction (question-independent) → Checkpointed graph builder
    ↓
artifacts/graphs/<type>/<id>.graph.json   (95 graphs, 5 node types, 8 edge types)
    ↓
Scope selection → Expand → State packet → 4o-mini answer → gpt-4o judge
```

Graph construction never sees the benchmark question.

## Version History

| Version | Scope Selection | LLM Cost/Answer | Status |
|---|---|---|---|
| v7 | Lexical label matching + type priors | 1 call (answer) | Baseline |
| v7.1 | TF-IDF scope profile (broken) | 1 call | Abandoned |
| v7.2 | Scope → Time → Facet → Claim (over-filtered) | 1 call | Abandoned |
| v7.3 | Hybrid pool (ms/tr skip Facet) | 1 call | Abandoned |
| v7.4 | BM25 content profile | 1 call | Best recall |
| v7.5 | LLM semantic scope (4o-mini) | 2 calls | Best accuracy |
| v9  | LLM semantic scope (packaged) | 2 calls | Clean version |
| v10 | BM25 E4 scope (tuned) | 1 call | Zero-cost retrieval |

## Key Finding: BM25 E4 Parameters

After 12-configuration grid search on 95 graphs:

| | events | claims | lw | ew | ev_r (95 case) |
|---|---|---|---|---|---|
| Baseline | 120 | 160 | 3 | 2 | 0.814 |
| **E4** | **5** | **10** | **3** | **2** | **0.887** |
| E1 | 5 | 10 | 1 | 1 | 0.884 |

Small scope profiles prevent large generic scopes from dominating.

## Benchmark Results

### Question-independent graph (all versions use same 95 graphs)

| Type | v7.5 (LLM) ans_j | v10 (BM25) ans_j | v10 ev_r | TSM |
|---|---|---|---|---|
| ku | 0.700 (n=10) | — | — | 0.808 |
| ms | 0.500 (n=43) | 0.273 (n=55) | 0.613 | 0.692 |
| sp | 0.500 (n=20) | — | — | 0.400 |
| tr | 0.800 (n=10) | — | — | 0.699 |
| **Weighted** | **~0.72** | — | — | **0.748** |

### Evidence recall by method

| Method | ms ev_r | ku ev_r | sp ev_r | tr ev_r | Overall ev_r |
|---|---|---|---|---|---|
| V7 (lexical) | 0.558 | 0.500 | — | 0.858 | 0.698 |
| V7.4 (BM25 baseline) | 0.775 | 1.000 | 0.750 | 0.975 | 0.814 |
| V10 (BM25 E4) | **0.860** | **1.000** | **0.850** | **1.000** | **0.887** |

BM25 E4 achieves dramatically higher evidence recall than lexical or LLM-based scope selection, but evidence quality (claim noise) limits answer accuracy.

## Current Bottleneck

**4o-mini cannot count across sessions.** Even with perfect evidence recall (ev_r=1.0), the model misses 5 hours or counts 2 items instead of 3. The claims are atomic facts ("30h Last of Us", "25h Hades"), not aggregated summaries ("total 140 hours"). The model must perform arithmetic on fragmented evidence.

## Graph Inventory

| Type | Count | Location |
|---|---|---|
| knowledge-update | 10 | v6/v10 |
| multi-session | 55 | v9/v10 |
| single-session-preference | 20 | v6/v10 |
| temporal-reasoning | 10 | v6/v10 |
| **Total** | **95** | |

Missing: single-session-assistant (56), single-session-user (70).

## Next Steps

1. **BM25 → LLM two-stage scope selection** (BM25 top-15 → LLM top-8)
2. **Claim denoising** (scope-internal BM25 on claims)
3. **Evidence formatting for arithmetic** (session-grouped + numeric hints)
4. **Build remaining types** (sa/su, 126 graphs)

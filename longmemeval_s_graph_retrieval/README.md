# LongMemEval-S Graph Retrieval

Candidate-session → local Scope-Time-State graph → State_packet → answer.

The main pipeline (`stamb_state_benchmark/`) is not modified. Each subdirectory is
a standalone method variant.

---

## Architecture

```
Candidate session retrieval
  → LLM graph extraction (Claims / State Facets / relations)
  → in-memory networkx.MultiDiGraph
  → topology-driven State_packet retrieval
  → answer model reads State_packet
```

Graph schema: Episode/Event, Claim, State Facet, Entity/Scope, Time nodes;
supersedes / corrects / conflicts / supports edges.

---

## Iterations

### v1: `task_semantics_local_graph`

Runtime graph construction. LLM extracts claims per batch of sessions, builds
graph in-process, retrieves State_packet. One-model setting (same LLM constructs
graph and answers).

### v2: `prebuilt_llm_kg_graph`

Offline construction + online retrieval. Strong LLM prebuilds graph artifacts
(one `.graph.json` per question_id). Benchmark loads artifacts, gpt-4o-mini
reads State_packet. Two-model setting.

### v3 (final): `prebuilt_llm_kg_graph_v2_stability_first`

Same two-model architecture as v2, plus:

- `StableRequestsJsonClient` with `reasoning_content` fallback — handles
  reasoning-model empty-content failures.
- `max_tokens=8192` default.
- Scheduler (`build_all.py`) with isolated per-case workers, heartbeat,
  auto-resume, stuck detection.
- Graphs organized by question type under `artifacts/graphs/<type>/`.
- 60 prebuilt graphs included.

**Benchmark (60 cases, gpt-4o-mini reader, gpt-4o judge):**

| Question Type | Graph | BM25-only |
|---|---|---|
| knowledge-update | **1.000** | 0.500 |
| multi-session | **0.700** | 0.400 |
| single-session-assistant | **1.000** | 0.900 |
| single-session-preference | **0.600** | 0.200 |
| single-session-user | **0.800** | 0.800 |
| temporal-reasoning | **0.900** | 0.500 |
| **Total** | **0.833** | **0.550** |

---

## Quick Start (final version)

```bash
cd longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first

# Run benchmark using prebuilt graphs
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.run_longmemeval \
  --limit-per-type 10 \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs \
  --answer-provider openai \
  --answer-model gpt-4o-mini \
  --judge \
  --judge-provider openai \
  --judge-model gpt-4o-2024-08-06 \
  --output outputs/results.json
```

See `prebuilt_llm_kg_graph_v2_stability_first/README.md` for full documentation.

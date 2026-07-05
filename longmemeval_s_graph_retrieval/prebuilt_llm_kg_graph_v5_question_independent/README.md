# LongMemEval-S v5 Question-Independent Graph

v5 keeps the v2 graph schema unchanged while moving all question conditioning out
of graph construction.

```text
Offline construction:
all visible history sessions -> v2-compatible graph artifact

Online retrieval:
question -> lexical/entity/time graph search -> local state packet -> answer
```

Construction must not use `question`, `question_type`, `question_date`, `answer`,
or `answer_session_ids`. It only sees session ids, dates, roles, turn text, and
message order. The resulting graph still uses the v2 node and edge types:

- Nodes: `Episode/Event`, `Claim`, `State Facet`, `Entity/Scope`, `Time`
- Edges: `event_mentions_entity`, `event_in_scope`, `claim_supported_by_event`,
  `claim_corrects_claim`, `claim_supersedes_claim`, `claim_conflicts_with_claim`,
  `facet_supported_by_claim`, `facet_current_after_time`

## Commands

Dry-run one artifact:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v5_question_independent.build_one_case --question-id <id> --dry-run
```

Build one artifact:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v5_question_independent.build_one_case --question-id <id>
```

Evaluate built artifacts:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v5_question_independent.run_longmemeval --limit-per-type 1 --dry-run
```

Use v2/v4 as query-conditioned diagnostics; use v5 as the formal
question-independent graph setting.


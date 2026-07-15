# STS Graph v3 Design

**Status:** approved for implementation

**Date:** 2026-07-15

**Primary target:** LoCoMo QA, starting with `conv-26`

**Construction model:** `gpt-4o-mini`

## 1. Decision

STS Graph v3 is a new, isolated graph and retrieval version. It does not replace, rewrite, or share runtime switches with the existing v2 implementation.

The design is governed by two principles:

1. The model-facing schema must stay small enough for reliable `gpt-4o-mini` structured output.
2. The stored graph and retrieval semantics must generalize beyond LoCoMo without benchmark-specific ontologies, task labels, or gold metadata.

The resulting method is:

```text
minimal Claim extraction
-> code-owned graph construction
-> Scope-routed Event-first retrieval
-> on-demand Claim completion
-> Time/State validity
-> bounded typed joins
-> SUPPORT/REFUTE/UNKNOWN verification
-> operation-aware readout
```

## 2. Version isolation

### 2.1 Existing v2 remains untouched

The implementation must not modify, import runtime code from, or overwrite:

```text
Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/
Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py
Graph/output/results/locomo_qa/ours_scope_time_state/
every pre-existing Graph/output/graph/locomo_qa_sample_graph_*/ root
every pre-existing LoCoMo cache root under Graph/output/cache/
Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py
```

Existing artifacts remain the frozen A/B baseline even if v3 later becomes the preferred method. Before implementation, code records a checksum manifest for these protected roots; tests compare it after v3 writes. Path guards operate on `Path.resolve()` and reject protected directories and symlink targets.

The protected cache set is frozen from the implementation-start snapshot and explicitly excludes the dedicated `Graph/output/cache/locomo_qa_sts_v3/` root. A later builder/query invocation must not dynamically reclassify v3's own cache as a protected v2 cache.

### 2.2 New v3 surfaces

The implementation will add:

```text
pipeline/sts_v3/
  __init__.py
  adapter.py
  schema.py
  build.py
  retrieve.py
  verify.py

Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/
  __init__.py
  adapter.py
  graph_builder.py
  graph_query_runner.py

pipeline/sts_v3/tests/test_contract.py
Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py
```

New artifacts must use dedicated paths:

```text
Graph/output/graph/locomo_qa_sts_v3/<sample_id>/
Graph/output/cache/locomo_qa_sts_v3/
Graph/output/results/locomo_qa/ours_scope_time_state_v3/
```

Before opening any writable graph, cache, result, trace, or manifest path, the v3 CLI resolves it and fails if it is equal to or contained by a protected root. The same guard applies to every symlink target.

### 2.3 No compatibility branches inside v3

The v3 core will not contain:

- `legacy`, `relation-aware`, `scope-coverage`, or `auto` expansion modes;
- Event-only or StateFacet-only variants;
- v2 schema readers or silent v2 conversion;
- LLM Ledger, time-selector, evidence-repair, or task-specific retrieval branches.

If v2 behavior is needed, callers use the preserved v2 runner.

## 3. Scope of the first implementation

The first implementation includes the shared v3 core, the LoCoMo adapter, contract tests, and a `conv-26` construction/retrieval smoke path.

EverMemBench is not migrated in the first implementation. Its existing path stays unchanged. Generalization is enforced through the core adapter contract and synthetic contract tests so later adapters do not change the v3 schema or retrieval algorithm.

## 4. Core adapter boundary

The shared core accepts only visible-memory records:

```text
memory_id
source_record_id
sequence_index
text
speaker_or_author
source_time
structural_scopes
source_type
```

Open fields such as `source_type` and `scope_kind` are strings, not core enums.

`memory_id` is the benchmark-neutral graph boundary. The LoCoMo adapter maps its `sample_id` to `memory_id`; other adapters may map a conversation, topic, group corpus, or haystack memory. The adapter may provide a query-time actor or date anchor when that information is part of the benchmark question contract. It may not provide:

```text
benchmark name to retrieval logic
question category or qtype
gold answer
gold evidence or answer-session IDs
multiple-choice options as retrieval text
benchmark-specific repair hints
```

Changing any forbidden metadata must leave the graph hash and retrieved v3 node IDs unchanged.

## 5. Stored graph schema

The stored graph has six node roles. Domain values remain open vocabulary.

All nodes contain:

```text
node_id: str
node_type: Scope | Event | Entity | Claim | Time | StateFacet
graph_id: str
memory_id: str
construction_method: str
```

Graph-level version and build provenance belong in the manifest rather than every node.

### 5.1 Scope

```text
scope_kind: str
scope_key: str
label: str
aliases: list[str]
is_hard_boundary: bool
```

Scope represents a visible source boundary. The LLM never creates Scope nodes or topic labels. Semantic Scope retrieval uses an index document derived from the Scope's raw Events, linked Entity aliases, Claim predicates/objects, and normalized Times.

Scope is source-provided structure, not an LLM classification. The adapter copies or deterministically names containers already present in the source, such as a memory, session, channel, thread, or explicit topic ID/title. If the source has no topic metadata, v3 creates no Topic Scope. For LoCoMo specifically, the adapter creates only one hard Memory Scope per `sample_id` and one child Session Scope per `session_N`; speaker is an Entity, session date is Time, and no Speaker or Topic Scope is materialized. Scope `label` comes from the source key/title, while the separate retrieval document is assembled by code from linked evidence.

### 5.2 Event

```text
source_record_id: str
sequence_index: int
source_type: str
text: str
language: str | null
content_hash: str
```

Event is the only answer-citable raw evidence unit. Speaker, Scope, Claim, and Time references are edges rather than duplicated Event fields.

### 5.3 Entity

```text
canonical_name: str
canonical_key: str
aliases: list[str]
entity_type: str | null
entity_type_source: str
resolution_method: str
```

`entity_type` is descriptive and open vocabulary. Retrieval and joins depend on Entity identity and edge role, not a closed entity type list.

Entity resolution is high precision:

1. source or speaker ID;
2. exact canonical name;
3. exact verified alias inside one memory;
4. otherwise a separate unresolved Entity.

Fuzzy or embedding similarity may retrieve aliases but may not write a canonical merge. Conjunctions such as `Alice and Bob` or `Melanie and another person` must not merge into one member.

### 5.4 Claim

```text
predicate: str
object_kind: entity | literal
object_literal: str | null
literal_datatype: str | null
polarity: positive | negative
assertion_status: asserted | uncertain | non_asserted
temporal_extent: bounded | ongoing | unknown
proposition_key: str
```

Subject and entity object identities are represented only by `HAS_SUBJECT` and `HAS_OBJECT` edges.

`predicate` and `literal_datatype` remain open vocabulary. `polarity`, `assertion_status`, and `temporal_extent` are the minimal logical kernel needed for state folding and proposition verification.

Predicate normalization is lexical, not ontological: Unicode normalization, lowercasing where applicable, whitespace/punctuation normalization, and conservative lemmatization. Semantic similarity may retrieve two predicates for comparison, but it does not persistently merge them into one predicate key without proposition-level evidence.

### 5.5 Time

```text
raw_text: str
normalized_start: str | null
normalized_end: str | null
precision: str
normalization_status: exact | range | relative_resolved | unresolved
anchor_event_id: str | null
```

Time role belongs to the edge because the same interval may be an Event occurrence, Claim validity, plan time, or state-current boundary.

For `HAS_TIME`, `source_text/source_start/source_end` are null only when Time is inherited solely from the source Event timestamp; in that case `Time.anchor_event_id` is required.

### 5.6 StateFacet

```text
dimension_key: str
predicate: str
status: current | ambiguous
resolution_method: deterministic | pairwise_llm | mixed
```

StateFacet is a materialized current-state index. It does not duplicate value, support Claim IDs, Event IDs, Scope IDs, or Time arrays. Its selected value comes from the Claim linked by `SUPPORTS(support_role=selected)`.

Historical StateFacets are not materialized. Historical values remain Claims connected by lifecycle edges and Time.

## 6. Edge schema

All edges contain:

```text
edge_id: str
edge_type: str
source_id: str
target_id: str
construction_method: str
```

The v3 edge types are:

| Edge | Endpoints | Required edge fields |
|---|---|---|
| `IN_SCOPE` | Event -> Scope | `scope_role` |
| `PARENT_SCOPE` | Scope -> Scope | `hierarchy_role` |
| `MENTIONS` | Event -> Entity | `mention_role`, `surface` |
| `ASSERTS` | Event -> Claim | `evidence_span`, `start`, `end`, `claim_ordinal` |
| `HAS_SUBJECT` | Claim -> Entity | `surface`, `resolution_method` |
| `HAS_OBJECT` | Claim -> Entity | `surface`, `resolution_method` |
| `OCCURRED_AT` | Event -> Time | `source_field` |
| `HAS_TIME` | Claim -> Time | `time_role`, `source_text`, `source_start`, `source_end` |
| `SUPPORTS` | Claim -> StateFacet | `support_role=selected|compatible|candidate` |
| `STATE_OF` | StateFacet -> Entity | none |
| `CURRENT_AFTER` | StateFacet -> Time | `basis_claim_id` |
| `SUPERSEDES` | new Claim -> old Claim | `decision_method`, `basis_event_ids` |
| `CORRECTS` | new Claim -> old Claim | `decision_method`, `basis_event_ids` |
| `CONFLICTS_WITH` | Claim <-> Claim | `decision_method`, `basis_event_ids` |

There are no generic `RELATED_TO`, `IMPLIES`, or `EQUIVALENT_TO` edges.

## 7. Minimal model-facing construction contract

`gpt-4o-mini` never emits graph nodes, graph edges, graph IDs, Scope labels, normalized Time, StateFacet fields, support IDs, lifecycle edges, or benchmark metadata.

It emits ten scalar fields per Claim:

```json
{
  "claims": [
    {
      "event": "E1",
      "subject": "Melanie",
      "predicate": "join",
      "object": "LGBTQ support group",
      "object_kind": "entity",
      "polarity": "positive",
      "assertion_status": "asserted",
      "temporal_kind": "event",
      "time_text": "last month",
      "evidence_span": "I joined an LGBTQ support group last month."
    }
  ]
}
```

Allowed model enums are intentionally small:

```text
object_kind: entity | literal
polarity: positive | negative
assertion_status: asserted | uncertain | non_asserted
temporal_kind: event | state | unknown
```

Short Event handles are mapped back to exact source IDs by code.

Both construction and query-frame prompts use the same open predicate convention: a concise lower-snake-case base relation, independent of particular entity names, Time, and polarity. This is a formatting contract, not a closed predicate vocabulary.

Code derives:

```text
predicate normalization
temporal extent validation
Entity IDs and aliases
literal normalization
proposition key
Time role and normalized interval
all node and edge IDs
State eligibility and lifecycle
```

The temporal enum maps deterministically into the stored logical kernel:

| Model field | Stored interpretation |
|---|---|
| `temporal_kind=event` | normally `temporal_extent=bounded` |
| `temporal_kind=state` | `ongoing` unless an explicit closed interval makes it `bounded` |
| `temporal_kind=unknown` | `temporal_extent=unknown` |

The code may downgrade a temporal interpretation to `unknown` when source Time evidence does not support it. It may not upgrade an `uncertain` or `non_asserted` Claim into an asserted Claim.

### 7.1 Extraction defaults

The shared core chunks by input-token budget and never crosses a hard Scope boundary. The following are LoCoMo's initial adapter defaults, not benchmark semantics:

```text
target Events per call: 4
context Events before/after: at most 2 each
maximum input tokens per extraction call: 8000
temperature: 0
soft maximum Claims per Event: 4
hard safety maximum Claims per Event: 6
```

The builder must not silently truncate an overflow. It retries the single Event and records `claim_overflow`; if the retry still exceeds the hard maximum, that Event's extraction fails validation instead of keeping an arbitrary prefix. A Claim is accepted only when:

- its Event handle is in the request whitelist;
- normalization may locate candidate spans, but `evidence_span` must map to exactly one raw character interval and satisfy `Event.text[start:end] == evidence_span`;
- `time_text` is null or maps to exactly one raw interval fully inside that Claim's evidence interval;
- subject, predicate, and object are non-empty;
- all enum values are valid.

An invalid Claim is discarded rather than repaired into unsupported graph content.

## 8. Claim deduplication and state folding

### 8.1 Same-Event extraction duplicates

After Entity and Time normalization, Claims with the same source Event and `proposition_key` are physically deduplicated. The accepted Claim retains a valid evidence span. Opposite polarity, different assertion status, or different temporal keys therefore never collide.

### 8.2 Repeated propositions across Events

Claims from different Events remain distinct even when their `proposition_key` matches. Retrieval may group them as one semantic proposition while proof closure retains every raw Event provenance.

### 8.3 State eligibility

A Claim is eligible for state folding only when:

```text
assertion_status = asserted
temporal_extent = ongoing
subject Entity is resolved
predicate is non-empty
```

The deterministic keys are:

```text
predicate_key = lexical_normalize(predicate)
object_key = "entity:" + object_entity_id
          or "literal:" + literal_datatype + ":" + lexical_normalize(object_literal)
temporal_key = sorted(time_role, normalized interval)
            or sorted(time_role, lexical_normalize(unresolved source time text))
            or "none"
proposition_key = sha256(subject_entity_id, predicate_key, object_key,
                         polarity, assertion_status, temporal_extent, temporal_key)
dimension_key = sha256(subject_entity_id, predicate_key)
```

`proposition_key` groups semantically identical propositions without collapsing their source Claims. `dimension_key` is used only to block candidate state comparisons; sharing it does not by itself authorize a fold.

### 8.4 Fold decisions

| Situation | Result |
|---|---|
| Same current value | one Claim is selected; repeated evidence is compatible support on the same StateFacet |
| Later value explicitly replaces the earlier value | `SUPERSEDES(new, old)` |
| Explicit correction | `CORRECTS(new, old)` |
| Unresolved contradiction | `CONFLICTS_WITH`, StateFacet ambiguous |
| Independent values that may coexist | `separate`; no lifecycle edge and no shared StateFacet |

There is no closed predicate-cardinality ontology. In initial v3, a StateFacet materializes one current single-valued state dimension. Claims judged `separate` remain directly retrievable through Claim/Event; if the bucket had a provisional facet, it is removed. Differing values that are neither separate nor explicitly ordered remain ambiguous rather than being forced into a single- or multi-valued class.

Deterministic checks run first. Only unresolved pairs call `gpt-4o-mini`, which returns one field:

```json
{"decision":"same|new_replaces_old|new_corrects_old|conflict|separate"}
```

Invalid resolver output creates no lifecycle edge and leaves one ambiguous StateFacet with both Claims as candidates. It must not silently treat conflicting values as independent current facts.

State folding is incremental rather than all-pairs. Claims are grouped by `(subject_entity_id, predicate_key)` and processed in deterministic state order. A same-`object_key`, same-polarity incoming Claim is merged as compatible evidence without an LLM call. Claims outside that group are never compared. Only a different object or polarity within the same active dimension is compared with its current selected/candidate representative; the resolver decides replacement, correction, conflict, or separation from the two structured Claims and their two raw Events. This keeps resolver work linear in Claims per dimension rather than quadratic.

### 8.5 State time order and proof closure

Code derives each ongoing Claim's `effective_state_time` in this order:

1. a resolved `HAS_TIME` role such as `valid_from`, `started_at`, or `current_after`;
2. its source Event's resolved occurrence/source time;
3. unknown.

When both Claims have resolved effective times, chronological order wins; equal times break by `sequence_index`, then `source_record_id`. When neither has resolved Time, `sequence_index` defines discourse order. When only one has resolved Time, code does not infer supersession from order alone: an explicit correction/replacement decision is required, otherwise the result is ambiguous or separate.

Resolver inputs are ordered by source sequence, so `new` and `old` mean later and earlier source records. Code rejects `new_replaces_old` if resolved effective times contradict that direction and the evidence does not explicitly express a correction or retrospective replacement.

A lifecycle edge does not make the historical Claim a selected facet member. A current supersession proof is the closed bundle:

```text
current Claim --SUPPORTS(support_role=selected)--> StateFacet
current Claim --SUPERSEDES/CORRECTS--> historical Claim
raw Event --ASSERTS--> each Claim
```

Both lifecycle endpoints must share `dimension_key`. The verifier may use this bundle for current validity while still allowing the historical Claim to SUPPORT a past-time query.

## 9. Minimal query frame

The online frame call returns:

```json
{
  "bindings": [
    {"id":"b1","s":"Melanie","p":"meet","o":"?x","t":null,"polarity":"positive","assertion":"asserted"},
    {"id":"b2","s":"?x","p":"occupation","o":"?answer","t":null,"polarity":"positive","assertion":"asserted"}
  ],
  "answer":"?answer",
  "operation":"lookup",
  "answer_mode":"extract",
  "state_mode":"history",
  "count_unit":null
}
```

Constraints:

```text
at most 4 bindings
at most 3 intermediate variables
operation: lookup | list | count | boolean
answer_mode: extract | compose
binding polarity: positive | negative | any
binding assertion: asserted | uncertain | non_asserted | any
state_mode: none | current | history | at_time
count_unit: occurrence | event | entity | value | stated_number | null
```

Each binding's `t` is either null, the corresponding time phrase from the question, or a variable such as `?answer` when Time is the requested slot. This uses the existing binding field; it does not add a time-answer mode. Intersection is represented by multiple bindings sharing the same answer variable. Comparison and open-domain composition questions use `answer_mode=compose` with every premise or operand represented by a binding. Neither case introduces another retrieval mode or a persisted derived-relation edge.

Frame failure does not trigger an LLM repair call. The fallback is the original question plus exact Entity anchors. It may retrieve diagnostic context, but answer readout proceeds only if code can still construct at least one valid binding; otherwise the result is unavailable.

## 10. Scope-Time-State retrieval v3

There is one v3 chain:

```text
Question
-> compact bindings
-> Scope routing
-> Event-first retrieval
-> attach Claims
-> scoped Claim completion when bindings are missing
-> Time/State validity
-> bounded binding-guided Entity joins
-> proposition verifier
-> operation readout
-> answer
```

This remains a Scope-Time-State chain. Scope supplies the retrieval prior, Time orders or rejects evidence, and State validates current persistent values. Claim is the typed proposition carried by an Event, not a fourth routing axis or a parallel answer source. Single-hop questions can stop on the Event-first path; Claim completion and typed joins activate only when the required proof is incomplete.

### 10.1 Atomic queries

The retriever keeps the original question and adds at most three binding queries. With one to three bindings, each gets its own query. With four bindings, the third and fourth are combined into the final retrieval query, while the verifier still retains all four bindings separately. The total is therefore always at most four atomic queries.

### 10.2 Scope routing

Exact Entity anchors reserve at most four specific Scopes. BM25 and optional dense retrieval fill the Scope set to `scope_top_k=14` using standard reciprocal-rank fusion:

```text
RRF(u) = sum(1 / (60 + rank_r(u)))
```

There is no custom cross-query mean, raw-score mixing, or benchmark-specific Scope boost.

### 10.3 Event-first seed

The first retrieval stage returns at most 18 Events. Each binding reserves two Event positions before the remaining positions are filled by RRF rank.

The Event index contains raw text, speaker/author aliases, normalized Time, and Scope. Retrieved Events deterministically attach their asserted Claims.

Event-first retrieval preserves single-hop candidate recall when Claim indexing or predicate retrieval is imperfect, but a raw Event alone does not bypass Claim/proof verification.

### 10.4 Scoped Claim completion

If attached Claims do not cover all bindings, the unresolved bindings query the Claim index inside the selected Scopes. The completion stage returns at most eight Claims total and reserves two per unresolved binding.

Every retrieved Claim must close through `ASSERTS` to a raw Event. Claim retrieval is not a global primary lane.

### 10.5 Time routing

Explicit temporal constraints partition candidates into:

```text
compatible > unknown > incompatible
```

Unknown Time lowers rank but is not filtered. Explicitly incompatible evidence is rejected. Final temporal readout uses only selected proof Times.

### 10.6 State routing

StateFacet is looked up by resolved owner Entity and predicate only when the query frame has `state_mode=current`.

At most four StateFacets are attached. StateFacet is a validity layer, never an independent retrieval lane. `history` and `at_time` questions use Claim/Event/Time and do not consult the current facet.

### 10.7 Typed joins

If proof bindings remain unresolved, expansion is allowed only through role-aware Claim arguments:

```text
Claim A -> Entity <- Claim B
```

The variable role must agree with the query frame. For example, `b1.o=?x` may bind to `b2.s=?x`.

Limits:

```text
maximum Claim-to-Claim joins: 2
maximum frontier Entities: 4
maximum new Claims per frontier: 3
```

`MENTIONS`, Scope hierarchy, Session, and Topic are not semantic expansion edges. A non-question Entity with graph degree above 32 is not expanded.

There is no PPR, community summary, unrestricted BFS, or hub-scoring formula.

### 10.8 Global backoff

Only an incomplete scoped proof triggers memory-wide Event backoff. Each unresolved binding may add up to four Events, with a global cap of eight. Backoff never crosses a Scope marked `is_hard_boundary=true`. Backoff Events re-enter their actual Scope and pass through the same Claim, Time, State, and verifier checks.

### 10.9 Complete list/count scan

Top-k retrieval never proves completeness. For `list` and `count`, once exact binding keys are available, code scans the inverted Claim postings for `(subject Entity, predicate_key, optional object key, polarity, assertion, Time)` across the entire `memory_id`. If the adapter exposes multiple hard Scope boundaries, the scan is exhaustive only when an exact question/source anchor selects the boundary; a semantic Scope guess cannot establish completeness.

Posting lists expose their total size. Code processes at most 256 matching Claims or intermediate exact-key join rows. If a required predicate has only a semantic retrieval match, a hard boundary is unresolved, or a posting/join total exceeds the cap, `coverage_truncated=true`. Otherwise the posting scan reports `exhausted=true`. The scan may inspect more Claims than the answer context contains; only selected proof Events enter the final prompt.

### 10.10 Binding unification

A Claim covers one binding only when all specified fields pass these deterministic rules:

- named subject/object Entities resolve to the exact graph Entity ID; a verified alias is only a route to that ID;
- named literal objects match their datatype-aware normalized literal exactly;
- variables unify on exact Entity IDs or normalized literal keys, and the same variable must keep one value across hops;
- `predicate_key` exactly matches the lexically normalized query predicate;
- binding polarity is `any` or exactly matches Claim polarity;
- binding assertion is `any` or exactly matches Claim `assertion_status`; uncertain and non-asserted Claims cannot support an ordinary `asserted` binding;
- explicit binding Time is compatible with Claim/Event Time;
- the Claim closes through `ASSERTS` to one raw Event.

BM25 and dense similarity are recall/ranking signals only; neither can independently turn a predicate mismatch into SUPPORT. A StateFacet path covers a binding through its selected Claim under the same rules. A raw Event without a covering Claim cannot satisfy a verifier binding.

### 10.11 Ranking and early stop

There is no weighted binding formula or four-level score threshold. Explicit Entity, object, polarity, assertion, and Time contradictions are hard rejects. Remaining proof paths use lexicographic ordering:

```text
complete required-binding coverage
covered binding count
exact subject/object agreement
valid Time/State
retrieval rank
fewer semantic joins
fewer raw Events
```

Scalar lookup and boolean questions stop when a complete non-conflicting proof is available. List and count operations do not stop after the first value.

## 11. Verification and readout

Each required proposition receives one verdict:

```text
SUPPORT
REFUTE
UNKNOWN
```

- `SUPPORT`: a complete binding-unified, provenance-closed, temporally compatible proof exists.
- `REFUTE`: a Claim matches subject, predicate, object, Time, and requested assertion status but has the opposite requested polarity; `CORRECTS` may refute only the exact corrected proposition; `SUPERSEDES` may refute an old value only for a current-state query after the transition.
- `UNKNOWN`: neither condition is proven.

`UNKNOWN` must never be treated as `REFUTE`.

Supersession does not refute that the old value was historically true. For `history` or `at_time`, the verifier evaluates the Claim against its own Time interval.

Readout rules:

| Readout case | Rule |
|---|---|
| lookup | all premises SUPPORT before reading the answer variable |
| boolean | SUPPORT -> yes, REFUTE -> no, UNKNOWN -> unavailable |
| list | each distinct value requires its own raw Event proof |
| count | use `count_unit`: distinct proof occurrences, Event IDs, Entity IDs, normalized values, or an explicit `stated_number` Claim |
| shared-answer intersection | the same value must be independently supported for every required entity |
| comparison | compare only operand values whose bindings are all SUPPORT; ties or missing operands return unavailable |
| composition | every premise binding must SUPPORT before the final answer model may derive an answer |

For `answer_mode=extract`, proof unification first produces candidate substitutions for `?answer`; the final model may not introduce a value, premise, or citation absent from that proof bundle. Direct Entity, literal, boolean, and count answers are read deterministically when possible.

For `answer_mode=compose`, the final model may derive a new answer from fully supported memory premises and general knowledge, but it may not invent another memory fact or cite an Event outside the proof bundle. The trace marks `answer_derivation=llm_composition`, and derived values are never written back into the graph. If any required premise is REFUTE or UNKNOWN, composition returns unavailable.

Every candidate generator returns both rows and an `exhausted` flag. `coverage_truncated=true` whenever an eligible Scope, Event, Claim, frontier, backoff, proof, or context set has more valid items than its hard cap. For list/count, the complete posting scan is authoritative for the domain it exhausts and supersedes earlier seed-cap uncertainty. Exact list/count completeness is allowed only when every generator still used by the final proof reports exhaustion. Context pruning must never drop a selected proof Event; if a complete proof itself exceeds the context cap, readout returns unavailable/incomplete instead of truncating the proof. An exact count is never emitted while `coverage_truncated=true`.

The final answer context is capped at eight Events for scalar questions and sixteen Events for list/count questions. Deterministic boolean/count readout may skip the answer LLM. Otherwise online LLM calls are capped at two: query frame and final answer.

## 12. Trace and diagnostics

Every query records:

```text
query_frame
atomic_queries
selected_scope_ids
seed_event_ids
attached_claim_ids
claim_completion_ids
posting_scan_totals
posting_scan_exhausted
state_facet_ids
semantic_paths
binding_verdicts
selected_proof_ids
answer_event_ids
answer_derivation
global_backoff_used
coverage_truncated
```

The trace must make Scope misses, Claim extraction misses, failed joins, verifier rejection, and answer-composition loss distinguishable.

## 13. Initial fixed budgets

```text
atomic_queries: 4
scope_top_k: 14
anchor_scope_reserve: 4
event_seed_top_k: 18
binding_event_reserve: 2
claim_completion_top_k: 8
exact_posting_scan_cap: 256
state_top_k: 4
frontier_entities: 4
claims_per_frontier: 3
max_claim_joins: 2
global_backoff_events: 8
scalar_context_events: 8
set_context_events: 16
```

The first A/B keeps Scope/Event budgets close to the frozen v2 run so graph, proof-chain, and top-k changes remain attributable. Budgets may be calibrated once on frozen cross-benchmark development slices and then frozen; they are not tuned per benchmark task type.

## 14. Validation invariants

The graph validator must enforce:

1. no dangling nodes or edges;
2. every Claim has exactly one `ASSERTS` source Event and one `HAS_SUBJECT` Entity;
3. entity-valued Claims have one `HAS_OBJECT`; literal-valued Claims have none;
4. every `ASSERTS.evidence_span` maps to its source Event;
5. every Claim Time is supported by a source span or Event anchor;
6. every `proposition_key` and `dimension_key` recomputes from normalized stored data;
7. a current StateFacet has exactly one selected Claim and deterministic state order;
8. an ambiguous StateFacet has no selected Claim and at least two candidate Claims;
9. every StateFacet support belongs to the same state dimension;
10. lifecycle edge endpoints belong to one state dimension and `basis_event_ids` exactly name their source Events;
11. canonical Entity merges never rely only on fuzzy or embedding similarity;
12. build hashes depend only on visible memory, v3 configuration, prompt, and builder version;
13. resolved v3 output paths and symlink targets cannot enter a protected v2/artifact root.

## 15. Testing and promotion gates

### 15.1 Contract tests

- ten-field extraction schema accepts valid output and rejects extra graph-owned fields;
- short Event handle whitelist and evidence-span validation;
- conjunction Entity non-merge regression;
- same-Event Claim deduplication;
- repeated-proposition provenance preservation;
- proposition/time key collision regressions;
- deterministic state ordering, state fold, and ambiguous pair fallback;
- StateFacet proof closure;
- standard RRF BM25-only fallback;
- Event-first early stop;
- scoped Claim completion and at most two typed joins;
- `UNKNOWN != REFUTE`;
- composition blocked by any REFUTE/UNKNOWN premise and never persisted into the graph;
- exact count blocked when coverage is truncated;
- exact posting-scan exhaustion and hard-boundary ambiguity;
- overflow retry that still exceeds the hard Claim cap fails build validation;
- graph/retrieval invariance under qtype, gold, or option mutation;
- protected-path rejection and before/after checksum-manifest equality.

### 15.2 `gpt-4o-mini` extraction smoke

Run a frozen 100-Event sample at temperature zero. Required initial gates:

```text
first-pass JSON parse rate >= 99%
Event handle validity = 100%
evidence-span validity >= 98%
repeat-run proposition consistency >= 95%
no silent Claim overflow
```

### 15.3 LoCoMo A/B

Start with `conv-26`, all 199 questions, and the exact named model `gpt-4o-mini`.

- single-hop and temporal Answer F1 may not regress by more than 1 percentage point;
- open-domain Answer F1 may not regress by more than 1 percentage point;
- multi-hop selected-evidence recall must exceed the frozen v2 result;
- unsupported non-abstaining adversarial answers must be at most 10%;
- every final answer value and citation must map to selected raw Events;
- semantic joins must never exceed two;
- online LLM calls must never exceed two per question.

The v3 method is not promoted over v2 until these gates pass.

## 16. Dead-code policy

The existing v2 implementation remains intact because it is a live baseline, not dead code.

Inside newly added v3 surfaces:

- do not copy unused v2 variants, prompts, options, or compatibility switches;
- when v3 logic is replaced during implementation, delete the replaced v3 code in the same change;
- keep LoCoMo wrappers thin and put shared behavior in `pipeline/sts_v3`;
- do not leave deprecated aliases or no-op flags for unimplemented behavior.

Implementation bugs do not authorize schema growth. The ten model fields, six node roles, typed edge set, compact query frame, and one retrieval chain remain frozen while implementing v3. A bug must first be fixed in an existing adapter, validation, materialization, index, retrieval, verifier, or readout layer, with the replaced v3 logic removed. If a reproducible case truly cannot be represented, implementation pauses and proposes the smallest cross-benchmark schema delta for explicit approval; it must not add a catch-all metadata blob, compatibility mode, or benchmark-specific field on its own.

## 17. Non-goals

The first v3 implementation does not include:

- migration of all external benchmarks;
- global PPR;
- community detection or summaries;
- unrestricted BFS;
- cross-encoder reranking;
- LLM-generated Scope or topic nodes;
- a fixed domain ontology;
- historical StateFacet nodes;
- a third online repair/verifier LLM call;
- mutation of benchmark datasets or gold contracts.

## 18. Completion definition

The first implementation is complete when:

1. the isolated v3 core and LoCoMo adapter exist at the specified paths;
2. the implementation commit contains no path under the preserved v2 code or artifact directories, and their checksum manifest is unchanged;
3. schema, retrieval, verifier, leakage, and version-isolation tests pass;
4. the 100-Event extraction smoke satisfies its gates;
5. a new `conv-26` v3 graph can be built into the dedicated output path;
6. a v3 QA smoke produces a complete trace without invoking any v2 runtime branch;
7. the exact full A/B command is documented, while the expensive full run remains an explicit execution step.

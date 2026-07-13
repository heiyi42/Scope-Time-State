# LoCoMo v3 State and Identity Repair Design

## Purpose

Repair the LoCoMo v3 graph builder so that `StateFacet` represents a resolved
persistent state rather than a mostly one-Claim-per-facet projection. Keep the
design inside the Scope-Time-State boundary: subject identity exists only to
identify the owner of a state, not to solve open-world entity resolution.

This is the first of two independent changes. It covers subject ownership,
semantic state grouping, state resolution, validation, and dead-code removal.
Time-role and absolute-time improvements are intentionally deferred to a
separate change after this design is implemented and verified.

## Current Failure

The current builder first canonicalizes raw `state_slot` labels, then partitions
Claims by that slot before the semantic state-group resolver runs. A false
negative in slot aliasing is therefore irreversible: related Claims never reach
the same resolver call. In the current artifacts this produces 85 persistent
Claims and 85 StateFacets for `conv-26`, and 126 persistent Claims and 124
StateFacets for `conv-42`.

The unfinished global subject reconciler is a separate regression. It expanded
state ownership into claim-level global entity disambiguation with qualifier
spans, internal cluster IDs, page reconciliation, and local ID namespaces. Its
protocol no longer matches four existing tests, and it does not prevent coarse
merges such as `Nate's pets` into `Nate`.

## Goals

1. Let semantically related persistent Claims reach the same final grouping
   pass even when their raw `state_slot` labels differ.
2. Keep different state dimensions separate even when they share a raw slot or
   topic.
3. Resolve subject ownership with the minimum identity machinery needed by STS.
4. Allow positive and negative values of one state dimension to be compared
   without collapsing them into one value.
5. Require complete, validated LLM assignments and preserve atomic graph writes.
6. Remove the subject and slot code that the new path replaces; do not retain a
   legacy fallback, compatibility switch, or second live implementation.
7. Preserve existing graph artifacts until the new implementation passes its
   complete test suite and is rebuilt into a new output directory.

## Non-Goals

- Open-world entity resolution or cross-conversation identity linking.
- Claim extraction redesign or Claim recall optimization.
- Time-role changes, new Time roles, or broader temporal grounding.
- A target merge percentage. Correct positive and negative fixtures are the
  acceptance criterion; consolidation is not optimized for its own sake.
- Silent truncation, lossy windows, or `latest Claim = current` fallback.

## Chosen Architecture

```text
grounded Claims
  -> minimal subject ownership
  -> high-recall temporary state candidate families
  -> family-local object identity
  -> final semantic slot/group/cardinality/value assignment
  -> final state buckets
  -> current-state resolution and explicit validity relations
  -> StateFacets
```

The temporary candidate family is not a canonical graph identity. It exists
only to give the final semantic resolver enough recall to recover from raw-slot
variation. The final resolver remains responsible for separating different
state dimensions.

## Subject Ownership

`canonical_subject` is the state owner supplied by grounded Claim extraction.
Subject resolution follows these rules:

1. Claims with the same normalized subject label receive the same deterministic
   owner ID without an LLM call.
2. When distinct labels exist, one bounded label-level LLM alias assignment may
   merge clear aliases such as `Caro` and `Caroline`, or `Melanie's kids` and
   `Melanie's children`.
3. The assignment is validated as a complete partition of the input labels and
   is applied to Claims only after the entire result passes validation.
4. An owner/possessed-entity guard rejects an assignment that merges a bare
   owner with a possessive entity, such as `Nate` with `Nate's pets`.
5. Exact-label homonyms are outside this layer. Claim extraction must provide a
   grounded qualified owner such as `coworker Alex` or `cousin Alex` when the
   conversation requires them to remain distinct.

The builder will not page, shard, or reconcile subject clusters globally.
There is no qualifier-span protocol or response-local subject namespace.

## Candidate Families

For each canonical subject, the builder creates temporary candidate families
across raw slot labels. The family assignment is intentionally high recall:
Claims that might describe the same state dimension should be placed together,
while clearly unrelated dimensions may be separated early.

Each family assignment receives Claim context, including raw slot, object,
answer span, full grounded evidence, memory kind, modality, polarity, and report
time. It must return every eligible persistent Claim exactly once. Family IDs
are temporary and must not appear in nodes, edges, canonical IDs, or graph
provenance.

Raw `state_slot` is evidence for the family decision, not a hard partition key.
The old slot-alias result is not retained as a fallback.

## Final Semantic State Assignment

Within each candidate family, one semantic assignment returns one or more final
groups. Every final group contains:

- `canonical_state_slot`
- `canonical_state_group_id`
- `state_cardinality`, exactly `single` or `multi`
- its complete member Claim IDs
- one `canonical_state_value_id` per member Claim
- family-local canonical object identity for each member Claim

The validator requires each input Claim to occur in exactly one final group,
each group ID to be unique within the subject, each member to have all required
canonical fields, and one cardinality declaration per final group. Results are
committed to Claims only after full validation.

The final resolver may merge different raw slots into one state dimension and
may split identical raw slots into different dimensions. Related-but-distinct
dimensions such as `screenplay_theme` and `screenplay_status` must remain
separate.

Positive and negative Claims may be members of the same final state group.
Polarity remains part of the canonical state-value key, so opposite assertions
cannot become support for the same value. Their lifecycle is resolved later by
an explicit `CORRECTS`, `SUPERSEDES`, or `CONFLICTS_WITH` relation when needed.

## Current-State Resolution

Final state buckets remain keyed by canonical subject, final state group, and
final state slot. The current-state resolver:

- merges Claims for the same canonical value into one StateFacet support set;
- permits multiple simultaneous values only for a `multi` group;
- emits exactly one current or ambiguous value for a `single` group;
- cannot keep a corrected or superseded Claim as the current primary;
- cannot hide a different value inside a support list;
- requires every non-current Claim to remain connected to a materialized state
  through an explicit validity relation;
- never defaults to the latest Claim when semantic resolution is incomplete.

## Large Inputs and Failure Semantics

The number 24 is not a semantic boundary. The repaired v3 path will not fail
merely because a family or state bucket contains more than 24 Claims.

The resolver receives the complete input whenever it fits the configured model
context. Its response must still cover every Claim without duplication. A build
fails only when the complete request cannot fit the model capacity, the provider
fails, or semantic validation remains incomplete after the configured retries.

The builder must never truncate a family, drop Claims, silently split an
equivalence class, or introduce paginated anchor reconciliation. Failures occur
before output replacement and preserve the prior graph directory.

## Validation and Atomicity

Validation remains fail closed at semantic boundaries:

- subject labels form a complete valid partition;
- candidate families cover every eligible persistent Claim exactly once;
- final groups cover every family member exactly once;
- all canonical state and object fields are nonempty and valid;
- final group cardinality is declared once and is internally consistent;
- StateFacet support lists and `SUPPORTS` edges agree exactly;
- obsolete and conflicting values obey explicit relation semantics;
- all Claim and StateFacet provenance remains grounded in source Events.

No partially validated assignment is written into Claim dictionaries. Graph
output continues to use staged sibling-directory writes and is replaced only
after full graph validation succeeds.

## Dead-Code Removal

The implementation removes the replaced subject machinery, including qualifier
constants and validation, claim-level subject assignment, global initial/batch/
page reconciliation, internal cluster IDs, local ID namespaces, subject shard
cache stages, and the `llm_global_subject_identity_reconciliation` provenance.

It also removes the old slot-representative/slot-alias/canonical-slot prepartition
path, its dedicated provenance names, and any tests that exist only to preserve
the rejected qualifier, pagination, or local-ID architecture.

Generic label and claim-ID assignment helpers may remain only when they still
have a live caller in the object or final semantic assignment path. Unused
helpers, imports, prompt builders, cache stages, and compatibility branches are
deleted in the same change.

## Test-Driven Acceptance

Production changes are implemented only after a failing regression test proves
the intended behavior. The required fixtures are:

1. Exact subject labels merge deterministically without an LLM call.
2. `Caro` and `Caroline` can merge through the label-level alias assignment.
3. `Nate` and `Nate's pets` cannot share a canonical subject ID, even if an LLM
   proposes the merge.
4. Grounded qualified owners such as `coworker Alex` and `cousin Alex` remain
   distinct.
5. Different raw slots describing one lifecycle enter the same final group and
   can produce an explicit supersession.
6. The same raw slot used for different state dimensions is split into separate
   final groups.
7. Related but different dimensions are not merged.
8. Multiple compatible values in a `multi` group remain separate current
   StateFacets.
9. Positive and negative values can share a group, cannot share one support
   value, and require a relation when one becomes obsolete.
10. More than 24 Claims are sent as a complete resolver input rather than
    rejected or truncated.
11. Missing, duplicated, or invalid assignments fail before any Claim mutation
    or output replacement.

All existing LoCoMo graph tests plus the new fixtures must pass. Acceptance is
based on fixture correctness and graph invariants, not on forcing a particular
aggregate consolidation rate.

## Artifact Verification

After the complete test suite passes, build `conv-26`, `conv-42`, and `conv-43`
with the requested `gpt-4o-mini` configuration into a new graph directory. Do
not overwrite the current v3 artifacts.

Audit the new artifacts for:

- Claim-to-StateFacet support-size distribution;
- multi-Claim semantic groups and their evidence;
- false merges across owners, objects, and state dimensions;
- explicit state `CORRECTS`, `SUPERSEDES`, and `CONFLICTS_WITH` relations;
- complete provenance and zero graph validation warnings.

The new graph is accepted only when these semantic checks agree with the golden
fixtures and manual evidence inspection. A higher merge rate alone is not
evidence of correctness.

## Deferred Time Change

The subsequent Time-specific design will separately address deterministic
grounding for uniquely resolvable expressions, role-aware weekday direction,
fronted lifecycle time phrases, and correct null semantics for unresolved
absolute time. None of those changes belong in this implementation.

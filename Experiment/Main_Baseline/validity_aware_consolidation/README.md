# Validity-Aware Consolidation

This baseline implements the STALE paper's CUPMem design for STAMB-State.
In Oracle-Facet runs it receives the scoped case stream and requested output slots.
In public End-to-End runs it is exposed as `validity_global_public` and
`validity_scope_routed_public`, where no hidden `output_slots`, gold states, or gold support are
available.

The implementation follows the paper structure:

- Typed temporal state schema `Omega = {(domain, local_slot)}` with single/multi cardinality.
- Write-side belief updating from state-relevant evidence spans into state-update candidates.
- The code exposes an unadjudicated candidate stream plus typed schema and affected-domain graph.
- The LLM readout performs local same-slot/same-domain update, topology-triggered stale-state
  search, and state adjudication into `KEEP`, `STALE`, `REPLACE`, or `UNKNOWN_CURRENT`.
- Constrained readout is therefore part of the LLM workflow, not a deterministic precomputed
  active/stale memory list.
- Public End-to-End readout free-identifies query-required current-state facets through the public
  JSON schema instead of assuming oracle output slots.

Synthetic CUPMem candidate IDs are only internal context. The benchmark runner must still return raw
STAMB event IDs as `support_event`, `support_events`, and `evidence_events`.

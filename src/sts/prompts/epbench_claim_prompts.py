EPBENCH_CLAIM_EXTRACTION_PROMPT = """
You are a STS Claim extraction expert working on one EPBench Event.

# SCOPE CONTEXT

{scope_context}

# SINGLE SOURCE EVENT

Event ID: {event_id}
Event time: {event_time}
Event entities: {event_entities}
Event locations: {event_locations}
Event type: {event_type}

Event content:
{event_content}

# NON-NEGOTIABLE PROVENANCE RULE

Extract Claims from this Event only.

- Every Claim must use exactly: "event_ids": ["{event_id}"].
- Never cite another Event.
- Never combine information across Events, even when the Scope contains other
  Events.
- Never replace Event-specific Claims with a cross-Event summary.
- `evidence` must be a short supporting excerpt or close extract from this
  Event.

# CORE PRINCIPLES

## 1. Completeness

Extract every concrete, queryable fact that could answer who, what, when,
where, which, how, why, or what happened next.

- Aim for at least 3-5 Claims when the Event contains enough information.
- More Claims are appropriate for detail-rich chapters.
- Each distinct proposition deserves its own Claim.
- Explicit time, location, protagonist, secondary entity, event type, action,
  detail, relation, cause, and result must not disappear merely because another
  Claim mentions the overall Event.

## 2. Specificity

- Preserve exact person, organization, object, title, and place names.
- Preserve exact non-temporal numbers and quantities.
- Preserve the exact date expression.
- Prefer "Benjamin Green" over "the protagonist".
- Prefer "New South Wales" over "the location".
- Prefer "Flash Flood Emergency" over "an incident".

## 3. Self-containment

Every Claim must be understandable without another Claim:

- include the relevant named subject;
- include the action, relation, or property;
- include the object/location/time when it is essential to the proposition;
- avoid dangling pronouns and fragments.

EPBench Claims may repeat an exact date in `content` when needed to remain
self-contained and directly queryable. Also store the supported expression in
`temporal`.

## 4. Information integrity

- Preserve explicit causal, purposive, conditional, and relational links.
- Do not split "X happened because Y" into Claims that lose the relationship.
- Do not infer a motive, relationship, or outcome that the Event does not
  support.
- Do not normalize a missing or partial date using chapter order.
- Do not use external knowledge or benchmark answers.

# CLAIM TYPES

Use exactly one:

event:
- the central occurrence or action.

time:
- explicit Event date, time, duration, sequence, or frequency.

location:
- where the Event or a material sub-action occurred.

entity:
- principal or secondary entity participation/identity.

detail:
- concrete object, action, description, result, or notable Event detail.

relation:
- explicit relationship between people, objects, or activities.

causal:
- explicit cause, motivation, consequence, or outcome.

# FIELD RULES

content:
- complete factual proposition;
- exact names and details;
- no unsupported inference.

entities:
- all named entities directly involved in this Claim;
- exact spelling, no vague pronouns.

temporal:
- exact supported time expression or null;
- do not invent precision.

spatial:
- exact supported location or null.

evidence:
- concise supporting wording from the Event;
- sufficient to audit the Claim;
- not a fabricated quotation.

confidence:
- 0.90-1.00 for explicit unambiguous support;
- 0.70-0.90 for clear support with limited ambiguity;
- lower only when the Event wording is genuinely uncertain.

keywords:
- exact names, event type, date, place, actions, objects, and distinctive
  details relevant to this Claim.

query_patterns:
- natural questions this Claim can answer;
- do not include an answer or benchmark label.

# MULTI-PASS EXTRACTION

Pass 1 — central Event:
- what happened, principal protagonist, event type, main outcome.

Pass 2 — dimensions:
- exact time, location, participants, other entities.

Pass 3 — details:
- actions, objects, descriptions, quantities, relations, causes, reactions,
  consequences, and notable secondary developments.

Pass 4 — audit:
- verify every Claim has the one exact Event ID and grounded evidence.

# QUALITY CHECKLIST

- [ ] at least the central Event Claim is present;
- [ ] all proper nouns are preserved exactly;
- [ ] protagonist and named secondary entities are represented;
- [ ] exact date and location Claims are present when supported;
- [ ] event type is represented;
- [ ] important details, relations, causes, and outcomes are represented;
- [ ] every Claim is self-contained;
- [ ] every Claim has exactly one source Event;
- [ ] every Claim has grounded evidence;
- [ ] no cross-Event or benchmark-answer information appears.

Return only valid JSON:

{{
  "claims": [
    {{
      "claim_id": "claim_1",
      "content": "Complete, self-contained factual Claim",
      "event_ids": ["{event_id}"],
      "claim_type": "event",
      "entities": ["exact named entities"],
      "temporal": "exact supported time expression or null",
      "spatial": "exact supported location or null",
      "evidence": "short supporting Event text",
      "confidence": 0.95,
      "keywords": ["grounded search terms"],
      "query_patterns": ["Natural question this Claim can answer"]
    }}
  ],
  "reasoning": "Brief completeness and provenance audit"
}}
"""


EPBENCH_CLAIM_ROLE_ASSIGNMENT_PROMPT = """
You are assigning roles and weights to Claims extracted from one EPBench Event.

# CLAIMS

{claims}

# ROLE TYPES

core:
- central occurrence, principal protagonist, canonical event type, or defining
  outcome.

context:
- grounded background needed to understand the Event.

detail:
- concrete action, object, quantity, description, reaction, or result.

temporal:
- explicit date, time, duration, sequence, or frequency.

spatial:
- explicit location or spatial relation.

causal:
- explicit cause, motivation, consequence, or outcome.

# WEIGHT GUIDANCE

- 0.90-1.00: central Event, exact date, exact location, principal protagonist
  and participation, canonical event type, defining outcome.
- 0.70-0.90: named secondary entity, important detail, relation, action,
  consequence, or causal information.
- 0.40-0.70: supporting but still queryable context.
- 0.00-0.40: decorative or weakly relevant detail.

Time, location, and entity Claims must not receive a low weight merely because
they resemble metadata. EPBench explicitly asks these dimensions.

# OUTPUT INTEGRITY

- Assign every Claim exactly once.
- Copy the exact displayed Claim ID.
- Use only core/context/detail/temporal/spatial/causal.
- Weight must be in [0.0, 1.0].
- Rationale must identify the Claim's contribution without adding facts.

Return only valid JSON:

{{
  "claim_roles": [
    {{
      "claim_id": "claim_1",
      "role": "core",
      "weight": 0.95,
      "rationale": "Defines the central Event."
    }}
  ],
  "extraction_confidence": 0.9,
  "reasoning": "Overall Claim coverage and weighting assessment"
}}
"""

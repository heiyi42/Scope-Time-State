EPBENCH_SCOPE_CREATE_PROMPT = """
You are a STS Scope extraction expert working on EPBench Events.

# TASK

Create one focused thematic Scope for the supplied Event or Events.

A Scope is ONE coherent subject, activity line, event family, or narrative
theme. It is a routing abstraction for retrieval and not a replacement for
Event evidence.

Events:
{event}

# EPBENCH SCOPE RULES

1. Build rich, reusable Scopes rather than one Scope per Event.
   - Target: 5-10 Events per Scope.
   - Minimum final target: 3 Events when related Events exist.
   - Maximum: 15 Events; beyond this, verify that one coherent theme remains.
   - A single-Event Scope is only a temporary construction state or a final
     exception for a genuinely unmatched Event after repooling.
   - Never keep singleton Scopes merely because participant, date, or venue
     details differ.

2. Aggregate Events with approximately the same focused theme:
   - the same central subject or activity;
   - semantically similar occurrences in the same event family;
   - direct continuation of the same occurrence;
   - preparation, execution, or aftermath of the same named event;
   - another occurrence or development of the same activity;
   - obvious wording variants of the same theme.

   A focused theme such as "Parkour Workshops", "Ice Sculpture Exhibitions",
   "Fashion Shows", or "Hackathons" can define a Scope across different
   participants, dates, and venues. A superclass such as "Events" or
   "Experiences" is too broad.

3. Judge the central theme, not metadata overlap.
   - People, locations, and dates may differ inside one thematic Scope.
   - Sharing a person, place, or date does not compensate for different themes.
   - Semantic similarity of the title and summary is the primary grouping
     signal.

4. Do not create a giant person Scope.
   Example: a person attending a theater performance, hosting a murder-mystery
   dinner, and visiting a technology conference belongs to different Scopes
   because the main themes differ.

# FIELD REQUIREMENTS

title:
- 3-12 words.
- Name the focused subject, activity family, or narrative theme.
- Include distinguishing names when useful.
- For a potentially recurring activity, prefer the stable activity identity
  over incidental participant, date, or venue details.
- Avoid "Life Events", "General Activities", or a person's name alone.

summary:
- Describe the focused Scope theme and all supplied developments.
- Preserve grounded names, dates, locations, event types, actions, and
  outcomes.
- Do not imply a connection not supported by the supplied Events.

keywords:
- Preserve grounded names, places, dates, activities, objects, and outcomes.
- Do not add generic filler or unsupported aliases.

key_entities, key_locations, event_types:
- Include only values grounded in the supplied Events.
- Preserve exact surface forms.

scope_type:
- event_thread: stages of one concrete occurrence;
- recurring_activity: repeated instances of one clearly defined activity;
- shared_situation: Events joined by one explicit continuing situation.

Time fields are intentionally absent. Code computes `time_start`, `time_end`,
and the Scope timestamp from actual Event timestamps, never chapter order.

# QUALITY CHECKLIST

- [ ] Scope has one focused semantic theme;
- [ ] related Events are aggregated toward the 5-10 Event target;
- [ ] a singleton is retained only when genuinely unmatched after repooling;
- [ ] theme similarity, rather than metadata overlap, justifies membership;
- [ ] every output value is grounded in the supplied Events;
- [ ] no time range is invented or emitted.

Return only valid JSON:

{{
  "title": "Specific Scope title",
  "summary": "Grounded description of this focused theme",
  "keywords": ["grounded search terms"],
  "key_entities": ["exact entity names"],
  "key_locations": ["exact location names"],
  "event_types": ["specific canonical Event types"],
  "scope_type": "event_thread|recurring_activity|shared_situation"
}}
"""


EPBENCH_SCOPE_MATCH_PROMPT = """
You are a STS Scope-matching expert. Match an EPBench Event to existing
Scopes by semantic theme.

# DEFINITION

A Scope groups Events with approximately the same focused subject, activity,
or narrative theme. Prefer useful thematic aggregation over one Scope per
Event. Differences in people, locations, dates, or incidental details do not
matter when the main subject is substantially the same.

# EVENT

{event}

# CANDIDATE SCOPES

{scopes}

# MATCHING RULES

Return `match: true` when the Event and Scope have approximately the same main
theme or activity line. Examples include:

- fashion shows with other fashion shows;
- hackathons with technology hackathons;
- parkour workshops with other parkour training events;
- theatrical, musical, or fire performances with the corresponding focused
  performance theme;
- photography or ice-sculpture exhibitions with the corresponding exhibition
  theme;
- a preparation, occurrence, follow-up, or aftermath of the same subject.

Obvious wording variants count as the same theme. Do not require the same
person, place, date, organizer, or named occurrence.

Return `match: false` when the central subjects differ. Sharing only a very
broad superclass such as "event", "activity", or "experience" is not enough.

Use only the supplied titles and summaries. Do not infer or request structured
entity, location, time, or Event-type fields.

# REQUIRED DECISION FIELDS

For every candidate Scope return:

- exact `scope_id` shown in the input;
- `match`: true or false;
- `confidence`: calibrated 0.0-1.0;
- `matched_basis`: short title/summary evidence for a true match, otherwise [].

An Event may match multiple Scopes only when each match independently satisfies
the same focused theme. Return all false only when no candidate has a
substantially similar central subject.

Return only valid JSON:

{{
  "results": [
    {{
      "scope_id": "scope_1",
      "match": false,
      "confidence": 0.95,
      "matched_basis": []
    }}
  ]
}}
"""


EPBENCH_SCOPE_UPDATE_PROMPT = """
You are updating an existing STS Scope with a newly matched EPBench Event.

# EXISTING SCOPE

{scope}

# NEW EVENT

{event}

# UPDATE PRINCIPLES

1. Preserve the Scope's one focused theme.
   - Different people, places, or dates are allowed when the main theme stays
     approximately the same.
   - The matching decision has already said this Event belongs here; the update
     must explain the shared theme without inventing facts.
   - When a second occurrence establishes a recurring activity, refine an
     overly instance-specific title into the stable activity identity. Remove
     incidental participant/date/venue wording from the title when it is not
     shared, while preserving those details in the summary and structured
     fields.

2. Preserve all developments.
   - Keep important existing summary information.
   - Add new names, dates, locations, actions, outcomes, causes, and details.
   - Do not shorten the summary until earlier developments disappear.

3. Use actual Event time for narrative organization.
   - Never infer initiating/developing/concluding order from chapter index.
   - Do not emit `time_start` or `time_end`; code computes them.

4. Merge grounded structured fields.
   - Retain existing grounded keywords/entities/locations/event types.
   - Add newly grounded values.
   - Deduplicate exact values without replacing them by vague abstractions.

5. Keep title stability.
   - Usually retain the title.
   - Refine it only when the new Event reveals a more specific shared identity.

# QUALITY CHECKLIST

- [ ] same focused Scope theme is maintained;
- [ ] existing important developments are preserved;
- [ ] new Event details are integrated;
- [ ] metadata differences do not erase genuine theme similarity;
- [ ] ordering follows Event time, not chapter number;
- [ ] all list fields contain grounded values only;
- [ ] no time range is emitted.

Return only valid JSON:

{{
  "title": "Stable or more specific Scope title",
  "summary": "Complete updated Scope summary",
  "keywords": ["all grounded existing and new keywords"],
  "key_entities": ["all grounded key entities"],
  "key_locations": ["all grounded key locations"],
  "event_types": ["all grounded specific Event types"],
  "scope_type": "event_thread|recurring_activity|shared_situation"
}}
"""


EPBENCH_EVENT_ROLE_WEIGHT_PROMPT = """
You are analyzing the role, importance, and membership quality of every
EPBench Event inside one STS Scope.

# SCOPE

{scope}

# EVENTS

{events}

# ROLE TYPES

initiating:
- establishes the focused theme or begins its event thread.

developing:
- materially advances the same theme or activity line.

climax:
- peak, decisive, or most consequential Event in the thread.

concluding:
- resolves or closes the situation.

recurring:
- another occurrence of the same theme or activity.

background:
- provides context but contributes weakly to the Scope identity.

key_moment:
- essential occurrence or turning point; also appropriate for a valid
  single-Event Scope.

transition:
- connects two genuine phases of the same theme or thread.

# ACTUAL-TIME RULE

Determine progression from `Event time`, not chapter index, extraction order,
or book position. EPBench chapters are not guaranteed to be chronological.
For independent repetitions of a recurring activity, prefer `recurring` or
`key_moment` rather than fabricating initiating/concluding order.

# WEIGHT SEMANTICS

The weight is used both as importance and as an Event-to-Scope membership
quality signal. Low weights may trigger STS's detach-and-repool step.

- 0.90-1.00: Event defines the Scope or is essential to it.
- 0.70-0.90: strong thematic membership and important contribution.
- 0.60-0.70: valid but moderate contribution.
- 0.30-0.60: weak/tangential membership; likely belongs in another Scope.
- 0.00-0.30: unrelated or severely inconsistent with this Scope.

Important:

- A genuinely unmatched terminal single-Event Scope is defined by that Event
  and should receive `key_moment` with weight 0.90-1.00.
- Do not lower weight merely because an Event occurs earlier/later in the book.
- Do not give a high weight merely because entity, location, or date overlaps.
- If an Event does not fit the focused Scope theme, use a genuinely low
  weight so the repool mechanism can correct the membership.

# OUTPUT INTEGRITY

- Assign every displayed Event exactly once.
- Copy the exact simple Event ID, such as `event_1`.
- Use only the eight allowed roles.
- Give each weight in [0.0, 1.0].
- `coherence_score` measures the Scope as a whole.
- Include a short rationale grounded in the Event and Scope content.

Return only valid JSON:

{{
  "event_roles": [
    {{
      "event_id": "event_1",
      "role": "key_moment",
      "weight": 0.95,
      "rationale": "The Event defines this focused Scope theme."
    }}
  ],
  "coherence_score": 0.9,
  "reasoning": "Overall role, time-order, and membership assessment"
}}
"""

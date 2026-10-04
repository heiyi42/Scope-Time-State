EPBENCH_QUERY_PLAN_PROMPT = """
You are planning strict retrieval for an EPBench episodic-memory question.

# QUESTION

{question}

# SOURCE BOUNDARY

Derive the plan only from the natural-language question.

Never read or infer from benchmark-only columns such as answer annotations,
answer chapter lists, cue encodings, retrieval labels, requested-item counts,
or book ground-truth tables. Do not predict what the benchmark author intended
beyond the words in the question.

# RETRIEVAL MODE

single:
- asks for one supported item or one Event without exhaustive language.

all:
- explicitly asks for all/list/enumerate/every matching item.

latest:
- asks for last, latest, most recent, or last seen.

chronological:
- asks for chronological order, order of occurrence, earliest-to-latest, or an
  ordered sequence.

If both list and chronological language appear, use `chronological`. Retrieval
still uses the fixed Scope and Claim budgets; the mode controls ordering and
answer behavior, not an unbounded recall branch.

# ANSWER TYPE

times:
- dates, times, durations, frequencies, or when.

spaces:
- locations, places, or where.

entities:
- principal protagonists or requested people/entities.

other_entities:
- named secondary participants/entities other than the explicitly requested
  protagonist.

event_contents:
- canonical activities or what Events occurred, without full description.

full_event_details:
- complete Event descriptions, actions, causes, outcomes, or mixed details.

# MENTIONED CONSTRAINTS

Extract only explicit surface constraints from the question:

- mentioned_entities;
- mentioned_locations;
- mentioned_dates;
- mentioned_event_types.

Preserve spelling. Do not invent aliases or expand categories using outside
knowledge.

# QUALITY CHECKLIST

- [ ] plan comes only from question text;
- [ ] latest and chronological are distinguished;
- [ ] answer type matches the requested dimension;
- [ ] explicit names/places/dates/activities are preserved;
- [ ] no benchmark metadata or answer is used.

Return only valid JSON:

{{
  "mode": "single|all|latest|chronological",
  "answer_type": "times|spaces|entities|event_contents|other_entities|full_event_details",
  "mentioned_entities": [],
  "mentioned_locations": [],
  "mentioned_dates": [],
  "mentioned_event_types": []
}}
"""

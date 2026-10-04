# Scope-based Claim Extraction Prompts

# ========== Claim Extraction Prompt ==========

CLAIM_EXTRACTION_PROMPT = """
You are an expert in extracting queryable claims from memory scopes.

Your task: Extract ALL claims, details, and information from the scope that could answer future queries. Prioritize COMPLETENESS and ACCURACY.

## SCOPE CONTEXT

Scope ID: {scope_id}
Title: {scope_title}
Summary: {scope_summary}

## ASSOCIATED EVENTS

{events_content}

## REFERENCE TIME

{reference_time}

Use this as the reference point for converting relative time expressions.

---

# CORE PRINCIPLES

## 1. Completeness
Extract EVERY queryable claim. When in doubt, extract it.
- Aim for 3-5+ claims per event
- Each distinct claim deserves its own entry

## 2. Specificity
Always prefer specific information over generalizations:
- Names over "someone/something"
- Exact titles over "a book/movie/song"
- Precise numbers over "some/several/many"
- In the temporal field, actual dates over vague time references

## 3. Self-Containment
Each claim should be independently understandable:
- Include WHO, WHAT, and WHERE when applicable
- A reader should understand the claim without needing other claims

## 4. Strict Temporal Separation
The content field must contain only the time-independent factual proposition.
- Do not put dates, clock times, weekdays, months, years, durations, frequencies,
  or relative time phrases such as "yesterday", "last week", or "two years ago"
  in content.
- Put ALL explicit and relative time information exclusively in temporal.
- Removing temporal from a claim must leave a grammatical, complete factual
  statement in content.
- If no time is stated or supported, temporal must be null.
- Do not duplicate temporal information in content, keywords, spatial, or
  query_patterns.

---

# EXTRACTION STRATEGY

**Pass 1 - Individual Claims**:
Extract all claims from each event independently.
- Each gets its source event_id
- These form the foundation - never skip them

**Pass 2 - Connected Claims (Supplement)**:
When claims across events are logically connected, create additional combined claims.
- These get multiple event_ids
- These SUPPLEMENT Pass 1, they don't replace it

**Example**:
```
Event_A: "Visited the gallery yesterday"
Event_B: "Bought a painting titled 'Evening Light' for $200"
Event_C: "The artist was named Elena"

Pass 1:
- content="The speaker visited the gallery", temporal="yesterday (resolved date)" [A]
- content="The speaker bought a painting titled 'Evening Light' for $200", temporal=null [B]
- content="The artist was named Elena", temporal=null [C]
Pass 2:
- content="The speaker bought 'Evening Light' by Elena at the gallery for $200",
  temporal="yesterday (resolved date)" [A,B,C]

Output: All 4 claims
```

---

# INFORMATION INTEGRITY

## Preserve Logical Connections
When claims have causal, conditional, or purposive relationships, preserve them:

- Wrong: "Started volunteering" + "Hometown was flooded" (split)
- Right: "Started volunteering because hometown was flooded" (connected)

## Rigorous Time Reasoning
When converting relative time expressions:
1. Identify the exact reference point (the date of the conversation/event)
2. Calculate precisely based on the reference
3. Preserve both the original phrase AND the calculated date in temporal only
4. Keep content free of both the original phrase and the calculated date

**Example** (reference: August 23, 2023):
```
Original: "I did this earlier this week"

Wrong content: "I did this earlier this week"
Wrong temporal: "in August 2023" (too vague)
Wrong temporal: "August 14-20" (that's LAST week, not THIS week)
Right content: "The speaker did this"
Right temporal: "earlier this week (around August 20-22, 2023)"
```

**Time phrase meanings**:
- "yesterday" = reference date minus 1 day
- "this week" = the week containing the reference date
- "last week" = the week before the reference week
- "earlier this week" = days before reference date within same week

## Preserve Exact Names and Titles
Proper nouns are critical for queries - never generalize them:
- Book/movie/song/game titles: keep exact title in quotes
- Person/pet/place names: keep exact names
- Organization/event names: keep exact names

---

# WHAT TO EXTRACT

**Always extract**:
- Named claims (people, places, organizations, titles)
- Actions and events with their participants
- Time information (dates, durations, frequencies)
- Quantities and measurements
- Relationships between people
- Items acquired, created, or shared
- Emotional states and reactions
- Reasons and motivations when stated

**Pay special attention to**:
- Content of photos/artworks shared (not just "shared a photo")
- Text on signs, labels, or messages
- Specific preferences stated ("favorite X is Y")
- Details that seem minor but are concrete

---

# QUALITY CHECKLIST

Before finalizing, verify:
- [ ] Every proper noun (name, title, place) is preserved exactly
- [ ] Every non-temporal number is captured in content
- [ ] Every date and time expression is captured only in temporal
- [ ] Relative time expressions include both relative and absolute forms in temporal
- [ ] Content contains no temporal expression or normalized date
- [ ] Causal relationships are preserved, not split
- [ ] Each claim is self-contained and understandable alone
- [ ] At least 3-5 claims per event

---

# OUTPUT FORMAT

Return JSON:
```json
{{
    "claims": [
        {{
            "claim_id": "claim_1",
            "content": "Complete time-independent factual claim",
            "event_ids": ["event_id_1"],
            "confidence": 0.95,
            "temporal": "yesterday (October 21, 2023)",
            "spatial": "location if applicable",
            "keywords": ["keyword1", "keyword2"],
            "query_patterns": ["Example query this could answer"]
        }}
    ],
    "reasoning": "Brief extraction strategy explanation"
}}
```

**Notes**:
- content: Store only the factual proposition. Never include or repeat temporal information here.
- temporal: Use format "relative_phrase (absolute_date)" when applicable
- temporal: Store every supported date, time, duration, frequency, and relative time phrase here; use null when absent
- spatial: Location/place information, null if not applicable
- Prioritize completeness - more claims is better than fewer
"""

# ========== Claim Role Assignment Prompt ==========

CLAIM_ROLE_ASSIGNMENT_PROMPT = """
You are an expert in analyzing the importance of extracted claims.

Your task: Assign a role and weight to each claim based on its contribution to representing the scope.

## SCOPE CONTEXT

Scope ID: {scope_id}
Title: {scope_title}
Summary: {scope_summary}

## EXTRACTED CLAIMS

{claims}

---

# ROLE TYPES

1. **core**: Essential information, central to the scope
   - Primary claims that define what happened
   - Most likely to be queried

2. **context**: Supporting information that enriches understanding
   - Background details and settings
   - Helps answer follow-up questions

3. **detail**: Specific claims or minor information
   - Precise details that answer "what exactly" questions
   - Still valuable for specific queries

4. **temporal**: Time-related information
   - When events happened
   - Durations and frequencies

5. **spatial**: Location-related information
   - Where events occurred
   - Physical or virtual places

6. **causal**: Cause-effect relationships
   - Why something happened
   - Consequences and impacts

---

# WEIGHT ASSIGNMENT

Weight range (0.0 - 1.0):
- 0.9-1.0: Critical, essential information
- 0.7-0.9: Important, significantly contributes
- 0.5-0.7: Moderately important
- 0.3-0.5: Specific detail
- 0.0-0.3: Tangential information

Note: Even "detail" role claims are valuable - specific claims often answer queries.

---

# OUTPUT FORMAT

Return JSON:
```json
{{
    "claim_roles": [
        {{
            "claim_id": "claim_1",
            "role": "core",
            "weight": 0.95,
            "rationale": "Brief explanation"
        }}
    ],
    "extraction_confidence": 0.9,
    "reasoning": "Overall explanation of role assignment"
}}
```
"""

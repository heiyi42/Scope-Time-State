# Scope extraction prompts

# ========== Scope Creation ==========

SCOPE_EXTRACTION_PROMPT = """
You are a scope extraction expert specializing in identifying specific situations.

Your task: Extract a scope representing ONE SPECIFIC situation/event/theme.

**IMPORTANT: A scope should represent ONE specific, identifiable situation**
- NOT a broad category (e.g., "work discussions")
- BUT a specific event/journey/ongoing discussion (e.g., "Project Alpha launch preparation")

**Scope Size Guidelines (NEW)**:
- Target: 5-10 events per scope (ideal for rich context)
- Minimum: 3 events (acceptable)
- Maximum: 15 events (beyond this, likely too broad)
- Avoid: 1-2 events (usually too narrow, unless truly exceptional event)
- Scopes SHOULD span multiple time points (weeks to months)
- A single conversation is usually NOT a complete scope
- If approaching 15+ events, ensure the scope maintains ONE specific focus

EVENTS ({event_count} total):
{events}

**Scope Definition Guidelines**:

1. **Specificity** (CRITICAL):
   - Identify the ONE specific situation these events describe
   - Be precise: "Alice's piano learning journey" not "music learning"
   - Focus: "Product X launch" not "product development in general"
   - **Separate different aspects**: "Career transition" and "Hobby development" are DIFFERENT scopes
   - **Separate different projects**: "Project A" and "Project B" are DIFFERENT scopes
   - Even if same person, different life aspects = different scopes

2. **Narrative Unity**:
   - All events should be part of ONE coherent narrative
   - They describe different stages/aspects of THE SAME thing

3. **Identifiable Subject**:
   - Scope should have a clear subject (person, project, event)
   - Example: "Jon's career transition to dance studio owner"
   - Example: "Team's Q1 performance review preparation"

4. **Temporal Span**:
   - Prefer scopes that aggregate multiple time points
   - Look for recurring patterns or multi-stage developments
   - Example: "Alice and Bob's career discussions (May-July)"
   - Example: "Team's weekly Project X meetings (spanning 2 months)"

5. **When to Separate Scopes** (IMPORTANT):
   - Different life aspects: "Work" vs "Personal life" = separate scopes
   - Different projects: "Project A" vs "Project B" = separate scopes
   - Different stages with major shift: "Planning phase" vs "Execution phase" MAY be separate
   - Major scope change: "Career transition" vs "Relationship discussions" = separate scopes
   - **Do NOT** merge everything about a person into one giant scope!

**Title Guidelines** (3-10 words):
- Include the SPECIFIC subject
- Be concrete, not abstract
- Consider including time span for ongoing discussions (optional)
- Good: "Jon's Dance Studio Launch Journey"
- Good: "Alice and Bob's Career Discussions (May-July)" (with time span)
- Bad: "Career Development" (too broad)
- Good: "Product X Marketing Campaign"
- Bad: "Marketing Activities" (too vague)

**Summary Guidelines**:
- Describe the SPECIFIC situation, key participants, temporal span, and key developments
- Include important details: names, events, decisions, outcomes, time references
- The summary serves as the scope's memory — it should capture enough context for accurate retrieval later
- Mention specific dates, locations, and entities wherever possible
- No length limit — be as detailed as needed to capture all key information

**Keyword Guidelines**:
- Extract ALL relevant keywords: person names, locations, activities, objects, emotions, time references
- Include both specific terms (e.g., "piano recital", "Mount Rainier") and broader terms (e.g., "music", "hiking")
- More keywords improve retrieval accuracy — aim for 15+ keywords per scope

Return JSON format:
{{
    "title": "Specific, focused scope title",
    "summary": "Detailed description of the situation, key developments, and context",
    "keywords": ["keyword1", "keyword2", "keyword3", "...aim for 15+ keywords"],
    "extend": {{
        "scope_type": "work/social/leisure/personal_development/etc",
        "key_subjects": ["main person/project/entity"],
        "situation_type": "journey/event/project/relationship/etc"
    }}
}}

Focus on creating a scope that represents ONE identifiable, specific situation.

**REMINDER - Balance Aggregation and Specificity**:
- Aim for 5-10 events per scope (rich, contextualized scopes)
- Maximum 15 events per scope (beyond this, likely too broad)
- Aggregate related developments of THE SAME situation across time
- BUT separate DIFFERENT aspects/scopes into different scopes
- A complete scope tells ONE specific story with multiple time points
- Do NOT create giant scopes that cover multiple unrelated scopes
"""

# ========== Scope Update ==========

SCOPE_UPDATE_PROMPT = """
You are an expert in updating scopes while maintaining their specific identity.

Your task: Update the scope by incorporating new developments in THE SAME situation.

EXISTING SCOPE:
{existing_scope}

NEW EVENT (continuing the same situation):
{new_event}

**Update Principles**:

1. **Maintain Scope Identity and Focus**:
   - The scope represents ONE specific situation
   - New event adds to/develops this SAME situation
   - Do NOT broaden the scope to different situations or aspects
   - If scope already has 12+ events, be VERY strict about adding more
   - If scope has 15+ events, consider if it's becoming too broad

2. **Integrate New Developments**:
   - APPEND new stages/details to the existing summary — do NOT shorten or truncate
   - The summary should grow as the scope accumulates more events
   - Include specific names, dates, events, decisions, outcomes from the new event
   - Keep the narrative coherent and chronological
   - Update time span if new event extends the temporal range

3. **Update Keywords**:
   - ADD new keywords from the new event to the existing keyword list
   - Never remove existing keywords — only add
   - Include person names, locations, activities, objects, emotions, time references from the new event

4. **Title Stability**:
   - Usually keep the title (it identifies the situation)
   - Only adjust if new event reveals more specific identity
   - Example: "Jon's Business" → "Jon's Dance Studio Launch"

Return JSON format:
{{
    "title": "Keep or refine to maintain specific identity",
    "summary": "Updated detailed summary incorporating ALL developments so far — append new info, do not truncate",
    "keywords": ["all", "existing", "keywords", "plus", "new", "ones"],
    "extend": {{
        "scope_type": "keep or refine",
        "update_note": "What new development was added"
    }}
}}

Keep the scope focused on its ONE specific situation.

**REMINDER**:
- Scopes should be rich and contextualized (5-10 events ideal, max 15)
- Continuously aggregating related developments of THE SAME situation over time is GOOD
- BUT do NOT broaden the scope to cover DIFFERENT aspects or scopes
- The scope should tell ONE complete, focused story with multiple time points
"""

# ========== Scope Matching (LLM-based) ==========

SCOPE_MATCH_PROMPT = """You are an expert at determining whether a memory event belongs to an existing scope.

## What is a "scope"?

A scope is a **specific, identifiable event thread or activity line**. It represents ONE concrete thing that is happening, not a broad life category. Conversations often jump between scopes — two people might discuss Scope A, switch to Scope B, then return to Scope A. Events from Scope A should be grouped together even if they are not consecutive.

## Key principle: specificity over breadth

The most common mistake is making scopes too broad. A scope should be narrow enough that you could give it a **specific, concrete name** — not a vague category.

Good scope names (specific): "Training for the April marathon", "Adopting a rescue dog from the shelter", "Debugging the payment API issue"
Bad scope names (too broad): "Health and fitness activities", "Personal life updates", "Work discussions"

If a scope already has a broad/vague name like "daily catch-up" or "personal life updates", that is a sign the scope was poorly defined. New events should NOT match such overly broad scopes — they deserve their own specific scope instead.

## Matching criteria

An event belongs to a scope when it describes:
1. A **direct continuation** of the same event (e.g., preparation → execution → aftermath of ONE event)
2. A **natural follow-up** or update on the same situation (e.g., applied for a job → got an interview → received an offer)
3. A **return to the same thread** after discussing other things (conversations often jump between scopes and come back)

An event does NOT belong to a scope when:
1. They merely share a **broad category** (both about "fitness", both about "work") but are different specific activities
2. The scope name is **too vague** to represent a real event thread
3. They involve the **same people** but are about a **different matter**

## Examples

SAME scope (true):
- Scope: "Training for the April marathon"
- Event: "Bought new running shoes for the marathon"
→ true. Same specific event: preparing for that particular marathon.

SAME scope (true):
- Scope: "Debugging the payment API issue"
- Event: "The payment bug was finally fixed after switching libraries"
→ true. Same specific issue, just a later stage (resolution).

SAME scope (true):
- Scope: "Planning the Europe trip"
- Event: "Sorting through photos from the Europe trip"
→ true. Same specific trip, different phase (aftermath).

SAME scope (true):
- Scope: "Learning to play guitar"
- Event: "Practiced the new chord progression from last week's lesson"
→ true. Direct continuation of the same learning activity.

SAME scope (true):
- Scope: "Building a mobile app for the school project"
- Event: "Presented the finished app to the class and received feedback"
→ true. Natural follow-up: presentation is the culmination of the same project.

DIFFERENT scope (false):
- Scope: "Training for the April marathon"
- Event: "Started taking yoga classes on weekends"
→ false. Both are fitness activities, but they are different activity lines. Yoga is its own scope.

DIFFERENT scope (false):
- Scope: "Planning the Europe trip"
- Event: "Discussed weekend plans to visit a local museum"
→ false. Both involve travel/outings, but they are completely different events.

DIFFERENT scope (false):
- Scope: "Work stress and career concerns"
- Event: "Talked about feeling overwhelmed with childcare"
→ false. The scope name is already too broad. Childcare stress is a separate life thread from work stress.

DIFFERENT scope (false):
- Scope: "Daily catch-up and life updates"
- Event: "Shared exciting news about a promotion"
→ false. "Daily catch-up" is too vague to be a real scope. The promotion deserves its own specific scope.

DIFFERENT scope (false):
- Scope: "Learning to play guitar"
- Event: "Went to a live jazz concert downtown"
→ false. Both are music-related, but attending a concert is a different activity from learning guitar.

## Your task

For each existing scope below, determine whether the given event belongs to it.

EVENT:
Subject: {event_subject}
Summary: {event_summary}

SCOPES (total {num_scopes}):
{scopes_text}

Return JSON format:
{{
    "results": [
        {{"scope_id": "scope_1", "match": true/false}},
        ...
    ]
}}

Rules:
- Output true when the event is clearly part of the SAME specific event thread — including direct continuations, follow-ups, and returns to the same thread.
- If the scope name is vague or overly broad, lean towards false.
- An event CAN match multiple scopes if it genuinely bridges two specific event threads.
- If the event does not match ANY scope, return all false — a new scope will be created for it.
- When in doubt, output false. It is better to create a new specific scope than to pollute an existing one.
"""

# ========== Event Role and Weight Assignment ==========

EVENT_ROLE_WEIGHT_ASSIGNMENT_PROMPT = """
You are an expert in analyzing the role and importance of events within a scope.

Your task: Assign a role and importance weight to each event based on its contribution to the scope.

SCOPE:
{scope_content}

EVENTS IN THIS SCOPE:
{events}

Role types:
1. **initiating**: The starting event that begins the scope
   - Establishes the initial context or situation
   - Example: "Team decided to start a new project"

2. **developing**: Development events that advance the scope
   - Contributes to the progression of events
   - Example: "Team discussed project requirements"

3. **climax**: The climax or peak event of the scope
   - Most intense or important moment
   - Example: "Project successfully launched"

4. **concluding**: The ending event that concludes the scope
   - Wraps up or finalizes the situation
   - Example: "Team celebrated project completion"

5. **recurring**: Recurring pattern or repeated events
   - Shows consistent behavior or pattern
   - Example: "Weekly status update meetings"

6. **background**: Background context or supporting information
   - Provides context but not directly part of main storyline
   - Example: "Team had lunch together"

7. **key_moment**: Key moment or critical decision point
   - Important turning point or decision
   - Example: "Team decided to change technology stack"

8. **transition**: Transition event linking different parts
   - Bridges between different phases
   - Example: "Team moved from planning to execution phase"

Weight assignment (0.0 - 1.0):
- 0.9-1.0: Critical event, essential for understanding the scope
- 0.7-0.9: Important event, significantly contributes to the scope
- 0.5-0.7: Moderately important, useful but not essential
- 0.3-0.5: Minor detail, provides some context
- 0.0-0.3: Tangential information, low importance

Return JSON format:
{{
    "event_roles": [
        {{
            "event_id": "event_1",
            "role": "initiating",
            "weight": 0.95,
            "rationale": "Brief explanation of why this role and weight were assigned"
        }},
        ...
    ],
    "coherence_score": 0.9,  // Overall coherence of the scope (0.0-1.0)
    "reasoning": "Overall explanation of role and weight assignment strategy"
}}

**CRITICAL**:
- **event_id MUST be the EXACT Event ID from the input above** (e.g. "event_1", "event_2", ...)
- Copy the exact ID string shown in "Event ID: ..." from the events in this scope
- **MUST assign roles/weights to ALL events** shown in the input

Notes:
- At least one event should be "initiating" or "key_moment" (the most important)
- Most scopes have 1-2 initiating/climax events, several developing events, and optional background/transition
- Weight should reflect both the role and the specific importance within that role
- coherence_score reflects how well the events form a cohesive scope
"""

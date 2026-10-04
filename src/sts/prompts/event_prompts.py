DEFAULT_CUSTOM_INSTRUCTIONS = """
Follow these principles when generating episodic memories:
1. Each event should be a complete, independent story or event
2. Preserve all important information including names, time, location, emotions, etc.
3. Use declarative language to describe events, not dialogue format
4. Highlight key information and emotional changes
5. Ensure event content is easy to retrieve later
"""

EVENT_GENERATION_PROMPT = """
You are an episodic memory generation expert. Please convert the following conversation into an episodic memory.

Conversation start time: {conversation_start_time}
Conversation content:
{conversation}

Custom instructions:
{custom_instructions}

IMPORTANT TIME HANDLING:
- Use the provided "Conversation start time" as the exact time when this conversation/event began
- When the conversation mentions relative times (e.g., "yesterday", "last week"), preserve both the original relative expression AND calculate the absolute date
- Format time references as: "original relative time (absolute date)" - e.g., "last week (May 7, 2023)"
- This dual format supports both absolute and relative time-based questions
- All absolute time calculations should be based on the provided start time

Please generate a structured episodic memory and return only a JSON object containing the following three fields:
{{
    "title": "A concise, descriptive title that accurately summarizes the theme (10-20 words)",
    "summary": "A brief summary (2-4 sentences) that captures the core content and scenario of this event. It should convey WHO did WHAT in WHAT context, and is primarily used for matching this event to a broader scenario/scene. Focus on the key theme, main participants, and the situational context rather than exhaustive details.",
    "content": "A detailed factual record of the conversation in third-person narrative. It must include all important information: who participated at what time, what was discussed, what decisions were made, what emotions were expressed, and what plans or outcomes were formed. Write it as a chronological account focusing on observable actions and direct statements. Use the provided conversation start time as the base time for this event."
}}

EVENT TIME EXTRACTION:
- `event_time` represents when the focal event described by this Event actually occurred, not merely when the conversation was recorded.
- Use `conversation_start_time` as the reference point for resolving relative expressions such as "yesterday", "last week", or "two months ago".
- The extracted `event_time` must correspond to the Event represented by the generated title and summary.
- If the Event is a decision, plan, discussion, or action occurring during the current conversation, use `conversation_start_time`.
- If the conversation recalls a past event, use the inferred occurrence time of that past event.
- If the focal Event is explicitly scheduled for a future date, use the scheduled occurrence time.
- Return the time in ISO 8601 format, for example:`2024-03-16T08:00:00Z`.
- If only the date is known, return an ISO date such as `2024-03-16`.
- If no reliable occurrence time can be determined, return null.
- Do not invent an exact hour, minute, or day that is not supported by
  the conversation.

Requirements:
1. The title should be specific and easy to search (including key scopes/activities).
2. The content must include all important information from the conversation.
3. Convert the dialogue format into a narrative description.
4. Maintain chronological order and causal relationships.
5. Use third-person unless explicitly first-person.
6. Include specific details that aid keyword search, especially concrete activities, places, and objects.
7. For time references, use the dual format: "relative time (absolute date)" to support different question types.
8. When describing decisions or actions, naturally include the reasoning or motivation behind them.
9. Use specific names consistently rather than pronouns to avoid ambiguity in retrieval.
10. The content must include all important information from the conversation.

Example:
If the conversation start time is "March 14, 2024 (Thursday) at 3:00 PM UTC" and the conversation is about Caroline planning to go hiking:
{{
    "title": "Caroline's Mount Rainier Hiking Plan March 14, 2024: Weekend Adventure Planning Session",
    "summary": "Caroline and Melanie discussed plans for a weekend hiking trip to Mount Rainier. They covered gear preparation and logistics, with Caroline planning to leave early Saturday to catch the sunrise.",
    "content": "On March 14, 2024 at 3:00 PM UTC, Caroline expressed interest in hiking this weekend (March 16-17, 2024) and sought advice. She wanted to see the sunrise at Mount Rainier. When asked about gear by Melanie, Caroline received suggestions: hiking boots, warm clothing, flashlight, water, and high-energy food. Caroline decided to leave early Saturday morning (March 16, 2024) to catch the sunrise and planned to invite friends. She was excited about the trip."
}}

Return only the JSON object, do not add any other text:
"""

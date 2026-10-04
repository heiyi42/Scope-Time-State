"""Prompts for post-clustering State presentation."""

STATE_CHRONOLOGICAL_SUMMARY_PROMPT = """You summarize one temporal State built from partially ordered Claim groups.

Write exactly one concise English sentence describing only the temporal
progression supported by the groups below.

Rules:
- Use all Claims as evidence; do not summarize only the first few.
- Preserve only explicitly supported relations between time groups.
- Claims in the same time group have no supported internal order.
- Do not infer causality from chronology.
- Compress repeated details, but retain material changes and the final outcome.
- Do not invent facts, motives, outcomes, or dates.
- Do not output a list or join Claims with arrows.
- Return JSON only: {{"summary": "..."}}.

Temporal Claim groups:
{grouped_claims}
"""

from __future__ import annotations

from pipeline.external.groupmembench.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    qtype="temporal",
    task_name="Temporal state facet extraction",
    scope_instruction=(
        "Anchor the Entity/Scope node to the project channel, phase, and topic for the requested date, deadline, or instruction."
    ),
    claim_instruction=(
        "Extract date, deadline, due-date, instruction-date, lock-date, and validation-date claims. Distinguish "
        "message timestamp from dates asserted in message content. If the question asks on what date someone was "
        "instructed or asked to do something, the relevant date is the occurred_at date of the instruction Event, "
        "not a later deadline or repeated current-state reminder."
    ),
    relation_instruction=(
        "Use SUPERSEDES when a later scoped claim changes an earlier date. Use CONFLICTS_WITH when two active-looking "
        "date claims cannot both be current."
    ),
    facet_instruction=(
        "Return a temporal StateFacet with CURRENT_AFTER set to the supporting event time. For instruction-date "
        "questions, the StateFacet value must be the occurred_at date of the supporting instruction Event."
    ),
    answer_instruction="Answer dates in the format requested by the question whenever the scoped evidence supports it.",
)

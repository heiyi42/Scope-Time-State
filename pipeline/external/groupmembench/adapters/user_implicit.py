from __future__ import annotations

from pipeline.external.groupmembench.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    qtype="user_implicit",
    task_name="User-implicit source anchored state resolution",
    scope_instruction=(
        "Anchor the Entity/Scope node to the project channel, phase, topic, and asking_user_id when the question uses "
        "I, me, my, or other first-person references."
    ),
    claim_instruction=(
        "Extract claims authored by, addressed to, or clearly referring to the asking user. Keep author/source evidence explicit."
    ),
    relation_instruction=(
        "Separate Event -[:MENTIONS]-> Entity from Event -[:IN_SCOPE]-> Scope. A mention of the asking user is not enough "
        "unless it supports the state being asked about."
    ),
    facet_instruction=(
        "Return user-anchored facets such as my_blocker, my_focus, my_needed_signoff, my_request, or my_responsibility."
    ),
    answer_instruction="Resolve first-person references through the source_anchor before answering.",
    source_anchor_required=True,
)


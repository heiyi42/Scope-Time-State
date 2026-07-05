from __future__ import annotations

from pipeline.external.groupmembench.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    qtype="term_ambiguity",
    task_name="Term ambiguity and entity normalization",
    scope_instruction=(
        "Anchor the Entity/Scope node to the project channel, phase, and topic even when the question uses a synonym "
        "or role alias for the entity."
    ),
    claim_instruction=(
        "Extract responsibility, ownership, status, deadline, and approval claims after normalizing role or team aliases."
    ),
    relation_instruction=(
        "Use MENTIONS edges for alias/entity mentions, but require IN_SCOPE plus claim support before a StateFacet is current."
    ),
    facet_instruction=(
        "Return facets such as responsibility, owner, status, freeze_status, deadline, or approval_rule."
    ),
    answer_instruction="Answer the normalized entity's state without being distracted by surface-form variation.",
    alias_normalization_required=True,
)


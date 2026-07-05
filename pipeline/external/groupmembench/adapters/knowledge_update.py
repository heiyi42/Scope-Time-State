from __future__ import annotations

from pipeline.external.groupmembench.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    qtype="knowledge_update",
    task_name="Knowledge update and current-state resolution",
    scope_instruction=(
        "Anchor the Entity/Scope node to the project channel, phase, and topic for the updated decision or current approach."
    ),
    claim_instruction=(
        "Extract old and new decision claims, current approach claims, scope changes, owner changes, status changes, "
        "and any explicit update language. For approval-scope questions, keep explicit widen/expand/include/fold-into-signoff "
        "claims separate from generic keep-as-is or simplification claims."
    ),
    relation_instruction=(
        "Prioritize Claim -[:SUPERSEDES]-> Claim and Claim -[:CORRECTS]-> Claim edges. A later update should not "
        "erase the historical event, but it can make the old claim non-current."
    ),
    facet_instruction=(
        "Return the current valid StateFacet after resolving stale or superseded claims. For approval-scope questions, "
        "the StateFacet value should describe the accepted approval boundary, not a generic project status. Preserve "
        "explicit scope-boundary qualifiers and tradeoffs when the supporting claims state them."
    ),
    answer_instruction="Answer with the current valid state, not the stale earlier claim.",
)

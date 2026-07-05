from __future__ import annotations

from pipeline.external.groupmembench.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    qtype="state_query",
    task_name="General state query",
    scope_instruction=(
        "Anchor the best matching Entity/Scope node for the state object named or implied by the question."
    ),
    claim_instruction=(
        "Extract candidate owner, date, status, rule, responsibility, scope, blocker, and decision claims that could "
        "directly answer the requested state."
    ),
    relation_instruction=(
        "Use SUPERSEDES, CORRECTS, or CONFLICTS_WITH only when scoped messages explicitly update, correct, or conflict "
        "with another claim."
    ),
    facet_instruction=(
        "Return an active StateFacet only when accepted current claims directly support the requested state; otherwise "
        "return an insufficient_evidence StateFacet."
    ),
    answer_instruction="Answer from active supported StateFacets; if the locked facet is insufficient_evidence, say no information is available.",
)

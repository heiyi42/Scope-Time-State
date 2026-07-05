from __future__ import annotations

from pipeline.external.groupmembench.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    qtype="multi_hop",
    task_name="Multi-hop state construction",
    scope_instruction=(
        "Anchor the Entity/Scope node to the project channel, phase, and topic named or implied by the question. "
        "The answer may require multiple scoped events."
    ),
    claim_instruction=(
        "Extract partial facts from multiple events when needed, including dates, owners, approvals, rules, "
        "requirements, blockers, and decision details."
    ),
    relation_instruction=(
        "Use SUPPORTS when several claims jointly support one StateFacet. Use SUPERSEDES, CORRECTS, or "
        "CONFLICTS_WITH only when the scoped messages explicitly indicate an update, correction, or incompatible claim."
    ),
    facet_instruction=(
        "Build a composed StateFacet whose support_events include every event required to answer the question."
    ),
    answer_instruction="Answer with the composed value only when all required scoped claims are supported.",
)


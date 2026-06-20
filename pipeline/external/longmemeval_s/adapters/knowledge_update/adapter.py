from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    question_type="knowledge-update",
    task_name="Knowledge update",
    task_instruction=(
        "Task focus: identify the latest valid user information after updates, corrections, or changed preferences. "
        "Prefer newer superseding information over stale earlier mentions when they conflict."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create current-state facets for the latest valid value and put stale or superseded claims in rejected_claims."
    ),
    evidence_instruction=(
        "Find both the earlier value and any later update, correction, changed preference, or revised fact. "
        "For conflicting snippets, keep their session dates so the answer stage can choose the latest valid value."
    ),
    answer_instruction=(
        "Choose the latest valid value supported by the evidence. "
        "If an earlier value is superseded by a later update, answer with the updated value and list the stale value in rejected_claims. "
        "Do not return the first value when a later correction or update is present."
    ),
)

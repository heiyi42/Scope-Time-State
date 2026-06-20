from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    question_type="single-session-user",
    task_name="Single-session user fact recall",
    task_instruction=(
        "Task focus: recall one specific fact stated by the user in one relevant session. "
        "Answer with the remembered user-side information, not with generic advice or unrelated assistant content."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create a facet for the queried user fact and cite only the session that directly states it."
    ),
    evidence_instruction=(
        "Find the session where the user directly states the queried fact. "
        "Prefer user turns over assistant paraphrases. Keep only snippets that explicitly contain the requested fact."
    ),
    answer_instruction=(
        "Answer with the exact remembered user-side fact. "
        "Do not add generic advice or information from unrelated assistant turns."
    ),
)

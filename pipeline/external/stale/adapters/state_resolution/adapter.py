from pipeline.external.stale.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    task_type="state_resolution",
    dim_key="dim1_query",
    response_key="dim1_response",
    meta_key="dim1_meta",
    task_name="State Resolution",
    task_instruction=(
        "Task focus: decide whether the earlier user state is still valid after later conversation evidence. "
        "Do not preserve an older memory when a later observation implicitly invalidates it."
    ),
    evidence_instruction=(
        "Find the earlier state-bearing statement, the later updated statement, and any evidence needed to infer "
        "that the old state is stale or no longer safe to use."
    ),
    answer_instruction=(
        "Answer the explicit state-validity question directly. If the old state is invalidated or uncertain after "
        "a later update, say so instead of treating it as current."
    ),
)

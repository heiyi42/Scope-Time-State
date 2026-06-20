from pipeline.external.stale.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    task_type="implicit_policy_adaptation",
    dim_key="dim3_query",
    response_key="dim3_response",
    meta_key="dim3_meta",
    task_name="Implicit Policy Adaptation",
    task_instruction=(
        "Task focus: perform a downstream recommendation or action while implicitly applying the user's updated "
        "state. The response must not follow stale constraints from the older memory."
    ),
    evidence_instruction=(
        "Find the current user state that should guide downstream behavior, plus any stale earlier state that must "
        "be rejected when forming the recommendation or action."
    ),
    answer_instruction=(
        "Give a directly useful downstream answer that is adapted to the updated state. Avoid generic responses and "
        "avoid recommendations that fit only the stale state."
    ),
)

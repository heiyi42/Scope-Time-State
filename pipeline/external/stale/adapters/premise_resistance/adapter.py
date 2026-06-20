from pipeline.external.stale.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    task_type="premise_resistance",
    dim_key="dim2_query",
    response_key="dim2_response",
    meta_key="dim2_meta",
    task_name="Premise Resistance",
    task_instruction=(
        "Task focus: detect and resist a user query that embeds an outdated premise from stale memory. "
        "The answer should not blindly comply with a premise that later evidence makes false."
    ),
    evidence_instruction=(
        "Find the stale premise in the question, the historical statement that once supported it, and the later "
        "conversation evidence that changes or invalidates that premise."
    ),
    answer_instruction=(
        "Politely correct or qualify the false premise before answering. Ground the response in the user's updated "
        "state rather than the outdated assumption."
    ),
)

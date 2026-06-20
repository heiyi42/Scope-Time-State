from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    question_type="temporal-reasoning",
    task_name="Temporal reasoning",
    task_instruction=(
        "Task focus: reason over session timestamps, dates mentioned inside turns, and temporal expressions relative to the question date. "
        "Perform any needed date arithmetic explicitly before giving the answer."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create facets for the relevant dated events, temporal constraints, and computed temporal relation."
    ),
    evidence_instruction=(
        "Find all sessions that mention the events, dates, intervals, or ordering constraints needed by the question. "
        "Capture the session date plus any date or time phrase inside the conversation. "
        "Keep all snippets needed for date arithmetic or chronological ordering."
    ),
    answer_instruction=(
        "Compute the temporal relation explicitly from the evidence dates before answering. "
        "For day, week, month, or ordering questions, derive the number or ordered sequence from the dated snippets. "
        "Do not answer I don't know when the required dates or ordered events are present in the evidence."
    ),
)

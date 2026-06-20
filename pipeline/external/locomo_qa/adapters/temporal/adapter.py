from pipeline.external.locomo_qa.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    category=2,
    question_type="temporal",
    task_name="Temporal dialog reasoning",
    task_instruction=(
        "Task focus: answer using session dates, event dates, ordering, recency, or temporal expressions in the conversation."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create facets for relevant dated events and the temporal relation or calculation used to answer."
    ),
    evidence_instruction=(
        "Find all dialog turns and session dates needed for date lookup, date arithmetic, ordering, or recency. "
        "Preserve both the dialog ID and the session date. "
        "For questions with an explicit calendar date, include sessions on that date and nearby sessions when a turn uses 'yesterday', "
        "'last week', or similar relative wording."
    ),
    answer_instruction=(
        "Use session dates and temporal phrases before returning the final short answer. "
        "If the question asks when something happened, answer with the most specific date supported by the evidence. "
        "If it asks for a month, return the month and year rather than a full date unless the evidence requires a range. "
        "When a turn is framed as 'last month' relative to a dated session, prefer that month-level frame for month questions."
    ),
)

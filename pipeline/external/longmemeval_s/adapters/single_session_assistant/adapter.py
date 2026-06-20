from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    question_type="single-session-assistant",
    task_name="Single-session assistant memory recall",
    task_instruction=(
        "Task focus: recall one specific fact, recommendation, schedule, artifact, or answer previously provided by the assistant. "
        "Answer with the assistant-side information from the relevant session."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create a facet for the prior assistant output and cite the session where that output was given."
    ),
    evidence_instruction=(
        "Find the session where the assistant previously gave the requested answer, recommendation, schedule, artifact, or description. "
        "Prefer assistant turns and keep the exact assistant-side detail needed to answer."
    ),
    answer_instruction=(
        "Answer with the previously provided assistant-side detail. "
        "If the question asks what was recommended, scheduled, named, or described, return that prior detail directly."
    ),
)

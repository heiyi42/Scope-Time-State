from pipeline.external.locomo_qa.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    category=4,
    question_type="single-hop",
    task_name="Single-hop dialog fact recall",
    task_instruction=(
        "Task focus: answer a direct question from one local fact in the conversation. "
        "Prefer the dialog turn that explicitly states the requested fact."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create a compact state facet for the queried fact and cite only the dialog IDs that directly support it."
    ),
    evidence_instruction=(
        "Find the smallest set of dialog turns that directly states the answer. "
        "Do not cite neighboring turns unless they are needed to disambiguate speaker, date, or referent."
    ),
    answer_instruction=(
        "Return a short phrase answer grounded in the cited dialog turn. "
        "Do not add outside knowledge or extra explanation."
    ),
)

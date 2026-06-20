from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    question_type="multi-session",
    task_name="Multi-session synthesis",
    task_instruction=(
        "Task focus: combine evidence from multiple sessions. "
        "Aggregate, compare, count, or synthesize every relevant fact before answering."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create one facet per contributing fact or partial count, then compose the final aggregate answer."
    ),
    evidence_instruction=(
        "Find every session that contributes a distinct item, count, comparison point, or partial fact needed by the question. "
        "Do not stop after the first matching session; multi-session questions often need several supporting sessions. "
        "For totals, money, elapsed time, counts, and lists, keep each contributing unit separately with its value and session ID. "
        "If a single snippet contains multiple contributing units, preserve each unit rather than summarizing it as one fact."
    ),
    answer_instruction=(
        "Combine all evidence snippets before answering. "
        "For counts, enumerate the contributing units first, deduplicate exact repeats, and then return the count. "
        "For money or time totals, list each amount or duration and then sum them. "
        "For questions that ask for items to pick up or return, count each pending pickup or return obligation; an exchange can involve both returning one item and picking up another. "
        "For project-leadership questions, count only projects the user explicitly led, is leading, or was responsible for; do not count a job title, team membership, or solo class work unless the evidence explicitly frames it as a led/currently leading project. "
        "For synthesis, include every required component rather than a partial answer."
    ),
)

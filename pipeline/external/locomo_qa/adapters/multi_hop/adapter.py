from pipeline.external.locomo_qa.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    category=1,
    question_type="multi-hop",
    task_name="Multi-hop dialog synthesis",
    task_instruction=(
        "Task focus: combine evidence across multiple dialog turns, sessions, speakers, or partial facts before answering."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, keep each contributing fact as a separate facet, then synthesize the final answer from those facets."
    ),
    evidence_instruction=(
        "Find every dialog turn that contributes a distinct fact, comparison, count, relation, or disambiguating clue. "
        "Do not stop after the first matching turn when the question needs synthesis. "
        "For questions containing 'both', 'share', or 'have in common', first identify the relation named by the question "
        "such as interests, plans, purchases, passed-away people, or life events, then collect only facts for that relation. "
        "If the question asks a broad commonality without naming a relation, prefer specific shared life events or states over "
        "generic shared hobbies or conversational topics. "
        "For 'which places/items/people' questions, collect the complete named set across sessions and keep specific names "
        "or models when the evidence provides them."
    ),
    answer_instruction=(
        "Combine all extracted evidence before answering. "
        "For comma-separated multi-answer golds, return the complete set of required short phrases, separated by commas. "
        "For comparison questions, answer the shared relation or state requested by the question rather than listing every "
        "topic both speakers mentioned. Prefer specific item/place/person names over generic labels, and avoid adding related "
        "but non-required facts that are not part of the requested set."
    ),
)

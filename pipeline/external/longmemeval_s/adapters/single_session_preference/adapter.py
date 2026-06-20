from pipeline.external.longmemeval_s.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    question_type="single-session-preference",
    task_name="Single-session preference-grounded response",
    task_instruction=(
        "Task focus: generate a personalized response using the user's remembered preference, tool choice, constraint, or setup. "
        "The final answer can be open-ended, but it must visibly use the relevant preference rather than giving a generic answer."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, create facets for the preference and any response constraints that should shape the recommendation."
    ),
    evidence_instruction=(
        "Find the user preference, tool choice, setup, constraint, or personal context that should personalize the response. "
        "Keep snippets that reveal the preference and any concrete constraints, not generic assistant advice. "
        "For broad recommendation questions, evidence is sufficient when it gives a transferable preference in the same category; "
        "do not require the previous session to mention the exact current city, date, or item named in the new question."
    ),
    answer_instruction=(
        "Generate a useful response that visibly uses the remembered preference or constraint. "
        "Do not ask a clarifying question or say there is no prior information when preference evidence exists. "
        "If exact current external options are not in the evidence, give preference-aligned categories, selection criteria, or examples instead. "
        "Avoid unrelated fallback interests; prioritize the strongest directly relevant preference facet. "
        "The answer does not need to repeat every snippet, but it must be clearly personalized and actionable."
    ),
)

from pipeline.external.locomo_qa.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    category=3,
    question_type="open-domain",
    task_name="Open-domain knowledge inference",
    task_instruction=(
        "Task focus: answer by combining conversation evidence with ordinary commonsense or open-domain world knowledge."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, separate remembered conversation facts from the open-domain inference used to bridge them."
    ),
    evidence_instruction=(
        "Find the dialog facts, observations, or session summaries that license the open-domain inference. "
        "Do not cite external knowledge as evidence; cite only conversation dialog IDs. "
        "Before selecting evidence, identify the answer type requested by the question: country, field of study, health condition, "
        "financial status, yes/no with reason, person, place, or activity. "
        "Include image-caption or image-search-query clues when they identify a place, object, country, brand, or activity. "
        "Reject evidence that supports a nearby topical inference but not the requested answer type."
    ),
    answer_instruction=(
        "Use ordinary commonsense or world knowledge only as a bridge from the cited conversation facts. "
        "Keep the answer concise, prefer canonical full names over abbreviations, and do not hallucinate new personal facts. "
        "Answer with the requested type, not with the raw clue: country questions need a country, health questions need a health-condition label, "
        "financial-status questions need a socioeconomic-status label, and field questions need study/career fields. "
        "For yes/no inference questions, include the short conversation-grounded reason after yes or no instead of returning "
        "only a bare polarity. For status, occupation, health, location, and identity questions, answer the requested "
        "category label or entity rather than a loosely related observation. "
        "For country questions, return the full country name and mirror a leading preposition when the question asks 'in what country'."
    ),
)

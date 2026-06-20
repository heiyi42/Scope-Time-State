from pipeline.external.locomo_qa.adapters.base import TaskAdapter


ADAPTER = TaskAdapter(
    category=5,
    question_type="adversarial",
    task_name="Adversarial false-premise detection",
    task_instruction=(
        "Task focus: detect false premises, wrong-speaker substitutions, and facts that are not mentioned for the entity in the question."
    ),
    scope_time_state_instruction=(
        "For Scope-Time-State, put contradicted or wrong-entity claims in rejected_claims and answer with abstention when needed."
    ),
    evidence_instruction=(
        "Find dialog turns that expose why the question is unanswerable, contradicted, or assigned to the wrong speaker. "
        "Preserve the true speaker and dialog ID for any misleading fact. "
        "If the question asks what a person realized, did, said, or planned, include the exact dialog turn containing that tempting fact "
        "when it belongs to a different person or is otherwise not valid for the question subject. "
        "Check exact entity names: a fact about a different named person is contradiction evidence, not answer evidence. "
        "For what/which questions, do not treat an unnamed category repeated from the question as a sufficient answer."
    ),
    answer_instruction=(
        "This LoCoMo category is an abstention task. Unless the extracted evidence directly establishes the requested "
        "fact for the exact subject in the question, put exactly \"No information available\" in the answer field. "
        "Do not replace a false premise with a related true fact, and do not answer with a tempting fact that belongs "
        "to another speaker, date, or event. For what/which questions, abstain if evidence only confirms that a broad "
        "category exists but does not name the requested specific value."
    ),
)

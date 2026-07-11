"""LoCoMo's official QA scoring semantics from task_eval/evaluation.py."""

from __future__ import annotations

from collections import Counter
import re
import string
from typing import List, Sequence


def normalize_answer(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace(",", "").lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\b(a|an|the|and)\b", " ", text)
    return " ".join(text.split())


def stem_tokens(tokens: Sequence[str]) -> List[str]:
    try:
        from nltk.stem import PorterStemmer
    except ImportError:
        return list(tokens)
    stemmer = PorterStemmer()
    return [stemmer.stem(token) for token in tokens]


def token_f1(prediction: object, ground_truth: object) -> float:
    prediction_tokens = stem_tokens(normalize_answer(prediction).split())
    ground_truth_tokens = stem_tokens(normalize_answer(ground_truth).split())
    if not prediction_tokens or not ground_truth_tokens:
        return 0.0
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(prediction_tokens)
    recall = num_same / len(ground_truth_tokens)
    return 2 * precision * recall / (precision + recall)


def multi_answer_f1(prediction: object, ground_truth: object) -> float:
    predictions = [item.strip() for item in str(prediction).split(",")]
    ground_truths = [item.strip() for item in str(ground_truth).split(",")]
    if not predictions or not ground_truths:
        return 0.0
    return sum(max(token_f1(candidate, gold) for candidate in predictions) for gold in ground_truths) / len(ground_truths)


def official_qa_f1(category: int, prediction: str, ground_truth: str) -> float:
    if category == 3:
        ground_truth = ground_truth.split(";", 1)[0].strip()
    if category == 1:
        return multi_answer_f1(prediction, ground_truth)
    if category in {2, 3, 4}:
        return token_f1(prediction, ground_truth)
    if category == 5:
        lowered = prediction.lower()
        return 1.0 if "no information available" in lowered or "not mentioned" in lowered else 0.0
    raise ValueError(f"unsupported LoCoMo category={category}")

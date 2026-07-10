from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from dateutil import parser as date_parser
from openai import OpenAI


BASELINE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASELINE_DIR.parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import provider_config  # noqa: E402


PROMPT_VERSION = "locomo-semantic-equivalence-v2"
ABSTENTION_RE = re.compile(r"no information available|not mentioned in the conversation", re.IGNORECASE)
MONTH_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}
TASK_ORDER = ("single-hop", "multi-hop", "temporal", "open-domain", "adversarial")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Semantically rescore completed LoCoMo QA baseline results.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--input-glob", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--judge-model", default="gpt-4o-mini")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--verify-equivalents", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def clean_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"^(?:on|the)\s+", "", text)
    return re.sub(r"\s+", " ", text).strip(" .")


def parse_absolute_dates(value: object) -> Set[date]:
    text = clean_text(value)
    if not re.search(r"\b(?:19|20)\d{2}\b", text):
        return set()
    date_shape = (
        rf"(?:\d{{1,4}}[-/.]\d{{1,2}}(?:[-/.]\d{{1,4}})?|"
        rf"\d{{1,2}}\s+{MONTH_RE}\s+(?:19|20)\d{{2}}|"
        rf"{MONTH_RE}\s+\d{{1,2}}(?:,)?\s+(?:19|20)\d{{2}})"
    )
    if not re.fullmatch(date_shape, text, re.IGNORECASE):
        return set()
    parsed: Set[date] = set()
    for day_first in (False, True):
        try:
            parsed.add(date_parser.parse(text, dayfirst=day_first, yearfirst=True, fuzzy=False).date())
        except (OverflowError, ValueError):
            continue
    return parsed


def parse_date_constraint(value: object) -> Optional[Tuple[str, Set[object]]]:
    text = clean_text(value)
    text = re.sub(r"^(?:around|approximately|about)\s+", "", text)
    absolute = parse_absolute_dates(text)
    if absolute:
        return "day", set(absolute)

    month_year = re.fullmatch(rf"({MONTH_RE})\s+((?:19|20)\d{{2}})", text, re.IGNORECASE)
    if month_year:
        try:
            parsed = date_parser.parse(text, fuzzy=False)
            return "month", {(parsed.year, parsed.month)}
        except ValueError:
            return None

    year_month = re.fullmatch(r"((?:19|20)\d{2})[-/.](\d{1,2})", text)
    if year_month and 1 <= int(year_month.group(2)) <= 12:
        return "month", {(int(year_month.group(1)), int(year_month.group(2)))}

    if re.fullmatch(r"(?:19|20)\d{2}", text):
        return "year", {int(text)}

    weekday_relative = re.fullmatch(
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(before|after)\s+(.+)",
        text,
    )
    if weekday_relative:
        bases = parse_absolute_dates(weekday_relative.group(3))
        resolved: Set[date] = set()
        target = WEEKDAYS[weekday_relative.group(1)]
        for base in bases:
            if weekday_relative.group(2) == "before":
                delta = (base.weekday() - target) % 7 or 7
                resolved.add(base - timedelta(days=delta))
            else:
                delta = (target - base.weekday()) % 7 or 7
                resolved.add(base + timedelta(days=delta))
        return ("day", set(resolved)) if resolved else None

    relative = re.fullmatch(r"(day|week)\s+(before|after)\s+(.+)", text)
    if relative:
        bases = parse_absolute_dates(relative.group(3))
        days = 1 if relative.group(1) == "day" else 7
        sign = -1 if relative.group(2) == "before" else 1
        resolved = {base + timedelta(days=sign * days) for base in bases}
        return ("day", set(resolved)) if resolved else None

    few_days = re.fullmatch(r"(?:a\s+)?few\s+days\s+(before|after)\s+(.+)", text)
    if few_days:
        bases = parse_absolute_dates(few_days.group(2))
        sign = -1 if few_days.group(1) == "before" else 1
        resolved = {base + timedelta(days=sign * offset) for base in bases for offset in (2, 3, 4)}
        return ("day", set(resolved)) if resolved else None
    return None


def date_equivalent(gold: object, prediction: object) -> bool:
    gold_constraint = parse_date_constraint(gold)
    prediction_constraint = parse_date_constraint(prediction)
    if not gold_constraint or not prediction_constraint:
        return False
    gold_precision, gold_values = gold_constraint
    prediction_precision, prediction_values = prediction_constraint
    if gold_precision == prediction_precision:
        return bool(gold_values & prediction_values)
    if gold_precision == "year" and prediction_precision in {"month", "day"}:
        prediction_years = {
            value[0] if isinstance(value, tuple) else value.year for value in prediction_values
        }
        return bool(gold_values & prediction_years)
    if gold_precision == "month" and prediction_precision == "day":
        prediction_months = {(value.year, value.month) for value in prediction_values if isinstance(value, date)}
        return bool(gold_values & prediction_months)
    return False


def normalize_numbers(value: object) -> str:
    text = clean_text(value)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [NUMBER_WORDS.get(token, token) for token in text.split() if token not in {"a", "an", "the"}]
    return " ".join(tokens)


def number_format_equivalent(gold: object, prediction: object) -> bool:
    normalized_gold = normalize_numbers(gold)
    normalized_prediction = normalize_numbers(prediction)
    return (
        bool(normalized_gold)
        and normalized_gold == normalized_prediction
        and clean_text(gold) != clean_text(prediction)
        and any(character.isdigit() for character in normalized_gold)
    )


def deterministic_judgment(row: Mapping[str, object]) -> Optional[Dict[str, object]]:
    answer_f1 = float(row.get("answer_f1") or 0.0)
    hypothesis = str(row.get("hypothesis") or "")
    if str(row.get("question_type")) == "adversarial":
        is_correct = answer_f1 >= 1.0 or bool(ABSTENTION_RE.search(hypothesis))
        return {
            "label": "equivalent" if is_correct else "wrong",
            "reason": "adversarial_abstention" if is_correct else "adversarial_not_abstained",
            "confidence": "high",
            "source": "deterministic",
        }
    if answer_f1 >= 1.0:
        return {
            "label": "equivalent",
            "reason": "official_f1_exact",
            "confidence": "high",
            "source": "deterministic",
        }
    if ABSTENTION_RE.search(hypothesis):
        return {
            "label": "wrong",
            "reason": "abstained_with_available_gold",
            "confidence": "high",
            "source": "deterministic",
        }
    gold = row.get("gold_answer")
    if date_equivalent(gold, hypothesis):
        return {
            "label": "equivalent",
            "reason": "date_format_or_granularity",
            "confidence": "high",
            "source": "deterministic",
        }
    if number_format_equivalent(gold, hypothesis):
        return {
            "label": "equivalent",
            "reason": "number_format",
            "confidence": "high",
            "source": "deterministic",
        }
    return None


def cache_key(row: Mapping[str, object], model: str) -> str:
    payload = {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "question": row.get("question"),
        "gold_answer": row.get("gold_answer"),
        "hypothesis": row.get("hypothesis"),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_cache(path: Path) -> Dict[str, Dict[str, object]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    return {str(key): dict(value) for key, value in payload.items() if isinstance(value, dict)}


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def judge_system_prompt() -> str:
    return """You are a strict LoCoMo QA answer-equivalence judge.
Classify each prediction against the question and gold answer:
- equivalent: it fully supplies every fact, entity, item, relation, polarity, and temporal constraint required by the gold answer. Accept date/number formatting, inflection, concise answers, synonyms, reordered complete lists, and harmless restatement.
- partial: it has at least one correct requested fact but omits a gold item/detail, is too broad or too narrow, or mixes a correct answer with unsupported alternatives.
- wrong: it answers a different fact, contradicts the gold, or has no material correct answer.

Hard constraints:
1. For questions asking multiple items, every gold item must appear semantically for equivalent. One matching item is partial.
2. Extra alternative items not supported by gold make the answer partial, not equivalent.
3. A more specific date is equivalent to a gold year/month only when it is within that year/month. A less specific prediction is partial.
4. Do not infer facts beyond the question and gold answer.
5. Judge answer correctness, not wording overlap.

Choose one reason from: concise_paraphrase, synonym, complete_list_reorder, specificity, partial_list, mixed_extra_facts, different_fact, contradiction, other.
Return JSON only: {"items":[{"id":"...","label":"equivalent|partial|wrong","reason":"...","confidence":"high|medium|low","note":"brief"}]}.
Return exactly one result for every input id."""


def call_judge_batch(
    batch: Sequence[Tuple[str, Mapping[str, object]]],
    api_key: str,
    api_base: str,
    model: str,
) -> Dict[str, Dict[str, object]]:
    client = OpenAI(api_key=api_key, base_url=api_base, timeout=180, max_retries=2)
    items = [
        {
            "id": key,
            "question_type": row.get("question_type"),
            "question": row.get("question"),
            "gold_answer": row.get("gold_answer"),
            "prediction": row.get("hypothesis"),
        }
        for key, row in batch
    ]
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": judge_system_prompt()},
                    {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=4096,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
            results: Dict[str, Dict[str, object]] = {}
            for item in parsed.get("items", []):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                label = str(item.get("label") or "").strip().lower()
                if label not in {"equivalent", "partial", "wrong"}:
                    continue
                results[str(item["id"])] = {
                    "label": label,
                    "reason": str(item.get("reason") or "other"),
                    "confidence": str(item.get("confidence") or "medium"),
                    "note": str(item.get("note") or ""),
                    "source": "gpt-4o-mini-judge",
                }
            missing = [key for key, _ in batch if key not in results]
            if missing:
                if len(batch) == 1:
                    raise ValueError(f"judge omitted the requested id: {missing[0]}")
                missing_set = set(missing)
                for missing_key, missing_row in batch:
                    if missing_key not in missing_set:
                        continue
                    results.update(
                        call_judge_batch(
                            [(missing_key, missing_row)],
                            api_key=api_key,
                            api_base=api_base,
                            model=model,
                        )
                    )
            return results
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"semantic judge batch failed: {last_error}")


def verifier_system_prompt() -> str:
    return """You are the final, conservative verifier for LoCoMo QA answer equivalence.
The preliminary judge marked each prediction as fully equivalent. Recheck it from scratch.

Return equivalent only when the prediction contains every requested gold fact, item, entity, relation, polarity, and temporal constraint, with no contradictory or unsupported alternative facts.
- If a list has three gold items and the prediction supplies one or two, return partial.
- Reordered complete lists are equivalent.
- Date and number formatting differences are equivalent only when they express the same value.
- A concise answer is equivalent only when it directly entails the whole gold answer.
- Do not use outside knowledge or invent missing details.

Return JSON only: {"items":[{"id":"...","label":"equivalent|partial|wrong","reason":"...","confidence":"high|medium|low","note":"brief"}]}.
Return exactly one result for every input id."""


def call_verifier_batch(
    batch: Sequence[Tuple[str, Mapping[str, object]]],
    api_key: str,
    api_base: str,
    model: str,
) -> Dict[str, Dict[str, object]]:
    client = OpenAI(api_key=api_key, base_url=api_base, timeout=180, max_retries=2)
    items = [
        {
            "id": key,
            "question_type": row.get("question_type"),
            "question": row.get("question"),
            "gold_answer": row.get("gold_answer"),
            "prediction": row.get("hypothesis"),
        }
        for key, row in batch
    ]
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": verifier_system_prompt()},
                    {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=4096,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
            results: Dict[str, Dict[str, object]] = {}
            for item in parsed.get("items", []):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                label = str(item.get("label") or "").strip().lower()
                if label not in {"equivalent", "partial", "wrong"}:
                    continue
                results[str(item["id"])] = {
                    "label": label,
                    "reason": str(item.get("reason") or "other"),
                    "confidence": str(item.get("confidence") or "medium"),
                    "note": str(item.get("note") or ""),
                    "source": "gpt-4o-mini-verifier",
                }
            missing = [key for key, _ in batch if key not in results]
            if missing:
                raise ValueError(f"verifier omitted {len(missing)} ids")
            return results
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"semantic verifier batch failed: {last_error}")


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [float(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def summarize_rows(rows: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    labels = Counter(str(row["semantic_label"]) for row in rows)
    return {
        "n_cases": len(rows),
        "official_answer_f1": mean(float(row.get("official_answer_f1") or 0.0) for row in rows),
        "official_bleu1": mean(
            None if row.get("official_bleu1") is None else float(row["official_bleu1"]) for row in rows
        ),
        "J": mean(1.0 if row["semantic_correct"] else 0.0 for row in rows),
        "equivalent": labels.get("equivalent", 0),
        "partial": labels.get("partial", 0),
        "wrong": labels.get("wrong", 0),
    }


def write_csv(path: Path, headers: Sequence[str], records: Sequence[Mapping[str, object]]) -> None:
    lines = [",".join(headers)]
    for record in records:
        values: List[str] = []
        for header in headers:
            value = record.get(header)
            if value is None:
                values.append("")
            elif isinstance(value, float):
                values.append(f"{value:.6f}")
            else:
                values.append(str(value))
        lines.append(",".join(values))
    path.write_text("\n".join(lines) + "\n")


def load_result_rows(patterns: Sequence[str]) -> Tuple[List[Dict[str, object]], List[str]]:
    paths = sorted({path for pattern in patterns for path in glob.glob(pattern)})
    if not paths:
        raise FileNotFoundError(f"no result files matched: {patterns}")
    rows: List[Dict[str, object]] = []
    for path in paths:
        payload = json.loads(Path(path).read_text())
        result_items = payload.get("results") or []
        if len(result_items) != 1:
            raise ValueError(f"expected one variant in {path}, got {len(result_items)}")
        for source_row in result_items[0].get("rows") or []:
            row = dict(source_row)
            row["source_result"] = path
            rows.append(row)
    return rows, paths


def main() -> int:
    load_dotenv()
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = Path(args.cache)
    cache = load_cache(cache_path)
    source_rows, source_paths = load_result_rows(args.input_glob)

    prepared: List[Dict[str, object]] = []
    pending: List[Tuple[str, Mapping[str, object]]] = []
    for source_row in source_rows:
        row = dict(source_row)
        judgment = deterministic_judgment(row)
        key = cache_key(row, args.judge_model)
        if judgment is None:
            judgment = cache.get(key)
        if judgment is None:
            pending.append((key, row))
        row["semantic_cache_key"] = key
        row["semantic_judgment"] = judgment
        prepared.append(row)

    print(
        f"baseline={args.baseline} rows={len(prepared)} pending_judge={len(pending)} "
        f"cached={len(cache)}",
        flush=True,
    )
    if pending:
        api_key, _, api_base = provider_config("openai")
        batches = [pending[index : index + args.batch_size] for index in range(0, len(pending), args.batch_size)]
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {
                executor.submit(call_judge_batch, batch, api_key, api_base, args.judge_model): index
                for index, batch in enumerate(batches, start=1)
            }
            completed = 0
            for future in as_completed(futures):
                cache.update(future.result())
                completed += 1
                write_json_atomic(cache_path, cache)
                print(f"[{args.baseline}-semantic-judge] {completed}/{len(batches)} batches", flush=True)

    for row in prepared:
        if row["semantic_judgment"] is None:
            row["semantic_judgment"] = cache.get(str(row["semantic_cache_key"]))

    verification_pending: List[Tuple[str, Mapping[str, object]]] = []
    if args.verify_equivalents:
        for row in prepared:
            judgment = row["semantic_judgment"]
            if not isinstance(judgment, dict):
                raise RuntimeError(f"missing preliminary judgment for {row.get('question_id')}")
            if judgment.get("label") != "equivalent" or judgment.get("source") != "gpt-4o-mini-judge":
                continue
            verification_key = f"verify:{row['semantic_cache_key']}"
            if verification_key not in cache:
                verification_pending.append((verification_key, row))

    if verification_pending:
        api_key, _, api_base = provider_config("openai")
        batches = [
            verification_pending[index : index + args.batch_size]
            for index in range(0, len(verification_pending), args.batch_size)
        ]
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {
                executor.submit(call_verifier_batch, batch, api_key, api_base, args.judge_model): index
                for index, batch in enumerate(batches, start=1)
            }
            completed = 0
            for future in as_completed(futures):
                cache.update(future.result())
                completed += 1
                write_json_atomic(cache_path, cache)
                print(f"[{args.baseline}-semantic-verify] {completed}/{len(batches)} batches", flush=True)

    if args.verify_equivalents:
        for row in prepared:
            judgment = row["semantic_judgment"]
            if (
                not isinstance(judgment, dict)
                or judgment.get("source") != "gpt-4o-mini-judge"
                or judgment.get("label") != "equivalent"
            ):
                continue
            verification = cache.get(f"verify:{row['semantic_cache_key']}")
            if not isinstance(verification, dict):
                raise RuntimeError(f"missing semantic verification for {row.get('question_id')}")
            row["semantic_judgment"] = verification

    scored_rows: List[Dict[str, object]] = []
    for row in prepared:
        judgment = row.pop("semantic_judgment") or cache.get(str(row["semantic_cache_key"]))
        if not isinstance(judgment, dict):
            raise RuntimeError(f"missing semantic judgment for {row.get('question_id')}")
        scored_rows.append(
            {
                "sample_id": row.get("sample_id"),
                "question_id": row.get("question_id"),
                "question_type": row.get("question_type"),
                "category": row.get("category"),
                "question": row.get("question"),
                "gold_answer": row.get("gold_answer"),
                "hypothesis": row.get("hypothesis"),
                "official_answer_f1": row.get("answer_f1"),
                "official_bleu1": row.get("bleu1"),
                "semantic_label": judgment["label"],
                "semantic_correct": judgment["label"] == "equivalent",
                "semantic_reason": judgment.get("reason"),
                "semantic_confidence": judgment.get("confidence"),
                "semantic_note": judgment.get("note", ""),
                "semantic_source": judgment.get("source"),
                "source_result": row.get("source_result"),
            }
        )

    overall = summarize_rows(scored_rows)
    by_task: List[Dict[str, object]] = []
    for task in TASK_ORDER:
        task_rows = [row for row in scored_rows if row["question_type"] == task]
        by_task.append({"question_type": task, **summarize_rows(task_rows)})
    by_task.append({"question_type": "overall", **overall})

    by_sample: List[Dict[str, object]] = []
    for sample_id in sorted({str(row["sample_id"]) for row in scored_rows}):
        sample_rows = [row for row in scored_rows if row["sample_id"] == sample_id]
        by_sample.append({"sample_id": sample_id, **summarize_rows(sample_rows)})

    non_adversarial = [row for row in scored_rows if row["question_type"] != "adversarial"]
    summary = {
        "benchmark": "LoCoMo QA",
        "baseline": args.baseline,
        "semantic_protocol": PROMPT_VERSION,
        "judge_model": args.judge_model,
        "J_definition": "Final semantic-equivalence pass rate. Date and number format matches are canonicalized deterministically; all other equivalent candidates require GPT-4o-mini judging and conservative verification.",
        "source_results": source_paths,
        "n_samples": len(by_sample),
        **overall,
        "non_adversarial_J": summarize_rows(non_adversarial)["J"],
        "by_question_type": by_task,
        "by_sample": by_sample,
    }

    detail_path = output_dir / "semantic_rescore_gpt4omini.json"
    summary_path = output_dir / "summary_semantic_gpt4omini.json"
    task_csv_path = output_dir / "summary_semantic_gpt4omini_by_task.csv"
    sample_csv_path = output_dir / "summary_semantic_gpt4omini_by_sample.csv"
    write_json_atomic(
        detail_path,
        {
            "benchmark": "LoCoMo QA",
            "baseline": args.baseline,
            "semantic_protocol": PROMPT_VERSION,
            "judge_model": args.judge_model,
            "rows": scored_rows,
        },
    )
    write_json_atomic(summary_path, summary)
    headers = (
        "question_type",
        "n_cases",
        "official_answer_f1",
        "official_bleu1",
        "J",
        "equivalent",
        "partial",
        "wrong",
    )
    write_csv(task_csv_path, headers, by_task)
    sample_headers = (
        "sample_id",
        "n_cases",
        "official_answer_f1",
        "official_bleu1",
        "J",
        "equivalent",
        "partial",
        "wrong",
    )
    write_csv(sample_csv_path, sample_headers, by_sample)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

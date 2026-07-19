from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import yaml


BASELINE_DIR = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = BASELINE_DIR.parent
PROJECT_DIR = BENCHMARK_DIR.parents[2]
for import_path in (PROJECT_DIR, BASELINE_DIR, Path(__file__).resolve().parent):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from common.loader import DATA_PATH, LoCoMoQAItem, load_sample_qa  # noqa: E402
from Experiment.run.common.io import load_dotenv  # noqa: E402
from prepare_input import prepare_samples  # noqa: E402
from common.loader import load_sample  # noqa: E402
from ours_scope_time_state.graph_query_runner import (  # noqa: E402
    exact_match_score,
    f1_from_precision_recall,
    format_metric,
    normalize_output_dialog_ids,
    official_style_answer_score,
    precision,
    recall,
    summarize,
)


QUESTION_TYPE_BY_CATEGORY = {
    "multi-hop": 1,
    "temporal": 2,
    "open-domain": 3,
    "single-hop": 4,
    "adversarial": 5,
}

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
PROFILES: Mapping[str, Mapping[str, Any]] = {
    "qwen7b": {
        "model": "qwen2.5:7b",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "ollama",
        "slug": "qwen25_7b",
        "max_tokens": 1024,
    },
    "gpt4omini": {
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "slug": "gpt4omini",
        "max_tokens": 4096,
    },
}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LoCoMo-QA via the installed Microsoft GraphRAG package.")
    parser.add_argument("--stage", choices=("prepare", "init", "index", "answer", "evaluate", "all"), default="prepare")
    parser.add_argument("--llm-profile", choices=tuple(PROFILES), default="gpt4omini")
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--sample-id", default="conv-26")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--predictions", type=Path, default=None, help="GraphRAG answer JSONL to evaluate; defaults to --output.")
    parser.add_argument("--eval-output", type=Path, default=None, help="Evaluation JSON path; defaults next to predictions.")
    parser.add_argument("--method", choices=("local", "global", "drift", "basic"), default="local")
    parser.add_argument(
        "--response-type",
        default="Compact JSON object with answer and evidence_dialog_ids",
        help="GraphRAG response format hint. Default is aligned with LoCoMo answer-F1 evaluation.",
    )
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force-init", action="store_true")
    parser.add_argument("--split-by-session", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def usable_env_value(name: str) -> str:
    value = str(os.environ.get(name, "")).strip()
    if not value or value.startswith("$") or "你的" in value:
        return ""
    return value


def resolve_args(args: argparse.Namespace) -> argparse.Namespace:
    profile = PROFILES[args.llm_profile]
    args.profile = profile
    args.model = str(profile["model"])
    args.chat_api_base = str(profile["base_url"])
    args.chat_api_key = str(profile["api_key"])
    if args.llm_profile == "qwen7b":
        local_model = usable_env_value("LOCAL_MODEL")
        if local_model:
            local_base = usable_env_value("LOCAL_API_BASE")
            local_key = usable_env_value("LOCAL_API_KEY")
            missing = [
                name
                for name, value in (("LOCAL_API_BASE", local_base), ("LOCAL_API_KEY", local_key))
                if not value
            ]
            if missing:
                raise ValueError(
                    "LOCAL_MODEL selects the school-server Qwen endpoint, but these settings are missing: "
                    + ", ".join(missing)
                )
            args.model = local_model
            args.chat_api_base = local_base
            args.chat_api_key = local_key
    else:
        args.chat_api_base = (
            usable_env_value("OPENAI_API_BASE")
            or usable_env_value("OPENAI_BASE_URL")
            or args.chat_api_base
        )
        args.chat_api_key = usable_env_value("OPENAI_API_KEY")

    args.embedding_model = EMBEDDING_MODEL
    args.embedding_api_base = (
        usable_env_value("OPENAI_EMBEDDING_API_BASE")
        or usable_env_value("OPENAI_EMBEDDING_BASE_URL")
        or DEFAULT_EMBEDDING_BASE_URL
    )
    args.embedding_api_key = usable_env_value("OPENAI_EMBEDDING_API_KEY") or usable_env_value("OPENAI_API_KEY")
    slug = str(profile["slug"])
    args.workspace = args.workspace or (
        PROJECT_DIR / "Graph/output/baseline_store/locomo_qa/graph_rag" / slug / args.sample_id
    )
    args.output = args.output or (
        PROJECT_DIR / "Graph/output/results/locomo_qa/graph_rag" / slug / f"results_{args.sample_id}.jsonl"
    )
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_dotenv()
    args = resolve_args(parse_args(argv))
    args.workspace = args.workspace.resolve()
    args.output = args.output.resolve()
    args.predictions = args.predictions.resolve() if args.predictions else None
    args.eval_output = args.eval_output.resolve() if args.eval_output else None

    if args.stage in {"prepare", "all"}:
        sample = load_sample(args.data, args.sample_id)
        prepare_samples([sample], args.workspace, split_by_session=args.split_by_session, data_path=args.data)

    if args.stage in {"init", "index", "answer", "all"} and not args.dry_run:
        ensure_graphrag_available()

    if args.stage in {"init", "all"}:
        run_graphrag(["init", "--root", str(args.workspace), "--model", args.model, "--embedding", args.embedding_model, *force_flag(args.force_init)], args)
        if args.dry_run:
            print(
                f"profile={args.llm_profile} chat_model={args.model} chat_api_base={args.chat_api_base} "
                f"embedding_model={args.embedding_model} embedding_api_base={args.embedding_api_base}",
                flush=True,
            )
        else:
            write_graphrag_configuration(args)

    if args.stage in {"index", "all"}:
        run_graphrag(["index", "--root", str(args.workspace)], args)

    if args.stage in {"answer", "all"}:
        run_answer(args)

    if args.stage in {"evaluate", "all"}:
        run_evaluate(args)

    return 0


def graphrag_executable() -> str:
    env_script_dir = Path(sys.executable).resolve().parent
    script_dir = env_script_dir / "Scripts"
    for candidate in (
        script_dir / "graphrag.exe",
        script_dir / "graphrag",
        env_script_dir / "graphrag.exe",
        env_script_dir / "graphrag",
    ):
        if candidate.exists():
            return str(candidate)
    command = shutil.which("graphrag")
    if command:
        return command
    return "graphrag"


def ensure_graphrag_available() -> None:
    executable = graphrag_executable()
    if executable != "graphrag" or shutil.which("graphrag"):
        return
    raise RuntimeError(
        "The Microsoft GraphRAG CLI is not installed in this environment. "
        "Install it with: python -m pip install graphrag"
    )


def force_flag(enabled: bool) -> List[str]:
    return ["--force"] if enabled else []


def write_graphrag_configuration(args: argparse.Namespace) -> None:
    if not args.chat_api_key:
        raise ValueError(f"missing chat API key for {args.llm_profile}")
    if not args.embedding_api_key:
        raise ValueError("missing OPENAI_EMBEDDING_API_KEY or OPENAI_API_KEY for text-embedding-3-small")
    env_path = args.workspace / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    managed_keys = {"GRAPHRAG_CHAT_API_KEY", "GRAPHRAG_EMBEDDING_API_KEY"}
    lines = [
        line
        for line in existing.splitlines()
        if line.split("=", 1)[0].strip() not in managed_keys
    ]
    lines.extend(
        (
            f"GRAPHRAG_CHAT_API_KEY={args.chat_api_key}",
            f"GRAPHRAG_EMBEDDING_API_KEY={args.embedding_api_key}",
        )
    )
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    settings_path = args.workspace / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"GraphRAG init did not create {settings_path}")
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    configure_model_maps(settings, args)
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False, allow_unicode=True), encoding="utf-8")


def configure_model_maps(settings: Dict[str, Any], args: argparse.Namespace) -> None:
    completion_models = settings.get("completion_models")
    embedding_models = settings.get("embedding_models")
    if isinstance(completion_models, dict) and isinstance(embedding_models, dict):
        configure_model_entry(
            first_model_entry(completion_models, "completion"),
            args.model,
            args.chat_api_base,
            "${GRAPHRAG_CHAT_API_KEY}",
            max_tokens=int(args.profile["max_tokens"]),
        )
        configure_model_entry(first_model_entry(embedding_models, "embedding"), EMBEDDING_MODEL, args.embedding_api_base, "${GRAPHRAG_EMBEDDING_API_KEY}")
        return
    models = settings.get("models")
    if isinstance(models, dict):
        chat_entry = models.get("default_chat_model") or models.get("default_completion_model")
        embedding_entry = models.get("default_embedding_model")
        if isinstance(chat_entry, dict) and isinstance(embedding_entry, dict):
            configure_model_entry(
                chat_entry,
                args.model,
                args.chat_api_base,
                "${GRAPHRAG_CHAT_API_KEY}",
                max_tokens=int(args.profile["max_tokens"]),
            )
            configure_model_entry(embedding_entry, EMBEDDING_MODEL, args.embedding_api_base, "${GRAPHRAG_EMBEDDING_API_KEY}")
            return
    raise ValueError("unsupported GraphRAG settings schema: completion and embedding model maps were not found")


def first_model_entry(model_map: Dict[str, Any], label: str) -> Dict[str, Any]:
    for value in model_map.values():
        if isinstance(value, dict):
            return value
    raise ValueError(f"GraphRAG {label} model map is empty")


def configure_model_entry(
    entry: Dict[str, Any],
    model: str,
    api_base: str,
    api_key: str,
    *,
    max_tokens: Optional[int] = None,
) -> None:
    entry["model_provider"] = "openai"
    entry["model"] = model
    entry["auth_method"] = "api_key"
    entry["api_key"] = api_key
    entry["api_base"] = api_base
    if max_tokens is not None:
        call_args = entry.get("call_args")
        if not isinstance(call_args, dict):
            call_args = {}
            entry["call_args"] = call_args
        call_args["max_tokens"] = max_tokens


def run_answer(args: argparse.Namespace) -> None:
    rows = select_rows(load_sample_qa(args.data, args.sample_id), args)
    existing = load_existing(args.output) if args.resume else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    results = []
    total = len(rows)
    with args.output.open("a" if args.resume else "w", encoding="utf-8") as handle:
        for index, row in enumerate(rows, start=1):
            if index <= args.start:
                continue
            if row.question_id in existing:
                print(f"[skip {index}/{total}] {row.question_id}", flush=True)
                continue
            print(f"[{index}/{total}] {row.question_id} {row.question}", flush=True)
            query_result = query_graphrag(args, row.question)
            record = {
                "schema_version": "locomo-graphrag-answer-v1",
                "baseline": "microsoft_graphrag_cli",
                "llm_profile": args.llm_profile,
                "model": args.model,
                "embedding_model": EMBEDDING_MODEL,
                "sample_id": row.sample_id,
                "question_id": row.question_id,
                "qa_index": row.qa_index,
                "category": row.category,
                "question_type": row.question_type,
                "question": row.question,
                "gold_answer": row.answer,
                "gold_evidence_dialog_ids": list(row.evidence_dialog_ids),
                "answer": query_result["answer"],
                "raw_graphrag_response": query_result["raw_response"],
                "candidate_dialog_ids": query_result["candidate_dialog_ids"],
                "evidence_dialog_ids": query_result["evidence_dialog_ids"],
                "graphrag_context_keys": query_result["context_keys"],
                "query_prompt": locomo_query_prompt(row.question),
                "graphrag_method": args.method,
                "graphrag_response_type": args.response_type,
                "gold_used_for_index_or_query": False,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            results.append(record)
    print(f"saved: {args.output}")


def run_evaluate(args: argparse.Namespace) -> None:
    predictions_path = args.predictions or args.output
    if not predictions_path.exists():
        raise FileNotFoundError(f"predictions file not found: {predictions_path}")

    rows_by_id = {row.question_id: row for row in select_rows(load_sample_qa(args.data, args.sample_id), args)}
    eval_rows: List[Dict[str, object]] = []
    for record in load_jsonl(predictions_path):
        question_id = str(record.get("question_id") or "")
        if not question_id:
            continue
        row = rows_by_id.get(question_id)
        if row is None:
            continue
        hypothesis = str(record.get("answer") or "").strip()
        candidate_dialog_ids = normalize_output_dialog_ids(record.get("candidate_dialog_ids"))
        evidence_dialog_ids = normalize_output_dialog_ids(record.get("evidence_dialog_ids"))
        candidate_precision = precision(candidate_dialog_ids, row.evidence_dialog_ids)
        candidate_recall = recall(candidate_dialog_ids, row.evidence_dialog_ids)
        evidence_precision = precision(evidence_dialog_ids, row.evidence_dialog_ids)
        evidence_recall = recall(evidence_dialog_ids, row.evidence_dialog_ids)
        eval_rows.append(
            {
                "question_id": row.question_id,
                "sample_id": row.sample_id,
                "qa_index": row.qa_index,
                "category": row.category,
                "question_type": row.question_type,
                "question": row.question,
                "gold_answer": row.answer,
                "initial_hypothesis": hypothesis,
                "hypothesis": hypothesis,
                "candidate_dialog_ids": candidate_dialog_ids,
                "evidence_dialog_ids": evidence_dialog_ids,
                "gold_evidence_dialog_ids": list(row.evidence_dialog_ids),
                "candidate_dialog_recall": candidate_recall,
                "candidate_dialog_precision": candidate_precision,
                "evidence_dialog_recall": evidence_recall,
                "evidence_dialog_precision": evidence_precision,
                "evidence_dialog_f1": f1_from_precision_recall(evidence_precision, evidence_recall),
                "answer_f1": official_style_answer_score(row, hypothesis),
                "exact_match": exact_match_score(hypothesis, row.answer) if row.category != 5 else False,
                "raw_graphrag_answer": hypothesis,
                "graphrag_method": record.get("graphrag_method"),
            }
        )

    result = {"variant": "microsoft_graphrag_cli", "summary": summarize(eval_rows), "rows": eval_rows}
    payload = {
        "schema_version": "locomo-graphrag-eval-v1",
        "benchmark": "LoCoMo-QA",
        "baseline": "microsoft_graphrag_cli",
        "llm_profile": args.llm_profile,
        "model": args.model,
        "embedding_model": EMBEDDING_MODEL,
        "sample_id": args.sample_id,
        "predictions_path": str(predictions_path),
        "workspace": str(args.workspace),
        "gold_used_for_index_or_query": False,
        "uses_llm_as_judge": False,
        "scoring": "LoCoMo paper answer F1 via existing Baseline/ours_scope_time_state scoring helpers",
        "notes": [
            "Microsoft GraphRAG CLI performs graph indexing/querying.",
            "This adapter computes LoCoMo-style answer F1/exact-match from generated answers.",
            "For local search, this adapter uses the official GraphRAG Python API to capture context text units and map [D#:turn] markers back to LoCoMo dialog ids.",
            "For non-local GraphRAG methods or older prediction files without stored context ids, context/evidence metrics may be n/a.",
        ],
        "results": [result],
    }

    output_path = args.eval_output or predictions_path.with_name(f"{predictions_path.stem}.eval.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hypotheses_path = output_path.with_name(f"{output_path.stem}.hypotheses.jsonl")
    with hypotheses_path.open("w", encoding="utf-8") as handle:
        for row in eval_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print_eval_summary(args.model, [result])
    print(f"saved: {output_path}")
    print(f"hypotheses: {hypotheses_path}")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
    return records


def print_eval_summary(model: str, results: Sequence[Dict[str, object]]) -> None:
    print("LoCoMo QA GraphRAG evaluation")
    print(f"answer_model={model}")
    print()
    print(f"{'variant':<35} {'n':>4} {'ans_f1':>8} {'task_f1':>8} {'exact':>8} {'cand_r':>8} {'cand_p':>8} {'ev_r':>8} {'ev_p':>8} {'ev_f1':>8}")
    print("-" * 122)
    for result in results:
        summary = result["summary"]
        print(
            f"{result['variant']:<35} "
            f"{summary['n_cases']:>4} "
            f"{format_metric(summary['answer_f1']):>8} "
            f"{format_metric(summary['task_averaged_answer_f1']):>8} "
            f"{format_metric(summary['exact_match']):>8} "
            f"{format_metric(summary['candidate_dialog_recall']):>8} "
            f"{format_metric(summary['candidate_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_recall']):>8} "
            f"{format_metric(summary['evidence_dialog_precision']):>8} "
            f"{format_metric(summary['evidence_dialog_f1']):>8}"
        )


def query_graphrag(args: argparse.Namespace, question: str) -> Dict[str, object]:
    if args.method == "local":
        try:
            return query_graphrag_local_api(args, question)
        except Exception as exc:
            print(f"warning: official GraphRAG Python API query failed; falling back to CLI without context ids: {exc}", file=sys.stderr)
    command = [
        "query",
        "--root",
        str(args.workspace),
        "--method",
        args.method,
        "--response-type",
        args.response_type,
        locomo_query_prompt(question),
    ]
    completed = run_graphrag(command, args, capture=True)
    raw_response = (completed.stdout or "").strip()
    parsed = parse_graphrag_answer(raw_response)
    return {
        "answer": parsed["answer"],
        "raw_response": raw_response,
        "candidate_dialog_ids": [],
        "evidence_dialog_ids": parsed["evidence_dialog_ids"],
        "context_keys": [],
    }


def query_graphrag_local_api(args: argparse.Namespace, question: str) -> Dict[str, object]:
    from graphrag.config.load_config import load_config
    import graphrag.api as api
    import pandas as pd

    output_dir = args.workspace / "output"
    config = load_config(root_dir=args.workspace)
    required = {
        "communities": pd.read_parquet(output_dir / "communities.parquet"),
        "community_reports": pd.read_parquet(output_dir / "community_reports.parquet"),
        "text_units": pd.read_parquet(output_dir / "text_units.parquet"),
        "relationships": pd.read_parquet(output_dir / "relationships.parquet"),
        "entities": pd.read_parquet(output_dir / "entities.parquet"),
    }
    covariates_path = output_dir / "covariates.parquet"
    covariates = pd.read_parquet(covariates_path) if covariates_path.exists() else None
    raw_response, context_data = asyncio.run(
        api.local_search(
            config=config,
            entities=required["entities"],
            communities=required["communities"],
            community_reports=required["community_reports"],
            text_units=required["text_units"],
            relationships=required["relationships"],
            covariates=covariates,
            community_level=2,
            response_type=args.response_type,
            query=locomo_query_prompt(question),
            verbose=False,
        )
    )
    raw_text = response_to_text(raw_response)
    parsed = parse_graphrag_answer(raw_text)
    candidate_dialog_ids = dialog_ids_from_context_data(context_data)
    return {
        "answer": parsed["answer"],
        "raw_response": raw_text,
        "candidate_dialog_ids": candidate_dialog_ids,
        "evidence_dialog_ids": parsed["evidence_dialog_ids"],
        "context_keys": sorted(context_data.keys()) if isinstance(context_data, dict) else [],
    }


def locomo_query_prompt(question: str) -> str:
    return (
        "Answer this LoCoMo QA question using only the indexed conversation evidence. "
        "Return compact JSON only with keys answer and evidence_dialog_ids. "
        "The answer value must be a short gold-style phrase, date, name, or comma-separated list. "
        "The answer value must not be a dialog id such as D1:3. "
        "The evidence_dialog_ids value must list supporting dialog ids exactly like D1:3 from the indexed text. "
        "Do not write a report, explanation, citations, markdown, or extra background. "
        "For false-premise or unavailable information, answer exactly \"No information available\" "
        "or \"Not mentioned in the conversation\" and use an empty evidence_dialog_ids list. "
        f"Question: {question}"
    )


def response_to_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False)


def parse_graphrag_answer(raw_response: str) -> Dict[str, object]:
    text = raw_response.strip()
    json_text = extract_json_object(text)
    if json_text:
        try:
            payload = json.loads(json_text)
            answer = str(payload.get("answer") or "").strip()
            evidence_ids = normalize_output_dialog_ids(payload.get("evidence_dialog_ids"))
            if answer:
                return {"answer": answer, "evidence_dialog_ids": evidence_ids}
        except json.JSONDecodeError:
            pass
    return {
        "answer": strip_markdown_fences(text),
        "evidence_dialog_ids": normalize_output_dialog_ids(DIALOG_ID_RE.findall(text)),
    }


def extract_json_object(text: str) -> str:
    stripped = strip_markdown_fences(text)
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return ""


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


DIALOG_ID_RE = re.compile(r"D\d+:\d+")


def dialog_ids_from_context_data(context_data: object) -> List[str]:
    if not isinstance(context_data, dict):
        return []
    ids: List[str] = []
    for value in context_data.values():
        if hasattr(value, "to_dict"):
            for record in value.to_dict(orient="records"):
                ids.extend(dialog_ids_from_record(record))
        elif isinstance(value, list):
            for record in value:
                ids.extend(dialog_ids_from_record(record))
    return normalize_output_dialog_ids(ids)


def dialog_ids_from_record(record: object) -> List[str]:
    if not isinstance(record, dict):
        return []
    ids: List[str] = []
    for key in ("text", "content", "source", "description"):
        value = record.get(key)
        if value is not None:
            ids.extend(DIALOG_ID_RE.findall(str(value)))
    return ids


def run_graphrag(command: Sequence[str], args: argparse.Namespace, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    full_command = [graphrag_executable(), *command]
    print(" ".join(quote(part) for part in full_command), flush=True)
    if args.dry_run:
        return subprocess.CompletedProcess(full_command, 0, stdout="", stderr="")
    env = os.environ.copy()
    return subprocess.run(
        full_command,
        cwd=str(PROJECT_DIR),
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def select_rows(rows: Sequence[LoCoMoQAItem], args: argparse.Namespace) -> List[LoCoMoQAItem]:
    selected = list(rows)
    if args.question_types:
        categories = {QUESTION_TYPE_BY_CATEGORY[item] for item in args.question_types}
        selected = [row for row in selected if row.category in categories]
    if args.limit_per_type > 0:
        counts: dict[int, int] = {}
        limited = []
        for row in selected:
            current = counts.get(row.category, 0)
            if current >= args.limit_per_type:
                continue
            counts[row.category] = current + 1
            limited.append(row)
        selected = limited
    if args.limit_cases > 0:
        selected = selected[: args.limit_cases]
    return selected


def load_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    existing = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("question_id"):
            existing[str(item["question_id"])] = item
    return existing


def quote(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        return repr(value)
    return value


if __name__ == "__main__":
    started = time.time()
    try:
        raise SystemExit(main())
    finally:
        print(f"elapsed_sec={time.time() - started:.1f}", flush=True)

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, Optional

import requests

from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import LLMRequestError, provider_config, parse_json_object, json_safe_object
from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import TaskSemanticsLocalGraphBuilder
from longmemeval_s_graph_retrieval.task_semantics_local_graph.llm_extractor import LLMGraphExtractor
from pipeline.external.longmemeval_s.adapters import TASK_TYPES
from pipeline.external.longmemeval_s.runner import bm25_top_session_ids, retrieval_query, select_rows

from .common import candidate_sessions_for_row, load_rows_utf8, resolve_data_path
from .graph_store import write_graph_artifact


DEFAULT_GRAPH_DIR = Path(__file__).resolve().parent / "artifacts" / "graphs"


class RequestsJsonClient:
    """OpenAI-compatible JSON client using raw requests (bypasses SDK for tixyw compatibility)."""

    def __init__(self, model: str, api_key: str, api_base: str, cache_path: Path, use_cache: bool) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.cache_path = cache_path
        self.use_cache = use_cache
        self.cache: Dict[str, Dict[str, Any]] = {}
        if use_cache and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.cache = {}

    def _save_cache(self) -> None:
        if not self.use_cache:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.cache_path)

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        cache_key = hashlib.sha256(
            json.dumps({"model": self.model, "system": system_prompt, "user": user_prompt},
                       ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        if self.use_cache and cache_key in self.cache:
            return dict(self.cache[cache_key])

        url = f"{self.api_base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        }
        parse_retries = int(os.environ.get("LLM_PARSE_RETRIES", "2"))
        last_error: Optional[Exception] = None

        for attempt in range(parse_retries + 1):
            json_modes = [True, False]
            for json_mode in json_modes:
                try:
                    req_payload = dict(payload)
                    if json_mode:
                        req_payload["response_format"] = {"type": "json_object"}
                    resp = requests.post(url, headers=headers, json=req_payload, timeout=300)
                    if resp.status_code != 200:
                        msg = f"API error {resp.status_code}: {resp.text[:200]}"
                        raise LLMRequestError("requests", self.model, self.api_base, msg)
                    data = resp.json()
                    try:
                        content = data["choices"][0]["message"]["content"] or ""
                    except (KeyError, IndexError) as exc:
                        # Show actual response for debugging
                        sample = json.dumps(data, ensure_ascii=False)[:500]
                        msg = f"Unexpected API response structure: {sample}"
                        raise LLMRequestError("requests", self.model, self.api_base, msg) from exc
                    parsed = json_safe_object(parse_json_object(content))
                    if self.use_cache:
                        self.cache[cache_key] = dict(parsed)
                        self._save_cache()
                    return dict(parsed)
                except (ValueError, KeyError, json.JSONDecodeError) as exc:
                    last_error = exc
                    continue
                except LLMRequestError as exc:
                    if json_mode:
                        last_error = exc
                        continue
                    raise
            if attempt < parse_retries:
                time.sleep(1 + attempt)
                continue
            if last_error is not None:
                raise last_error
            raise ValueError("model did not return parseable JSON")

        raise ValueError("unreachable")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prebuild LongMemEval-S local KG artifacts with an LLM.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--question-types", nargs="+", default=[])
    parser.add_argument("--task-candidate-k", type=int, default=20)
    parser.add_argument("--graph-batch-size", type=int, default=5)
    parser.add_argument("--max-facets", type=int, default=12)
    parser.add_argument("--construction-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--construction-model", default="deepseek-v4-flash")
    parser.add_argument("--construction-cache", default=str(DEFAULT_GRAPH_DIR / "llm_cache.graph_build.json"))
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.task_candidate_k < 1:
        parser.error("--task-candidate-k must be >= 1")
    if args.graph_batch_size < 1:
        parser.error("--graph-batch-size must be >= 1")
    if args.max_facets < 1:
        parser.error("--max-facets must be >= 1")
    return args


def make_client(provider: str, model: str, cache_path: Path, use_cache: bool) -> RequestsJsonClient:
    api_key, default_model, api_base = provider_config(provider)
    return RequestsJsonClient(
        model=model or default_model,
        api_key=api_key,
        api_base=api_base,
        cache_path=cache_path,
        use_cache=use_cache,
    )


def main() -> int:
    args = parse_args()
    load_dotenv()
    data_path = resolve_data_path(args.data)
    rows = select_rows(load_rows_utf8(data_path), args.question_types, args.limit_cases, args.limit_per_type)
    unsupported = sorted({row.question_type for row in rows} - set(TASK_TYPES))
    if unsupported:
        print(f"unsupported question types in selection: {unsupported}", file=sys.stderr)
        return 2
    question_types = Counter(row.question_type for row in rows)
    graph_dir = Path(args.graph_dir)
    if args.dry_run:
        print(
            f"valid prebuild graph run: rows={len(rows)} question_types={dict(question_types)} "
            f"graph_dir={graph_dir} data_path={data_path}"
        )
        return 0

    try:
        client = make_client(
            args.construction_provider,
            args.construction_model,
            Path(args.construction_cache),
            use_cache=not args.no_cache,
        )
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    extractor = LLMGraphExtractor(client)
    builder = TaskSemanticsLocalGraphBuilder(
        batch_size=args.graph_batch_size,
        max_facets=args.max_facets,
        extractor=extractor,
    )
    graph_dir.mkdir(parents=True, exist_ok=True)
    built = 0
    skipped = 0
    try:
        for index, row in enumerate(rows, start=1):
            graph_path = graph_dir / f"{row.question_id}.graph.json"
            if graph_path.exists() and not args.overwrite:
                skipped += 1
                print(f"[prebuild] skip existing {index}/{len(rows)} {row.question_id}", flush=True)
                continue
            selected_session_ids = bm25_top_session_ids(
                row,
                args.task_candidate_k,
                query_text=retrieval_query(row, expand=True),
            )
            sessions = candidate_sessions_for_row(row, selected_session_ids)
            graph = builder.build(
                sessions=sessions,
                question=row.question,
                question_type=row.question_type,
                question_date=row.question_date,
            )
            metadata = {
                "method": "prebuilt_llm_kg_graph",
                "question_id": row.question_id,
                "question_type": row.question_type,
                "question": row.question,
                "question_date": row.question_date,
                "candidate_session_ids": list(selected_session_ids),
                "answer_session_ids": list(row.answer_session_ids),
                "construction_provider": args.construction_provider,
                "construction_model": args.construction_model,
                "task_candidate_k": args.task_candidate_k,
                "graph_batch_size": args.graph_batch_size,
                "max_facets": args.max_facets,
            }
            write_graph_artifact(graph_path, graph, metadata)
            built += 1
            print(f"[prebuild] wrote {index}/{len(rows)} {graph_path}", flush=True)
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    manifest = {
        "method": "prebuilt_llm_kg_graph",
        "data_path": str(data_path),
        "n_rows": len(rows),
        "built": built,
        "skipped": skipped,
        "question_types": dict(question_types),
        "construction_provider": args.construction_provider,
        "construction_model": args.construction_model,
        "task_candidate_k": args.task_candidate_k,
        "graph_batch_size": args.graph_batch_size,
        "max_facets": args.max_facets,
    }
    (graph_dir / "build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote manifest {graph_dir / 'build_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


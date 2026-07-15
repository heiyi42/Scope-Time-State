"""Run EPBench through the unified STS v2 build, retrieve, QA, and judge stages."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence


if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[5]
    BASELINE_DIR = Path(__file__).resolve().parent.parent
    for import_path in (REPO_ROOT, BASELINE_DIR):
        if str(import_path) not in sys.path:
            sys.path.insert(0, str(import_path))
    from STS.config import (  # type: ignore
        ANSWER_MODEL,
        BUILD_MODEL,
        CACHE_DIR,
        CLAIM_CANDIDATE_K,
        EMBEDDING_MODEL,
        EVENT_CANDIDATE_K,
        FINAL_CHAPTER_K,
        GRAPH_DIR,
        JUDGE_MODEL,
        MAX_CLAIMS_PER_CHAPTER,
        MESSAGE_CHUNK_SIZE,
        RESOLVER_CANDIDATE_LIMIT,
        RESULT_DIR,
        SCOPE_TOP_K,
    )
    from STS.graph_builder import (  # type: ignore
        EXTRACTION_SCHEMA_VERSION,
        build_graph,
        extract_chapter_records,
        write_graph,
    )
    from STS.loader import load_chapters, load_qa  # type: ignore
    from STS.qa_runner import run_judge, run_qa  # type: ignore
    from STS.staged import EmbeddingConfig, STSGraphIndex  # type: ignore
else:
    from .config import (
        ANSWER_MODEL,
        BUILD_MODEL,
        CACHE_DIR,
        CLAIM_CANDIDATE_K,
        EMBEDDING_MODEL,
        EVENT_CANDIDATE_K,
        FINAL_CHAPTER_K,
        GRAPH_DIR,
        JUDGE_MODEL,
        MAX_CLAIMS_PER_CHAPTER,
        MESSAGE_CHUNK_SIZE,
        RESOLVER_CANDIDATE_LIMIT,
        RESULT_DIR,
        SCOPE_TOP_K,
    )
    from .graph_builder import EXTRACTION_SCHEMA_VERSION, build_graph, extract_chapter_records, write_graph
    from .loader import load_chapters, load_qa
    from .qa_runner import run_judge, run_qa
    from .staged import EmbeddingConfig, STSGraphIndex


@dataclass(frozen=True)
class ClientBundle:
    extraction: Any
    merge: Any
    frame: Any
    answer: Any
    judge: Any
    embedding_config: EmbeddingConfig | None


@dataclass(frozen=True)
class ArtifactPaths:
    graph_root: Path
    cache_root: Path
    result_root: Path

    @property
    def graph_dir(self) -> Path:
        return self.graph_root / "book1"


def _artifact_paths(output_root: Path | None) -> ArtifactPaths:
    if output_root is None:
        return ArtifactPaths(GRAPH_DIR, CACHE_DIR, RESULT_DIR)
    root = Path(output_root).expanduser().resolve()
    return ArtifactPaths(root / "graph", root / "cache", root / "results")


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _real_clients(args: argparse.Namespace, paths: ArtifactPaths) -> ClientBundle:
    from Experiment.run.common.io import load_dotenv
    from Experiment.run.common.llm_client import LLMClient, provider_config

    load_dotenv()
    api_key, _provider_model, api_base = provider_config("openai")

    def client(name: str, model: str) -> Any:
        return LLMClient(
            provider="openai",
            model=model,
            api_key=api_key,
            api_base=api_base,
            cache_path=paths.cache_root / f"{name}.json",
            use_cache=not args.no_cache,
        )

    return ClientBundle(
        extraction=client("build", args.model),
        merge=client("merge", args.model),
        frame=client("frame", args.answer_model),
        answer=client("answer", args.answer_model),
        judge=client("judge", args.judge_model),
        embedding_config=EmbeddingConfig(
            model=args.embedding_model,
            cache_dir=paths.cache_root / "embeddings",
            batch_size=args.embedding_batch_size,
        ),
    )


def _load_extraction_cache(path: Path) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != EXTRACTION_SCHEMA_VERSION:
        return {}
    rows = payload.get("records", [])
    return {int(row["chapter_id"]): row for row in rows}


def _build(args: argparse.Namespace, paths: ArtifactPaths, clients: ClientBundle) -> Path:
    chapters = load_chapters()
    if args.chapter_limit is not None:
        if args.chapter_limit < 1:
            raise ValueError("chapter-limit must be positive")
        chapters = chapters[: args.chapter_limit]
    cache_path = paths.cache_root / "extraction_records.json"
    cached = _load_extraction_cache(cache_path) if not args.no_resume else {}
    missing = [chapter for chapter in chapters if chapter.chapter_id not in cached]
    if missing:
        records, _traces = extract_chapter_records(
            missing,
            clients.extraction,
            message_chunk_size=args.message_chunk_size,
            max_claims_per_chapter=args.max_claims_per_chapter,
            workers=args.workers,
        )
        cached.update({int(record["chapter_id"]): record for record in records})
        _write_json_atomic(
            cache_path,
            {
                "schema_version": EXTRACTION_SCHEMA_VERSION,
                "records": [cached[key] for key in sorted(cached)],
            },
        )
    selected_records = [cached[chapter.chapter_id] for chapter in chapters]
    graph = build_graph(
        chapters,
        selected_records,
        merge_client=clients.merge,
        resolver_candidate_limit=args.resolver_candidate_limit,
    )
    graph["manifest"]["runtime"] = {
        "build_model": args.model,
        "evidence_mode": "sentence_id",
        "message_chunk_size": args.message_chunk_size,
        "max_claims_per_chapter": args.max_claims_per_chapter,
    }
    target = write_graph(paths.graph_root, graph)
    print(f"STS graph: {target}")
    return target


def _retrieval_kwargs(args: argparse.Namespace) -> dict[str, int]:
    return {
        "scope_top_k": args.scope_top_k,
        "event_candidate_k": args.event_candidate_k,
        "claim_candidate_k": args.claim_candidate_k,
        "final_chapter_k": args.final_chapter_k,
    }


def _retrieve(args: argparse.Namespace, paths: ArtifactPaths, clients: ClientBundle) -> Path:
    index = STSGraphIndex.load(paths.graph_dir, embedding_config=clients.embedding_config)
    rows = []
    questions = load_qa()[args.question_offset : args.question_offset + args.question_limit]
    for item in questions:
        result = index.retrieve(item.question, clients.frame, **_retrieval_kwargs(args))
        rows.append({"row_index": item.row_index, "q_idx": item.q_idx, **result.to_dict()})
    output_path = paths.result_root / "retrieval.json"
    _write_json_atomic(output_path, {"rows": rows})
    print(f"STS retrieval: {output_path}")
    return output_path


def _qa(args: argparse.Namespace, paths: ArtifactPaths, clients: ClientBundle) -> Path:
    output_path = paths.result_root / "qa.json"
    run_qa(
        graph_dir=paths.graph_dir,
        output_path=output_path,
        answer_client=clients.answer,
        frame_client=clients.frame,
        embedding_config=clients.embedding_config,
        offset=args.question_offset,
        limit=args.question_limit,
        resume=not args.no_resume,
        workers=args.workers,
        **_retrieval_kwargs(args),
    )
    print(f"STS QA: {output_path}")
    return output_path


def _judge(args: argparse.Namespace, paths: ArtifactPaths, clients: ClientBundle) -> Path:
    output_path = paths.result_root / "judged.json"
    run_judge(
        qa_result_path=paths.result_root / "qa.json",
        output_path=output_path,
        judge_client=clients.judge,
        resume=not args.no_resume,
        workers=args.workers,
    )
    print(f"STS judge: {output_path}")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("build", "retrieve", "qa", "judge", "all"), default="all")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--model", default=BUILD_MODEL)
    parser.add_argument("--answer-model", default=ANSWER_MODEL)
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    parser.add_argument("--embedding-batch-size", type=int, default=24)
    parser.add_argument("--message-chunk-size", type=int, default=MESSAGE_CHUNK_SIZE)
    parser.add_argument("--max-claims-per-chapter", type=int, default=MAX_CLAIMS_PER_CHAPTER)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resolver-candidate-limit", type=int, default=RESOLVER_CANDIDATE_LIMIT)
    parser.add_argument("--scope-top-k", type=int, default=SCOPE_TOP_K)
    parser.add_argument("--event-candidate-k", type=int, default=EVENT_CANDIDATE_K)
    parser.add_argument("--claim-candidate-k", type=int, default=CLAIM_CANDIDATE_K)
    parser.add_argument("--final-chapter-k", type=int, default=FINAL_CHAPTER_K)
    parser.add_argument("--chapter-limit", type=int)
    parser.add_argument("--question-offset", type=int, default=0)
    parser.add_argument("--question-limit", type=int, default=686)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, clients: ClientBundle | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.question_offset < 0 or args.question_limit < 0:
        raise ValueError("question offset and limit must be non-negative")
    paths = _artifact_paths(args.output_root)
    active_clients = clients or _real_clients(args, paths)
    if args.stage in {"build", "all"}:
        _build(args, paths, active_clients)
    if args.stage in {"retrieve", "all"}:
        _retrieve(args, paths, active_clients)
    if args.stage in {"qa", "all"}:
        _qa(args, paths, active_clients)
    if args.stage in {"judge", "all"}:
        _judge(args, paths, active_clients)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

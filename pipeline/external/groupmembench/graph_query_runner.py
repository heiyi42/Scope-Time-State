from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
from threading import Event, RLock, Thread
import time
from typing import Any, Dict, List, Optional, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.embedding_retrieval import OpenAIEmbeddingIndex  # noqa: E402
from pipeline.external.groupmembench.adapters import TASK_TYPES, get_adapter  # noqa: E402
from pipeline.external.groupmembench.domain_graph import (  # noqa: E402
    claims_from_graph_artifact,
    domain_graph_artifact_dir,
    is_domain_graph_artifact,
    messages_from_graph_artifact,
    scopes_from_graph_artifact,
)
from pipeline.external.groupmembench.graph_store import GraphArtifact, graph_artifact_dir, load_graph_artifact  # noqa: E402
from pipeline.external.groupmembench.judging import judge_answer, summarize  # noqa: E402
from pipeline.external.groupmembench.loader import (  # noqa: E402
    CACHE_DIR,
    DOMAINS,
    GRAPH_OUTPUT_DIR,
    GroupQuestion,
    RESULT_DIR,
    filter_messages_for_scope,
)
from pipeline.external.groupmembench.retrieval import (  # noqa: E402
    DEFAULT_EMBEDDING_MESSAGE_SCORE_WEIGHT,
    DEFAULT_EMBEDDING_SCOPE_SCORE_WEIGHT,
    document_text,
    refine_scope_route_with_evidence,
    ranked_messages,
    select_graph_build_messages,
)
from pipeline.external.groupmembench.routing import score_scope  # noqa: E402
from pipeline.external.groupmembench.runner import load_selected_questions  # noqa: E402
from pipeline.external.groupmembench.staged import (  # noqa: E402
    complete_graph_state_packet_from_claims,
    compose_answer,
)
from pipeline.external.groupmembench.time_roles import infer_group_time_role_with_llm  # noqa: E402


GRAPH_STORE_MODES = ("auto", "domain", "question")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Answer GroupMemBench queries from persistent graph artifacts.")
    parser.add_argument("--graph-dir", default=str(GRAPH_OUTPUT_DIR / "groupmembench_domain_graph_v1"))
    parser.add_argument("--graph-store-mode", choices=GRAPH_STORE_MODES, default="auto")
    parser.add_argument("--domains", nargs="+", choices=DOMAINS, default=["Finance"])
    parser.add_argument("--qtypes", nargs="+", choices=TASK_TYPES, default=list(TASK_TYPES))
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None, help="Optional model override for query-time validity/state/composer.")
    parser.add_argument("--judge", action="store_true", help="Run the official-style GroupMemBench LLM judge.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--judge-model", default=None, help="Optional model override for the judge provider.")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=0, help="Print running accuracy after every N cases.")
    parser.add_argument("--query-workers", type=int, default=1, help="Number of independent questions to run in parallel.")
    parser.add_argument("--scope-candidate-k", type=int, default=8)
    parser.add_argument("--scope-evidence-k", type=int, default=80)
    parser.add_argument("--graph-event-limit", type=int, default=96)
    parser.add_argument("--claim-top-k", type=int, default=32)
    parser.add_argument("--embedding-retrieval", choices=("none", "hybrid"), default="none")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument(
        "--embedding-cache",
        default=str(CACHE_DIR / "embedding_cache.groupmembench_graph_query.json"),
    )
    parser.add_argument("--embedding-batch-size", type=int, default=24)
    parser.add_argument(
        "--embedding-targets",
        default="event,scope",
        help="Comma-separated hybrid embedding rerank targets: event, scope, or event,scope.",
    )
    parser.add_argument(
        "--embedding-candidate-k",
        type=int,
        default=32,
        help="Backward-compatible maximum lexical candidates per message/scope stage to rerank with embeddings.",
    )
    parser.add_argument(
        "--event-embedding-candidate-k",
        type=int,
        default=0,
        help="Maximum lexical event/message candidates to rerank with embeddings. 0 uses --embedding-candidate-k.",
    )
    parser.add_argument(
        "--scope-embedding-candidate-k",
        type=int,
        default=0,
        help="Maximum lexical scope candidates to rerank with embeddings. 0 uses --embedding-candidate-k.",
    )
    parser.add_argument(
        "--embedding-message-weight",
        type=float,
        default=DEFAULT_EMBEDDING_MESSAGE_SCORE_WEIGHT,
        help="Score weight for event/message embedding hits after lexical candidate filtering.",
    )
    parser.add_argument(
        "--embedding-scope-weight",
        type=float,
        default=DEFAULT_EMBEDDING_SCOPE_SCORE_WEIGHT,
        help="Score weight for scope embedding hits after lexical candidate filtering.",
    )
    parser.add_argument("--embedding-base-url", default=None)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.groupmembench_graph_query.json"))
    parser.add_argument("--judge-cache", default=str(CACHE_DIR / "llm_cache.groupmembench_judge.json"))
    parser.add_argument("--output", default=str(RESULT_DIR / "results_groupmembench_graph_query_smoke.json"))
    parser.add_argument(
        "--row-checkpoint",
        default=None,
        help="Optional JSONL checkpoint of completed rows; reruns skip completed question indexes.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=0.0,
        help="Print periodic liveness progress while long LLM calls are in flight.",
    )
    return parser.parse_args()


def artifact_for_question(graph_dir: Path, question: GroupQuestion, graph_store_mode: str) -> Path:
    if graph_store_mode == "domain":
        return domain_graph_artifact_dir(graph_dir, question.domain)
    if graph_store_mode == "question":
        return graph_artifact_dir(graph_dir, question.domain, question.qtype, question.question_id)
    domain_artifact = domain_graph_artifact_dir(graph_dir, question.domain)
    if (domain_artifact / "manifest.json").exists():
        return domain_artifact
    return graph_artifact_dir(graph_dir, question.domain, question.qtype, question.question_id)


def ensure_artifact_matches_question(artifact: GraphArtifact, question: GroupQuestion) -> None:
    manifest = artifact.manifest
    if is_domain_graph_artifact(artifact):
        if str(manifest.get("domain") or "") != question.domain:
            raise ValueError(f"domain graph artifact does not match query domain: {manifest.get('domain')!r}")
        if manifest.get("question_conditioned") is True:
            raise ValueError("domain graph artifact is marked question_conditioned=True")
        return
    expected = {
        "case_id": question.case_id,
        "domain": question.domain,
        "qtype": question.qtype,
        "question_id": question.question_id,
    }
    mismatches = [
        f"{key}:artifact={manifest.get(key)!r}:query={value!r}"
        for key, value in expected.items()
        if str(manifest.get(key) or "") != str(value)
    ]
    if mismatches:
        raise ValueError(f"graph artifact does not match selected question: {'; '.join(mismatches)}")


def _embedding_query(question: GroupQuestion) -> str:
    return f"{question.asking_user_id} {question.question}".strip()


def parse_embedding_targets(raw_targets: object) -> set[str]:
    aliases = {
        "event": "event",
        "events": "event",
        "message": "event",
        "messages": "event",
        "scope": "scope",
        "scopes": "scope",
    }
    targets: set[str] = set()
    for part in str(raw_targets or "").split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key not in aliases:
            raise ValueError(f"unknown embedding target {part!r}; expected event, scope, or event,scope")
        targets.add(aliases[key])
    if not targets:
        raise ValueError("--embedding-targets must include event, scope, or both")
    return targets


def scope_embedding_documents(scopes: List[Any], messages: List[Any], adapter: Any) -> tuple[List[str], List[str]]:
    messages_by_scope: Dict[Tuple[str, str, str, str], List[Any]] = {}
    for message in messages:
        messages_by_scope.setdefault(message.scope_key(), []).append(message)
    doc_ids: List[str] = []
    documents: List[str] = []
    for scope in scopes:
        scoped_messages = messages_by_scope.get((scope.domain, scope.channel, scope.phase_name, scope.topic), [])
        parts = [scope.text()]
        parts.extend(document_text(message, adapter) for message in scoped_messages[:160])
        doc_ids.append(scope.scope_id)
        documents.append(" ".join(part for part in parts if part)[:12000])
    return doc_ids, documents


def embedding_scores_for_domain_query(
    question: GroupQuestion,
    adapter: Any,
    artifact: GraphArtifact,
    messages: List[Any],
    scopes: List[Any],
    args: argparse.Namespace,
) -> tuple[Dict[str, float], Dict[str, float], Dict[str, object]]:
    if args.embedding_retrieval != "hybrid":
        return {}, {}, {"enabled": False, "mode": "none"}
    cache_path = Path(args.embedding_cache)
    query = _embedding_query(question)
    namespace = f"groupmembench:{artifact.root}"
    targets = parse_embedding_targets(args.embedding_targets)
    fallback_candidate_limit = max(1, int(args.embedding_candidate_k))
    event_candidate_limit = max(1, int(args.event_embedding_candidate_k or fallback_candidate_limit))
    scope_candidate_limit = max(1, int(args.scope_embedding_candidate_k or fallback_candidate_limit))
    message_hits = []
    scope_hits = []
    candidate_message_ids: List[str] = []
    candidate_scope_ids: List[str] = []
    scope_doc_ids: List[str] = []

    if "event" in targets:
        message_index = OpenAIEmbeddingIndex(
            [message.event_id for message in messages],
            [document_text(message, adapter)[:12000] for message in messages],
            model=args.embedding_model,
            cache_path=cache_path,
            namespace=f"{namespace}:messages",
            batch_size=args.embedding_batch_size,
            base_url=args.embedding_base_url,
        )
        candidate_message_budget = min(max(args.scope_evidence_k, args.graph_event_limit, 32), event_candidate_limit)
        candidate_message_ids = [
            item[4].event_id
            for item in ranked_messages(messages, question, adapter)[: min(len(messages), candidate_message_budget)]
        ]
        message_hits = message_index.search(
            query,
            len(candidate_message_ids),
            allowed_doc_ids=candidate_message_ids,
            max_candidates=event_candidate_limit,
        )

    if "scope" in targets:
        scope_doc_ids, scope_docs = scope_embedding_documents(scopes, messages, adapter)
        scope_index = OpenAIEmbeddingIndex(
            scope_doc_ids,
            scope_docs,
            model=args.embedding_model,
            cache_path=cache_path,
            namespace=f"{namespace}:scopes",
            batch_size=args.embedding_batch_size,
            base_url=args.embedding_base_url,
        )
        candidate_scope_budget = min(max(args.scope_candidate_k * 4, 16), scope_candidate_limit)
        candidate_scope_ids = [
            scope.scope_id
            for _, _, scope in sorted(
                ((score_scope(question, scope), index, scope) for index, scope in enumerate(scopes)),
                key=lambda item: (-item[0], -item[2].event_count, item[1]),
            )[: min(len(scopes), candidate_scope_budget)]
        ]
        scope_hits = scope_index.search(
            query,
            len(candidate_scope_ids),
            allowed_doc_ids=candidate_scope_ids,
            max_candidates=scope_candidate_limit,
        )

    return (
        {hit.doc_id: hit.score for hit in message_hits},
        {hit.doc_id: hit.score for hit in scope_hits},
        {
            "enabled": True,
            "mode": "hybrid",
            "model": args.embedding_model,
            "targets": sorted(targets),
            "cache": str(cache_path),
            "candidate_limit": fallback_candidate_limit,
            "event_candidate_limit": event_candidate_limit,
            "scope_candidate_limit": scope_candidate_limit,
            "message_score_weight": round(max(0.0, float(args.embedding_message_weight)), 4),
            "scope_score_weight": round(max(0.0, float(args.embedding_scope_weight)), 4),
            "message_doc_count": len(messages),
            "message_candidate_count": len(candidate_message_ids),
            "scope_doc_count": len(scope_doc_ids),
            "scope_candidate_count": len(candidate_scope_ids),
            "top_message_hits": [
                {"event_id": hit.doc_id, "score": round(hit.score, 6)}
                for hit in message_hits[:10]
            ],
            "top_scope_hits": [
                {"scope_id": hit.doc_id, "score": round(hit.score, 6)}
                for hit in scope_hits[:10]
            ],
        },
    )


def answer_from_question_graph(
    client: LLMClient,
    question: GroupQuestion,
    artifact: GraphArtifact,
) -> Dict[str, object]:
    adapter = get_adapter(question.qtype)
    raw = compose_answer(client, question, adapter, artifact.locked_raw)
    trace = raw.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["graph_query_runner"] = {
        "graph_first": True,
        "graph_artifact_dir": str(artifact.root),
        "graph_store_mode": "question",
        "raw_corpus_loaded_for_graph_build": False,
    }
    raw["pipeline_trace"] = trace
    return raw


def answer_from_domain_graph(
    client: LLMClient,
    question: GroupQuestion,
    artifact: GraphArtifact,
    args: argparse.Namespace,
) -> Dict[str, object]:
    adapter = get_adapter(question.qtype)
    messages = messages_from_graph_artifact(artifact)
    if not messages:
        raise ValueError(f"domain graph artifact has no Episode/Event nodes: {artifact.root}")
    scopes = scopes_from_graph_artifact(artifact, messages)
    message_embedding_scores, scope_embedding_scores, embedding_debug = embedding_scores_for_domain_query(
        question,
        adapter,
        artifact,
        messages,
        scopes,
        args,
    )
    route, scope_route_debug = refine_scope_route_with_evidence(
        messages,
        question,
        adapter,
        scopes,
        args.scope_candidate_k,
        args.scope_evidence_k,
        message_embedding_scores=message_embedding_scores,
        scope_embedding_scores=scope_embedding_scores,
        message_embedding_score_weight=args.embedding_message_weight,
        scope_embedding_score_weight=args.embedding_scope_weight,
    )
    time_role_route = infer_group_time_role_with_llm(client, question, adapter)
    routed_time_role = str(time_role_route.get("time_role") or "updated_at")
    scope_messages = filter_messages_for_scope(messages, route.target_scope)
    graph_messages, retrieval_debug = select_graph_build_messages(
        scope_messages,
        question,
        adapter,
        route,
        args.graph_event_limit,
        routed_time_role,
        embedding_scores=message_embedding_scores,
        embedding_score_weight=args.embedding_message_weight,
    )
    retrieval_debug["scope_route_debug"] = scope_route_debug
    retrieval_debug["time_role_route"] = time_role_route
    retrieval_debug["embedding_retrieval"] = embedding_debug
    retrieval_debug["in_scope_episode_event_count"] = len(scope_messages)
    retrieval_debug["episode_event_context_count"] = len(graph_messages)
    selected_claims = claims_from_graph_artifact(artifact, [message.event_id for message in graph_messages])
    locked_raw = complete_graph_state_packet_from_claims(
        client,
        question,
        adapter,
        route,
        selected_claims,
        graph_messages,
        scope_messages,
        args.claim_top_k,
        routed_time_role,
        claim_source="offline_domain_graph",
    )
    raw = compose_answer(client, question, adapter, locked_raw)
    trace = raw.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["domain_graph_query"] = {
        "scope_route": route.as_dict(),
        "retrieval_debug": retrieval_debug,
        "prebuilt_claim_count": len(selected_claims),
    }
    trace["graph_query_runner"] = {
        "graph_first": True,
        "graph_artifact_dir": str(artifact.root),
        "graph_store_mode": "domain",
        "raw_corpus_loaded_for_graph_build": False,
    }
    raw["pipeline_trace"] = trace
    return raw


def answer_from_graph(
    client: LLMClient,
    question: GroupQuestion,
    artifact: GraphArtifact,
    args: argparse.Namespace,
) -> Dict[str, object]:
    if is_domain_graph_artifact(artifact):
        return answer_from_domain_graph(client, question, artifact, args)
    return answer_from_question_graph(client, question, artifact)


def raw_candidate_event_ids(raw: Dict[str, object], artifact: GraphArtifact) -> List[str]:
    packet = raw.get("state_packet", {})
    if isinstance(packet, dict) and isinstance(packet.get("candidate_events"), list):
        return [str(event_id) for event_id in packet["candidate_events"]]
    return artifact.candidate_event_ids


def trace_payload(raw: Dict[str, object]) -> Dict[str, object]:
    trace = raw.get("pipeline_trace", {})
    return trace if isinstance(trace, dict) else {}


def build_row(
    question: GroupQuestion,
    artifact: GraphArtifact,
    raw: Dict[str, object],
    evaluation: Optional[Dict[str, object]],
) -> Dict[str, object]:
    trace = trace_payload(raw)
    domain_query = trace.get("domain_graph_query", {})
    if not isinstance(domain_query, dict):
        domain_query = {}
    retrieval_debug = domain_query.get("retrieval_debug")
    if not isinstance(retrieval_debug, dict):
        retrieval_debug = artifact.manifest.get("retrieval_debug", {})
    if not isinstance(retrieval_debug, dict):
        retrieval_debug = {}
    scope_route = domain_query.get("scope_route")
    if not isinstance(scope_route, dict):
        scope_route = artifact.manifest.get("scope_route", {})
    if not isinstance(scope_route, dict):
        scope_route = {}
    candidate_event_ids = raw_candidate_event_ids(raw, artifact)
    return {
        "case_id": question.case_id,
        "domain": question.domain,
        "qtype": question.qtype,
        "question_id": question.question_id,
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "gold_answer": question.answer,
        "variant": "domain_graph_store_query" if is_domain_graph_artifact(artifact) else "graph_store_query",
        "answer": str(raw.get("answer", "")),
        "scope_route": scope_route,
        "time_role_route": retrieval_debug.get("time_role_route"),
        "candidate_event_ids": candidate_event_ids,
        "in_scope_episode_event_count": int(
            retrieval_debug.get("in_scope_episode_event_count", len(candidate_event_ids))
        ),
        "retrieval_debug": retrieval_debug,
        "graph_artifact_dir": str(artifact.root),
        "model_output": raw,
        "evaluation": evaluation
        or {
            "judge_method": "not_run",
            "correct": None,
            "score": None,
            "reasoning": "Graph query runner did not evaluate this answer.",
        },
    }


def make_client(provider: str, cache_path: str, use_cache: bool, model_override: Optional[str] = None) -> tuple[LLMClient, str]:
    api_key, model, api_base = provider_config(provider)
    if model_override:
        model = model_override
    return (
        LLMClient(
            provider=provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            cache_path=Path(cache_path),
            use_cache=use_cache,
        ),
        model,
    )


def print_summary(output: Dict[str, Any]) -> None:
    summary = output["summary"]
    print("GroupMemBench graph query runner")
    print(f"cases={summary['n_cases']} overall_accuracy={summary['overall_accuracy']}")
    print(f"accuracy_by_qtype={summary['accuracy_by_qtype']}")
    print(
        "trace rates: "
        f"scope={summary['trace_has_scope_rate']} "
        f"claim={summary['trace_has_claim_rate']} "
        f"relation={summary['trace_has_relation_rate']} "
        f"state_facet={summary['trace_has_state_facet_rate']}"
    )


def write_output(output: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {output_path}")


def load_row_checkpoint(checkpoint_path: Optional[str]) -> List[Tuple[int, Dict[str, object]]]:
    if not checkpoint_path:
        return []
    path = Path(checkpoint_path)
    if not path.exists():
        return []
    rows_by_index: Dict[int, Dict[str, object]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"row checkpoint has invalid JSON on line {line_number}: {path}") from exc
        index = payload.get("index")
        row = payload.get("row")
        if not isinstance(index, int) or not isinstance(row, dict):
            raise ValueError(f"row checkpoint line {line_number} must contain integer index and object row: {path}")
        rows_by_index[index] = row
    return sorted(rows_by_index.items(), key=lambda item: item[0])


def append_row_checkpoint(checkpoint_path: Optional[str], row_result: Tuple[int, Dict[str, object]]) -> None:
    if not checkpoint_path:
        return
    path = Path(checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    index, row = row_result
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps({"index": index, "row": row}, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    questions = load_selected_questions(args.domains, args.qtypes, args.limit_per_type, args.limit_cases)
    if not questions:
        print("no GroupMemBench questions selected", file=sys.stderr)
        return 2
    graph_dir = Path(args.graph_dir)
    missing = [
        str(artifact_for_question(graph_dir, question, args.graph_store_mode))
        for question in questions
        if not artifact_for_question(graph_dir, question, args.graph_store_mode).exists()
    ]
    if missing and not args.allow_missing:
        print("missing graph artifacts; run domain_graph_builder first:", file=sys.stderr)
        for path in missing:
            print(f"- {path}", file=sys.stderr)
        return 2

    load_dotenv()
    try:
        client, model = make_client(args.provider, args.cache, not args.no_cache, args.model)
        judge_client: Optional[LLMClient] = None
        judge_model: Optional[str] = None
        if args.judge:
            judge_client, judge_model = make_client(
                args.judge_provider,
                args.judge_cache,
                not args.no_cache,
                args.judge_model,
            )
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    indexed_rows: List[Tuple[int, Dict[str, object]]] = load_row_checkpoint(args.row_checkpoint)
    completed_indexes = {index for index, _ in indexed_rows}
    if completed_indexes:
        print(
            f"loaded row checkpoint rows={len(completed_indexes)} path={args.row_checkpoint}",
            flush=True,
        )
    heartbeat_stop = Event()

    if args.heartbeat_seconds > 0:
        heartbeat_seconds = max(1.0, float(args.heartbeat_seconds))

        def heartbeat() -> None:
            while not heartbeat_stop.wait(heartbeat_seconds):
                print(
                    f"heartbeat completed={len(completed_indexes)}/{len(questions)}",
                    flush=True,
                )

        Thread(target=heartbeat, daemon=True).start()

    artifact_cache: Dict[str, GraphArtifact] = {}
    artifact_cache_lock = RLock()

    def cached_artifact(path: Path) -> GraphArtifact:
        key = str(path)
        with artifact_cache_lock:
            artifact = artifact_cache.get(key)
            if artifact is None:
                artifact = load_graph_artifact(path)
                artifact_cache[key] = artifact
            return artifact

    def run_one(index: int, question: GroupQuestion) -> Optional[Tuple[int, Dict[str, object]]]:
        artifact_path = artifact_for_question(graph_dir, question, args.graph_store_mode)
        if not artifact_path.exists() and args.allow_missing:
            print(f"skipping missing graph / {question.case_id}", flush=True)
            return None
        print(f"querying graph / {question.case_id} ({index}/{len(questions)})", flush=True)
        artifact = cached_artifact(artifact_path)
        ensure_artifact_matches_question(artifact, question)
        raw = answer_from_graph(client, question, artifact, args)
        evaluation = judge_answer(judge_client, question, str(raw.get("answer", "")))
        time.sleep(0.2)
        return index, build_row(question, artifact, raw, evaluation)

    def append_progress(row_result: Optional[Tuple[int, Dict[str, object]]]) -> None:
        if row_result is None:
            return
        index, _ = row_result
        if index in completed_indexes:
            return
        append_row_checkpoint(args.row_checkpoint, row_result)
        completed_indexes.add(index)
        indexed_rows.append(row_result)
        rows = [row for _, row in indexed_rows]
        if args.progress_every > 0 and (len(rows) % args.progress_every == 0 or len(rows) == len(questions)):
            running = summarize(rows)
            print(
                f"progress cases={running['n_cases']} "
                f"overall_accuracy={running['overall_accuracy']} "
                f"accuracy_by_qtype={running['accuracy_by_qtype']}",
                flush=True,
            )

    try:
        query_workers = min(max(1, args.query_workers), len(questions))
        if query_workers == 1:
            for index, question in enumerate(questions, start=1):
                if index in completed_indexes:
                    continue
                append_progress(run_one(index, question))
        else:
            print(f"parallel query workers={query_workers} cases={len(questions)}", flush=True)
            with ThreadPoolExecutor(max_workers=query_workers) as executor:
                futures = [
                    executor.submit(run_one, index, question)
                    for index, question in enumerate(questions, start=1)
                    if index not in completed_indexes
                ]
                for future in as_completed(futures):
                    append_progress(future.result())
    except LLMRequestError as exc:
        print("\nLLM request failed during graph query.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("\nLLM output failed graph-query JSON validation.", file=sys.stderr)
        print(f"provider: {args.provider}", file=sys.stderr)
        print(f"model: {model}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        heartbeat_stop.set()

    rows = [row for _, row in sorted(indexed_rows, key=lambda item: item[0])]
    output = {
        "benchmark": "GroupMemBench",
        "variant": "domain_graph_store_query",
        "graph_dir": str(graph_dir),
        "graph_store_mode": args.graph_store_mode,
        "domains": list(args.domains),
        "qtypes": list(args.qtypes),
        "provider": args.provider,
        "model": model,
        "embedding_retrieval": {
            "mode": args.embedding_retrieval,
            "model": args.embedding_model if args.embedding_retrieval == "hybrid" else None,
            "targets": sorted(parse_embedding_targets(args.embedding_targets))
            if args.embedding_retrieval == "hybrid"
            else [],
            "cache": args.embedding_cache if args.embedding_retrieval == "hybrid" else None,
            "candidate_k": args.embedding_candidate_k if args.embedding_retrieval == "hybrid" else 0,
            "event_candidate_k": (args.event_embedding_candidate_k or args.embedding_candidate_k)
            if args.embedding_retrieval == "hybrid"
            else 0,
            "scope_candidate_k": (args.scope_embedding_candidate_k or args.embedding_candidate_k)
            if args.embedding_retrieval == "hybrid"
            else 0,
            "message_score_weight": round(max(0.0, float(args.embedding_message_weight)), 4)
            if args.embedding_retrieval == "hybrid"
            else 0.0,
            "scope_score_weight": round(max(0.0, float(args.embedding_scope_weight)), 4)
            if args.embedding_retrieval == "hybrid"
            else 0.0,
        },
        "judge_provider": args.judge_provider if args.judge else None,
        "judge_model": judge_model if args.judge else None,
        "summary": summarize(rows),
        "rows": rows,
    }
    print_summary(output)
    write_output(output, Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.groupmembench.adapters import TASK_TYPES, get_adapter  # noqa: E402
from pipeline.external.groupmembench.judging import judge_answer, summarize  # noqa: E402
from pipeline.external.groupmembench.loader import (  # noqa: E402
    CACHE_DIR,
    DOMAINS,
    GroupMessage,
    GroupQuestion,
    RESULT_DIR,
    build_scope_inventory,
    filter_messages_for_scope,
    load_domain_messages,
    load_questions,
)
from pipeline.external.groupmembench.retrieval import (  # noqa: E402
    refine_scope_route_with_evidence,
    select_global_messages,
    select_graph_build_messages,
)
from pipeline.external.groupmembench.staged import (  # noqa: E402
    dry_run_graph_scope_state_packet,
    run_bm25_message_baseline,
    run_graph_scope_state_packet,
)
from pipeline.external.groupmembench.time_roles import infer_group_time_role, infer_group_time_role_with_llm  # noqa: E402


SUPPORTED_VARIANTS = ("graph_scope_state_packet", "bm25_message")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GroupMemBench through the graph scope-state pipeline.")
    parser.add_argument("--domains", nargs="+", choices=DOMAINS, default=["Finance", "Technology"])
    parser.add_argument("--qtypes", nargs="+", choices=TASK_TYPES, default=list(TASK_TYPES))
    parser.add_argument("--variants", nargs="+", default=["graph_scope_state_packet"])
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument(
        "--graph-provider",
        choices=("openai", "deepseek"),
        default=None,
        help="Provider for graph construction stages: Claim extraction, validity, and StateFacet selection. Defaults to --provider.",
    )
    parser.add_argument("--judge", action="store_true", help="Run the official-style GroupMemBench LLM judge.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=20, help="Candidate message count for the bm25_message baseline.")
    parser.add_argument("--scope-candidate-k", type=int, default=8)
    parser.add_argument("--scope-evidence-k", type=int, default=80)
    parser.add_argument("--graph-event-limit", type=int, default=96, help="Scoped Episode/Event budget for Claim graph construction; 0 means full selected scope.")
    parser.add_argument("--claim-chunk-size", type=int, default=16)
    parser.add_argument("--claim-top-k", type=int, default=32, help="Claim nodes passed to StateFacet selection after Claim graph retrieval.")
    parser.add_argument("--dry-run", action="store_true", help="Validate routing/retrieval/graph skeleton without LLM calls.")
    parser.add_argument("--list-tasks", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output", default=str(RESULT_DIR / "results_groupmembench_smoke.json"))
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.groupmembench.json"))
    parser.add_argument(
        "--graph-cache",
        default=None,
        help="Cache for graph construction stages. Defaults to --cache when --graph-provider is omitted.",
    )
    parser.add_argument("--judge-cache", default=str(CACHE_DIR / "llm_cache.groupmembench_judge.json"))
    return parser.parse_args()


def load_selected_questions(domains: Sequence[str], qtypes: Sequence[str], limit_per_type: int, limit_cases: int) -> List[GroupQuestion]:
    selected: List[GroupQuestion] = []
    for domain in domains:
        for qtype in qtypes:
            questions = load_questions(domain, qtype)
            if limit_per_type:
                questions = questions[:limit_per_type]
            selected.extend(questions)
    if limit_cases:
        selected = selected[:limit_cases]
    return selected


def load_messages_by_domain(domains: Sequence[str]) -> Dict[str, List[GroupMessage]]:
    return {domain: load_domain_messages(domain) for domain in domains}


def build_case_context(
    question: GroupQuestion,
    messages_by_domain: Dict[str, List[GroupMessage]],
    scope_candidate_k: int,
    scope_evidence_k: int,
    graph_event_limit: int,
    time_role_route: Optional[Dict[str, object]] = None,
) -> Tuple[Dict[str, object], List[GroupMessage], Dict[str, object]]:
    adapter = get_adapter(question.qtype)
    domain_messages = messages_by_domain[question.domain]
    scopes = build_scope_inventory(domain_messages)
    route, scope_route_debug = refine_scope_route_with_evidence(
        domain_messages,
        question,
        adapter,
        scopes,
        scope_candidate_k,
        scope_evidence_k,
    )
    if time_role_route is None:
        time_role_route = infer_group_time_role(question, adapter)
    routed_time_role = str(time_role_route.get("time_role") or "updated_at")
    scope_messages = filter_messages_for_scope(domain_messages, route.target_scope)
    graph_messages, retrieval_debug = select_graph_build_messages(
        scope_messages,
        question,
        adapter,
        route,
        graph_event_limit,
        routed_time_role,
    )
    retrieval_debug["scope_route_debug"] = scope_route_debug
    retrieval_debug["time_role_route"] = time_role_route
    retrieval_debug["in_scope_episode_event_count"] = len(scope_messages)
    retrieval_debug["episode_event_context_count"] = len(graph_messages)
    context = {
        "adapter": adapter,
        "route": route,
        "time_role_route": time_role_route,
        "routed_time_role": routed_time_role,
        "scope_messages": scope_messages,
        "retrieval_debug": retrieval_debug,
    }
    return context, graph_messages, route.as_dict()


def run_dry_case(
    question: GroupQuestion,
    messages_by_domain: Dict[str, List[GroupMessage]],
    variant: str,
    args: argparse.Namespace,
) -> Dict[str, object]:
    adapter = get_adapter(question.qtype)
    if variant == "graph_scope_state_packet":
        time_role_route = infer_group_time_role_with_llm(graph_client, question, adapter)
        context, candidates, route_payload = build_case_context(
            question,
            messages_by_domain,
            args.scope_candidate_k,
            args.scope_evidence_k,
            args.graph_event_limit,
            time_role_route,
        )
        route = context["route"]
        raw = dry_run_graph_scope_state_packet(
            question,
            route,
            candidates,
            context["scope_messages"],
            context["routed_time_role"],
        )
        retrieval_debug = context["retrieval_debug"]
    elif variant == "bm25_message":
        domain_messages = messages_by_domain[question.domain]
        candidates, retrieval_debug = select_global_messages(domain_messages, question, adapter, args.top_k)
        route_payload = {}
        raw = {
            "answer": "",
            "pipeline_trace": {
                "pipeline": "bm25_message",
                "dry_run": True,
                "candidate_events": [message.event_id for message in candidates],
            },
        }
    else:
        raise ValueError(f"unsupported variant={variant}")
    return build_row(question, variant, raw, route_payload, retrieval_debug, candidates, evaluation=None)


def run_llm_case(
    client: LLMClient,
    graph_client: LLMClient,
    judge_client: Optional[LLMClient],
    question: GroupQuestion,
    messages_by_domain: Dict[str, List[GroupMessage]],
    variant: str,
    args: argparse.Namespace,
) -> Dict[str, object]:
    adapter = get_adapter(question.qtype)
    if variant == "graph_scope_state_packet":
        context, candidates, route_payload = build_case_context(
            question,
            messages_by_domain,
            args.scope_candidate_k,
            args.scope_evidence_k,
            args.graph_event_limit,
        )
        raw = run_graph_scope_state_packet(
            graph_client,
            question,
            adapter,
            context["route"],
            candidates,
            context["scope_messages"],
            args.claim_chunk_size,
            args.claim_top_k,
            context["routed_time_role"],
            composer_client=client,
        )
        retrieval_debug = context["retrieval_debug"]
    elif variant == "bm25_message":
        domain_messages = messages_by_domain[question.domain]
        candidates, retrieval_debug = select_global_messages(domain_messages, question, adapter, args.top_k)
        route_payload = {}
        raw = run_bm25_message_baseline(client, question, candidates)
    else:
        raise ValueError(f"unsupported variant={variant}")
    evaluation = judge_answer(judge_client, question, str(raw.get("answer", "")))
    return build_row(question, variant, raw, route_payload, retrieval_debug, candidates, evaluation=evaluation)


def build_row(
    question: GroupQuestion,
    variant: str,
    raw: Dict[str, object],
    route_payload: Dict[str, object],
    retrieval_debug: Dict[str, object],
    candidates: Sequence[GroupMessage],
    evaluation: Optional[Dict[str, object]],
) -> Dict[str, object]:
    return {
        "case_id": question.case_id,
        "domain": question.domain,
        "qtype": question.qtype,
        "question_id": question.question_id,
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "gold_answer": question.answer,
        "variant": variant,
        "answer": str(raw.get("answer", "")),
        "scope_route": route_payload,
        "time_role_route": retrieval_debug.get("time_role_route"),
        "candidate_event_ids": [message.event_id for message in candidates],
        "in_scope_episode_event_count": int(retrieval_debug.get("in_scope_episode_event_count", len(candidates))),
        "retrieval_debug": retrieval_debug,
        "model_output": raw,
        "evaluation": evaluation or {
            "judge_method": "not_run",
            "correct": None,
            "score": None,
            "reasoning": "Dry run does not evaluate answers.",
        },
    }


def summarize_dry_rows(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    return {
        "n_cases": len(rows),
        "case_counts": {
            "by_domain": dict(Counter(str(row["domain"]) for row in rows)),
            "by_qtype": dict(Counter(str(row["qtype"]) for row in rows)),
            "by_variant": dict(Counter(str(row["variant"]) for row in rows)),
        },
        "scope_routed": sum(1 for row in rows if row.get("scope_route", {}).get("target_scope_id")),
        "candidate_events_nonempty": sum(1 for row in rows if row.get("candidate_event_ids")),
    }


def print_summary(output: Dict[str, object], dry_run: bool) -> None:
    print("GroupMemBench graph adapter")
    if dry_run:
        summary = output["summary"]
        print(f"dry_run=true cases={summary['n_cases']}")
        print(f"scope_routed={summary['scope_routed']} candidate_events_nonempty={summary['candidate_events_nonempty']}")
        print(f"by_qtype={summary['case_counts']['by_qtype']}")
        return
    summary = output["summary"]
    print(f"cases={summary['n_cases']} overall_accuracy={summary['overall_accuracy']}")
    print(f"accuracy_by_qtype={summary['accuracy_by_qtype']}")
    print(
        "trace rates: "
        f"scope={summary['trace_has_scope_rate']} "
        f"claim={summary['trace_has_claim_rate']} "
        f"relation={summary['trace_has_relation_rate']} "
        f"state_facet={summary['trace_has_state_facet_rate']}"
    )


def write_output(output: Dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {output_path}")


def main() -> int:
    args = parse_args()
    if args.list_tasks:
        print("Supported GroupMemBench qtypes:")
        for qtype in TASK_TYPES:
            adapter = get_adapter(qtype)
            print(f"- {qtype}: {adapter.task_name}")
        print("Supported variants:")
        for variant in SUPPORTED_VARIANTS:
            print(f"- {variant}")
        return 0

    for variant in args.variants:
        if variant not in SUPPORTED_VARIANTS:
            known = ", ".join(SUPPORTED_VARIANTS)
            print(f"unsupported GroupMemBench variant: {variant}; supported variants: {known}", file=sys.stderr)
            return 2

    questions = load_selected_questions(args.domains, args.qtypes, args.limit_per_type, args.limit_cases)
    if not questions:
        print("no GroupMemBench questions selected", file=sys.stderr)
        return 2
    messages_by_domain = load_messages_by_domain(args.domains)

    rows: List[Dict[str, object]] = []
    if args.dry_run:
        for variant in args.variants:
            for question in questions:
                rows.append(run_dry_case(question, messages_by_domain, variant, args))
        output = {
            "benchmark": "GroupMemBench",
            "dry_run": True,
            "variants": list(args.variants),
            "domains": list(args.domains),
            "qtypes": list(args.qtypes),
            "summary": summarize_dry_rows(rows),
            "rows": rows,
        }
        print_summary(output, dry_run=True)
        write_output(output, Path(args.output))
        return 0

    load_dotenv()
    try:
        api_key, model, api_base = provider_config(args.provider)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    client = LLMClient(
        provider=args.provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        cache_path=Path(args.cache),
        use_cache=not args.no_cache,
    )
    graph_provider = args.graph_provider or args.provider
    graph_model = model
    graph_client = client
    if args.graph_provider:
        try:
            graph_api_key, graph_model, graph_api_base = provider_config(graph_provider)
        except RuntimeError as exc:
            print(f"Graph config error: {exc}", file=sys.stderr)
            return 2
        graph_client = LLMClient(
            provider=graph_provider,
            model=graph_model,
            api_key=graph_api_key,
            api_base=graph_api_base,
            cache_path=Path(args.graph_cache or args.cache),
            use_cache=not args.no_cache,
        )
    judge_client: Optional[LLMClient] = None
    judge_model: Optional[str] = None
    if args.judge:
        try:
            judge_api_key, judge_model, judge_api_base = provider_config(args.judge_provider)
        except RuntimeError as exc:
            print(f"Judge config error: {exc}", file=sys.stderr)
            return 2
        judge_client = LLMClient(
            provider=args.judge_provider,
            model=judge_model,
            api_key=judge_api_key,
            api_base=judge_api_base,
            cache_path=Path(args.judge_cache),
            use_cache=not args.no_cache,
        )

    try:
        for variant in args.variants:
            for index, question in enumerate(questions, start=1):
                print(f"running {variant} / {question.case_id} ({index}/{len(questions)})", flush=True)
                rows.append(run_llm_case(client, graph_client, judge_client, question, messages_by_domain, variant, args))
                time.sleep(0.2)
    except LLMRequestError as exc:
        print("\nLLM request failed.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = {
        "benchmark": "GroupMemBench",
        "variants": list(args.variants),
        "domains": list(args.domains),
        "qtypes": list(args.qtypes),
        "provider": args.provider,
        "model": model,
        "graph_provider": graph_provider,
        "graph_model": graph_model,
        "judge_provider": args.judge_provider if judge_client else None,
        "judge_model": judge_model,
        "summary": summarize(rows),
        "rows": rows,
    }
    print_summary(output, dry_run=False)
    write_output(output, Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

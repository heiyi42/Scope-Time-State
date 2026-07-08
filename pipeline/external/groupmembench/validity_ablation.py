from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
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
from pipeline.external.groupmembench.adapters.base import TaskAdapter  # noqa: E402
from pipeline.external.groupmembench.judging import judge_answer, mean  # noqa: E402
from pipeline.external.groupmembench.loader import CACHE_DIR, DOMAINS, GroupMessage, GroupQuestion, RESULT_DIR  # noqa: E402
from pipeline.external.groupmembench.prompts import (  # noqa: E402
    state_selection_system_prompt,
    state_selection_user_prompt,
    validity_system_prompt,
    validity_user_prompt,
)
from pipeline.external.groupmembench.runner import (  # noqa: E402
    build_case_context,
    load_messages_by_domain,
    load_selected_questions,
    write_output,
)
from pipeline.external.groupmembench.staged import (  # noqa: E402
    compose_answer,
    extract_claim_graph,
    fallback_state_selection_raw,
    raw_state_packet,
    select_claim_candidates,
    source_messages_for_claims,
    validate_and_repair_graph_packet,
    validate_and_repair_validity_packet,
)
from pipeline.external.groupmembench.time_roles import time_role_instruction  # noqa: E402


VALIDITY_VARIANTS = ("baseline", "target_matrix", "same_target")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run GroupMemBench validity-only ablations with frozen Scope/Event/Claim candidates."
    )
    parser.add_argument("--domains", nargs="+", choices=DOMAINS, default=["Finance"])
    parser.add_argument("--qtypes", nargs="+", choices=TASK_TYPES, default=["knowledge_update"])
    parser.add_argument("--validity-variants", nargs="+", choices=VALIDITY_VARIANTS, default=list(VALIDITY_VARIANTS))
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument(
        "--validity-provider",
        choices=("openai", "deepseek"),
        default=None,
        help="Provider used only for the Claim validity stage. Defaults to --provider.",
    )
    parser.add_argument("--judge", action="store_true", help="Run the official-style GroupMemBench LLM judge.")
    parser.add_argument("--judge-provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=0)
    parser.add_argument("--scope-candidate-k", type=int, default=8)
    parser.add_argument("--scope-evidence-k", type=int, default=80)
    parser.add_argument("--graph-event-limit", type=int, default=96)
    parser.add_argument("--claim-chunk-size", type=int, default=16)
    parser.add_argument("--claim-top-k", type=int, default=32)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output", default=str(RESULT_DIR / "results_groupmembench_validity_ablation.json"))
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.groupmembench_validity_ablation.json"))
    parser.add_argument(
        "--validity-cache",
        default=None,
        help="Cache for the validity-stage client. Defaults to --cache when --validity-provider is omitted.",
    )
    parser.add_argument("--judge-cache", default=str(CACHE_DIR / "llm_cache.groupmembench_validity_ablation_judge.json"))
    return parser.parse_args()


def ablation_validity_system_prompt(adapter: TaskAdapter, variant: str) -> str:
    base = validity_system_prompt(adapter)
    if variant == "target_matrix":
        return (
            base
            + "\n\nAblation variant: target_matrix. First classify every Claim's relation to the query target, "
            "then decide validity. This is diagnostic only: do not use gold answers or hidden metadata."
        )
    if variant == "same_target":
        return (
            base
            + "\n\nAblation variant: same_target. Be conservative about CORRECTS/SUPERSEDES: a newer Claim can "
            "supersede an older Claim only when both assert the same query-conditioned StateFacet target."
        )
    return base


def ablation_validity_user_prompt(
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: Any,
    candidate_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
    variant: str,
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    routed_time_role: Optional[str] = None,
    validation_error: Optional[Dict[str, object]] = None,
    compact: bool = False,
) -> str:
    if variant == "baseline":
        return validity_user_prompt(
            question,
            adapter,
            route,
            candidate_claims,
            source_messages,
            scope_messages,
            routed_time_role,
        )

    scope_messages = scope_messages or source_messages
    task_by_variant = {
        "target_matrix": (
            "For each candidate Claim, first set target_match to direct_target, adjacent_target, or background. "
            "direct_target means the Claim itself answers the requested current state target. adjacent_target means "
            "the Claim is in the same project/scope but is about implementation progress, review status, risk, "
            "sign-off mechanics, or cleanup that does not change the requested state value. Accept only direct_target "
            "Claims that are current valid. If a richer Claim and a shorter duplicate overlap, prefer the richer Claim "
            "that preserves owner/dependency/scope qualifiers. Return claim_assessments for diagnosis plus validity_packet."
        ),
        "same_target": (
            "Decide current validity and relations, but require every CORRECTS or SUPERSEDES edge to be same-target: "
            "the from/to Claims must assert competing values for the same query-conditioned StateFacet. Do not mark a "
            "Claim stale only because a later adjacent status, review, sign-off, implementation-freeze, or process gate "
            "message exists. Accept the Claim(s) that directly define the current requested state value."
        ),
    }
    if compact:
        task_suffix = (
            " Retry mode: return only validity_packet. Do not include claim_assessments or long explanations. "
            "Keep reasons short."
        )
    else:
        task_suffix = ""
    payload: Dict[str, object] = {
        "cache_namespace": {
            "benchmark": "GroupMemBench",
            "domain": question.domain,
            "qtype": question.qtype,
            "question_id": question.question_id,
            "stage": "claim_validity_ablation",
            "variant": variant,
        },
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "target_scope": route.target_scope.as_dict(),
        "candidate_scope_nodes": route.candidate_scopes,
        "routed_time_role": routed_time_role,
        "time_role_contract": time_role_instruction(routed_time_role),
        "in_scope_episode_event_count": len(scope_messages),
        "in_scope_episode_event_ids": [message.event_id for message in scope_messages],
        "candidate_claims": list(candidate_claims),
        "source_events": [message.visible_event() for message in source_messages],
        "task": task_by_variant[variant] + task_suffix,
        "output_schema": {
            "validity_packet": {
                "target_scope_id": "must equal target_scope.scope_id",
                "accepted_current_claims": [
                    {
                        "claim_id": "claim id copied from candidate_claims",
                        "facet_type": "short facet target",
                        "reason": "why this claim is current valid for the query",
                    }
                ],
                "rejected_claims": [
                    {
                        "claim_id": "claim id copied from candidate_claims",
                        "event_id": "source event id copied from the claim",
                        "validity": "stale|superseded|invalidated|conflicting|discussion_only|wrong_target|irrelevant|insufficient_evidence",
                        "reason": "why this claim must not support an active StateFacet",
                    }
                ],
                "relations": [
                    {
                        "type": "CORRECTS|SUPERSEDES|CONFLICTS_WITH",
                        "from": "newer_or_left_claim_id",
                        "to": "older_or_right_claim_id",
                        "evidence_event_ids": ["Msg_..."],
                        "reason": "why this relation controls current validity",
                    }
                ],
            },
        },
    }
    if not compact:
        payload["output_schema"]["claim_assessments"] = [
            {
                "claim_id": "claim id copied from candidate_claims",
                "target_match": "direct_target|adjacent_target|background",
                "validity": "current_valid|stale|superseded|invalidated|conflicting|discussion_only|wrong_target|irrelevant",
                "same_target_as": ["claim ids that assert the same target if relevant"],
                "reason": "brief diagnostic reason",
            }
        ]
    if validation_error:
        payload["previous_output_error"] = validation_error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def complete_validity_variant(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: Any,
    selected_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
    variant: str,
    scope_messages: Optional[Sequence[GroupMessage]] = None,
    routed_time_role: Optional[str] = None,
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object]]:
    system = ablation_validity_system_prompt(adapter, variant)
    try:
        raw = client.complete_json(
            system,
            ablation_validity_user_prompt(
                question,
                adapter,
                route,
                selected_claims,
                source_messages,
                variant,
                scope_messages,
                routed_time_role,
            ),
        )
    except ValueError as exc:
        recovery = {"initial_parse_error": str(exc)[:500], "compact_retry": True}
        try:
            raw = client.complete_json(
                system,
                ablation_validity_user_prompt(
                    question,
                    adapter,
                    route,
                    selected_claims,
                    source_messages,
                    variant,
                    scope_messages,
                    routed_time_role,
                    validation_error={
                        "error": str(exc)[:500],
                        "retry_instruction": "Return compact valid JSON with validity_packet only.",
                    },
                    compact=True,
                ),
            )
            raw["validity_ablation_recovery"] = {**recovery, "compact_retry_succeeded": True}
        except ValueError as retry_exc:
            raw = {
                "validity_packet": {
                    "target_scope_id": route.target_scope.scope_id,
                    "accepted_current_claims": [],
                    "rejected_claims": [],
                    "relations": [],
                },
                "validity_ablation_recovery": {
                    **recovery,
                    "compact_retry_succeeded": False,
                    "fallback_empty_packet": True,
                    "retry_parse_error": str(retry_exc)[:500],
                },
            }
    packet, validation = validate_and_repair_validity_packet(
        raw,
        question,
        route,
        selected_claims,
        source_messages,
    )
    return packet, validation, raw


def selected_claims_with_validity(
    selected_claims: Sequence[Dict[str, object]],
    validity_packet: Dict[str, object],
) -> List[Dict[str, object]]:
    status_by_claim = {
        str(item.get("claim_id", "")): "current_valid"
        for item in validity_packet.get("accepted_current_claims", [])
        if isinstance(item, dict)
    }
    for item in validity_packet.get("rejected_claims", []):
        if isinstance(item, dict):
            status_by_claim.setdefault(str(item.get("claim_id", "")), str(item.get("validity") or "rejected"))
    annotated: List[Dict[str, object]] = []
    for claim in selected_claims:
        item = deepcopy(claim)
        claim_id = str(item.get("claim_id", ""))
        if claim_id in status_by_claim:
            item["validity_status"] = status_by_claim[claim_id]
        annotated.append(item)
    return annotated


def complete_state_from_frozen_validity(
    client: LLMClient,
    question: GroupQuestion,
    adapter: TaskAdapter,
    route: Any,
    graph_messages: Sequence[GroupMessage],
    scope_messages: Sequence[GroupMessage],
    claim_graph: Dict[str, object],
    selected_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
    claim_selection: Dict[str, object],
    validity_packet: Dict[str, object],
    validity_validation: Dict[str, object],
    validity_raw: Dict[str, object],
    validity_variant: str,
    claim_chunk_size: int,
    routed_time_role: Optional[str] = None,
) -> Dict[str, object]:
    selected_for_state = selected_claims_with_validity(selected_claims, validity_packet)
    state_selection_recovery: Dict[str, object] = {}
    try:
        raw = client.complete_json(
            state_selection_system_prompt(adapter),
            state_selection_user_prompt(
                question,
                adapter,
                route,
                selected_for_state,
                validity_packet,
                source_messages,
                scope_messages,
                routed_time_role,
            ),
        )
    except ValueError as exc:
        retry_claims = [
            claim
            for claim in selected_for_state
            if str(claim.get("validity_status", "")) == "current_valid"
        ] or selected_for_state[: min(8, len(selected_for_state))]
        retry_source_messages = source_messages_for_claims(retry_claims, source_messages)
        state_selection_recovery = {
            "initial_parse_error": str(exc)[:500],
            "retry_claim_count": len(retry_claims),
            "retry_source_event_count": len(retry_source_messages),
        }
        try:
            raw = client.complete_json(
                state_selection_system_prompt(adapter),
                state_selection_user_prompt(
                    question,
                    adapter,
                    route,
                    retry_claims,
                    validity_packet,
                    retry_source_messages,
                    scope_messages,
                    routed_time_role,
                    validation_error={
                        "error": str(exc)[:500],
                        "retry_instruction": "Return compact valid JSON only with state_packet.state_facets.",
                    },
                ),
            )
            state_selection_recovery["retry_succeeded"] = True
        except ValueError as retry_exc:
            state_selection_recovery["retry_succeeded"] = False
            state_selection_recovery["fallback_used"] = True
            state_selection_recovery["retry_parse_error"] = str(retry_exc)[:500]
            raw = fallback_state_selection_raw(
                question,
                route,
                selected_for_state,
                validity_packet,
                retry_source_messages,
                reason=f"state_selection_json_parse_failed:{exc}; retry_failed:{retry_exc}",
            )

    state_packet = raw_state_packet(raw)
    merged_relations: List[Dict[str, object]] = []
    seen_relations = set()
    for relation in list(validity_packet.get("relations", [])) + list(state_packet.get("relations", [])):
        if not isinstance(relation, dict):
            continue
        key = (str(relation.get("type", "")).upper(), str(relation.get("from", "")), str(relation.get("to", "")))
        if key in seen_relations:
            continue
        seen_relations.add(key)
        merged_relations.append(deepcopy(relation))

    merged_raw = deepcopy(raw)
    merged_raw["state_packet"] = {
        "target_scope_id": state_packet.get("target_scope_id") or route.target_scope.scope_id,
        "candidate_events": [message.event_id for message in graph_messages],
        "claims": claim_graph["claims"],
        "validity_decisions": validity_packet,
        "relations": merged_relations,
        "rejected_claims": list(claim_graph["rejected_claims"]) + list(validity_packet.get("rejected_claims", [])),
        "state_facets": state_packet.get("state_facets", []),
    }
    rejected_from_state = state_packet.get("rejected_claims", [])
    if isinstance(rejected_from_state, list):
        merged_raw["state_packet"]["rejected_claims"].extend(rejected_from_state)

    repaired, validation = validate_and_repair_graph_packet(
        merged_raw,
        question,
        route,
        graph_messages,
        scope_messages,
        routed_time_role,
    )
    trace = repaired.get("pipeline_trace", {})
    if not isinstance(trace, dict):
        trace = {}
    trace["validity_ablation"] = {
        "variant": validity_variant,
        "fixed_scope": True,
        "fixed_episode_events": True,
        "fixed_claim_candidates": True,
    }
    trace["claim_graph_build"] = {
        "graph_event_count": len(graph_messages),
        "claim_chunk_size": max(1, claim_chunk_size),
        "extracted_claim_count": len(claim_graph["claims"]),
        "claim_extraction_validations": claim_graph["claim_extraction_validations"],
        "routed_time_role": routed_time_role,
    }
    trace["claim_graph_selection"] = claim_selection
    trace["claim_validity"] = {
        "variant": validity_variant,
        "accepted_current_claim_count": len(validity_packet.get("accepted_current_claims", [])),
        "rejected_claim_count": len(validity_packet.get("rejected_claims", [])),
        "relation_count": len(validity_packet.get("relations", [])),
        "validation": validity_validation,
        "raw_output": validity_raw,
    }
    if state_selection_recovery:
        trace["state_selection_recovery"] = state_selection_recovery
    trace["time_role_route"] = {"time_role": routed_time_role} if routed_time_role else None
    repaired["pipeline_trace"] = trace
    return compose_answer(client, question, adapter, repaired)


def summarize_ablation(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    by_variant: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    by_qtype: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_variant[str(row["validity_variant"])].append(row)
        by_qtype[str(row["qtype"])].append(row)

    def accuracy(items: Sequence[Dict[str, object]]) -> Optional[float]:
        return mean(float(item.get("evaluation", {}).get("score", 0.0)) for item in items)

    def avg_trace_count(items: Sequence[Dict[str, object]], key: str) -> Optional[float]:
        values = []
        for item in items:
            trace = item.get("model_output", {}).get("pipeline_trace", {})
            validity = trace.get("claim_validity", {}) if isinstance(trace, dict) else {}
            value = validity.get(key)
            if value is not None:
                values.append(float(value))
        return mean(values)

    return {
        "n_rows": len(rows),
        "n_cases": len({str(row["case_id"]) for row in rows}),
        "validity_variants": sorted(by_variant),
        "accuracy_by_validity_variant": {variant: accuracy(items) for variant, items in sorted(by_variant.items())},
        "accuracy_by_qtype": {qtype: accuracy(items) for qtype, items in sorted(by_qtype.items())},
        "avg_accepted_current_claims_by_variant": {
            variant: avg_trace_count(items, "accepted_current_claim_count")
            for variant, items in sorted(by_variant.items())
        },
        "avg_rejected_claims_by_variant": {
            variant: avg_trace_count(items, "rejected_claim_count")
            for variant, items in sorted(by_variant.items())
        },
        "avg_relations_by_variant": {
            variant: avg_trace_count(items, "relation_count")
            for variant, items in sorted(by_variant.items())
        },
    }


def build_ablation_row(
    question: GroupQuestion,
    validity_variant: str,
    raw: Dict[str, object],
    route_payload: Dict[str, object],
    retrieval_debug: Dict[str, object],
    graph_messages: Sequence[GroupMessage],
    selected_claims: Sequence[Dict[str, object]],
    source_messages: Sequence[GroupMessage],
    evaluation: Dict[str, object],
) -> Dict[str, object]:
    return {
        "case_id": question.case_id,
        "domain": question.domain,
        "qtype": question.qtype,
        "question_id": question.question_id,
        "question": question.question,
        "asking_user_id": question.asking_user_id,
        "gold_answer": question.answer,
        "variant": f"validity_ablation:{validity_variant}",
        "validity_variant": validity_variant,
        "answer": str(raw.get("answer", "")),
        "scope_route": route_payload,
        "time_role_route": retrieval_debug.get("time_role_route"),
        "candidate_event_ids": [message.event_id for message in graph_messages],
        "selected_claim_ids": [str(claim.get("claim_id", "")) for claim in selected_claims],
        "source_event_ids_for_validity": [message.event_id for message in source_messages],
        "in_scope_episode_event_count": int(retrieval_debug.get("in_scope_episode_event_count", len(graph_messages))),
        "retrieval_debug": retrieval_debug,
        "model_output": raw,
        "evaluation": evaluation,
    }


def run_case_ablation(
    client: LLMClient,
    validity_client: LLMClient,
    judge_client: Optional[LLMClient],
    question: GroupQuestion,
    messages_by_domain: Dict[str, List[GroupMessage]],
    variants: Sequence[str],
    args: argparse.Namespace,
) -> List[Dict[str, object]]:
    adapter = get_adapter(question.qtype)
    context, graph_messages, route_payload = build_case_context(
        question,
        messages_by_domain,
        args.scope_candidate_k,
        args.scope_evidence_k,
        args.graph_event_limit,
    )
    route = context["route"]
    routed_time_role = context["routed_time_role"]
    scope_messages = context["scope_messages"]
    retrieval_debug = context["retrieval_debug"]
    claim_graph = extract_claim_graph(
        client,
        question,
        adapter,
        route,
        graph_messages,
        args.claim_chunk_size,
        routed_time_role,
    )
    selected_claims, source_messages, claim_selection = select_claim_candidates(
        question,
        adapter,
        claim_graph["claims"],
        graph_messages,
        args.claim_top_k,
        routed_time_role,
    )
    source_messages = source_messages or list(graph_messages[: min(len(graph_messages), 8)])

    rows: List[Dict[str, object]] = []
    for variant in variants:
        validity_packet, validity_validation, validity_raw = complete_validity_variant(
            validity_client,
            question,
            adapter,
            route,
            selected_claims,
            source_messages,
            variant,
            scope_messages,
            routed_time_role,
        )
        raw = complete_state_from_frozen_validity(
            client,
            question,
            adapter,
            route,
            graph_messages,
            scope_messages,
            claim_graph,
            selected_claims,
            source_messages,
            claim_selection,
            validity_packet,
            validity_validation,
            validity_raw,
            variant,
            args.claim_chunk_size,
            routed_time_role,
        )
        evaluation = judge_answer(judge_client, question, str(raw.get("answer", "")))
        rows.append(
            build_ablation_row(
                question,
                variant,
                raw,
                route_payload,
                retrieval_debug,
                graph_messages,
                selected_claims,
                source_messages,
                evaluation,
            )
        )
    return rows


def main() -> int:
    args = parse_args()
    questions = load_selected_questions(args.domains, args.qtypes, args.limit_per_type, args.limit_cases)
    if not questions:
        print("no GroupMemBench questions selected", file=sys.stderr)
        return 2

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

    validity_provider = args.validity_provider or args.provider
    validity_model = model
    validity_client = client
    if args.validity_provider:
        try:
            validity_api_key, validity_model, validity_api_base = provider_config(validity_provider)
        except RuntimeError as exc:
            print(f"Validity config error: {exc}", file=sys.stderr)
            return 2
        validity_client = LLMClient(
            provider=validity_provider,
            model=validity_model,
            api_key=validity_api_key,
            api_base=validity_api_base,
            cache_path=Path(args.validity_cache or args.cache),
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

    messages_by_domain = load_messages_by_domain(args.domains)
    rows: List[Dict[str, object]] = []
    try:
        for index, question in enumerate(questions, start=1):
            print(f"building frozen claim context / {question.case_id} ({index}/{len(questions)})", flush=True)
            rows.extend(
                run_case_ablation(
                    client,
                    validity_client,
                    judge_client,
                    question,
                    messages_by_domain,
                    args.validity_variants,
                    args,
                )
            )
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
        "ablation": "validity_only",
        "fixed_stages": ["scope_route", "episode_event_retrieval", "claim_extraction", "claim_selection"],
        "varied_stage": "claim_validity",
        "validity_variants": list(args.validity_variants),
        "domains": list(args.domains),
        "qtypes": list(args.qtypes),
        "provider": args.provider,
        "model": model,
        "validity_provider": validity_provider,
        "validity_model": validity_model,
        "judge_provider": args.judge_provider if judge_client else None,
        "judge_model": judge_model,
        "summary": summarize_ablation(rows),
        "rows": rows,
    }
    summary = output["summary"]
    print("GroupMemBench validity ablation")
    print(f"cases={summary['n_cases']} rows={summary['n_rows']}")
    print(f"accuracy_by_validity_variant={summary['accuracy_by_validity_variant']}")
    write_output(output, Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

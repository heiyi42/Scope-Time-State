from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional


PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.common.io import load_dotenv  # noqa: E402
from Experiment.run.common.llm_client import LLMClient, LLMRequestError, provider_config  # noqa: E402
from pipeline.external.groupmembench.adapters import TASK_TYPES, get_adapter  # noqa: E402
from pipeline.external.groupmembench.graph_store import (  # noqa: E402
    graph_artifact_dir,
    graph_manifest_for_question,
    write_graph_artifact,
)
from pipeline.external.groupmembench.loader import CACHE_DIR, DOMAINS, GRAPH_OUTPUT_DIR, GroupQuestion  # noqa: E402
from pipeline.external.groupmembench.runner import (  # noqa: E402
    build_case_context,
    load_messages_by_domain,
    load_selected_questions,
)
from pipeline.external.groupmembench.staged import (  # noqa: E402
    complete_graph_state_packet,
    dry_run_graph_scope_state_packet,
)
from pipeline.external.groupmembench.time_roles import infer_group_time_role_with_llm  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build query-conditioned GroupMemBench smoke graph artifacts. "
            "Use domain_graph_builder.py for the benchmark protocol."
        )
    )
    parser.add_argument(
        "--allow-query-conditioned",
        action="store_true",
        help="Required because this builder constructs graph artifacts after seeing each question.",
    )
    parser.add_argument("--domains", nargs="+", choices=DOMAINS, default=["Finance"])
    parser.add_argument("--qtypes", nargs="+", choices=TASK_TYPES, default=list(TASK_TYPES))
    parser.add_argument("--provider", choices=("openai", "deepseek"), default="deepseek")
    parser.add_argument("--model", default=None, help="Optional model override for the graph-building provider.")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-per-type", type=int, default=1)
    parser.add_argument("--scope-candidate-k", type=int, default=8)
    parser.add_argument("--scope-evidence-k", type=int, default=80)
    parser.add_argument("--graph-event-limit", type=int, default=96)
    parser.add_argument("--claim-chunk-size", type=int, default=16)
    parser.add_argument("--claim-top-k", type=int, default=32)
    parser.add_argument("--dry-run", action="store_true", help="Write graph skeleton artifacts without LLM graph construction.")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache", default=str(CACHE_DIR / "llm_cache.groupmembench_graph_builder.json"))
    parser.add_argument("--output-dir", default=str(GRAPH_OUTPUT_DIR / "groupmembench_graph_store_smoke"))
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> Dict[str, object]:
    return {
        "domains": list(args.domains),
        "qtypes": list(args.qtypes),
        "limit_cases": args.limit_cases,
        "limit_per_type": args.limit_per_type,
        "scope_candidate_k": args.scope_candidate_k,
        "scope_evidence_k": args.scope_evidence_k,
        "graph_event_limit": args.graph_event_limit,
        "claim_chunk_size": args.claim_chunk_size,
        "claim_top_k": args.claim_top_k,
        "provider": args.provider,
        "model": args.model,
        "dry_run": args.dry_run,
    }


def build_case_graph(
    client: Optional[LLMClient],
    question: GroupQuestion,
    messages_by_domain: Dict[str, list],
    args: argparse.Namespace,
    provider: str,
    model: str,
    output_dir: Path,
) -> Dict[str, object]:
    adapter = get_adapter(question.qtype)
    if not args.dry_run and client is None:
        raise ValueError("graph builder requires an LLM client unless --dry-run is set")
    time_role_route = None if args.dry_run else infer_group_time_role_with_llm(client, question, adapter)
    context, graph_messages, scope_route = build_case_context(
        question,
        messages_by_domain,
        args.scope_candidate_k,
        args.scope_evidence_k,
        args.graph_event_limit,
        time_role_route,
    )
    if args.dry_run:
        locked_raw = dry_run_graph_scope_state_packet(
            question,
            context["route"],
            graph_messages,
            context["scope_messages"],
            context["routed_time_role"],
        )
    else:
        locked_raw = complete_graph_state_packet(
            client,
            question,
            adapter,
            context["route"],
            graph_messages,
            context["scope_messages"],
            args.claim_chunk_size,
            args.claim_top_k,
            context["routed_time_role"],
        )
    manifest = graph_manifest_for_question(
        question=question,
        build_config=build_config(args),
        scope_route=scope_route,
        retrieval_debug=context["retrieval_debug"],
        graph_provider=provider,
        graph_model=model,
    )
    artifact_root = graph_artifact_dir(output_dir, question.domain, question.qtype, question.question_id)
    artifact = write_graph_artifact(artifact_root, manifest, locked_raw)
    return {
        "case_id": question.case_id,
        "domain": question.domain,
        "qtype": question.qtype,
        "question_id": question.question_id,
        "artifact_dir": str(artifact.root),
        "node_count": len(artifact.nodes),
        "edge_count": len(artifact.edges),
        "graph_warnings": artifact.manifest.get("graph_warnings", []),
        "target_scope_id": artifact.target_scope_id,
        "candidate_event_count": len(artifact.candidate_event_ids),
    }


def write_summary(output_dir: Path, summary: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "build_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {path}")


def print_summary(summary: Dict[str, object]) -> None:
    print("GroupMemBench graph builder")
    print(
        f"cases={summary['n_cases']} provider={summary['graph_provider']} "
        f"model={summary['graph_model']} output_dir={summary['output_dir']}"
    )
    print(f"warnings={summary['warning_count']} artifacts={len(summary['artifacts'])}")


def main() -> int:
    args = parse_args()
    if not args.allow_query_conditioned:
        print(
            "Refusing query-conditioned graph construction. "
            "Use `python -m pipeline.external.groupmembench.domain_graph_builder` "
            "to build one offline subgraph per domain corpus. "
            "Pass --allow-query-conditioned only for smoke/ablation runs.",
            file=sys.stderr,
        )
        return 2
    questions = load_selected_questions(args.domains, args.qtypes, args.limit_per_type, args.limit_cases)
    if not questions:
        print("no GroupMemBench questions selected", file=sys.stderr)
        return 2
    messages_by_domain = load_messages_by_domain(args.domains)
    client: Optional[LLMClient] = None
    model = args.model or "dry-run"
    if not args.dry_run:
        load_dotenv()
        try:
            api_key, model, api_base = provider_config(args.provider)
            if args.model:
                model = args.model
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

    output_dir = Path(args.output_dir)
    artifacts: List[Dict[str, object]] = []
    try:
        for index, question in enumerate(questions, start=1):
            print(f"building graph / {question.case_id} ({index}/{len(questions)})", flush=True)
            artifacts.append(build_case_graph(client, question, messages_by_domain, args, args.provider, model, output_dir))
            time.sleep(0.2)
    except LLMRequestError as exc:
        print("\nLLM request failed during graph build.", file=sys.stderr)
        print(f"provider: {exc.provider}", file=sys.stderr)
        print(f"model: {exc.model}", file=sys.stderr)
        print(f"endpoint: {exc.endpoint}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("\nLLM output failed graph-build JSON validation.", file=sys.stderr)
        print(f"provider: {args.provider}", file=sys.stderr)
        print(f"model: {model}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = {
        "benchmark": "GroupMemBench",
        "n_cases": len(artifacts),
        "graph_provider": args.provider,
        "graph_model": model,
        "output_dir": str(output_dir),
        "build_config": build_config(args),
        "dry_run": bool(args.dry_run),
        "warning_count": sum(len(item.get("graph_warnings", [])) for item in artifacts),
        "artifacts": artifacts,
    }
    print_summary(summary)
    write_summary(output_dir, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

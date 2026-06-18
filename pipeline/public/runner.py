from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence

from Experiment.Main_Baseline.tsm.tsm_memory import build_tsm_prompt_spec_from_index
from Experiment.Main_Baseline.validity_aware_consolidation.cupmem_memory import build_cupmem_prompt_spec
from Experiment.run.common.llm_client import LLMClient
from Experiment.run.common.models import QueryCase
from Experiment.run.run_public_benchmark.prompts import public_system_prompt, public_user_prompt
from Experiment.run.run_public_benchmark.routing import build_public_prompt_spec, infer_time_role, route_scope_from_profiles
from Experiment.run.run_public_benchmark.types import (
    PublicCase,
    PublicEvalRow,
    PublicScopedCase,
    PublicTSMIndexCache,
    SCOPE_PROFILE_ROUTED_VARIANTS,
    ScopeProfile,
    canonical_public_variant_name,
)
from pipeline.public.judging import attach_public_judge_score, evaluate_public_output
from pipeline.public.reporting import summarize_rows
from pipeline.public.staged import run_public_ours_pipeline


def run_public_variant(
    client: LLMClient,
    judge_client: Optional[LLMClient],
    variant_name: str,
    events: Sequence[object],
    scope_profiles: Sequence[ScopeProfile],
    public_cases: Sequence[PublicCase],
    hidden_cases_by_id: Dict[str, QueryCase],
    scope_top_k: int,
    tsm_construction_mode: str,
) -> Dict[str, object]:
    rows: List[PublicEvalRow] = []
    canonical_name = canonical_public_variant_name(variant_name)
    tsm_index_cache = PublicTSMIndexCache(indexes={})
    tsm_construction_llm = client.complete_json if tsm_construction_mode == "llm" else None
    for public_case in public_cases:
        hidden_case = hidden_cases_by_id[public_case.case_id]
        print(f"running {variant_name} / {public_case.case_id}", flush=True)
        routed_scope = None
        routed_time_role = None
        router_raw = None
        candidate_scope_profiles: List[Dict[str, object]] = []
        if canonical_name in SCOPE_PROFILE_ROUTED_VARIANTS:
            routed_scope, router_raw, candidate_scope_profiles = route_scope_from_profiles(
                client,
                events,
                scope_profiles,
                public_case,
                scope_top_k,
            )
        if canonical_name == "ours_scope_time_state":
            routed_time_role = infer_time_role(public_case.query, public_case.operation)
        if canonical_name in {"tsm_global_public", "tsm_scope_routed_public"}:
            tsm_case = PublicScopedCase(
                case_id=public_case.case_id,
                query=public_case.query,
                operation=public_case.operation,
                scope_id=routed_scope if canonical_name == "tsm_scope_routed_public" else None,
            )
            tsm_index = tsm_index_cache.get(
                events,
                tsm_case.scope_id,
                tsm_construction_llm,
                tsm_construction_mode,
            )
            spec = build_tsm_prompt_spec_from_index(tsm_index, tsm_case)
        elif canonical_name in {"validity_global_public", "validity_scope_routed_public"}:
            validity_case = PublicScopedCase(
                case_id=public_case.case_id,
                query=public_case.query,
                operation=public_case.operation,
                scope_id=routed_scope if canonical_name == "validity_scope_routed_public" else None,
            )
            spec = build_cupmem_prompt_spec(events, validity_case)
        else:
            spec = build_public_prompt_spec(
                variant_name,
                events,
                public_case,
                routed_scope=routed_scope,
                routed_time_role=routed_time_role,
            )
        if canonical_name == "ours_scope_time_state":
            raw = run_public_ours_pipeline(
                client,
                spec,
                public_case,
                router_raw,
                routed_scope,
                routed_time_role,
            )
            raw.setdefault("pipeline_trace", {})["scope_profile_candidates"] = candidate_scope_profiles
        else:
            raw = client.complete_json(public_system_prompt(), public_user_prompt(spec, public_case))
            if canonical_name in {"tsm_global_public", "tsm_scope_routed_public"}:
                trace = raw.get("pipeline_trace", {})
                if not isinstance(trace, dict):
                    trace = {}
                trace.update(
                    {
                        "pipeline": canonical_name,
                        "scope_router_output": router_raw,
                        "routed_scope": routed_scope,
                        "scope_profile_candidates": candidate_scope_profiles,
                        "tsm_construction_mode": tsm_construction_mode,
                        "tsm_index_event_count": len(tsm_index.events),
                        "tsm_visible_event_count": len(spec.visible_events),
                    }
                )
                raw["pipeline_trace"] = trace
            elif canonical_name in {"validity_global_public", "validity_scope_routed_public"}:
                trace = raw.get("pipeline_trace", {})
                if not isinstance(trace, dict):
                    trace = {}
                trace.update(
                    {
                        "pipeline": canonical_name,
                        "scope_router_output": router_raw,
                        "routed_scope": routed_scope,
                        "scope_profile_candidates": candidate_scope_profiles,
                        "validity_visible_event_count": len(spec.visible_events),
                    }
                )
                raw["pipeline_trace"] = trace
        row = evaluate_public_output(raw, hidden_case)
        if judge_client is not None:
            print(f"judging {variant_name} / {public_case.case_id}", flush=True)
            row = attach_public_judge_score(judge_client, hidden_case, row)
        rows.append(row)
        time.sleep(0.2)

    summary = summarize_rows(rows)
    summary.update(
        {
            "variant": canonical_name,
            "requested_variant": variant_name,
            "model_provider": client.provider,
            "model": client.model,
            "judge_provider": judge_client.provider if judge_client else None,
            "judge_model": judge_client.model if judge_client else None,
            "cases": [row.__dict__ for row in rows],
        }
    )
    return summary

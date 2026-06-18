from __future__ import annotations

from copy import deepcopy
import time
from typing import Dict, List, Optional, Sequence

from Experiment.run.common.llm_client import LLMClient
from Experiment.run.common.models import EvalRow, Event, QueryCase
from Experiment.run.common.utils import minimize_locked_state_evidence
from Experiment.run.run_oracle_benchmark.graph_trace import (
    attach_answer_trace_to_graph_trace,
    build_graph_trace,
    graph_trace_generation_summary,
    graph_trace_to_locked_state,
)
from Experiment.run.run_oracle_benchmark.judging import attach_judge_score
from Experiment.run.run_oracle_benchmark.prompts import (
    composer_system_prompt,
    composer_user_prompt,
    state_frame_system_prompt,
    state_frame_user_prompt,
    system_prompt,
    user_prompt,
    verifier_system_prompt,
    verifier_user_prompt,
)
from Experiment.registry import build_prompt_spec, canonical_variant_name
from pipeline.oracle.evaluation import evaluate_output, should_skip_judge_failures
from pipeline.oracle.event_ids import complete_validated_retriever
from pipeline.oracle.state_frame import merge_locked_state_with_answer, verify_state_frame_support
from pipeline.oracle.support_auditor import complete_validated_support_auditor


def run_variant(
    client: LLMClient,
    judge_client: Optional[LLMClient],
    variant_name: str,
    events: Sequence[Event],
    cases: Sequence[QueryCase],
    tsm_construction_mode: str = "llm",
    ours_pipeline: str = "two_stage",
    ours_readout_policy: str = "baseline",
) -> Dict[str, object]:
    rows: List[EvalRow] = []
    canonical_name = canonical_variant_name(variant_name)
    for case in cases:
        print(f"running {variant_name} / {case.case_id}", flush=True)
        construction_llm = client.complete_json if canonical_name == "tsm" and tsm_construction_mode == "llm" else None
        spec = build_prompt_spec(
            variant_name,
            events,
            case,
            construction_llm=construction_llm,
            construction_mode=tsm_construction_mode,
        )
        if canonical_name == "ours_scope_time_state":
            retriever_raw, retriever_event_id_validation = complete_validated_retriever(
                client,
                spec,
                case,
                ours_readout_policy,
            )
            locked_state = (
                minimize_locked_state_evidence(retriever_raw, case)
                if ours_readout_policy == "minimized_no_background"
                else retriever_raw
            )
            support_auditor_raw: Optional[Dict[str, object]] = None
            support_auditor_event_id_validation: Optional[Dict[str, object]] = None
            if ours_readout_policy == "minimized_no_background":
                support_auditor_raw, support_auditor_event_id_validation = complete_validated_support_auditor(
                    client,
                    case,
                    spec.visible_events,
                    locked_state,
                )
                locked_state = minimize_locked_state_evidence(support_auditor_raw, case)
            runtime_graph_trace: Dict[str, object] = {}
            locked_state_before_graph_trace: Optional[Dict[str, object]] = None
            if ours_pipeline == "graph_trace":
                locked_state_before_graph_trace = deepcopy(locked_state)
                runtime_graph_trace = build_graph_trace(
                    case,
                    spec.visible_events,
                    locked_state,
                    trace_status="runtime_intermediate_from_locked_state",
                )
                locked_state = graph_trace_to_locked_state(runtime_graph_trace, locked_state, case)
            state_frame_trace: Dict[str, object] = {}
            if ours_pipeline == "stateframe":
                state_frame_raw = client.complete_json(
                    state_frame_system_prompt(),
                    state_frame_user_prompt(case, spec.visible_events, locked_state),
                )
                state_frame_trace = verify_state_frame_support(case, spec.visible_events, locked_state, state_frame_raw)
            answer_raw = client.complete_json(
                composer_system_prompt(ours_readout_policy),
                composer_user_prompt(case, spec.visible_events, locked_state, state_frame_trace, ours_readout_policy),
            )
            verified_answer_raw = client.complete_json(
                verifier_system_prompt(ours_readout_policy),
                verifier_user_prompt(case, locked_state, answer_raw, state_frame_trace),
            )
            raw = merge_locked_state_with_answer(
                locked_state,
                verified_answer_raw,
                state_frame_trace if ours_pipeline == "stateframe" else None,
            )
            raw["pipeline_trace"]["retriever_output"] = retriever_raw
            raw["pipeline_trace"]["retriever_event_id_validation"] = retriever_event_id_validation
            if ours_readout_policy == "minimized_no_background":
                raw["pipeline_trace"]["support_auditor_output"] = support_auditor_raw
                raw["pipeline_trace"]["support_auditor_event_id_validation"] = support_auditor_event_id_validation
                raw["pipeline_trace"]["locked_state_after_evidence_minimizer"] = (
                    locked_state_before_graph_trace if locked_state_before_graph_trace is not None else locked_state
                )
            raw["pipeline_trace"]["composer_output"] = answer_raw
            if ours_pipeline == "graph_trace":
                raw["pipeline_trace"]["graph_trace_stage_output"] = runtime_graph_trace
                raw["pipeline_trace"]["locked_state_before_graph_trace"] = locked_state_before_graph_trace
                raw["pipeline_trace"]["locked_state_after_graph_trace"] = {
                    "evidence_events": locked_state.get("evidence_events", []),
                    "state_slots": locked_state.get("state_slots", {}),
                }
                raw["graph_trace"] = attach_answer_trace_to_graph_trace(runtime_graph_trace, spec.visible_events, raw)
                trace_summary = graph_trace_generation_summary(raw["graph_trace"])
                trace_summary["mode"] = "runtime_intermediate"
            else:
                raw["graph_trace"] = build_graph_trace(case, spec.visible_events, raw)
                trace_summary = graph_trace_generation_summary(raw["graph_trace"])
                trace_summary["mode"] = "posthoc_from_final_raw"
            raw["pipeline_trace"]["graph_trace_generation"] = trace_summary
        else:
            raw = client.complete_json(system_prompt(), user_prompt(spec, case))
        row = evaluate_output(raw, case)
        if judge_client is not None:
            print(f"judging {variant_name} / {case.case_id}", flush=True)
            try:
                row = attach_judge_score(judge_client, case, row)
            except Exception as exc:
                if not should_skip_judge_failures():
                    raise
                provider = getattr(exc, "provider", judge_client.provider)
                model = getattr(exc, "model", judge_client.model)
                endpoint = getattr(exc, "endpoint", judge_client.api_base)
                row.raw_output["judge_error"] = {
                    "provider": provider,
                    "model": model,
                    "endpoint": endpoint,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                print(
                    f"warning: judge failed for {variant_name} / {case.case_id}; continuing because "
                    "JUDGE_FAILURE_POLICY=skip",
                    flush=True,
                )
        rows.append(row)
        time.sleep(0.2)
    judge_scores = [row.slot_value_judge for row in rows if row.slot_value_judge is not None]
    answer_scores = [row.answer_judge for row in rows if row.answer_judge is not None]
    judge_failed_cases = [row.case_id for row in rows if judge_client is not None and row.judge_output is None]
    context_scores = [row.context_event_recall for row in rows if row.context_event_recall is not None]
    hard_negative_scores = [row.invalid_distractor_rate for row in rows if row.invalid_distractor_rate is not None]
    over_evidence_scores = [row.over_evidence_rate for row in rows if row.over_evidence_rate is not None]
    unknown_current_scores = [
        row.unknown_current_correct for row in rows if row.unknown_current_correct is not None
    ]
    unknown_current_false_completion_cases = [
        row.case_id for row in rows if row.unknown_current_false_completion
    ]
    result = {
        "variant": variant_name,
        "model_provider": client.provider,
        "model": client.model,
        "judge_provider": judge_client.provider if judge_client else None,
        "judge_model": judge_client.model if judge_client else None,
        "avg_event_f1": round(sum(row.event_f1 for row in rows) / len(rows), 3),
        "avg_event_precision": round(sum(row.event_precision for row in rows) / len(rows), 3),
        "avg_gold_event_recall": round(sum(row.gold_event_recall for row in rows) / len(rows), 3),
        "avg_context_event_recall": round(sum(context_scores) / len(context_scores), 3) if context_scores else None,
        "avg_slot_support_accuracy": round(sum(row.slot_support_accuracy for row in rows) / len(rows), 3),
        "avg_slot_support_f1": round(sum(row.slot_support_f1 for row in rows) / len(rows), 3),
        "avg_required_support_f1": round(sum(row.required_support_f1 for row in rows) / len(rows), 3),
        "avg_slot_value_judge": round(sum(judge_scores) / len(judge_scores), 3) if judge_scores else None,
        "avg_answer_judge": round(sum(answer_scores) / len(answer_scores), 3) if answer_scores else None,
        "judge_scored_cases": len(judge_scores),
        "judge_failed_cases": judge_failed_cases,
        "avg_invalid_distractor_rate": round(sum(hard_negative_scores) / len(hard_negative_scores), 3)
        if hard_negative_scores
        else None,
        "avg_over_evidence_rate": round(sum(over_evidence_scores) / len(over_evidence_scores), 3)
        if over_evidence_scores
        else None,
        "unknown_current_accuracy": round(sum(unknown_current_scores) / len(unknown_current_scores), 3)
        if unknown_current_scores
        else None,
        "unknown_current_cases": len(unknown_current_scores),
        "unknown_current_false_completion_rate": round(
            len(unknown_current_false_completion_cases) / len(unknown_current_scores),
            3,
        )
        if unknown_current_scores
        else None,
        "unknown_current_false_completion_cases": unknown_current_false_completion_cases,
        "cases": [row.__dict__ for row in rows],
    }
    if canonical_name == "tsm":
        result["tsm_construction_mode"] = tsm_construction_mode
    if canonical_name == "ours_scope_time_state":
        result["ours_pipeline"] = ours_pipeline
        result["ours_readout_policy"] = ours_readout_policy
    return result

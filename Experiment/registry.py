from __future__ import annotations

from importlib import import_module
from typing import Callable, Dict, Optional, Sequence

from Experiment.common import BaselinePromptSpec


MAIN_BASELINE_MODULES = {
    "full_context_llm": "Experiment.Main_Baseline.full_context_llm.baseline",
    "hybrid_rag": "Experiment.Main_Baseline.hybrid_rag.baseline",
    "tsm": "Experiment.Main_Baseline.tsm.baseline",
    "validity_aware_consolidation": "Experiment.Main_Baseline.validity_aware_consolidation.baseline",
    "ours_scope_time_state": "Experiment.Main_Baseline.ours_scope_time_state.baseline",
}

APPENDIX_BASELINE_MODULES = {
    "latest_event_only": "Experiment.Appendix_Baseline.latest_event_only.baseline",
    "temporal_fact_graph": "Experiment.Appendix_Baseline.temporal_fact_graph.baseline",
    "temporal_kg_oracle_schema": "Experiment.Appendix_Baseline.temporal_kg_oracle_schema.baseline",
    "tremu_style": "Experiment.Appendix_Baseline.tremu_style.baseline",
}

BASELINE_MODULES = {**MAIN_BASELINE_MODULES, **APPENDIX_BASELINE_MODULES}

BASELINE_ALIASES = {
    "llm_only_full_context": "full_context_llm",
    "recent_rag_topk": "hybrid_rag",
    "tsm_semantic_timeline": "tsm",
    "temporal_semantic_memory": "tsm",
    "validity_aware": "validity_aware_consolidation",
    "stale_cupmem": "validity_aware_consolidation",
    "cupmem_style": "validity_aware_consolidation",
    "scope_time_state_pipeline": "ours_scope_time_state",
    "kg_schema_with_validity_rules": "temporal_kg_oracle_schema",
    "tremu_lite": "tremu_style",
}


def baseline_names() -> Sequence[str]:
    return tuple(BASELINE_MODULES)


def main_baseline_names() -> Sequence[str]:
    return tuple(MAIN_BASELINE_MODULES)


def appendix_baseline_names() -> Sequence[str]:
    return tuple(APPENDIX_BASELINE_MODULES)


def canonical_variant_name(variant_name: str) -> str:
    return BASELINE_ALIASES.get(variant_name, variant_name)


LLMJSONFn = Callable[[str, str], Dict[str, object]]


def build_prompt_spec(
    variant_name: str,
    events: Sequence[object],
    case: object,
    construction_llm: Optional[LLMJSONFn] = None,
    construction_mode: str = "llm",
) -> BaselinePromptSpec:
    canonical_name = canonical_variant_name(variant_name)
    try:
        module_path = BASELINE_MODULES[canonical_name]
    except KeyError as exc:
        known = ", ".join(tuple(BASELINE_MODULES) + tuple(BASELINE_ALIASES))
        raise ValueError(f"unknown variant: {variant_name}; known variants: {known}") from exc
    module = import_module(module_path)
    if canonical_name == "tsm":
        return module.build(events, case, construction_llm=construction_llm, construction_mode=construction_mode)
    return module.build(events, case)

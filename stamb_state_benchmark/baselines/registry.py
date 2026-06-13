from __future__ import annotations

from importlib import import_module
from typing import Sequence

try:
    from baselines.common import BaselinePromptSpec
except ModuleNotFoundError:
    from stamb_state_benchmark.baselines.common import BaselinePromptSpec


BASELINE_MODULES = {
    "llm_only_full_context": "baselines.llm_only_full_context.baseline",
    "latest_event_only": "baselines.latest_event_only.baseline",
    "recent_rag_topk": "baselines.recent_rag_topk.baseline",
    "temporal_fact_graph": "baselines.temporal_fact_graph.baseline",
    "kg_schema_with_validity_rules": "baselines.kg_schema_with_validity_rules.baseline",
    "tremu_lite": "baselines.tremu_lite.baseline",
    "scope_time_state_pipeline": "baselines.scope_time_state_pipeline.baseline",
}


def baseline_names() -> Sequence[str]:
    return tuple(BASELINE_MODULES)


def build_prompt_spec(variant_name: str, events: Sequence[object], case: object) -> BaselinePromptSpec:
    try:
        module_path = BASELINE_MODULES[variant_name]
    except KeyError as exc:
        known = ", ".join(BASELINE_MODULES)
        raise ValueError(f"unknown variant: {variant_name}; known variants: {known}") from exc
    try:
        module = import_module(module_path)
    except ModuleNotFoundError:
        module = import_module(f"stamb_state_benchmark.{module_path}")
    return module.build(events, case)

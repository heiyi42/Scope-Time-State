from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from Experiment.Main_Baseline.tsm.tsm_memory import TSMIndex, build_tsm_index
from Experiment.registry import canonical_variant_name


SUPPORTED_VARIANTS = (
    "full_context_llm",
    "hybrid_rag",
    "tsm_global_public",
    "tsm_scope_routed_public",
    "validity_global_public",
    "validity_scope_routed_public",
    "ours_scope_time_state",
)
PUBLIC_VARIANT_ALIASES = {
    "tsm": "tsm_scope_routed_public",
    "validity_aware_consolidation": "validity_scope_routed_public",
    "validity_aware": "validity_scope_routed_public",
    "stale_cupmem": "validity_scope_routed_public",
    "cupmem_style": "validity_scope_routed_public",
}
SCOPE_PROFILE_ROUTED_VARIANTS = {
    "tsm_scope_routed_public",
    "validity_scope_routed_public",
    "ours_scope_time_state",
}


def canonical_public_variant_name(variant_name: str) -> str:
    registry_name = canonical_variant_name(variant_name)
    return PUBLIC_VARIANT_ALIASES.get(variant_name, PUBLIC_VARIANT_ALIASES.get(registry_name, registry_name))


@dataclass(frozen=True)
class PublicCase:
    case_id: str
    query: str
    operation: str


@dataclass(frozen=True)
class PublicScopedCase:
    case_id: str
    query: str
    operation: str
    scope_id: Optional[str]


LLMJSONFn = Callable[[str, str], Dict[str, object]]


@dataclass
class PublicTSMIndexCache:
    indexes: Dict[Tuple[str, str, Tuple[Tuple[str, str], ...]], TSMIndex]

    def get(
        self,
        events: Sequence[object],
        scope_id: Optional[str],
        construction_llm: Optional[LLMJSONFn],
        construction_mode: str,
    ) -> TSMIndex:
        scoped_events = [
            event
            for event in events
            if scope_id and getattr(event, "scope_id", None) == scope_id
        ]
        index_events = scoped_events or list(events)
        event_signature = tuple(
            (str(getattr(event, "event_id", "")), str(getattr(event, "updated_at", "")))
            for event in index_events
        )
        key = (construction_mode, scope_id or "__global__", event_signature)
        if key not in self.indexes:
            print(
                f"building TSM index scope={scope_id or '__global__'} "
                f"events={len(index_events)} construction_mode={construction_mode}",
                flush=True,
            )
            self.indexes[key] = build_tsm_index(
                index_events,
                construction_llm=construction_llm,
                construction_mode=construction_mode,
            )
        return self.indexes[key]


@dataclass(frozen=True)
class ScopeProfile:
    scope_id: str
    profile: Dict[str, object]
    profile_text: str


@dataclass
class PublicEvalRow:
    case_id: str
    query: str
    evidence_support_f1: float
    evidence_precision: float
    gold_event_recall: float
    facet_recall: Optional[float]
    facet_precision: Optional[float]
    answer_judge: Optional[float]
    answer_judge_10: Optional[float]
    unsupported_claim_rate: Optional[float]
    invalid_distractor_rate: Optional[float]
    over_evidence_rate: Optional[float]
    over_evidence_count: int
    unknown_current_correct: Optional[float]
    unknown_current_false_completion: Optional[bool]
    hard_negative_hits: List[str]
    difficulty_tags: Tuple[str, ...]
    answerability: str
    pred_events: List[str]
    pred_facets: List[Dict[str, object]]
    answer: str
    raw_output: Dict[str, object]
    judge_output: Optional[Dict[str, object]]

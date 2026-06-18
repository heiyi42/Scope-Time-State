from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence

from ...common import BaselinePromptSpec
from .tsm_memory import build_tsm_prompt_spec


LLMJSONFn = Callable[[str, str], Dict[str, object]]


def build(
    events: Sequence[object],
    case: object,
    construction_llm: Optional[LLMJSONFn] = None,
    construction_mode: str = "llm",
) -> BaselinePromptSpec:
    return build_tsm_prompt_spec(events, case, construction_llm=construction_llm, construction_mode=construction_mode)

from __future__ import annotations

from typing import Sequence

from ...common import BaselinePromptSpec
from .cupmem_memory import build_cupmem_prompt_spec


def build(events: Sequence[object], case: object) -> BaselinePromptSpec:
    return build_cupmem_prompt_spec(events, case)

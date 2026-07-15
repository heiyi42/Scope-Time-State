"""Compatibility wrapper for the Baseline Graphiti local adapter."""

from pathlib import Path
import sys


OUTER_EVERMEMBENCH_DIR = Path(__file__).resolve().parents[5]
BASELINE_DIR = OUTER_EVERMEMBENCH_DIR / "Baseline"
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

from graphiti_local.adapter import GraphitiLocalAdapter  # noqa: E402

__all__ = ["GraphitiLocalAdapter"]

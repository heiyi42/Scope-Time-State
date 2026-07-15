"""Compatibility wrapper for the Baseline Mem0 local adapter."""

from pathlib import Path
import sys


OUTER_EVERMEMBENCH_DIR = Path(__file__).resolve().parents[5]
BASELINE_DIR = OUTER_EVERMEMBENCH_DIR / "Baseline"
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

from mem0_local.adapter import Mem0LocalAdapter  # noqa: E402

__all__ = ["Mem0LocalAdapter"]

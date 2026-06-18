from __future__ import annotations

from pathlib import Path


RUN_COMMON_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = RUN_COMMON_DIR.parents[1]
PROJECT_DIR = RUN_COMMON_DIR.parents[2]
BENCHMARK_DIR = PROJECT_DIR / "stamb_state_benchmark"

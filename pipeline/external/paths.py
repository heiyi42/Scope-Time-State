from __future__ import annotations

from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
EXTERNAL_OUTPUT_ROOT = PROJECT_DIR / "Graph" / "output"
EXTERNAL_GRAPH_DIR = EXTERNAL_OUTPUT_ROOT / "graph"
EXTERNAL_CACHE_DIR = EXTERNAL_OUTPUT_ROOT / "cache"
EXTERNAL_RESULT_DIR = EXTERNAL_OUTPUT_ROOT / "result"

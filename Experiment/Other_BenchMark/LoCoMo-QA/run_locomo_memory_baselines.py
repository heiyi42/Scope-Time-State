from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
BASELINE_DIR = Path(__file__).resolve().parent / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

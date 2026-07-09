from __future__ import annotations

from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parents[3]
BASELINE_DIR = Path(__file__).resolve().parent / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from ours_scope_time_state.qa_probe import main  # noqa: E402


if __name__ == "__main__":
    result = main()
    raise SystemExit(result if isinstance(result, int) else 0)

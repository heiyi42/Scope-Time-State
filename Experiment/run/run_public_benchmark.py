from __future__ import annotations

from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from Experiment.run.run_public_benchmark.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parents[3]
BASELINE_DIR = Path(__file__).resolve().parent / "Baseline"
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from adapter_registry import get_adapter_class, load_adapter_config, supported_adapters  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect copied EverMemBench baseline adapters.")
    parser.add_argument("--list", action="store_true", help="List available baseline adapters.")
    parser.add_argument("--system", choices=supported_adapters(), default="")
    parser.add_argument("--print-config", action="store_true", help="Print the resolved Baseline config for --system.")
    parser.add_argument("--base-url", default="", help="Optional base URL override for config inspection.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list or not args.system:
        print("\n".join(supported_adapters()))
        if not args.system:
            return 0
    adapter_class = get_adapter_class(args.system)
    print(f"{args.system}: {adapter_class.__module__}.{adapter_class.__name__}")
    if args.print_config:
        print(json.dumps(load_adapter_config(args.system, base_url=args.base_url), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

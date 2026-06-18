from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from v1_common import DEFAULT_V1_DIR, PUBLIC_CASE_FORBIDDEN_FIELDS, build_scope_profiles, read_json, write_json


def public_case(case: Dict[str, Any]) -> Dict[str, Any]:
    stripped = {key: value for key, value in case.items() if key not in PUBLIC_CASE_FORBIDDEN_FIELDS}
    return {
        "case_id": stripped["case_id"],
        "query": stripped["query"],
        "operation": stripped["operation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-gold public STAMB-State v1 input files.")
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_V1_DIR / "public")
    args = parser.parse_args()

    events = read_json(args.v1_dir / "events_raw.json")
    cases = read_json(args.v1_dir / "cases.json")
    public_cases = [public_case(dict(case)) for case in cases]
    version_name = args.v1_dir.name

    write_json(args.public_dir / "events.json", events)
    write_json(args.public_dir / "cases.json", public_cases)
    write_json(args.public_dir / "scope_profiles.json", build_scope_profiles(events))
    (args.public_dir / "README.md").write_text(
        f"# STAMB-State {version_name} Public Track\n\n"
        "`events.json`, `cases.json`, and `scope_profiles.json` are the no-gold end-to-end input files.\n"
        "`scope_profiles.json` contains routing profiles derived only from public raw events.\n"
        "Evaluator-only fields are retained only in `../cases.json` and annotation files.\n",
        encoding="utf-8",
    )
    print(f"wrote public track to {args.public_dir}")
    print(f"events={len(events)} cases={len(public_cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

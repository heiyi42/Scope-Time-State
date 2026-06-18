from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from v1_common import DEFAULT_OUTPUT_DIR, LEGACY_DATA_DIR, load_legacy_cases, load_legacy_events, summarize_counts, write_json


def audit(events_path: Path, cases_path: Path) -> Dict[str, Any]:
    events = load_legacy_events(events_path)
    cases = load_legacy_cases(cases_path)
    event_ids = [str(event.get("event_id")) for event in events]
    case_ids = [str(case.get("case_id")) for case in cases]
    scope_ids = sorted({str(event.get("scope_id")) for event in events})
    case_scope_ids = sorted({str(case.get("scope_id")) for case in cases})

    issues: List[str] = []
    duplicate_event_ids = sorted([event_id for event_id, count in Counter(event_ids).items() if count > 1])
    duplicate_case_ids = sorted([case_id for case_id, count in Counter(case_ids).items() if count > 1])
    if duplicate_event_ids:
        issues.append(f"duplicate event_id: {duplicate_event_ids}")
    if duplicate_case_ids:
        issues.append(f"duplicate case_id: {duplicate_case_ids}")
    for scope_id in case_scope_ids:
        if scope_id not in scope_ids:
            issues.append(f"case scope has no events: {scope_id}")

    return {
        "events_path": str(events_path),
        "cases_path": str(cases_path),
        "event_count": len(events),
        "case_count": len(cases),
        "scope_count": len(scope_ids),
        "scopes": scope_ids,
        "event_type_distribution": summarize_counts((event.get("event_type") for event in events), "event_type"),
        "status_distribution": summarize_counts((event.get("status", "active") for event in events), "status"),
        "state_relevant_distribution": summarize_counts((event.get("state_relevant", True) for event in events), "state_relevant"),
        "operation_distribution": summarize_counts((case.get("operation") for case in cases), "operation"),
        "time_role_distribution": summarize_counts((case.get("time_role") for case in cases), "time_role"),
        "planned_for_event_count": sum(1 for event in events if event.get("planned_for") is not None),
        "mentioned_differs_from_occurred_count": sum(1 for event in events if event.get("mentioned_at") != event.get("occurred_at")),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the legacy STAMB-State v0 pilot data.")
    parser.add_argument("--events", type=Path, default=LEGACY_DATA_DIR / "events.json")
    parser.add_argument("--cases", type=Path, default=LEGACY_DATA_DIR / "cases.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR / "audit_v0.json")
    args = parser.parse_args()

    report = audit(args.events, args.cases)
    write_json(args.out, report)
    print(f"events={report['event_count']} cases={report['case_count']} scopes={report['scope_count']}")
    print(f"time_roles={report['time_role_distribution']}")
    print(f"operations={report['operation_distribution']}")
    print(f"wrote {args.out}")
    if report["issues"]:
        print("issues:")
        for issue in report["issues"]:
            print(f"- {issue}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

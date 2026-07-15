"""Question-agnostic grounding of relative time expressions against visible anchors."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


ANCHOR_FORMATS: Sequence[str] = (
    "%I:%M %p on %d %B, %Y",
    "%I:%M %p on %d %B %Y",
    "%d %B, %Y",
    "%d %B %Y",
    "%B %d, %Y",
    "%B %d %Y",
    "%d %b, %Y",
    "%d %b %Y",
    "%b %d, %Y",
    "%b %d %Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)
NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
NUMBER_PATTERN = r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"
WEEKDAY_ALIASES = {
    "mon": (0, "Monday"),
    "monday": (0, "Monday"),
    "tue": (1, "Tuesday"),
    "tues": (1, "Tuesday"),
    "tuesday": (1, "Tuesday"),
    "wed": (2, "Wednesday"),
    "weds": (2, "Wednesday"),
    "wednesday": (2, "Wednesday"),
    "thu": (3, "Thursday"),
    "thur": (3, "Thursday"),
    "thurs": (3, "Thursday"),
    "thursday": (3, "Thursday"),
    "fri": (4, "Friday"),
    "friday": (4, "Friday"),
    "sat": (5, "Saturday"),
    "saturday": (5, "Saturday"),
    "sun": (6, "Sunday"),
    "sunday": (6, "Sunday"),
}
WEEKDAY_PATTERN = "|".join(sorted(WEEKDAY_ALIASES, key=len, reverse=True))
TEMPORAL_QUESTION_RE = re.compile(
    r"\b(?:when\s+(?:did|does|do|is|was|were|will|has|have|had|can|could)|"
    r"(?:what|which)\s+(?:date|day|month|year|time)|on\s+what\s+day|"
    r"how\s+long|how\s+many\s+(?:days?|weeks?|months?|years?)|"
    r"(?:time|date)\s+interval|which\s+(?:event\s+)?(?:happened\s+)?(?:first|earlier|later)|"
    r"deadline|due\s+date)\b",
    flags=re.IGNORECASE,
)


def question_requests_temporal_grounding(question: object) -> bool:
    return bool(TEMPORAL_QUESTION_RE.search(" ".join(str(question or "").split())))


def parse_anchor_datetime(value: object) -> Optional[datetime]:
    text = normalize_datetime_text(value)
    if not text:
        return None
    for date_format in ANCHOR_FORMATS:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    iso_prefix = re.match(r"\d{4}-\d{2}-\d{2}", text)
    if iso_prefix:
        try:
            return datetime.strptime(iso_prefix.group(0), "%Y-%m-%d")
        except ValueError:
            return None
    return None


def normalize_datetime_text(value: object) -> str:
    text = " ".join(str(value or "").split())
    return re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)


def format_day(value: datetime) -> str:
    return f"{value.day} {value.strftime('%B')} {value.year}"


def format_month(value: datetime) -> str:
    return value.strftime("%B %Y")


def shift_month(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def number_value(value: str) -> int:
    lowered = value.lower()
    return NUMBER_WORDS.get(lowered, int(lowered) if lowered.isdigit() else 0)


def weekday_relative(anchor: datetime, target_weekday: int, direction: str) -> datetime:
    if direction == "before":
        delta = (anchor.weekday() - target_weekday) % 7 or 7
        return anchor - timedelta(days=delta)
    delta = (target_weekday - anchor.weekday()) % 7 or 7
    return anchor + timedelta(days=delta)


def calendar_week(anchor: datetime, week_offset: int) -> Tuple[datetime, datetime]:
    start = anchor - timedelta(days=anchor.weekday()) + timedelta(weeks=week_offset)
    return start, start + timedelta(days=6)


def previous_weekend(anchor: datetime, count: int = 1) -> Tuple[datetime, datetime]:
    days_since_saturday = (anchor.weekday() - 5) % 7 or 7
    start = anchor - timedelta(days=days_since_saturday + 7 * max(count - 1, 0))
    return start, start + timedelta(days=1)


def next_weekend(anchor: datetime) -> Tuple[datetime, datetime]:
    days_until_saturday = (5 - anchor.weekday()) % 7 or 7
    start = anchor + timedelta(days=days_until_saturday)
    return start, start + timedelta(days=1)


def interval_row(
    *,
    expression: str,
    anchor: datetime,
    kind: str,
    normalized_value: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    duration: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "expression": expression,
        "anchor_time": anchor.isoformat(sep=" "),
        "anchor_date": anchor.date().isoformat(),
        "kind": kind,
        "normalized_value": normalized_value,
        "resolved_start": start.date().isoformat() if start else None,
        "resolved_end": end.date().isoformat() if end else None,
        "duration": duration,
    }


def ground_temporal_expressions(text: object, anchor_value: object) -> List[Dict[str, Any]]:
    """Resolve visible relative expressions without using task labels or answer metadata."""

    source = " ".join(str(text or "").split())
    anchor = parse_anchor_datetime(anchor_value)
    if not source or anchor is None:
        return []

    matches: List[Tuple[int, int, Dict[str, Any]]] = []

    def add(match: re.Match[str], row: Dict[str, Any]) -> None:
        matches.append((match.start(), match.end(), row))

    for match in re.finditer(
        rf"\b(?P<count>{NUMBER_PATTERN})\s+(?P<unit>days?|weeks?|weekends?|months?|years?)\s+ago\b",
        source,
        flags=re.IGNORECASE,
    ):
        count = number_value(match.group("count"))
        unit = match.group("unit").lower()
        expression = match.group(0)
        if unit.startswith("day"):
            resolved = anchor - timedelta(days=count)
            row = interval_row(
                expression=expression,
                anchor=anchor,
                kind="relative_day",
                normalized_value=format_day(resolved),
                start=resolved,
                end=resolved,
            )
        elif unit.startswith("weekend"):
            start, end = previous_weekend(anchor, count)
            count_text = "the" if count == 1 else str(count)
            label = f"{count_text} weekend{'s' if count != 1 else ''} before {format_day(anchor)}"
            row = interval_row(
                expression=expression,
                anchor=anchor,
                kind="relative_weekend",
                normalized_value=label,
                start=start,
                end=end,
            )
        elif unit.startswith("week"):
            start, end = calendar_week(anchor, -count)
            count_text = "the" if count == 1 else str(count)
            label = f"{count_text} week{'s' if count != 1 else ''} before {format_day(anchor)}"
            row = interval_row(
                expression=expression,
                anchor=anchor,
                kind="relative_week",
                normalized_value=label,
                start=start,
                end=end,
            )
        elif unit.startswith("month"):
            resolved = shift_month(anchor, -count)
            row = interval_row(
                expression=expression,
                anchor=anchor,
                kind="relative_month",
                normalized_value=format_month(resolved),
                start=resolved.replace(day=1),
                end=resolved.replace(day=calendar.monthrange(resolved.year, resolved.month)[1]),
            )
        else:
            resolved_year = anchor.year - count
            row = interval_row(
                expression=expression,
                anchor=anchor,
                kind="relative_year",
                normalized_value=f"{count} years ago",
                start=anchor.replace(year=resolved_year),
                end=anchor.replace(year=resolved_year),
                duration=f"{count} years",
            )
        add(match, row)

    for match in re.finditer(
        rf"\bin\s+(?P<count>{NUMBER_PATTERN})\s+(?P<unit>days?|weeks?|months?|years?)\b",
        source,
        flags=re.IGNORECASE,
    ):
        count = number_value(match.group("count"))
        unit = match.group("unit").lower()
        if unit.startswith("day"):
            resolved = anchor + timedelta(days=count)
        elif unit.startswith("week"):
            resolved = anchor + timedelta(weeks=count)
        elif unit.startswith("month"):
            resolved = shift_month(anchor, count)
        else:
            resolved = shift_month(anchor, count * 12)
        add(
            match,
            interval_row(
                expression=match.group(0),
                anchor=anchor,
                kind="relative_future",
                normalized_value=format_day(resolved),
                start=resolved,
                end=resolved,
            ),
        )

    simple_day_rules = (
        (r"\b(?:the )?day after tomorrow(?:\s+(?:morning|afternoon|evening|night))?\b", 2, "relative_day"),
        (r"\bday before yesterday\b", -2, "relative_day"),
        (r"\byesterday\b", -1, "relative_day"),
        (r"\blast night\b", -1, "relative_day"),
        (r"\btoday\b", 0, "relative_day"),
        (r"\btonight\b", 0, "relative_day"),
        (r"\btomorrow\b", 1, "relative_day"),
    )
    for pattern, offset, kind in simple_day_rules:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            resolved = anchor + timedelta(days=offset)
            add(
                match,
                interval_row(
                    expression=match.group(0),
                    anchor=anchor,
                    kind=kind,
                    normalized_value=format_day(resolved),
                    start=resolved,
                    end=resolved,
                ),
            )

    for match in re.finditer(r"\bfrom now on\b", source, flags=re.IGNORECASE):
        add(
            match,
            interval_row(
                expression=match.group(0),
                anchor=anchor,
                kind="open_future_interval",
                normalized_value=f"from {format_day(anchor)} onward",
                start=anchor,
            ),
        )

    for match in re.finditer(
        rf"\b(?P<direction>last|previous|next)\s+(?P<weekday>{WEEKDAY_PATTERN})\b",
        source,
        flags=re.IGNORECASE,
    ):
        weekday, weekday_name = WEEKDAY_ALIASES[match.group("weekday").lower()]
        direction = "after" if match.group("direction").lower() == "next" else "before"
        resolved = weekday_relative(anchor, weekday, direction)
        add(
            match,
            interval_row(
                expression=match.group(0),
                anchor=anchor,
                kind="relative_weekday",
                normalized_value=f"the {weekday_name} {direction} {format_day(anchor)}",
                start=resolved,
                end=resolved,
            ),
        )

    period_rules = (
        (r"\b(?:last|previous) week\b", "relative_week", -1, "the week before"),
        (r"\bthis week\b", "relative_week", 0, "the week of"),
        (r"\bnext week\b", "relative_week", 1, "the week after"),
    )
    for pattern, kind, week_offset, prefix in period_rules:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            start, end = calendar_week(anchor, week_offset)
            add(
                match,
                interval_row(
                    expression=match.group(0),
                    anchor=anchor,
                    kind=kind,
                    normalized_value=f"{prefix} {format_day(anchor)}",
                    start=start,
                    end=end,
                ),
            )

    for match in re.finditer(
        r"\b(?:last|this past|previous) weekend\b",
        source,
        flags=re.IGNORECASE,
    ):
        start, end = previous_weekend(anchor)
        add(
            match,
            interval_row(
                expression=match.group(0),
                anchor=anchor,
                kind="relative_weekend",
                normalized_value=f"the weekend before {format_day(anchor)}",
                start=start,
                end=end,
            ),
        )

    for match in re.finditer(r"\bnext weekend\b", source, flags=re.IGNORECASE):
        start, end = next_weekend(anchor)
        add(
            match,
            interval_row(
                expression=match.group(0),
                anchor=anchor,
                kind="relative_weekend",
                normalized_value=f"the weekend after {format_day(anchor)}",
                start=start,
                end=end,
            ),
        )

    month_rules = (
        (r"\blast month\b", -1),
        (r"\bthis month\b", 0),
        (r"\bnext month\b", 1),
    )
    for pattern, offset in month_rules:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            resolved = shift_month(anchor, offset)
            add(
                match,
                interval_row(
                    expression=match.group(0),
                    anchor=anchor,
                    kind="relative_month",
                    normalized_value=format_month(resolved),
                    start=resolved.replace(day=1),
                    end=resolved.replace(day=calendar.monthrange(resolved.year, resolved.month)[1]),
                ),
            )

    for match in re.finditer(r"\b(?:last|previous) year\b", source, flags=re.IGNORECASE):
        resolved = anchor.replace(year=anchor.year - 1)
        add(
            match,
            interval_row(
                expression=match.group(0),
                anchor=anchor,
                kind="relative_year",
                normalized_value=str(resolved.year),
                start=resolved.replace(month=1, day=1),
                end=resolved.replace(month=12, day=31),
            ),
        )

    for match in re.finditer(
        rf"\b(?P<count>{NUMBER_PATTERN})\s+years?\s+(?:now|so far)\b",
        source,
        flags=re.IGNORECASE,
    ):
        count = number_value(match.group("count"))
        start_year = anchor.year - count
        add(
            match,
            interval_row(
                expression=match.group(0),
                anchor=anchor,
                kind="duration",
                normalized_value=f"since {start_year} ({count} years)",
                start=anchor.replace(year=start_year),
                end=anchor,
                duration=f"{count} years",
            ),
        )

    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: List[Tuple[int, int, Dict[str, Any]]] = []
    for start, end, row in matches:
        if any(start < existing_end and end > existing_start for existing_start, existing_end, _row in selected):
            continue
        selected.append((start, end, row))
    return [row for _start, _end, row in selected]


def ground_explicit_time_value(value: object, anchor_value: object = "") -> Optional[Dict[str, Any]]:
    source_text = normalize_datetime_text(value)
    anchor = parse_anchor_datetime(anchor_value)
    parsed = parse_anchor_datetime(source_text)
    if parsed is None and anchor is not None:
        for date_format in ("%d %B", "%B %d", "%d %b", "%b %d"):
            try:
                partial = datetime.strptime(source_text, date_format)
                parsed = partial.replace(year=anchor.year)
                break
            except ValueError:
                continue
    if parsed is None and anchor is not None:
        for clock_format in ("%I:%M %p", "%I %p", "%H:%M"):
            try:
                clock = datetime.strptime(source_text, clock_format)
                parsed = anchor.replace(
                    hour=clock.hour,
                    minute=clock.minute,
                    second=clock.second,
                    microsecond=0,
                )
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    has_clock = bool(
        re.search(
            r"\b(?:\d{1,2}(?::\d{2})?\s*[ap]m|(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?)\b",
            source_text,
            re.I,
        )
    )
    normalized = format_day(parsed)
    if has_clock:
        normalized = f"{normalized} {parsed.strftime('%H:%M:%S')}"
    anchor = anchor or parsed
    return interval_row(
        expression=source_text,
        anchor=anchor,
        kind="explicit_time",
        normalized_value=normalized,
        start=parsed,
        end=parsed,
    )


def format_temporal_grounding(row: Dict[str, Any], *, include_resolved: bool = False) -> str:
    duration = f" duration={row['duration']!r}" if row.get("duration") else ""
    resolved = ""
    if include_resolved and row.get("resolved_start"):
        resolved_value = str(row["resolved_start"])
        if row.get("resolved_end") and row.get("resolved_end") != row.get("resolved_start"):
            resolved_value = f"{resolved_value}..{row['resolved_end']}"
        resolved = f" resolved={resolved_value}"
    return (
        f"event={row.get('event_id', '')} role={row.get('time_role', '')} "
        f"raw={row.get('expression', '')!r} anchor={row.get('anchor_date', '')} "
        f"normalized={row.get('normalized_value', '')!r}{duration}{resolved}"
    )

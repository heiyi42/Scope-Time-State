from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

import dateparser

from sts.state.models import ResolvedClaimTime
from sts.graph.types import Claim, Event


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_semantic_time(value: Optional[str]) -> Optional[datetime]:
    if not value or not value.strip():
        return None
    parsed = dateparser.parse(
        value,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": "UTC",
            "TO_TIMEZONE": "UTC",
            "PREFER_DAY_OF_MONTH": "first",
        },
    )
    return normalize_datetime(parsed) if parsed else None


_MONTH_NAMES = (
    "january|february|march|april|may|june|july|august|"
    "september|october|november|december|jan|feb|mar|apr|"
    "jun|jul|aug|sep|sept|oct|nov|dec"
)


def infer_time_precision(value: str) -> str:
    normalized = value.strip().casefold()
    if re.search(r"\b\d{1,2}:\d{2}\b|\b(?:am|pm)\b", normalized):
        return "minute"
    if re.fullmatch(r"\d{4}", normalized):
        return "year"
    if re.fullmatch(r"\d{4}[-/]\d{1,2}", normalized):
        return "month"
    if re.search(rf"\b(?:{_MONTH_NAMES})\b", normalized):
        without_year = re.sub(r"\b(?:19|20)\d{2}\b", "", normalized)
        if not re.search(r"\b\d{1,2}\b", without_year):
            return "month"
    return "day"


def semantic_interval(
    value: datetime,
    precision: str,
) -> tuple[datetime, datetime]:
    value = normalize_datetime(value)
    if precision == "year":
        start = value.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        end = start.replace(year=start.year + 1) - timedelta(microseconds=1)
        return start, end
    if precision == "month":
        start = value.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        last_day = calendar.monthrange(start.year, start.month)[1]
        end = start.replace(
            day=last_day,
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
        return start, end
    if precision == "day":
        start = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1) - timedelta(microseconds=1)
    if precision == "minute":
        start = value.replace(second=0, microsecond=0)
        return start, start + timedelta(minutes=1) - timedelta(microseconds=1)
    return value, value


class ClaimTimeResolver:
    """Resolve semantic Claim time without inventing a current timestamp."""

    def resolve(
        self,
        claim: Claim,
        events_by_id: Mapping[str, Event],
    ) -> Optional[ResolvedClaimTime]:
        semantic_time = parse_semantic_time(claim.temporal)
        if semantic_time is not None:
            precision = infer_time_precision(claim.temporal or "")
            start, end = semantic_interval(semantic_time, precision)
            return ResolvedClaimTime(
                semantic_time,
                start,
                end,
                precision,
                "claim_temporal",
                1.0,
            )

        source_events = [
            events_by_id[event_id]
            for event_id in claim.event_ids
            if event_id in events_by_id
        ]
        event_times = [
            normalize_datetime(event_time)
            for event in source_events
            if (event_time := getattr(event, "event_time", None)) is not None
        ]
        if event_times:
            value = min(event_times)
            return ResolvedClaimTime(
                value, value, value, "event", "event_time", 0.9
            )

        event_timestamps = [
            normalize_datetime(event.timestamp)
            for event in source_events
            if event.timestamp is not None
        ]
        if event_timestamps:
            value = min(event_timestamps)
            return ResolvedClaimTime(
                value,
                value,
                value,
                "event",
                "event_timestamp",
                0.8,
            )

        if claim.timestamp is not None:
            value = normalize_datetime(claim.timestamp)
            return ResolvedClaimTime(
                value,
                value,
                value,
                "second",
                "claim_timestamp",
                0.5,
            )
        return None

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Mapping

from sts.state.models import (
    ClaimThreadFeature,
    ResolvedClaimTime,
)
from sts.graph.types import Claim, Event


def normalize_entity(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value.casefold()


def _normalized_unique(values: Iterable[str]) -> tuple[str, ...]:
    normalized = {normalize_entity(value) for value in values if value}
    return tuple(sorted(value for value in normalized if value))


class ClaimThreadFeatureBuilder:
    def build(
        self,
        claim: Claim,
        resolved: ResolvedClaimTime,
        events_by_id: Mapping[str, Event],
    ) -> ClaimThreadFeature:
        source_events = [
            events_by_id[event_id]
            for event_id in claim.event_ids
            if event_id in events_by_id
        ]
        participant_values = []
        for event in source_events:
            participant_values.extend(event.participants or [])
            for row in event.original_data:
                for key in ("speaker_name", "user_name"):
                    value = row.get(key)
                    if isinstance(value, str):
                        participant_values.append(value)
        participants = _normalized_unique(participant_values)
        topic_entities = _normalized_unique([claim.spatial or ""])
        topic_terms = _normalized_unique(claim.keywords or [])
        thread_entities = _normalized_unique(
            [*participants, *topic_entities]
        )

        structured_text = "\n".join(
            [
                f"WHAT: {claim.content}",
                (
                    "WHO: "
                    + (
                        " | ".join(thread_entities)
                        if thread_entities
                        else "UNKNOWN"
                    )
                ),
                f"WHERE: {claim.spatial or 'UNKNOWN'}",
                f"WHEN: {claim.temporal or resolved.value.isoformat()}",
                (
                    "KEYWORDS: "
                    + (" | ".join(claim.keywords) if claim.keywords else "UNKNOWN")
                ),
            ]
        )
        return ClaimThreadFeature(
            claim_id=claim.claim_id,
            structured_text=structured_text,
            content_text=claim.content,
            resolved_time=resolved.value,
            time_start=resolved.start,
            time_end=resolved.end,
            time_precision=resolved.precision,
            time_source=resolved.source,
            time_confidence=resolved.confidence,
            participants=participants,
            topic_entities=topic_entities,
            topic_terms=topic_terms,
            event_ids=tuple(claim.event_ids),
            claim_confidence=claim.confidence,
        )

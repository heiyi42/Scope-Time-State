from __future__ import annotations

import datetime as dt
import json
import re

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None

from sts.prompts.epbench_event_prompts import EPBENCH_EVENT_EXTRACTION_PROMPT
from sts.graph.types import Event, RawDataType
from sts.utils.datetime_utils import get_timezone


MONTH_DATE_PATTERN = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}\b",
    flags=re.IGNORECASE,
)


def _json_object(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        if json_repair is None:
            raise
        value = json_repair.loads(text)
    if not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object")
    return value


async def generate_json(llm_provider, prompt: str, attempts: int = 3) -> dict:
    error = None
    for attempt in range(attempts):
        current = prompt
        if error is not None:
            current += (
                "\n\nThe previous output was invalid. Return only the requested "
                f"JSON object. Validation error: {error}"
            )
        try:
            response = await llm_provider.generate(
                current,
                response_format={"type": "json_object"},
            )
            return _json_object(response)
        except (ValueError, json.JSONDecodeError) as caught:
            error = caught
    raise ValueError(f"LLM did not return a valid JSON object: {error}")


def parse_event_time(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    match = MONTH_DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return dt.datetime.strptime(
            match.group(0).title(), "%B %d, %Y"
        ).replace(tzinfo=get_timezone())
    except ValueError:
        return None


class EPBenchEventExtractor:
    def __init__(self, llm_provider):
        self.llm_provider = llm_provider

    async def extract_event(
        self,
        book_id: str,
        chapter_idx: int,
        chapter_text: str,
    ) -> Event:
        output = await generate_json(
            self.llm_provider,
            EPBENCH_EVENT_EXTRACTION_PROMPT.format(
                chapter_idx=chapter_idx,
                chapter_text=chapter_text,
            ),
        )
        for field in ("title", "summary", "content"):
            if not isinstance(output.get(field), str) or not output[field].strip():
                raise ValueError(
                    f"Chapter {chapter_idx}: missing non-empty {field}"
                )
        for field in ("entities", "locations", "keywords"):
            if not isinstance(output.get(field), list):
                raise ValueError(f"Chapter {chapter_idx}: {field} must be a list")
        if output.get("event_type") is not None and not isinstance(
            output["event_type"], str
        ):
            raise ValueError(f"Chapter {chapter_idx}: event_type must be a string")

        event_time_text = output.get("event_time_text")
        if event_time_text is not None and (
            not isinstance(event_time_text, str)
            or event_time_text not in chapter_text
        ):
            event_time_text = None
        if event_time_text is None:
            match = MONTH_DATE_PATTERN.search(chapter_text)
            event_time_text = match.group(0) if match else None
        timestamp = parse_event_time(event_time_text)
        entities = [str(value).strip() for value in output["entities"] if str(value).strip()]
        locations = [str(value).strip() for value in output["locations"] if str(value).strip()]
        confidence = min(1.0, max(0.0, float(output.get("confidence", 0.8))))
        content = output["content"].strip()
        summary = output["summary"].strip()
        return Event(
            event_id=f"{book_id}:chapter:{chapter_idx}",
            user_id_list=[],
            original_data=[{"chapter_idx": chapter_idx, "text": chapter_text}],
            timestamp=timestamp,
            summary=summary,
            participants=entities,
            type=RawDataType.BOOK_CHAPTER,
            keywords=[
                str(value).strip()
                for value in output["keywords"]
                if str(value).strip()
            ],
            subject=output["title"].strip(),
            event_description=content,
            book_id=book_id,
            chapter_idx=chapter_idx,
            event_time_text=event_time_text,
            entities=entities,
            locations=locations,
            event_type=output.get("event_type"),
            extraction_confidence=confidence,
            metadata={"dataset": "epbench", "source_type": "book_chapter"},
        )

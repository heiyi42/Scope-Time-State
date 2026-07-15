"""Extract ARTEM events from the fixed EPBench Long Book.

Only ``book.json`` is shown to the extraction model. The QA parquet is converted
separately for retrieval and is never part of the event-extraction prompt.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from config import (
    BOOK_ID,
    DEFAULT_OUTPUT_ROOT,
    EPBENCH_BOOK_PATH,
    EPBENCH_QA_PATH,
    REPO_ROOT,
    book_output_dir,
    validate_source_paths,
)


MODEL = "gpt-4o-mini"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Experiment.run.common.llm_client import LLMClient, provider_config  # noqa: E402


def load_book_chapters(book_path: Path = EPBENCH_BOOK_PATH) -> list[dict[str, Any]]:
    with book_path.open("r", encoding="utf-8") as stream:
        book = json.load(stream)
    if not isinstance(book, str):
        raise TypeError(f"EPBench book.json must contain a JSON string, got {type(book).__name__}")

    matches = list(
        re.finditer(
            r"^Chapter\s+(\d+)\s*$\n(.*?)(?=^Chapter\s+\d+\s*$|\Z)",
            book,
            flags=re.MULTILINE | re.DOTALL,
        )
    )
    chapters = [
        {"chapter": int(match.group(1)), "text": match.group(2).strip()}
        for match in matches
    ]
    if len(chapters) != 196:
        raise ValueError(f"Expected 196 validated EPBench chapters, found {len(chapters)}")
    return chapters


def prepare_qa(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    """Convert the fixed 686-row QA parquet to ARTEM JSON without reordering."""
    validate_source_paths()
    output_dir = book_output_dir(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    qa_output = output_dir / f"qa_book{BOOK_ID}.json"

    qa = pd.read_parquet(EPBENCH_QA_PATH)
    if len(qa) != 686:
        raise ValueError(f"Expected 686 EPBench questions, found {len(qa)}")
    required = {
        "q_idx",
        "question",
        "cue",
        "cue_completed",
        "retrieval_type",
        "get",
        "correct_answer",
        "n_chapters_correct_answer",
    }
    missing = sorted(required.difference(qa.columns))
    if missing:
        raise ValueError(f"EPBench QA parquet is missing columns: {missing}")

    records = json.loads(qa.to_json(orient="records"))
    for row_index, record in enumerate(records):
        record["artem_query_index"] = row_index
    with qa_output.open("w", encoding="utf-8") as stream:
        json.dump(records, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return qa_output


def event_extraction_prompt(chapter_text: str, chapter_number: int) -> str:
    return f"""Extract one episodic event from Chapter {chapter_number}.
Use only the chapter text below. Return exactly one JSON object with these keys:
{{"date": ["Month DD, YYYY"], "location": "...", "entity": ["..."], "content": "..."}}

The content must be one short sentence describing the central event. Do not use
Markdown and do not add any explanation.

Chapter {chapter_number}:
{chapter_text}
"""


def parse_extracted_event(response: str | dict[str, Any], chapter_number: int) -> dict[str, Any]:
    if isinstance(response, dict):
        parsed = response
    else:
        match = re.search(r"\{.*\}", response, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Chapter {chapter_number}: model returned no JSON object")
        payload = match.group(0)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = ast.literal_eval(payload)
    if not isinstance(parsed, dict):
        raise ValueError(f"Chapter {chapter_number}: extracted payload is not an object")

    dates = parsed.get("date", [])
    if isinstance(dates, str):
        dates = [dates]
    entities = parsed.get("entity", [])
    if isinstance(entities, str):
        entities = [entities]
    location = parsed.get("location", "")
    if isinstance(location, list):
        location = location[0] if location else ""

    normalized_entities = []
    for item in entities:
        if isinstance(item, dict):
            item = item.get("name") or item.get("entity") or ""
        value = str(item).strip()
        if value:
            normalized_entities.append(value)

    return {
        "chapter": chapter_number,
        "time": [str(item).strip() for item in dates if str(item).strip()],
        "spaces": str(location).strip(),
        "entities": normalized_entities,
        "content": str(parsed.get("content", "")).strip(),
    }


class OpenAIEventExtractor:
    def __init__(self, output_root: Path | str, use_cache: bool = True) -> None:
        load_dotenv(REPO_ROOT / ".env")
        api_key, _, api_base = provider_config("openai")
        self.client = LLMClient(
            provider="openai",
            model=MODEL,
            api_key=api_key,
            api_base=api_base,
            cache_path=Path(output_root) / "llm_cache.event_extraction.gpt-4o-mini.json",
            use_cache=use_cache,
        )

    def generate(self, prompt: str) -> dict[str, Any]:
        return self.client.complete_json(
            "You are a precise information extraction system. Return only the requested JSON object.",
            prompt,
        )


def extract_events(
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    limit_chapters: int | None = None,
    resume: bool = True,
    use_cache: bool = True,
) -> Path:
    validate_source_paths()
    chapters = load_book_chapters()
    if limit_chapters is not None:
        if limit_chapters <= 0:
            raise ValueError("limit_chapters must be positive")
        chapters = chapters[:limit_chapters]

    output_dir = book_output_dir(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"extracted_features_book{BOOK_ID}.json"

    existing: dict[int, dict[str, Any]] = {}
    if resume and output_path.is_file():
        with output_path.open("r", encoding="utf-8") as stream:
            existing = {int(item["chapter"]): item for item in json.load(stream)}

    pending = [chapter for chapter in chapters if chapter["chapter"] not in existing]
    if pending:
        extractor = OpenAIEventExtractor(output_root, use_cache=use_cache)
        for position, chapter in enumerate(pending, start=1):
            print(
                f"Extracting chapter {chapter['chapter']} "
                f"({position}/{len(pending)}) with {MODEL}"
            )
            response = extractor.generate(
                event_extraction_prompt(chapter["text"], chapter["chapter"])
            )
            event = parse_extracted_event(response, chapter["chapter"])
            existing[chapter["chapter"]] = event
            ordered = [existing[key] for key in sorted(existing)]
            with output_path.open("w", encoding="utf-8") as stream:
                json.dump(ordered, stream, indent=2, ensure_ascii=False)
                stream.write("\n")

    print(f"Extracted events ready: {output_path} ({len(existing)} chapters)")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract ARTEM events from EPBench Long Book")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--limit-chapters", type=int)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    qa_path = prepare_qa(args.output_root)
    print(f"QA ready: {qa_path}")
    extract_events(
        output_root=args.output_root,
        limit_chapters=args.limit_chapters,
        resume=not args.no_resume,
        use_cache=not args.no_cache,
    )


if __name__ == "__main__":
    main()

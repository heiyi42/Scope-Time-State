"""Protocol-aligned answer prompt for the official LoCoMo runner."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional


ANSWERER_MEMORY_LIMIT = 200


def _human_date(value: str) -> str:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:26].rstrip("Z"), fmt.replace("%z", "")).strftime("%A, %B %d, %Y")
        except ValueError:
            continue
    return value[:10] or "unknown date"


def _format_memories(search_results: Iterable[Dict[str, Any]]) -> str:
    rows = list(search_results)[:ANSWERER_MEMORY_LIMIT]
    if not rows:
        return "(No relevant memories found)"
    rows.sort(key=lambda item: str(item.get("created_at", "")))
    lines = ["The following memories are presented in chronological order (oldest to newest).", ""]
    for item in rows:
        created_at = str(item.get("created_at", ""))
        prefix = f"({_human_date(created_at)})" if created_at else "(unknown date)"
        lines.append(f"{prefix} {item.get('memory', '')}")
    return "\n".join(lines)


def get_answer_generation_prompt(
    question: str,
    search_results: Iterable[Dict[str, Any]],
    *,
    reference_date: Optional[str] = None,
) -> str:
    reference_date = reference_date or "2023"
    memories = _format_memories(search_results)
    return f"""You are answering a question using retrieved memories from past conversations.

Read every memory and combine relevant facts. Verify the correct person or entity, prefer the most
specific supported detail, and include all supported items for list or count questions. Use the
conversation date as the temporal reference; do not use today's date or invent names, dates, or facts.
For temporal questions, resolve relative time against {reference_date}. Reason about the memories first,
then give the final answer after exactly `ANSWER:`.

{memories}

Question: {question}

ANSWER:"""

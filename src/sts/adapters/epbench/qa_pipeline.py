from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from sts.extraction.epbench_event_extractor import generate_json
from sts.prompts.epbench_answer_prompts import EPBENCH_ANSWER_PROMPT

from .context_builder import EPBenchRetriever, format_context
from .loader import load_qa_questions
from .query_parser import parse_query_plan


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def render_answer(output: dict) -> str:
    if not isinstance(output.get("has_answer"), bool):
        raise ValueError("Answer output requires boolean has_answer")
    if not isinstance(output.get("items"), list):
        raise ValueError("Answer output requires an items list")
    if any(not isinstance(item, str) for item in output["items"]):
        raise ValueError("Every answer item must be a string")
    items = [item.strip() for item in output["items"] if item.strip()]
    if not output["has_answer"] or not items:
        return "No matching evidence was found."
    if len(items) == 1:
        return items[0]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))


class EPBenchQARunner:
    def __init__(
        self,
        llm_provider,
        embedding_provider,
        concurrency: int = 8,
    ):
        self.llm = llm_provider
        self.embedding_provider = embedding_provider
        self.concurrency = max(1, concurrency)

    async def run(
        self,
        graph_path: str | Path,
        data_folder: str | Path,
        output_path: str | Path,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Path:
        graph_path = Path(graph_path)
        output_path = Path(output_path)
        graph_bytes = graph_path.read_bytes()
        graph_sha256 = hashlib.sha256(graph_bytes).hexdigest()
        answer_model = str(getattr(self.llm, "model", "unknown"))
        graph = json.loads(graph_bytes)
        if graph.get("schema_version") != "sts_epbench_v1":
            raise ValueError("QA requires an sts_epbench_v1 graph")
        retriever = EPBenchRetriever(
            graph,
            self.embedding_provider,
            graph_path.parent
            / "cache"
            / "sts_epbench_v1"
            / "qa_retrieval_embeddings.json",
        )
        retrieval_signature = hashlib.sha256(
            "\0".join(
                [
                    graph_sha256,
                    str(self.embedding_provider.model_name),
                    "scope9-raw-claim-rrf30-state-event-pack-v5",
                ]
            ).encode()
        ).hexdigest()
        questions = load_qa_questions(data_folder)
        if offset < 0:
            raise ValueError("QA offset must be non-negative")
        questions = questions[offset:]
        if limit is not None:
            questions = questions[:limit]
        completed = {}
        if output_path.exists():
            old = json.loads(output_path.read_text(encoding="utf-8"))
            if (
                old.get("graph_path") == str(graph_path.resolve())
                and old.get("graph_sha256") == graph_sha256
                and old.get("answer_model") == answer_model
                and old.get("retrieval_signature")
                == retrieval_signature
            ):
                completed = {row["row_idx"]: row for row in old.get("rows", [])}

        semaphore = asyncio.Semaphore(self.concurrency)
        save_lock = asyncio.Lock()

        def payload(rows: list[dict]) -> dict:
            return {
                "schema_version": "epbench_qa_v1",
                "graph_path": str(graph_path.resolve()),
                "graph_sha256": graph_sha256,
                "answer_model": answer_model,
                "embedding_model": str(
                    self.embedding_provider.model_name
                ),
                "retrieval_signature": retrieval_signature,
                "rows": sorted(rows, key=lambda row: row["row_idx"]),
            }

        async def one(question: dict) -> dict:
            if question["row_idx"] in completed:
                return completed[question["row_idx"]]
            plan = parse_query_plan(question["question"])
            selection = await retriever.retrieve(
                question["question"],
                plan,
            )
            context = format_context(graph, selection)
            if not selection["claim_ids"]:
                answer = "No matching evidence was found."
            else:
                async with semaphore:
                    output = await generate_json(
                        self.llm,
                        EPBENCH_ANSWER_PROMPT.format(
                            query_plan=json.dumps(plan.to_dict(), ensure_ascii=False),
                            context=context,
                            question=question["question"],
                        ),
                    )
                answer = render_answer(output)
            row = {
                **question,
                "answer": answer,
                "query_plan": plan.to_dict(),
                "retrieval_mode": selection["retrieval_mode"],
                "retrieved_scope_ids": selection["scope_ids"],
                "retrieved_state_ids": selection["state_ids"],
                "retrieved_claim_ids": selection["claim_ids"],
                "packed_event_ids": selection["packed_event_ids"],
                "retrieval_log": selection["retrieval_log"],
            }
            async with save_lock:
                completed[row["row_idx"]] = row
                _atomic_json(output_path, payload(list(completed.values())))
            return row

        rows = await asyncio.gather(*(one(question) for question in questions))
        rows.sort(key=lambda row: row["row_idx"])
        _atomic_json(output_path, payload(rows))
        return output_path

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import networkx as nx

from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph.graph_store import write_graph_artifact
from longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v2_stability_first.status_utils import (
    atomic_write_json,
    read_json,
    utc_now_iso,
)
from longmemeval_s_graph_retrieval.task_semantics_local_graph.graph_builder import (
    ALLOWED_EDGE_TYPES,
    ALLOWED_NODE_TYPES,
    CORRECTION_MARKERS,
    EDGE_CLAIM_CORRECTS_CLAIM,
    EDGE_CLAIM_SUPPORTED_BY_EVENT,
    EDGE_CLAIM_SUPERSEDES_CLAIM,
    EDGE_FACET_CURRENT_AFTER_TIME,
    EDGE_FACET_SUPPORTED_BY_CLAIM,
    NEGATION_MARKERS,
    NODE_CLAIM,
    NODE_STATE_FACET,
    TaskSemanticsLocalGraphBuilder,
    UPDATE_MARKERS,
    has_any_marker,
    important_terms,
    normalize_label,
    parse_sort_key,
    stable_id,
)


StatusCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class CheckpointBuildResult:
    graph: nx.MultiDiGraph
    total_batches: int
    completed_batches: int
    llm_batch_calls: int
    reused_batch_checkpoints: int
    state_reconcile_ran: bool
    partial_graph_path: Path | None


class CheckpointedQuestionIndependentGraphBuilder:
    """Build the v2 graph schema with durable batch checkpoints."""

    def __init__(
        self,
        extractor: Any,
        batch_size: int,
        max_facets: int,
        batch_dir: Path,
        partial_graph_path: Path | None,
        partial_graph_every: int,
        resume: bool,
        run_state_reconcile: bool,
        max_claims_per_event: int,
        max_entity_labels: int,
        max_scope_labels: int,
        status_callback: StatusCallback | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if max_facets < 1:
            raise ValueError("max_facets must be >= 1")
        if partial_graph_every < 1:
            raise ValueError("partial_graph_every must be >= 1")
        if max_claims_per_event < 0:
            raise ValueError("max_claims_per_event must be >= 0")
        if max_entity_labels < 1:
            raise ValueError("max_entity_labels must be >= 1")
        if max_scope_labels < 1:
            raise ValueError("max_scope_labels must be >= 1")
        self.extractor = extractor
        self.batch_size = batch_size
        self.max_facets = max_facets
        self.batch_dir = batch_dir
        self.partial_graph_path = partial_graph_path
        self.partial_graph_every = partial_graph_every
        self.resume = resume
        self.run_state_reconcile = run_state_reconcile
        self.max_claims_per_event = max_claims_per_event
        self.max_entity_labels = max_entity_labels
        self.max_scope_labels = max_scope_labels
        self.status_callback = status_callback
        self.base = TaskSemanticsLocalGraphBuilder(batch_size=batch_size, max_facets=max_facets, extractor=None)

    def build(
        self,
        sessions: Sequence[Mapping[str, Any]],
        metadata: Mapping[str, Any],
        question_id: str,
    ) -> CheckpointBuildResult:
        normalized = self.base._normalize_sessions(sessions)
        normalized = sorted(normalized, key=lambda item: parse_sort_key(item.date, item.order))
        graph = nx.MultiDiGraph()
        graph.graph["schema"] = {
            "node_types": sorted(ALLOWED_NODE_TYPES),
            "edge_types": sorted(ALLOWED_EDGE_TYPES),
            "method": "task_semantics_local_graph",
        }
        graph.graph["method"] = "prebuilt_llm_kg_graph_v10_1"
        graph.graph["question_independent_construction"] = True
        latest_time_node = self.base._add_latest_time_node(graph, normalized, "")
        graph.graph["latest_time_node"] = latest_time_node

        event_records = self.base._add_event_nodes_for_extractor(graph, normalized, "", "", set())
        total_batches = ceil(len(event_records) / self.batch_size) if event_records else 0
        self._emit(
            "base_graph_ready",
            {
                "question_id": question_id,
                "total_events": len(event_records),
                "total_batches": total_batches,
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
            },
        )
        self._write_partial_graph(graph, metadata, "base")

        event_by_id = {str(item["event_id"]): item for item in event_records}
        previous_claims: list[dict[str, Any]] = []
        claim_ref_to_id: dict[str, str] = {}
        claim_order: list[str] = []
        completed_batches = 0
        llm_batch_calls = 0
        reused_batch_checkpoints = 0

        self.batch_dir.mkdir(parents=True, exist_ok=True)
        for batch_index, start in enumerate(range(0, len(event_records), self.batch_size)):
            batch_events = event_records[start : start + self.batch_size]
            checkpoint_path = self.batch_dir / f"batch_{batch_index:04d}.claims.json"
            extraction, reused = self._load_or_extract_batch(
                checkpoint_path,
                batch_index,
                batch_events,
                previous_claims,
                total_batches,
            )
            if reused:
                reused_batch_checkpoints += 1
            else:
                llm_batch_calls += 1
            batch_claim_refs = self._ingest_batch(
                graph,
                extraction,
                event_by_id,
                start,
                latest_time_node,
                previous_claims,
                claim_ref_to_id,
                claim_order,
            )
            completed_batches += 1
            self.base._add_extracted_relations(
                graph,
                extraction.get("relations") or [],
                claim_ref_to_id,
                batch_claim_refs,
                previous_claims,
            )
            self._emit(
                "batch_ingested",
                {
                    "question_id": question_id,
                    "batch_index": batch_index,
                    "completed_batches": completed_batches,
                    "total_batches": total_batches,
                    "claims": len(previous_claims),
                    "nodes": graph.number_of_nodes(),
                    "edges": graph.number_of_edges(),
                    "reused_checkpoint": reused,
                },
            )
            if completed_batches % self.partial_graph_every == 0 or completed_batches == total_batches:
                self._write_partial_graph(graph, metadata, f"batch_{batch_index:04d}")

        state_reconcile_ran = False
        if self.run_state_reconcile and previous_claims:
            state_reconcile_ran = True
            state = self._load_or_extract_state(question_id, previous_claims)
            self._materialize_state_result(graph, state, previous_claims, claim_ref_to_id, latest_time_node)
            self._write_partial_graph(graph, metadata, "state_reconciled")

        return CheckpointBuildResult(
            graph=graph,
            total_batches=total_batches,
            completed_batches=completed_batches,
            llm_batch_calls=llm_batch_calls,
            reused_batch_checkpoints=reused_batch_checkpoints,
            state_reconcile_ran=state_reconcile_ran,
            partial_graph_path=self.partial_graph_path,
        )

    def _load_or_extract_batch(
        self,
        checkpoint_path: Path,
        batch_index: int,
        batch_events: Sequence[Mapping[str, Any]],
        previous_claims: Sequence[Mapping[str, Any]],
        total_batches: int,
    ) -> tuple[dict[str, Any], bool]:
        if self.resume and checkpoint_path.exists():
            payload = read_json(checkpoint_path)
            extraction = dict(payload.get("extraction") or {})
            self._emit(
                "batch_checkpoint_loaded",
                {"batch_index": batch_index, "total_batches": total_batches, "checkpoint_path": str(checkpoint_path)},
            )
            return extraction, True

        self._emit(
            "extracting_batch",
            {
                "batch_index": batch_index,
                "total_batches": total_batches,
                "event_ids": [str(item.get("event_id")) for item in batch_events],
            },
        )
        extraction = dict(
            self.extractor.extract_batch(
                batch_events=batch_events,
                question="",
                question_type="",
                question_date="",
                previous_claims=list(previous_claims)[-80:],
            )
        )
        payload = {
            "method": "prebuilt_llm_kg_graph_v10_1",
            "batch_index": batch_index,
            "event_ids": [str(item.get("event_id")) for item in batch_events],
            "n_previous_claims": len(previous_claims),
            "extraction": extraction,
            "created_at": utc_now_iso(),
        }
        atomic_write_json(checkpoint_path, payload)
        self._emit(
            "batch_checkpoint_written",
            {"batch_index": batch_index, "total_batches": total_batches, "checkpoint_path": str(checkpoint_path)},
        )
        return extraction, False

    def _ingest_batch(
        self,
        graph: nx.MultiDiGraph,
        extraction: Mapping[str, Any],
        event_by_id: Mapping[str, Mapping[str, Any]],
        batch_start: int,
        latest_time_node: str,
        previous_claims: list[dict[str, Any]],
        claim_ref_to_id: dict[str, str],
        claim_order: list[str],
    ) -> dict[str, str]:
        batch_claim_refs: dict[str, str] = {}
        claims_by_event: dict[str, int] = {}
        for index, raw_claim in enumerate(extraction.get("claims") or []):
            if not isinstance(raw_claim, Mapping):
                continue
            event_id = str(raw_claim.get("event_id", ""))
            if event_id not in event_by_id:
                continue
            claim_text = str(raw_claim.get("claim") or raw_claim.get("text") or "").strip()
            if not claim_text:
                continue
            if self.max_claims_per_event:
                claims_by_event[event_id] = claims_by_event.get(event_id, 0) + 1
                if claims_by_event[event_id] > self.max_claims_per_event:
                    continue
            claim_ref = str(raw_claim.get("claim_ref") or raw_claim.get("id") or f"batch_{batch_start}_{index}")
            scope_labels = self.base._normalized_label_list(raw_claim.get("scope_labels") or raw_claim.get("scopes"))
            entity_labels = self.base._normalized_label_list(raw_claim.get("entity_labels") or raw_claim.get("entities"))
            scope_labels = (scope_labels or self.base._extract_scopes("", "", claim_text))[: self.max_scope_labels]
            entity_labels = (entity_labels or self.base._extract_entities("", claim_text, set()))[: self.max_entity_labels]

            event_record = event_by_id[event_id]
            self.base._connect_event_semantics(graph, event_id, entity_labels, scope_labels)
            claim_id = stable_id("claim", f"{event_id}:{claim_ref}:{claim_text}")
            claim_terms = set(important_terms(claim_text, limit=16))
            self.base._add_node(
                graph,
                claim_id,
                NODE_CLAIM,
                text=claim_text,
                session_id=event_record["session_id"],
                event_id=event_id,
                role=event_record["role"],
                date=event_record["date"],
                parsed_date=event_record["parsed_date"],
                sort_key=int(event_record["sort_key"]) * 10 + index,
                terms=sorted(claim_terms),
                entity_labels=entity_labels,
                scope_labels=scope_labels,
                has_update_marker=has_any_marker(claim_text, UPDATE_MARKERS),
                has_correction_marker=has_any_marker(claim_text, CORRECTION_MARKERS),
                has_negation_marker=has_any_marker(claim_text, NEGATION_MARKERS),
                source="llm_extractor",
                claim_ref=claim_ref,
            )
            self.base._add_edge(graph, claim_id, event_id, EDGE_CLAIM_SUPPORTED_BY_EVENT)
            claim_order.append(claim_id)
            batch_claim_refs[claim_ref] = claim_id
            claim_ref_to_id[claim_ref] = claim_id

            facet = raw_claim.get("state_facet")
            is_current = bool(raw_claim.get("is_current") or raw_claim.get("current") or raw_claim.get("supports_current_state"))
            if isinstance(facet, Mapping) and is_current and not self.run_state_reconcile:
                self.base._materialize_llm_facet(graph, claim_id, facet, latest_time_node)

            previous_claims.append(
                {
                    "claim_id": claim_id,
                    "claim_ref": claim_ref,
                    "claim": claim_text,
                    "scope_labels": scope_labels,
                    "entity_labels": entity_labels,
                    "session_id": event_record["session_id"],
                    "date": event_record["date"],
                }
            )
        return batch_claim_refs

    def _load_or_extract_state(self, question_id: str, previous_claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        state_path = self.batch_dir.parent / "state" / f"{question_id}.state.json"
        if self.resume and state_path.exists():
            payload = read_json(state_path)
            self._emit("state_checkpoint_loaded", {"state_path": str(state_path)})
            return dict(payload.get("state") or {})
        self._emit("extracting_state_facets", {"n_claims": len(previous_claims)})
        state = dict(
            self.extractor.extract_state_facets(
                claims=previous_claims,
                question="",
                question_type="",
                question_date="",
            )
        )
        atomic_write_json(
            state_path,
            {
                "method": "prebuilt_llm_kg_graph_v10_1",
                "question_id": question_id,
                "n_claims": len(previous_claims),
                "state": state,
                "created_at": utc_now_iso(),
            },
        )
        self._emit("state_checkpoint_written", {"state_path": str(state_path)})
        return state

    def _materialize_state_result(
        self,
        graph: nx.MultiDiGraph,
        state: Mapping[str, Any],
        previous_claims: Sequence[Mapping[str, Any]],
        claim_ref_to_id: Mapping[str, str],
        latest_time_node: str,
    ) -> None:
        self.base._add_extracted_relations(
            graph,
            state.get("relations") or [],
            claim_ref_to_id,
            claim_ref_to_id,
            previous_claims,
        )
        for raw_rejected in state.get("rejected_claims") or []:
            if not isinstance(raw_rejected, Mapping):
                continue
            rejected_id = str(raw_rejected.get("claim_id") or "")
            rejected_by_id = str(raw_rejected.get("rejected_by_claim_id") or raw_rejected.get("active_claim_id") or "")
            if not rejected_id or not rejected_by_id or rejected_id == rejected_by_id:
                continue
            if not graph.has_node(rejected_id) or not graph.has_node(rejected_by_id):
                continue
            reason = normalize_label(str(raw_rejected.get("reason") or "stale"))
            edge_type = EDGE_CLAIM_SUPERSEDES_CLAIM if reason == "stale" else EDGE_CLAIM_CORRECTS_CLAIM
            self.base._add_edge(
                graph,
                rejected_by_id,
                rejected_id,
                edge_type,
                reason=str(raw_rejected.get("reason") or "llm_rejected_claim"),
            )

        for index, raw_facet in enumerate(state.get("state_facets") or []):
            if not isinstance(raw_facet, Mapping):
                continue
            name = normalize_label(str(raw_facet.get("name") or "task_state"))
            value = str(raw_facet.get("value") or "").strip()
            support_claim_ids = [
                str(item)
                for item in raw_facet.get("support_claim_ids") or raw_facet.get("claim_ids") or []
                if item
            ]
            support_claim_ids = [claim_id for claim_id in support_claim_ids if graph.has_node(claim_id)]
            if not value or not support_claim_ids:
                continue
            facet_id = stable_id("facet", f"final:{index}:{name}:{value}:{','.join(support_claim_ids)}")
            self.base._add_node(
                graph,
                facet_id,
                NODE_STATE_FACET,
                name=name,
                value=value,
                claim_id=support_claim_ids[0],
                session_id=graph.nodes[support_claim_ids[0]].get("session_id"),
                current_after=graph.nodes[support_claim_ids[0]].get("parsed_date")
                or graph.nodes[support_claim_ids[0]].get("date")
                or "",
                source="llm_state_reconcile",
            )
            for claim_id in support_claim_ids:
                self.base._add_edge(graph, facet_id, claim_id, EDGE_FACET_SUPPORTED_BY_CLAIM)
            self.base._add_edge(graph, facet_id, latest_time_node, EDGE_FACET_CURRENT_AFTER_TIME)

    def _write_partial_graph(self, graph: nx.MultiDiGraph, metadata: Mapping[str, Any], stage: str) -> None:
        if self.partial_graph_path is None:
            return
        partial_metadata = dict(metadata)
        partial_metadata["partial"] = True
        partial_metadata["partial_stage"] = stage
        partial_metadata["partial_updated_at"] = utc_now_iso()
        write_graph_artifact(self.partial_graph_path, graph, partial_metadata)
        self._emit(
            "partial_graph_written",
            {
                "partial_graph_path": str(self.partial_graph_path),
                "partial_stage": stage,
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
            },
        )

    def _emit(self, stage: str, payload: dict[str, Any]) -> None:
        if self.status_callback is not None:
            self.status_callback(stage, payload)


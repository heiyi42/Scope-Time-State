from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence, Tuple, Union

import networkx as nx

from .graph_builder import TaskSemanticsLocalGraphBuilder
from .graph_retriever import StatePacketGraphRetriever
from .llm_extractor import JsonLLMClient, LLMGraphExtractor


def build_state_packet_from_sessions(
    sessions: Sequence[Mapping[str, Any]],
    question: str,
    question_type: str = "",
    question_date: str = "",
    batch_size: int = 5,
    max_facets: int = 12,
    extractor: object = None,
    return_graph: bool = False,
) -> Union[Dict[str, Any], Tuple[Dict[str, Any], nx.MultiDiGraph]]:
    """Build a local graph from candidate sessions and return a State_packet.

    The expected `sessions` input is the BM25 top-k candidate set already
    selected by the existing pipeline. Each item should contain:

    - `session_id`: LongMemEval session id
    - `date`: session timestamp string
    - `turns`: list of `{role, content}` turn dictionaries
    """

    builder = TaskSemanticsLocalGraphBuilder(batch_size=batch_size, max_facets=max_facets, extractor=extractor)
    graph = builder.build(
        sessions=sessions,
        question=question,
        question_type=question_type,
        question_date=question_date,
    )
    retriever = StatePacketGraphRetriever()
    state_packet = retriever.retrieve_state_packet(graph)
    if return_graph:
        return state_packet, graph
    return state_packet


def build_state_packet_with_llm_client(
    sessions: Sequence[Mapping[str, Any]],
    question: str,
    llm_client: JsonLLMClient,
    question_type: str = "",
    question_date: str = "",
    batch_size: int = 5,
    max_facets: int = 12,
    return_graph: bool = False,
) -> Union[Dict[str, Any], Tuple[Dict[str, Any], nx.MultiDiGraph]]:
    """Build State_packet using LLM-backed graph construction.

    This is the intended benchmark path for this method. The heuristic builder is
    kept only as a local no-API fallback.
    """

    extractor = LLMGraphExtractor(llm_client)
    return build_state_packet_from_sessions(
        sessions=sessions,
        question=question,
        question_type=question_type,
        question_date=question_date,
        batch_size=batch_size,
        max_facets=max_facets,
        extractor=extractor,
        return_graph=return_graph,
    )


def validate_state_packet(state_packet: Mapping[str, Any]) -> None:
    required_keys = {
        "relevant_session_ids",
        "evidence_snippets",
        "state_facets",
        "rejected_claims",
        "enough_evidence",
    }
    missing = required_keys - set(state_packet)
    if missing:
        raise ValueError(f"state_packet missing keys: {sorted(missing)}")
    if not isinstance(state_packet["relevant_session_ids"], list):
        raise TypeError("relevant_session_ids must be a list")
    if not isinstance(state_packet["evidence_snippets"], list):
        raise TypeError("evidence_snippets must be a list")
    if not isinstance(state_packet["state_facets"], list):
        raise TypeError("state_facets must be a list")
    if not isinstance(state_packet["rejected_claims"], list):
        raise TypeError("rejected_claims must be a list")
    if not isinstance(state_packet["enough_evidence"], bool):
        raise TypeError("enough_evidence must be a bool")

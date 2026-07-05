from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from pipeline.external.groupmembench.graph_store import GraphArtifact, safe_path_part
from pipeline.external.groupmembench.loader import GroupMessage, ScopeNode, build_scope_inventory


def domain_graph_artifact_dir(base_dir, domain: str):
    return base_dir / safe_path_part(domain)


def is_domain_graph_artifact(artifact: GraphArtifact) -> bool:
    return str(artifact.manifest.get("build_unit") or "") == "domain_corpus"


def event_node_to_message(node: Dict[str, object], fallback_domain: str) -> GroupMessage:
    metadata = node.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    domain = str(metadata.get("domain") or fallback_domain)
    event_id = str(node.get("event_id") or metadata.get("msg_node") or "")
    return GroupMessage(
        domain=domain,
        channel=str(metadata.get("channel") or ""),
        msg_node=event_id,
        content=str(node.get("content") or ""),
        author=str(metadata.get("author") or node.get("source_id") or ""),
        role=str(metadata.get("role") or ""),
        timestamp=str(node.get("occurred_at") or node.get("updated_at") or ""),
        reply_to=str(metadata.get("reply_to")) if metadata.get("reply_to") not in {None, "", "null"} else None,
        phase_name=str(metadata.get("phase_name") or ""),
        topic=str(metadata.get("topic") or ""),
        message_type=str(metadata.get("message_type") or ""),
        path_type=str(metadata.get("path_type") or ""),
    )


def messages_from_graph_artifact(artifact: GraphArtifact) -> List[GroupMessage]:
    domain = str(artifact.manifest.get("domain") or "")
    messages = [
        event_node_to_message(node, domain)
        for node in artifact.nodes
        if node.get("node_type") == "Episode/Event" and node.get("event_id")
    ]
    messages.sort(key=lambda item: (item.channel, item.timestamp, item.event_id))
    return messages


def scope_node_from_graph(node: Dict[str, object], fallback_domain: str) -> Optional[ScopeNode]:
    scope_id = str(node.get("scope_id") or "")
    if not scope_id:
        return None
    return ScopeNode(
        scope_id=scope_id,
        domain=str(node.get("domain") or fallback_domain),
        channel=str(node.get("channel") or ""),
        phase_name=str(node.get("phase_name") or ""),
        topic=str(node.get("topic") or ""),
        scope_type=str(node.get("type") or "project_phase_topic"),
        source_anchor=str(node.get("source_anchor")) if node.get("source_anchor") not in {None, "", "null"} else None,
        state_target=str(node.get("state_target")) if node.get("state_target") not in {None, "", "null"} else None,
        state_target_terms=tuple(str(term) for term in node.get("state_target_terms", []) if term),
        base_scope_id=str(node.get("base_scope_id")) if node.get("base_scope_id") not in {None, "", "null"} else None,
        reply_thread=str(node.get("reply_thread")) if node.get("reply_thread") not in {None, "", "null"} else None,
        event_count=int(node.get("event_count") or 0),
    )


def scopes_from_graph_artifact(artifact: GraphArtifact, messages: Optional[Sequence[GroupMessage]] = None) -> List[ScopeNode]:
    domain = str(artifact.manifest.get("domain") or "")
    scopes: List[ScopeNode] = []
    seen = set()
    for node in artifact.nodes:
        if node.get("node_type") != "Entity/Scope" or node.get("role") != "scope":
            continue
        scope = scope_node_from_graph(node, domain)
        if scope is None or scope.scope_id in seen:
            continue
        seen.add(scope.scope_id)
        scopes.append(scope)
    if not scopes and messages is not None:
        scopes = build_scope_inventory(messages)
    scopes.sort(key=lambda item: (item.domain, item.channel, item.phase_name, item.topic, item.scope_id))
    return scopes


def claims_from_graph_artifact(
    artifact: GraphArtifact,
    event_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, object]]:
    allowed = set(event_ids or [])
    claims = []
    for node in artifact.nodes:
        if node.get("node_type") != "Claim" or not node.get("claim_id"):
            continue
        event_id = str(node.get("event_id") or "")
        if allowed and event_id not in allowed:
            continue
        claims.append(dict(node))
    claims.sort(key=lambda item: (str(item.get("event_id") or ""), str(item.get("claim_id") or "")))
    return claims

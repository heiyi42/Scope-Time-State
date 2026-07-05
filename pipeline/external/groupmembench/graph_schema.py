from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence

from pipeline.external.groupmembench.loader import GroupMessage, ScopeNode


NODE_TYPES = ("Episode/Event", "Claim", "StateFacet", "Entity/Scope", "Time")
EDGE_TYPES = (
    "MENTIONS",
    "IN_SCOPE",
    "ASSERTS",
    "CORRECTS",
    "SUPERSEDES",
    "CONFLICTS_WITH",
    "SUPPORTS",
    "CURRENT_AFTER",
    "CURRENT_STATE_OF",
)

EDGE_ALIASES: Mapping[str, str] = {
    "event_mentions_entity": "MENTIONS",
    "event_in_scope": "IN_SCOPE",
    "claim_supported_by_event": "ASSERTS",
    "event_asserts_claim": "ASSERTS",
    "claim_corrects_claim": "CORRECTS",
    "claim_supersedes_claim": "SUPERSEDES",
    "claim_conflicts_with_claim": "CONFLICTS_WITH",
    "facet_supported_by_claim": "SUPPORTS",
    "claim_supports_facet": "SUPPORTS",
    "facet_current_after_time": "CURRENT_AFTER",
    "facet_current_state_of_scope": "CURRENT_STATE_OF",
    "statefacet_current_state_of_scope": "CURRENT_STATE_OF",
}

EDGE_ENDPOINT_TYPES: Mapping[str, tuple[str, str]] = {
    "MENTIONS": ("Episode/Event", "Entity/Scope"),
    "IN_SCOPE": ("Episode/Event", "Entity/Scope"),
    "ASSERTS": ("Episode/Event", "Claim"),
    "CORRECTS": ("Claim", "Claim"),
    "SUPERSEDES": ("Claim", "Claim"),
    "CONFLICTS_WITH": ("Claim", "Claim"),
    "SUPPORTS": ("Claim", "StateFacet"),
    "CURRENT_AFTER": ("StateFacet", "Time"),
    "CURRENT_STATE_OF": ("StateFacet", "Entity/Scope"),
}


def canonical_edge_type(edge_type: object) -> str:
    value = str(edge_type or "").strip()
    canonical = EDGE_ALIASES.get(value.lower(), value.upper())
    if canonical not in EDGE_TYPES:
        known = ", ".join(EDGE_TYPES)
        raise ValueError(f"unsupported graph edge type: {value or '<missing>'}; expected one of: {known}")
    return canonical


def validate_edge_type(edge_type: object) -> str:
    return canonical_edge_type(edge_type)


def entity_id(kind: str, value: str) -> str:
    cleaned = " ".join(str(value).split()) or "unknown"
    return f"entity::{kind}::{cleaned}"


def time_id(timestamp: str) -> str:
    return f"time::{timestamp or 'unknown'}"


def time_node(timestamp: str, time_role: str = "message_timestamp") -> Dict[str, object]:
    return {"node_type": "Time", "time_id": time_id(timestamp), "value": timestamp, "time_role": time_role}


def event_node(message: GroupMessage) -> Dict[str, object]:
    payload = message.visible_event()
    payload["node_type"] = "Episode/Event"
    return payload


def scope_node(scope: ScopeNode) -> Dict[str, object]:
    payload = scope.as_dict()
    payload["node_type"] = "Entity/Scope"
    payload["role"] = "scope"
    return payload


def mentioned_entities(message: GroupMessage) -> List[Dict[str, object]]:
    raw_entities = [
        ("author", message.author),
        ("role", message.role),
        ("channel", message.channel),
        ("phase", message.phase_name),
        ("topic", message.topic),
    ]
    entities: List[Dict[str, object]] = []
    seen = set()
    for kind, value in raw_entities:
        if not value:
            continue
        node_id = entity_id(kind, value)
        if node_id in seen:
            continue
        seen.add(node_id)
        entities.append({"node_type": "Entity/Scope", "role": "entity", "entity_id": node_id, "kind": kind, "value": value})
    return entities


def time_nodes(messages: Iterable[GroupMessage]) -> List[Dict[str, object]]:
    seen = set()
    nodes: List[Dict[str, object]] = []
    for message in messages:
        node_id = time_id(message.timestamp)
        if node_id in seen:
            continue
        seen.add(node_id)
        nodes.append(time_node(message.timestamp))
    return nodes


def build_event_scope_graph(scope: ScopeNode, messages: Sequence[GroupMessage]) -> Dict[str, object]:
    entity_nodes: Dict[str, Dict[str, object]] = {}
    edges: List[Dict[str, object]] = []
    for message in messages:
        edges.append(
            {
                "type": "IN_SCOPE",
                "from": message.event_id,
                "to": scope.scope_id,
                "reason": "message metadata matches the routed Entity/Scope node",
            }
        )
        for entity in mentioned_entities(message):
            entity_nodes[str(entity["entity_id"])] = entity
            edges.append(
                {
                    "type": "MENTIONS",
                    "from": message.event_id,
                    "to": entity["entity_id"],
                    "reason": "visible message metadata or text-level participant/entity mention",
                }
            )
    return {
        "schema": {
            "node_types": list(NODE_TYPES),
            "edge_types": list(EDGE_TYPES),
            "edge_aliases": dict(EDGE_ALIASES),
            "edge_endpoint_types": {edge: list(types) for edge, types in EDGE_ENDPOINT_TYPES.items()},
            "source": "Design/Graph/*.png",
        },
        "nodes": {
            "entity_scope": scope_node(scope),
            "episode_events": [event_node(message) for message in messages],
            "mentioned_entity_scopes": list(entity_nodes.values()),
            "times": time_nodes(messages),
            "claims": [],
            "state_facets": [],
        },
        "edges": edges,
    }

"""Benchmark-neutral STS v2 graph schema."""

from __future__ import annotations

from typing import Mapping, Tuple


SCHEMA_VERSION = "scope-time-state-graph-v2-state-merge"
NODE_TYPES = ("Episode/Event", "Claim", "StateFacet", "Entity/Scope", "Time")
EDGE_ENDPOINT_TYPES: Mapping[str, Tuple[str, str]] = {
    "MENTIONS": ("Episode/Event", "Entity/Scope"),
    "IN_SCOPE": ("Episode/Event", "Entity/Scope"),
    "ASSERTS": ("Episode/Event", "Claim"),
    "OCCURRED_AT": ("Episode/Event", "Time"),
    "HAS_TIME": ("Claim", "Time"),
    "CORRECTS": ("Claim", "Claim"),
    "SUPERSEDES": ("Claim", "Claim"),
    "CONFLICTS_WITH": ("Claim", "Claim"),
    "SUPPORTS": ("Claim", "StateFacet"),
    "CURRENT_AFTER": ("StateFacet", "Time"),
    "CURRENT_STATE_OF": ("StateFacet", "Entity/Scope"),
}
EDGE_TYPES = tuple(EDGE_ENDPOINT_TYPES)

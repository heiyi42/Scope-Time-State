"""
STS: STSGraph-based Memory System for Long-term Conversational QA
"""

from sts.graph.types import Event, Claim, Scope, State, RawDataType
from sts.graph.schema import (
    STSGraph,
    ClaimNode,
    EventNode,
    ScopeNode,
    EventClaimRelation,
    ScopeEventRelation,
    ClaimRole,
    EventRole,
)

__version__ = "0.1.0"
__all__ = [
    # Types
    "Event",
    "Claim",
    "Scope",
    "State",
    "RawDataType",
    # Structure
    "STSGraph",
    "ClaimNode",
    "EventNode",
    "ScopeNode",
    "EventClaimRelation",
    "ScopeEventRelation",
    "ClaimRole",
    "EventRole",
]

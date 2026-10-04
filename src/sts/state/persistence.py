from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def attach_states(
    graph: Mapping[str, Any],
    build_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach STS States and Claim membership to a QA-ready graph copy."""
    attached = deepcopy(dict(graph))
    states = {}
    memberships = []
    temporal_relations = []
    assignments = dict(build_payload.get("claim_state_assignments", {}))

    for scope_result in build_payload.get("scope_results", []):
        for state in scope_result.get("states", []):
            state_data = deepcopy(state)
            state_id = state_data.pop("state_id")
            state_data["id"] = state_id
            states[state_id] = state_data
        memberships.extend(
            deepcopy(scope_result.get("state_memberships", []))
        )
        temporal_relations.extend(
            deepcopy(scope_result.get("temporal_relations", []))
        )

    claims = attached.get("claims", {})
    if set(assignments) != set(claims):
        missing = sorted(set(claims) - set(assignments))
        extra = sorted(set(assignments) - set(claims))
        raise ValueError(
            "Claim-State assignment coverage mismatch: "
            f"missing={missing[:5]}, extra={extra[:5]}"
        )
    if any(state_id is None for state_id in assignments.values()):
        raise ValueError("QA graph cannot contain unassigned Claims")

    for claim_id, state_id in assignments.items():
        if state_id not in states:
            raise ValueError(
                f"Claim {claim_id!r} references unknown State {state_id!r}"
            )
        claims[claim_id]["state_id"] = state_id

    attached["states"] = states
    attached["state_memberships"] = memberships
    attached["temporal_relations"] = temporal_relations
    attached["state_build"] = {
        "schema_version": build_payload.get("schema_version"),
        "embedding_model": build_payload.get("embedding_model"),
        "config": deepcopy(build_payload.get("config", {})),
        "summary": deepcopy(build_payload.get("summary", {})),
    }
    return attached

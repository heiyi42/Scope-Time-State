"""Extract chronological State summaries from already-threaded Claims."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Mapping

from sts.prompts.state_prompt import STATE_CHRONOLOGICAL_SUMMARY_PROMPT
from sts.graph.types import Claim


class StateExtractor:
    """Write State summaries without changing STS State membership or order."""

    def __init__(self, llm_provider, max_concurrency: int = 8):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.llm_provider = llm_provider
        self.max_concurrency = max_concurrency

    async def extract(
        self,
        state_payload: Mapping[str, Any],
        claims_by_id: Mapping[str, Claim],
    ) -> dict[str, Any]:
        """Return a copy whose States have ordered-Claim summaries."""
        extracted = deepcopy(dict(state_payload))
        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = []

        for scope_result in extracted.get("scope_results", []):
            for state in scope_result.get("states", []):
                tasks.append(
                    self._extract_one(
                        state,
                        claims_by_id,
                        semaphore,
                    )
                )

        await asyncio.gather(*tasks)
        extracted["summary_generation"] = {
            "method": "temporal_group_summary_v1",
            "model": getattr(
                getattr(self.llm_provider, "provider", None),
                "model",
                None,
            ),
            "state_count": len(tasks),
        }
        return extracted

    async def _extract_one(
        self,
        state: dict[str, Any],
        claims_by_id: Mapping[str, Claim],
        semaphore: asyncio.Semaphore,
    ) -> None:
        claim_ids = list(state.get("claim_ids", []))
        claims = []
        for claim_id in claim_ids:
            claim = claims_by_id.get(claim_id)
            if claim is None:
                raise ValueError(
                    f"State {state.get('state_id')} references unknown "
                    f"Claim {claim_id}"
                )
            claims.append(claim)

        if not claims:
            raise ValueError(f"State {state.get('state_id')} has no Claims")

        # A one-Claim State is already a complete atomic statement.
        if len(claims) == 1:
            state["summary"] = claims[0].content
            state["summary_method"] = "single_claim_identity"
            return

        time_groups = list(state.get("time_groups", []))
        grouped_claim_ids = [
            claim_id
            for group in time_groups
            for claim_id in group.get("claim_ids", [])
        ]
        if set(grouped_claim_ids) != set(claim_ids):
            raise ValueError(
                f"State {state.get('state_id')} time-group membership "
                "does not match claim_ids"
            )
        claim_by_id = {claim.claim_id: claim for claim in claims}
        group_blocks = []
        for group in sorted(
            time_groups,
            key=lambda item: (
                item.get("rank", 0),
                item.get("start_time", ""),
                item.get("group_id", ""),
            ),
        ):
            start = group.get("start_time") or "unknown"
            end = group.get("end_time") or start
            precision = group.get("precision") or "unknown"
            lines = [
                (
                    f"[Time group {group.get('rank', 0)}: "
                    f"{start} to {end}; precision={precision}; "
                    "internal order unspecified]"
                )
            ]
            lines.extend(
                f"- {claim_by_id[claim_id].content}"
                for claim_id in group.get("claim_ids", [])
            )
            group_blocks.append("\n".join(lines))
        grouped_claims = "\n\n".join(group_blocks)
        prompt = STATE_CHRONOLOGICAL_SUMMARY_PROMPT.format(
            grouped_claims=grouped_claims
        )
        async with semaphore:
            raw = await self.llm_provider.generate(
                prompt,
                temperature=0,
                response_format={"type": "json_object"},
            )

        try:
            response = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid State summary JSON for {state.get('state_id')}"
            ) from error

        summary = response.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(
                f"Empty State summary for {state.get('state_id')}"
            )
        if "\n" in summary or "→" in summary or "->" in summary:
            raise ValueError(
                f"State {state.get('state_id')} summary must be one "
                "prose sentence, not a list or arrow chain"
            )

        state["summary"] = " ".join(summary.split())
        state["summary_method"] = "llm_temporal_group_summary_v1"

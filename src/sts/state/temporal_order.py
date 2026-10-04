from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

import networkx as nx

from sts.state.models import ClaimThreadFeature
from sts.utils.datetime_utils import to_iso_format


@dataclass(frozen=True)
class StateTimeGroup:
    group_id: str
    claim_ids: tuple[str, ...]
    start_time: datetime
    end_time: datetime
    precision: str
    rank: int

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "claim_ids": list(self.claim_ids),
            "start_time": to_iso_format(self.start_time),
            "end_time": to_iso_format(self.end_time),
            "precision": self.precision,
            "rank": self.rank,
            "internal_order": "unspecified",
        }


@dataclass(frozen=True)
class TimeGroupRelation:
    source_group_id: str
    target_group_id: str


class TemporalOrderBuilder:
    """Build a partial temporal order without inventing within-time order."""

    def build(
        self,
        state_id: str,
        claim_ids: Sequence[str],
        features: Mapping[str, ClaimThreadFeature],
    ) -> tuple[list[StateTimeGroup], list[TimeGroupRelation]]:
        grouped: dict[
            tuple[datetime, datetime, str], list[str]
        ] = {}
        for claim_id in claim_ids:
            feature = features[claim_id]
            key = (
                feature.time_start,
                feature.time_end,
                feature.time_precision,
            )
            grouped.setdefault(key, []).append(claim_id)

        records = []
        for (start, end, precision), members in grouped.items():
            stable_members = tuple(sorted(members))
            group_id = self._group_id(state_id, stable_members)
            records.append(
                (group_id, stable_members, start, end, precision)
            )
        records.sort(
            key=lambda item: (item[2], item[3], item[0])
        )

        precedence = nx.DiGraph()
        precedence.add_nodes_from(record[0] for record in records)
        for left_index, left in enumerate(records):
            for right in records[left_index + 1 :]:
                if left[3] < right[2]:
                    precedence.add_edge(left[0], right[0])

        reduced = (
            nx.transitive_reduction(precedence)
            if precedence.number_of_edges()
            else precedence
        )
        ranks: dict[str, int] = {}
        for group_id in nx.topological_sort(precedence):
            predecessors = list(precedence.predecessors(group_id))
            ranks[group_id] = (
                max(ranks[parent] for parent in predecessors) + 1
                if predecessors
                else 0
            )

        groups = [
            StateTimeGroup(
                group_id=group_id,
                claim_ids=members,
                start_time=start,
                end_time=end,
                precision=precision,
                rank=ranks[group_id],
            )
            for group_id, members, start, end, precision in records
        ]
        groups.sort(
            key=lambda group: (
                group.rank,
                group.start_time,
                group.end_time,
                group.group_id,
            )
        )
        relations = [
            TimeGroupRelation(source, target)
            for source, target in sorted(reduced.edges())
        ]
        return groups, relations

    @staticmethod
    def _group_id(state_id: str, claim_ids: tuple[str, ...]) -> str:
        key = "\0".join([state_id, *claim_ids])
        return f"time_group_{uuid.uuid5(uuid.NAMESPACE_URL, key)}"

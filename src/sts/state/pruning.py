from __future__ import annotations

import networkx as nx
import numpy as np


class ClaimGraphPruner:
    """Modern CPU implementation of STS pruning."""

    def __init__(
        self,
        prune_percentile: float = 70.0,
        outdegree_limit: int = 1,
    ):
        self.prune_percentile = prune_percentile
        self.outdegree_limit = outdegree_limit

    def prune(self, graph: nx.DiGraph) -> nx.DiGraph:
        pruned = graph.copy()

        for node in list(pruned.nodes):
            incoming = list(pruned.in_edges(node, data=True))
            if len(incoming) <= 1:
                continue
            incoming.sort(
                key=lambda edge: (
                    float(edge[2]["distance"]),
                    str(edge[0]),
                )
            )
            pruned.remove_edges_from(
                (source, target) for source, target, _ in incoming[1:]
            )

        for component in list(nx.weakly_connected_components(pruned)):
            component_edges = list(pruned.subgraph(component).edges(data=True))
            if not component_edges:
                continue
            cutoff = float(
                np.percentile(
                    [float(data["distance"]) for _, _, data in component_edges],
                    self.prune_percentile,
                )
            )
            to_remove = []
            for source, target, data in component_edges:
                if (
                    float(data["distance"]) > cutoff
                    and pruned.out_degree(source) > self.outdegree_limit
                ):
                    to_remove.append((source, target))
            pruned.remove_edges_from(to_remove)
        return pruned

    def partition(self, graph: nx.DiGraph) -> list[set[str]]:
        pruned = self.prune(graph)
        communities = [
            set(component)
            for component in nx.weakly_connected_components(pruned)
        ]
        return sorted(communities, key=lambda group: sorted(group))

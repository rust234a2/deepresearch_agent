from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult, ultimate_controllers
from deepresearch_agent.ownership_graph import OwnershipGraph


class NeighborEdge(BaseModel):
    node_id: str
    name: str
    node_type: str
    edge_type: Literal["shareholding", "investment"]
    direction: Literal["in", "out"]
    holding_pct: str | None = None


class OwnershipGraphBackend(Protocol):
    def has_node(self, node_id: str) -> bool: ...
    def display_name(self, node_id: str) -> str: ...
    def ultimate_controllers(self, node_id: str, max_depth: int = 5) -> list[ControllerResult]: ...
    def direct_neighbors(self, node_id: str) -> list[NeighborEdge]: ...
    def company_industry(self, node_id: str) -> str | None: ...


class InMemoryOwnershipBackend:
    def __init__(self, graph: OwnershipGraph) -> None:
        self._graph = graph

    def has_node(self, node_id: str) -> bool:
        return node_id in self._graph.nodes

    def display_name(self, node_id: str) -> str:
        node = self._graph.nodes.get(node_id)
        return node.display_name if node is not None else node_id

    def _node_type(self, node_id: str) -> str:
        node = self._graph.nodes.get(node_id)
        return node.node_type if node is not None else ""

    def ultimate_controllers(self, node_id: str, max_depth: int = 5) -> list[ControllerResult]:
        return ultimate_controllers(self._graph, node_id, max_depth=max_depth)

    def direct_neighbors(self, node_id: str) -> list[NeighborEdge]:
        neighbors: list[NeighborEdge] = []
        for edge in self._graph.successors(node_id):
            neighbors.append(
                NeighborEdge(
                    node_id=edge.target_node_id,
                    name=self.display_name(edge.target_node_id),
                    node_type=self._node_type(edge.target_node_id),
                    edge_type=edge.edge_type,
                    direction="out",
                    holding_pct=edge.holding_pct,
                )
            )
        for edge in self._graph.predecessors(node_id):
            neighbors.append(
                NeighborEdge(
                    node_id=edge.source_node_id,
                    name=self.display_name(edge.source_node_id),
                    node_type=self._node_type(edge.source_node_id),
                    edge_type=edge.edge_type,
                    direction="in",
                    holding_pct=edge.holding_pct,
                )
            )
        neighbors.sort(key=lambda n: (n.direction, n.node_id))
        return neighbors

    def company_industry(self, node_id: str) -> str | None:
        return None  # 内存图无行业层（N3 只灌 Neo4j）；优雅降级，不误报集中度

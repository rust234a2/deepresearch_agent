from __future__ import annotations

from dataclasses import dataclass, field

from deepresearch_agent.company_models import GraphEdge, GraphNode
from deepresearch_agent.company_repository import CompanyRepository


@dataclass
class OwnershipGraph:
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    out_edges: dict[str, list[GraphEdge]] = field(default_factory=dict)
    in_edges: dict[str, list[GraphEdge]] = field(default_factory=dict)

    def get_node(self, node_id: str) -> GraphNode | None:
        return self.nodes.get(node_id)

    def successors(self, node_id: str) -> list[GraphEdge]:
        return self.out_edges.get(node_id, [])

    def predecessors(self, node_id: str) -> list[GraphEdge]:
        return self.in_edges.get(node_id, [])


def load_ownership_graph(repository: CompanyRepository) -> OwnershipGraph:
    nodes = {node.node_id: node for node in repository.iter_graph_nodes()}
    edges = repository.iter_graph_edges()
    out_edges: dict[str, list[GraphEdge]] = {}
    in_edges: dict[str, list[GraphEdge]] = {}
    for edge in edges:
        out_edges.setdefault(edge.source_node_id, []).append(edge)
        in_edges.setdefault(edge.target_node_id, []).append(edge)
    return OwnershipGraph(nodes=nodes, edges=edges, out_edges=out_edges, in_edges=in_edges)

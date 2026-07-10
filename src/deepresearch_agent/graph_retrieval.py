from __future__ import annotations

from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult, ultimate_controllers
from deepresearch_agent.ownership_backend import NeighborEdge
from deepresearch_agent.ownership_graph import OwnershipGraph


class SeedContext(BaseModel):
    code: str
    name: str
    score: float
    controllers: list[ControllerResult]
    neighbors: list[NeighborEdge]


class SharedController(BaseModel):
    node_id: str
    name: str
    controlled_seeds: list[str]
    via_person: bool


class HybridContext(BaseModel):
    query: str | None = None
    seeds: list[SeedContext]
    shared_controllers: list[SharedController]


def _name(graph: OwnershipGraph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    return node.display_name if node is not None else node_id


def _type(graph: OwnershipGraph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    return node.node_type if node is not None else ""


def _direct_neighbors(graph: OwnershipGraph, code: str) -> list[NeighborEdge]:
    neighbors: list[NeighborEdge] = []
    for edge in graph.successors(code):
        neighbors.append(
            NeighborEdge(
                node_id=edge.target_node_id,
                name=_name(graph, edge.target_node_id),
                node_type=_type(graph, edge.target_node_id),
                edge_type=edge.edge_type,
                direction="out",
                holding_pct=edge.holding_pct,
            )
        )
    for edge in graph.predecessors(code):
        neighbors.append(
            NeighborEdge(
                node_id=edge.source_node_id,
                name=_name(graph, edge.source_node_id),
                node_type=_type(graph, edge.source_node_id),
                edge_type=edge.edge_type,
                direction="in",
                holding_pct=edge.holding_pct,
            )
        )
    neighbors.sort(key=lambda n: (n.direction, n.node_id))
    return neighbors


def assemble_subgraph_context(
    graph: OwnershipGraph,
    seed_codes: list[str],
    max_depth: int = 5,
    query: str | None = None,
    scores: dict[str, float] | None = None,
) -> HybridContext:
    scores = scores or {}
    seeds: list[SeedContext] = []
    controlled: dict[str, set[str]] = {}
    meta: dict[str, tuple[str, bool]] = {}
    for code in seed_codes:
        if code not in graph.nodes:
            continue
        controllers = ultimate_controllers(graph, code, max_depth=max_depth)
        seeds.append(
            SeedContext(
                code=code,
                name=_name(graph, code),
                score=scores.get(code, 0.0),
                controllers=controllers,
                neighbors=_direct_neighbors(graph, code),
            )
        )
        for controller in controllers:
            controlled.setdefault(controller.node_id, set()).add(code)
            name, via = meta.get(controller.node_id, (controller.display_name, False))
            meta[controller.node_id] = (name, via or controller.via_person)
    shared = [
        SharedController(
            node_id=nid,
            name=meta[nid][0],
            controlled_seeds=sorted(codes),
            via_person=meta[nid][1],
        )
        for nid, codes in controlled.items()
        if len(codes) >= 2
    ]
    shared.sort(key=lambda s: (-len(s.controlled_seeds), s.node_id))
    seeds.sort(key=lambda s: (-s.score, s.code))
    return HybridContext(query=query, seeds=seeds, shared_controllers=shared)


def hybrid_search(
    query: str,
    scope_retriever,
    graph: OwnershipGraph,
    k: int = 10,
    max_depth: int = 5,
) -> HybridContext:
    hits = scope_retriever.search(query, k)
    scores: dict[str, float] = {}
    for hit in hits:
        code = hit.unified_social_credit_code
        scores[code] = max(scores.get(code, 0.0), hit.score)
    seed_codes = sorted(scores, key=lambda code: (-scores[code], code))
    return assemble_subgraph_context(
        graph, seed_codes, max_depth=max_depth, query=query, scores=scores
    )

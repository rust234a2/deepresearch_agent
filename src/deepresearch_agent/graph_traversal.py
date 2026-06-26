from __future__ import annotations

from collections import deque

from pydantic import BaseModel

from deepresearch_agent.company_models import GraphEdge
from deepresearch_agent.ownership_graph import OwnershipGraph


DEFAULT_BLOCK_EXPAND_TYPES = ("fund",)


class EgoResult(BaseModel):
    center: str
    node_ids: list[str]
    edges: list[GraphEdge]


class ControllerResult(BaseModel):
    node_id: str
    display_name: str
    depth: int
    via_person: bool


class CommonController(BaseModel):
    node_id: str
    display_name: str
    depth_from_a: int
    depth_from_b: int
    via_person: bool


class GraphPath(BaseModel):
    node_ids: list[str]
    length: int
    via_person: bool


def _node_type(graph: OwnershipGraph, node_id: str) -> str | None:
    node = graph.nodes.get(node_id)
    return node.node_type if node is not None else None


def _is_person(graph: OwnershipGraph, node_id: str) -> bool:
    node = graph.nodes.get(node_id)
    return bool(node is not None and node.is_person)


def _display(graph: OwnershipGraph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    return node.display_name if node is not None else node_id


def _upward_reachable(
    graph: OwnershipGraph,
    node_id: str,
    max_depth: int,
    block_expand_types: tuple[str, ...],
) -> dict[str, tuple[int, bool]]:
    """向上（入边/股东方向）可达的非 fund 节点 -> (最短深度, 路径是否经过自然人)。"""
    reached: dict[str, tuple[int, bool]] = {}
    seen = {node_id}
    queue: deque[tuple[str, int, bool]] = deque([(node_id, 0, False)])
    while queue:
        current, depth, via_person = queue.popleft()
        if depth >= max_depth:
            continue
        if current != node_id and _node_type(graph, current) in block_expand_types:
            continue
        for edge in graph.predecessors(current):
            parent = edge.source_node_id
            if parent in seen or _node_type(graph, parent) in block_expand_types:
                continue
            seen.add(parent)
            parent_via = via_person or _is_person(graph, parent)
            reached[parent] = (depth + 1, parent_via)
            queue.append((parent, depth + 1, parent_via))
    return reached


def ego_graph(
    graph: OwnershipGraph,
    node_id: str,
    radius: int = 2,
    block_expand_types: tuple[str, ...] = DEFAULT_BLOCK_EXPAND_TYPES,
) -> EgoResult:
    visited = {node_id}
    frontier = [node_id]
    for _ in range(radius):
        next_frontier: list[str] = []
        for current in frontier:
            if current != node_id and _node_type(graph, current) in block_expand_types:
                continue
            neighbors = {edge.target_node_id for edge in graph.successors(current)}
            neighbors |= {edge.source_node_id for edge in graph.predecessors(current)}
            for neighbor in sorted(neighbors):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
    edges = [
        edge
        for edge in graph.edges
        if edge.source_node_id in visited and edge.target_node_id in visited
    ]
    return EgoResult(center=node_id, node_ids=sorted(visited), edges=edges)


def ultimate_controllers(
    graph: OwnershipGraph,
    node_id: str,
    max_depth: int = 5,
    block_expand_types: tuple[str, ...] = DEFAULT_BLOCK_EXPAND_TYPES,
) -> list[ControllerResult]:
    reached = _upward_reachable(graph, node_id, max_depth, block_expand_types)
    results: list[ControllerResult] = []
    for nid, (depth, via_person) in reached.items():
        has_parent = any(
            _node_type(graph, edge.source_node_id) not in block_expand_types
            for edge in graph.predecessors(nid)
        )
        if (not has_parent) or _is_person(graph, nid):
            results.append(
                ControllerResult(
                    node_id=nid,
                    display_name=_display(graph, nid),
                    depth=depth,
                    via_person=via_person,
                )
            )
    results.sort(key=lambda c: (c.depth, c.node_id))
    return results

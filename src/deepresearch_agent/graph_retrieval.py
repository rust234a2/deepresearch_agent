from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult
from deepresearch_agent.ownership_backend import NeighborEdge, OwnershipGraphBackend


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
    concentrated_industries: list[str] = []


class HybridContext(BaseModel):
    query: str | None = None
    seeds: list[SeedContext]
    shared_controllers: list[SharedController]


def assemble_subgraph_context(
    backend: OwnershipGraphBackend,
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
        if not backend.has_node(code):
            continue
        controllers = backend.ultimate_controllers(code, max_depth=max_depth)
        seeds.append(
            SeedContext(
                code=code,
                name=backend.display_name(code),
                score=scores.get(code, 0.0),
                controllers=controllers,
                neighbors=backend.direct_neighbors(code),
            )
        )
        for controller in controllers:
            controlled.setdefault(controller.node_id, set()).add(code)
            name, via = meta.get(controller.node_id, (controller.display_name, False))
            meta[controller.node_id] = (name, via or controller.via_person)
    shared: list[SharedController] = []
    for nid, codes in controlled.items():
        if len(codes) < 2:
            continue
        by_industry: dict[str, int] = {}
        for code in codes:
            industry = backend.company_industry(code)
            if industry:
                by_industry[industry] = by_industry.get(industry, 0) + 1
        concentrated = sorted(name for name, n in by_industry.items() if n >= 2)
        shared.append(
            SharedController(
                node_id=nid,
                name=meta[nid][0],
                controlled_seeds=sorted(codes),
                via_person=meta[nid][1],
                concentrated_industries=concentrated,
            )
        )
    shared.sort(key=lambda s: (-len(s.controlled_seeds), s.node_id))
    seeds.sort(key=lambda s: (-s.score, s.code))
    return HybridContext(query=query, seeds=seeds, shared_controllers=shared)


def hybrid_search(
    query: str,
    scope_retriever,
    backend: OwnershipGraphBackend,
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
        backend, seed_codes, max_depth=max_depth, query=query, scores=scores
    )


# ---------- 可视化子图投影（供网页图谱面板使用，纯函数、不额外查图） ----------

MAX_NEIGHBORS_PER_DIRECTION = 15

_KIND_PRIORITY = {"seed": 3, "controller": 2, "shareholder": 1, "investment": 0}


class SubgraphNode(BaseModel):
    id: str
    name: str
    kind: Literal["seed", "shareholder", "investment", "controller"]
    node_type: str = ""
    score: float = 0.0
    is_shared_controller: bool = False
    concentrated_industries: list[str] = []


class SubgraphEdge(BaseModel):
    source: str
    target: str
    kind: Literal["shareholding", "investment", "control_clue"]
    holding_pct: str | None = None
    via_person: bool = False


class GraphSubgraph(BaseModel):
    nodes: list[SubgraphNode]
    edges: list[SubgraphEdge]
    truncated: bool = False


def _pct_value(pct: str | None) -> float:
    if not pct:
        return -1.0
    match = re.search(r"\d+(?:\.\d+)?", pct)
    return float(match.group()) if match else -1.0


def project_subgraph(context: HybridContext) -> GraphSubgraph:
    nodes: dict[str, SubgraphNode] = {}
    edges: list[SubgraphEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    truncated = False

    def upsert(node: SubgraphNode) -> None:
        existing = nodes.get(node.id)
        if existing is None:
            nodes[node.id] = node
            return
        keep, other = (
            (node, existing)
            if _KIND_PRIORITY[node.kind] > _KIND_PRIORITY[existing.kind]
            else (existing, node)
        )
        keep.is_shared_controller = keep.is_shared_controller or other.is_shared_controller
        keep.concentrated_industries = keep.concentrated_industries or other.concentrated_industries
        keep.score = max(keep.score, other.score)
        keep.node_type = keep.node_type or other.node_type
        nodes[node.id] = keep

    def add_edge(edge: SubgraphEdge) -> None:
        key = (edge.source, edge.target, edge.kind)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append(edge)

    for seed in context.seeds:
        upsert(
            SubgraphNode(
                id=seed.code, name=seed.name, kind="seed", node_type="company", score=seed.score
            )
        )

    shared_meta = {item.node_id: item for item in context.shared_controllers}
    for seed in context.seeds:
        for direction, kind in (("in", "shareholder"), ("out", "investment")):
            picked = sorted(
                (n for n in seed.neighbors if n.direction == direction),
                key=lambda n: (-_pct_value(n.holding_pct), n.node_id),
            )
            if len(picked) > MAX_NEIGHBORS_PER_DIRECTION:
                truncated = True
                picked = picked[:MAX_NEIGHBORS_PER_DIRECTION]
            for neighbor in picked:
                upsert(
                    SubgraphNode(
                        id=neighbor.node_id,
                        name=neighbor.name,
                        kind=kind,  # type: ignore[arg-type]
                        node_type=neighbor.node_type,
                    )
                )
                if direction == "in":
                    add_edge(
                        SubgraphEdge(
                            source=neighbor.node_id,
                            target=seed.code,
                            kind=neighbor.edge_type,
                            holding_pct=neighbor.holding_pct,
                        )
                    )
                else:
                    add_edge(
                        SubgraphEdge(
                            source=seed.code,
                            target=neighbor.node_id,
                            kind=neighbor.edge_type,
                            holding_pct=neighbor.holding_pct,
                        )
                    )
        for controller in seed.controllers:
            shared = shared_meta.get(controller.node_id)
            upsert(
                SubgraphNode(
                    id=controller.node_id,
                    name=controller.display_name,
                    kind="controller",
                    node_type="person" if controller.node_id.startswith("person:") else "company",
                    is_shared_controller=shared is not None,
                    concentrated_industries=(
                        list(shared.concentrated_industries) if shared else []
                    ),
                )
            )
            add_edge(
                SubgraphEdge(
                    source=controller.node_id,
                    target=seed.code,
                    kind="control_clue",
                    via_person=controller.via_person,
                )
            )

    return GraphSubgraph(nodes=list(nodes.values()), edges=edges, truncated=truncated)

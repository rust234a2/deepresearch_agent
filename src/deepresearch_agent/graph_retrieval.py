from __future__ import annotations

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


# ---------- 问题聚焦子图投影（供网页图谱面板使用，纯函数、不额外查图） ----------
# 只回答提问本身：查询概念节点 → 命中的种子企业，加上种子间的实际关联证据
# （共享控制人）。单一控制人、直接股东、对外投资是噪声，不进入载荷。

QUERY_NODE_ID = "query"


class SubgraphNode(BaseModel):
    id: str
    name: str
    kind: Literal["query", "seed", "controller"]
    node_type: str = ""
    score: float = 0.0
    is_shared_controller: bool = False
    concentrated_industries: list[str] = []


class SubgraphEdge(BaseModel):
    source: str
    target: str
    kind: Literal["semantic_match", "control_clue"]
    via_person: bool = False


class GraphSubgraph(BaseModel):
    nodes: list[SubgraphNode]
    edges: list[SubgraphEdge]


def project_subgraph(context: HybridContext) -> GraphSubgraph:
    if not context.seeds:
        return GraphSubgraph(nodes=[], edges=[])

    nodes: list[SubgraphNode] = [
        SubgraphNode(id=QUERY_NODE_ID, name=context.query or "", kind="query")
    ]
    edges: list[SubgraphEdge] = []
    seed_codes: set[str] = set()
    for seed in context.seeds:
        seed_codes.add(seed.code)
        nodes.append(
            SubgraphNode(
                id=seed.code, name=seed.name, kind="seed", node_type="company", score=seed.score
            )
        )
        edges.append(SubgraphEdge(source=QUERY_NODE_ID, target=seed.code, kind="semantic_match"))

    for shared in context.shared_controllers:
        controlled = [code for code in shared.controlled_seeds if code in seed_codes]
        if not controlled:
            continue
        nodes.append(
            SubgraphNode(
                id=shared.node_id,
                name=shared.name,
                kind="controller",
                node_type="person" if shared.node_id.startswith("person:") else "company",
                is_shared_controller=True,
                concentrated_industries=list(shared.concentrated_industries),
            )
        )
        edges.extend(
            SubgraphEdge(
                source=shared.node_id,
                target=code,
                kind="control_clue",
                via_person=shared.via_person,
            )
            for code in controlled
        )

    return GraphSubgraph(nodes=nodes, edges=edges)

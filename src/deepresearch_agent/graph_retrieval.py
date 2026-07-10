from __future__ import annotations

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

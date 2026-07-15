from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.graph_retrieval import assemble_subgraph_context, hybrid_search
from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend
from deepresearch_agent.ownership_graph import load_ownership_graph

LINKS = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _graph(tmp_path: Path):
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        LINKS / "companies.csv",
        LINKS / "contacts.csv",
        database_path,
        shareholders_csv=LINKS / "shareholders.csv",
        investments_csv=LINKS / "investments.csv",
    )
    return load_ownership_graph(CompanyRepository(database_path))


def test_assemble_shared_controllers_across_seeds(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), [A_CODE, B_CODE, C_CODE])

    shared = {s.node_id: s for s in ctx.shared_controllers}
    # 共同控股集团 直接控股 甲、乙，并经 甲投资丙 间接控制 丙 → 控制全部三家
    assert "ext:共同控股集团有限公司" in shared
    assert set(shared["ext:共同控股集团有限公司"].controlled_seeds) == {A_CODE, B_CODE, C_CODE}
    assert shared["ext:共同控股集团有限公司"].via_person is False
    assert "person:张三" in shared
    assert set(shared["person:张三"].controlled_seeds) == {A_CODE, C_CODE}
    assert shared["person:张三"].via_person is True


def test_assemble_seed_context_controllers_and_neighbors(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), [A_CODE], scores={A_CODE: 0.9})

    seed = ctx.seeds[0]
    assert seed.code == A_CODE
    assert seed.score == 0.9
    controller_ids = {c.node_id for c in seed.controllers}
    assert "ext:共同控股集团有限公司" in controller_ids
    assert "person:张三" in controller_ids
    neighbor_ids = {n.node_id for n in seed.neighbors}
    assert C_CODE in neighbor_ids
    assert "ext:共同控股集团有限公司" in neighbor_ids
    invest = next(n for n in seed.neighbors if n.node_id == C_CODE)
    assert invest.direction == "out" and invest.edge_type == "investment"
    held_by = next(n for n in seed.neighbors if n.node_id == "ext:共同控股集团有限公司")
    assert held_by.direction == "in" and held_by.edge_type == "shareholding"


def test_assemble_skips_unknown_seed(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), ["no-such-code"])

    assert ctx.seeds == []
    assert ctx.shared_controllers == []


class _Hit:
    def __init__(self, code: str, score: float):
        self.unified_social_credit_code = code
        self.score = score


class _StubRetriever:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, k):
        return self._hits


def test_hybrid_search_uses_scope_seeds_sorted_by_score(tmp_path):
    graph = _graph(tmp_path)
    retriever = _StubRetriever([_Hit(B_CODE, 0.7), _Hit(A_CODE, 0.95), _Hit(A_CODE, 0.4)])

    ctx = hybrid_search("注塑成型", retriever, InMemoryOwnershipBackend(graph))

    assert ctx.query == "注塑成型"
    assert [s.code for s in ctx.seeds] == [A_CODE, B_CODE]
    assert ctx.seeds[0].score == 0.95
    shared_ids = {s.node_id for s in ctx.shared_controllers}
    assert "ext:共同控股集团有限公司" in shared_ids


class _IndustryBackend:
    """假后端：显式给定 industry 映射，验证集中度检测。"""

    def __init__(self, graph, industries):
        from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend

        self._mem = InMemoryOwnershipBackend(graph)
        self._industries = industries

    def has_node(self, node_id):
        return self._mem.has_node(node_id)

    def display_name(self, node_id):
        return self._mem.display_name(node_id)

    def ultimate_controllers(self, node_id, max_depth=5):
        return self._mem.ultimate_controllers(node_id, max_depth=max_depth)

    def direct_neighbors(self, node_id):
        return self._mem.direct_neighbors(node_id)

    def company_industry(self, node_id):
        return self._industries.get(node_id)


def test_shared_controller_flags_same_industry_concentration(tmp_path):
    graph = _graph(tmp_path)
    # 甲、丙 同行业"机床"，乙 不同 → 控制 {甲,丙} 的控制人应标记该行业
    backend = _IndustryBackend(graph, {A_CODE: "机床制造", C_CODE: "机床制造", B_CODE: "餐饮"})

    ctx = assemble_subgraph_context(backend, [A_CODE, B_CODE, C_CODE])

    shared = {s.node_id: s for s in ctx.shared_controllers}
    zhangsan = shared["person:张三"]  # 张三 控制 甲、丙（均"机床制造"）
    assert zhangsan.concentrated_industries == ["机床制造"]


def test_inmemory_backend_reports_no_industry_concentration(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), [A_CODE, B_CODE, C_CODE])

    assert all(s.concentrated_industries == [] for s in ctx.shared_controllers)


# ---------- project_subgraph：HybridContext → 问题聚焦子图（查询+种子+共享控制人） ----------

from deepresearch_agent.graph_retrieval import (  # noqa: E402
    HybridContext,
    SeedContext,
    SharedController,
    project_subgraph,
)
from deepresearch_agent.graph_traversal import ControllerResult  # noqa: E402
from deepresearch_agent.ownership_backend import NeighborEdge  # noqa: E402


def _neighbor(node_id, name, node_type, edge_type, direction, pct=None):
    return NeighborEdge(node_id=node_id, name=name, node_type=node_type,
                        edge_type=edge_type, direction=direction, holding_pct=pct)


def _controller(node_id, name, via_person=False):
    return ControllerResult(node_id=node_id, display_name=name, depth=1, via_person=via_person)


def _seed(code, name, score=0.0, controllers=(), neighbors=()):
    return SeedContext(code=code, name=name, score=score,
                       controllers=list(controllers), neighbors=list(neighbors))


def test_project_subgraph_query_hub_and_semantic_edges():
    ctx = HybridContext(query="注塑", seeds=[
        _seed("91A", "甲公司", score=0.9),
        _seed("91B", "乙公司", score=0.7),
    ], shared_controllers=[])

    sub = project_subgraph(ctx)

    hub = next(n for n in sub.nodes if n.kind == "query")
    assert hub.id == "query" and hub.name == "注塑"
    kinds = {n.id: n.kind for n in sub.nodes}
    assert kinds == {"query": "query", "91A": "seed", "91B": "seed"}
    seed_a = next(n for n in sub.nodes if n.id == "91A")
    assert seed_a.score == 0.9 and seed_a.node_type == "company"
    edges = {(e.source, e.target): e for e in sub.edges}
    assert edges[("query", "91A")].kind == "semantic_match"
    assert edges[("query", "91B")].kind == "semantic_match"
    assert len(sub.edges) == 2


def test_project_subgraph_keeps_only_shared_controllers():
    # 甲有独占控制人张三、直接股东基金X、对外投资丙——均不入图；共享控制人 集团 入图
    ctx = HybridContext(
        query="q",
        seeds=[
            _seed("91A", "甲公司", 0.9,
                  controllers=[_controller("person:张三", "张三", True),
                               _controller("ext:集团", "集团")],
                  neighbors=[
                      _neighbor("ext:基金X", "基金X", "company", "shareholding", "in", "60%"),
                      _neighbor("91C", "丙公司", "company", "investment", "out", "30%"),
                  ]),
            _seed("91B", "乙公司", 0.8, controllers=[_controller("ext:集团", "集团")]),
        ],
        shared_controllers=[SharedController(
            node_id="ext:集团", name="集团", controlled_seeds=["91A", "91B"],
            via_person=False, concentrated_industries=["机床制造"],
        )],
    )

    sub = project_subgraph(ctx)

    ids = {n.id for n in sub.nodes}
    assert ids == {"query", "91A", "91B", "ext:集团"}
    group = next(n for n in sub.nodes if n.id == "ext:集团")
    assert group.kind == "controller"
    assert group.is_shared_controller is True
    assert group.concentrated_industries == ["机床制造"]
    assert group.node_type == "company"
    clues = sorted((e.source, e.target) for e in sub.edges if e.kind == "control_clue")
    assert clues == [("ext:集团", "91A"), ("ext:集团", "91B")]


def test_project_subgraph_shared_controller_via_person_and_person_type():
    ctx = HybridContext(
        query="q",
        seeds=[_seed("91A", "甲公司", 0.9), _seed("91B", "乙公司", 0.8)],
        shared_controllers=[SharedController(
            node_id="person:张三", name="张三", controlled_seeds=["91A", "91B"],
            via_person=True, concentrated_industries=[],
        )],
    )

    sub = project_subgraph(ctx)

    zhang = next(n for n in sub.nodes if n.id == "person:张三")
    assert zhang.node_type == "person"
    assert zhang.concentrated_industries == []
    clues = [e for e in sub.edges if e.kind == "control_clue"]
    assert len(clues) == 2 and all(e.via_person for e in clues)


def test_project_subgraph_skips_controlled_codes_outside_seeds():
    # controlled_seeds 含种子集合外的代码 → 不为其造节点/边
    ctx = HybridContext(
        query="q",
        seeds=[_seed("91A", "甲公司", 0.9), _seed("91B", "乙公司", 0.8)],
        shared_controllers=[SharedController(
            node_id="ext:集团", name="集团", controlled_seeds=["91A", "91B", "91X"],
            via_person=False,
        )],
    )

    sub = project_subgraph(ctx)

    assert "91X" not in {n.id for n in sub.nodes}
    assert sorted(e.target for e in sub.edges if e.kind == "control_clue") == ["91A", "91B"]


def test_project_subgraph_no_shared_controllers_is_hub_and_seeds_only():
    ctx = HybridContext(query="注塑", seeds=[_seed("91A", "甲公司", 0.9)],
                        shared_controllers=[])

    sub = project_subgraph(ctx)

    assert {n.kind for n in sub.nodes} == {"query", "seed"}
    assert all(e.kind == "semantic_match" for e in sub.edges)


def test_project_subgraph_empty_seeds_yields_empty_subgraph():
    sub = project_subgraph(HybridContext(query="注塑", seeds=[], shared_controllers=[]))
    assert sub.nodes == [] and sub.edges == []

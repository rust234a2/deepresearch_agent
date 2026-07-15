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


# ---------- project_subgraph：HybridContext → 可视化子图 ----------

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


def test_project_subgraph_maps_nodes_and_edges():
    ctx = HybridContext(seeds=[_seed(
        "91A", "甲公司", score=0.9,
        controllers=[_controller("person:张三", "张三", via_person=True)],
        neighbors=[
            _neighbor("ext:基金X", "基金X", "company", "shareholding", "in", "60%"),
            _neighbor("91C", "丙公司", "company", "investment", "out", "30%"),
        ],
    )], shared_controllers=[])

    sub = project_subgraph(ctx)

    kinds = {n.id: n.kind for n in sub.nodes}
    assert kinds == {"91A": "seed", "ext:基金X": "shareholder",
                     "91C": "investment", "person:张三": "controller"}
    types = {n.id: n.node_type for n in sub.nodes}
    assert types["person:张三"] == "person" and types["91A"] == "company"
    seed_node = next(n for n in sub.nodes if n.id == "91A")
    assert seed_node.score == 0.9
    edges = {(e.source, e.target): e for e in sub.edges}
    assert edges[("ext:基金X", "91A")].kind == "shareholding"
    assert edges[("ext:基金X", "91A")].holding_pct == "60%"
    assert edges[("91A", "91C")].kind == "investment"
    clue = edges[("person:张三", "91A")]
    assert clue.kind == "control_clue" and clue.via_person is True
    assert sub.truncated is False


def test_project_subgraph_dedups_prefers_stronger_kind_and_keeps_edges():
    # 张三 既是 甲 的直接股东，又是 甲、乙 的最终控制人 → 一个节点、kind=controller、三条边
    zhang_in = _neighbor("person:张三", "张三", "person", "shareholding", "in", "40%")
    ctx = HybridContext(seeds=[
        _seed("91A", "甲公司", 0.9,
              controllers=[_controller("person:张三", "张三", True)], neighbors=[zhang_in]),
        _seed("91B", "乙公司", 0.8, controllers=[_controller("person:张三", "张三", True)]),
    ], shared_controllers=[])

    sub = project_subgraph(ctx)

    zhang = [n for n in sub.nodes if n.id == "person:张三"]
    assert len(zhang) == 1 and zhang[0].kind == "controller"
    triples = sorted((e.source, e.target, e.kind) for e in sub.edges)
    assert triples == [
        ("person:张三", "91A", "control_clue"),
        ("person:张三", "91A", "shareholding"),
        ("person:张三", "91B", "control_clue"),
    ]


def test_project_subgraph_marks_shared_controllers():
    ctx = HybridContext(
        seeds=[
            _seed("91A", "甲公司", 0.9, controllers=[_controller("ext:集团", "集团")]),
            _seed("91B", "乙公司", 0.8, controllers=[_controller("ext:集团", "集团")]),
        ],
        shared_controllers=[SharedController(
            node_id="ext:集团", name="集团", controlled_seeds=["91A", "91B"],
            via_person=False, concentrated_industries=["机床制造"],
        )],
    )

    sub = project_subgraph(ctx)

    node = next(n for n in sub.nodes if n.id == "ext:集团")
    assert node.is_shared_controller is True
    assert node.concentrated_industries == ["机床制造"]
    assert node.node_type == "company"


def test_project_subgraph_truncates_neighbors_by_pct():
    neighbors = [
        _neighbor(f"ext:股东{i:02d}", f"股东{i:02d}", "company", "shareholding", "in", f"{i}%")
        for i in range(1, 18)  # 17 个直接股东，比例 1%..17%
    ]
    ctx = HybridContext(seeds=[_seed("91A", "甲公司", 0.9, neighbors=neighbors)],
                        shared_controllers=[])

    sub = project_subgraph(ctx)

    holders = {n.id for n in sub.nodes if n.kind == "shareholder"}
    assert len(holders) == 15
    assert "ext:股东17" in holders and "ext:股东03" in holders  # 高比例保留
    assert "ext:股东01" not in holders and "ext:股东02" not in holders  # 最低两个被截断
    assert sub.truncated is True


def test_project_subgraph_empty_context():
    sub = project_subgraph(HybridContext(seeds=[], shared_controllers=[]))
    assert sub.nodes == [] and sub.edges == [] and sub.truncated is False

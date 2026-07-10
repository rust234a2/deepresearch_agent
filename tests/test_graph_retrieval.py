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

from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.graph_traversal import ultimate_controllers
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


def test_backend_has_node_and_display_name(tmp_path):
    backend = InMemoryOwnershipBackend(_graph(tmp_path))
    assert backend.has_node(A_CODE) is True
    assert backend.has_node("no-such") is False
    assert backend.display_name(A_CODE) == "甲公司"
    assert backend.display_name("no-such") == "no-such"


def test_backend_ultimate_controllers_matches_traversal(tmp_path):
    graph = _graph(tmp_path)
    backend = InMemoryOwnershipBackend(graph)
    assert backend.ultimate_controllers(A_CODE) == ultimate_controllers(graph, A_CODE)


def test_backend_direct_neighbors_shape_and_sort(tmp_path):
    backend = InMemoryOwnershipBackend(_graph(tmp_path))
    neighbors = backend.direct_neighbors(A_CODE)
    assert neighbors == sorted(neighbors, key=lambda n: (n.direction, n.node_id))
    # 甲 对外投资 丙（out / investment）
    assert any(
        n.node_id == C_CODE and n.direction == "out" and n.edge_type == "investment"
        for n in neighbors
    )
    # 乙 持股 甲（in / shareholding）
    assert any(
        n.node_id == B_CODE and n.direction == "in" and n.edge_type == "shareholding"
        for n in neighbors
    )

from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_models import external_node_id
from deepresearch_agent.company_repository import CompanyRepository
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


def test_external_node_id_branches():
    assert external_node_id("张三", True) == ("person:张三", "person")
    assert external_node_id("某证券投资基金", False) == ("fund:某证券投资基金", "fund")
    assert external_node_id("某公司", False) == ("ext:某公司", "company")


def test_load_ownership_graph_builds_nodes_and_adjacency(tmp_path):
    graph = _graph(tmp_path)

    assert graph.get_node(A_CODE) is not None
    assert graph.get_node(A_CODE).node_type == "company"

    predecessor_sources = {e.source_node_id for e in graph.predecessors(A_CODE)}
    assert B_CODE in predecessor_sources
    assert "ext:共同控股集团有限公司" in predecessor_sources
    assert "person:张三" in predecessor_sources

    successor_targets = {e.target_node_id for e in graph.successors(A_CODE)}
    assert C_CODE in successor_targets
    assert "ext:共同投资标的有限公司" in successor_targets


def test_load_ownership_graph_edge_count_and_unknown(tmp_path):
    graph = _graph(tmp_path)

    assert len(graph.edges) > 0
    assert all(
        e.source_node_id in graph.nodes and e.target_node_id in graph.nodes for e in graph.edges
    )
    assert graph.get_node("no-such-node") is None
    assert graph.successors("no-such-node") == []
    assert graph.predecessors("no-such-node") == []

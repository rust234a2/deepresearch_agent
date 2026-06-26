from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_models import GraphEdge, GraphNode
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.graph_traversal import (
    ego_graph,
    ultimate_controllers,
)
from deepresearch_agent.ownership_graph import OwnershipGraph, load_ownership_graph


LINKS = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _graph(tmp_path: Path) -> OwnershipGraph:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        LINKS / "companies.csv",
        LINKS / "contacts.csv",
        database_path,
        shareholders_csv=LINKS / "shareholders.csv",
        investments_csv=LINKS / "investments.csv",
    )
    return load_ownership_graph(CompanyRepository(database_path))


def _manual_graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> OwnershipGraph:
    out_edges: dict[str, list[GraphEdge]] = {}
    in_edges: dict[str, list[GraphEdge]] = {}
    for edge in edges:
        out_edges.setdefault(edge.source_node_id, []).append(edge)
        in_edges.setdefault(edge.target_node_id, []).append(edge)
    return OwnershipGraph(
        nodes={n.node_id: n for n in nodes},
        edges=edges,
        out_edges=out_edges,
        in_edges=in_edges,
    )


def test_ego_graph_includes_in_and_out_neighbors(tmp_path):
    graph = _graph(tmp_path)

    ego = ego_graph(graph, A_CODE, radius=1)

    assert ego.center == A_CODE
    assert A_CODE in ego.node_ids
    assert B_CODE in ego.node_ids
    assert "person:张三" in ego.node_ids
    assert C_CODE in ego.node_ids
    assert "ext:共同投资标的有限公司" in ego.node_ids


def test_ego_graph_does_not_expand_from_fund():
    nodes = [
        GraphNode(node_id="X", display_name="X", normalized_name="x",
                  node_type="company", in_database=True, mention_count=1),
        GraphNode(node_id="Y", display_name="Y", normalized_name="y",
                  node_type="company", in_database=True, mention_count=1),
        GraphNode(node_id="fund:F", display_name="F基金", normalized_name="f基金",
                  node_type="fund", in_database=False, mention_count=2),
    ]
    edges = [
        GraphEdge(source_node_id="fund:F", target_node_id="X", edge_type="shareholding"),
        GraphEdge(source_node_id="fund:F", target_node_id="Y", edge_type="shareholding"),
    ]
    graph = _manual_graph(nodes, edges)

    ego = ego_graph(graph, "X", radius=2)

    assert "fund:F" in ego.node_ids
    assert "Y" not in ego.node_ids


def test_ultimate_controllers(tmp_path):
    graph = _graph(tmp_path)

    controllers = ultimate_controllers(graph, A_CODE)

    by_id = {c.node_id: c for c in controllers}
    assert "ext:共同控股集团有限公司" in by_id
    assert by_id["ext:共同控股集团有限公司"].via_person is False
    assert "person:张三" in by_id
    assert by_id["person:张三"].via_person is True
    assert B_CODE not in by_id

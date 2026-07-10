from __future__ import annotations


def build_ownership_neo4j(repository, driver) -> None:
    """从 SQLite 读 graph_nodes/边，幂等灌进 Neo4j。SQLite 是事实源，此为可重建产物。"""
    nodes = repository.iter_graph_nodes()
    edges = repository.iter_graph_edges()
    node_rows = [
        {
            "node_id": n.node_id,
            "display_name": n.display_name,
            "node_type": n.node_type,
            "is_person": n.is_person,
        }
        for n in nodes
    ]
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT entity_node_id IF NOT EXISTS "
            "FOR (n:Entity) REQUIRE n.node_id IS UNIQUE"
        )
        session.run("MATCH (n:Entity) DETACH DELETE n")
        session.run(
            "UNWIND $rows AS row MERGE (n:Entity {node_id: row.node_id}) "
            "SET n.display_name = row.display_name, n.node_type = row.node_type, "
            "n.is_person = row.is_person",
            rows=node_rows,
        )
        for rel, kind in (("SHAREHOLDING", "shareholding"), ("INVESTMENT", "investment")):
            rows = [
                {"src": e.source_node_id, "tgt": e.target_node_id, "pct": e.holding_pct}
                for e in edges
                if e.edge_type == kind
            ]
            session.run(
                f"UNWIND $rows AS row "
                f"MATCH (s:Entity {{node_id: row.src}}), (t:Entity {{node_id: row.tgt}}) "
                f"MERGE (s)-[r:{rel}]->(t) SET r.holding_pct = row.pct",
                rows=rows,
            )

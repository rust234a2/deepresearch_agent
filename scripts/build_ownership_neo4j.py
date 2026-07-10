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


_INDUSTRY_LEVELS = ("门类", "大类", "中类", "小类")


def _ind_id(level: str, name: str) -> str:
    return f"ind:{level}:{name}"


def _industry_chain(ci) -> list[tuple[str, str]]:
    """公司的非空四级行业链，浅→深（门类→小类）。"""
    names = (
        ci.gb_industry_section,
        ci.gb_industry_division,
        ci.gb_industry_group,
        ci.gb_industry_class,
    )
    return [(level, name) for level, name in zip(_INDUSTRY_LEVELS, names) if name]


def build_industry_neo4j(repository, driver) -> None:
    """从登记的国标四级行业名建 (:Industry) 树 + 公司归属边。幂等，只影响行业子图。"""
    node_rows: dict[str, dict] = {}
    hier_rows: dict[tuple[str, str], dict] = {}
    member_rows: list[dict] = []
    for ci in repository.iter_company_industries():
        chain = _industry_chain(ci)
        if not chain:
            continue
        ids = []
        for level, name in chain:
            nid = _ind_id(level, name)
            node_rows[nid] = {"node_id": nid, "name": name, "level": level}
            ids.append(nid)
        for shallow, deep in zip(ids, ids[1:]):
            hier_rows[(deep, shallow)] = {"deep": deep, "shallow": shallow}
        member_rows.append({"code": ci.unified_social_credit_code, "ind": ids[-1]})

    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT industry_node_id IF NOT EXISTS "
            "FOR (i:Industry) REQUIRE i.node_id IS UNIQUE"
        )
        session.run("MATCH (i:Industry) DETACH DELETE i")
        session.run(
            "UNWIND $rows AS row MERGE (i:Industry {node_id: row.node_id}) "
            "SET i.name = row.name, i.level = row.level",
            rows=list(node_rows.values()),
        )
        session.run(
            "UNWIND $rows AS row "
            "MATCH (d:Industry {node_id: row.deep}), (s:Industry {node_id: row.shallow}) "
            "MERGE (d)-[:SUBCLASS_OF]->(s)",
            rows=list(hier_rows.values()),
        )
        session.run(
            "UNWIND $rows AS row "
            "MATCH (c:Entity {node_id: row.code}), (i:Industry {node_id: row.ind}) "
            "MERGE (c)-[:IN_INDUSTRY]->(i)",
            rows=member_rows,
        )

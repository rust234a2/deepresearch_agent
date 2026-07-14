from __future__ import annotations

import os

from deepresearch_agent.graph_traversal import ControllerResult
from deepresearch_agent.ownership_backend import NeighborEdge


class Neo4jBackend:
    """OwnershipGraphBackend 的 Neo4j 实现：遍历下推为 Cypher。

    via_person 语义说明：内存实现取"BFS 首达路径"的值；此处取"任一有效路径是否
    经自然人"（定义更确定）。二者在 ownership_links fixture 上逐条相等。
    """

    def __init__(self, driver) -> None:
        self._driver = driver

    @classmethod
    def from_env(cls) -> Neo4jBackend:
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "devpassword")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return cls(driver)

    def has_node(self, node_id: str) -> bool:
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (n:Entity {node_id: $id}) RETURN count(n) > 0 AS exists", id=node_id
            ).single()
        return bool(rec["exists"])

    def display_name(self, node_id: str) -> str:
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (n:Entity {node_id: $id}) RETURN n.display_name AS name", id=node_id
            ).single()
        return rec["name"] if rec is not None else node_id

    def ultimate_controllers(self, node_id: str, max_depth: int = 5) -> list[ControllerResult]:
        query = (
            f"MATCH path = (start:Entity {{node_id: $id}})"
            f"<-[:SHAREHOLDING|INVESTMENT*1..{int(max_depth)}]-(ctrl:Entity) "
            "WHERE none(n IN nodes(path)[1..] WHERE n.node_type = 'fund') "
            "AND (ctrl.is_person OR NOT EXISTS { "
            "MATCH (ctrl)<-[:SHAREHOLDING|INVESTMENT]-(p:Entity) WHERE p.node_type <> 'fund' }) "
            "WITH ctrl, min(length(path)) AS depth, "
            "max(CASE WHEN any(n IN nodes(path)[1..] WHERE n.is_person) THEN 1 ELSE 0 END) AS via "
            "RETURN ctrl.node_id AS node_id, ctrl.display_name AS display_name, "
            "depth, via = 1 AS via_person ORDER BY depth, node_id"
        )
        with self._driver.session() as s:
            return [
                ControllerResult(
                    node_id=r["node_id"],
                    display_name=r["display_name"],
                    depth=r["depth"],
                    via_person=r["via_person"],
                )
                for r in s.run(query, id=node_id)
            ]

    def direct_neighbors(self, node_id: str) -> list[NeighborEdge]:
        query = (
            "MATCH (x:Entity {node_id: $id})-[r:SHAREHOLDING|INVESTMENT]-(nb:Entity) "
            "RETURN nb.node_id AS node_id, nb.display_name AS name, nb.node_type AS node_type, "
            "type(r) AS rel_type, r.holding_pct AS holding_pct, "
            "CASE WHEN startNode(r).node_id = $id THEN 'out' ELSE 'in' END AS direction"
        )
        with self._driver.session() as s:
            neighbors = [
                NeighborEdge(
                    node_id=r["node_id"],
                    name=r["name"],
                    node_type=r["node_type"],
                    edge_type=r["rel_type"].lower(),
                    direction=r["direction"],
                    holding_pct=r["holding_pct"],
                )
                for r in s.run(query, id=node_id)
            ]
        neighbors.sort(key=lambda n: (n.direction, n.node_id))
        return neighbors

    def company_industry(self, node_id: str) -> str | None:
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (c:Entity {node_id: $id})-[:IN_INDUSTRY]->(i:Industry) "
                "RETURN i.name AS name",
                id=node_id,
            ).single()
        return rec["name"] if rec is not None else None

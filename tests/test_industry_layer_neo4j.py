import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("neo4j")

from deepresearch_agent.company_repository import CompanyRepository

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

LINKS = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"


def _repository(tmp_path: Path) -> CompanyRepository:
    from deepresearch_agent.company_database import build_company_database

    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        LINKS / "companies.csv",
        LINKS / "contacts.csv",
        database_path,
        shareholders_csv=LINKS / "shareholders.csv",
        investments_csv=LINKS / "investments.csv",
    )
    return CompanyRepository(database_path)


def _driver_or_skip():
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "devpassword")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
    except Exception:
        driver.close()
        pytest.skip("Neo4j 不可达（先 docker compose up -d neo4j）")
    return driver


def _count(driver, query: str) -> int:
    with driver.session() as s:
        return s.run(query).single()["c"]


@pytest.mark.neo4j
def test_industry_layer_matches_data(tmp_path):
    from build_ownership_neo4j import (
        _industry_chain,
        build_industry_neo4j,
        build_ownership_neo4j,
    )

    repository = _repository(tmp_path)
    driver = _driver_or_skip()
    try:
        build_ownership_neo4j(repository, driver)  # 先建 :Entity
        entity_before = _count(driver, "MATCH (n:Entity) RETURN count(n) AS c")

        build_industry_neo4j(repository, driver)

        industries = repository.iter_company_industries()
        distinct_nodes = set()
        member_count = 0
        hier_pairs = set()
        for ci in industries:
            chain = _industry_chain(ci)
            if not chain:
                continue
            member_count += 1
            ids = [f"ind:{lv}:{nm}" for lv, nm in chain]
            for lv, nm in chain:
                distinct_nodes.add((lv, nm))
            for shallow, deep in zip(ids, ids[1:]):
                hier_pairs.add((deep, shallow))

        assert member_count >= 2, "fixture 应有多家公司带行业，便于验证共享"
        assert _count(driver, "MATCH (i:Industry) RETURN count(i) AS c") == len(distinct_nodes)
        assert (
            _count(driver, "MATCH (:Entity)-[:IN_INDUSTRY]->(:Industry) RETURN count(*) AS c")
            == member_count
        )
        assert (
            _count(driver, "MATCH (:Industry)-[:SUBCLASS_OF]->(:Industry) RETURN count(*) AS c")
            == len(hier_pairs)
        )

        # 共享：多家同一小类 → 指向同一节点（distinct 节点数 < 归属边数 即体现去重共享）
        assert len(distinct_nodes) < member_count * 4 or member_count == 1

        # 幂等：再灌一次，计数不变
        build_industry_neo4j(repository, driver)
        assert _count(driver, "MATCH (i:Industry) RETURN count(i) AS c") == len(distinct_nodes)

        # 不越界：行业灌图不动 :Entity
        assert _count(driver, "MATCH (n:Entity) RETURN count(n) AS c") == entity_before
    finally:
        driver.close()

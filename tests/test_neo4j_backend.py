import os
from pathlib import Path

import pytest

pytest.importorskip("neo4j")

from deepresearch_agent.company_repository import CompanyRepository

LINKS = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _repository(tmp_path: Path) -> CompanyRepository:
    from deepresearch_agent.company_database import build_company_database

    database_path = tmp_path / "companies.sqlite3"
    if not database_path.exists():
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


@pytest.mark.neo4j
def test_loader_populates_neo4j_matching_sqlite(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_ownership_neo4j import build_ownership_neo4j

    repository = _repository(tmp_path)
    driver = _driver_or_skip()
    try:
        build_ownership_neo4j(repository, driver)
        with driver.session() as s:
            n = s.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
            e = s.run(
                "MATCH ()-[r:SHAREHOLDING|INVESTMENT]->() RETURN count(r) AS c"
            ).single()["c"]
        assert n == len(repository.iter_graph_nodes())
        assert e == len(repository.iter_graph_edges())
    finally:
        driver.close()

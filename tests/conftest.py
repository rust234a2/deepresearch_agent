from pathlib import Path

import pytest

from deepresearch_agent.company_database import build_company_database


@pytest.fixture
def company_database_path(tmp_path: Path) -> Path:
    fixtures = Path(__file__).parent / "fixtures" / "procurement"
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        fixtures / "companies.csv",
        fixtures / "contacts.csv",
        database_path,
    )
    return database_path

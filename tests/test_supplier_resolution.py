from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.supplier_resolution import resolve_supplier


FIXTURES = Path(__file__).parent / "fixtures" / "procurement"


def _repository(tmp_path: Path) -> CompanyRepository:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
    )
    return CompanyRepository(database_path)


def test_resolve_supplier_by_legal_name(tmp_path):
    result = resolve_supplier("核验示例科技股份有限公司", _repository(tmp_path))

    assert result.status == "resolved"
    assert result.legal_name == "示例科技股份有限公司"
    assert result.match_type == "legal_name"


def test_resolve_supplier_by_alias(tmp_path):
    result = resolve_supplier("评估示例设备有限公司", _repository(tmp_path))

    assert result.status == "resolved"
    assert result.legal_name == "示例科技股份有限公司"
    assert result.matched_text == "示例设备有限公司"
    assert result.match_type == "alias"


def test_resolve_supplier_reports_unknown_question(tmp_path):
    result = resolve_supplier("评估不存在企业", _repository(tmp_path))

    assert result.status == "not_found"
    assert result.legal_name is None
    assert result.candidates == []

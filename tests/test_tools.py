from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


FIXTURES = Path(__file__).parent / "fixtures" / "procurement"


def _registry(tmp_path: Path):
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
    )
    return build_procurement_tool_registry(CompanyRepository(database_path))


def test_company_profile_tool_returns_only_source_backed_fields(tmp_path):
    registry = _registry(tmp_path)

    result = registry.run(
        "get_company_profile",
        {"credit_code": "91330000123456789X"},
    )

    assert result.status == "ok"
    assert result.data["legal_name"] == "示例科技股份有限公司"
    assert result.data["business_scope"] == "工业设备制造；工业设备销售。"
    assert "products" not in result.data
    assert "certifications" not in result.data
    assert result.permission_tier == "read_private"


def test_company_contact_tool_returns_source_backed_contact(tmp_path):
    registry = _registry(tmp_path)

    result = registry.run(
        "get_company_contact",
        {"credit_code": "91330000123456789X"},
    )

    assert result.status == "ok"
    assert result.data["phones"] == ["0571-12345678", "400-123-4567"]
    assert result.data["emails"] == ["info@example.cn", "sales@example.cn"]


def test_unknown_company_returns_structured_tool_error(tmp_path):
    registry = _registry(tmp_path)

    result = registry.run("get_company_profile", {"credit_code": "missing"})

    assert result.status == "error"
    assert "Unknown company credit code" in result.data["error"]

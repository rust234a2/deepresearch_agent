import csv
import sqlite3
from pathlib import Path

import pytest

from deepresearch_agent.company_data_cleaning import CORE_COLUMNS
from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository


FIXTURES = Path(__file__).parent / "fixtures" / "procurement"


def _build_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
    )
    return database_path


def _build_database_with_ownership(tmp_path: Path) -> Path:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
        shareholders_csv=FIXTURES / "shareholders.csv",
        investments_csv=FIXTURES / "investments.csv",
    )
    return database_path


def test_repository_returns_profile_aliases_and_contact(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))

    record = repository.get_by_credit_code("91330000123456789X")

    assert record is not None
    assert record.profile.legal_name == "示例科技股份有限公司"
    assert record.profile.business_scope == "工业设备制造；工业设备销售。"
    assert record.profile.aliases == ["示例机械有限公司", "示例设备有限公司"]
    assert record.contact is not None
    assert record.contact.phones == ["0571-12345678", "400-123-4567"]


def test_repository_get_contact_returns_contact_and_none_for_missing(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))

    contact = repository.get_contact("91330000123456789X")

    assert contact is not None
    assert contact.legal_name == "示例科技股份有限公司"
    assert contact.phones == ["0571-12345678", "400-123-4567"]
    assert repository.get_contact("missing-code") is None


def test_repository_resolves_legal_name_and_alias_from_question(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))

    legal_name = repository.resolve_text("请核验示例科技股份有限公司的工商信息")
    alias = repository.resolve_text("请核验示例设备有限公司的工商信息")

    assert legal_name.status == "resolved"
    assert legal_name.match_type == "legal_name"
    assert legal_name.unified_social_credit_code == "91330000123456789X"
    assert alias.status == "resolved"
    assert alias.match_type == "alias"
    assert alias.matched_text == "示例设备有限公司"


def test_repository_returns_not_found_for_unknown_question(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))

    result = repository.resolve_text("请核验不存在公司")

    assert result.status == "not_found"
    assert result.candidates == []


def test_repository_reports_shared_alias_as_ambiguous(tmp_path):
    with (FIXTURES / "companies.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    second = dict(rows[0])
    second["source_name"] = "第二科技"
    second["legal_name"] = "第二科技股份有限公司"
    second["unified_social_credit_code"] = "911100001111111111"
    second["aliases"] = "示例设备有限公司"
    companies_path = tmp_path / "companies.csv"
    with companies_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CORE_COLUMNS)
        writer.writeheader()
        writer.writerows([rows[0], second])
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(companies_path, FIXTURES / "contacts.csv", database_path)

    result = CompanyRepository(database_path).resolve_text("比较示例设备有限公司")

    assert result.status == "ambiguous"
    assert [item.legal_name for item in result.candidates] == [
        "示例科技股份有限公司",
        "第二科技股份有限公司",
    ]


def test_repository_prefers_more_specific_name_over_substring(tmp_path):
    with (FIXTURES / "companies.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    short = dict(rows[0])
    short["source_name"] = "示例"
    short["legal_name"] = "示例"
    short["unified_social_credit_code"] = "911100002222222222"
    short["aliases"] = ""
    companies_path = tmp_path / "companies.csv"
    with companies_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CORE_COLUMNS)
        writer.writeheader()
        writer.writerows([rows[0], short])
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(companies_path, FIXTURES / "contacts.csv", database_path)

    result = CompanyRepository(database_path).resolve_text("核验示例科技股份有限公司的工商信息")

    assert result.status == "resolved"
    assert result.legal_name == "示例科技股份有限公司"
    assert result.unified_social_credit_code == "91330000123456789X"


def test_repository_returns_scope_chunks_by_id(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))
    with sqlite3.connect(_build_database(tmp_path)) as connection:
        ids = [row[0] for row in connection.execute(
            "SELECT chunk_id FROM business_scope_chunks ORDER BY chunk_id"
        )]

    records = repository.get_scope_chunks(ids)

    assert set(records) == set(ids)
    first = records[ids[0]]
    assert first.legal_name == "示例科技股份有限公司"
    assert first.text in {"工业设备制造", "工业设备销售"}
    assert repository.get_scope_chunks([]) == {}


def test_repository_scope_index_metadata_absent_before_build(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))

    assert repository.get_scope_index_metadata() is None


def test_repository_rejects_missing_database(tmp_path):
    repository = CompanyRepository(tmp_path / "missing.sqlite3")

    with pytest.raises(FileNotFoundError, match="build_company_database.py"):
        repository.resolve_text("示例科技股份有限公司")


def test_repository_rejects_unsupported_schema_version(tmp_path):
    database_path = _build_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 99")
    repository = CompanyRepository(database_path)

    with pytest.raises(RuntimeError, match="expected 4"):
        repository.resolve_text("示例科技股份有限公司")


def test_get_graph_node_returns_typed_nodes(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    company = repository.get_graph_node("91330000123456789X")
    assert company is not None
    assert company.node_type == "company"
    assert company.in_database is True
    assert company.unified_social_credit_code == "91330000123456789X"

    person = repository.get_graph_node("person:张三")
    assert person is not None
    assert person.node_type == "person"
    assert person.is_person is True

    assert repository.get_graph_node("no-such-node") is None


def test_iter_graph_nodes_returns_all_nodes(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    nodes = repository.iter_graph_nodes()

    assert len(nodes) == 3
    assert "91330000123456789X" in {node.node_id for node in nodes}
    assert "person:张三" in {node.node_id for node in nodes}
    assert any(
        node.display_name == "某外部子公司有限公司" and not node.in_database for node in nodes
    )


def test_get_shareholders_returns_ordered_records_with_person_flag(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    records = repository.get_shareholders("91330000123456789X")

    assert len(records) == 2
    person = records[0]
    assert person.shareholder_name == "张三"
    assert person.shareholder_is_person is True
    assert person.shareholder_credit_code is None
    assert person.share_class == "流通A股"
    assert person.shares_held == "1000"
    assert person.indirect_holding_pct is None
    entity = records[1]
    assert entity.shareholder_type == "企业法人"
    assert entity.shareholder_is_person is False
    assert entity.shareholder_credit_code == "91330000123456789X"


def test_get_shareholders_returns_empty_for_unknown_and_edgeless(tmp_path):
    owned_dir = tmp_path / "owned"
    owned_dir.mkdir()
    with_ownership = CompanyRepository(_build_database_with_ownership(owned_dir))
    assert with_ownership.get_shareholders("missing-code") == []

    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    without_ownership = CompanyRepository(_build_database(plain_dir))
    assert without_ownership.get_shareholders("91330000123456789X") == []


def test_get_investments_returns_records_with_resolution(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    records = repository.get_investments("91330000123456789X")

    assert len(records) == 2
    resolved = records[0]
    assert resolved.investee_name == "示例科技股份有限公司"
    assert resolved.investee_credit_code == "91330000123456789X"
    assert resolved.status == "存续"
    assert resolved.holding_pct == "100%"
    external = records[1]
    assert external.investee_name == "某外部子公司有限公司"
    assert external.investee_credit_code is None
    assert external.status == "注销"
    assert external.subscribed_capital_original == "500万元"


def test_get_investments_returns_empty_for_unknown_and_edgeless(tmp_path):
    owned_dir = tmp_path / "owned"
    owned_dir.mkdir()
    with_ownership = CompanyRepository(_build_database_with_ownership(owned_dir))
    assert with_ownership.get_investments("missing-code") == []

    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    without_ownership = CompanyRepository(_build_database(plain_dir))
    assert without_ownership.get_investments("91330000123456789X") == []


def test_iter_shareholder_edges_returns_normalized_nodes(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    edges = repository.iter_shareholder_edges()

    assert len(edges) == 2
    person = next(e for e in edges if e.node_name == "张三")
    assert person.company_code == "91330000123456789X"
    assert person.is_person is True
    assert person.node_code is None
    entity = next(e for e in edges if e.is_person is False)
    assert entity.node_code == "91330000123456789X"


def test_iter_investment_edges_and_company_names(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    edges = repository.iter_investment_edges()
    names = repository.get_all_company_names()

    assert len(edges) == 2
    resolved = next(e for e in edges if e.node_code is not None)
    assert resolved.node_code == "91330000123456789X"
    assert all(e.is_person is False for e in edges)
    assert names["91330000123456789X"] == "示例科技股份有限公司"


_LINKS = FIXTURES / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _build_ownership_links_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        _LINKS / "companies.csv",
        _LINKS / "contacts.csv",
        database_path,
        shareholders_csv=_LINKS / "shareholders.csv",
        investments_csv=_LINKS / "investments.csv",
    )
    return database_path


def test_iter_graph_edges_maps_endpoints_to_node_ids(tmp_path):
    repository = CompanyRepository(_build_ownership_links_database(tmp_path))

    edges = repository.iter_graph_edges()

    triples = {(e.source_node_id, e.target_node_id, e.edge_type) for e in edges}
    assert ("ext:共同控股集团有限公司", A_CODE, "shareholding") in triples
    assert (B_CODE, A_CODE, "shareholding") in triples
    assert (A_CODE, C_CODE, "investment") in triples
    assert (A_CODE, "ext:共同投资标的有限公司", "investment") in triples
    fund_edge = next(
        e for e in edges if e.source_node_id.startswith("fund:") and e.target_node_id == A_CODE
    )
    assert fund_edge.edge_type == "shareholding"


def test_iter_company_industries_returns_four_level_names(company_database_path):
    repo = CompanyRepository(company_database_path)

    rows = repo.iter_company_industries()

    assert len(rows) == len(repo.get_all_company_names())
    with_class = [r for r in rows if r.gb_industry_class]
    assert with_class, "fixture 应至少有一家带小类行业"
    sample = with_class[0]
    assert sample.gb_industry_section and sample.gb_industry_division
    assert sample.gb_industry_group and sample.gb_industry_class
    assert sample.unified_social_credit_code

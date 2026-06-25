import csv
import sqlite3
from pathlib import Path

import pytest

from deepresearch_agent.company_data_cleaning import CONTACT_COLUMNS, CORE_COLUMNS
from deepresearch_agent.company_database import build_company_database


FIXTURES = Path(__file__).parent / "fixtures" / "procurement"


def _read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_build_company_database_creates_schema_indexes_and_metadata(tmp_path):
    database_path = tmp_path / "companies.sqlite3"

    summary = build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
    )

    assert summary == {"companies": 1, "contacts": 1}
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM company_aliases").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM company_contacts").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM business_scope_chunks"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT text FROM business_scope_chunks ORDER BY ordinal"
        ).fetchall() == [("工业设备制造",), ("工业设备销售",)]
        assert connection.execute(
            "SELECT embedding FROM business_scope_chunks WHERE embedding IS NULL"
        ).fetchall() == [(None,), (None,)]
        assert connection.execute("SELECT COUNT(*) FROM scope_index_metadata").fetchone()[0] == 0
        metadata = connection.execute(
            "SELECT company_count, contact_count, companies_sha256, contacts_sha256 "
            "FROM import_metadata"
        ).fetchone()
        assert metadata[:2] == (1, 1)
        assert len(metadata[2]) == 64
        assert len(metadata[3]) == 64
        assert connection.execute("SELECT COUNT(*) FROM company_shareholders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM company_investments").fetchone()[0] == 0
        ownership_meta = connection.execute(
            "SELECT shareholder_count, investment_count, shareholders_sha256, investments_sha256 "
            "FROM import_metadata"
        ).fetchone()
        assert ownership_meta == (0, 0, None, None)
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert {
        "idx_companies_registration_status",
        "idx_companies_province_city",
        "idx_companies_industry_division",
        "idx_companies_enterprise_size",
        "idx_company_aliases_normalized",
        "idx_shareholders_company",
        "idx_shareholders_holder_code",
        "idx_investments_company",
        "idx_investments_investee_code",
    } <= indexes


def test_build_company_database_rejects_duplicate_credit_code_with_line_number(tmp_path):
    companies_path = tmp_path / "companies.csv"
    rows = _read_rows(FIXTURES / "companies.csv")
    _write_rows(companies_path, CORE_COLUMNS, [rows[0], rows[0]])

    with pytest.raises(ValueError, match=r"companies\.csv:3: duplicate credit code"):
        build_company_database(companies_path, FIXTURES / "contacts.csv", tmp_path / "db.sqlite3")


def test_build_company_database_rejects_empty_company_dataset(tmp_path):
    companies_path = tmp_path / "companies.csv"
    _write_rows(companies_path, CORE_COLUMNS, [])

    with pytest.raises(ValueError, match="company dataset is empty"):
        build_company_database(companies_path, FIXTURES / "contacts.csv", tmp_path / "db.sqlite3")


def test_build_company_database_rejects_orphan_contact(tmp_path):
    contacts_path = tmp_path / "contacts.csv"
    rows = _read_rows(FIXTURES / "contacts.csv")
    rows[0]["unified_social_credit_code"] = "911100001111111111"
    _write_rows(contacts_path, CONTACT_COLUMNS, rows)

    with pytest.raises(ValueError, match=r"contacts\.csv:2: orphan contact"):
        build_company_database(FIXTURES / "companies.csv", contacts_path, tmp_path / "db.sqlite3")


def test_build_company_database_rejects_contact_name_mismatch(tmp_path):
    contacts_path = tmp_path / "contacts.csv"
    rows = _read_rows(FIXTURES / "contacts.csv")
    rows[0]["legal_name"] = "错误企业名称"
    _write_rows(contacts_path, CONTACT_COLUMNS, rows)

    with pytest.raises(ValueError, match=r"contacts\.csv:2: legal name mismatch"):
        build_company_database(FIXTURES / "companies.csv", contacts_path, tmp_path / "db.sqlite3")


def test_failed_build_preserves_existing_database_file(tmp_path):
    database_path = tmp_path / "companies.sqlite3"
    database_path.write_bytes(b"existing database sentinel")
    companies_path = tmp_path / "companies.csv"
    rows = _read_rows(FIXTURES / "companies.csv")
    _write_rows(companies_path, CORE_COLUMNS, [rows[0], rows[0]])

    with pytest.raises(ValueError):
        build_company_database(companies_path, FIXTURES / "contacts.csv", database_path)

    assert database_path.read_bytes() == b"existing database sentinel"

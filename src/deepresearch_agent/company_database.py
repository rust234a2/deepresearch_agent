from __future__ import annotations

import csv
import hashlib
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from deepresearch_agent.company_data_cleaning import CONTACT_COLUMNS, CORE_COLUMNS
from deepresearch_agent.company_models import CompanyContact, CompanyProfile


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _CompanySourceRow:
    line_number: int
    raw: dict[str, str]
    profile: CompanyProfile


@dataclass(frozen=True)
class _ContactSourceRow:
    line_number: int
    raw: dict[str, str]
    contact: CompanyContact


def normalize_company_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def build_company_database(
    companies_csv: str | Path,
    contacts_csv: str | Path,
    output_path: str | Path,
) -> dict[str, int]:
    companies_path = Path(companies_csv)
    contacts_path = Path(contacts_csv)
    companies = _read_companies(companies_path)
    contacts = _read_contacts(contacts_path, companies)
    _build_atomic_database(companies, contacts, companies_path, contacts_path, Path(output_path))
    return {"companies": len(companies), "contacts": len(contacts)}


def _read_companies(path: Path) -> list[_CompanySourceRow]:
    rows = _read_csv(path, CORE_COLUMNS)
    if not rows:
        raise ValueError(f"{path}: company dataset is empty")

    companies: list[_CompanySourceRow] = []
    seen_codes: set[str] = set()
    seen_names: set[str] = set()
    for line_number, row in rows:
        try:
            profile = CompanyProfile.model_validate(row)
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        code = profile.unified_social_credit_code
        if code in seen_codes:
            raise ValueError(f"{path}:{line_number}: duplicate credit code {code}")
        normalized_name = normalize_company_name(profile.legal_name)
        if normalized_name in seen_names:
            raise ValueError(f"{path}:{line_number}: duplicate legal name {profile.legal_name}")
        seen_codes.add(code)
        seen_names.add(normalized_name)
        companies.append(_CompanySourceRow(line_number, row, profile))
    return companies


def _read_contacts(
    path: Path,
    companies: list[_CompanySourceRow],
) -> list[_ContactSourceRow]:
    rows = _read_csv(path, CONTACT_COLUMNS)
    company_names = {
        item.profile.unified_social_credit_code: item.profile.legal_name for item in companies
    }
    contacts: list[_ContactSourceRow] = []
    seen_codes: set[str] = set()
    for line_number, row in rows:
        try:
            contact = CompanyContact.model_validate(row)
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        code = contact.unified_social_credit_code
        if code not in company_names:
            raise ValueError(f"{path}:{line_number}: orphan contact {code}")
        if contact.legal_name != company_names[code]:
            raise ValueError(
                f"{path}:{line_number}: legal name mismatch for {code}: "
                f"{contact.legal_name} != {company_names[code]}"
            )
        if code in seen_codes:
            raise ValueError(f"{path}:{line_number}: duplicate contact {code}")
        seen_codes.add(code)
        contacts.append(_ContactSourceRow(line_number, row, contact))
    return contacts


def _read_csv(path: Path, expected_columns: list[str]) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected_columns:
            raise ValueError(
                f"{path}: invalid header: expected {expected_columns}, got {reader.fieldnames}"
            )
        return [(line_number, dict(row)) for line_number, row in enumerate(reader, start=2)]


def _build_atomic_database(
    companies: list[_CompanySourceRow],
    contacts: list[_ContactSourceRow],
    companies_path: Path,
    contacts_path: Path,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.unlink(missing_ok=True)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary_path)
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            _create_schema(connection)
            _insert_companies(connection, companies)
            _insert_contacts(connection, contacts)
            connection.execute(
                "INSERT INTO import_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    SCHEMA_VERSION,
                    _sha256(companies_path),
                    _sha256(contacts_path),
                    len(companies),
                    len(companies),
                    len(contacts),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.close()
        connection = None
        temporary_path.replace(output_path)
    except Exception:
        if connection is not None:
            connection.close()
        temporary_path.unlink(missing_ok=True)
        raise


def _create_schema(connection: sqlite3.Connection) -> None:
    company_columns = [column for column in CORE_COLUMNS if column != "aliases"]
    definitions: list[str] = []
    for column in company_columns:
        if column == "unified_social_credit_code":
            definitions.append(f"{column} TEXT PRIMARY KEY")
        elif column in {"source_name", "legal_name"}:
            definitions.append(f"{column} TEXT NOT NULL")
        else:
            definitions.append(f"{column} TEXT")
    definitions.append("normalized_legal_name TEXT NOT NULL UNIQUE")
    connection.execute(f"CREATE TABLE companies ({', '.join(definitions)})")
    connection.executescript(
        """
        CREATE TABLE company_aliases (
            unified_social_credit_code TEXT NOT NULL
                REFERENCES companies(unified_social_credit_code),
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            UNIQUE(unified_social_credit_code, normalized_alias)
        );
        CREATE TABLE company_contacts (
            unified_social_credit_code TEXT PRIMARY KEY
                REFERENCES companies(unified_social_credit_code),
            legal_name TEXT NOT NULL,
            phones TEXT,
            emails TEXT,
            mailing_address TEXT
        );
        CREATE TABLE import_metadata (
            schema_version INTEGER NOT NULL,
            companies_sha256 TEXT NOT NULL,
            contacts_sha256 TEXT NOT NULL,
            input_company_count INTEGER NOT NULL,
            company_count INTEGER NOT NULL,
            contact_count INTEGER NOT NULL,
            generated_at TEXT NOT NULL
        );
        CREATE INDEX idx_companies_registration_status
            ON companies(registration_status);
        CREATE INDEX idx_companies_province_city
            ON companies(province, city);
        CREATE INDEX idx_companies_industry_division
            ON companies(gb_industry_division);
        CREATE INDEX idx_companies_enterprise_size
            ON companies(enterprise_size);
        CREATE INDEX idx_company_aliases_normalized
            ON company_aliases(normalized_alias);
        """
    )


def _insert_companies(
    connection: sqlite3.Connection,
    companies: list[_CompanySourceRow],
) -> None:
    columns = [column for column in CORE_COLUMNS if column != "aliases"]
    insert_columns = [*columns, "normalized_legal_name"]
    sql = (
        f"INSERT INTO companies ({', '.join(insert_columns)}) "
        f"VALUES ({', '.join('?' for _ in insert_columns)})"
    )
    for item in companies:
        values = [item.raw[column] for column in columns]
        values.append(normalize_company_name(item.profile.legal_name))
        connection.execute(sql, values)
        connection.executemany(
            "INSERT INTO company_aliases VALUES (?, ?, ?)",
            [
                (
                    item.profile.unified_social_credit_code,
                    alias,
                    normalize_company_name(alias),
                )
                for alias in item.profile.aliases
            ],
        )


def _insert_contacts(
    connection: sqlite3.Connection,
    contacts: list[_ContactSourceRow],
) -> None:
    connection.executemany(
        "INSERT INTO company_contacts VALUES (?, ?, ?, ?, ?)",
        [tuple(item.raw[column] for column in CONTACT_COLUMNS) for item in contacts],
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

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
from deepresearch_agent.company_models import CompanyContact, CompanyProfile, external_node_id
from deepresearch_agent.rag.chunking import chunk_business_scope


SCHEMA_VERSION = 4


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
    shareholders_csv: str | Path | None = None,
    investments_csv: str | Path | None = None,
) -> dict[str, int]:
    from deepresearch_agent.investment_data_cleaning import OUTPUT_COLUMNS as INVESTMENT_COLUMNS
    from deepresearch_agent.shareholder_data_cleaning import OUTPUT_COLUMNS as SHAREHOLDER_COLUMNS

    companies_path = Path(companies_csv)
    contacts_path = Path(contacts_csv)
    companies = _read_companies(companies_path)
    contacts = _read_contacts(contacts_path, companies)
    shareholders_path = Path(shareholders_csv) if shareholders_csv is not None else None
    investments_path = Path(investments_csv) if investments_csv is not None else None
    shareholders = _read_edges(shareholders_path, SHAREHOLDER_COLUMNS) if shareholders_path else []
    investments = _read_edges(investments_path, INVESTMENT_COLUMNS) if investments_path else []
    counts = _build_atomic_database(
        companies,
        contacts,
        shareholders,
        investments,
        companies_path,
        contacts_path,
        shareholders_path,
        investments_path,
        Path(output_path),
    )
    return {"companies": len(companies), "contacts": len(contacts), **counts}


def _read_edges(path: Path, expected_columns: list[str]) -> list[dict[str, str]]:
    return [row for _, row in _read_csv(path, expected_columns)]


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
    shareholders: list[dict[str, str]],
    investments: list[dict[str, str]],
    companies_path: Path,
    contacts_path: Path,
    shareholders_path: Path | None,
    investments_path: Path | None,
    output_path: Path,
) -> dict[str, int]:
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
            _insert_scope_chunks(connection, companies)
            legal_map, alias_map = _build_name_index(companies)
            sh_inserted, sh_unresolved = _insert_shareholders(
                connection, shareholders, legal_map, alias_map
            )
            inv_inserted, inv_unresolved = _insert_investments(
                connection, investments, legal_map, alias_map
            )
            node_count = _insert_graph_nodes(connection, companies)
            connection.execute(
                "INSERT INTO import_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    SCHEMA_VERSION,
                    _sha256(companies_path),
                    _sha256(contacts_path),
                    _sha256(shareholders_path) if shareholders_path is not None else None,
                    _sha256(investments_path) if investments_path is not None else None,
                    len(companies),
                    len(companies),
                    len(contacts),
                    sh_inserted,
                    inv_inserted,
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
    return {
        "shareholders": sh_inserted,
        "investments": inv_inserted,
        "unresolved_shareholders": sh_unresolved,
        "unresolved_investments": inv_unresolved,
        "nodes": node_count,
    }


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
            shareholders_sha256 TEXT,
            investments_sha256 TEXT,
            input_company_count INTEGER NOT NULL,
            company_count INTEGER NOT NULL,
            contact_count INTEGER NOT NULL,
            shareholder_count INTEGER NOT NULL,
            investment_count INTEGER NOT NULL,
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
        CREATE TABLE business_scope_chunks (
            chunk_id INTEGER PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL
                REFERENCES companies(unified_social_credit_code),
            section_label TEXT,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB
        );
        CREATE INDEX idx_scope_chunks_company
            ON business_scope_chunks(unified_social_credit_code);
        CREATE TABLE scope_index_metadata (
            embedding_model TEXT NOT NULL,
            embedding_dim INTEGER NOT NULL,
            normalized INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            built_at TEXT NOT NULL
        );
        CREATE TABLE company_shareholders (
            id INTEGER PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL
                REFERENCES companies(unified_social_credit_code),
            shareholder_name TEXT NOT NULL,
            normalized_shareholder_name TEXT NOT NULL,
            shareholder_credit_code TEXT,
            shareholder_type TEXT,
            shareholder_is_person TEXT NOT NULL,
            share_class TEXT,
            shares_held TEXT,
            indirect_holding_pct TEXT,
            associated_product TEXT
        );
        CREATE INDEX idx_shareholders_company
            ON company_shareholders(unified_social_credit_code);
        CREATE INDEX idx_shareholders_holder_code
            ON company_shareholders(shareholder_credit_code);
        CREATE TABLE company_investments (
            id INTEGER PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL
                REFERENCES companies(unified_social_credit_code),
            investee_name TEXT NOT NULL,
            normalized_investee_name TEXT NOT NULL,
            investee_credit_code TEXT,
            status TEXT,
            investee_established_date TEXT,
            holding_pct TEXT,
            subscribed_capital_amount TEXT,
            subscribed_capital_currency TEXT,
            subscribed_capital_original TEXT,
            final_beneficiary_pct TEXT,
            region TEXT,
            industry TEXT,
            associated_product TEXT
        );
        CREATE INDEX idx_investments_company
            ON company_investments(unified_social_credit_code);
        CREATE INDEX idx_investments_investee_code
            ON company_investments(investee_credit_code);
        CREATE TABLE graph_nodes (
            node_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            node_type TEXT NOT NULL,
            in_database INTEGER NOT NULL,
            unified_social_credit_code TEXT,
            is_person INTEGER NOT NULL,
            mention_count INTEGER NOT NULL
        );
        CREATE INDEX idx_graph_nodes_normalized ON graph_nodes(normalized_name);
        CREATE INDEX idx_graph_nodes_type ON graph_nodes(node_type);
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


def _insert_scope_chunks(
    connection: sqlite3.Connection,
    companies: list[_CompanySourceRow],
) -> None:
    for item in companies:
        code = item.profile.unified_social_credit_code
        for chunk in chunk_business_scope(item.profile.business_scope):
            connection.execute(
                "INSERT INTO business_scope_chunks "
                "(unified_social_credit_code, section_label, ordinal, text, embedding) "
                "VALUES (?, ?, ?, ?, NULL)",
                (code, chunk.section_label, chunk.ordinal, chunk.text),
            )


def _build_name_index(
    companies: list[_CompanySourceRow],
) -> tuple[dict[str, str], dict[str, set[str]]]:
    legal_map: dict[str, str] = {}
    alias_map: dict[str, set[str]] = {}
    for item in companies:
        code = item.profile.unified_social_credit_code
        legal_map[normalize_company_name(item.profile.legal_name)] = code
        for alias in item.profile.aliases:
            alias_map.setdefault(normalize_company_name(alias), set()).add(code)
    return legal_map, alias_map


def _resolve(
    normalized_name: str,
    legal_map: dict[str, str],
    alias_map: dict[str, set[str]],
) -> str | None:
    if normalized_name in legal_map:
        return legal_map[normalized_name]
    codes = alias_map.get(normalized_name)
    if codes is not None and len(codes) == 1:
        return next(iter(codes))
    return None


def _insert_shareholders(
    connection: sqlite3.Connection,
    rows: list[dict[str, str]],
    legal_map: dict[str, str],
    alias_map: dict[str, set[str]],
) -> tuple[int, int]:
    inserted = 0
    unresolved = 0
    for row in rows:
        anchor = _resolve(row["normalized_company_name"], legal_map, alias_map)
        if anchor is None:
            unresolved += 1
            continue
        holder_code: str | None = None
        if row["shareholder_is_person"] != "true":
            holder_code = _resolve(
                normalize_company_name(row["shareholder_name"]), legal_map, alias_map
            )
        connection.execute(
            "INSERT INTO company_shareholders "
            "(unified_social_credit_code, shareholder_name, normalized_shareholder_name, "
            "shareholder_credit_code, shareholder_type, shareholder_is_person, share_class, "
            "shares_held, indirect_holding_pct, associated_product) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                anchor,
                row["shareholder_name"],
                normalize_company_name(row["shareholder_name"]),
                holder_code,
                row["shareholder_type"],
                row["shareholder_is_person"],
                row["share_class"],
                row["shares_held"],
                row["indirect_holding_pct"],
                row["associated_product"],
            ),
        )
        inserted += 1
    return inserted, unresolved


def _insert_investments(
    connection: sqlite3.Connection,
    rows: list[dict[str, str]],
    legal_map: dict[str, str],
    alias_map: dict[str, set[str]],
) -> tuple[int, int]:
    inserted = 0
    unresolved = 0
    for row in rows:
        anchor = _resolve(row["normalized_company_name"], legal_map, alias_map)
        if anchor is None:
            unresolved += 1
            continue
        investee_code = _resolve(row["normalized_investee_name"], legal_map, alias_map)
        connection.execute(
            "INSERT INTO company_investments "
            "(unified_social_credit_code, investee_name, normalized_investee_name, "
            "investee_credit_code, status, investee_established_date, holding_pct, "
            "subscribed_capital_amount, subscribed_capital_currency, subscribed_capital_original, "
            "final_beneficiary_pct, region, industry, associated_product) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                anchor,
                row["investee_name"],
                row["normalized_investee_name"],
                investee_code,
                row["status"],
                row["investee_established_date"],
                row["holding_pct"],
                row["subscribed_capital_amount"],
                row["subscribed_capital_currency"],
                row["subscribed_capital_original"],
                row["final_beneficiary_pct"],
                row["region"],
                row["industry"],
                row["associated_product"],
            ),
        )
        inserted += 1
    return inserted, unresolved


def _insert_graph_nodes(
    connection: sqlite3.Connection,
    companies: list[_CompanySourceRow],
) -> int:
    legal_map = {
        item.profile.unified_social_credit_code: item.profile.legal_name for item in companies
    }
    nodes: dict[str, dict] = {}

    def bump_company(code: str) -> None:
        node = nodes.get(code)
        if node is None:
            legal_name = legal_map[code]
            nodes[code] = {
                "node_id": code,
                "display_name": legal_name,
                "normalized_name": normalize_company_name(legal_name),
                "node_type": "company",
                "in_database": 1,
                "unified_social_credit_code": code,
                "is_person": 0,
                "mention_count": 1,
            }
        else:
            node["mention_count"] += 1

    def bump_external(display_name: str, normalized_name: str, is_person: bool) -> None:
        node_id, node_type = external_node_id(normalized_name, is_person)
        node = nodes.get(node_id)
        if node is None:
            nodes[node_id] = {
                "node_id": node_id,
                "display_name": display_name,
                "normalized_name": normalized_name,
                "node_type": node_type,
                "in_database": 0,
                "unified_social_credit_code": None,
                "is_person": 1 if is_person else 0,
                "mention_count": 1,
            }
        else:
            node["mention_count"] += 1

    for anchor, name, normalized, code, is_person in connection.execute(
        "SELECT unified_social_credit_code, shareholder_name, normalized_shareholder_name, "
        "shareholder_credit_code, shareholder_is_person FROM company_shareholders"
    ).fetchall():
        bump_company(anchor)
        if code is not None:
            bump_company(code)
        else:
            bump_external(name, normalized, is_person == "true")

    for anchor, name, normalized, code in connection.execute(
        "SELECT unified_social_credit_code, investee_name, normalized_investee_name, "
        "investee_credit_code FROM company_investments"
    ).fetchall():
        bump_company(anchor)
        if code is not None:
            bump_company(code)
        else:
            bump_external(name, normalized, False)

    for node in nodes.values():
        connection.execute(
            "INSERT INTO graph_nodes (node_id, display_name, normalized_name, node_type, "
            "in_database, unified_social_credit_code, is_person, mention_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                node["node_id"],
                node["display_name"],
                node["normalized_name"],
                node["node_type"],
                node["in_database"],
                node["unified_social_credit_code"],
                node["is_person"],
                node["mention_count"],
            ),
        )
    return len(nodes)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

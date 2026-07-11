from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from deepresearch_agent.company_database import SCHEMA_VERSION, normalize_company_name
from deepresearch_agent.company_models import (
    CompanyContact,
    CompanyIndustry,
    CompanyProfile,
    CompanyRecord,
    CompanyResolution,
    CompanyResolutionCandidate,
    GraphEdge,
    GraphNode,
    InvestmentRecord,
    OwnershipEdge,
    ScopeChunkRecord,
    ScopeIndexMetadata,
    ShareholderRecord,
    external_node_id,
)


class CompanyRepository:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.exists():
            raise FileNotFoundError(
                f"Company database not found: {self.database_path}. "
                "Run scripts/build_company_database.py first."
            )
        connection = sqlite3.connect(
            f"file:{self.database_path.resolve().as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            connection.close()
            raise RuntimeError(
                f"Unsupported company database schema {version}; "
                f"expected {SCHEMA_VERSION}. Rebuild it."
            )
        return connection

    def get_by_credit_code(self, code: str) -> CompanyRecord | None:
        normalized_code = code.strip()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM companies WHERE unified_social_credit_code = ?",
                (normalized_code,),
            ).fetchone()
            if row is None:
                return None
            aliases = [
                item[0]
                for item in connection.execute(
                    "SELECT alias FROM company_aliases "
                    "WHERE unified_social_credit_code = ? ORDER BY alias",
                    (normalized_code,),
                )
            ]
            contact_row = connection.execute(
                "SELECT * FROM company_contacts WHERE unified_social_credit_code = ?",
                (normalized_code,),
            ).fetchone()

        profile_data = dict(row)
        profile_data.pop("normalized_legal_name")
        profile_data["aliases"] = aliases
        profile = CompanyProfile.model_validate(profile_data)
        contact = CompanyContact.model_validate(dict(contact_row)) if contact_row else None
        return CompanyRecord(profile=profile, contact=contact)

    def get_contact(self, code: str) -> CompanyContact | None:
        normalized_code = code.strip()
        with self._connect() as connection:
            contact_row = connection.execute(
                "SELECT * FROM company_contacts WHERE unified_social_credit_code = ?",
                (normalized_code,),
            ).fetchone()
        if contact_row is None:
            return None
        return CompanyContact.model_validate(dict(contact_row))

    def resolve_text(self, text: str) -> CompanyResolution:
        normalized_text = normalize_company_name(text)
        matches: dict[str, tuple[str, str, str]] = {}
        with self._connect() as connection:
            legal_names = connection.execute(
                "SELECT unified_social_credit_code, legal_name, legal_name AS matched_text "
                "FROM companies"
            ).fetchall()
            aliases = connection.execute(
                "SELECT aliases.unified_social_credit_code, companies.legal_name, "
                "aliases.alias AS matched_text "
                "FROM company_aliases AS aliases "
                "JOIN companies USING (unified_social_credit_code)"
            ).fetchall()

        for row, match_type in [
            *((row, "legal_name") for row in legal_names),
            *((row, "alias") for row in aliases),
        ]:
            matched_text = row["matched_text"]
            normalized_candidate = normalize_company_name(matched_text)
            if not _contains_name(normalized_text, normalized_candidate):
                continue
            code = row["unified_social_credit_code"]
            candidate = (row["legal_name"], matched_text, match_type)
            current = matches.get(code)
            if current is None or _match_rank(candidate) > _match_rank(current):
                matches[code] = candidate

        if not matches:
            return CompanyResolution(status="not_found")

        matches = _drop_dominated_matches(matches)

        if len(matches) > 1:
            candidates = sorted(
                (
                    CompanyResolutionCandidate(
                        legal_name=legal_name,
                        unified_social_credit_code=code,
                    )
                    for code, (legal_name, _, _) in matches.items()
                ),
                key=lambda item: item.legal_name,
            )
            return CompanyResolution(status="ambiguous", candidates=candidates)

        code, (legal_name, matched_text, match_type) = next(iter(matches.items()))
        return CompanyResolution(
            status="resolved",
            legal_name=legal_name,
            unified_social_credit_code=code,
            matched_text=matched_text,
            match_type=match_type,
            candidates=[
                CompanyResolutionCandidate(
                    legal_name=legal_name,
                    unified_social_credit_code=code,
                )
            ],
        )

    def get_scope_chunks(self, chunk_ids: list[int]) -> dict[int, ScopeChunkRecord]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chunks.chunk_id, chunks.unified_social_credit_code, "
                "companies.legal_name, chunks.section_label, chunks.text "
                "FROM business_scope_chunks AS chunks "
                "JOIN companies USING (unified_social_credit_code) "
                f"WHERE chunks.chunk_id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
        return {
            row["chunk_id"]: ScopeChunkRecord(
                chunk_id=row["chunk_id"],
                unified_social_credit_code=row["unified_social_credit_code"],
                legal_name=row["legal_name"],
                section_label=row["section_label"],
                text=row["text"],
            )
            for row in rows
        }

    def get_scope_index_metadata(self) -> ScopeIndexMetadata | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT embedding_model, embedding_dim, normalized, chunk_count, built_at "
                "FROM scope_index_metadata LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return ScopeIndexMetadata(
            embedding_model=row["embedding_model"],
            embedding_dim=row["embedding_dim"],
            normalized=bool(row["normalized"]),
            chunk_count=row["chunk_count"],
            built_at=row["built_at"],
        )

    def get_shareholders(self, code: str) -> list[ShareholderRecord]:
        normalized_code = code.strip()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, shareholder_name, "
                "shareholder_credit_code, shareholder_type, shareholder_is_person, "
                "share_class, shares_held, indirect_holding_pct, associated_product "
                "FROM company_shareholders "
                "WHERE unified_social_credit_code = ? ORDER BY id",
                (normalized_code,),
            ).fetchall()
        return [ShareholderRecord.model_validate(dict(row)) for row in rows]

    def get_investments(self, code: str) -> list[InvestmentRecord]:
        normalized_code = code.strip()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, investee_name, investee_credit_code, "
                "status, investee_established_date, holding_pct, subscribed_capital_amount, "
                "subscribed_capital_currency, subscribed_capital_original, "
                "final_beneficiary_pct, region, industry, associated_product "
                "FROM company_investments "
                "WHERE unified_social_credit_code = ? ORDER BY id",
                (normalized_code,),
            ).fetchall()
        return [InvestmentRecord.model_validate(dict(row)) for row in rows]

    def get_all_company_names(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, legal_name FROM companies"
            ).fetchall()
        return {row["unified_social_credit_code"]: row["legal_name"] for row in rows}

    def iter_aliases(self) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, alias FROM company_aliases "
                "ORDER BY unified_social_credit_code, alias"
            ).fetchall()
        return [(row["unified_social_credit_code"], row["alias"]) for row in rows]

    def iter_company_industries(self) -> list[CompanyIndustry]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, gb_industry_section, "
                "gb_industry_division, gb_industry_group, gb_industry_class "
                "FROM companies"
            ).fetchall()
        return [CompanyIndustry.model_validate(dict(row)) for row in rows]

    def iter_shareholder_edges(self) -> list[OwnershipEdge]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, normalized_shareholder_name, "
                "shareholder_credit_code, shareholder_is_person FROM company_shareholders"
            ).fetchall()
        return [
            OwnershipEdge(
                company_code=row["unified_social_credit_code"],
                node_name=row["normalized_shareholder_name"],
                node_code=row["shareholder_credit_code"],
                is_person=row["shareholder_is_person"] == "true",
            )
            for row in rows
        ]

    def iter_investment_edges(self) -> list[OwnershipEdge]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, normalized_investee_name, "
                "investee_credit_code FROM company_investments"
            ).fetchall()
        return [
            OwnershipEdge(
                company_code=row["unified_social_credit_code"],
                node_name=row["normalized_investee_name"],
                node_code=row["investee_credit_code"],
                is_person=False,
            )
            for row in rows
        ]

    def get_graph_node(self, node_id: str) -> GraphNode | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT node_id, display_name, normalized_name, node_type, in_database, "
                "unified_social_credit_code, is_person, mention_count "
                "FROM graph_nodes WHERE node_id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            return None
        return _graph_node_from_row(row)

    def iter_graph_nodes(self) -> list[GraphNode]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT node_id, display_name, normalized_name, node_type, in_database, "
                "unified_social_credit_code, is_person, mention_count FROM graph_nodes"
            ).fetchall()
        return [_graph_node_from_row(row) for row in rows]

    def iter_graph_edges(self) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        with self._connect() as connection:
            for anchor, normalized, code, is_person, pct in connection.execute(
                "SELECT unified_social_credit_code, normalized_shareholder_name, "
                "shareholder_credit_code, shareholder_is_person, indirect_holding_pct "
                "FROM company_shareholders"
            ).fetchall():
                source = (
                    code if code is not None else external_node_id(normalized, is_person == "true")[0]
                )
                edges.append(
                    GraphEdge(
                        source_node_id=source,
                        target_node_id=anchor,
                        edge_type="shareholding",
                        holding_pct=pct,
                        status=None,
                    )
                )
            for anchor, normalized, code, pct, status in connection.execute(
                "SELECT unified_social_credit_code, normalized_investee_name, "
                "investee_credit_code, holding_pct, status FROM company_investments"
            ).fetchall():
                target = code if code is not None else external_node_id(normalized, False)[0]
                edges.append(
                    GraphEdge(
                        source_node_id=anchor,
                        target_node_id=target,
                        edge_type="investment",
                        holding_pct=pct,
                        status=status,
                    )
                )
        return edges


def _drop_dominated_matches(
    matches: dict[str, tuple[str, str, str]],
) -> dict[str, tuple[str, str, str]]:
    """Drop matches whose matched text is a proper substring of another match's.

    When a question contains a full legal name, a shorter company name that is a
    substring of it also matches. The more specific (containing) name wins, so the
    shorter, incidental match is not treated as a competing entity.
    """
    normalized = {
        code: normalize_company_name(matched_text)
        for code, (_, matched_text, _) in matches.items()
    }
    kept: dict[str, tuple[str, str, str]] = {}
    for code, value in matches.items():
        text = normalized[code]
        if any(
            other_code != code and text != other_text and text in other_text
            for other_code, other_text in normalized.items()
        ):
            continue
        kept[code] = value
    return kept


def _graph_node_from_row(row: sqlite3.Row) -> GraphNode:
    return GraphNode(
        node_id=row["node_id"],
        display_name=row["display_name"],
        normalized_name=row["normalized_name"],
        node_type=row["node_type"],
        in_database=bool(row["in_database"]),
        unified_social_credit_code=row["unified_social_credit_code"],
        is_person=bool(row["is_person"]),
        mention_count=row["mention_count"],
    )


def _contains_name(text: str, candidate: str) -> bool:
    if not candidate:
        return False
    if candidate.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return candidate in text


def _match_rank(match: tuple[str, str, str]) -> tuple[int, bool]:
    _, matched_text, match_type = match
    return len(normalize_company_name(matched_text)), match_type == "legal_name"

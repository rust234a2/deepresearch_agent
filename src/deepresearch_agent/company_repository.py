from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from deepresearch_agent.company_database import SCHEMA_VERSION, normalize_company_name
from deepresearch_agent.company_models import (
    CompanyContact,
    CompanyProfile,
    CompanyRecord,
    CompanyResolution,
    CompanyResolutionCandidate,
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
        record = self.get_by_credit_code(code)
        return record.contact if record is not None else None

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

from __future__ import annotations

import re
import unicodedata

from deepresearch_agent.data_loader import load_supplier_profiles
from deepresearch_agent.state import SupplierResolution


def resolve_supplier(question: str) -> SupplierResolution:
    normalized_question = _normalize(question)
    matches: dict[str, tuple[str, str]] = {}

    for profile in load_supplier_profiles():
        legal_name = profile.company.legal_name
        names = [(legal_name, "legal_name"), *((alias, "alias") for alias in profile.company.aliases)]
        supplier_matches = [
            (name, match_type)
            for name, match_type in names
            if _contains_name(normalized_question, _normalize(name))
        ]
        if supplier_matches:
            matches[legal_name] = max(
                supplier_matches,
                key=lambda item: (len(_normalize(item[0])), item[1] == "legal_name"),
            )

    if not matches:
        return SupplierResolution(status="not_found")
    if len(matches) > 1:
        return SupplierResolution(status="ambiguous", candidates=sorted(matches))

    supplier_name, (matched_text, match_type) = next(iter(matches.items()))
    return SupplierResolution(
        status="resolved",
        supplier_name=supplier_name,
        matched_text=matched_text,
        match_type=match_type,
        candidates=[supplier_name],
    )


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _contains_name(question: str, candidate: str) -> bool:
    if not candidate:
        return False
    if candidate.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])"
        return re.search(pattern, question) is not None
    return candidate in question

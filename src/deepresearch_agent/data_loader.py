from __future__ import annotations

import json
import re
from pathlib import Path

from deepresearch_agent.state import (
    CompanyProfile,
    ComplianceProfile,
    SupplierCapability,
    SupplierDueDiligenceProfile,
)


SUPPLIER_DATA_PATH = Path("data/procurement/suppliers.json")


def load_supplier_profiles(path: str | Path = SUPPLIER_DATA_PATH) -> list[SupplierDueDiligenceProfile]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_supplier_from_fixture(item) for item in payload]


def find_supplier_profile(
    name: str,
    path: str | Path = SUPPLIER_DATA_PATH,
) -> SupplierDueDiligenceProfile:
    normalized = name.casefold()
    for supplier in load_supplier_profiles(path):
        known_names = [supplier.company.legal_name, *supplier.company.aliases]
        if any(candidate.casefold() == normalized for candidate in known_names):
            return supplier
    raise ValueError(f"Unknown supplier: {name}")


def _supplier_from_fixture(item: dict) -> SupplierDueDiligenceProfile:
    return SupplierDueDiligenceProfile(
        company=CompanyProfile(
            legal_name=item["supplier_name"],
            country=item["country"],
            aliases=item.get("aliases", []),
        ),
        capability=SupplierCapability(
            products=item.get("products", []),
            delivery_capacity=item.get("delivery_capacity"),
            production_sites=_extract_production_sites(item.get("delivery_capacity", "")),
            monthly_capacity_units=_extract_monthly_capacity_units(item.get("delivery_capacity", "")),
        ),
        compliance=ComplianceProfile(
            certifications=item.get("certifications", []),
            sanctions_listed=bool(item.get("listed", False)),
            blacklist_listed=bool(item.get("listed", False)),
            listing_reason=item.get("listing_reason") or None,
            risk_summary=item.get("risk_summary") or None,
        ),
    )


def _extract_monthly_capacity_units(text: str) -> int | None:
    match = re.search(r"monthly capacity of ([0-9,]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _extract_production_sites(text: str) -> int | None:
    match = re.search(r"\b(one|two|three|four|five|\d+)\s+manufacturing sites?\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).casefold()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    return words.get(value, int(value) if value.isdigit() else None)

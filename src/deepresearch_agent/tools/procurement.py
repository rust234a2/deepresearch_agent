from __future__ import annotations

import json
from pathlib import Path

from deepresearch_agent.tools.base import RegisteredTool, ToolRegistry


DATA_PATH = Path("data/procurement/suppliers.json")


def _load_suppliers() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _find_supplier(name: str) -> dict:
    normalized = name.lower()
    for supplier in _load_suppliers():
        if supplier["supplier_name"].lower() == normalized:
            return supplier
    raise ValueError(f"Unknown supplier: {name}")


def _extract_supplier_profile(args: dict) -> dict:
    supplier = _find_supplier(args["supplier_name"])
    return {
        "supplier_name": supplier["supplier_name"],
        "country": supplier["country"],
        "products": supplier["products"],
        "certifications": supplier["certifications"],
        "delivery_capacity": supplier["delivery_capacity"],
        "risk_summary": supplier["risk_summary"],
    }


def _check_sanctions_or_blacklist(args: dict) -> dict:
    supplier = _find_supplier(args["company_name"])
    return {
        "company_name": supplier["supplier_name"],
        "listed": supplier["listed"],
        "reason": supplier["listing_reason"] or "No match in local sanctions fixture.",
    }


def build_procurement_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            name="extract_supplier_profile",
            description="Return a structured profile for a supplier from local fixture data.",
            permission_tier="read_public",
            handler=_extract_supplier_profile,
        )
    )
    registry.register(
        RegisteredTool(
            name="check_sanctions_or_blacklist",
            description="Check whether a supplier appears in the local sanctions fixture.",
            permission_tier="read_public",
            handler=_check_sanctions_or_blacklist,
        )
    )
    return registry

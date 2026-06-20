from __future__ import annotations

from deepresearch_agent.data_loader import find_supplier_profile
from deepresearch_agent.tools.base import RegisteredTool, ToolRegistry


def _extract_supplier_profile(args: dict) -> dict:
    supplier = find_supplier_profile(args["supplier_name"])
    return {
        "supplier_name": supplier.company.legal_name,
        "country": supplier.company.country,
        "products": supplier.capability.products,
        "certifications": supplier.compliance.certifications,
        "delivery_capacity": supplier.capability.delivery_capacity,
        "risk_summary": supplier.compliance.risk_summary or "No risk summary in supplier profile.",
    }


def _check_sanctions_or_blacklist(args: dict) -> dict:
    supplier = find_supplier_profile(args["company_name"])
    return {
        "company_name": supplier.company.legal_name,
        "listed": supplier.compliance.sanctions_listed or supplier.compliance.blacklist_listed,
        "reason": supplier.compliance.listing_reason or "No match in local sanctions fixture.",
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

from __future__ import annotations

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.tools.base import RegisteredTool, ToolRegistry


def build_procurement_tool_registry(repository: CompanyRepository) -> ToolRegistry:
    registry = ToolRegistry()

    def get_profile(args: dict) -> dict:
        record = repository.get_by_credit_code(args["credit_code"])
        if record is None:
            raise ValueError(f"Unknown company credit code: {args['credit_code']}")
        return record.profile.model_dump(mode="json")

    def get_contact(args: dict) -> dict:
        contact = repository.get_contact(args["credit_code"])
        if contact is None:
            raise ValueError(f"No contact data for company: {args['credit_code']}")
        return contact.model_dump(mode="json")

    registry.register(
        RegisteredTool(
            name="get_company_profile",
            description="Return source-backed Chinese company registration data.",
            permission_tier="read_private",
            handler=get_profile,
        )
    )
    registry.register(
        RegisteredTool(
            name="get_company_contact",
            description="Return source-backed company contact data.",
            permission_tier="read_private",
            handler=get_contact,
        )
    )
    return registry

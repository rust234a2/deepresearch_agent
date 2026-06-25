from __future__ import annotations

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.ownership_links import find_related_parties
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

    def get_ownership_neighborhood(args: dict) -> dict:
        code = args["credit_code"]
        return {
            "shareholders": [r.model_dump(mode="json") for r in repository.get_shareholders(code)],
            "investments": [r.model_dump(mode="json") for r in repository.get_investments(code)],
        }

    def get_related_parties(args: dict) -> dict:
        code = args["credit_code"]
        return {
            "related_parties": [
                r.model_dump(mode="json") for r in find_related_parties(repository, code)
            ]
        }

    registry.register(
        RegisteredTool(
            name="get_ownership_neighborhood",
            description="Return source-backed direct shareholders and outbound investments.",
            permission_tier="read_private",
            handler=get_ownership_neighborhood,
        )
    )
    registry.register(
        RegisteredTool(
            name="get_related_parties",
            description="Return inferred related parties via shared ownership (clues, not conclusions).",
            permission_tier="read_private",
            handler=get_related_parties,
        )
    )
    return registry

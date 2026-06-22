from __future__ import annotations

from deepresearch_agent.rag.retriever import ScopeRetriever
from deepresearch_agent.tools.base import RegisteredTool, ToolRegistry


def build_scope_tool_registry(retriever: ScopeRetriever) -> ToolRegistry:
    registry = ToolRegistry()

    def search(args: dict) -> dict:
        hits = retriever.search(args["query"], args.get("k", 10))
        return {"hits": [hit.model_dump() for hit in hits]}

    registry.register(
        RegisteredTool(
            name="search_company_scope",
            description="Semantic search over company business scope clauses.",
            permission_tier="read_private",
            handler=search,
        )
    )
    return registry

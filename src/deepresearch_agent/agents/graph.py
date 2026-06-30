from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from deepresearch_agent.agents.nodes import (
    critique_node,
    graph_search_node,
    planner_node,
    researcher_node,
    scope_search_node,
    writer_node,
)
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import DomainPack, load_domain_pack
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


DEFAULT_DATABASE_PATH = Path("data/procurement/derived/companies.sqlite3")
DEFAULT_INDEX_PATH = Path("data/procurement/derived/scope_index.faiss")


def _should_continue(state: ResearchState) -> str:
    if state.missing_dimensions and state.iteration < state.max_iterations:
        return "researcher"
    return "writer"


def build_graph(domain_pack: DomainPack, repository: CompanyRepository, scope_node=None, graph_node=None):
    tools = build_procurement_tool_registry(repository)
    graph = StateGraph(ResearchState)
    graph.add_node(
        "planner",
        lambda state: planner_node(state, domain_pack, repository),
    )
    graph.add_node(
        "researcher",
        lambda state: researcher_node(state, tools, domain_pack),
    )
    graph.add_node("critic", critique_node)
    graph.add_node("writer", lambda state: writer_node(state, domain_pack))
    graph.set_entry_point("planner")

    planner_routes = {"researcher": "researcher", "writer": "writer"}
    if scope_node is not None:
        graph.add_node("scope_search", scope_node)
        graph.add_edge("scope_search", END)
        planner_routes["scope_search"] = "scope_search"
    if graph_node is not None:
        graph.add_node("graph_search", graph_node)
        graph.add_edge("graph_search", END)
        planner_routes["graph_search"] = "graph_search"

    def route_after_planner(state: ResearchState) -> str:
        resolution = state.supplier_resolution
        status = resolution.status if resolution is not None else "not_found"
        if status == "resolved":
            return "researcher"
        if status == "not_found":
            if graph_node is not None:
                return "graph_search"
            if scope_node is not None:
                return "scope_search"
        return "writer"

    graph.add_conditional_edges("planner", route_after_planner, planner_routes)
    graph.add_edge("researcher", "critic")
    graph.add_conditional_edges(
        "critic",
        _should_continue,
        {"researcher": "researcher", "writer": "writer"},
    )
    graph.add_edge("writer", END)
    return graph.compile()


def run_compiled(compiled_graph, question: str, domain: str) -> ResearchState:
    result = compiled_graph.invoke(ResearchState(question=question, domain=domain))
    if isinstance(result, ResearchState):
        return result
    return ResearchState.model_validate(result)


def run_research(
    question: str,
    domain: str = "procurement",
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    index_path: str | Path = DEFAULT_INDEX_PATH,
    enable_scope: bool = False,
    enable_graph: bool = False,
) -> ResearchState:
    domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
    repository = CompanyRepository(database_path)
    scope_node = (
        _build_scope_node(database_path, index_path)
        if enable_scope and not enable_graph
        else None
    )
    graph_node = _build_graph_node(database_path, index_path) if enable_graph else None
    app = build_graph(domain_pack, repository, scope_node=scope_node, graph_node=graph_node)
    return run_compiled(app, question, domain)


def _build_scope_node(database_path: str | Path, index_path: str | Path):
    retriever = None
    try:
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        if Path(index_path).exists():
            retriever = load_scope_retriever(database_path, index_path, BgeEmbedder())
    except Exception:
        retriever = None
    return lambda state: scope_search_node(state, retriever)


def _build_graph_node(database_path: str | Path, index_path: str | Path):
    searcher = None
    try:
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.ownership_graph import load_ownership_graph
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        if Path(index_path).exists():
            retriever = load_scope_retriever(database_path, index_path, BgeEmbedder())
            graph = load_ownership_graph(CompanyRepository(database_path))
            searcher = lambda query: hybrid_search(query, retriever, graph)
    except Exception:
        searcher = None
    return lambda state: graph_search_node(state, searcher)

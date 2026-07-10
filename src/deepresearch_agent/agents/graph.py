from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from deepresearch_agent.agents.nodes import (
    critique_node,
    planner_node,
    researcher_node,
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


def build_graph(
    domain_pack: DomainPack,
    repository: CompanyRepository,
    scope_retriever=None,
    graph_searcher=None,
    llm=None,
    scope_enabled: bool = False,
    graph_enabled: bool = False,
):
    tools = build_procurement_tool_registry(repository)
    graph = StateGraph(ResearchState)
    graph.add_node("planner", lambda state: planner_node(state, domain_pack, repository, llm))
    graph.add_node(
        "researcher",
        lambda state: researcher_node(
            state, tools, domain_pack, scope_retriever, graph_searcher, scope_enabled, graph_enabled
        ),
    )
    graph.add_node("critic", critique_node)
    graph.add_node("writer", lambda state: writer_node(state, domain_pack))
    graph.set_entry_point("planner")
    graph.add_edge("planner", "researcher")
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
    scope_retriever = (
        _build_scope_retriever(database_path, index_path)
        if (enable_scope or enable_graph)
        else None
    )
    graph_searcher = (
        _build_graph_searcher(database_path, scope_retriever) if enable_graph else None
    )
    app = build_graph(
        domain_pack,
        repository,
        scope_retriever=scope_retriever,
        graph_searcher=graph_searcher,
        llm=_build_llm(),
        scope_enabled=enable_scope,
        graph_enabled=enable_graph,
    )
    return run_compiled(app, question, domain)


def _build_scope_retriever(database_path: str | Path, index_path: str | Path):
    try:
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        if Path(index_path).exists():
            return load_scope_retriever(database_path, index_path, BgeEmbedder())
    except Exception:
        return None
    return None


def _build_graph_searcher(database_path: str | Path, scope_retriever):
    if scope_retriever is None:
        return None
    try:
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend.from_env()
        return lambda query: hybrid_search(query, scope_retriever, backend)
    except Exception:
        return None


def _build_llm():
    try:
        from deepresearch_agent.llm.deepseek import build_deepseek_classifier

        return build_deepseek_classifier()
    except Exception:
        return None

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
from deepresearch_agent.observability import configure_tracing, get_tracer, traced_node
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


DEFAULT_DATABASE_PATH = Path("data/procurement/derived/companies.sqlite3")
DEFAULT_INDEX_PATH = Path("data/procurement/derived/scope_index.faiss")


def _should_continue(state: ResearchState) -> str:
    if state.missing_dimensions and state.iteration < state.max_iterations:
        return "researcher"
    return "writer"


def _planner_attrs(state) -> dict:
    resolution = state.supplier_resolution
    attrs: dict = {"resolution_status": resolution.status if resolution is not None else "not_found"}
    if state.complexity is not None:
        attrs["complexity_level"] = state.complexity.level
        attrs["complexity_method"] = state.complexity.method
    return attrs


def _researcher_attrs(state) -> dict:
    return {
        "retrieval_mode": state.retrieval_mode or "",
        "retrieval_available": state.retrieval_available,
        "scope_candidates": len(state.scope_candidates),
        "graph_candidates": len(state.graph_candidates),
        "shared_controllers": len(state.shared_controllers),
    }


def _critic_attrs(state) -> dict:
    return {"missing_dimensions": len(state.missing_dimensions), "iteration": state.iteration}


def _writer_attrs(state) -> dict:
    if state.report is not None:
        report_type = "unresolved" if state.report.supplier_name == "Unknown supplier" else "named"
    elif state.scope_report is not None:
        report_type = "scope"
    elif state.graph_report is not None:
        report_type = "graph"
    else:
        report_type = "none"
    return {"report_type": report_type, "degradations": len(state.degradations)}


def build_graph(
    domain_pack: DomainPack,
    repository: CompanyRepository,
    scope_retriever=None,
    graph_searcher=None,
    llm=None,
    scope_enabled: bool = False,
    graph_enabled: bool = False,
    enable_tracing: bool = False,
):
    tools = build_procurement_tool_registry(repository)
    graph = StateGraph(ResearchState)

    planner_fn = lambda state: planner_node(state, domain_pack, repository, llm)
    researcher_fn = lambda state: researcher_node(
        state, tools, domain_pack, scope_retriever, graph_searcher, scope_enabled, graph_enabled
    )
    critic_fn = critique_node
    writer_fn = lambda state: writer_node(state, domain_pack)

    if enable_tracing:
        planner_fn = traced_node("planner", planner_fn, _planner_attrs)
        researcher_fn = traced_node("researcher", researcher_fn, _researcher_attrs)
        critic_fn = traced_node("critic", critic_fn, _critic_attrs)
        writer_fn = traced_node("writer", writer_fn, _writer_attrs)

    graph.add_node("planner", planner_fn)
    graph.add_node("researcher", researcher_fn)
    graph.add_node("critic", critic_fn)
    graph.add_node("writer", writer_fn)
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
    enable_tracing: bool = False,
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
    if enable_tracing:
        configure_tracing()
    app = build_graph(
        domain_pack,
        repository,
        scope_retriever=scope_retriever,
        graph_searcher=graph_searcher,
        llm=_build_llm(),
        scope_enabled=enable_scope,
        graph_enabled=enable_graph,
        enable_tracing=enable_tracing,
    )
    tracer = get_tracer() if enable_tracing else None
    if tracer is not None:
        with tracer.start_as_current_span("research") as span:
            span.set_attribute("question", question)
            span.set_attribute("domain", domain)
            return run_compiled(app, question, domain)
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

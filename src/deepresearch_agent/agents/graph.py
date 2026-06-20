from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from deepresearch_agent.agents.nodes import critique_node, planner_node, researcher_node, writer_node
from deepresearch_agent.domain import DomainPack, load_domain_pack
from deepresearch_agent.retrieval.local import LocalDocumentRetriever
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


def _should_continue(state: ResearchState) -> str:
    if state.missing_dimensions and state.iteration < state.max_iterations:
        return "researcher"
    return "writer"


def _route_after_planner(state: ResearchState) -> str:
    if state.supplier_resolution is not None and state.supplier_resolution.status == "resolved":
        return "researcher"
    return "writer"


def build_graph(domain_pack: DomainPack):
    retriever = LocalDocumentRetriever("data/procurement/documents")
    tools = build_procurement_tool_registry()

    graph = StateGraph(ResearchState)
    graph.add_node("planner", lambda state: planner_node(state, domain_pack=domain_pack))
    graph.add_node(
        "researcher",
        lambda state: researcher_node(
            state,
            retriever=retriever,
            tools=tools,
            domain_pack=domain_pack,
        ),
    )
    graph.add_node("critic", critique_node)
    graph.add_node("writer", lambda state: writer_node(state, domain_pack=domain_pack))

    graph.set_entry_point("planner")
    graph.add_conditional_edges(
        "planner",
        _route_after_planner,
        {
            "researcher": "researcher",
            "writer": "writer",
        },
    )
    graph.add_edge("researcher", "critic")
    graph.add_conditional_edges(
        "critic",
        _should_continue,
        {
            "researcher": "researcher",
            "writer": "writer",
        },
    )
    graph.add_edge("writer", END)
    return graph.compile()


def run_research(question: str, domain: str = "procurement") -> ResearchState:
    domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
    app = build_graph(domain_pack)
    initial_state = ResearchState(question=question, domain=domain)
    result = app.invoke(initial_state)
    if isinstance(result, ResearchState):
        return result
    return ResearchState.model_validate(result)

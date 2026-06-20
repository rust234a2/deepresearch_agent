from pathlib import Path

from deepresearch_agent.agents.graph import _should_continue, run_research
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.state import ResearchState


def test_graph_generates_report_for_approved_supplier():
    final_state = run_research("Assess ACME Sensors for industrial sensor procurement")
    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert final_state.report is not None
    assert final_state.report.supplier_name == "ACME Sensors"
    assert final_state.report.evidence_table
    assert final_state.iteration >= 1
    assert [item.dimension for item in final_state.plan] == domain_pack.research_dimensions


def test_graph_rejects_known_restricted_supplier():
    final_state = run_research("Assess Northstar Components for control module procurement")

    assert final_state.report is not None
    assert final_state.report.recommendation == "reject"
    assert any("Human review required" in question for question in final_state.report.open_questions)


def test_router_stops_when_iteration_budget_is_exhausted():
    state = ResearchState(
        question="Assess ACME Sensors",
        domain="procurement",
        missing_dimensions=["compliance"],
        iteration=1,
        max_iterations=3,
    )

    assert _should_continue(state) == "researcher"

    state.iteration = 3

    assert _should_continue(state) == "writer"

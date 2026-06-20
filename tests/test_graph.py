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


def test_graph_deduplicates_evidence_and_deterministic_tool_calls_across_retries():
    final_state = run_research("Assess ACME Sensors for industrial sensor procurement")

    evidence_keys = [
        (item.dimension, item.citation.source_id, item.claim)
        for item in final_state.evidence
    ]
    trace_keys = [
        (item.tool_name, tuple(sorted(item.args.items())))
        for item in final_state.trace
    ]

    assert len(evidence_keys) == len(set(evidence_keys))
    assert len(trace_keys) == len(set(trace_keys))


def test_graph_rejects_known_restricted_supplier():
    final_state = run_research("Assess Northstar Components for control module procurement")

    assert final_state.report is not None
    assert final_state.report.recommendation == "reject"
    assert any("Human review required" in question for question in final_state.report.open_questions)


def test_graph_returns_insufficient_evidence_for_unknown_supplier():
    final_state = run_research("Assess Missing Supplier for control module procurement")

    assert final_state.report is not None
    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table == []
    assert final_state.iteration == 0
    assert any("supplier" in question.lower() for question in final_state.report.open_questions)


def test_graph_requests_clarification_for_ambiguous_supplier_question():
    final_state = run_research("Compare ACME with Northstar for this purchase")

    assert final_state.report is not None
    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table == []
    assert "ACME Sensors" in final_state.report.summary
    assert "Northstar Components" in final_state.report.summary


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

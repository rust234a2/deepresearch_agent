from deepresearch_agent.agents.graph import run_research


def test_graph_generates_report_for_approved_supplier():
    final_state = run_research("Assess ACME Sensors for industrial sensor procurement")

    assert final_state.report is not None
    assert final_state.report.supplier_name == "ACME Sensors"
    assert final_state.report.evidence_table
    assert final_state.iteration >= 1


def test_graph_rejects_known_restricted_supplier():
    final_state = run_research("Assess Northstar Components for control module procurement")

    assert final_state.report is not None
    assert final_state.report.recommendation == "reject"

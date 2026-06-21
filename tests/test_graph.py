from pathlib import Path

from deepresearch_agent.agents.graph import _should_continue, run_research
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.state import ResearchState


def test_graph_generates_source_backed_company_report(company_database_path):
    final_state = run_research(
        "核验示例科技股份有限公司的工商和经营范围",
        database_path=company_database_path,
    )
    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert final_state.report.supplier_name == "示例科技股份有限公司"
    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table
    assert {item.dimension for item in final_state.evidence} == set(
        domain_pack.research_dimensions
    )
    assert "工业设备制造" in " ".join(item.claim for item in final_state.evidence)


def test_graph_deduplicates_evidence_and_tool_calls(company_database_path):
    final_state = run_research(
        "核验示例科技股份有限公司",
        database_path=company_database_path,
    )

    evidence_keys = [
        (item.dimension, item.citation.source_id, item.claim) for item in final_state.evidence
    ]
    trace_keys = [
        (item.tool_name, tuple(sorted(item.args.items()))) for item in final_state.trace
    ]
    assert len(evidence_keys) == len(set(evidence_keys))
    assert len(trace_keys) == len(set(trace_keys))


def test_graph_returns_insufficient_evidence_for_unknown_company(company_database_path):
    final_state = run_research("核验不存在企业", database_path=company_database_path)

    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table == []
    assert final_state.iteration == 0


def test_router_stops_when_iteration_budget_is_exhausted():
    state = ResearchState(
        question="核验示例科技股份有限公司",
        domain="procurement",
        missing_dimensions=["contact"],
        iteration=1,
        max_iterations=3,
    )
    assert _should_continue(state) == "researcher"
    state.iteration = 3
    assert _should_continue(state) == "writer"

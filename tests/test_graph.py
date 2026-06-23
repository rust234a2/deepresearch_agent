import sys
from pathlib import Path

import pytest

from deepresearch_agent.agents.graph import _should_continue, run_research
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.state import ResearchState

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


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


def _stub_scope_node(state):
    from deepresearch_agent.state import ScopeSearchReport

    state.scope_report = ScopeSearchReport(
        query=state.question,
        summary="stub",
        candidates=[],
        open_questions=[],
    )
    return state


def test_capability_question_routes_to_scope_when_node_injected(company_database_path):
    from deepresearch_agent.agents.graph import build_graph, run_compiled
    from deepresearch_agent.company_repository import CompanyRepository

    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))
    repository = CompanyRepository(company_database_path)
    app = build_graph(domain_pack, repository, scope_node=_stub_scope_node)

    state = run_compiled(app, "哪些企业能做注塑成型", "procurement")

    assert state.scope_report is not None
    assert state.scope_report.summary == "stub"
    assert state.report is None


def test_named_company_still_routes_to_verify_with_scope_node(company_database_path):
    from deepresearch_agent.agents.graph import build_graph, run_compiled
    from deepresearch_agent.company_repository import CompanyRepository

    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))
    repository = CompanyRepository(company_database_path)
    app = build_graph(domain_pack, repository, scope_node=_stub_scope_node)

    state = run_compiled(app, "核验示例科技股份有限公司", "procurement")

    assert state.report is not None
    assert state.report.supplier_name == "示例科技股份有限公司"
    assert state.scope_report is None


def test_run_research_without_scope_keeps_supplier_report(company_database_path):
    state = run_research("哪些企业能做注塑成型", database_path=company_database_path)

    assert state.scope_report is None
    assert state.report is not None
    assert state.report.recommendation == "insufficient_evidence"


def test_run_research_enable_scope_without_index_returns_unavailable(company_database_path, tmp_path):
    missing_index = tmp_path / "does_not_exist.faiss"

    state = run_research(
        "哪些企业能做注塑成型",
        database_path=company_database_path,
        index_path=missing_index,
        enable_scope=True,
    )

    assert state.scope_report is not None
    assert "不可用" in state.scope_report.summary
    assert state.report is None


@pytest.mark.slow
def test_run_research_scope_search_end_to_end(company_database_path, tmp_path):
    from build_scope_index import build_scope_index
    from deepresearch_agent.rag.embedding import BgeEmbedder

    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, BgeEmbedder())

    state = run_research(
        "哪些企业能做工业设备制造",
        database_path=company_database_path,
        index_path=index_path,
        enable_scope=True,
    )

    assert state.scope_report is not None
    assert state.scope_report.candidates
    assert state.scope_report.recommendation == "insufficient_evidence"
    assert state.report is None

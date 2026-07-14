import sys
from pathlib import Path

import pytest

from deepresearch_agent.agents.graph import (
    _should_continue,
    build_graph,
    run_compiled,
    run_research,
)
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.state import ResearchState

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

DOMAIN_PACK = load_domain_pack(Path("domains/procurement/domain.yaml"))


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """强制 run_research 走确定性启发式，测试不依赖 DeepSeek 网络。"""
    from deepresearch_agent.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "_build_llm", lambda: None)


def test_graph_generates_source_backed_company_report(company_database_path):
    final_state = run_research(
        "核验示例科技股份有限公司的工商和经营范围",
        database_path=company_database_path,
    )
    assert final_state.report.supplier_name == "示例科技股份有限公司"
    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table
    assert {item.dimension for item in final_state.evidence} == {
        "company_identity", "registration", "industry_and_business_scope"
    }
    assert "工业设备制造" in " ".join(item.claim for item in final_state.evidence)


def test_graph_deduplicates_evidence_and_tool_calls(company_database_path):
    final_state = run_research("核验示例科技股份有限公司", database_path=company_database_path)
    evidence_keys = [
        (item.dimension, item.citation.source_id, item.claim) for item in final_state.evidence
    ]
    trace_keys = [(item.tool_name, tuple(sorted(item.args.items()))) for item in final_state.trace]
    assert len(evidence_keys) == len(set(evidence_keys))
    assert len(trace_keys) == len(set(trace_keys))


def test_unknown_company_without_retrieval_is_unresolved_report(company_database_path):
    final_state = run_research("核验不存在企业", database_path=company_database_path)
    assert final_state.report is not None
    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table == []
    assert final_state.iteration == 0
    assert final_state.scope_report is None
    assert final_state.graph_report is None


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


class _ScopeHit:
    def __init__(self, code, name, text, score):
        self.unified_social_credit_code = code
        self.legal_name = name
        self.section_label = None
        self.text = text
        self.score = score


class _ScopeRetriever:
    def search(self, query, k):
        return [_ScopeHit("X", "示例科技股份有限公司", "工业设备制造", 0.95)]


def test_capability_question_routes_to_scope_when_retriever_injected(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, scope_retriever=_ScopeRetriever(), scope_enabled=True
    )
    state = run_compiled(app, "哪些企业能做注塑成型", "procurement")
    assert state.scope_report is not None
    assert state.scope_report.candidates
    assert state.report is None


def test_named_company_verifies_even_with_scope_retriever(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, scope_retriever=_ScopeRetriever(), scope_enabled=True
    )
    state = run_compiled(app, "核验示例科技股份有限公司", "procurement")
    assert state.report is not None
    assert state.report.supplier_name == "示例科技股份有限公司"
    assert state.scope_report is None


def _stub_graph_searcher(query):
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext

    return HybridContext(
        query=query,
        seeds=[SeedContext(code="X", name="示例科技股份有限公司", score=0.9, controllers=[], neighbors=[])],
        shared_controllers=[],
    )


def test_relationship_capability_routes_to_graph_when_searcher_injected(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, graph_searcher=_stub_graph_searcher, graph_enabled=True
    )
    state = run_compiled(app, "哪些做注塑的供应商互相关联", "procurement")
    assert state.graph_report is not None
    assert state.graph_report.candidates
    assert state.report is None


def test_named_company_verifies_even_with_graph_searcher(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, graph_searcher=_stub_graph_searcher, graph_enabled=True
    )
    state = run_compiled(app, "核验示例科技股份有限公司", "procurement")
    assert state.report is not None
    assert state.graph_report is None


def test_run_research_without_retrieval_keeps_supplier_report(company_database_path):
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


def test_run_research_enable_graph_without_index_degrades(company_database_path, tmp_path):
    missing_index = tmp_path / "does_not_exist.faiss"
    state = run_research(
        "哪些做注塑的供应商互相关联",
        database_path=company_database_path,
        index_path=missing_index,
        enable_graph=True,
    )
    assert state.graph_report is not None
    assert "不可用" in state.graph_report.summary
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


def test_build_graph_searcher_none_when_neo4j_unavailable(company_database_path, monkeypatch):
    import deepresearch_agent.neo4j_backend as nb
    from deepresearch_agent.agents import graph as graph_module

    def boom(cls):
        raise RuntimeError("neo4j 不可达")

    monkeypatch.setattr(nb.Neo4jBackend, "from_env", classmethod(boom))
    searcher = graph_module._build_graph_searcher(company_database_path, object())
    assert searcher is None


def test_graph_runtime_failure_degrades_to_scope_end_to_end(company_database_path):
    repository = CompanyRepository(company_database_path)

    def boom(query):
        raise RuntimeError("图加载失败")

    app = build_graph(
        DOMAIN_PACK, repository,
        scope_retriever=_ScopeRetriever(), graph_searcher=boom,
        scope_enabled=True, graph_enabled=True,
    )
    state = run_compiled(app, "哪些做注塑的供应商互相关联", "procurement")
    assert state.scope_report is not None
    assert state.scope_report.candidates
    assert "已降级为经营范围检索" in state.scope_report.open_questions[0]
    assert state.graph_report is None
    assert state.report is None

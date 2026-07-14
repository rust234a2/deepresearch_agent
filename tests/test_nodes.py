from pathlib import Path

from deepresearch_agent.agents.nodes import (
    critique_node,
    planner_node,
    researcher_node,
    writer_node,
)
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.graph_retrieval import assemble_subgraph_context
from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend
from deepresearch_agent.ownership_graph import load_ownership_graph
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.base import RegisteredTool, ToolRegistry
from deepresearch_agent.tools.procurement import build_procurement_tool_registry

DOMAIN_PACK = load_domain_pack(Path("domains/procurement/domain.yaml"))


def _repository(company_database_path: Path) -> CompanyRepository:
    return CompanyRepository(company_database_path)


def test_planner_resolves_company_and_creates_source_backed_plan(company_database_path):
    state = ResearchState(question="核验示例科技股份有限公司", domain="procurement")

    updated = planner_node(state, DOMAIN_PACK, _repository(company_database_path))

    assert updated.supplier_name == "示例科技股份有限公司"
    assert updated.company_credit_code == "91330000123456789X"
    assert [item.dimension for item in updated.plan] == DOMAIN_PACK.research_dimensions


def test_planner_resolves_alias_to_legal_name(company_database_path):
    state = ResearchState(question="核验示例设备有限公司", domain="procurement")

    updated = planner_node(state, DOMAIN_PACK, _repository(company_database_path))

    assert updated.supplier_name == "示例科技股份有限公司"
    assert updated.supplier_resolution.status == "resolved"


def test_planner_limits_dimensions_to_the_question(company_database_path):
    state = ResearchState(
        question="核验示例科技股份有限公司的工商和经营范围", domain="procurement"
    )

    updated = planner_node(state, DOMAIN_PACK, _repository(company_database_path))

    assert [item.dimension for item in updated.plan] == [
        "company_identity",
        "registration",
        "industry_and_business_scope",
    ]


def test_researcher_skips_unrequested_tools(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(
            question="核验示例科技股份有限公司的工商和经营范围", domain="procurement"
        ),
        DOMAIN_PACK,
        repository,
    )

    updated = researcher_node(state, build_procurement_tool_registry(repository), DOMAIN_PACK)

    assert {item.dimension for item in updated.evidence} == {
        "company_identity",
        "registration",
        "industry_and_business_scope",
    }
    assert [item.tool_name for item in updated.trace] == ["get_company_profile"]


def test_planner_does_not_plan_unknown_company(company_database_path):
    state = ResearchState(question="核验不存在企业", domain="procurement")

    updated = planner_node(state, DOMAIN_PACK, _repository(company_database_path))

    assert updated.supplier_name is None
    assert updated.plan == []
    assert updated.supplier_resolution.status == "not_found"


def test_researcher_collects_all_source_backed_dimensions(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )

    updated = researcher_node(
        state,
        build_procurement_tool_registry(repository),
        DOMAIN_PACK,
    )

    assert {item.dimension for item in updated.evidence} == set(DOMAIN_PACK.research_dimensions)
    assert any("工业设备制造" in item.claim for item in updated.evidence)
    assert all(item.citation.source_id == "company:91330000123456789X" for item in updated.evidence)
    assert {item.tool_name for item in updated.trace} == {
        "get_company_profile",
        "get_company_contact",
        "get_ownership_neighborhood",
        "get_related_parties",
    }


def test_researcher_emits_ownership_fallback_when_no_ownership_data(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )

    updated = researcher_node(state, build_procurement_tool_registry(repository), DOMAIN_PACK)

    ownership = [e for e in updated.evidence if e.dimension == "ownership_structure"]
    related = [e for e in updated.evidence if e.dimension == "related_parties"]
    assert len(ownership) == 1 and "数据源未提供" in ownership[0].claim
    assert len(related) == 1 and "数据源未发现" in related[0].claim


def test_researcher_emits_related_parties_with_low_confidence_clues(tmp_path):
    from deepresearch_agent.company_database import build_company_database

    fixtures = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        fixtures / "companies.csv",
        fixtures / "contacts.csv",
        database_path,
        shareholders_csv=fixtures / "shareholders.csv",
        investments_csv=fixtures / "investments.csv",
    )
    repository = _repository(database_path)
    state = planner_node(
        ResearchState(question="核验甲公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )

    updated = researcher_node(state, build_procurement_tool_registry(repository), DOMAIN_PACK)

    related = [e for e in updated.evidence if e.dimension == "related_parties"]
    assert related
    person = next(e for e in related if "共同自然人" in e.claim)
    assert person.confidence == 0.2
    assert "经由自然人" in person.claim
    ownership = [e for e in updated.evidence if e.dimension == "ownership_structure"]
    assert any("股东" in e.claim or "对外投资" in e.claim for e in ownership)


def test_researcher_respects_tool_allowlist(company_database_path):
    repository = _repository(company_database_path)
    restricted = DOMAIN_PACK.model_copy(update={"allowed_tools": []})
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        restricted,
        repository,
    )

    updated = researcher_node(state, build_procurement_tool_registry(repository), restricted)

    assert updated.evidence == []
    assert updated.trace == []
    assert updated.iteration == 1


def test_researcher_records_unavailable_tool(company_database_path):
    repository = _repository(company_database_path)
    profile_only = DOMAIN_PACK.model_copy(update={"allowed_tools": ["get_company_profile"]})
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        profile_only,
        repository,
    )

    updated = researcher_node(state, ToolRegistry(), profile_only)

    assert updated.evidence == []
    assert updated.trace[0].tool_name == "get_company_profile"
    assert updated.trace[0].status == "error"
    assert updated.trace[0].error is not None
    assert "get_company_profile" in updated.trace[0].error


def test_researcher_captures_tool_error_message(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )
    registry = ToolRegistry()

    def boom(args: dict) -> dict:
        raise ValueError("db exploded")

    registry.register(
        RegisteredTool(
            name="get_company_profile",
            description="raises for test",
            permission_tier="read_private",
            handler=boom,
        )
    )

    updated = researcher_node(state, registry, DOMAIN_PACK)

    profile_trace = next(item for item in updated.trace if item.tool_name == "get_company_profile")
    assert profile_trace.status == "error"
    assert profile_trace.error is not None
    assert "db exploded" in profile_trace.error


def test_critic_identifies_missing_source_dimension(company_database_path):
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        DOMAIN_PACK,
        _repository(company_database_path),
    )

    updated = critique_node(state)

    assert "company_identity" in updated.missing_dimensions


def test_writer_never_approves_from_registration_data_only(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )
    state = researcher_node(state, build_procurement_tool_registry(repository), DOMAIN_PACK)
    state = critique_node(state)

    updated = writer_node(state, DOMAIN_PACK)

    assert updated.report.recommendation == "insufficient_evidence"
    assert updated.report.evidence_table
    assert any("不能据此作出采购批准" in risk for risk in updated.report.risks)
    assert not any("未发现风险" in risk for risk in updated.report.risks)


_LINKS = Path("tests/fixtures/procurement/ownership_links")


def _ownership_graph(tmp_path):
    from deepresearch_agent.company_database import build_company_database

    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        _LINKS / "companies.csv",
        _LINKS / "contacts.csv",
        database_path,
        shareholders_csv=_LINKS / "shareholders.csv",
        investments_csv=_LINKS / "investments.csv",
    )
    return load_ownership_graph(CompanyRepository(database_path))


def test_research_state_has_c2_retrieval_fields():
    state = ResearchState(question="q", domain="procurement")
    assert state.complexity is None
    assert state.retrieval_mode is None
    assert state.retrieval_available is True
    assert state.scope_candidates == []
    assert state.graph_candidates == []
    assert state.shared_controllers == []


def test_planner_sets_complexity_from_llm(company_database_path):
    state = ResearchState(question="随便问问", domain="procurement")
    updated = planner_node(
        state, DOMAIN_PACK, _repository(company_database_path), llm=lambda q: "complex"
    )
    assert updated.complexity is not None
    assert updated.complexity.level == "complex"
    assert updated.complexity.method == "llm"


def test_planner_complexity_falls_back_to_heuristic(company_database_path):
    state = ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement")
    updated = planner_node(state, DOMAIN_PACK, _repository(company_database_path))
    assert updated.complexity is not None
    assert updated.complexity.method == "heuristic"
    assert updated.complexity.level == "medium"


class _ScopeHit:
    def __init__(self, code, name, text, score):
        self.unified_social_credit_code = code
        self.legal_name = name
        self.section_label = None
        self.text = text
        self.score = score


class _ScopeRetriever:
    def search(self, query, k):
        return [
            _ScopeHit("X", "示例科技股份有限公司", "工业设备制造", 0.95),
            _ScopeHit("X", "示例科技股份有限公司", "工业设备销售", 0.80),
        ]


def test_researcher_scope_mode_groups_candidates(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="工业设备制造", domain="procurement"), DOMAIN_PACK, repository
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_ScopeRetriever(), scope_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert len(updated.scope_candidates) == 1
    assert updated.scope_candidates[0].unified_social_credit_code == "X"
    assert updated.scope_candidates[0].top_score == 0.95
    assert updated.retrieval_available is True


def test_researcher_scope_mode_unavailable_when_retriever_missing(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些企业能做注塑成型", domain="procurement"), DOMAIN_PACK, repository
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK, scope_retriever=None, scope_enabled=True
    )
    assert updated.retrieval_mode == "scope"
    assert updated.retrieval_available is False
    assert updated.scope_candidates == []


def test_researcher_graph_mode_builds_candidates_and_shared(tmp_path, company_database_path):
    graph = _ownership_graph(tmp_path)
    seeds = ["91110000000000111A", "91110000000000222B", "91110000000000333C"]
    searcher = lambda query: assemble_subgraph_context(InMemoryOwnershipBackend(graph), seeds, query=query)
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK, graph_searcher=searcher, graph_enabled=True
    )
    assert updated.retrieval_mode == "graph"
    names = {c.legal_name for c in updated.graph_candidates}
    assert {"甲公司", "乙公司", "丙公司"} <= names
    shared = {s.controller_name: s for s in updated.shared_controllers}
    assert shared["共同控股集团有限公司"].via_person is False
    assert shared["张三"].via_person is True
    assert shared["张三"].note == "经自然人节点关联"


def test_researcher_graph_mode_falls_back_to_scope_when_searcher_absent(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_ScopeRetriever(), scope_enabled=True,
        graph_searcher=None, graph_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert len(updated.scope_candidates) == 1


def test_researcher_ambiguous_is_unresolved_and_does_not_retrieve(company_database_path):
    from deepresearch_agent.company_models import CompanyResolution

    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="核验示例", domain="procurement"), DOMAIN_PACK, repository
    )
    if state.supplier_resolution.status != "ambiguous":
        state.supplier_resolution = CompanyResolution(status="ambiguous", candidates=[])
        state.supplier_name = None
    updated = researcher_node(state, ToolRegistry(), DOMAIN_PACK)
    assert updated.retrieval_mode == "unresolved"
    assert updated.evidence == []
    assert updated.scope_candidates == []
    assert updated.graph_candidates == []


def test_writer_scope_report_from_candidates(company_database_path):
    from deepresearch_agent.state import Citation, Evidence, ScopeCandidate

    state = ResearchState(question="工业设备制造", domain="procurement")
    state.retrieval_mode = "scope"
    state.scope_candidates = [
        ScopeCandidate(
            unified_social_credit_code="X",
            legal_name="示例科技股份有限公司",
            matched_clauses=[
                Evidence(
                    claim="工业设备制造",
                    dimension="business_scope_match",
                    confidence=0.9,
                    citation=Citation(
                        source_id="company:X", title="t", url="local://companies/X", snippet="工业设备制造"
                    ),
                )
            ],
            top_score=0.9,
        )
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.scope_report is not None
    assert updated.scope_report.recommendation == "insufficient_evidence"
    assert "候选" in updated.scope_report.summary
    assert updated.report is None


def test_writer_scope_report_unavailable(company_database_path):
    state = ResearchState(question="哪些企业能做注塑成型", domain="procurement")
    state.retrieval_mode = "scope"
    state.retrieval_available = False
    updated = writer_node(state, DOMAIN_PACK)
    assert "不可用" in updated.scope_report.summary
    assert updated.scope_report.candidates == []


def test_writer_graph_report_from_findings(company_database_path):
    from deepresearch_agent.state import GraphSearchCandidate, SharedControllerFinding

    state = ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement")
    state.retrieval_mode = "graph"
    state.graph_candidates = [
        GraphSearchCandidate(
            unified_social_credit_code="A", legal_name="甲公司", top_score=0.9,
            ultimate_controllers=["共同控股集团有限公司"],
        )
    ]
    state.shared_controllers = [
        SharedControllerFinding(
            controller_name="张三", controlled_companies=["甲公司", "乙公司"],
            via_person=True, note="经自然人节点关联",
        )
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.graph_report is not None
    assert updated.graph_report.recommendation == "insufficient_evidence"
    assert "共享关联" in updated.graph_report.summary
    assert "接入制裁和监管名单数据。" in updated.graph_report.open_questions
    assert updated.report is None


def test_writer_graph_report_unavailable(company_database_path):
    state = ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement")
    state.retrieval_mode = "graph"
    state.retrieval_available = False
    updated = writer_node(state, DOMAIN_PACK)
    assert "不可用" in updated.graph_report.summary
    assert updated.graph_report.candidates == []


def test_research_state_has_degradations_field():
    state = ResearchState(question="q", domain="procurement")
    assert state.degradations == []


def test_retrieve_graph_returns_error_string_on_exception():
    from deepresearch_agent.agents.nodes import _retrieve_graph

    state = ResearchState(question="q", domain="procurement")

    def boom(query):
        raise RuntimeError("图加载失败")

    err = _retrieve_graph(state, boom)
    assert err is not None and "图加载失败" in err
    assert state.retrieval_available is False


def test_retrieve_graph_returns_none_on_missing_and_success():
    from deepresearch_agent.agents.nodes import _retrieve_graph
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext

    missing_state = ResearchState(question="q", domain="procurement")
    assert _retrieve_graph(missing_state, None) is None
    assert missing_state.retrieval_available is False

    ok_state = ResearchState(question="q", domain="procurement")

    def searcher(query):
        return HybridContext(
            query=query,
            seeds=[SeedContext(code="X", name="示例", score=0.9, controllers=[], neighbors=[])],
            shared_controllers=[],
        )

    assert _retrieve_graph(ok_state, searcher) is None
    assert len(ok_state.graph_candidates) == 1


def test_researcher_graph_runtime_failure_degrades_to_scope(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )

    def boom(query):
        raise RuntimeError("图加载失败")

    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_ScopeRetriever(), graph_searcher=boom,
        scope_enabled=True, graph_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert len(updated.scope_candidates) == 1
    assert updated.retrieval_available is True
    assert len(updated.degradations) == 1
    assert "已降级为经营范围检索" in updated.degradations[0]
    assert "图加载失败" in updated.degradations[0]


def test_researcher_graph_runtime_failure_without_scope_records_no_path(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )

    def boom(query):
        raise RuntimeError("图加载失败")

    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=None, graph_searcher=boom,
        scope_enabled=False, graph_enabled=True,
    )
    assert updated.retrieval_mode == "graph"
    assert updated.retrieval_available is False
    assert len(updated.degradations) == 1
    assert "无可用降级路径" in updated.degradations[0]


def test_researcher_scope_runtime_failure_records_degradation(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些企业能做注塑成型", domain="procurement"),
        DOMAIN_PACK, repository,
    )

    class _BoomRetriever:
        def search(self, query, k):
            raise RuntimeError("faiss 索引损坏")

    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_BoomRetriever(), scope_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert updated.retrieval_available is False
    assert len(updated.degradations) == 1
    assert "经营范围检索运行时失败" in updated.degradations[0]


def test_researcher_missing_retriever_records_no_degradation(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些企业能做注塑成型", domain="procurement"),
        DOMAIN_PACK, repository,
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK, scope_retriever=None, scope_enabled=True
    )
    assert updated.retrieval_mode == "scope"
    assert updated.retrieval_available is False
    assert updated.degradations == []


def test_writer_scope_report_surfaces_degradations():
    from deepresearch_agent.state import ScopeCandidate

    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "scope"
    state.degradations = ["图检索运行时失败：X，已降级为经营范围检索。"]
    state.scope_candidates = [
        ScopeCandidate(unified_social_credit_code="X", legal_name="甲", matched_clauses=[], top_score=0.9)
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.scope_report.open_questions[0] == "图检索运行时失败：X，已降级为经营范围检索。"


def test_writer_scope_unavailable_surfaces_degradations():
    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "scope"
    state.retrieval_available = False
    state.degradations = ["经营范围检索运行时失败：Y。"]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.scope_report.open_questions[0] == "经营范围检索运行时失败：Y。"


def test_writer_graph_unavailable_surfaces_degradations():
    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "graph"
    state.retrieval_available = False
    state.degradations = ["图检索运行时失败：Z，无可用降级路径。"]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.graph_report.open_questions[0] == "图检索运行时失败：Z，无可用降级路径。"


def test_graph_findings_flag_industry_collusion_note():
    from deepresearch_agent.agents.nodes import _build_graph_findings
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext, SharedController

    context = HybridContext(
        query="q",
        seeds=[
            SeedContext(code="A", name="甲", score=0.9, controllers=[], neighbors=[]),
            SeedContext(code="C", name="丙", score=0.8, controllers=[], neighbors=[]),
        ],
        shared_controllers=[
            SharedController(
                node_id="person:张三", name="张三", controlled_seeds=["A", "C"],
                via_person=True, concentrated_industries=["机床制造"],
            )
        ],
    )
    _candidates, shared = _build_graph_findings(context)
    finding = shared[0]
    assert finding.concentrated_industries == ["机床制造"]
    assert finding.note == "同行业（机床制造）+同控制人"


def test_graph_findings_keep_plain_note_without_concentration():
    from deepresearch_agent.agents.nodes import _build_graph_findings
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext, SharedController

    context = HybridContext(
        query="q",
        seeds=[SeedContext(code="A", name="甲", score=0.9, controllers=[], neighbors=[])],
        shared_controllers=[
            SharedController(
                node_id="ext:集团", name="集团", controlled_seeds=["A", "B"],
                via_person=False, concentrated_industries=[],
            )
        ],
    )
    _candidates, shared = _build_graph_findings(context)
    assert shared[0].concentrated_industries == []
    assert shared[0].note == "经企业股权链关联"


def test_writer_graph_summary_flags_collusion(company_database_path):
    from deepresearch_agent.state import GraphSearchCandidate, SharedControllerFinding

    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "graph"
    state.graph_candidates = [
        GraphSearchCandidate(
            unified_social_credit_code="A", legal_name="甲", top_score=0.9, ultimate_controllers=[]
        )
    ]
    state.shared_controllers = [
        SharedControllerFinding(
            controller_name="张三", controlled_companies=["甲", "丙"], via_person=True,
            note="同行业（机床制造）+同控制人",
            concentrated_industries=["机床制造"],
        )
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert "同行业+同控制人" in updated.graph_report.summary

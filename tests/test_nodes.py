from pathlib import Path

from deepresearch_agent.agents.nodes import critique_node, planner_node, researcher_node, writer_node
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
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
    assert "须人工复核" in person.claim
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


def test_scope_search_node_returns_unavailable_when_retriever_missing():
    from deepresearch_agent.agents.nodes import scope_search_node

    state = ResearchState(question="哪些企业能做注塑成型", domain="procurement")
    updated = scope_search_node(state, None)

    assert updated.scope_report is not None
    assert updated.scope_report.recommendation == "insufficient_evidence"
    assert updated.scope_report.candidates == []
    assert "不可用" in updated.scope_report.summary


def test_scope_search_node_groups_hits_into_candidates():
    from deepresearch_agent.agents.nodes import scope_search_node

    class _Hit:
        def __init__(self, code, name, text, score):
            self.unified_social_credit_code = code
            self.legal_name = name
            self.section_label = None
            self.text = text
            self.score = score

    class _Retriever:
        def search(self, query, k):
            return [
                _Hit("X", "示例科技股份有限公司", "工业设备制造", 0.95),
                _Hit("X", "示例科技股份有限公司", "工业设备销售", 0.80),
            ]

    state = ResearchState(question="工业设备制造", domain="procurement")
    updated = scope_search_node(state, _Retriever())

    report = updated.scope_report
    assert report is not None
    assert report.recommendation == "insufficient_evidence"
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.unified_social_credit_code == "X"
    assert candidate.top_score == 0.95
    assert [ev.claim for ev in candidate.matched_clauses] == ["工业设备制造", "工业设备销售"]
    assert candidate.matched_clauses[0].dimension == "business_scope_match"
    assert candidate.matched_clauses[0].citation.url == "local://companies/X"


def test_scope_search_node_reports_no_matches_when_empty():
    from deepresearch_agent.agents.nodes import scope_search_node

    class _Empty:
        def search(self, query, k):
            return []

    state = ResearchState(question="完全不相关的查询", domain="procurement")
    updated = scope_search_node(state, _Empty())

    assert updated.scope_report.candidates == []
    assert "未检索到" in updated.scope_report.summary


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

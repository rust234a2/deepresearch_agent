from pathlib import Path

from deepresearch_agent.agents.nodes import critique_node, planner_node, researcher_node, writer_node
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.base import ToolRegistry
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


def test_researcher_collects_six_source_backed_dimensions(company_database_path):
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
    }


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

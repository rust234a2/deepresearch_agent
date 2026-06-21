from pathlib import Path

from deepresearch_agent.domain import load_domain_pack


def test_load_procurement_domain_pack_uses_source_backed_dimensions():
    pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert pack.research_dimensions == [
        "company_identity",
        "registration",
        "capital",
        "industry_and_business_scope",
        "enterprise_scale",
        "contact",
    ]
    assert pack.allowed_tools == ["get_company_profile", "get_company_contact"]


def test_domain_pack_does_not_claim_unsupported_compliance_evidence():
    pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert pack.hitl_policy.high_risk_recommendation is False
    assert pack.hitl_policy.missing_compliance_evidence is False

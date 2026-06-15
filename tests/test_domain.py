from pathlib import Path

from deepresearch_agent.domain import load_domain_pack


def test_load_procurement_domain_pack():
    pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert pack.name == "procurement"
    assert "supplier_profile" in pack.research_dimensions
    assert "search_supplier_docs" in pack.allowed_tools
    assert pack.report_sections[0] == "Executive Summary"


def test_domain_pack_defines_hitl_policy():
    pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert pack.hitl_policy.high_risk_recommendation is True
    assert pack.hitl_policy.missing_compliance_evidence is True

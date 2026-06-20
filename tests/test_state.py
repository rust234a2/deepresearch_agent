from deepresearch_agent.state import (
    Citation,
    CompanyProfile,
    ComplianceProfile,
    Evidence,
    FinancialProfile,
    ProcurementHistory,
    ResearchState,
    SupplierCapability,
    SupplierDueDiligenceProfile,
    SupplierReport,
)


def test_research_state_defaults():
    state = ResearchState(
        question="Assess ACME Sensors for industrial sensor procurement",
        domain="procurement",
    )

    assert state.question.startswith("Assess ACME")
    assert state.domain == "procurement"
    assert state.iteration == 0
    assert state.max_iterations == 3
    assert state.plan == []
    assert state.evidence == []
    assert state.trace == []


def test_evidence_requires_citation():
    citation = Citation(
        source_id="supplier_profile:acme-sensors",
        title="ACME Sensors profile",
        url="local://suppliers/acme-sensors",
        snippet="ISO 9001 certified supplier with two manufacturing sites.",
    )
    evidence = Evidence(
        claim="ACME Sensors has quality certification.",
        dimension="compliance",
        confidence=0.82,
        citation=citation,
    )

    assert evidence.citation.source_id == "supplier_profile:acme-sensors"
    assert evidence.dimension == "compliance"


def test_supplier_report_contains_recommendation_and_evidence():
    report = SupplierReport(
        supplier_name="ACME Sensors",
        recommendation="conditional",
        summary="Suitable if delivery capacity is confirmed.",
        risks=["Delivery capacity is not independently verified."],
        evidence_table=[
            Evidence(
                claim="ACME Sensors has ISO 9001 certification.",
                dimension="compliance",
                confidence=0.82,
                citation=Citation(
                    source_id="supplier_profile:acme-sensors",
                    title="ACME Sensors profile",
                    url="local://suppliers/acme-sensors",
                    snippet="ISO 9001 certified supplier.",
                ),
            )
        ],
        open_questions=["Confirm current monthly production capacity."],
    )

    assert report.recommendation == "conditional"
    assert report.evidence_table[0].claim.startswith("ACME")


def test_supplier_due_diligence_profile_models_procurement_company_data():
    profile = SupplierDueDiligenceProfile(
        company=CompanyProfile(
            legal_name="ACME Sensors",
            country="Malaysia",
            registration_id="MY-ACME-001",
            website="https://example.com/acme",
        ),
        capability=SupplierCapability(
            products=["industrial temperature sensor", "pressure sensor"],
            delivery_capacity="Two manufacturing sites; stated monthly capacity of 120000 sensor units.",
            production_sites=2,
            monthly_capacity_units=120000,
        ),
        compliance=ComplianceProfile(
            certifications=["ISO 9001", "RoHS"],
            sanctions_listed=False,
            blacklist_listed=False,
        ),
        financial=FinancialProfile(risk_summary="No public financial fixture in v1."),
        procurement_history=ProcurementHistory(
            approved_supplier=True,
            on_time_delivery_rate=0.97,
            quality_issue_count=1,
        ),
    )

    assert profile.company.legal_name == "ACME Sensors"
    assert profile.capability.monthly_capacity_units == 120000
    assert profile.compliance.certifications == ["ISO 9001", "RoHS"]
    assert profile.procurement_history.on_time_delivery_rate == 0.97


def test_supplier_due_diligence_profile_allows_missing_v1_data():
    profile = SupplierDueDiligenceProfile(
        company=CompanyProfile(legal_name="Private Supplier", country="China"),
        capability=SupplierCapability(products=["control module"]),
        compliance=ComplianceProfile(),
    )

    assert profile.financial.risk_summary is None
    assert profile.procurement_history.approved_supplier is None
    assert profile.compliance.certifications == []

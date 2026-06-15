from deepresearch_agent.state import (
    Citation,
    Evidence,
    ResearchState,
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

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


def test_scope_search_report_defaults_to_insufficient_evidence():
    from deepresearch_agent.state import (
        Citation,
        Evidence,
        ScopeCandidate,
        ScopeSearchReport,
    )

    evidence = Evidence(
        claim="工业设备制造",
        dimension="business_scope_match",
        confidence=0.9,
        citation=Citation(
            source_id="company:X",
            title="示例 经营范围",
            url="local://companies/X",
            snippet="工业设备制造",
        ),
    )
    candidate = ScopeCandidate(
        unified_social_credit_code="X",
        legal_name="示例科技股份有限公司",
        matched_clauses=[evidence],
        top_score=0.9,
    )
    report = ScopeSearchReport(
        query="工业设备制造",
        summary="一家候选",
        candidates=[candidate],
        open_questions=[],
    )

    assert report.recommendation == "insufficient_evidence"
    assert report.candidates[0].legal_name == "示例科技股份有限公司"
    assert report.candidates[0].matched_clauses[0].dimension == "business_scope_match"

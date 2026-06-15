from deepresearch_agent.agents.nodes import critique_node, planner_node, researcher_node, writer_node
from deepresearch_agent.retrieval.local import LocalDocumentRetriever
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


def test_planner_extracts_supplier_and_dimensions():
    state = ResearchState(
        question="Assess ACME Sensors for industrial sensor procurement",
        domain="procurement",
    )

    updated = planner_node(state)

    assert updated.supplier_name == "ACME Sensors"
    assert [item.dimension for item in updated.plan] == [
        "supplier_profile",
        "compliance",
        "delivery_capability",
        "negative_news",
    ]


def test_researcher_collects_evidence():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        )
    )

    updated = researcher_node(
        state,
        retriever=LocalDocumentRetriever("data/procurement/documents"),
        tools=build_procurement_tool_registry(),
    )

    assert updated.evidence
    assert any(item.dimension == "compliance" for item in updated.evidence)
    assert updated.trace


def test_critic_identifies_missing_dimensions_when_evidence_is_empty():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        )
    )

    updated = critique_node(state)

    assert "supplier_profile" in updated.missing_dimensions


def test_writer_creates_report_from_evidence():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        )
    )
    state = researcher_node(
        state,
        retriever=LocalDocumentRetriever("data/procurement/documents"),
        tools=build_procurement_tool_registry(),
    )
    state = critique_node(state)

    updated = writer_node(state)

    assert updated.report is not None
    assert updated.report.supplier_name == "ACME Sensors"
    assert updated.report.recommendation in {"approve", "conditional"}
    assert updated.report.evidence_table

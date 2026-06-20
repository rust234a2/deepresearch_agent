from pathlib import Path

from deepresearch_agent.agents.nodes import critique_node, planner_node, researcher_node, writer_node
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.retrieval.local import LocalDocumentRetriever
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


DOMAIN_PACK = load_domain_pack(Path("domains/procurement/domain.yaml"))


def test_planner_extracts_supplier_and_dimensions():
    state = ResearchState(
        question="Assess ACME Sensors for industrial sensor procurement",
        domain="procurement",
    )

    updated = planner_node(state, domain_pack=DOMAIN_PACK)

    assert updated.supplier_name == "ACME Sensors"
    assert [item.dimension for item in updated.plan] == DOMAIN_PACK.research_dimensions


def test_researcher_collects_evidence():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        ),
        domain_pack=DOMAIN_PACK,
    )

    updated = researcher_node(
        state,
        retriever=LocalDocumentRetriever("data/procurement/documents"),
        tools=build_procurement_tool_registry(),
        domain_pack=DOMAIN_PACK,
    )

    assert updated.evidence
    assert any(item.dimension == "compliance" for item in updated.evidence)
    assert updated.trace
    document_evidence = [item for item in updated.evidence if item.citation.source_id.startswith("doc:")]
    assert all(item.citation.source_id == "doc:acme-sensors" for item in document_evidence)


def test_researcher_respects_domain_tool_allowlist():
    restricted_pack = DOMAIN_PACK.model_copy(update={"allowed_tools": []})
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        ),
        domain_pack=restricted_pack,
    )

    updated = researcher_node(
        state,
        retriever=LocalDocumentRetriever("data/procurement/documents"),
        tools=build_procurement_tool_registry(),
        domain_pack=restricted_pack,
    )

    assert updated.evidence == []
    assert updated.trace == []
    assert updated.iteration == 1


def test_critic_identifies_missing_dimensions_when_evidence_is_empty():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        ),
        domain_pack=DOMAIN_PACK,
    )

    updated = critique_node(state)

    assert "supplier_profile" in updated.missing_dimensions


def test_writer_creates_report_from_evidence():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        ),
        domain_pack=DOMAIN_PACK,
    )
    state = researcher_node(
        state,
        retriever=LocalDocumentRetriever("data/procurement/documents"),
        tools=build_procurement_tool_registry(),
        domain_pack=DOMAIN_PACK,
    )
    state = critique_node(state)

    updated = writer_node(state, domain_pack=DOMAIN_PACK)

    assert updated.report is not None
    assert updated.report.supplier_name == "ACME Sensors"
    assert updated.report.recommendation in {"approve", "conditional"}
    assert updated.report.evidence_table
